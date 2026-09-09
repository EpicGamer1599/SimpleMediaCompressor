import threading
from dataclasses import asdict

from simplemedia.filesystem import (
    commit_output,
    destination,
    output_directory,
    scan_folder,
)
from simplemedia.models import ImageOptions, Job, OutputOptions, media_type


def job(source, **kwargs):
    return Job(
        str(source),
        "image",
        asdict(ImageOptions(format="png")),
        asdict(OutputOptions(**kwargs)),
    )


def test_collision_and_atomic_publish(tmp_path):
    source = tmp_path / "picture.png"
    source.write_bytes(b"original")
    item = job(source, create_folder=False)
    first = destination(item)
    first.write_bytes(b"keep this existing output")
    assert destination(item).name == "picture_compressed_1.png"
    temp = tmp_path / "temporary.png"
    temp.write_bytes(b"new complete output")
    final = commit_output(temp, first, False, source)
    assert final.name == "picture_compressed_1.png"
    assert first.read_bytes() == b"keep this existing output"
    assert source.read_bytes() == b"original"
    assert not temp.exists()


def test_source_protected_even_with_overwrite(tmp_path):
    import pytest

    source = tmp_path / "source.png"
    source.write_bytes(b"original")
    temp = tmp_path / "temp.png"
    temp.write_bytes(b"new")
    with pytest.raises(ValueError, match="source"):
        commit_output(temp, source, True, source)
    assert source.read_bytes() == b"original"


def test_bulk_scan_and_structure(tmp_path):
    root = tmp_path / "Vacation"
    child = root / "Day 1"
    child.mkdir(parents=True)
    (root / "photo.jpg").touch()
    (child / "clip.MP4").touch()
    (child / "audio.mp3").touch()
    (child / "photo_compressed_1.jpg").touch()
    (child / "notes.txt").touch()
    (root / "Compressed").mkdir()
    (root / "Compressed" / "dont-scan.jpg").touch()
    files, errors = scan_folder(root, True, True, threading.Event(), lambda *_: None)
    assert len(files) == 3 and not errors
    files, _ = scan_folder(root, False, False, threading.Event(), lambda *_: None)
    assert len(files) == 1
    item = job(child / "image.png", directory=str(tmp_path / "out"), source_folder=False)
    item.root = str(root)
    assert output_directory(item) == tmp_path / "out" / "Compressed" / "Day 1"
    item.output_options["source_folder"] = True
    assert output_directory(item) == root / "Compressed" / "Day 1"


def test_scan_cancellation(tmp_path):
    event = threading.Event()
    event.set()
    assert scan_folder(tmp_path, True, True, event, lambda *_: None)[0] == []


def test_extension_detection():
    assert media_type("hello.WEBP") == "image"
    assert media_type("movie.MKV") == "video"
    assert media_type("voice.opus") == "audio"
    assert media_type("program.exe") is None
