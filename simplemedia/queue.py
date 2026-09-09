from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path

import psutil

from .ffmpeg import CREATE_FLAGS, FFmpegInfo
from .filesystem import commit_output, destination, temporary_output
from .models import ACTIVE, TERMINAL, Job, now
from .storage import Store

log = logging.getLogger(__name__)


class Control:
    def __init__(self):
        self.cancel = threading.Event()
        self.process: subprocess.Popen | None = None
        self.suspended: list[psutil.Process] = []
        self.terminated: list[psutil.Process] = []

    def pause(self):
        if self.process is None or self.process.poll() is not None or self.suspended:
            return
        parent = psutil.Process(self.process.pid)
        # Suspend the spawning parent first, then the now-stable descendant set.
        try:
            parent.suspend()
            self.suspended.append(parent)
            for child in parent.children(recursive=True):
                try:
                    child.suspend()
                    self.suspended.append(child)
                except psutil.NoSuchProcess:
                    pass
        except psutil.Error:
            self.resume()
            raise

    def resume(self):
        for process in reversed(self.suspended):
            try:
                process.resume()
            except psutil.NoSuchProcess:
                pass
        self.suspended.clear()

    def stop(self):
        self.cancel.set()
        if self.process is None or self.process.poll() is not None:
            return
        try:
            parent = psutil.Process(self.process.pid)
            # Stop parent from creating another encoder while cancelling.
            if not any(process.pid == parent.pid for process in self.suspended):
                parent.suspend()
            children = parent.children(recursive=True)
            self.terminated = [*children, parent]
            for process in reversed(children):
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
            parent.kill()
        except psutil.NoSuchProcess:
            pass
        finally:
            self.suspended.clear()


class QueueManager:
    def __init__(self, store: Store, ffmpeg: FFmpegInfo | None = None):
        self.store = store
        self.ffmpeg = ffmpeg or FFmpegInfo()
        self.lock = threading.RLock()
        self.jobs = [job for job in store.load_jobs() if not job.archived]
        self.events = queue.Queue()
        self.controls: dict[str, Control] = {}
        self.reserved: set[Path] = set()
        self.closing = False
        self.paused = False
        self.batch_active = False
        self.batch_ids: set[str] = set()
        self.wake = threading.Event()
        for job in self.jobs:
            if job.status in ACTIVE:
                job.status = "Waiting"
                job.warnings.append(
                    "Interrupted by an earlier shutdown; ready to restart from the beginning."
                )
            job.enabled = False
            job.paused = False
            if job.status == "Waiting":
                job.progress = 0
        self.scheduler = threading.Thread(
            target=self._schedule, name="queue-scheduler", daemon=True
        )
        self.scheduler.start()

    def snapshot(self) -> list[Job]:
        with self.lock:
            return [Job.from_dict(job.to_dict()) for job in self.jobs]

    def _save(self, job: Job):
        try:
            self.store.save_job(job)
        except Exception:
            log.exception("Could not persist job %s", job.id)
            self.events.put(
                (
                    "error",
                    "Local history could not be saved. Check free space and application data permissions.",
                )
            )

    def add(self, jobs: list[Job]):
        for job in jobs:
            job.enabled = self.store.settings["auto_start"]
        self.store.save_jobs(jobs)
        with self.lock:
            self.jobs.extend(jobs)
        self.wake.set()

    def start(self, job_id: str | None = None):
        with self.lock:
            self.paused = False
            for job in self.jobs:
                if job_id is None or job.id == job_id:
                    if job.status == "Waiting":
                        job.enabled, job.paused = True, False
                    elif job.status in ACTIVE:
                        self.controls[job.id].resume()
                        job.paused = False
        self.wake.set()

    def pause(self, job_id: str | None = None):
        with self.lock:
            if job_id is None:
                self.paused = True
            for job in self.jobs:
                if (job_id is None or job.id == job_id) and job.status not in TERMINAL:
                    if job.id in self.controls:
                        self.controls[job.id].pause()
                    job.paused = True
        self.wake.set()

    def cancel(self, job_id: str | None = None):
        with self.lock:
            for job in self.jobs:
                if (job_id is None or job.id == job_id) and job.status not in TERMINAL:
                    if job.id in self.controls:
                        self.controls[job.id].stop()
                    else:
                        job.status, job.finished_at = "Cancelled", now()
                        job.enabled, job.paused = False, False
                        self._save(job)
        self.wake.set()

    def retry(self, job_id: str | None = None):
        with self.lock:
            retryable = {"Failed", "Cancelled"} if job_id else {"Failed"}
            for job in self.jobs:
                if (job_id is None or job.id == job_id) and job.status in retryable:
                    job.status, job.error, job.finished_at = "Waiting", "", ""
                    job.progress, job.elapsed, job.eta = 0, 0, None
                    job.output, job.output_size, job.warnings = "", 0, []
                    job.enabled, job.paused = True, False
                    self._save(job)
        self.wake.set()

    def remove(self, job_id: str):
        with self.lock:
            job = next((j for j in self.jobs if j.id == job_id), None)
            if job is None:
                return
            if job.id in self.controls:
                raise ValueError("Cancel this job and wait for it to stop before removing it.")
            self.jobs.remove(job)
            if job.status not in TERMINAL:
                self.store.delete_job(job.id)
            else:
                job.archived = True
                self._save(job)

    def clear_completed(self):
        with self.lock:
            completed = [j for j in self.jobs if j.status == "Completed"]
            for job in completed:
                job.archived = True
            self.store.save_jobs(completed)
            self.jobs[:] = [j for j in self.jobs if j.status != "Completed"]

    def clear_history(self):
        with self.lock:
            self.store.clear_history()
            self.jobs[:] = [j for j in self.jobs if j.status not in TERMINAL]

    def _schedule(self):
        while not self.closing:
            with self.lock:
                if not self.paused:
                    for job in self.jobs:
                        if len(self.controls) >= self.store.settings["max_jobs"]:
                            break
                        if job.status == "Waiting" and job.enabled and not job.paused:
                            control = Control()
                            self.controls[job.id] = control
                            job.status = "Preparing"
                            self.batch_active = True
                            self.batch_ids.add(job.id)
                            self._save(job)
                            threading.Thread(
                                target=self._run,
                                args=(job, control),
                                name=f"encoder-{job.id[:6]}",
                                daemon=True,
                            ).start()
                pending = any(j.status == "Waiting" and j.enabled for j in self.jobs)
                if self.batch_active and not self.controls and not pending:
                    batch = [j.to_dict() for j in self.jobs if j.id in self.batch_ids]
                    self.events.put(("complete", batch))
                    self.batch_active = False
                    self.batch_ids.clear()
            self.wake.wait(0.2)
            self.wake.clear()

    def _run(self, job: Job, control: Control):
        target = temp = None
        ipc_paths = []
        event_stream = error_stream = None
        success = False
        last = time.monotonic()
        try:
            source = Path(job.source)
            if not source.is_file():
                raise FileNotFoundError(
                    "The input file no longer exists. Locate it and add it again."
                )
            job.original_size = source.stat().st_size
            with self.lock:
                target = destination(job, self.reserved)
                self.reserved.add(target)
                job.output = str(target)
            temp = temporary_output(target)
            free = shutil.disk_usage(target.parent).free
            if free < 1024 * 1024:
                raise OSError(
                    "Less than 1 MB is free on the output drive. Free some disk space and retry."
                )
            if free < job.original_size * 1.2:
                job.warnings.append(
                    "Low disk space: the output may not fit. Compression can sometimes increase size."
                )
                self.events.put(("warning", f"Low disk space for {source.name}."))
            with self.lock:
                if control.cancel.is_set():
                    return
                info = asdict(self.ffmpeg)
                info["encoders"] = sorted(info["encoders"])
                ipc_directory = self.store.directory / "workers"
                ipc_directory.mkdir(exist_ok=True)
                for suffix in (".request.json", ".events.jsonl", ".stderr"):
                    fd, name = tempfile.mkstemp(
                        prefix=job.id + "-", suffix=suffix, dir=ipc_directory
                    )
                    os.close(fd)
                    ipc_paths.append(Path(name))
                request_path, events_path, errors_path = ipc_paths
                payload = {"job": job.to_dict(), "target": str(temp), "ffmpeg": info}
                request_path.write_text(json.dumps(payload), encoding="utf-8")
                command = (
                    [sys.executable, "--worker"]
                    if getattr(sys, "frozen", False)
                    else [sys.executable, "-m", "simplemedia", "--worker"]
                )
                command += [
                    "--request",
                    str(request_path),
                    "--events",
                    str(events_path),
                ]
                error_stream = errors_path.open("w", encoding="utf-8")
                event_stream = events_path.open("r", encoding="utf-8")
                control.process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=error_stream,
                    creationflags=CREATE_FLAGS,
                    cwd=None
                    if getattr(sys, "frozen", False)
                    else str(Path(__file__).resolve().parent.parent),
                )
                job.status = "Compressing"
                if job.paused or self.paused:
                    job.paused = True
                    control.pause()
            worker_error = ""
            pending_text = ""
            while True:
                current = time.monotonic()
                exited = control.process.poll() is not None
                pending_text += event_stream.read()
                lines = pending_text.split("\n")
                pending_text = lines.pop()
                with self.lock:
                    if not job.paused:
                        job.elapsed += current - last
                    last = current
                    for line in lines:
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if "progress" in event:
                            job.progress = max(job.progress, min(0.995, float(event["progress"])))
                            job.eta = (
                                job.elapsed * (1 - job.progress) / job.progress
                                if job.progress > 0.01
                                else None
                            )
                        if "warning" in event:
                            job.warnings.append(event["warning"])
                        if "error" in event:
                            worker_error = event["error"]
                        success |= bool(event.get("done"))
                if exited:
                    break
                time.sleep(0.05)
            if control.cancel.is_set():
                return
            if control.process.returncode or not success:
                error_stream.flush()
                with errors_path.open("rb") as reader:
                    reader.seek(max(0, errors_path.stat().st_size - 3000))
                    detail = reader.read().decode("utf-8", errors="replace")
                raise RuntimeError(worker_error or "The encoder stopped unexpectedly. " + detail)
            with self.lock:
                if control.cancel.is_set():
                    return
                if not temp.stat().st_size:
                    raise ValueError("The encoder produced an empty output file.")
                actual = commit_output(temp, target, job.output_options["overwrite"], source)
                job.output, job.output_size = str(actual), actual.stat().st_size
                job.status, job.progress, job.eta = "Completed", 1.0, 0
                if job.output_size > job.original_size:
                    job.warnings.append(
                        "The output is larger than the source. Try lower quality, resizing, or another format."
                    )
        except Exception as error:
            with self.lock:
                job.status = "Failed"
                job.error = str(error)
            log.warning("Job %s failed (%s)", job.id, type(error).__name__)
        finally:
            if control.process:
                if control.process.poll() is None:
                    control.stop()
                    control.process.wait(timeout=10)
                if control.terminated:
                    # Wait off the UI thread for inherited file handles to close.
                    _, alive = psutil.wait_procs(control.terminated, timeout=5)
                    for process in alive:
                        try:
                            process.kill()
                        except psutil.NoSuchProcess:
                            pass
                for stream in (control.process.stdout, control.process.stderr):
                    if stream:
                        stream.close()
            for stream in (event_stream, error_stream):
                if stream:
                    stream.close()
            for path in ipc_paths:
                self._cleanup(path, job.id)
            if temp:
                self._cleanup(temp, job.id)
            with self.lock:
                if control.cancel.is_set():
                    job.status, job.error = (
                        ("Waiting" if self.closing else "Cancelled"),
                        "",
                    )
                    if self.closing:
                        job.progress = 0
                job.finished_at = "" if job.status == "Waiting" else now()
                job.paused, job.enabled = False, False
                self._save(job)
                if target:
                    self.reserved.discard(target)
                self.controls.pop(job.id, None)
            self.wake.set()

    @staticmethod
    def _cleanup(path: Path, job_id: str):
        for _attempt in range(8):
            try:
                path.unlink(missing_ok=True)
                return
            except PermissionError:
                # Windows can release handles shortly after reporting process exit.
                time.sleep(0.05)
            except OSError:
                break
        log.warning("Temporary file cleanup failed for job %s", job_id)

    def shutdown(self):
        self.closing = True
        with self.lock:
            for control in self.controls.values():
                control.stop()
        self.wake.set()
        self.scheduler.join(timeout=3)
        deadline = time.monotonic() + 12
        while self.controls and time.monotonic() < deadline:
            time.sleep(0.05)
