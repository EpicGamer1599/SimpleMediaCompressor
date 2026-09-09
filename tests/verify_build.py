"""Run with Python after build.py to exercise the actual packaged application.

The visible UI is rendered with SDL's dummy driver. Real image, video and audio
jobs run through the frozen executable, with a regular QueueManager controlling
their progress, output publication, and history.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

from simplemedia.ffmpeg import CREATE_FLAGS, FFmpegInfo, detect, probe_media, run_capture
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, help="Executable to validate")
    parser.add_argument("--bundled", action="store_true", help="Require a self-contained EXE")
    options = parser.parse_args()
    exe = options.exe or (
        ROOT
        / "dist/SimpleMediaCompressure"
        / ("SimpleMediaCompressure.exe" if os.name == "nt" else "SimpleMediaCompressure")
    )
    if not exe.is_file():
        raise SystemExit("Build the application first: python build.py")
    directory = ROOT / ".artifacts" / ("packaged-" + str(int(time.time())))
    directory.mkdir(parents=True)
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SMC_DATA_DIR=str(directory / "data"))
    if options.bundled:
        # Run a copy with no adjacent dependencies and hide installed FFmpeg.
        standalone = directory / "standalone"
        standalone.mkdir()
        exe = Path(shutil.copy2(exe, standalone / exe.name))
        local = directory / "localappdata"
        runtime = directory / "runtime"
        local.mkdir()
        runtime.mkdir()
        env.update(
            PATH=str(Path(os.environ["SystemRoot"]) / "System32"),
            LOCALAPPDATA=str(local),
            TEMP=str(runtime),
            TMP=str(runtime),
            PYTHONPATH="",
            PYTHONHOME="",
        )
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
    manager = QueueManager(store, FFmpegInfo() if options.bundled else info)
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
            kwargs["env"] = env
        return original_popen(args, *positional, **kwargs)

    try:
        with patch("simplemedia.queue.subprocess.Popen", packaged_popen):
            manager.add(jobs)
            manager.start()
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline and (
                any(j.status not in TERMINAL for j in jobs) or manager.controls
            ):
                time.sleep(0.05)
        assert all(j.status == "Completed" for j in jobs), [
            (j.kind, j.status, j.error) for j in jobs
        ]
        assert all(Path(j.output).stat().st_size > 0 for j in jobs)
        with Image.open(jobs[0].output) as converted:
            assert converted.size == (600, 400)
            converted.load()
        for job in jobs[1:]:
            media = probe_media(info, job.output)
            assert float(media["format"]["duration"]) >= 1
            assert any(stream["codec_type"] == job.kind for stream in media["streams"])
        print("Packaged image, video and audio workers passed.")
    finally:
        manager.shutdown()
        store.close()
    screenshot = directory / "queue.png"
    result = subprocess.run(
        [str(exe), "--page", "Queue", "--screenshot", str(screenshot)],
        env=env,
        timeout=90,
        creationflags=CREATE_FLAGS,
    )
    assert result.returncode == 0 and screenshot.is_file(), "Packaged GUI failed to render"
    print("Packaged GUI passed:", screenshot)
    if options.bundled:
        assert list(standalone.iterdir()) == [exe]
        assert not list(runtime.iterdir()), "The one-file application left extraction files behind"
        print("Standalone EXE passed with no adjacent dependencies or external FFmpeg paths.")


if __name__ == "__main__":
    main()
