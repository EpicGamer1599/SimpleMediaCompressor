import time
from dataclasses import asdict
from pathlib import Path

import pytest
from PIL import Image

from simplemedia.models import (
    TERMINAL,
    ImageOptions,
    Job,
    OutputOptions,
    VideoOptions,
)
from simplemedia.queue import QueueManager
from simplemedia.storage import Store


def wait_for(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.03)
    raise AssertionError("Timed out waiting for queue state")


def make_job(path, **options):
    return Job(str(path), "image", asdict(ImageOptions(**options)), asdict(OutputOptions()))


@pytest.fixture
def manager(tmp_path):
    store = Store(tmp_path / "data")
    manager = QueueManager(store)
    yield manager
    manager.shutdown()
    store.close()


def test_multiple_jobs_failure_isolation_and_history(manager, tmp_path):
    a = tmp_path / "first & [ユニコード].png"
    b = tmp_path / "second.png"
    bad = tmp_path / "broken.png"
    Image.new("RGB", (100, 100), "red").save(a)
    Image.new("L", (400, 200), 40).save(b)
    bad.write_bytes(b"corrupt")
    jobs = [make_job(p) for p in [a, b, bad, tmp_path / "missing.png"]]
    manager.add(jobs)
    assert all(j.status == "Waiting" for j in jobs)
    manager.start()
    wait_for(lambda: all(j.status in TERMINAL for j in jobs) and not manager.controls)
    assert [j.status for j in jobs] == ["Completed", "Completed", "Failed", "Failed"]
    assert all(Path(j.output).exists() for j in jobs[:2])
    assert "no longer exists" in jobs[3].error
    assert len(manager.store.load_jobs()) == 4
    assert not list(tmp_path.rglob(".smc-*"))
    manager.clear_completed()
    assert len(manager.jobs) == 2
    assert len(manager.store.load_jobs()) == 4


def test_pause_resume_cancel_cleanup(manager, tmp_path):
    source = tmp_path / "large.png"
    Image.effect_noise((2800, 2200), 90).convert("RGB").save(source)
    item = make_job(source, compression=100, quality=95)
    manager.add([item])
    manager.start()
    wait_for(lambda: item.status == "Compressing")
    manager.pause(item.id)
    assert item.paused
    assert manager.controls[item.id].suspended
    progress = item.progress
    time.sleep(0.2)
    assert item.status == "Compressing" and item.progress == progress
    manager.start(item.id)
    assert not item.paused
    manager.pause()
    manager.cancel(item.id)
    wait_for(lambda: item.status == "Cancelled" and not manager.controls)
    assert source.exists()
    assert not list(tmp_path.rglob(".smc-*"))
    assert not list(tmp_path.rglob("large_compressed*"))


def test_waiting_pause_retry_and_remove(manager, tmp_path):
    path = tmp_path / "missing.png"
    item = make_job(path)
    manager.add([item])
    manager.pause()
    time.sleep(0.25)
    assert item.status == "Waiting"
    manager.cancel()
    assert item.status == "Cancelled"
    Image.new("RGB", (40, 30), "blue").save(path)
    manager.retry(item.id)
    manager.start()
    wait_for(lambda: item.status == "Completed" and not manager.controls)
    manager.remove(item.id)
    assert not manager.jobs
    assert manager.store.load_jobs()[0].status == "Completed"
    manager.clear_history()
    assert not manager.store.load_jobs()


def test_missing_ffmpeg(manager, tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"some data")
    item = Job(str(source), "video", asdict(VideoOptions()), asdict(OutputOptions()))
    manager.add([item])
    manager.start()
    wait_for(lambda: item.status == "Failed" and not manager.controls)
    assert "FFmpeg" in item.error and "missing" in item.error


def test_settings_and_pending_jobs_survive_restart(tmp_path):
    directory = tmp_path / "data"
    store = Store(directory)
    store.settings.update(max_jobs=1, image_quality=73, output_directory=str(tmp_path))
    store.save_settings()
    manager = QueueManager(store)
    item = make_job(tmp_path / "pending.png")
    manager.add([item])
    manager.shutdown()
    store.close()
    store = Store(directory)
    manager = QueueManager(store)
    try:
        assert store.settings["image_quality"] == 73
        assert store.settings["max_jobs"] == 1
        assert manager.jobs[0].status == "Waiting"
        assert not manager.jobs[0].enabled
    finally:
        manager.shutdown()
        store.close()


def test_concurrency_limit(manager, tmp_path):
    manager.store.settings["max_jobs"] = 1
    jobs = []
    for i in range(5):
        path = tmp_path / f"{i}.png"
        Image.new("RGB", (200, 100), (i * 20, 40, 80)).save(path)
        jobs.append(make_job(path))
    manager.add(jobs)
    manager.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and any(j.status not in TERMINAL for j in jobs):
        assert len(manager.controls) <= 1
        time.sleep(0.02)
    assert all(j.status == "Completed" for j in jobs)


def test_completed_queue_removal_survives_restart(tmp_path):
    store = Store(tmp_path / "data")
    manager = QueueManager(store)
    item = make_job(tmp_path / "file.png")
    item.status = "Completed"
    item.finished_at = "2026-09-09T00:00:00+00:00"
    manager.add([item])
    manager.clear_completed()
    manager.shutdown()
    store.close()
    store = Store(tmp_path / "data")
    manager = QueueManager(store)
    try:
        assert not manager.jobs
        assert len(store.load_jobs()) == 1
    finally:
        manager.shutdown()
        store.close()


def test_active_shutdown_restores_waiting(tmp_path):
    source = tmp_path / "large.png"
    Image.effect_noise((2400, 1800), 90).convert("RGB").save(source)
    store = Store(tmp_path / "data")
    manager = QueueManager(store)
    item = make_job(source, compression=100, quality=95)
    manager.add([item])
    manager.start()
    wait_for(lambda: item.status == "Compressing")
    manager.pause()
    manager.shutdown()
    assert item.status == "Waiting"
    assert not item.finished_at
    store.close()
    store = Store(tmp_path / "data")
    manager = QueueManager(store)
    try:
        assert manager.jobs[0].status == "Waiting"
        assert not manager.jobs[0].enabled
        assert not list(tmp_path.rglob(".smc-*"))
    finally:
        manager.shutdown()
        store.close()


def test_corrupt_settings_recover(tmp_path):
    (tmp_path / "settings.json").write_text("{broken")
    store = Store(tmp_path)
    assert store.settings["max_jobs"] == 2
    assert store.warning
    store.close()


def test_retry_failed_does_not_restart_cancelled_jobs(manager, tmp_path):
    failed = make_job(tmp_path / "failed.png")
    cancelled = make_job(tmp_path / "cancelled.png")
    failed.status = "Failed"
    cancelled.status = "Cancelled"
    manager.add([failed, cancelled])
    manager.pause()
    manager.retry()
    assert failed.status == "Waiting" and failed.enabled
    assert cancelled.status == "Cancelled" and not cancelled.enabled


def test_failed_overwrite_keeps_existing_output(manager, tmp_path):
    source = tmp_path / "corrupt.png"
    source.write_bytes(b"broken")
    folder = tmp_path / "Compressed"
    folder.mkdir()
    output = folder / "corrupt_compressed.webp"
    output.write_bytes(b"existing output must survive")
    item = make_job(source)
    item.output_options["overwrite"] = True
    manager.add([item])
    manager.start()
    wait_for(lambda: item.status == "Failed" and not manager.controls)
    assert output.read_bytes() == b"existing output must survive"


def test_two_jobs_reserve_different_outputs(manager, tmp_path):
    source = tmp_path / "same.png"
    Image.new("RGB", (90, 70), "red").save(source)
    jobs = [make_job(source), make_job(source)]
    manager.add(jobs)
    manager.start()
    wait_for(lambda: all(j.status in TERMINAL for j in jobs) and not manager.controls)
    assert all(j.status == "Completed" for j in jobs)
    assert jobs[0].output != jobs[1].output


def test_low_disk_space_fails_cleanly(manager, tmp_path, monkeypatch):
    from collections import namedtuple

    source = tmp_path / "image.png"
    Image.new("RGB", (30, 30), "red").save(source)
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr("simplemedia.queue.shutil.disk_usage", lambda path: Usage(1024, 1023, 1))
    item = make_job(source)
    manager.add([item])
    manager.start()
    wait_for(lambda: item.status == "Failed" and not manager.controls)
    assert "disk space" in item.error
    assert source.exists()
    assert not list(tmp_path.rglob(".smc-*"))


@pytest.mark.ffmpeg
def test_ffmpeg_process_tree_pause_and_cancel(manager, tmp_path, ffmpeg_info):
    import psutil

    from simplemedia.ffmpeg import run_capture

    source = tmp_path / "long.mp4"
    generated = run_capture(
        [
            ffmpeg_info.path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30:duration=12",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-y",
            str(source),
        ]
    )
    assert generated.returncode == 0, generated.stderr
    manager.ffmpeg = ffmpeg_info
    item = Job(
        str(source),
        "video",
        asdict(VideoOptions(preset="veryslow", quality=90)),
        asdict(OutputOptions()),
    )
    manager.add([item])
    manager.start()

    def encoder_started():
        control = manager.controls.get(item.id)
        if not control or not control.process:
            return False
        try:
            return any(
                p.name().lower().startswith("ffmpeg")
                for p in psutil.Process(control.process.pid).children(recursive=True)
            )
        except psutil.NoSuchProcess:
            return False

    wait_for(encoder_started)
    manager.pause(item.id)
    processes = list(manager.controls[item.id].suspended)
    assert len(processes) >= 2
    # Windows may report a just-created suspended process as 'running' until
    # loader/kernel work settles. Verify that encoding CPU actually stops.
    time.sleep(0.2)
    before = [process.cpu_times() for process in processes]
    time.sleep(0.3)
    after = [process.cpu_times() for process in processes]
    assert before == after
    manager.start(item.id)
    manager.cancel(item.id)
    wait_for(lambda: item.status == "Cancelled" and not manager.controls)
    assert all(not process.is_running() for process in processes)
    assert not list(tmp_path.rglob(".smc-*"))
