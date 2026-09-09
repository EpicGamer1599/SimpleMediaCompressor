from pathlib import Path

import PIL
import pygame

from .. import metadata
from .ui import ACCENT, FAINT, MUTED, TEXT, YELLOW


def draw(app, x, y, w):
    ui = app.ui
    settings = app.settings
    col = (w - 64) // 2
    xx = x + 22
    right = xx + col + 20
    ui.panel((x, y, w, 297))
    ui.text("General", xx, y + 19, 20, TEXT, True)
    ui.select(
        "settings:theme",
        "Theme",
        (xx, y + 64, col, 64),
        settings["theme"],
        ["Midnight", "Graphite"],
        lambda v: app.setting("theme", v),
    )
    ui.select(
        "settings:jobs",
        "Maximum simultaneous jobs",
        (right, y + 64, col, 64),
        settings["max_jobs"],
        [
            (1, "1 · quiet"),
            (2, "2 · recommended"),
            (3, "3"),
            (4, "4 · higher resource use"),
        ],
        lambda v: app.setting("max_jobs", v),
        "Limits encoder processes. Each FFmpeg job uses two codec threads; some encoders may allocate extra helper threads. Lower this for large images.",
    )
    fields = [
        ("start_minimized", "Start minimized"),
        ("remember_output", "Remember last output folder"),
        ("auto_start", "Automatically start added jobs"),
        ("confirm_delete", "Confirm before removing queue items"),
    ]
    for i, (key, label) in enumerate(fields):
        ui.checkbox(
            "settings:" + key,
            label,
            (xx + (i % 2) * (col + 20), y + 158 + (i // 2) * 49, col, 33),
            settings[key],
            lambda v, key=key: app.setting(key, v),
        )
    ui.text(
        "Changes are saved automatically. Unfinished jobs are restored stopped on startup.",
        xx,
        y + 263,
        12,
        FAINT,
        max_width=w - 44,
    )
    y += 317
    ui.panel((x, y, w, 377))
    ui.text("Compression defaults", xx, y + 19, 20, TEXT, True)
    ui.select(
        "settings:imagefmt",
        "Default image format",
        (xx, y + 64, col, 64),
        settings["image_format"],
        ["webp", "jpg", "png", "tiff", "gif", "bmp"],
        lambda v: app.setting("image_format", v),
    )
    ui.select(
        "settings:videofmt",
        "Default video format",
        (right, y + 64, col, 64),
        settings["video_format"],
        ["mp4", "mkv", "mov", "webm"],
        lambda v: app.setting("video_format", v),
    )
    ui.slider(
        "settings:imageq",
        "Default image quality",
        (xx, y + 158, col, 85),
        settings["image_quality"],
        1,
        100,
        lambda v: app.setting("image_quality", v),
        "Smaller file",
        "Better quality",
    )
    ui.slider(
        "settings:videoq",
        "Default video quality",
        (right, y + 158, col, 85),
        settings["video_quality"],
        0,
        100,
        lambda v: app.setting("video_quality", v),
        "Smaller file",
        "Better quality",
    )
    ui.select(
        "settings:audiofmt",
        "Default audio format",
        (xx, y + 259, col, 64),
        settings["audio_format"],
        ["mp3", "m4a", "aac", "ogg", "opus", "flac", "wav"],
        lambda v: app.setting("audio_format", v),
    )
    ui.select(
        "settings:ab",
        "Default audio bitrate",
        (right, y + 259, col, 64),
        settings["audio_bitrate"],
        [(v, f"{v} kbps") for v in [64, 96, 128, 160, 192, 256, 320]],
        lambda v: app.setting("audio_bitrate", v),
    )
    ui.checkbox(
        "settings:metadata",
        "Preserve metadata by default",
        (xx, y + 336, w - 44, 27),
        settings["preserve_metadata"],
        lambda v: app.setting("preserve_metadata", v),
        "Supported fields are retained when the output format allows. Metadata such as GPS may contain personal information.",
    )
    y += 398
    info = app.manager.ffmpeg
    ui.panel((x, y, w, 349))
    ui.text("FFmpeg", xx, y + 19, 20, TEXT, True)
    ui.badge(
        "DETECTED: YES" if info.available else "DETECTED: NO",
        x + w - 156,
        y + 19,
        ACCENT if info.available else YELLOW,
    )
    ui.text(
        "Video and audio engine · Images work independently with Pillow.",
        xx,
        y + 53,
        13,
        MUTED,
        max_width=w - 44,
    )
    ui.field(
        "settings:ffpath",
        "FFmpeg executable (blank = automatic detection)",
        (xx, y + 91, w - 44, 64),
        settings["ffmpeg_path"],
        lambda v: app.setting("ffmpeg_path", v),
    )
    ui.button(
        "settings:detect",
        "Detecting…" if app.detecting else "Detect FFmpeg",
        (xx, y + 173, 154, 38),
        app.detect_ffmpeg,
        enabled=not app.detecting,
    )
    ui.button(
        "settings:browse",
        "Select executable",
        (xx + 166, y + 173, 162, 38),
        lambda: app.choose("ffmpeg"),
    )
    ui.button(
        "settings:install",
        "Installation guide",
        (xx + 340, y + 173, 160, 38),
        lambda: app.open_url("https://ffmpeg.org/download.html"),
    )
    ui.text(
        info.version,
        xx,
        y + 229,
        13,
        ACCENT if info.available else YELLOW,
        max_width=w - 44,
    )
    ui.text(info.path or info.error, xx, y + 259, 12, MUTED, max_width=w - 44)
    ui.register(
        "settings:detectedpath",
        (xx, y + 253, w - 44, 27),
        lambda: app.clipboard_set(info.path or info.error),
        tooltip=info.path or info.error,
    )
    status = (
        f"{len(info.encoders)} encoders available · "
        + ("FFprobe ready" if info.probe else "FFprobe missing: time estimates unavailable")
        if info.available
        else "Install FFmpeg, restart the app, or select ffmpeg.exe above."
    )
    ui.text(status, xx, y + 292, 12, FAINT, max_width=w - 44)
    y += 372
    ui.text("Stored locally", x, y, 16, TEXT, True)
    ui.text(str(app.store.directory), x, y + 29, 12, MUTED, max_width=w - 173)
    ui.button(
        "settings:data",
        "Open data folder",
        (x + w - 156, y + 10, 156, 38),
        lambda: app.open_folder(str(app.store.directory)),
    )
    return y + 70


def about(app, x, y, w):
    ui = app.ui
    if getattr(app, "license_view", False):
        ui.button(
            "about:back",
            "← Back",
            (x, y, 95, 37),
            lambda: setattr(app, "license_view", False),
        )
        y += 62
        ui.text("MIT License", x, y, 29, TEXT, True)
        y += 54
        path = Path(__file__).resolve().parents[1] / "LICENSE.txt"
        text = path.read_text(encoding="utf-8")
        bottom = ui.wrap(text, (x, y, w, 1000), 16, TEXT)
        return bottom + 30
    ui.panel((x, y, w, 240), (21, 42, 43), False, 18)
    ui.panel((x + 26, y + 26, 64, 64), ACCENT, False, 18)
    ui.icon("Compress", (x + 58, y + 58), (12, 17, 25), 37)
    ui.text(metadata.NAME, x + 111, y + 29, 29, TEXT, True, max_width=w - 145)
    ui.text(
        "A simple, powerful media compression tool.",
        x + 112,
        y + 77,
        15,
        MUTED,
        max_width=w - 150,
    )
    ui.badge("VERSION " + metadata.VERSION, x + 27, y + 120, ACCENT)
    ui.text(metadata.TAGLINE, x + 27, y + 166, 28, TEXT, True)
    y += 268
    ui.text(
        "Built for your desktop. Designed for your files.",
        x,
        y,
        21,
        TEXT,
        True,
        max_width=w,
    )
    y += 42
    ui.wrap(
        "Bring images, videos and audio into one simple queue. Choose how much space to save, keep an eye on every job, and keep your originals. All compression happens on your device; no account or internet connection is required.",
        (x, y, w, 110),
        16,
        MUTED,
    )
    y += 114
    ui.panel((x, y, w, 228))
    rows = [
        ("Developer", metadata.AUTHOR),
        ("License", metadata.LICENSE),
        ("Interface", f"Pygame CE {pygame.version.ver}"),
        ("Image processing", f"Pillow {PIL.__version__}"),
        ("Video & audio", app.manager.ffmpeg.version),
        (
            "Repository",
            metadata.REPOSITORY_URL or "Not configured · set project metadata before publishing",
        ),
    ]
    for i, (label, value) in enumerate(rows):
        ui.text(label, x + 22, y + 17 + i * 34, 13, MUTED)
        ui.text(value, x + 167, y + 17 + i * 34, 13, TEXT, max_width=w - 190)
    y += 251
    ui.button(
        "about:github",
        "GitHub",
        (x, y, 110, 40),
        lambda: app.open_url(metadata.REPOSITORY_URL),
        enabled=bool(metadata.REPOSITORY_URL),
    )
    ui.button(
        "about:license",
        "View license",
        (x + 123, y, 136, 40),
        lambda: (setattr(app, "license_view", True), setattr(app.ui, "scroll", 0)),
    )
    ui.button(
        "about:updates",
        "Check for updates",
        (x + 272, y, 171, 40),
        lambda: app.open_url(
            metadata.RELEASES_URL
            or (
                metadata.REPOSITORY_URL.rstrip("/") + "/releases" if metadata.REPOSITORY_URL else ""
            )
        ),
        enabled=bool(metadata.RELEASES_URL or metadata.REPOSITORY_URL),
    )
    y += 65
    ui.text(
        "Online actions only open the configured project pages in your browser.",
        x,
        y,
        12,
        FAINT,
        max_width=w,
    )
    ui.text(
        "No automatic downloads, telemetry, or background update checks.",
        x,
        y + 24,
        12,
        FAINT,
        max_width=w,
    )
    return y + 65
