from pathlib import Path

from ..ffmpeg import AUDIO_CODECS, VIDEO_CODECS, crf
from ..filesystem import size_text
from ..images import mapped_quality
from ..models import media_type
from .ui import ACCENT, BG, FAINT, MUTED, TEXT


def number(options, key, value):
    try:
        options[key] = min(32768, max(0, int(value)))
    except ValueError:
        options[key] = 0


def draw(app, x, y, w):
    ui = app.ui
    ui.text("01", x, y + 2, 14, ACCENT, True)
    ui.text("Select media", x + 34, y, 20, TEXT, True)
    ui.text("Drag files into the window, or browse below.", x + 34, y + 30, 14, MUTED)
    y += 65
    bw = (w - 40) // 5
    for i, (label, kind, icon) in enumerate(
        [
            ("Add Image", "image", "image"),
            ("Add Video", "video", "video"),
            ("Add Audio", "audio", "audio"),
            ("Multiple Files", "all", "plus"),
            ("Add Folder", "folder", "folder"),
        ]
    ):

        def choose(kind=kind):
            if kind == "folder":
                app.bulk_open = True
                app.choose("folder")
            else:
                app.choose("files", kind)

        ui.button(
            "select:" + kind,
            label,
            (x + i * (bw + 10), y, bw, 42),
            choose,
            icon=icon if bw > 135 else None,
        )
    y += 60
    if app.dialog_busy:
        ui.text(
            "File picker open · Select your media in the system dialog.",
            x,
            y,
            14,
            ACCENT,
        )
        y += 32
    if app.scan:
        ui.panel((x, y, w, 82), (23, 45, 46), True, 12)
        ui.text("Discovering your media…", x + 20, y + 14, 17, TEXT, True)
        ui.text(
            f"{app.scan['visited']:,} files checked · {app.scan['found']:,} supported",
            x + 20,
            y + 45,
            14,
            MUTED,
        )
        ui.button(
            "scan:cancel",
            "Cancel scan",
            (x + w - 137, y + 21, 116, 38),
            app.scan_cancel.set,
        )
        y += 98
    if app.bulk_open:
        ui.panel((x, y, w, 122))
        ui.text("Bulk folder options", x + 20, y + 15, 16, TEXT, True)
        ui.text(
            "Choose these options before scanning. Generated Compressed folders are excluded.",
            x + 20,
            y + 42,
            12,
            MUTED,
            max_width=w - 35,
        )
        cw = (w - 40) // 3
        for index, (key, label) in enumerate(
            [
                ("recursive", "Include subfolders"),
                ("keep_structure", "Keep folder structure"),
                ("skip", "Skip compressed files"),
            ]
        ):
            ui.checkbox(
                "bulk:" + key,
                label,
                (x + 20 + index * cw, y + 75, cw - 10, 30),
                app.bulk[key],
                lambda value, key=key: app.bulk.update({key: value}),
                "Skip names ending in _compressed or _compressed_1, etc., when scanning."
                if key == "skip"
                else "Applied when scanning a folder or adding the discovered files to the queue.",
            )
        y += 139
    count = len(app.staged)
    ui.panel((x, y, w, 104 if count else 112), BG, True, 13)
    if count:
        kinds = {
            kind: sum(media_type(source) == kind for source, _ in app.staged)
            for kind in ["image", "video", "audio"]
        }
        ui.badge(f"{count:,} FILES SELECTED", x + 20, y + 17, ACCENT)
        ui.text(
            " · ".join(f"{n} {kind}{'s' if n != 1 else ''}" for kind, n in kinds.items() if n),
            x + 200,
            y + 21,
            13,
            MUTED,
            max_width=w - 320,
        )
        names = ", ".join(Path(source).name for source, _ in app.staged[:4]) + (
            f" +{count - 4} more" if count > 4 else ""
        )
        ui.text(names, x + 20, y + 59, 14, TEXT, max_width=w - 120)
        ui.button(
            "stage:clear",
            "Clear",
            (x + w - 83, y + 17, 63, 32),
            lambda: app.staged.clear(),
        )
        ui.button(
            "stage:review",
            "Review",
            (x + w - 95, y + 57, 75, 31),
            lambda: app.confirm(
                "Selected media",
                "\n".join(Path(source).name for source, _ in app.staged[:5])
                + (f"\n+ {count - 5} more files" if count > 5 else ""),
                lambda: None,
                "Done",
            ),
        )
    else:
        ui.icon("plus", (x + 39, y + 54), ACCENT, 25)
        ui.text("Good things come in smaller files.", x + 72, y + 26, 18, TEXT, True)
        ui.text("Select a file or a whole folder to get started.", x + 72, y + 59, 14, MUTED)
    y += 133
    ui.text("02", x, y + 2, 14, ACCENT, True)
    ui.text("Make it your own", x + 34, y, 20, TEXT, True)
    y += 43
    for i, (kind, label) in enumerate(
        [("image", "Images"), ("video", "Videos"), ("audio", "Audio")]
    ):
        ui.button(
            "type:" + kind,
            label,
            (x + i * 120, y, 109, 38),
            lambda kind=kind: setattr(app, "selected_kind", kind),
            "primary" if app.selected_kind == kind else "normal",
            icon=kind,
        )
    ui.text(
        "Each media type keeps its own settings.",
        x + 374,
        y + 11,
        12,
        MUTED,
        max_width=w - 374,
    )
    y += 54
    start = y
    # Settings card height follows the controls, including the expanded section.
    heights = {
        "image": 530 if app.image_options["resize"] else 440,
        "video": 535 if app.advanced else 342,
        "audio": 444,
    }
    height = heights[app.selected_kind]
    ui.panel((x, y, w, height))
    xx, ww = x + 22, w - 44
    col = (ww - 22) // 2
    right = xx + col + 22
    o = app.options(app.selected_kind)

    def setv(key):
        return lambda value: o.update({key: value})

    if app.selected_kind == "image":
        ui.select(
            "image:format",
            "Output format",
            (xx, y + 20, col, 64),
            o["format"],
            [
                ("webp", "WebP · smaller, with transparency"),
                ("jpg", "JPEG · photos"),
                ("png", "PNG · lossless"),
                ("tiff", "TIFF · lossless"),
                ("gif", "GIF · animation / palette"),
                ("bmp", "BMP · uncompressed"),
            ],
            lambda value: app.set_format("image", value),
        )
        ui.select(
            "image:mode",
            "Encoding mode",
            (right, y + 20, col, 64),
            o["lossless"],
            [(False, "Standard"), (True, "Lossless (PNG / WebP / TIFF / BMP)")],
            setv("lossless"),
            "Lossless preserves decoded pixel values before optional resizing or metadata removal. PNG/TIFF/BMP are always lossless here.",
        )

        def compression(value):
            o.update(compression=value, quality=mapped_quality(value))

        ui.slider(
            "image:compression",
            "Compression level",
            (xx, y + 108, ww, 85),
            o["compression"],
            0,
            100,
            compression,
            "0% · minimum compression",
            "100% · maximum compression",
            "JPEG maps this to quality 100–50 and chroma subsampling; PNG to effort 0–9; WebP to quality plus effort 0–6. Quality can be adjusted separately below.",
        )
        ui.slider(
            "image:quality",
            "Quality (JPEG / lossy WebP)",
            (xx, y + 209, col, 85),
            o["quality"],
            1,
            100,
            setv("quality"),
            "Smaller file",
            "Better quality",
        )
        ui.text("Output size", right, y + 209, 14, TEXT, True)
        ui.wrap(
            "Measured after encoding. Lossless formats may not get smaller; resize for larger reductions.",
            (right, y + 238, col, 65),
            13,
            MUTED,
            3,
        )
        ui.checkbox(
            "image:resize",
            "Resize image",
            (xx, y + 310, col, 30),
            o["resize"],
            setv("resize"),
        )
        ui.checkbox(
            "image:strip",
            "Strip metadata",
            (right, y + 310, col, 30),
            o["strip_metadata"],
            setv("strip_metadata"),
            "Removes EXIF, text and color profiles. EXIF orientation is applied to pixels first.",
        )
        offset = 0
        if o["resize"]:
            ui.field(
                "image:width",
                "Maximum width (px)",
                (xx, y + 354, col // 2 - 7, 64),
                o["width"],
                lambda v: number(o, "width", v),
            )
            ui.field(
                "image:height",
                "Maximum height (px)",
                (xx + col // 2 + 7, y + 354, col // 2 - 7, 64),
                o["height"],
                lambda v: number(o, "height", v),
            )
            ui.checkbox(
                "image:aspect",
                "Preserve aspect ratio",
                (right, y + 381, col, 30),
                o["aspect"],
                setv("aspect"),
                "Fits inside the bounds without upscaling. Turning this off stretches to the exact width and height.",
            )
            offset = 90
        ui.checkbox(
            "image:progressive",
            "Progressive JPEG",
            (xx, y + 356 + offset, col, 30),
            o["progressive"],
            setv("progressive"),
        )
        ui.checkbox(
            "image:flatten",
            "Flatten transparency on white",
            (right, y + 356 + offset, col, 30),
            o["flatten_alpha"],
            setv("flatten_alpha"),
            "Only needed when converting transparent media to JPEG or BMP. By default those conversions fail safely.",
        )
        ui.text(
            "Animation is preserved in supported formats. Transparency is protected by default.",
            xx,
            y + 402 + offset,
            12,
            FAINT,
            max_width=ww,
        )
    elif app.selected_kind == "video":
        ui.select(
            "video:format",
            "Output format",
            (xx, y + 20, col, 64),
            o["format"],
            ["mp4", "mkv", "mov", "webm"],
            lambda v: app.set_format("video", v),
        )
        ui.select(
            "video:preset",
            "Encoding speed",
            (right, y + 20, col, 64),
            o["preset"],
            [
                ("veryfast", "Very Fast"),
                ("fast", "Fast"),
                ("medium", "Medium · recommended"),
                ("slow", "Slow"),
                ("veryslow", "Very Slow"),
            ],
            setv("preset"),
            "Slower presets spend more processing time finding smaller encodings. Hardware encoding uses its own balanced preset.",
        )
        ui.slider(
            "video:quality",
            "Visual quality",
            (xx, y + 106, ww, 85),
            o["quality"],
            0,
            100,
            setv("quality"),
            "Smaller file",
            "Better quality",
            "Mapped to H.264/H.265 CRF 36–16, or VP9 CRF 48–18. Higher quality usually creates a larger output.",
        )
        ui.select(
            "video:resolution",
            "Resolution (maximum height)",
            (xx, y + 210, col, 64),
            o["resolution"],
            ["Original", "480p", "720p", "1080p", "1440p", "2160p"],
            setv("resolution"),
        )
        ui.select(
            "video:fps",
            "Frame rate",
            (right, y + 210, col, 64),
            o["fps"],
            ["Original", "24", "25", "30", "50", "60"],
            setv("fps"),
        )
        ui.button(
            "video:advanced",
            "Advanced settings  " + ("−" if app.advanced else "+"),
            (xx, y + 293, 193, 32),
            lambda: setattr(app, "advanced", not app.advanced),
        )
        if app.advanced:
            ui.select(
                "video:codec",
                "Video codec",
                (xx, y + 352, col, 64),
                o["codec"],
                VIDEO_CODECS[o["format"]],
                setv("codec"),
            )
            encoders = app.manager.ffmpeg.encoders
            hardware = [("Off", "Off · software encoding")] + [
                (name, name + " · driver required")
                for name in ["h264_nvenc", "h264_qsv", "h264_amf"]
                if name in encoders
            ]
            ui.select(
                "video:hardware",
                "Hardware encoder (H.264 only)",
                (right, y + 352, col, 64),
                o["hardware"],
                hardware,
                setv("hardware"),
                "Listed encoders exist in FFmpeg. A compatible GPU and driver are also required. If encoding fails, turn this off.",
            )
            ui.select(
                "video:audio",
                "Audio codec",
                (xx, y + 435, col // 2 - 6, 64),
                o["audio_codec"],
                ["aac", "libopus", "libvorbis"],
                setv("audio_codec"),
            )
            ui.select(
                "video:ab",
                "Audio bitrate",
                (xx + col // 2 + 6, y + 435, col // 2 - 6, 64),
                o["audio_bitrate"],
                [(v, f"{v} kbps") for v in [64, 96, 128, 160, 192, 256, 320]],
                setv("audio_bitrate"),
            )
            ui.checkbox(
                "video:remove",
                "Remove audio",
                (right, y + 424, col, 30),
                o["remove_audio"],
                setv("remove_audio"),
            )
            ui.checkbox(
                "video:metadata",
                "Strip metadata",
                (right, y + 458, col, 30),
                o["strip_metadata"],
                setv("strip_metadata"),
            )
            value = (
                round(48 - o["quality"] * 0.3) if o["codec"] == "libvpx-vp9" else crf(o["quality"])
            )
            ui.text(f"Encoder quality / CRF: {value}", right, y + 501, 12, ACCENT)
    else:
        ui.select(
            "audio:format",
            "Output format",
            (xx, y + 20, col, 64),
            o["format"],
            ["mp3", "m4a", "aac", "ogg", "opus", "flac", "wav"],
            lambda v: app.set_format("audio", v),
        )
        ui.select(
            "audio:bitrate",
            "Bitrate",
            (right, y + 20, col, 64),
            o["bitrate"],
            [(v, f"{v} kbps") for v in [64, 96, 128, 160, 192, 256, 320]],
            setv("bitrate"),
            "Higher bitrates preserve more detail. Ignored for FLAC/WAV and MP3/Vorbis quality mode.",
        )
        ui.select(
            "audio:rate",
            "Sample rate",
            (xx, y + 111, col, 64),
            o["sample_rate"],
            ["Original", "16000", "22050", "24000", "32000", "44100", "48000", "96000"],
            setv("sample_rate"),
        )
        ui.select(
            "audio:channels",
            "Channels",
            (right, y + 111, col, 64),
            o["channels"],
            ["Original", "Mono", "Stereo"],
            setv("channels"),
        )
        ui.select(
            "audio:codec",
            "Codec (matched to format)",
            (xx, y + 202, col, 64),
            o["codec"],
            [AUDIO_CODECS[o["format"]]],
            setv("codec"),
        )
        ui.checkbox(
            "audio:mode",
            "Use variable quality (MP3 / Vorbis)",
            (right, y + 225, col, 30),
            o["quality_mode"],
            setv("quality_mode"),
            "MP3: 0 best, 9 smallest. Vorbis: 0 smallest, 9 best. Other encoders ignore this option.",
        )
        ui.slider(
            "audio:quality",
            "Variable quality",
            (xx, y + 300, col, 85),
            o["quality"],
            0,
            9,
            setv("quality"),
            "0 · best MP3 / small Vorbis",
            "9 · small MP3 / best Vorbis",
        )
        ui.checkbox(
            "audio:metadata",
            "Strip metadata",
            (right, y + 308, col, 30),
            o["strip_metadata"],
            setv("strip_metadata"),
        )
        ui.text(
            "FLAC is lossless. WAV is uncompressed.",
            right,
            y + 356,
            12,
            MUTED,
            max_width=col,
        )
        audio_source = next(
            (source for source, _ in app.staged if media_type(source) == "audio"), None
        )
        estimate = "Size estimate needs a selected file with a readable duration."
        if audio_source:
            info = app.inspect_media(audio_source)
            try:
                duration = float(info.get("format", {}).get("duration", 0))
            except (ValueError, TypeError):
                duration = 0
            if duration and o["format"] not in {"flac", "wav"} and not o["quality_mode"]:
                estimated = duration * o["bitrate"] * 1000 / 8
                estimate = f"First file estimate: ≈ {size_text(estimated)} + container overhead. Actual size can vary."
            elif o["format"] in {"flac", "wav"} or o["quality_mode"]:
                estimate = "Final size is measured after encoding for lossless, PCM and variable-quality output."
        ui.text(estimate, xx, y + 409, 12, ACCENT, max_width=ww)
    y = start + height + 27
    ui.text("03", x, y + 2, 14, ACCENT, True)
    ui.text("A home for your lighter files", x + 34, y, 20, TEXT, True)
    y += 46
    ui.panel((x, y, w, 208))
    out = app.output_options
    ui.field(
        "output:path",
        "Output folder",
        (x + 22, y + 20, w - 160, 64),
        out["directory"],
        lambda value: out.update(directory=value),
        "Use an absolute path. Enable Use source folder to ignore this field.",
    )
    ui.button(
        "output:browse",
        "Browse",
        (x + w - 119, y + 45, 97, 38),
        lambda: app.choose("output"),
    )
    cw = (w - 44) // 2
    ui.checkbox(
        "output:source",
        "Use source folder",
        (x + 22, y + 103, cw, 30),
        out["source_folder"],
        lambda v: out.update(source_folder=v),
    )
    ui.checkbox(
        "output:create",
        "Create “Compressed” folder",
        (x + 22 + cw, y + 103, cw, 30),
        out["create_folder"],
        lambda v: out.update(create_folder=v),
    )
    ui.checkbox(
        "output:overwrite",
        "Overwrite existing output files",
        (x + 22, y + 148, cw, 30),
        out["overwrite"],
        lambda v: out.update(overwrite=v),
        "Only generated output names can be overwritten. Source files are always protected. You will confirm before adding jobs.",
    )
    ui.text(
        "Source files are always kept safe.",
        x + 22 + cw,
        y + 156,
        13,
        ACCENT,
        max_width=cw - 15,
    )
    y += 230
    ui.text(
        "Settings are copied into each job when you add it.",
        x,
        y + 15,
        13,
        MUTED,
        max_width=w - 247,
    )
    ui.button(
        "compress:enqueue",
        f"Add {count} file{'s' if count != 1 else ''} to queue",
        (x + w - 223, y, 223, 46),
        app.enqueue,
        "primary",
        "plus",
        enabled=count > 0,
    )
    return y + 60
