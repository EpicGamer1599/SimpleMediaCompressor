from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
AUDIO_CODECS = {
    "mp3": "libmp3lame",
    "m4a": "aac",
    "aac": "aac",
    "ogg": "libvorbis",
    "opus": "libopus",
    "flac": "flac",
    "wav": "pcm_s16le",
}
VIDEO_CODECS = {
    "mp4": ["libx264", "libx265"],
    "mov": ["libx264", "libx265"],
    "mkv": ["libx264", "libx265", "libvpx-vp9"],
    "webm": ["libvpx-vp9"],
}


@dataclass
class FFmpegInfo:
    path: str = ""
    probe: str = ""
    version: str = "Not detected"
    encoders: set[str] = field(default_factory=set)
    error: str = ""

    @property
    def available(self):
        return bool(self.path and self.encoders)


def run_capture(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_FLAGS,
        check=False,
    )


def detect(manual: str = "") -> FFmpegInfo:
    executable = manual.strip()
    if not executable and getattr(sys, "frozen", False):
        # PyInstaller one-file builds unpack their bundled tools here.
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        bundled = base / "ffmpeg" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if bundled.is_file():
            executable = str(bundled)
    executable = executable or shutil.which("ffmpeg") or ""
    if not executable and os.name == "nt":
        # WinGet installations can exist before a shell's PATH is refreshed.
        package = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
        matches = sorted(package.glob("Gyan.FFmpeg*/ffmpeg*/bin/ffmpeg.exe"))
        executable = str(matches[-1]) if matches else ""
    if not executable:
        return FFmpegInfo(
            error="FFmpeg was not found. Images still work. Install FFmpeg or select its executable in Settings."
        )
    try:
        path = Path(executable).expanduser().resolve(strict=True)
        if path.name.lower() not in {"ffmpeg", "ffmpeg.exe"}:
            raise ValueError("Select the FFmpeg executable named ffmpeg or ffmpeg.exe.")
        version = run_capture([str(path), "-version"])
        if version.returncode or not version.stdout.startswith("ffmpeg version"):
            raise ValueError("The selected executable did not identify itself as FFmpeg.")
        encoders = run_capture([str(path), "-hide_banner", "-encoders"])
        if encoders.returncode:
            raise ValueError("FFmpeg could not list its encoders.")
        supported = set(re.findall(r"^\s*[VAS][A-Z.]{5}\s+(\S+)", encoders.stdout, re.MULTILINE))
        probe = path.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        return FFmpegInfo(
            str(path),
            str(probe) if probe.is_file() else shutil.which("ffprobe") or "",
            version.stdout.splitlines()[0],
            supported,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return FFmpegInfo(error=f"FFmpeg detection failed: {error}")


def crf(quality: int) -> int:
    return round(36 - max(0, min(100, quality)) * 0.20)


def probe_media(info: FFmpegInfo, source: str) -> dict:
    if not info.probe:
        return {}
    result = run_capture(
        [
            info.probe,
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            source,
        ],
        timeout=30,
    )
    if result.returncode:
        raise ValueError("This file could not be read as media. " + result.stderr[-1500:])
    return json.loads(result.stdout)


def command(info: FFmpegInfo, kind: str, source: str, target: str, options: dict) -> list[str]:
    o = options
    args = [
        info.path,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        source,
    ]
    required = []
    if kind == "video":
        codec = o["codec"]
        if o["format"] not in VIDEO_CODECS or codec not in VIDEO_CODECS[o["format"]]:
            raise ValueError("This video codec is incompatible with the selected output format.")
        if o["hardware"] != "Off":
            if codec != "libx264" or o["hardware"] not in {
                "h264_nvenc",
                "h264_qsv",
                "h264_amf",
            }:
                raise ValueError(
                    "Hardware encoding is supported for H.264 output only. Choose H.264 or turn hardware off."
                )
            codec = o["hardware"]
        required.append(codec)
        args += ["-map", "0:v:0", "-c:v", codec, "-threads", "2"]
        value = str(crf(o["quality"]))
        if codec == "h264_nvenc":
            args += ["-preset", "p4", "-rc", "vbr", "-cq", value, "-b:v", "0"]
        elif codec == "h264_qsv":
            args += ["-global_quality", value]
        elif codec == "h264_amf":
            args += ["-rc", "cqp", "-qp_i", value, "-qp_p", value]
        elif codec == "libvpx-vp9":
            args += [
                "-crf",
                str(round(48 - o["quality"] * 0.3)),
                "-b:v",
                "0",
                "-cpu-used",
                {
                    "veryfast": "6",
                    "fast": "4",
                    "medium": "2",
                    "slow": "1",
                    "veryslow": "0",
                }[o["preset"]],
            ]
        else:
            args += ["-crf", value, "-preset", o["preset"]]
        if o["resolution"] != "Original":
            height = int(o["resolution"].removesuffix("p"))
            if height not in {480, 720, 1080, 1440, 2160}:
                raise ValueError("Unsupported resolution.")
            args += [
                "-vf",
                f"scale=w=-2:h='min({height},ih)':force_divisible_by=2,pad=ceil(iw/2)*2:ceil(ih/2)*2",
            ]
        else:
            args += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
        args += ["-pix_fmt", "yuv420p"]
        if o["fps"] != "Original":
            if o["fps"] not in {"24", "25", "30", "50", "60"}:
                raise ValueError("Unsupported frame rate.")
            args += ["-r", o["fps"]]
        if o["remove_audio"]:
            args += ["-an"]
        else:
            if o["format"] == "webm" and o["audio_codec"] not in {
                "libopus",
                "libvorbis",
            }:
                raise ValueError("WebM requires Opus or Vorbis audio.")
            if o["format"] in {"mp4", "mov"} and o["audio_codec"] != "aac":
                raise ValueError("Choose AAC audio for MP4/MOV, or use MKV for other audio codecs.")
            required.append(o["audio_codec"])
            args += [
                "-map",
                "0:a:0?",
                "-c:a",
                o["audio_codec"],
                "-b:a",
                f"{o['audio_bitrate']}k",
            ]
        if o["format"] in {"mp4", "mov"}:
            args += ["-movflags", "+faststart"]
    else:
        if AUDIO_CODECS.get(o["format"]) != o["codec"]:
            raise ValueError("The audio codec does not match the selected format.")
        required.append(o["codec"])
        args += ["-map", "0:a:0", "-vn", "-c:a", o["codec"], "-threads", "2"]
        if o["quality_mode"] and o["codec"] in {"libmp3lame", "libvorbis"}:
            args += ["-q:a", str(o["quality"])]
        elif o["format"] not in {"flac", "wav"}:
            args += ["-b:a", f"{o['bitrate']}k"]
        if o["sample_rate"] != "Original":
            rate = int(o["sample_rate"])
            if rate not in {16000, 22050, 24000, 32000, 44100, 48000, 96000}:
                raise ValueError("Unsupported sample rate.")
            if o["codec"] == "libopus" and rate not in {16000, 24000, 48000}:
                raise ValueError(
                    "Opus supports 16000, 24000 or 48000 Hz here; choose Original for automatic resampling."
                )
            args += ["-ar", str(rate)]
        elif o["codec"] == "libopus":
            args += ["-ar", "48000"]
        if o["channels"] != "Original":
            args += ["-ac", "1" if o["channels"] == "Mono" else "2"]
    missing = [encoder for encoder in required if encoder not in info.encoders]
    if missing:
        raise ValueError(
            "Your FFmpeg build is missing encoder(s): "
            + ", ".join(missing)
            + ". Choose another codec or install a full FFmpeg build."
        )
    if o.get("strip_metadata", True):
        args += ["-map_metadata", "-1", "-map_chapters", "-1"]
    args += [target]
    return args


def compress(info: FFmpegInfo, kind: str, source: str, target: str, options: dict, emit) -> None:
    if not info.available:
        raise ValueError(
            info.error or "FFmpeg is missing. Install it or choose its executable in Settings."
        )
    metadata = probe_media(info, source)
    duration = float(metadata.get("format", {}).get("duration", 0) or 0)
    args = command(info, kind, source, target, options)
    errors = deque(maxlen=40)
    process = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_FLAGS,
    )

    def drain():
        for line in process.stderr:
            errors.append(line.rstrip()[:2000])

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        for line in process.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and duration:
                try:
                    emit(progress=min(0.99, max(0, int(value) / 1_000_000 / duration)))
                except ValueError:
                    pass
        process.wait()
        reader.join(timeout=2)
        if process.returncode:
            detail = "\n".join(errors)
            hint = "FFmpeg could not encode this file."
            if options.get("hardware", "Off") != "Off":
                hint += " Hardware support also requires a compatible GPU and driver; try Hardware: Off."
            raise RuntimeError(hint + "\n" + detail)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()
