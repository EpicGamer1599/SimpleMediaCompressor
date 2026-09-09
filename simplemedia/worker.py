"""Isolated encoder subprocess emitting newline-delimited JSON to a local stream."""

import json
import sys
from pathlib import Path


def main(request: str, events: str) -> None:
    # Windowed executables and pythonw have no Python stdout/stdin. A private,
    # append-only event stream works identically in source and frozen builds.
    stream = open(events, "a", encoding="utf-8", buffering=1)

    def emit(**message):
        stream.write(json.dumps(message, ensure_ascii=True) + "\n")
        stream.flush()

    try:
        payload = json.loads(Path(request).read_text(encoding="utf-8"))
        job, target = payload["job"], payload["target"]
        if not Path(job["source"]).is_file():
            raise FileNotFoundError("The input file no longer exists. Locate it and add it again.")
        if job["kind"] == "image":
            from .images import compress

            compress(job["source"], target, job["options"], emit)
        else:
            from .ffmpeg import FFmpegInfo, compress, detect

            info = payload["ffmpeg"]
            info["encoders"] = set(info["encoders"])
            encoder_info = FFmpegInfo(**info)
            if getattr(sys, "frozen", False) and not encoder_info.path and not encoder_info.error:
                encoder_info = detect()
            compress(
                encoder_info,
                job["kind"],
                job["source"],
                target,
                job["options"],
                emit,
            )
        emit(done=True)
    except Exception as error:
        emit(error=f"{type(error).__name__}: {error}")
        sys.exit(1)
    finally:
        stream.close()
