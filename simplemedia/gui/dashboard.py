from pathlib import Path

import pygame

from ..filesystem import size_text
from ..models import ACTIVE
from .ui import ACCENT, BLUE, FAINT, MUTED, PANEL, TEXT, YELLOW


def draw(app, x, y, w):
    ui = app.ui
    hero = ui.panel((x, y, w, 216), (21, 42, 43), False, 18)
    # A quiet geometric media illustration, rendered at native resolution.
    if w > 800:
        cx, cy = hero.right - 137, hero.y + 101
        pygame.draw.circle(ui.screen, (35, 69, 67), (cx, cy), 84, 1)
        pygame.draw.circle(ui.screen, (30, 60, 59), (cx, cy), 108, 1)
        for dx, dy, kind, color in [
            (-70, -38, "image", ACCENT),
            (15, -60, "video", BLUE),
            (-6, 22, "audio", YELLOW),
        ]:
            card = ui.panel((cx + dx, cy + dy, 78, 73), (27, 48, 52), True, 13)
            ui.icon(kind, (card.centerx, card.centery), color, 28)
        ui.badge("A little lighter.", cx - 63, hero.bottom - 39, ACCENT)
    ui.badge("YOUR FILES. MORE FREEDOM.", x + 26, y + 24, ACCENT)
    ui.text("Make room for more.", x + 26, y + 65, 33, TEXT, True)
    ui.text(
        "Compress images, videos and audio in one calm workspace.",
        x + 27,
        y + 111,
        15,
        MUTED,
        max_width=w - 55 if w < 800 else w - 285,
    )
    ui.button(
        "dash:add",
        "Add Media",
        (x + 27, y + 155, 151, 39),
        lambda: app.choose("files"),
        "primary",
        "plus",
    )
    ui.button(
        "dash:folder",
        "Add Folder",
        (x + 189, y + 155, 143, 39),
        lambda: (
            setattr(app, "bulk_open", True),
            app.navigate("Compress"),
            app.choose("folder"),
        ),
        icon="folder",
    )
    y += 236
    completed = [j for j in app.history if j.status == "Completed"]
    saved = sum(j.saved for j in completed)
    count = sum(j.status not in {"Completed", "Failed", "Cancelled"} for j in app.jobs)
    gap = 16
    cw = (w - 2 * gap) // 3
    stats = [
        (
            "Files compressed",
            f"{len(completed):,}",
            "Across your saved history",
            "image",
            BLUE,
        ),
        (
            "Space saved",
            size_text(saved),
            "Actual results, measured after encoding",
            "Compress",
            ACCENT,
        ),
        (
            "In your queue",
            f"{count:02d}",
            "A little patience. A little more space.",
            "Queue",
            YELLOW,
        ),
    ]
    for i, (title, value, sub, icon, color) in enumerate(stats):
        xx = x + i * (cw + gap)
        ui.panel((xx, y, cw, 126))
        ui.text(title, xx + 19, y + 16, 13, MUTED)
        ui.icon(icon, (xx + cw - 31, y + 28), color, 21)
        ui.text(value, xx + 19, y + 42, 30, TEXT, True)
        ui.text(sub, xx + 19, y + 94, 11, FAINT, max_width=cw - 32)
    y += 147
    ui.text("Your workspace", x, y, 20, TEXT, True)
    ui.button(
        "dash:view",
        "View queue  →",
        (x + w - 141, y - 3, 141, 34),
        lambda: app.navigate("Queue"),
    )
    y += 45
    active = [j for j in app.jobs if j.status in ACTIVE]
    ui.panel((x, y, w, 116))
    if active:
        job = active[0]
        ui.icon(job.kind, (x + 37, y + 36), ACCENT, 25)
        ui.text(Path(job.source).name, x + 64, y + 17, 17, TEXT, True, max_width=w - 270)
        ui.text(
            "Paused"
            if job.paused
            else "Compressing" + (f" · +{len(active) - 1} more" if len(active) > 1 else ""),
            x + 64,
            y + 44,
            13,
            ACCENT,
        )
        ui.text(f"{job.progress:.0%}", x + w - 74, y + 23, 20, ACCENT, True)
        ui.progress((x + 24, y + 84, w - 48, 6), job.progress)
    else:
        ui.panel((x + 24, y + 27, 58, 58), (28, 45, 53), False, 15)
        ui.icon("Compress", (x + 53, y + 56), BLUE, 28)
        ui.text("Ready for something lighter?", x + 101, y + 26, 19, TEXT, True)
        ui.text(
            "Add your media, choose a preset, and we’ll take it from there.",
            x + 101,
            y + 57,
            14,
            MUTED,
            max_width=w - 133,
        )
        if count:
            ui.button(
                "dash:start",
                "Start all",
                (x + w - 129, y + 34, 105, 40),
                app.manager.start,
                "primary",
            )
    y += 140
    ui.text("Recent activity", x, y, 20, TEXT, True)
    y += 38
    recent = sorted(
        (j for j in app.history if j.finished_at),
        key=lambda j: j.finished_at,
        reverse=True,
    )[:4]
    if not recent:
        ui.panel((x, y, w, 88))
        ui.text("A fresh start.", x + 22, y + 17, 16, TEXT, True)
        ui.text("Your completed compressions will appear here.", x + 22, y + 46, 14, MUTED)
        y += 88
    else:
        for job in recent:
            ui.panel((x, y, w, 66), PANEL, True, 10)
            ui.icon(
                job.kind,
                (x + 31, y + 32),
                ACCENT if job.status == "Completed" else YELLOW,
                20,
            )
            ui.text(Path(job.source).name, x + 57, y + 12, 15, TEXT, True, max_width=w - 355)
            ui.text(job.summary, x + 57, y + 36, 12, MUTED, max_width=w - 355)
            ui.text(
                f"{size_text(job.original_size)} → {size_text(job.output_size)}"
                if job.status == "Completed"
                else job.status,
                x + w - 272,
                y + 24,
                13,
                MUTED,
            )
            ui.badge(
                job.status,
                x + w - 103,
                y + 20,
                ACCENT if job.status == "Completed" else YELLOW,
            )
            ui.register(
                "recent:" + job.id,
                (x, y, w, 66),
                lambda job=job: setattr(app, "detail_id", job.id),
            )
            y += 76
    return y
