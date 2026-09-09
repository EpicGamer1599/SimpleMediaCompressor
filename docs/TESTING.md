# Validation record

Validated locally on **Windows 11**, using Python **3.12.8**, Pygame CE **2.5.8**, Pillow **12.3.0**, psutil **7.2.2**, and FFmpeg/FFprobe **8.1.1**.

## Automated checks

The final complete test run finished with **56 passed, 0 failed, 0 skipped**:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .test-data-beta-release
```

Ruff lint and formatting checks pass. Runtime dependencies are pinned, and the source compiles successfully.

| Area | Verification |
| --- | --- |
| Single / multiple images | Real Pillow encoding and isolated worker execution |
| Image modes | RGB, grayscale, RGBA, transparency protection and explicit flattening |
| Orientation / metadata | EXIF rotation, metadata removal and supported metadata retention |
| Animation | GIF input to GIF, WebP, APNG and TIFF; unsupported flattening rejected |
| Lossless encoding | WebP pixel equality |
| Large images | Multi-megapixel image workers, pause/resume and cancellation |
| Video | Real H.264 MP4, VP9 WebM and H.265 MKV encoding with stream inspection |
| Audio | Real MP3, M4A, AAC, OGG, Opus, FLAC and WAV encoding |
| Bulk processing | Recursive scan through the application to completed jobs with retained subfolders |
| Queue | Multiple jobs, concurrency limit, independent failure handling and retry; Retry failed leaves cancelled jobs stopped |
| Pause / cancel | Image worker suspension and real FFmpeg process-tree suspension/cancellation |
| File safety | Original preservation, collisions, simultaneous name reservation and failed overwrite protection |
| Errors | Corrupt media, absent source, missing FFmpeg, unavailable encoder and low free space |
| Bundled tools | Frozen builds prefer bundled FFmpeg/FFprobe; manual selection takes precedence; source runs use external tools |
| Restart | Waiting and interrupted active jobs restored stopped; cleared queue entries stay cleared |
| Persistence | Settings, history, clear-history behavior and corrupted-settings recovery |
| Pygame UI | All six pages at 1280 × 860 and 980 × 700; real input/dropdown/queue actions |
| Image preview | Original dimensions retained after JPEG draft downsampling |
| Windows dialogs | Native COM dialogs configured and released for folders, single and multiple files |

Fixtures are generated locally; tests do not download or require personal media. FFmpeg tests skip when a required tool or codec is missing in another environment, so check skip counts when reproducing validation.

## Windows executable

The **1.0.0beta** Windows x64 release was built with **PyInstaller 6.22.2** using `python build.py --release 1.0.0beta`. The single windowed executable includes Python, its runtime dependencies, FFmpeg and FFprobe, with a custom application icon.

```powershell
.\.venv\Scripts\python.exe tests/verify_build.py --exe release/1.0.0beta/SimpleMediaCompressure.exe --bundled
```

This successfully verified a copy of the EXE in a folder containing no adjacent dependencies, with PATH restricted to Windows system tools and LOCALAPPDATA redirected away from installed FFmpeg:

1. Actual image, video and audio jobs executed by the frozen application.
2. Completed image dimensions, decodable video/audio streams and durations, and recorded history through the queue manager.
3. The frozen GUI rendering its real completed queue with **FFmpeg ready** and exiting cleanly; the screenshot was inspected.
4. Automatic discovery of bundled tools without an external FFmpeg path in worker requests.
5. Cleanup of one-file temporary extraction directories after exit.

The release EXE is **196,378,151 bytes**. Its SHA-256 checksum was checked against `release/1.0.0beta/SHA256SUMS.txt`, and its accompanying MIT license matches the project's `LICENSE` exactly, including **Copyright (c) 2026 EpicGamer1599**.

The default `python build.py` still creates a directory-based development bundle with external FFmpeg. Generated builds and validation media live in ignored `release/`, `dist/`, `build/`, `.artifacts/` and `.test-data-*/` directories.

## Visual inspection

Rendered and inspected the dashboard, compression page, settings page at minimum size, a real completed mixed-media queue, before/after image details at minimum size, and scrolled output/resize controls. Additional automated checks render every page and its scrolled state at both window sizes.

The public screenshots in this repository show the actual interface with an empty library, avoiding personal media paths. Generated-media result screenshots remain local under `.artifacts/`.

## Scope and remaining platform checks

- The local run was Windows-based. A Linux/Windows CI matrix is supplied but was not run on a remote service here. macOS has not been tested on physical hardware.
- Windows dialog construction and COM lifetime are tested; interactive OS picker selection, physical drag-and-drop, and clipboard behavior should also be checked on each release machine.
- GPU encoders are capability-listed but were not benchmarked or verified against every GPU/driver combination. Software encoding was exercised.
- Tests use synthetic, finite-duration video/audio and multi-megapixel images. Multi-gigabyte media, every optional codec, network filesystems and unusual color/HDR workflows have not been exhaustively tested.
- Forced power loss is not simulated. Normal cancellation/shutdown removes partial output; a forced termination can leave ignored `.smc-*` temporary files.
