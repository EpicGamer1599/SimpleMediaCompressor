from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import pygame

BG = (12, 17, 25)
SIDEBAR = (16, 22, 32)
PANEL = (22, 30, 42)
RAISED = (29, 39, 53)
BORDER = (43, 55, 71)
TEXT = (233, 240, 248)
MUTED = (151, 168, 190)
FAINT = (113, 134, 158)
ACCENT = (102, 229, 190)
BLUE = (114, 169, 255)
YELLOW = (248, 198, 112)
RED = (250, 134, 143)


@dataclass
class Hit:
    key: str
    rect: pygame.Rect
    action: Callable | None
    kind: str = "button"
    value: str = ""
    tooltip: str = ""


class UI:
    def __init__(self, screen, clipboard_get, clipboard_set):
        self.screen = screen
        self.fonts = {}
        self.hits: list[Hit] = []
        self.previous: list[Hit] = []
        self.focus = ""
        self.editing = ""
        self.caret = 0
        self.select_all = False
        self.dropdown = None
        self.dropdown_offset = 0
        self.drag = ""
        self.hover_times = {}
        self.tip_since = time.monotonic()
        self.tip_key = ""
        self.mouse = (0, 0)
        self.clipboard_get = clipboard_get
        self.clipboard_set = clipboard_set
        self.scroll = 0
        self.max_scroll = 0
        self.viewport = pygame.Rect(0, 0, *screen.get_size())

    def font(self, size=16, bold=False):
        key = size, bold
        if key not in self.fonts:
            self.fonts[key] = pygame.font.SysFont(
                "Segoe UI,Inter,DejaVu Sans,Arial", size, bold=bold
            )
        return self.fonts[key]

    def text(self, text, x, y, size=16, color=TEXT, bold=False, max_width=None):
        font = self.font(size, bold)
        text = str(text).replace("\n", " ").replace("\r", " ")
        if max_width is not None and font.size(text)[0] > max_width:
            while text and font.size(text + "…")[0] > max_width:
                text = text[:-1]
            text += "…"
        image = font.render(text, True, color)
        self.screen.blit(image, (int(x), int(y)))
        return image.get_width()

    def wrap(self, value, rect, size=15, color=MUTED, max_lines=100):
        rect = pygame.Rect(rect)
        y = rect.y
        count = 0
        for paragraph in str(value).splitlines() or [""]:
            line = ""
            for word in paragraph.split(" "):
                if self.font(size).size(line + word)[0] > rect.w and line:
                    self.text(line, rect.x, y, size, color, max_width=rect.w)
                    y += size + 8
                    count += 1
                    line = ""
                if count >= max_lines:
                    return y
                line += word + " "
            self.text(line, rect.x, y, size, color, max_width=rect.w)
            y += size + 8
            count += 1
            if count >= max_lines:
                break
        return y

    def panel(self, rect, color=PANEL, border=True, radius=16):
        rect = pygame.Rect(rect)
        pygame.draw.rect(self.screen, color, rect, border_radius=radius)
        if border:
            pygame.draw.rect(self.screen, BORDER, rect, width=1, border_radius=radius)
        return rect

    def register(self, key, rect, action, kind="button", value="", tooltip=""):
        hit = pygame.Rect(rect).clip(self.screen.get_clip())
        if hit.w and hit.h:
            self.hits.append(Hit(key, hit, action, kind, value, tooltip))

    def icon(self, kind, center, color=ACCENT, size=22):
        x, y = center
        r = size // 2
        if kind in {"image", "Images"}:
            pygame.draw.rect(
                self.screen,
                color,
                (x - r, y - r + 2, size, size - 4),
                2,
                border_radius=4,
            )
            pygame.draw.circle(self.screen, color, (x + 4, y - 4), 2)
            pygame.draw.lines(
                self.screen,
                color,
                False,
                [
                    (x - r + 3, y + 5),
                    (x - 3, y - 1),
                    (x + 2, y + 4),
                    (x + 5, y + 1),
                    (x + r - 2, y + 5),
                ],
                2,
            )
        elif kind in {"video", "Videos"}:
            pygame.draw.rect(
                self.screen,
                color,
                (x - r, y - r + 2, size, size - 4),
                2,
                border_radius=4,
            )
            pygame.draw.polygon(self.screen, color, [(x - 3, y - 5), (x - 3, y + 5), (x + 5, y)])
        elif kind in {"audio", "Audio"}:
            for i, height in enumerate([7, 14, 22, 12, 6]):
                pygame.draw.line(
                    self.screen,
                    color,
                    (x - 10 + i * 5, y - height // 2),
                    (x - 10 + i * 5, y + height // 2),
                    2,
                )
        elif kind == "Dashboard":
            for dx in [-7, 5]:
                for dy in [-7, 5]:
                    pygame.draw.rect(
                        self.screen,
                        color,
                        (x + dx - 3, y + dy - 3, 8, 8),
                        2,
                        border_radius=2,
                    )
        elif kind in {"Queue", "History"}:
            for dy in [-7, 0, 7]:
                pygame.draw.line(self.screen, color, (x - 5, y + dy), (x + 9, y + dy), 2)
                pygame.draw.circle(self.screen, color, (x - 10, y + dy), 1)
        elif kind == "Compress":
            pygame.draw.lines(
                self.screen,
                color,
                False,
                [(x - 10, y - 8), (x - 3, y - 1), (x - 9, y - 1)],
                2,
            )
            pygame.draw.lines(
                self.screen,
                color,
                False,
                [(x + 10, y + 8), (x + 3, y + 1), (x + 9, y + 1)],
                2,
            )
        elif kind == "Settings":
            for dx, dy in [(-7, -4), (0, 5), (7, -1)]:
                pygame.draw.line(self.screen, color, (x + dx, y - 10), (x + dx, y + 10), 2)
                pygame.draw.circle(self.screen, color, (x + dx, y + dy), 3)
        elif kind == "folder":
            pygame.draw.lines(
                self.screen,
                color,
                True,
                [
                    (x - 11, y - 6),
                    (x - 3, y - 6),
                    (x, y - 3),
                    (x + 11, y - 3),
                    (x + 11, y + 9),
                    (x - 11, y + 9),
                ],
                2,
            )
        elif kind == "check":
            pygame.draw.lines(
                self.screen,
                color,
                False,
                [(x - 7, y), (x - 2, y + 5), (x + 8, y - 6)],
                2,
            )
        elif kind == "plus":
            pygame.draw.line(self.screen, color, (x - 7, y), (x + 7, y), 2)
            pygame.draw.line(self.screen, color, (x, y - 7), (x, y + 7), 2)
        else:
            pygame.draw.circle(self.screen, color, (x, y), r, 2)
            self.text("i", x - 2, y - 10, 16, color, True)

    def button(
        self,
        key,
        label,
        rect,
        action,
        style="normal",
        icon=None,
        enabled=True,
        tooltip="",
    ):
        rect = pygame.Rect(rect)
        hover = (
            enabled
            and rect.collidepoint(self.mouse)
            and self.screen.get_clip().collidepoint(self.mouse)
        )
        amount = self.hover_times.get(key, 0)
        amount += ((1 if hover else 0) - amount) * 0.24
        self.hover_times[key] = amount
        base = ACCENT if style == "primary" else (47, 30, 40) if style == "danger" else RAISED
        background = tuple(min(255, int(c + amount * 12)) for c in base)
        self.panel(rect, background, style != "primary", 9)
        color = BG if style == "primary" else RED if style == "danger" else TEXT
        if not enabled:
            color = FAINT
        tw = self.font(15, style == "primary").size(label)[0]
        start = rect.centerx - (tw + (28 if icon else 0)) // 2
        if icon:
            self.icon(icon, (start + 8, rect.centery), color, 18)
            start += 28
        self.text(
            label,
            start,
            rect.centery - 10,
            15,
            color,
            style == "primary",
            max_width=rect.w - 14,
        )
        if self.focus == key:
            pygame.draw.rect(self.screen, ACCENT, rect.inflate(4, 4), 1, border_radius=10)
        if enabled:
            self.register(key, rect, action, tooltip=tooltip)

    def checkbox(self, key, label, rect, value, action, tooltip=""):
        rect = pygame.Rect(rect)
        square = pygame.Rect(rect.x, rect.centery - 9, 18, 18)
        self.panel(square, ACCENT if value else BG, not value, 4)
        if value:
            self.icon("check", square.center, BG, 12)
        self.text(label, rect.x + 29, rect.centery - 10, 15, TEXT, max_width=rect.w - 30)
        if self.focus == key:
            pygame.draw.rect(self.screen, ACCENT, rect, 1, border_radius=4)
        self.register(key, rect, lambda: action(not value), tooltip=tooltip)

    def select(self, key, label, rect, value, options, action, tooltip=""):
        rect = pygame.Rect(rect)
        self.text(label, rect.x, rect.y, 13, MUTED, True)
        control = pygame.Rect(rect.x, rect.y + 25, rect.w, 38)
        self.panel(control, BG, True, 8)
        display = next(
            (str(v[1]) for v in options if isinstance(v, tuple) and v[0] == value),
            str(value),
        )
        self.text(display, control.x + 12, control.y + 9, 15, TEXT, max_width=control.w - 36)
        pygame.draw.lines(
            self.screen,
            MUTED,
            False,
            [
                (control.right - 22, control.centery - 2),
                (control.right - 17, control.centery + 3),
                (control.right - 12, control.centery - 2),
            ],
            2,
        )
        if self.focus == key:
            pygame.draw.rect(self.screen, ACCENT, control, 1, border_radius=8)

        def open_menu():
            if self.dropdown and self.dropdown[0] == key:
                self.dropdown = None
            else:
                self.dropdown = (key, control, options, action, value)
                self.dropdown_offset = 0

        self.register(key, control, open_menu, tooltip=tooltip)

    def field(self, key, label, rect, value, action, tooltip=""):
        rect = pygame.Rect(rect)
        self.text(label, rect.x, rect.y, 13, MUTED, True)
        control = pygame.Rect(rect.x, rect.y + 25, rect.w, 38)
        self.panel(control, BG, True, 8)
        if self.focus == key:
            pygame.draw.rect(self.screen, ACCENT, control, 1, border_radius=8)
            value = self.editing
        old_clip = self.screen.get_clip()
        self.screen.set_clip(control.inflate(-18, -4).clip(old_clip))
        offset = (
            max(0, self.font(15).size(str(value)[: self.caret])[0] - control.w + 30)
            if self.focus == key
            else 0
        )
        if self.focus == key and self.select_all:
            pygame.draw.rect(
                self.screen,
                (48, 85, 83),
                (
                    control.x + 10 - offset,
                    control.y + 7,
                    self.font(15).size(str(value))[0],
                    24,
                ),
            )
        self.text(value, control.x + 11 - offset, control.y + 9, 15)
        if self.focus == key and int(time.monotonic() * 2) % 2 == 0:
            cx = control.x + 11 - offset + self.font(15).size(str(value)[: self.caret])[0]
            pygame.draw.line(self.screen, ACCENT, (cx, control.y + 8), (cx, control.bottom - 8), 1)
        self.screen.set_clip(old_clip)
        self.register(key, control, action, "field", str(value), tooltip)

    def slider(self, key, label, rect, value, low, high, action, left="", right="", tooltip=""):
        rect = pygame.Rect(rect)
        self.text(label, rect.x, rect.y, 14, TEXT, True)
        self.text(str(value), rect.right - 40, rect.y, 14, ACCENT, True)
        track = pygame.Rect(rect.x + 5, rect.y + 38, rect.w - 10, 6)
        pygame.draw.rect(self.screen, BORDER, track, border_radius=3)
        x = track.x + int(track.w * (max(low, min(high, value)) - low) / (high - low))
        pygame.draw.rect(
            self.screen,
            ACCENT,
            (track.x, track.y, max(1, x - track.x), 6),
            border_radius=3,
        )
        pygame.draw.circle(self.screen, ACCENT, (x, track.centery), 8)
        pygame.draw.circle(self.screen, BG, (x, track.centery), 3)
        self.text(left, rect.x, rect.y + 58, 12, MUTED)
        self.text(right, rect.right - self.font(12).size(right)[0], rect.y + 58, 12, MUTED)
        self.register(
            key,
            (rect.x, rect.y + 24, rect.w, 30),
            lambda mx: action(
                round(low + (max(track.x, min(track.right, mx)) - track.x) / track.w * (high - low))
            ),
            "slider",
            str(value),
            tooltip,
        )

    def progress(self, rect, value, color=ACCENT):
        rect = pygame.Rect(rect)
        pygame.draw.rect(self.screen, BORDER, rect, border_radius=rect.h // 2)
        if value > 0:
            pygame.draw.rect(
                self.screen,
                color,
                (rect.x, rect.y, max(rect.h, int(rect.w * min(1, value))), rect.h),
                border_radius=rect.h // 2,
            )

    def badge(self, label, x, y, color=ACCENT):
        width = self.font(12, True).size(label)[0] + 25
        self.panel(
            (x, y, width, 25),
            tuple(int(c * 0.15 + BG[i] * 0.85) for i, c in enumerate(color)),
            False,
            6,
        )
        self.text(label, x + 12, y + 4, 12, color, True)
        return width

    def begin(self):
        self.previous = self.hits
        self.hits = []
        self.mouse = pygame.mouse.get_pos()
        self.screen.set_clip(None)
        self.screen.fill(BG)

    def handle(self, event):
        hits = self.hits
        if event.type == pygame.MOUSEWHEEL:
            if self.dropdown:
                self.dropdown_offset = max(
                    0,
                    min(
                        max(0, len(self.dropdown[2]) - 7),
                        self.dropdown_offset - event.y,
                    ),
                )
            else:
                self.scroll = max(0, min(self.max_scroll, self.scroll - event.y * 42))
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.select_all = False
            match = next(
                (hit for hit in reversed(hits) if hit.rect.collidepoint(event.pos)),
                None,
            )
            if self.dropdown and (match is None or not match.key.startswith("menu:")):
                self.dropdown = None
                return
            self.focus = match.key if match else ""
            if match:
                if match.kind == "field":
                    self.editing, self.caret = match.value, len(match.value)
                    pygame.key.start_text_input()
                elif match.kind == "slider":
                    self.drag = match.key
                    match.action(event.pos[0])
                elif match.action:
                    match.action()
            return
        if event.type == pygame.MOUSEBUTTONUP:
            self.drag = ""
        if event.type == pygame.MOUSEMOTION and self.drag:
            match = next((h for h in hits if h.key == self.drag), None)
            if match:
                match.action(event.pos[0])
        match = next((h for h in hits if h.key == self.focus), None)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
            focusable = [h for h in hits if h.kind != "slider"]
            if focusable:
                index = next((i for i, h in enumerate(focusable) if h.key == self.focus), -1)
                match = focusable[
                    (index + (-1 if event.mod & pygame.KMOD_SHIFT else 1)) % len(focusable)
                ]
                self.focus = match.key
                if match.kind == "field":
                    self.editing, self.caret = match.value, len(match.value)
                    self.select_all = True
            return
        if self.dropdown and event.type == pygame.KEYDOWN:
            key, rect, options, action, value = self.dropdown
            values = [o[0] if isinstance(o, tuple) else o for o in options]
            index = values.index(value) if value in values else 0
            if event.key in {pygame.K_DOWN, pygame.K_UP}:
                index = (index + (1 if event.key == pygame.K_DOWN else -1)) % len(values)
                self.dropdown = key, rect, options, action, values[index]
                self.dropdown_offset = max(0, min(max(0, len(values) - 7), index - 3))
            elif event.key in {pygame.K_RETURN, pygame.K_SPACE}:
                action(value)
                self.dropdown = None
            elif event.key == pygame.K_ESCAPE:
                self.dropdown = None
            return
        if match and match.kind == "field":
            if event.type == pygame.TEXTINPUT:
                self._insert(event.text)
                match.action(self.editing)
            elif event.type == pygame.KEYDOWN:
                ctrl = event.mod & pygame.KMOD_CTRL
                if ctrl and event.key == pygame.K_a:
                    self.select_all = True
                elif ctrl and event.key == pygame.K_c:
                    self.clipboard_set(self.editing)
                elif ctrl and event.key == pygame.K_v:
                    self._insert(self.clipboard_get().replace("\n", "").replace("\r", ""))
                elif event.key == pygame.K_BACKSPACE:
                    if self.select_all:
                        self.editing, self.caret = "", 0
                    elif self.caret:
                        self.editing = self.editing[: self.caret - 1] + self.editing[self.caret :]
                        self.caret -= 1
                    self.select_all = False
                elif event.key == pygame.K_DELETE:
                    if self.select_all:
                        self.editing, self.caret = "", 0
                    else:
                        self.editing = self.editing[: self.caret] + self.editing[self.caret + 1 :]
                    self.select_all = False
                elif event.key in {pygame.K_LEFT, pygame.K_RIGHT}:
                    self.caret = max(
                        0,
                        min(
                            len(self.editing),
                            self.caret + (-1 if event.key == pygame.K_LEFT else 1),
                        ),
                    )
                    self.select_all = False
                elif event.key == pygame.K_HOME:
                    self.caret = 0
                elif event.key == pygame.K_END:
                    self.caret = len(self.editing)
                elif event.key in {pygame.K_RETURN, pygame.K_ESCAPE}:
                    self.focus = ""
                match.action(self.editing)
        elif (
            match
            and event.type == pygame.KEYDOWN
            and event.key in {pygame.K_RETURN, pygame.K_SPACE}
            and match.kind == "button"
        ):
            match.action()

    def _insert(self, value):
        if self.select_all:
            self.editing, self.caret = "", 0
        value = value[: max(0, 4096 - len(self.editing))]
        self.editing = self.editing[: self.caret] + value + self.editing[self.caret :]
        self.caret += len(value)
        self.select_all = False

    def finish(self):
        self.screen.set_clip(None)
        if self.dropdown:
            key, rect, options, action, selected = self.dropdown
            visible = options[self.dropdown_offset : self.dropdown_offset + 7]
            height = len(visible) * 36 + 12
            y = (
                rect.bottom + 4
                if rect.bottom + height < self.screen.get_height() - 20
                else rect.top - height - 4
            )
            panel = self.panel((rect.x, y, rect.w, height), RAISED, True, 10)
            for index, option in enumerate(visible):
                value, label = option if isinstance(option, tuple) else (option, str(option))
                row = pygame.Rect(panel.x + 5, panel.y + 6 + index * 36, panel.w - 10, 34)
                if row.collidepoint(self.mouse) or value == selected:
                    self.panel(row, (43, 67, 67), False, 6)
                self.text(label, row.x + 9, row.y + 7, 14, TEXT, max_width=row.w - 18)

                def choose(value=value, action=action):
                    action(value)
                    self.dropdown = None

                self.register("menu:" + key + ":" + str(index), row, choose)
            return
        hovered = next((h for h in reversed(self.hits) if h.rect.collidepoint(self.mouse)), None)
        tip = hovered.tooltip if hovered else ""
        if tip != self.tip_key:
            self.tip_key, self.tip_since = tip, time.monotonic()
        if tip and time.monotonic() - self.tip_since > 0.7:
            width = min(380, self.screen.get_width() - 40)
            x = min(self.mouse[0] + 14, self.screen.get_width() - width - 16)
            y = min(self.mouse[1] + 22, self.screen.get_height() - 116)
            self.panel((x, y, width, 96), RAISED, True, 10)
            self.wrap(tip, (x + 12, y + 10, width - 24, 80), 13, TEXT, 3)
