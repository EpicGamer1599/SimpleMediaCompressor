"""Build a windowed executable with the same isolated worker entry point."""

import os
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    # PyInstaller replaces its output directory. Refuse a redirected/symlinked
    # build target outside this checkout before permitting that replacement.
    for relative in ("build", "dist", "dist/SimpleMediaCompressure"):
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root) or resolved == root:
            raise SystemExit(f"Build target must stay inside the project: {resolved}")
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onedir",
        "--name",
        "SimpleMediaCompressure",
        "--add-data",
        f"{root / 'simplemedia/LICENSE.txt'}:simplemedia",
        str(root / "main.py"),
    ]
    if os.name == "nt":
        args += ["--exclude-module", "tkinter"]
        # Draw the same simple application mark at native icon sizes.
        from PIL import Image, ImageDraw

        icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        drawing = ImageDraw.Draw(icon)
        drawing.rounded_rectangle((8, 8, 248, 248), radius=67, fill=(102, 229, 190))
        drawing.line([(62, 69), (114, 121), (62, 121)], fill=(12, 17, 25), width=15)
        drawing.line([(194, 187), (142, 135), (194, 135)], fill=(12, 17, 25), width=15)
        icon_path = root / "build" / "application.ico"
        icon_path.parent.mkdir(exist_ok=True)
        icon.save(icon_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        args += ["--icon", str(icon_path)]
    subprocess.run(args, cwd=root, check=True)
