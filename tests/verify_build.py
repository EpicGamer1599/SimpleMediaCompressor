"""Run with Python after build.py to exercise the actual packaged application.

The visible UI is rendered with SDL's dummy driver. Real image, video and audio
jobs run through the frozen executable, with a regular QueueManager controlling
their progress, output publication, and history.
"""

import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

from simplemedia.ffmpeg import CREATE_FLAGS, detect, run_capture
from simplemedia.models import (
    TERMINAL,
    AudioOptions,
    ImageOptions,
    Job,
    OutputOptions,
    VideoOptions,
)
from simplemedia.queue import QueueManager
from simplemedia.storage import Store


def main():
    exe = (
        ROOT
        / "dist/SimpleMediaCompressure"
        / ("SimpleMediaCompressure.exe" if os.name == "nt" else "SimpleMediaCompressure")
    )
    if not exe.is_file():
        raise SystemExit("Build the application first: python build.py")
    directory = ROOT / ".artifacts" / ("packaged-" + str(int(time.time())))
    directory.mkdir(parents=True)
    info = detect()
    assert info.available and info.probe, (
        "Install FFmpeg and FFprobe before running full packaged validation."
    )
    source = directory / "image.png"
    Image.effect_noise((600, 400), 35).convert("RGB").save(source)
    audio = directory / "audio.wav"
    video = directory / "video.mp4"
    for path, args in [
        (audio, ["-f", "lavfi", "-i", "sine=duration=1.2"]),
        (
            video,
            [
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=24:duration=1.2",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
            ],
        ),
    ]:
        result = run_capture(
            [info.path, "-hide_banner", "-loglevel", "error", *args, "-y", str(path)]
        )
        assert result.returncode == 0, result.stderr
    store = Store(directory / "data")
    manager = QueueManager(store, info)
    jobs = [
        Job(str(path), kind, asdict(options), asdict(OutputOptions()))
        for path, kind, options in [
            (source, "image", ImageOptions()),
            (video, "video", VideoOptions()),
            (audio, "audio", AudioOptions()),
        ]
    ]
    original_popen = subprocess.Popen

    def packaged_popen(args, *positional, **kwargs):
        if args[:4] == [sys.executable, "-m", "simplemedia", "--worker"]:
            args = [str(exe), *args[3:]]
        return original_popen(args, *positional, **kwargs)

    try:
        with patch("simplemedia.queue.subprocess.Popen", packaged_popen):
            manager.add(jobs)
            manager.start()
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and (
                any(j.status not in TERMINAL for j in jobs) or manager.controls
            ):
                time.sleep(0.05)
        assert all(j.status == "Completed" for j in jobs), [
            (j.kind, j.status, j.error) for j in jobs
        ]
        assert all(Path(j.output).stat().st_size > 0 for j in jobs)
        print("Packaged image, video and audio workers passed.")
    finally:
        manager.shutdown()
        store.close()
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SMC_DATA_DIR=str(directory / "data"))
    screenshot = directory / "queue.png"
    result = subprocess.run(
        [str(exe), "--page", "Queue", "--screenshot", str(screenshot)],
        env=env,
        timeout=35,
        creationflags=CREATE_FLAGS,
    )
    assert result.returncode == 0 and screenshot.is_file(), "Packaged GUI failed to render"
    print("Packaged GUI passed:", screenshot)


if __name__ == "__main__":
    main()
