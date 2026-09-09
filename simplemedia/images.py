from __future__ import annotations

import warnings
from pathlib import Path

from PIL import Image, ImageOps, features
from PIL.PngImagePlugin import PngInfo


def mapped_quality(compression: int) -> int:
    return round(100 - max(0, min(100, compression)) * 0.5)


def compress(source: str, target: str, options: dict, emit) -> None:
    o = options
    fmt = {"jpg": "JPEG", "tiff": "TIFF"}.get(o["format"], o["format"].upper())
    if fmt == "WEBP" and not features.check("webp"):
        raise ValueError("This Pillow installation has no WebP support. Choose PNG or JPEG.")
    if o["lossless"] and fmt not in {"WEBP", "PNG", "TIFF", "BMP"}:
        raise ValueError(
            "Lossless mode is available for WebP, PNG, TIFF and BMP. Choose one of these formats."
        )
    if not 1 <= o["quality"] <= 100:
        raise ValueError("Image quality must be between 1 and 100.")
    if o["resize"] and not (1 <= o["width"] <= 32768 and 1 <= o["height"] <= 32768):
        raise ValueError("Image dimensions must be between 1 and 32768 pixels.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(source) as original:
            total = getattr(original, "n_frames", 1)
            animated = total > 1
            if animated and fmt not in {"GIF", "WEBP", "PNG", "TIFF"}:
                raise ValueError(
                    "This file has multiple frames. Choose GIF, WebP, PNG or TIFF to preserve them."
                )
            # Pillow's animation encoders retain frames; bound their memory usage.
            if total * original.width * original.height * 4 > 512 * 1024 * 1024:
                raise ValueError(
                    "This image sequence would require over 512 MB of decoded frames. Resize/export it with a specialist tool first."
                )
            if animated and fmt == "GIF":
                emit(warning="GIF uses a 256-color palette and single-level transparency.")
            durations, frames = [], []
            first_info = dict(original.info)
            exif = b""
            default_image = bool(first_info.get("default_image"))
            start_frame = 1 if default_image and fmt != "PNG" else 0
            for index in range(start_frame, total):
                original.seek(index)
                frame = ImageOps.exif_transpose(original.copy())
                if index == 0:
                    exif = frame.getexif().tobytes()
                alpha = "A" in frame.getbands() or "transparency" in frame.info
                if fmt in {"JPEG", "BMP"} and alpha:
                    rgba = frame.convert("RGBA")
                    has_transparency = rgba.getextrema()[3][0] < 255
                    if has_transparency and not o["flatten_alpha"]:
                        raise ValueError(
                            "This image contains transparency. Choose PNG/WebP/TIFF/GIF, or enable ‘Flatten transparency on white’ to convert it."
                        )
                    background = Image.new("RGB", rgba.size, "white")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    frame = background
                    if has_transparency and index == 0:
                        emit(warning="Transparency was flattened onto white as requested.")
                elif fmt == "JPEG" and frame.mode not in {"RGB", "L"}:
                    frame = frame.convert("RGB")
                elif fmt in {"WEBP", "GIF"} or (
                    fmt == "PNG"
                    and frame.mode not in {"1", "L", "LA", "P", "RGB", "RGBA", "I;16", "I"}
                ):
                    frame = frame.convert("RGBA" if alpha else "RGB")
                if animated and fmt == "PNG":
                    # GIF decoding may switch from palette to RGB between frames.
                    # APNG needs one consistent mode, including the first frame.
                    frame = frame.convert("RGBA")
                if o["resize"]:
                    if o["aspect"]:
                        frame.thumbnail((o["width"], o["height"]), Image.Resampling.LANCZOS)
                    else:
                        frame = frame.resize((o["width"], o["height"]), Image.Resampling.LANCZOS)
                durations.append(original.info.get("duration", 100))
                # Remove implicit metadata too, not just explicit save kwargs.
                if o["strip_metadata"]:
                    transparency = frame.info.get("transparency")
                    frame.info.clear()
                    if transparency is not None:
                        frame.info["transparency"] = transparency
                frames.append(frame)
                emit(progress=0.05 + 0.55 * (index + 1) / total)
            kwargs = {}
            level = max(0, min(100, o["compression"]))
            if fmt == "JPEG":
                kwargs.update(
                    quality=o["quality"],
                    optimize=True,
                    progressive=o["progressive"],
                    subsampling=0 if o["quality"] >= 95 else 2,
                )
            elif fmt == "WEBP":
                kwargs.update(
                    quality=o["quality"],
                    lossless=o["lossless"],
                    method=round(level * 6 / 100),
                    exact=True,
                )
            elif fmt == "PNG":
                kwargs.update(compress_level=round(level * 9 / 100), optimize=level >= 85)
            elif fmt == "TIFF":
                kwargs.update(compression="tiff_deflate")
            elif fmt == "GIF":
                kwargs.update(optimize=level >= 30)
            if not o["strip_metadata"]:
                if fmt in {"JPEG", "PNG", "WEBP", "TIFF"}:
                    if exif:
                        kwargs["exif"] = exif
                    if first_info.get("icc_profile"):
                        kwargs["icc_profile"] = first_info["icc_profile"]
                if fmt == "PNG":
                    text = PngInfo()
                    for key, value in first_info.items():
                        if isinstance(value, str):
                            text.add_text(key, value)
                    kwargs["pnginfo"] = text
                if fmt in {"GIF", "JPEG"} and first_info.get("comment"):
                    kwargs["comment"] = first_info["comment"]
                emit(
                    warning="Metadata is preserved where the output format supports it; not every field is portable."
                )
            if animated:
                kwargs.update(save_all=True, append_images=frames[1:])
                if fmt != "TIFF":
                    kwargs.update(duration=durations, loop=first_info.get("loop", 0))
                    if fmt == "GIF":
                        kwargs["disposal"] = 2
                    elif fmt == "PNG" and default_image:
                        kwargs.update(default_image=True, duration=durations[1:])
            frames[0].save(target, format=fmt, **kwargs)
            for frame in frames:
                frame.close()
    if not Path(target).stat().st_size:
        raise ValueError("The image encoder returned an empty file.")
    emit(progress=1.0)
