from __future__ import annotations

import errno
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from .models import Job, media_type


def size_text(size: float) -> str:
    sign = "−" if size < 0 else ""
    size = abs(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{sign}{size:,.0f} {unit}" if unit == "B" else f"{sign}{size:,.1f} {unit}"
        size /= 1024
    return "0 B"


def time_text(seconds: float | None) -> str:
    if seconds is None:
        return "Calculating…"
    seconds = max(0, int(seconds))
    return (
        f"{seconds // 3600}h {(seconds % 3600) // 60}m"
        if seconds >= 3600
        else f"{seconds // 60}m {seconds % 60:02d}s"
    )


def output_directory(job: Job) -> Path:
    source = Path(job.source).resolve()
    options = job.output_options
    if options["source_folder"]:
        base = Path(job.root).resolve() if job.root and options["keep_structure"] else source.parent
    else:
        if not options["directory"].strip():
            raise ValueError("Choose an output folder or enable ‘Use source folder’.")
        base = Path(options["directory"]).expanduser().resolve()
    if options["create_folder"]:
        base /= "Compressed"
    if job.root and options["keep_structure"]:
        base /= source.parent.relative_to(Path(job.root).resolve())
    return base


def destination(job: Job, reserved: set[Path] | None = None) -> Path:
    folder = output_directory(job)
    folder.mkdir(parents=True, exist_ok=True)
    source = Path(job.source).resolve()
    extension = job.options["format"].lower()
    if extension not in {
        "jpg",
        "png",
        "webp",
        "bmp",
        "tiff",
        "gif",
        "mp4",
        "mkv",
        "mov",
        "webm",
        "mp3",
        "wav",
        "flac",
        "aac",
        "ogg",
        "m4a",
        "opus",
    }:
        raise ValueError("Unsupported output format.")
    candidate = folder / f"{source.stem}_compressed.{extension}"
    index = 0
    while (
        candidate.resolve() == source
        or candidate in (reserved or set())
        or (candidate.exists() and not job.output_options["overwrite"])
    ):
        index += 1
        candidate = folder / f"{source.stem}_compressed_{index}.{extension}"
    return candidate


def commit_output(temp: Path, target: Path, overwrite: bool, source: Path) -> Path:
    """Publish only complete files; never replace a source, even with overwrite on."""
    if target.resolve() == source.resolve():
        raise ValueError("The source file cannot be overwritten.")
    if overwrite:
        os.replace(temp, target)
        return target
    # Hard-link publication is atomic and fails if another process won the name.
    original = target
    suffix = 0
    while True:
        try:
            os.link(temp, target)
            temp.unlink()
            return target
        except FileExistsError:
            suffix += 1
            target = original.with_stem(f"{original.stem}_{suffix}")
        except OSError as error:
            if error.errno not in {
                errno.EPERM,
                errno.EOPNOTSUPP,
                errno.ENOSYS,
                errno.EXDEV,
            }:
                raise
            # FAT/network filesystems may lack hard links. Exclusive creation still
            # prevents clobbering another file; rollback on any copy failure.
            try:
                stream = target.open("xb")
            except FileExistsError:
                suffix += 1
                target = original.with_stem(f"{original.stem}_{suffix}")
                continue
            try:
                with stream, temp.open("rb") as reader:
                    shutil.copyfileobj(reader, stream, 1024 * 1024)
                temp.unlink()
                return target
            except BaseException:
                target.unlink(missing_ok=True)
                raise


def temporary_output(target: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=".smc-", suffix=target.suffix, dir=target.parent)
    os.close(fd)
    return Path(name)


def scan_folder(
    root: Path,
    recursive: bool,
    skip_compressed: bool,
    cancel: threading.Event,
    progress: Callable[[int, int], None],
    excluded: Path | None = None,
) -> tuple[list[str], list[str]]:
    files, errors = [], []
    visited = 0
    root = root.resolve()

    def onerror(error):
        errors.append(str(error))

    for current, directories, names in os.walk(root, followlinks=False, onerror=onerror):
        if cancel.is_set():
            break
        directories[:] = sorted(
            d
            for d in directories
            if d.lower() != "compressed"
            and not (Path(current) / d).is_symlink()
            and (excluded is None or (Path(current) / d).resolve() != excluded.resolve())
        )
        for name in sorted(names):
            if cancel.is_set():
                break
            visited += 1
            path = Path(current) / name
            if media_type(path) and not path.is_symlink() and not name.startswith(".smc-"):
                if not skip_compressed or not re.search(
                    r"_compressed(?:_\d+)*$", path.stem, re.IGNORECASE
                ):
                    files.append(str(path))
            if visited % 100 == 0:
                progress(visited, len(files))
        if not recursive:
            break
    progress(visited, len(files))
    return files, errors
