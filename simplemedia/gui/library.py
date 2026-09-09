from pathlib import Path

import pygame

from ..filesystem import output_directory, size_text, time_text
from ..models import ACTIVE, TERMINAL
from .ui import ACCENT, BG, BLUE, FAINT, MUTED, PANEL, RED, TEXT, YELLOW

COLORS = {
    "Waiting": MUTED,
    "Preparing": YELLOW,
    "Compressing": BLUE,
    "Completed": ACCENT,
    "Failed": RED,
    "Cancelled": FAINT,
}


def draw(app, x, y, w, history=False):
    ui = app.ui
    if history:
        ui.text("Your compression library", x, y + 9, 18, TEXT, True)
        ui.button(
            "history:clear",
            "Clear history",
            (x + w - 139, y, 139, 38),
            app.clear_history,
        )
    else:
        buttons = [
            (
                "start",
                "Resume all" if app.manager.paused else "Start all",
                app.manager.start,
                "primary",
                111,
            ),
            ("pause", "Pause all", app.manager.pause, "normal", 106),
            (
                "cancel",
                "Cancel all",
                lambda: app.confirm(
                    "Cancel all jobs?",
                    "Running encoders will stop and their partial output will be removed. Waiting jobs will be cancelled too.",
                    app.manager.cancel,
                    "Cancel all",
                ),
                "normal",
                107,
            ),
            ("retry", "Retry failed", app.manager.retry, "normal", 118),
            ("clear", "Clear completed", app.manager.clear_completed, "normal", 149),
        ]
        xx = x
        for key, label, action, style, width in buttons:
            ui.button("queue:" + key, label, (xx, y, width, 40), action, style)
            xx += width + 9
    y += 62
    ui.select(
        "library:filter",
        "Status",
        (x, y, 177, 64),
        app.library_filter,
        [
            "All",
            "Waiting",
            "Preparing",
            "Compressing",
            "Completed",
            "Failed",
            "Cancelled",
        ],
        lambda value: setattr(app, "library_filter", value),
    )
    ui.field(
        "library:search",
        "Search filenames",
        (x + 193, y, w - 193, 64),
        app.search,
        lambda value: setattr(app, "search", value),
    )
    y += 86
    jobs = [
        j
        for j in (app.history if history else app.jobs)
        if (not history or j.finished_at)
        and (app.library_filter == "All" or j.status == app.library_filter)
        and app.search.casefold() in Path(j.source).name.casefold()
    ]
    if history:
        jobs.sort(key=lambda j: j.finished_at, reverse=True)
    ui.text(f"{len(jobs):,} file{'s' if len(jobs) != 1 else ''}", x, y, 13, MUTED, True)
    ui.text(
        "Click a file for settings, output details and before / after.",
        x + 100,
        y,
        12,
        FAINT,
        max_width=w - 110,
    )
    y += 32
    if not jobs:
        ui.panel((x, y, w, 239))
        ui.icon("History" if history else "Queue", (x + w // 2, y + 55), ACCENT, 30)
        title = "Nothing here yet."
        tw = ui.font(23, True).size(title)[0]
        ui.text(title, x + (w - tw) // 2, y + 91, 23, TEXT, True)
        subtitle = (
            "Completed jobs will be saved here."
            if history
            else "Add a few files and give your storage some breathing room."
        )
        tw = ui.font(14).size(subtitle)[0]
        ui.text(subtitle, x + (w - tw) // 2, y + 130, 14, MUTED)
        ui.button(
            "empty:add",
            "Add Media",
            (x + w // 2 - 78, y + 173, 156, 41),
            lambda: app.choose("files"),
            "primary",
            "plus",
        )
        return y + 239
    # Virtualized rows: only paint/register visible jobs in a large queue.
    for job in jobs:
        row_h = 151
        if y + row_h >= app.content.top and y < app.content.bottom:
            ui.panel((x, y, w, row_h), PANEL, True, 13)
            color = COLORS[job.status]
            ui.icon(job.kind, (x + 31, y + 33), color, 23)
            ui.text(Path(job.source).name, x + 57, y + 14, 17, TEXT, True, max_width=w - 205)
            ui.text(
                f"{job.kind.title()} · {size_text(job.original_size)} · {job.summary}",
                x + 57,
                y + 41,
                12,
                MUTED,
                max_width=w - 205,
            )
            ui.badge(
                "Paused" if job.paused else job.status,
                x + w - 115,
                y + 19,
                YELLOW if job.paused else color,
            )
            try:
                out = job.output or str(output_directory(job))
            except ValueError:
                out = "Choose an output folder"
            ui.text("To  " + out, x + 21, y + 70, 12, FAINT, max_width=w - 40)
            ui.register(
                "job:" + job.id,
                (x, y, w, 96),
                lambda job=job: setattr(app, "detail_id", job.id),
                tooltip=out,
            )
            if job.status in ACTIVE:
                ui.progress((x + 21, y + 103, max(120, w - 321), 6), job.progress, color)
                ui.text(
                    f"{job.progress:.0%} · {time_text(job.eta)} remaining"
                    if not job.paused
                    else f"{job.progress:.0%} · Paused",
                    x + 21,
                    y + 120,
                    12,
                    MUTED,
                )
                ui.button(
                    "pause:" + job.id,
                    "Resume" if job.paused else "Pause",
                    (x + w - 276, y + 102, 83, 33),
                    lambda job=job: (
                        app.manager.start(job.id) if job.paused else app.manager.pause(job.id)
                    ),
                )
                ui.button(
                    "cancel:" + job.id,
                    "Cancel",
                    (x + w - 183, y + 102, 77, 33),
                    lambda job=job: app.manager.cancel(job.id),
                )
            elif job.status == "Waiting":
                ui.text(
                    "Paused" if job.paused else "Ready to compress",
                    x + 21,
                    y + 113,
                    13,
                    MUTED,
                )
                ui.button(
                    "start:" + job.id,
                    "Start",
                    (x + w - 270, y + 102, 75, 33),
                    lambda job=job: app.manager.start(job.id),
                    "primary",
                )
                ui.button(
                    "cancel:" + job.id,
                    "Cancel",
                    (x + w - 184, y + 102, 77, 33),
                    lambda job=job: app.manager.cancel(job.id),
                )
            elif job.status == "Completed":
                percent = job.saved / job.original_size * 100 if job.original_size else 0
                ui.text(
                    f"{size_text(job.original_size)} → {size_text(job.output_size)}  ·  {percent:.1f}% {'saved' if percent >= 0 else '(larger)'}",
                    x + 21,
                    y + 113,
                    14,
                    ACCENT if percent >= 0 else YELLOW,
                    max_width=w - 223,
                )
                ui.button(
                    "folder:" + job.id,
                    "Folder",
                    (x + w - 185, y + 102, 79, 33),
                    lambda job=job: app.open_folder(job.output),
                )
            else:
                ui.text(
                    job.error.splitlines()[0] if job.error else "Cancelled by you",
                    x + 21,
                    y + 112,
                    13,
                    color,
                    max_width=w - 230,
                )
                if not history:
                    ui.button(
                        "retry:" + job.id,
                        "Retry",
                        (x + w - 183, y + 102, 77, 33),
                        lambda job=job: app.manager.retry(job.id),
                    )
            ui.button(
                "details:" + job.id,
                "Details",
                (x + w - 96, y + 102, 75, 33),
                lambda job=job: setattr(app, "detail_id", job.id),
            )
        y += row_h + 12
    return y


def detail(app):
    ui = app.ui
    job = next((j for j in app.jobs + app.history if j.id == app.detail_id), None)
    if job is None:
        app.detail_id = ""
        return
    shade = pygame.Surface(ui.screen.get_size(), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 190))
    ui.screen.blit(shade, (0, 0))
    ui.hits = []
    ui.dropdown = None
    rect = pygame.Rect(
        0,
        0,
        min(850, ui.screen.get_width() - 80),
        min(730, ui.screen.get_height() - 64),
    )
    rect.center = ui.screen.get_rect().center
    ui.panel(rect)
    x, y, w = rect.x + 25, rect.y + 22, rect.w - 50
    ui.icon(job.kind, (x + 12, y + 15), COLORS[job.status], 22)
    ui.text(Path(job.source).name, x + 37, y, 21, TEXT, True, max_width=w - 125)
    ui.button(
        "detail:close",
        "Close",
        (rect.right - 98, rect.y + 18, 75, 33),
        lambda: setattr(app, "detail_id", ""),
    )
    ui.badge("Paused" if job.paused else job.status, x, y + 40, COLORS[job.status])
    ui.text(
        job.finished_at.replace("T", " ").replace("+00:00", " UTC")
        or "Added " + job.created_at.replace("T", " "),
        x + 125,
        y + 46,
        12,
        MUTED,
        max_width=w - 130,
    )
    y += 86
    if job.kind == "image" and job.status == "Completed":
        pw = (w - 15) // 2
        for index, (label, path) in enumerate(
            [("Original", job.source), ("Compressed", job.output)]
        ):
            px = x + index * (pw + 15)
            area = ui.panel((px, y, pw, 154), BG, True, 10)
            preview = app.preview(path)
            if preview:
                image, dimensions = preview
                factor = min((pw - 20) / image.get_width(), 113 / image.get_height(), 1)
                image = pygame.transform.smoothscale(
                    image,
                    (
                        max(1, int(image.get_width() * factor)),
                        max(1, int(image.get_height() * factor)),
                    ),
                )
                for cy in range(area.y + 5, area.bottom - 29, 12):
                    for cx in range(area.x + 5, area.right - 5, 12):
                        pygame.draw.rect(
                            ui.screen,
                            (39, 44, 51)
                            if ((cx - area.x) // 12 + (cy - area.y) // 12) % 2
                            else (28, 33, 40),
                            (
                                cx,
                                cy,
                                min(12, area.right - 5 - cx),
                                min(12, area.bottom - 29 - cy),
                            ),
                        )
                ui.screen.blit(
                    image,
                    (
                        area.centerx - image.get_width() // 2,
                        area.y + 6 + (113 - image.get_height()) // 2,
                    ),
                )
                ui.text(
                    label + " · " + dimensions,
                    px + 12,
                    area.bottom - 24,
                    12,
                    MUTED,
                    max_width=pw - 20,
                )
            else:
                ui.text(
                    label + " · Preview unavailable / loading",
                    px + 12,
                    area.y + 65,
                    12,
                    MUTED,
                    max_width=pw - 20,
                )
        y += 173
    elif job.status == "Failed":
        ui.panel((x, y, w, 126), (44, 29, 37), False, 10)
        ui.wrap(job.error, (x + 15, y + 12, w - 30, 110), 13, RED, 4)
        y += 144
    elif job.warnings:
        ui.wrap("\n".join(job.warnings), (x, y, w, 105), 14, YELLOW, 4)
        y += 113
    else:
        ui.text("Progress", x, y, 14, MUTED)
        ui.progress((x, y + 32, w, 8), job.progress)
        ui.text(
            f"{job.progress:.0%} · {time_text(job.elapsed)} elapsed",
            x,
            y + 54,
            14,
            ACCENT,
        )
        y += 102
    if job.status == "Completed":
        cw = w // 3
        for i, (title, value, color) in enumerate(
            [
                ("Original", size_text(job.original_size), MUTED),
                ("Compressed", size_text(job.output_size), TEXT),
                (
                    "Space saved",
                    size_text(job.saved),
                    ACCENT if job.saved >= 0 else YELLOW,
                ),
            ]
        ):
            ui.text(title, x + i * cw, y, 12, MUTED)
            ui.text(value, x + i * cw, y + 24, 25, color, True)
        before = max(job.original_size, job.output_size, 1)
        ui.progress((x, y + 67, w, 6), job.original_size / before, MUTED)
        ui.progress((x, y + 79, w, 6), job.output_size / before, ACCENT)
        ratio = job.saved / job.original_size * 100 if job.original_size else 0
        ui.text(
            f"{ratio:.1f}% saved" if ratio >= 0 else f"{abs(ratio):.1f}% larger than original",
            x,
            y + 94,
            13,
            ACCENT if ratio >= 0 else YELLOW,
        )
        y += 125
    ui.text("SOURCE", x, y, 10, FAINT, True)
    ui.text(job.source, x, y + 20, 13, TEXT, max_width=w)
    ui.register(
        "detail:source",
        (x, y + 15, w, 27),
        lambda: app.clipboard_set(job.source),
        tooltip="Click to copy the source path. " + job.source,
    )
    y += 47
    ui.text("OUTPUT", x, y, 10, FAINT, True)
    try:
        output = job.output or str(output_directory(job))
    except ValueError:
        output = "Not configured"
    ui.text(output, x, y + 20, 13, TEXT, max_width=w)
    ui.register(
        "detail:output",
        (x, y + 15, w, 27),
        lambda: app.clipboard_set(output),
        tooltip="Click to copy the output path. " + output,
    )
    y += 47
    ui.text("SETTINGS", x, y, 10, FAINT, True)
    ui.text(job.summary, x, y + 20, 13, TEXT, max_width=w)
    import json

    ui.register(
        "detail:settings",
        (x, y + 15, w, 27),
        lambda: app.clipboard_set(json.dumps(job.options, indent=2)),
        tooltip="Click to copy all compression settings as JSON.",
    )
    if job.warnings and rect.bottom - y > 100:
        ui.text(job.warnings[-1], x, y + 49, 12, YELLOW, max_width=w)
    bottom = rect.bottom - 61
    if job.status == "Failed":
        ui.button(
            "detail:copy",
            "Copy technical error",
            (x, bottom, 176, 37),
            lambda: app.copy_error(job),
        )
    elif job.status == "Completed":
        ui.button(
            "detail:folder",
            "Open output folder",
            (x, bottom, 173, 37),
            lambda: app.open_folder(job.output),
        )
    elif job.status in ACTIVE:
        ui.button(
            "detail:pause",
            "Resume" if job.paused else "Pause",
            (x, bottom, 96, 37),
            lambda: app.manager.start(job.id) if job.paused else app.manager.pause(job.id),
        )
    if job.status in {"Failed", "Cancelled"} and not job.archived:
        ui.button(
            "detail:retry",
            "Retry",
            (x + w - 199, bottom, 86, 37),
            lambda: app.manager.retry(job.id),
            "primary",
        )
    elif job.status not in TERMINAL:
        ui.button(
            "detail:cancel",
            "Cancel",
            (x + w - 199, bottom, 86, 37),
            lambda: app.manager.cancel(job.id),
        )
    if job.status not in ACTIVE and not job.archived:
        ui.button(
            "detail:remove",
            "Remove",
            (x + w - 101, bottom, 101, 37),
            lambda: (setattr(app, "detail_id", ""), app.remove_job(job)),
        )
