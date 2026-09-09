from dataclasses import asdict

import pytest
from PIL import Image, ImageChops, UnidentifiedImageError

from simplemedia.images import compress
from simplemedia.models import ImageOptions


def encode(source, target, **kwargs):
    messages = []
    compress(
        str(source),
        str(target),
        asdict(ImageOptions(**kwargs)),
        lambda **message: messages.append(message),
    )
    return messages


@pytest.mark.parametrize(
    "mode,format",
    [
        ("RGB", "jpg"),
        ("L", "jpg"),
        ("RGBA", "webp"),
        ("RGBA", "png"),
        ("RGB", "tiff"),
        ("RGB", "bmp"),
    ],
)
def test_image_formats(tmp_path, mode, format):
    source = tmp_path / "original.png"
    color = (40, 80, 120, 77) if mode == "RGBA" else 125 if mode == "L" else (40, 80, 120)
    Image.new(mode, (330, 220), color).save(source)
    before = source.read_bytes()
    target = tmp_path / ("result." + format)
    events = encode(source, target, format=format, resize=True, width=100, height=100)
    with Image.open(target) as result:
        assert result.size == (100, 67)
        result.load()
    assert source.read_bytes() == before
    assert events[-1]["progress"] == 1


def test_transparency_protected(tmp_path):
    source = tmp_path / "transparent.png"
    Image.new("RGBA", (50, 50), (200, 20, 90, 64)).save(source)
    output = tmp_path / "out.jpg"
    with pytest.raises(ValueError, match="transparency"):
        encode(source, output, format="jpg")
    assert not output.exists()
    messages = encode(source, output, format="jpg", flatten_alpha=True)
    assert any("warning" in m for m in messages)
    output2 = tmp_path / "out.png"
    encode(source, output2, format="png")
    with Image.open(output2) as result:
        assert result.getpixel((0, 0))[3] == 64


def test_exif_orientation_and_metadata(tmp_path):
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Test photographer"
    Image.new("RGB", (80, 40), "red").save(source, exif=exif)
    output = tmp_path / "out.jpg"
    encode(source, output, format="jpg", strip_metadata=True)
    with Image.open(output) as image:
        assert image.size == (40, 80)
        assert not image.getexif()
    encode(source, output, format="jpg", strip_metadata=False)
    with Image.open(output) as image:
        assert image.getexif()[315] == "Test photographer"
        assert image.getexif().get(274, 1) == 1


@pytest.mark.parametrize("fmt", ["gif", "webp", "png", "tiff"])
def test_animation_preserved(tmp_path, fmt):
    source = tmp_path / "animated.gif"
    frames = [Image.new("RGB", (40, 30), color) for color in ["red", "blue", "green"]]
    frames[0].save(source, save_all=True, append_images=frames[1:], duration=[80, 120, 160], loop=2)
    target = tmp_path / ("animation." + fmt)
    encode(source, target, format=fmt)
    with Image.open(target) as result:
        assert result.n_frames == 3
        if fmt in {"gif", "png"}:
            assert result.info["loop"] == 2
    with pytest.raises(ValueError, match="multiple frames"):
        encode(source, tmp_path / "bad.jpg", format="jpg")


def test_lossless_webp_pixels(tmp_path):
    source = tmp_path / "original.png"
    original = Image.effect_noise((130, 80), 35).convert("RGB")
    original.save(source)
    target = tmp_path / "out.webp"
    encode(source, target, lossless=True)
    with Image.open(target) as result:
        assert ImageChops.difference(original, result.convert("RGB")).getbbox() is None


def test_invalid_file(tmp_path):
    source = tmp_path / "corrupt.png"
    source.write_bytes(b"not an image")
    with pytest.raises(UnidentifiedImageError):
        encode(source, tmp_path / "out.webp")
