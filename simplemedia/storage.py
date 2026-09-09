from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import tempfile
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .models import Job


def data_directory() -> Path:
    override = os.environ.get("SMC_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "SimpleMediaCompressure"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/SimpleMediaCompressure"
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "SimpleMediaCompressure"
    )


def setup_logging(directory: Path) -> None:
    folder = directory / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        folder / "application.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


DEFAULT_SETTINGS = {
    "theme": "Midnight",
    "start_minimized": False,
    "remember_output": True,
    "auto_start": False,
    "confirm_delete": True,
    "max_jobs": 2,
    "image_quality": 80,
    "video_quality": 65,
    "audio_bitrate": 192,
    "image_format": "webp",
    "video_format": "mp4",
    "audio_format": "mp3",
    "preserve_metadata": False,
    "output_directory": "",
    "ffmpeg_path": "",
}


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.warning = ""
        self.settings = dict(DEFAULT_SETTINGS)
        try:
            loaded = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("Settings must be an object")
            for key, default in DEFAULT_SETTINGS.items():
                value = loaded.get(key, default)
                if type(value) is type(default):
                    self.settings[key] = value
        except FileNotFoundError:
            pass
        except (ValueError, OSError):
            self.warning = "Settings could not be read. Safe defaults were loaded."
        for key, low, high in (
            ("max_jobs", 1, 4),
            ("image_quality", 1, 100),
            ("video_quality", 0, 100),
            ("audio_bitrate", 64, 320),
        ):
            self.settings[key] = max(low, min(high, self.settings[key]))
        for key, choices in {
            "theme": ["Midnight", "Graphite"],
            "image_format": ["webp", "jpg", "png", "tiff", "gif", "bmp"],
            "video_format": ["mp4", "mkv", "mov", "webm"],
            "audio_format": ["mp3", "m4a", "aac", "ogg", "opus", "flac", "wav"],
        }.items():
            if self.settings[key] not in choices:
                self.settings[key] = DEFAULT_SETTINGS[key]
        self.db = sqlite3.connect(directory / "library.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL, finished TEXT NOT NULL)"
        )
        self.db.commit()

    def save_settings(self) -> None:
        with self.lock:
            values = dict(self.settings)
            if not values["remember_output"]:
                values["output_directory"] = ""
            atomic_json(self.directory / "settings.json", values)

    def save_job(self, job: Job) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO jobs VALUES (?, ?, ?)",
                (job.id, json.dumps(job.to_dict()), job.finished_at),
            )

    def save_jobs(self, jobs: list[Job]) -> None:
        records = [(job.id, json.dumps(job.to_dict()), job.finished_at) for job in jobs]
        with self.lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO jobs VALUES (?, ?, ?)", records)

    def load_jobs(self) -> list[Job]:
        with self.lock:
            result = []
            for (data,) in self.db.execute("SELECT data FROM jobs ORDER BY rowid"):
                try:
                    result.append(Job.from_dict(json.loads(data)))
                except (ValueError, TypeError):
                    self.warning = "An unreadable history record was skipped."
            return result

    def delete_job(self, job_id: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def clear_history(self) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM jobs WHERE finished != ''")

    def close(self) -> None:
        with self.lock:
            self.db.close()
