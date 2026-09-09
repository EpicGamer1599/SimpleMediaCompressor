"""Exercise the real Pygame controls and queue without opening a desktop window."""

import os

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import time
from types import SimpleNamespace

import pygame
import pytest
from PIL import Image

from simplemedia.app import PAGES, App
from simplemedia.models import TERMINAL


@pytest.fixture
def app(tmp_path):
    args = SimpleNamespace(size="1280x860", page="Dashboard", files=[], screenshot=None)
    app = App(tmp_path / "ui-data", args)
    yield app
    for thread in app.io_threads:
        thread.join(timeout=10)
    app.manager.shutdown()
    app.store.close()
    pygame.quit()


def click(app, key):
    hit = next(h for h in app.ui.hits if h.key == key)
    app.ui.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=hit.rect.center))


def test_all_pages_at_two_sizes(app, tmp_path):
    for size in [(1280, 860), (980, 700)]:
        app.screen = pygame.display.set_mode(size)
        app.ui.screen = app.screen
        for page in PAGES:
            app.navigate(page)
            app.draw()
            assert app.ui.hits
            app.ui.scroll = app.ui.max_scroll
            app.draw()
            for hit in app.ui.hits:
                assert app.screen.get_rect().contains(hit.rect), (page, hit)


def test_fields_dropdown_and_actual_queue(app, tmp_path):
    source = tmp_path / "UI sample.png"
    Image.new("RGBA", (640, 480), (55, 110, 150, 99)).save(source)
    app.staged = [(str(source), "")]
    app.navigate("Compress")
    app.draw()
    click(app, "image:format")
    app.draw()
    # Choose PNG through the actual dropdown menu hit targets.
    click(app, "menu:image:format:2")
    assert app.image_options["format"] == "png"
    app.ui.scroll = app.ui.max_scroll
    app.draw()
    click(app, "output:path")
    app.ui.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
    app.ui.handle(pygame.event.Event(pygame.TEXTINPUT, text=str(tmp_path / "output")))
    assert app.output_options["directory"] == str(tmp_path / "output")
    click(app, "compress:enqueue")
    assert app.page == "Queue"
    deadline = time.monotonic() + 20
    started = False
    while time.monotonic() < deadline:
        app.poll()
        app.draw()
        if app.jobs and not started:
            click(app, "queue:start")
            started = True
        if app.jobs and app.jobs[0].status in TERMINAL:
            break
        time.sleep(0.03)
    assert app.jobs[0].status == "Completed", app.jobs[0].error
    app.detail_id = app.jobs[0].id
    app.draw()
    assert any(h.key == "detail:folder" for h in app.ui.hits)
    app.screen = pygame.display.set_mode((980, 700))
    app.ui.screen = app.screen
    app.draw()
    assert any(h.key == "detail:close" for h in app.ui.hits)


def test_jpeg_preview_keeps_original_dimensions(app, tmp_path):
    path = tmp_path / "large.jpg"
    Image.new("RGB", (4000, 2000), "navy").save(path)
    assert app.preview(str(path)) is None
    deadline = time.monotonic() + 5
    while str(path) not in app.previews and time.monotonic() < deadline:
        app.poll()
        time.sleep(0.02)
    surface, dimensions = app.previews[str(path)]
    assert dimensions == "4,000 × 2,000"
    assert surface.get_width() <= 460 and surface.get_height() <= 260


def test_bulk_folder_to_completed_queue(app, tmp_path):
    root = tmp_path / "Vacation"
    child = root / "Day 1"
    child.mkdir(parents=True)
    for path in (root / "first.png", child / "second.png", child / "third.png"):
        Image.new("RGB", (60, 40), "teal").save(path)
    Image.new("RGB", (60, 40), "teal").save(child / "skip_compressed.png")
    app.start_scan(str(root))
    deadline = time.monotonic() + 10
    while app.scan and time.monotonic() < deadline:
        app.poll()
        time.sleep(0.02)
    assert len(app.staged) == 3
    app._enqueue()
    deadline = time.monotonic() + 20
    started = False
    while time.monotonic() < deadline:
        app.poll()
        if app.jobs and not started:
            app.manager.start()
            started = True
        if len(app.jobs) == 3 and all(job.status == "Completed" for job in app.jobs):
            break
        time.sleep(0.03)
    assert (root / "Compressed" / "first_compressed.webp").exists()
    assert (root / "Compressed" / "Day 1" / "second_compressed.webp").exists()
    assert len(app.history) == 3
