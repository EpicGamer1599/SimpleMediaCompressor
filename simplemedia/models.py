from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus"},
}
ACTIVE = {"Preparing", "Compressing"}
TERMINAL = {"Completed", "Failed", "Cancelled"}


def media_type(path: str | Path) -> str | None:
    return next(
        (
            kind
            for kind, extensions in EXTENSIONS.items()
            if Path(path).suffix.lower() in extensions
        ),
        None,
    )


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class ImageOptions:
    format: str = "webp"
    compression: int = 40
    quality: int = 80
    resize: bool = False
    width: int = 1920
    height: int = 1080
    aspect: bool = True
    strip_metadata: bool = True
    progressive: bool = True
    lossless: bool = False
    flatten_alpha: bool = False


@dataclass
class VideoOptions:
    format: str = "mp4"
    codec: str = "libx264"
    quality: int = 65
    preset: str = "medium"
    resolution: str = "Original"
    fps: str = "Original"
    audio_bitrate: int = 128
    audio_codec: str = "aac"
    remove_audio: bool = False
    strip_metadata: bool = True
    hardware: str = "Off"


@dataclass
class AudioOptions:
    format: str = "mp3"
    bitrate: int = 192
    sample_rate: str = "Original"
    channels: str = "Original"
    codec: str = "libmp3lame"
    quality_mode: bool = False
    quality: int = 3
    strip_metadata: bool = True


@dataclass
class OutputOptions:
    directory: str = ""
    source_folder: bool = True
    create_folder: bool = True
    keep_structure: bool = True
    overwrite: bool = False


@dataclass
class Job:
    source: str
    kind: str
    options: dict
    output_options: dict
    root: str = ""
    id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "Waiting"
    progress: float = 0.0
    paused: bool = False
    enabled: bool = False
    original_size: int = 0
    output: str = ""
    output_size: int = 0
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now)
    finished_at: str = ""
    elapsed: float = 0.0
    eta: float | None = None
    archived: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> Job:
        return cls(**{k: v for k, v in value.items() if k in cls.__dataclass_fields__})

    @property
    def saved(self) -> int:
        return self.original_size - self.output_size if self.status == "Completed" else 0

    @property
    def summary(self) -> str:
        o = self.options
        if self.kind == "image":
            return (
                f"{o['format'].upper()} · {'Lossless' if o['lossless'] else 'Quality ' + str(o['quality'])}"
                + (f" · {o['width']} × {o['height']}" if o["resize"] else "")
            )
        if self.kind == "video":
            return f"{o['format'].upper()} · {o['codec']} · {o['resolution']} · Q{o['quality']}"
        return f"{o['format'].upper()} · {o['bitrate']} kbps · {o['channels']} channels"
