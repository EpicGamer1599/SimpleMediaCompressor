from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import asdict
from pathlib import Path

import pygame
from PIL import Image, ImageOps

from . import metadata
from .ffmpeg import AUDIO_CODECS, VIDEO_CODECS, detect, probe_media
from .filesystem import scan_folder, size_text
from .gui.ui import (
    ACCENT,
    BG,
    BORDER,
    FAINT,
    MUTED,
    PANEL,
    SIDEBAR,
    TEXT,
    UI,
    YELLOW,
)
from .models import (
    ACTIVE,
    AudioOptions,
    ImageOptions,
    Job,
    OutputOptions,
    VideoOptions,
    media_type,
)
from .queue import QueueManager
from .storage import Store

log = logging.getLogger(__name__)
PAGES = ["Dashboard", "Compress", "Queue", "History", "Settings", "About"]
SUBTITLES = {
    "Dashboard": "A little less weight. A lot more room.",
    "Compress": "Your media, made lighter. Set it up once, then let it run.",
    "Queue": "Every file. Every detail. Everything under control.",
    "History": "A record of the space you’ve made.",
    "Settings": "Make yourself at home.",
    "About": "Small app. More room for the things you love.",
}


class App:
    def __init__(self, directory, args):
        pygame.display.init()
        pygame.font.init()
        width, height = (int(v) for v in args.size.lower().split("x"))
        self.screen = pygame.display.set_mode((max(980, width), max(700, height)), pygame.RESIZABLE)
        pygame.display.set_caption(f"{metadata.NAME} · v{metadata.VERSION}")
        icon = pygame.Surface((48, 48), pygame.SRCALPHA)
        pygame.draw.rect(icon, ACCENT, (2, 2, 44, 44), border_radius=13)
        pygame.draw.lines(icon, BG, False, [(12, 13), (22, 23), (12, 23)], 4)
        pygame.draw.lines(icon, BG, False, [(36, 35), (26, 25), (36, 25)], 4)
        pygame.display.set_icon(icon)
        self.store = Store(directory)
        self.settings = self.store.settings
        self.manager = QueueManager(self.store)
        self.ui = UI(self.screen, self.clipboard_get, self.clipboard_set)
        self.args, self.page = args, args.page
        self.running = True
        self.messages = queue.Queue()
        self.notices = []
        self.modal = None
        self.detail_id = ""
        self.dialog_busy = False
        self.detecting = False
        self.staged: list[tuple[str, str]] = []
        self.selected_kind = "image"
        self.image_options = asdict(
            ImageOptions(
                quality=self.settings["image_quality"],
                format=self.settings["image_format"],
                strip_metadata=not self.settings["preserve_metadata"],
            )
        )
        self.video_options = asdict(
            VideoOptions(
                quality=self.settings["video_quality"],
                format=self.settings["video_format"],
                strip_metadata=not self.settings["preserve_metadata"],
            )
        )
        self.audio_options = asdict(
            AudioOptions(
                bitrate=self.settings["audio_bitrate"],
                format=self.settings["audio_format"],
                strip_metadata=not self.settings["preserve_metadata"],
            )
        )
        self.set_format("video", self.video_options["format"])
        self.set_format("audio", self.audio_options["format"])
        self.output_options = asdict(OutputOptions(directory=self.settings["output_directory"]))
        self.bulk = {"recursive": True, "keep_structure": True, "skip": True}
        self.scan = None
        self.scan_cancel = threading.Event()
        self.bulk_open = False
        self.advanced = False
        self.jobs, self.history = [], []
        self.library_filter = "All"
        self.search = ""
        self.previews = {}
        self.preview_pending = set()
        self.media_info = {}
        self.info_pending = set()
        self.last_snapshot = 0
        self.snapshot_pending = False
        self.io_threads = []
        self.last_settings_save = 0
        self.settings_dirty = False
        self.page_started = time.monotonic()
        self.detect_ffmpeg()
        if args.files:
            self.stage(args.files)
        if self.store.warning:
            self.notify(self.store.warning, "warning")
        if self.settings["start_minimized"] and not args.screenshot:
            pygame.display.iconify()

    def notify(self, message, kind="info"):
        self.notices.append((str(message), kind, time.monotonic()))
        self.notices = self.notices[-3:]

    def navigate(self, page):
        self.page = page
        self.ui.scroll = 0
        self.ui.focus = ""
        self.ui.dropdown = None
        self.ui.hits = []
        self.page_started = time.monotonic()
        self.library_filter, self.search = "All", ""

    def setting(self, key, value):
        self.settings[key] = value
        self.settings_dirty = True
        self.last_settings_save = time.monotonic()
        if key == "image_quality":
            self.image_options["quality"] = value
        elif key == "video_quality":
            self.video_options["quality"] = value
        elif key == "audio_bitrate":
            self.audio_options["bitrate"] = value
        elif key in {"image_format", "video_format", "audio_format"}:
            self.set_format(key.split("_")[0], value)
        elif key == "preserve_metadata":
            for options in (self.image_options, self.video_options, self.audio_options):
                options["strip_metadata"] = not value

    def options(self, kind):
        return getattr(self, kind + "_options")

    def set_format(self, kind, value):
        o = self.options(kind)
        o["format"] = value
        if kind == "audio":
            o["codec"] = AUDIO_CODECS[value]
            if o["codec"] not in {"libmp3lame", "libvorbis"}:
                o["quality_mode"] = False
        elif kind == "video":
            o["codec"] = VIDEO_CODECS[value][0]
            o["audio_codec"] = "libopus" if value == "webm" else "aac"
            o["hardware"] = "Off"
        elif o.get("lossless") and value not in {"png", "webp", "tiff", "bmp"}:
            o["lossless"] = False

    def choose(self, purpose, kind="all"):
        if self.dialog_busy:
            return
        self.dialog_busy = True
        self.ui.dropdown = None
        initial = self.output_options["directory"] or str(Path.home())
        owner = pygame.display.get_wm_info().get("window", 0)

        def worker():
            try:
                from .dialogs import pick, pick_in_process

                result = (
                    pick(purpose, kind, initial, owner)
                    if os.name == "nt"
                    else pick_in_process(purpose, kind, initial, self.store.directory)
                )
                self.messages.put(("dialog", (purpose, result)))
            except Exception as error:
                self.messages.put(
                    (
                        "dialog_error",
                        "The native picker could not open. Drag files into the window as a fallback. "
                        + str(error),
                    )
                )

        threading.Thread(target=worker, name="native-picker", daemon=True).start()

    def stage(self, paths, root=""):
        # Stat and folder discovery can block on network drives; keep them off UI.
        self.navigate("Compress")

        def worker():
            accepted, rejected = [], 0
            for value in paths:
                path = Path(value).expanduser().absolute()
                if path.is_dir():
                    self.messages.put(("folder_drop", str(path)))
                elif media_type(path) and path.is_file():
                    accepted.append((str(path), root))
                else:
                    rejected += 1
            self.messages.put(("staged", (accepted, rejected)))

        threading.Thread(target=worker, daemon=True).start()

    def start_scan(self, root):
        if self.scan:
            self.notify("A folder scan is already running.", "warning")
            return
        self.navigate("Compress")
        self.bulk_open = True
        self.scan_cancel.clear()
        self.scan = {"root": root, "visited": 0, "found": 0}
        recursive, skip = self.bulk["recursive"], self.bulk["skip"]
        excluded = None
        if not self.output_options["source_folder"] and self.output_options["directory"]:
            excluded = Path(self.output_options["directory"])
            if self.output_options["create_folder"]:
                excluded /= "Compressed"

        def worker():
            try:
                files, errors = scan_folder(
                    Path(root),
                    recursive,
                    skip,
                    self.scan_cancel,
                    lambda v, f: self.messages.put(("scan_progress", (v, f))),
                    excluded,
                )
                self.messages.put(("scan_done", (root, files, errors, self.scan_cancel.is_set())))
            except Exception as error:
                self.messages.put(("scan_error", str(error)))

        threading.Thread(target=worker, name="folder-scan", daemon=True).start()

    def enqueue(self):
        if not self.staged:
            self.notify("Add some media first.", "warning")
            return
        if (
            not self.output_options["source_folder"]
            and not self.output_options["directory"].strip()
        ):
            self.notify("Choose an output folder or use the source folder.", "warning")
            return
        if (
            self.image_options["resize"]
            and min(self.image_options["width"], self.image_options["height"]) < 1
        ):
            self.notify("Enter a valid maximum width and height.", "warning")
            return
        if self.output_options["overwrite"]:
            self.confirm(
                "Replace existing outputs?",
                "Existing files with the generated _compressed name may be replaced. Source files are always preserved.",
                self._enqueue,
                "Replace outputs",
            )
        else:
            self._enqueue()

    def _enqueue(self):
        jobs = []
        for source, root in self.staged:
            kind = media_type(source)
            output = dict(self.output_options)
            output["keep_structure"] = self.bulk["keep_structure"]
            jobs.append(Job(source, kind, dict(self.options(kind)), output, root))
        # Queue persistence and source size discovery are I/O work too.
        self.staged = []

        def worker():
            try:
                for job in jobs:
                    try:
                        job.original_size = Path(job.source).stat().st_size
                    except OSError:
                        pass
                self.manager.add(jobs)
                self.messages.put(("queued", len(jobs)))
            except Exception as error:
                self.messages.put(("error", str(error)))

        thread = threading.Thread(target=worker, daemon=True)
        self.io_threads.append(thread)
        thread.start()
        if self.settings["remember_output"]:
            self.setting("output_directory", self.output_options["directory"])
        self.navigate("Queue")

    def detect_ffmpeg(self):
        if self.detecting:
            return
        self.detecting = True
        manual = self.settings["ffmpeg_path"]

        def worker():
            self.messages.put(("ffmpeg", detect(manual)))

        threading.Thread(target=worker, daemon=True).start()

    def confirm(self, title, message, action, button="Confirm"):
        self.modal = (title, message, action, button)
        self.ui.dropdown = None
        self.ui.focus = ""

    def remove_job(self, job):
        def action():
            self.manager.remove(job.id)

        if self.settings["confirm_delete"]:
            self.confirm(
                "Remove from queue?",
                "This removes the queue entry. Your media files and completed history are kept.",
                action,
                "Remove",
            )
        else:
            action()

    def clear_history(self):
        self.confirm(
            "Clear compression history?",
            "This permanently clears local job records and statistics. Media files are kept.",
            self.manager.clear_history,
            "Clear history",
        )

    def clipboard_get(self):
        try:
            return pygame.scrap.get_text()
        except pygame.error:
            return ""

    def clipboard_set(self, text):
        try:
            pygame.scrap.put_text(str(text))
        except pygame.error:
            self.notify("The system clipboard is unavailable.", "warning")

    def copy_error(self, job):
        self.clipboard_set(job.error)
        self.notify("Technical error copied.")

    def open_folder(self, value):
        path = Path(value)
        folder = path if path.is_dir() else path.parent
        if not folder.is_dir():
            self.notify("This folder no longer exists.", "warning")
            return
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", str(folder.resolve())])
        else:
            subprocess.Popen(
                [
                    "open" if sys.platform == "darwin" else "xdg-open",
                    str(folder.resolve()),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def open_url(self, url):
        if url.startswith(("https://", "http://")):
            webbrowser.open(url)
        else:
            self.notify(
                "Project links have not been configured yet. Set them in simplemedia/metadata.py."
            )

    def preview(self, path):
        if path in self.previews:
            return self.previews[path]
        if path not in self.preview_pending and media_type(path) == "image":
            self.preview_pending.add(path)

            def worker():
                try:
                    with Image.open(path) as original:
                        dimensions = f"{original.width:,} × {original.height:,}"
                        original.draft("RGB", (460, 260))
                        original.thumbnail((460, 460))
                        image = ImageOps.exif_transpose(original)
                        image.thumbnail((460, 260))
                        image = image.convert("RGBA")
                        result = (image.tobytes(), image.size, dimensions)
                    self.messages.put(("preview", (path, result)))
                except Exception:
                    self.messages.put(("preview", (path, None)))

            threading.Thread(target=worker, daemon=True).start()
        return None

    def inspect_media(self, path):
        if path in self.media_info:
            return self.media_info[path]
        if path not in self.info_pending and self.manager.ffmpeg.available:
            self.info_pending.add(path)
            info = self.manager.ffmpeg

            def worker():
                try:
                    result = probe_media(info, path)
                except Exception:
                    result = {}
                self.messages.put(("media_info", (path, result)))

            threading.Thread(target=worker, daemon=True).start()
        return {}

    def request_quit(self):
        if any(j.status in ACTIVE for j in self.jobs):
            self.confirm(
                "Stop processing and exit?",
                "Active encoders will stop and partial outputs will be removed. Unfinished jobs will be available to restart next time.",
                lambda: setattr(self, "running", False),
                "Stop and exit",
            )
        else:
            self.running = False

    def poll(self):
        while True:
            try:
                kind, payload = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "ffmpeg":
                self.manager.ffmpeg = payload
                self.detecting = False
            elif kind == "dialog":
                self.dialog_busy = False
                purpose, result = payload
                if result:
                    if purpose == "files":
                        self.stage(result)
                    elif purpose == "folder":
                        self.start_scan(result)
                    elif purpose == "output":
                        self.output_options.update(directory=result, source_folder=False)
                    elif purpose == "ffmpeg":
                        self.setting("ffmpeg_path", result)
                        self.detect_ffmpeg()
            elif kind == "staged":
                accepted, rejected = payload
                seen = {source for source, root in self.staged}
                self.staged.extend(
                    item for item in accepted if item[0] not in seen and not seen.add(item[0])
                )
                if accepted:
                    self.selected_kind = media_type(accepted[0][0])
                if rejected:
                    self.notify(f"Skipped {rejected} unsupported or missing file(s).", "warning")
            elif kind == "folder_drop":
                self.start_scan(payload)
            elif kind == "scan_progress" and self.scan:
                self.scan.update(visited=payload[0], found=payload[1])
            elif kind == "scan_done":
                root, files, errors, cancelled = payload
                self.scan = None
                if not cancelled:
                    seen = {source for source, _ in self.staged}
                    self.staged.extend((p, root) for p in files if p not in seen)
                    if files:
                        self.selected_kind = media_type(files[0])
                    self.notify(
                        f"Found {len(files):,} supported files."
                        + (f" {len(errors)} folders could not be read." if errors else "")
                    )
                else:
                    self.notify("Folder scan cancelled.")
            elif kind == "preview":
                path, result = payload
                self.preview_pending.discard(path)
                if len(self.previews) > 20:
                    self.previews.pop(next(iter(self.previews)))
                self.previews[path] = (
                    (pygame.image.frombytes(result[0], result[1], "RGBA"), result[2])
                    if result
                    else None
                )
            elif kind == "media_info":
                path, info = payload
                self.media_info[path] = info
                self.info_pending.discard(path)
            elif kind == "queued":
                self.notify(f"{payload} file(s) added to the queue.")
                self.last_snapshot = 0
            elif kind == "snapshot":
                self.jobs, self.history = payload
                self.snapshot_pending = False
            elif kind == "snapshot_error":
                self.snapshot_pending = False
                self.notify(payload, "error")
            else:
                if kind == "dialog_error":
                    self.dialog_busy = False
                if kind == "scan_error":
                    self.scan = None
                self.notify(payload, "error")
        while True:
            try:
                kind, payload = self.manager.events.get_nowait()
            except queue.Empty:
                break
            if kind == "complete":
                completed = [j for j in payload if j["status"] == "Completed"]
                before = sum(j["original_size"] for j in completed)
                after = sum(j["output_size"] for j in completed)
                failed = sum(j["status"] == "Failed" for j in payload)
                cancelled = sum(j["status"] == "Cancelled" for j in payload)
                self.notify(
                    f"Queue finished · {len(completed)} completed, {failed} failed, {cancelled} cancelled. {size_text(before)} → {size_text(after)} · {size_text(before - after)} saved."
                )
            else:
                self.notify(payload, kind)
        current = time.monotonic()
        if current - self.last_snapshot > 0.25 and not self.snapshot_pending:
            self.snapshot_pending = True

            def snapshot():
                try:
                    self.messages.put(
                        ("snapshot", (self.manager.snapshot(), self.store.load_jobs()))
                    )
                except Exception as error:
                    self.messages.put(("snapshot_error", str(error)))

            thread = threading.Thread(target=snapshot, daemon=True)
            self.io_threads = [t for t in self.io_threads if t.is_alive()]
            self.io_threads.append(thread)
            thread.start()
            self.last_snapshot = current
        if self.settings_dirty and current - self.last_settings_save > 0.5:
            try:
                self.store.save_settings()
            except OSError as error:
                log.warning("Settings could not be saved (%s)", type(error).__name__)
                self.notify(
                    "Settings could not be saved. Check disk space and data folder permissions.",
                    "error",
                )
            self.settings_dirty = False

    def draw_shell(self):
        ui = self.ui
        width, height = self.screen.get_size()
        side = 216 if width >= 1100 else 190
        self.side = side
        pygame.draw.rect(self.screen, SIDEBAR, (0, 0, side, height))
        pygame.draw.line(self.screen, BORDER, (side, 0), (side, height))
        ui.panel((22, 25, 39, 39), ACCENT, False, 11)
        ui.icon("Compress", (41, 44), BG, 24)
        ui.text("SimpleMedia", 72, 25, 19, TEXT, True)
        ui.text("COMPRESSURE", 73, 48, 10, MUTED, True)
        ui.text("WORKSPACE", 25, 108, 10, FAINT, True)
        for index, page in enumerate(PAGES):
            y = 137 + index * 52
            rect = pygame.Rect(14, y, side - 28, 43)
            selected = self.page == page
            if selected:
                ui.panel(rect, (30, 54, 54), False, 9)
                pygame.draw.rect(self.screen, ACCENT, (14, y + 12, 3, 19), border_radius=2)
            elif rect.collidepoint(ui.mouse):
                ui.panel(rect, PANEL, False, 9)
            ui.icon(page, (38, y + 21), ACCENT if selected else MUTED, 19)
            ui.text(page, 60, y + 11, 16, ACCENT if selected else MUTED, selected)
            ui.register("nav:" + page, rect, lambda page=page: self.navigate(page))
        ui.panel((16, height - 160, side - 32, 92), (19, 36, 39), False, 12)
        ui.icon("check", (35, height - 135), ACCENT, 17)
        ui.text("Private by design", 51, height - 145, 13, TEXT, True)
        ui.wrap(
            "Your files stay on your device. Always.",
            (29, height - 115, side - 56, 42),
            12,
            MUTED,
            2,
        )
        ui.text("v" + metadata.VERSION, 25, height - 43, 12, FAINT)
        ui.text("Made to make room.", 25, height - 25, 10, FAINT)
        x = side + 30
        ui.text(self.page, x, 25, 29, TEXT, True)
        ui.text(SUBTITLES[self.page], x, 69, 14, MUTED, max_width=width - x - 30)
        state = (
            "Checking FFmpeg…"
            if self.detecting
            else "FFmpeg ready"
            if self.manager.ffmpeg.available
            else "Images ready · FFmpeg missing"
        )
        state_color = ACCENT if self.manager.ffmpeg.available else YELLOW
        badge_width = ui.font(12, True).size(state)[0] + 25
        ui.badge(state, width - badge_width - 30, 32, state_color)
        self.content = pygame.Rect(x, 113, width - x - 30, height - 149)
        ui.viewport = self.content
        self.screen.set_clip(self.content)

    def draw_modal(self):
        if not self.modal:
            return
        ui = self.ui
        shade = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 175))
        self.screen.blit(shade, (0, 0))
        ui.hits = []
        ui.dropdown = None
        title, message, action, button = self.modal
        rect = pygame.Rect(0, 0, 560, 290)
        rect.center = self.screen.get_rect().center
        ui.panel(rect)
        ui.text(title, rect.x + 28, rect.y + 27, 23, TEXT, True)
        ui.wrap(message, (rect.x + 28, rect.y + 79, rect.w - 56, 110), 16, MUTED, 5)
        ui.button(
            "modal:no",
            "Cancel",
            (rect.right - 264, rect.bottom - 65, 105, 39),
            lambda: setattr(self, "modal", None),
        )

        def confirm():
            self.modal = None
            action()

        ui.button(
            "modal:yes",
            button,
            (rect.right - 148, rect.bottom - 65, 120, 39),
            confirm,
            "primary",
        )

    def draw(self):
        from .gui import compress, dashboard, library, settings

        ui = self.ui
        ui.begin()
        if self.settings["theme"] == "Graphite":
            self.screen.fill((22, 24, 28))
        self.draw_shell()
        x, y, w, h = self.content
        y -= int(ui.scroll)
        if self.page == "Dashboard":
            bottom = dashboard.draw(self, x, y, w)
        elif self.page == "Compress":
            bottom = compress.draw(self, x, y, w)
        elif self.page in {"Queue", "History"}:
            bottom = library.draw(self, x, y, w, self.page == "History")
        elif self.page == "Settings":
            bottom = settings.draw(self, x, y, w)
        else:
            bottom = settings.about(self, x, y, w)
        ui.max_scroll = max(0, bottom + int(ui.scroll) - self.content.bottom + 20)
        ui.scroll = min(ui.scroll, ui.max_scroll)
        self.screen.set_clip(None)
        if ui.max_scroll:
            track = pygame.Rect(self.screen.get_width() - 13, self.content.y, 4, self.content.h)
            thumb_h = max(30, int(track.h * track.h / (track.h + ui.max_scroll)))
            thumb_y = track.y + int((track.h - thumb_h) * ui.scroll / ui.max_scroll)
            pygame.draw.rect(self.screen, BORDER, (track.x, thumb_y, 4, thumb_h), border_radius=2)
        footer = pygame.Rect(
            self.side + 1,
            self.screen.get_height() - 32,
            self.screen.get_width() - self.side,
            32,
        )
        pygame.draw.rect(self.screen, BG, footer)
        pygame.draw.line(self.screen, BORDER, footer.topleft, footer.topright)
        active = sum(j.status in ACTIVE for j in self.jobs)
        waiting = sum(j.status == "Waiting" for j in self.jobs)
        status = (
            "Queue paused"
            if self.manager.paused
            else f"{active} processing · {waiting} waiting"
            if active or waiting
            else "Ready when you are"
        )
        ui.text(status, footer.x + 22, footer.y + 8, 11, MUTED)
        shortcut = "Ctrl+O  Add files     Ctrl+Enter  Start all     Drop files anywhere"
        ui.text(
            shortcut,
            footer.right - ui.font(11).size(shortcut)[0] - 22,
            footer.y + 8,
            11,
            FAINT,
        )
        if self.detail_id:
            library.detail(self)
        ui.finish()
        self.notices = [notice for notice in self.notices if time.monotonic() - notice[2] < 9]
        if self.notices and not self.modal:
            message, kind, created = self.notices[-1]
            rect = pygame.Rect(
                self.side + 28,
                self.screen.get_height() - 128,
                self.screen.get_width() - self.side - 56,
                79,
            )
            ui.panel(rect, (28, 47, 45) if kind == "info" else (49, 37, 39), True, 12)
            pygame.draw.rect(
                self.screen,
                ACCENT if kind == "info" else YELLOW,
                (rect.x, rect.y + 15, 3, rect.h - 30),
                border_radius=2,
            )
            ui.wrap(message, (rect.x + 18, rect.y + 12, rect.w - 58, 60), 14, TEXT, 2)
            ui.button(
                "notice:close",
                "×",
                (rect.right - 35, rect.y + 10, 25, 25),
                lambda: self.notices.clear(),
            )
        self.draw_modal()
        pygame.display.flip()

    def run(self):
        clock = pygame.time.Clock()
        frames = 0
        try:
            while self.running:
                for event in pygame.event.get():
                    try:
                        if event.type == pygame.QUIT:
                            self.request_quit()
                        elif event.type == pygame.VIDEORESIZE:
                            self.screen = pygame.display.set_mode(
                                (max(980, event.w), max(700, event.h)), pygame.RESIZABLE
                            )
                            self.ui.screen = self.screen
                            self.ui.dropdown = None
                        elif event.type == pygame.DROPFILE:
                            self.stage([event.file])
                        elif (
                            event.type == pygame.KEYDOWN
                            and event.key == pygame.K_ESCAPE
                            and self.modal
                        ):
                            self.modal = None
                        elif (
                            event.type == pygame.KEYDOWN
                            and event.key == pygame.K_ESCAPE
                            and self.detail_id
                            and not self.ui.dropdown
                        ):
                            self.detail_id = ""
                        elif (
                            event.type == pygame.KEYDOWN
                            and event.mod & pygame.KMOD_CTRL
                            and not self.modal
                            and not self.detail_id
                        ):
                            if event.key == pygame.K_o:
                                self.choose("folder" if event.mod & pygame.KMOD_SHIFT else "files")
                            elif event.key == pygame.K_RETURN:
                                self.manager.start()
                            elif pygame.K_1 <= event.key <= pygame.K_6:
                                self.navigate(PAGES[event.key - pygame.K_1])
                            else:
                                self.ui.handle(event)
                        else:
                            self.ui.handle(event)
                    except Exception as error:
                        log.exception("UI action failed")
                        self.notify(str(error), "error")
                self.poll()
                self.draw()
                frames += 1
                if self.args.screenshot and frames >= 40 and (not self.detecting or frames >= 600):
                    Path(self.args.screenshot).parent.mkdir(parents=True, exist_ok=True)
                    pygame.image.save(self.screen, self.args.screenshot)
                    break
                clock.tick(60)
        finally:
            self.scan_cancel.set()
            for thread in self.io_threads:
                thread.join(timeout=15)
            self.manager.shutdown()
            self.store.save_settings()
            self.store.close()
            pygame.quit()
