"""Build a development bundle or a self-contained, versioned Windows release."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from simplemedia.ffmpeg import detect, run_capture
from simplemedia.metadata import AUTHOR, NAME, VERSION

ROOT = Path(__file__).resolve().parent


def inside_project(relative: str) -> Path:
    """PyInstaller may replace outputs; reject redirected build paths first."""
    resolved = (ROOT / relative).resolve()
    if not resolved.is_relative_to(ROOT) or resolved == ROOT:
        raise ValueError(f"Build target must stay inside the project: {resolved}")
    return resolved


def make_icon() -> Path:
    from PIL import Image, ImageDraw

    icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    drawing = ImageDraw.Draw(icon)
    drawing.rounded_rectangle((8, 8, 248, 248), radius=67, fill=(102, 229, 190))
    drawing.line([(62, 69), (114, 121), (62, 121)], fill=(12, 17, 25), width=15)
    drawing.line([(194, 187), (142, 135), (194, 135)], fill=(12, 17, 25), width=15)
    path = inside_project("build") / "application.ico"
    path.parent.mkdir(exist_ok=True)
    icon.save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


def release_notices(destination: Path, info, label: str) -> None:
    """Keep unchanged upstream licenses and source references with the release."""
    licenses = destination / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", destination / "LICENSE.txt")
    shutil.copy2(ROOT / "CONTRIBUTING.md", destination / "CONTRIBUTING.md")
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python-LICENSE.txt")
    for name in ("pygame-ce", "Pillow", "psutil", "pyinstaller"):
        distribution = importlib.metadata.distribution(name)
        for file in distribution.files or []:
            if any(
                word in file.name.upper()
                for word in ("LICENSE", "LICENCE", "COPYING", "NOTICE", "LGPL")
            ):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    target = licenses / name / file.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        if name == "pygame-ce":
            generated = Path(distribution.locate_file("pygame/docs/generated"))
            for source in [generated / "LGPL.txt", *sorted((generated / "licenses").glob("*"))]:
                if source.is_file():
                    target = licenses / name / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    ffmpeg_directory = Path(info.path).parent.parent
    upstream_license = ffmpeg_directory / "LICENSE"
    upstream_readme = ffmpeg_directory / "README.txt"
    if not upstream_license.is_file() or not upstream_readme.is_file():
        raise ValueError(
            "Use an FFmpeg distribution with LICENSE and README.txt beside its bin folder."
        )
    shutil.copy2(upstream_license, licenses / "FFmpeg-LICENSE.txt")
    shutil.copy2(upstream_readme, licenses / "FFmpeg-UPSTREAM-README.txt")
    configuration = run_capture([info.path, "-version"]).stdout
    if "--enable-nonfree" in configuration:
        raise ValueError("Choose a redistributable FFmpeg build without --enable-nonfree.")
    (licenses / "FFmpeg-build-configuration.txt").write_text(configuration, encoding="utf-8")
    notices = (
        f"{NAME} {label}\nCopyright (c) 2026 {AUTHOR}\n\n"
        "The application source is MIT-licensed; see LICENSE.txt.\n"
        "Bundled third-party components retain their own copyright and license terms.\n\n"
        "FFmpeg and FFprobe are bundled as separate executables and called as subprocesses.\n"
        f"Build: {info.version}\n"
        "The bundled Gyan build uses GPL v3. Its unchanged license, upstream README\n"
        "with its exact source revision, and configuration are in licenses/.\n"
        "Upstream builds and source references: https://www.gyan.dev/ffmpeg/builds/\n"
        "FFmpeg source: https://github.com/FFmpeg/FFmpeg\n"
        "FFmpeg license information: https://ffmpeg.org/legal.html\n\n"
        f"Python {platform.python_version()}: https://www.python.org/\n"
        "Pygame CE (LGPL-2.1-or-later): https://github.com/pygame-community/pygame-ce\n"
        "Pillow (HPND): https://github.com/python-pillow/Pillow\n"
        "psutil (BSD-3-Clause): https://github.com/giampaolo/psutil\n"
        "PyInstaller bootloader (GPL with distribution exception): https://github.com/pyinstaller/pyinstaller\n"
        "Copies of the upstream license notices are in licenses/.\n"
    )
    (destination / "THIRD_PARTY_NOTICES.txt").write_text(notices, encoding="utf-8")
    (destination / "START_HERE.txt").write_text(
        f"{NAME} {label}\nOwner and maintainer: {AUTHOR}\n\n"
        f"Double-click {NAME}.exe to start.\n"
        "Python, Pygame, Pillow, psutil, FFmpeg and FFprobe are included in the EXE.\n"
        "No Python installation, FFmpeg setup or internet connection is needed to compress files.\n"
        "Windows 10/11, 64-bit. Launch can take a little longer while the application\n"
        "unpacks its included tools into your temporary folder.\n"
        "Allow roughly 600 MB of free temporary space. Your originals are preserved.\n\n"
        "Add media, choose your output settings, add files to the queue, then Start all.\n"
        "Settings, history and logs are stored in %LOCALAPPDATA%\\SimpleMediaCompressure.\n"
        "The adjacent documentation and licenses are provided for reference and distribution;\n"
        "the EXE can run by itself. Keep the license notices when sharing the release.\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release",
        metavar="VERSION",
        help="Build release/VERSION as one self-contained Windows EXE",
    )
    parser.add_argument(
        "--ffmpeg-dir", type=Path, help="Optional FFmpeg distribution folder or its bin directory"
    )
    options = parser.parse_args()
    for relative in ("build", "dist", f"dist/{NAME}"):
        inside_project(relative)
    arguments = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name",
        NAME,
        "--add-data",
        f"{ROOT / 'simplemedia/LICENSE.txt'}:simplemedia",
    ]
    if os.name == "nt":
        arguments += ["--exclude-module", "tkinter", "--icon", str(make_icon())]
    info = None
    destination = None
    if options.release:
        if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
            parser.error("Build this release on 64-bit Windows.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", options.release):
            parser.error("Use a single version folder name, for example 1.0.0beta.")
        destination = inside_project(f"release/{options.release}")
        inside_project(f"release/{options.release}/licenses")
        work = inside_project(f"build/release-{options.release}")
        destination.mkdir(parents=True, exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)
        manual = ""
        if options.ffmpeg_dir:
            directory = options.ffmpeg_dir.expanduser().resolve()
            manual = str(
                directory / "ffmpeg.exe"
                if (directory / "ffmpeg.exe").is_file()
                else directory / "bin/ffmpeg.exe"
            )
        info = detect(manual)
        if not info.available or not info.probe:
            parser.error(
                "A full FFmpeg installation with FFprobe is needed to build this release. "
                + info.error
            )
        release_notices(destination, info, options.release)
        arguments += [
            "--onefile",
            "--noupx",
            "--distpath",
            str(destination),
            "--workpath",
            str(work),
            "--specpath",
            str(work),
            "--add-binary",
            f"{info.path}:ffmpeg",
            "--add-binary",
            f"{info.probe}:ffmpeg",
            "--add-data",
            f"{destination / 'licenses'}:licenses",
            "--add-data",
            f"{destination / 'THIRD_PARTY_NOTICES.txt'}:.",
        ]
    else:
        arguments += ["--onedir"]
    arguments.append(str(ROOT / "main.py"))
    subprocess.run(arguments, cwd=ROOT, check=True)
    if destination:
        executable = destination / f"{NAME}.exe"
        with executable.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        (destination / "SHA256SUMS.txt").write_text(
            f"{digest}  {executable.name}\n", encoding="utf-8"
        )
        manifest = {
            "application": NAME,
            "application_version": VERSION,
            "release": options.release,
            "owner_and_maintainer": AUTHOR,
            "platform": "Windows x64",
            "packaging": "onefile",
            "python": platform.python_version(),
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in ("pygame-ce", "Pillow", "psutil", "pyinstaller")
            },
            "ffmpeg": info.version,
            "executable": executable.name,
            "size_bytes": executable.stat().st_size,
            "sha256": digest,
        }
        (destination / "BUILD_INFO.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Release ready: {executable}")


if __name__ == "__main__":
    main()
