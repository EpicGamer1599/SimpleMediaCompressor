# Contributing

## Ownership and contribution policy

EpicGamer1599 is the project owner and maintainer. The official project and repository remain maintained and controlled by EpicGamer1599.

Anyone may submit issues, suggestions, or pull requests. Contributions are reviewed before being merged, and the maintainer has final discretion over which changes are accepted into the official repository.

Contributing code does not automatically give someone ownership or control of the project. Contributors should retain appropriate attribution for their own contributions where applicable.

The MIT License permits others to use, copy, modify, and redistribute the software under its terms. These permissions do not grant control over the official repository.

## Development setup

Use a supported Python version, create a virtual environment, and install `requirements-dev.txt`. Keep changes focused and explain the user-visible problem, the new behavior, and how you verified it.

## Architecture

| Module | Responsibility |
| --- | --- |
| `simplemedia/metadata.py` | Central project identity and version |
| `simplemedia/app.py` | Pygame lifecycle, navigation, asynchronous dialogs and UI messages |
| `simplemedia/dialogs.py` | Native Windows dialogs and isolated Tk pickers on macOS/Linux |
| `simplemedia/gui/ui.py` | Shared drawing primitives, input handling and reusable controls |
| `simplemedia/gui/` | Dashboard, compression, queue/history, settings/about page renderers |
| `simplemedia/models.py` | Job records, media classification and typed default options |
| `simplemedia/queue.py` | Bounded scheduler, worker lifecycle, pause/resume/cancel and publication |
| `simplemedia/worker.py` | Isolated media encoder entry point and JSON event emission |
| `simplemedia/images.py` | Pillow decoding, transformations, metadata and image encoding |
| `simplemedia/ffmpeg.py` | Discovery, codec validation, command arguments and streaming progress |
| `simplemedia/filesystem.py` | Output naming, safe publication and cancellable folder scanning |
| `simplemedia/storage.py` | Atomic settings writes, SQLite records and rotating logs |

Pygame calls belong on the UI thread. Media processing belongs in workers; filesystem scans, native dialogs and history snapshots run off the event loop. The scheduler protects shared job state with a lock, and the UI consumes snapshots/messages.

## Changes and validation

- Never execute media through a shell or replace a source file.
- Validate container/codec compatibility and report unsupported capabilities explicitly.
- Preserve transparency, orientation and animation, or return a clear actionable error.
- Add regression tests for behavior changes that affect files, worker lifecycle or persistence.
- Run `python -m pytest -q`. Check that FFmpeg cases ran when changing video/audio behavior.
- Render changed pages at 1280 × 860 and 980 × 700, including scrolled/expanded states.
- Exercise a real mixed queue and cancellation before changing the process controller.
- Update documentation and the changelog to match shipped behavior.

Before opening a pull request, describe the concrete trigger and resulting behavior, list relevant validation, and include screenshots for interface changes. Avoid committing generated media, logs, local state, virtual environments, FFmpeg binaries or executable builds.

Bug reports should include your operating system, Python/app version, FFmpeg version, steps to reproduce, settings, and the copied technical error. Remove private paths or metadata before sharing. A small synthetic reproduction file is preferable to personal media.
