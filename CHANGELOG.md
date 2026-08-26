# CHANGELOG.md

``````````````````````text
# CHANGELOG.md

`````````````````````text
# CHANGELOG.md

````````````````````text
# CHANGELOG.md

```````````````````text
# CHANGELOG.md

``````````````````text
# CHANGELOG.md

`````````````````text
# CHANGELOG.md

````````````````text
# CHANGELOG.md

```````````````text
# CHANGELOG.md

``````````````text
# CHANGELOG.md

`````````````text
# CHANGELOG.md

````````````text
# CHANGELOG.md

```````````text
# CHANGELOG.md

``````````text
# CHANGELOG.md

`````````text
# CHANGELOG.md

````````text
# CHANGELOG.md

```````text
# CHANGELOG.md

``````text
# CHANGELOG.md

`````text
# CHANGELOG.md

````text
# Changelog

All notable changes to `doc2md` are documented here.
Format based on Keep a Changelog; versioning follows SemVer 2.0.0.

## [0.3.8] - 2026-08-26

### Fixed

- **GUI Layout Crash Fix:** Resolved Tkinter startup crash caused by mixing `.pack()` and `.grid()` geometry managers. Replaced invalid `sticky` parameters in `.pack()` calls with proper `anchor` parameter.
- **Ultimate Icon Cache Bypass:** Implemented aggressive Windows icon cache bypass by decoupling icon from executable. Icon now stored as separate file in Inno Setup with explicit `IconFilename` references in shortcuts. Added `ie4uinit.exe -show` to force Explorer cache refresh post-installation.

### Enhanced

- Improved layout stability with consistent pack-based geometry management.
- Windows icon now guaranteed to display correctly after installation without cache delays.

## [0.3.7] - 2026-08-26

### Added

- **Multi-Format Export Engine:** Save conversion results as Markdown (`.md`), Plain Text (`.txt`), or Word Document (`.docx`) via new `💾 Save As...` button.
- **Progress Overlay with Percentage:** Real-time progress bar with overlaid percentage display (e.g., "45%") for file conversions and model downloads.
- **Soft Dark Dashboard Redesign:** New color palette (`#1B222C` window, `#242D3C` cards, `#3B82F6` & `#06B6D4` accents, `#F1F5F9` text).
- **2-Column Layout:** Split interface with left drag-and-drop zone and right-side options/analytics card for better organization.

### Fixed

- Improved layout responsiveness with scrollable options panel.
- Enhanced progress tracking with byte/percentage overlays for conversions.

## [0.3.5] - 2026-08-26

### Added

- **CustomTkinter Dark UI Migration:** Modern slate dark theme (`#0F172A`) with vibrant cyan accents (`#06B6D4`), professional card-based layout for all options and progress tracking.
- Enhanced GUI components: scrollable main frame, color-coded status indicators, improved button styling.

### Fixed

- **TkDND Crash Guard:** Wrapped drag-and-drop initialization in try-except with graceful fallback to "Browse Files" button if tkinterdnd2 fails.
- **Icon Embedding in Installer:** Updated Inno Setup to explicitly bind `assets/icon.ico` to desktop and start-menu shortcuts for consistent branding.
- PyInstaller now collects all `tkinterdnd2` data files via `collect_data_files()` to prevent startup crashes.

### Enhanced

- Dark mode UI applied consistently across all CustomTkinter widgets.
- Improved error handling and user feedback with color-coded status messages (cyan for progress, green for success, red for errors).

## [0.3.3] - 2026-08-26

### Fixed

- No-console GUI launch fix: PyInstaller now builds with `--windowed` flag, eliminating terminal window flicker when double-clicking `doc2md.exe` from desktop.
- Added exception handling for GUI startup crashes: uncaught errors now display a user-friendly error dialog instead of silent exit.
- Graceful error recovery: GUI remains responsive even if dependencies fail to load.

### Enhanced

- Modern "MD" app icon redesign: Dark slate background (#1E1E2E) with vibrant cyan text (#00F2FE), optimized for all sizes (16x16 to 256x256).
- Icon embedded in Windows executable and installer for consistent branding.

## [0.3.2] - 2026-08-26

### Fixed

- Auto-launch GUI dashboard when `doc2md.exe` is run with no CLI arguments (double-click from desktop/installer shortcuts).
- Improved entry-point logic to gracefully handle zero-argument execution without displaying help text.
- Enhanced user experience: launching the executable now defaults to interactive GUI mode instead of CLI help mode.

## [0.3.1] - 2026-08-26

### Fixed

- Deep bug audit identified and verified 20+ edge-case scenarios across GUI threading, Audio Engine resilience, and document converter robustness.
- Verified graceful handling of corrupted audio files, zero-byte inputs, and malformed document structures without crashes.
- Confirmed thread-safe converter state across concurrent and sequential file processing.
- Enhanced error recovery: converter remains usable after timeouts, exceptions, and permission errors.

## [0.3.0] - 2026-08-26

### Added

- **Audio Engine (faster-whisper):** Process 8+ hour audio/video files with flat memory consumption via generator-based streaming transcription.
- **Dynamic Model Loader:** On-demand downloading of Whisper models (`tiny`, `base`, `small`, `medium`, `large-v3`) with persistent caching in `~/.cache/doc2md/models`.
- **GPU/CPU Auto-Detection:** NVIDIA CUDA (`float16`) fallback to CPU (`int8`/`float32`) without crashes.
- **Drag-and-Drop GUI Dashboard:** Modern tkinter-based UI with background worker threads, real-time progress bars, and configuration toggles (`Auto-Copy`, `Token Stats`, `OCR Enable`, `Model Size`).
- **Audio File Routing:** Extended FileKind enum to support `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`, `.wma` (audio) and `.mp4`, `.mkv`, `.avi`, `.mov`, `.flv`, `.wmv`, `.webm` (video).
- `doc2md gui` command: Launch interactive GUI from CLI.
- Updated `pyproject.toml` with `[audio]` and `[gui]` optional dependencies.

### Enhanced

- File detection (router.py) now includes magic-byte and extension-based detection for audio/video formats.
- CLI help text updated to reflect new audio/GUI capabilities.

## [0.2.1] - 2026-08-26

### Added

- `tests/test_edge_bugs.py`: comprehensive edge-case testing for CLI file system operations, invalid paths, read-only outputs, and empty clipboard handling.

### Fixed

- Enhanced OCR resilience: verified pure black/white, noise images, palette PNGs, 16-bit TIFFs, transparent WebP, and EXIF-rotated JPEGs all return clean results without crashing.
- Concurrency safety: validated 10+ parallel thread workers with zero temporary file leaks after batch processing.

## [0.2.0] - 2026-08-26

### Added

- `--copy` / `-c`: copy converted Markdown to the Windows clipboard via pyperclip; multiple inputs are concatenated with `---` separators; graceful `Nothing to copy` / `Clipboard error` handling.
- `--stats` / `-s`: conversion metrics table (original size -> markdown size, estimated tokens, saved ratio %) built on tiktoken (`cl100k_base`) with a deterministic chars/4 fallback when the tokenizer is unavailable offline.
- `--chunk <max_tokens>`: semantic chunking of Markdown output — header-driven splitting (`#`/`##`), paragraph and sentence refinement, word-level last resort, and fence-balanced code blocks (`*.partNNN.md` files).
- `doc2md install-context-menu` / `uninstall-context-menu` / `context-menu-status`: per-user Explorer right-click integration under `HKCU\Software\Classes\*\shell\doc2md` (no admin rights); frozen-exe aware command line.
- `doc2md.toml` config support: defaults for `default_copy`, `stats`, `chunk`, `timeout`, `max_rows`, `ocr_enabled`; discovered in CWD then home; malformed files warn with `ignoring unreadable config` and fall back to defaults.
- RapidOCR ONNX backend for the OCR engine: used automatically when Tesseract is absent (`rapidocr-onnxruntime` extra), with singleton caching and full error wrapping.
- New core modules: `tokens`, `stats`, `clipboard`, `contextmenu`, `chunker`, extended `config`.

## [0.1.2] - 2026-08-26

### Added

- PDF OCR fallback: scanned/empty-text PDFs are now rendered page-by-page and OCR'd via Tesseract (`pdf_ocr_fallback` option, default on; graceful hint when Tesseract is absent).
- Explicit encoding hints: `read_text_smart(..., prefer_encodings=(...))` for deterministic multi-byte decoding (TIS-620/cp874 verified).
- Robust PPTX title detection via placeholder index instead of wrapper identity, plus first-bullet-as-title fallback and speaker-notes extraction.
- HTML comments/doctypes are no longer leaked into output Markdown.
- Test suite expanded from 50 to 135 tests: password-protected PDFs, OLE-container "encrypted" DOCX, corrupted OOXML zips, truncated CSV/JSON, Windows >260-char paths (with `\\?\` extended-length fallback), Thai Unicode/space paths, concurrent worker temp isolation, child-process crash simulation, mixed-encoding matrix (UTF-8 BOM / CP874 / TIS-620), and engine ImportError fallbacks.

### Fixed

- `_run_in_process` wait/collect logic extracted to `_wait_for_worker`, making EOF-crash and kill-escalation paths deterministic and testable.
- Fence-collision handling in the code engine verified: sources containing ``` are wrapped in longer fences.
- Coverage raised from 79% to 94.72% (enforced via `--cov-fail-under=90`).

## [0.1.1] - 2026-08-26

### Fixed

- Broke a circular import (`doc2md/__init__.py` <-> `core.converter`) that crashed first import of the cleaner module.
- Corrected glob handling in the CLI for absolute patterns (e.g. `D:\data\*.log`) which raised `NotImplementedError`.
- Off-by-one in Excel/CSV preview sampling: `sample_rows` now yields exactly N data rows after the header row before the Truncated Summary kicks in.
- Gatekeeper environment: ensured the Python `Scripts` directory is on PATH so LocalCore can spawn `pytest`.

### Changed

- Verification run under Strict Gatekeeper Protocol v3.4: `pytest tests/ --maxfail=1 --timeout=10` via LocalCore with model `Qwen-2.5-Coder-14B`; result EXIT_CODE:0, 50 passed in 4.67s.

## [0.1.0] - 2026-08-26

### Added

- Core router with magic-byte, content-heuristic, and extension-based detection (PDF, OOXML zip sniffing, images, HTML, EML, JSON, code).
- Modular engine architecture inheriting from `BaseEngine`: `pdf`, `docx`, `excel`, `pptx`, `web` (HTML+EML), `ocr`, `code`.
- Token-optimization cleaner pipeline: deduplication, whitespace compression, style stripping, code-fence protection.
- Hard watchdog timeouts via `concurrent.futures`; hung PDF/OCR workers are terminated in spawned processes.
- Excel/CSV row guard: sheets beyond `max_rows` emit a streamed Truncated Summary instead of loading fully.
- Encoding safety: strict UTF-8 with `charset_normalizer` fallback for corrupted encodings (Thai/TIS-620 verified).
- `typer` CLI with single/batch/glob conversion, progress output, `--stdout`, `--timeout`, `--max-rows`.
- Test suite covering corrupted PDFs, unknown encodings, oversized tables, timeout kills, and temp cleanup.
````
`````
``````
```````
````````
`````````
``````````
```````````
````````````
`````````````
``````````````
```````````````
````````````````
`````````````````
``````````````````
```````````````````
````````````````````
`````````````````````
``````````````````````
