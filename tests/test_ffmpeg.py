import os
import subprocess
import sys
from dataclasses import asdict

import pytest

from simplemedia.ffmpeg import (
    AUDIO_CODECS,
    FFmpegInfo,
    command,
    compress,
    detect,
    probe_media,
    run_capture,
)
from simplemedia.models import AudioOptions, VideoOptions


@pytest.mark.ffmpeg
@pytest.mark.parametrize("format", ["mp3", "m4a", "aac", "ogg", "opus", "flac", "wav"])
def test_real_audio(tmp_path, ffmpeg_info, format):
    codec = AUDIO_CODECS[format]
    if codec not in ffmpeg_info.encoders:
        pytest.skip("Encoder unavailable: " + codec)
    source = tmp_path / "tone.wav"
    made = run_capture(
        [
            ffmpeg_info.path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2",
            "-y",
            str(source),
        ]
    )
    assert made.returncode == 0, made.stderr
    target = tmp_path / ("compressed." + format)
    options = asdict(AudioOptions(format=format, codec=codec, bitrate=96, channels="Mono"))
    events = []
    compress(
        ffmpeg_info,
        "audio",
        str(source),
        str(target),
        options,
        lambda **e: events.append(e),
    )
    meta = probe_media(ffmpeg_info, str(target))
    assert target.stat().st_size > 0
    assert float(meta["format"]["duration"]) >= 1
    assert meta["streams"][0]["channels"] == 1
    assert events


@pytest.mark.ffmpeg
@pytest.mark.parametrize(
    "format,codec,audio",
    [
        ("mp4", "libx264", "aac"),
        ("webm", "libvpx-vp9", "libopus"),
        ("mkv", "libx265", "aac"),
    ],
)
def test_real_video(tmp_path, ffmpeg_info, format, codec, audio):
    if codec not in ffmpeg_info.encoders or audio not in ffmpeg_info.encoders:
        pytest.skip("Required encoders unavailable")
    source = tmp_path / "source video.mp4"
    result = run_capture(
        [
            ffmpeg_info.path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1.2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(source),
        ]
    )
    assert result.returncode == 0, result.stderr
    target = tmp_path / ("compressed." + format)
    options = asdict(
        VideoOptions(
            format=format,
            codec=codec,
            audio_codec=audio,
            preset="veryfast",
            resolution="480p",
            fps="24",
        )
    )
    events = []
    compress(
        ffmpeg_info,
        "video",
        str(source),
        str(target),
        options,
        lambda **e: events.append(e),
    )
    meta = probe_media(ffmpeg_info, str(target))
    assert any(stream["codec_type"] == "video" for stream in meta["streams"])
    assert any(stream["codec_type"] == "audio" for stream in meta["streams"])
    assert meta["streams"][0]["height"] == 180
    assert any("progress" in e for e in events)


def test_missing_and_invalid_ffmpeg(tmp_path):
    assert not detect(str(tmp_path / "missing" / "ffmpeg.exe")).available


@pytest.mark.parametrize("frozen,manual", [(True, False), (True, True), (False, False)])
def test_bundled_ffmpeg_discovery(tmp_path, monkeypatch, frozen, manual):
    extension = ".exe" if os.name == "nt" else ""
    for folder in ("ffmpeg", "external", "selected"):
        directory = tmp_path / folder
        directory.mkdir()
        (directory / ("ffmpeg" + extension)).touch()
        (directory / ("ffprobe" + extension)).touch()
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(
        "simplemedia.ffmpeg.shutil.which",
        lambda name: str(tmp_path / "external" / (name + extension)),
    )
    selected = "selected" if manual else "ffmpeg" if frozen else "external"
    expected = tmp_path / selected / ("ffmpeg" + extension)
    calls = []

    def capture(arguments):
        calls.append(arguments)
        output = (
            "ffmpeg version test\n" if "-version" in arguments else " V..... libx264\n A..... aac\n"
        )
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr="")

    monkeypatch.setattr("simplemedia.ffmpeg.run_capture", capture)
    result = detect(str(expected) if manual else "")
    assert result.available and result.encoders == {"libx264", "aac"}
    assert result.path == str(expected)
    assert result.probe == str(expected.with_name("ffprobe" + extension))
    assert len(calls) == 2 and all(call[0] == str(expected) for call in calls)


def test_unavailable_encoder_and_safe_args():
    info = FFmpegInfo(path="ffmpeg", encoders={"aac"})
    with pytest.raises(ValueError, match="missing encoder"):
        command(
            info,
            "video",
            "untrusted; $(name).mp4",
            "output.mp4",
            asdict(VideoOptions()),
        )
    info.encoders.add("libx264")
    args = command(info, "video", "untrusted; $(name).mp4", "output.mp4", asdict(VideoOptions()))
    assert "untrusted; $(name).mp4" in args
    assert args[args.index("-protocol_whitelist") + 1] == "file,pipe"


def test_container_compatibility():
    with pytest.raises(ValueError, match="incompatible"):
        command(
            FFmpegInfo(),
            "video",
            "a",
            "b",
            asdict(VideoOptions(format="webm", codec="libx264")),
        )
