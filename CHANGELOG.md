# CHANGELOG.md

```````````````````````````````````````text
# CHANGELOG.md

``````````````````````````````````````text
# CHANGELOG.md

`````````````````````````````````````text
# CHANGELOG.md

````````````````````````````````````text
# CHANGELOG.md

```````````````````````````````````text
# CHANGELOG.md

``````````````````````````````````text
# CHANGELOG.md

`````````````````````````````````text
# CHANGELOG.md

````````````````````````````````text
# CHANGELOG.md

```````````````````````````````text
# CHANGELOG.md

``````````````````````````````text
# CHANGELOG.md

`````````````````````````````text
# CHANGELOG.md

````````````````````````````text
# CHANGELOG.md

```````````````````````````text
# CHANGELOG.md

``````````````````````````text
# CHANGELOG.md

`````````````````````````text
# CHANGELOG.md

````````````````````````text
# CHANGELOG.md

```````````````````````text
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

## [1.0.5] - 2026-08-29

### Patch: Thread Starvation, Zombie Process & UI Polish Fixes

**Overview:** v1.0.5 is a deep-architecture pass addressing what happens when the app is closed mid-conversion, plus three UI polish issues introduced by earlier releases (uneven button spacing, a disabled-combobox white-box artifact, and a progress label background box).

### Added

- **Hard Exit Protocol:** `WM_DELETE_WINDOW` and the Exit button now route through `_on_exit_request()`. If a conversion is active, it force-kills any spawned `ffmpeg.exe` processes via `taskkill /F /IM ffmpeg.exe /T`, deletes leftover temp `.wav` chunks from the system Temp folder, then calls `os._exit(0)` — guaranteeing instant shutdown even if the main thread is frozen inside a native transcription call.
- **`AudioEngine.kill_all_ffmpeg_processes()` / `cleanup_temp_audio_chunks()`:** New static methods centralizing FFmpeg zombie-process and temp-file cleanup in the engine module, callable by the GUI without an engine instance.

### Fixed

- **Grid Geometry:** Removed the "Open Folder" button entirely; the remaining 5 buttons (Browse, Start/Stop, Copy, Save, Exit) now use `grid_columnconfigure(weight=1)` so they share equal width instead of left/right-packed uneven spacing.
- **Combobox White-Box Artifact:** Model selector's `fg_color` changed from white to the dark card color, with an explicit `text_color_disabled` so the selected model name stays legible when the control is locked during conversion.
- **Progress Label Background Box:** Percentage overlay on the progress bar now sets `fg_color="transparent"` explicitly, removing the background box over the progress track.
- **Model Lock During Conversion:** The model combobox is now actually disabled while a conversion runs (previously never disabled) and re-enabled on completion, cancellation, or crash.

---

## [1.0.4] - 2026-08-29

### Patch: Numeric Percentage Progress Bar

**Overview:** v1.0.4 replaces the static "Processing..." text overlay with a live, numeric percentage label that updates dynamically during conversion, giving users real visibility into progress instead of an indeterminate pulsing bar.

### Added

- **Fine-Grained Audio Progress Callback:** `audio_engine.convert()` now accepts a `progress_callback` option and reports transcription progress (0-99%) based on transcribed segment position relative to total audio duration, invoked after each segment is processed.
- **Real Overall Progress Tracking:** `_convert_worker()` now computes true numeric percentages across the whole batch — `(files completed + in-file fraction) / total files * 100` — instead of simulating activity with a pulsing bar.
- **`_update_progress_display()` Helper:** Centralized method that clamps and applies a percentage to both the progress bar fill and its centered numeric label (e.g. "45%").

### Fixed

- **Removed Static "Processing..." Overlay:** The progress bar center no longer shows blurry placeholder text; it always displays an accurate numeric percentage from 0% to 100%.
- **Pickling Safety for Process-Isolated Engines:** The progress callback is only attached to `Converter.options` for audio/video files; PDF/OCR conversions (which run in a spawned process) never receive the callback, avoiding an unpicklable local closure being sent across the process boundary.

---

## [1.0.3] - 2026-08-29

### Patch: Force Embed FFmpeg into Standalone Executable

**Overview:** v1.0.3 implements aggressive FFmpeg bundling via PyInstaller's binaries parameter, ensuring the standalone `doc2md.exe` carries FFmpeg directly without external dependencies. Users no longer need system FFmpeg installation or imageio_ffmpeg package.

### Added

- **Force-Embedded FFmpeg Binary:** Updated `build_exe.py` to detect FFmpeg via `imageio_ffmpeg.get_ffmpeg_exe()` and explicitly inject it into PyInstaller's `--add-binary` configuration for guaranteed standalone packaging.
- **Standalone Execution Path Override:** Audio engine now prioritizes `sys._MEIPASS` (PyInstaller bundle) as the first FFmpeg lookup location, with fallback chain for development/legacy scenarios.

### Fixed

- **Mandatory FFmpeg Requirement:** Build process now raises `RuntimeError` if FFmpeg cannot be located, preventing accidental creation of broken builds.
- **Embedded FFmpeg Discovery:** Execution path logic detects bundled `ffmpeg.exe` inside standalone package without requiring `imageio_ffmpeg` at runtime.

### Enhanced

- **Build Logging:** Added file size reporting for bundled binaries and clearer progress indicators (✓ = success, 🎯 = bundled, ❌ = critical).

---

## [1.0.2] - 2026-08-29

### Patch: Bulletproof Audio Crash Guard & Developer Credit

**Overview:** v1.0.2 implements a bulletproof exception handling layer around all audio/Whisper/CTranslate2 operations, preventing silent application crashes and providing graceful error recovery with developer attribution.

### Added

- **Developer Credit:** Added "Developed by Passagain P." footer credit in main application window for attribution.
- **Bulletproof Audio Crash Guard:** Implemented dual-layer exception handling:
 - Outer `BaseException` catch in `_convert_worker()` guards against CTranslate2, FFmpeg, and Whisper runtime crashes
 - Inner `BaseException` catch in `audio_engine.convert()` ensures audio processing errors never crash the engine
 - Both layers log full tracebacks and display user-friendly error messages

### Fixed

- **Silent Audio Crashes:** Prevented rare CTranslate2/Whisper library crashes from silently terminating the application
- **Thread Cleanup Guarantee:** Added `root.update_idletasks()` in finally block to ensure UI state cleanup even during catastrophic errors
- **Error Recovery:** Bulletproof handlers ensure clean error dialogs and proper button state restoration after any audio processing failure

---

## [1.0.1] - 2026-08-29

### Patch: FFmpeg Bundling & System Path Resolution

**Overview:** v1.0.1 resolves the system FFmpeg dependency by bundling FFmpeg executables directly into the standalone distribution, eliminating the need for separate system installation while maintaining backward compatibility.

### Added

- **Bundled FFmpeg Executable:** PyInstaller now automatically bundles `ffmpeg.exe` and `ffprobe.exe` (if available) into the distribution, ensuring audio transcription works immediately on target systems without external FFmpeg installation.
- **Enhanced FFmpeg Path Detection:** `_get_ffmpeg_path()` now implements a multi-priority search strategy:
 1. PyInstaller `sys._MEIPASS` bundled FFmpeg
 2. Python executable directory (portable installs)
 3. Project root directory (local development)
 4. System PATH lookup
 5. `imageio_ffmpeg` package fallback

### Fixed

- **System FFmpeg Dependency:** Eliminated hard requirement for users to have FFmpeg installed on system PATH before using audio conversion features.
- **Cross-Platform Portability:** Standalone `doc2md.exe` now works on systems without FFmpeg in PATH, improving distribution and user experience.

### Enhanced

- **Build Pipeline:** `build_exe.py` now includes intelligent FFmpeg detection and bundling with fallback to `imageio_ffmpeg` package when system FFmpeg unavailable.

---

## [1.0.0] - 2026-08-29

### Major Release: Production-Ready Audio Converter

**Overview:** v1.0.0 marks the first stable production release of doc2md. Comprehensive bug audit, race condition prevention, and clean error handling ensure robust, enterprise-grade reliability.

### Added

- **Thread-Safe Race Condition Prevention:** Explicit thread joining logic in `convert_files()` ensures previous worker thread is fully terminated before spawning new conversion. Previous thread checked via `is_alive()` and joined with 5-second timeout, preventing concurrent background thread collisions.
- **Enhanced Audio Error Handling:** Specialized error parsing for FFmpeg missing binaries, GPU/CUDA fallback issues, and corrupt audio containers with friendly user-facing messages.

### Enhanced

- **Staged Files Lifecycle Management:** Added explicit `staged_files.clear()` in `_stop_conversion()` to prevent stale file re-processing.

### Fixed

- **Race Condition on Rapid Conversions:** Previous version could spawn multiple overlapping worker threads, leading to file duplication or data loss.
- **Stale Staged Files After Cancellation:** Cancelling conversion now properly resets staged files.

---

## [0.3.22] - 2026-08-27

### Added

- **Instant Worker Abort Event:** Introduced `threading.Event` abort signal mechanism for immediate transcription cancellation. Audio engine now checks `abort_event.is_set()` before and during segment processing loops to terminate heavy transcription jobs instantly upon user cancellation request, preventing long-running operations from blocking the UI.

### Fixed

- **UI State Recovery Guarantee:** Enhanced `_stop_conversion()` to immediately update status text to "Conversion cancelled by user", stop spinner animation, reset progress bar to 0%, and restore "▶️ Start Conversion" button (Emerald `#059669`) without waiting for background worker to complete. Prevents "stuck" UI state during cancellation.
- **Abort Event Integration:** Audio engine now extracts `abort_event` from conversion options dict, allowing the GUI to pass cancellation signals directly to transcription loops for instant response to user cancellation clicks.

## [0.3.21] - 2026-08-27

### Added

- **Audio Crash Prevention:** Wrapped audio transcription threads in comprehensive `try...except Exception` blocks in both `audio_engine.py` (convert method and _load_model) and GUI worker threads to prevent background exceptions from terminating the main Python process. Audio errors now trigger graceful UI error messages instead of silent crashes.

### Fixed

- **Missing Stop Button Binding:** Added explicit `update_idletasks()` call after button state change in `_start_conversion()` to ensure the "🟥 Stop Conversion" button UI updates immediately before the worker thread starts, fixing races where button clicks weren't registered.
- **Unhandled Audio Worker Exceptions:** Enhanced `_convert_worker()` with dual exception handlers (`Exception` and `BaseException`) to catch all possible audio engine failures and log them with full tracebacks instead of crashing silently.

## [0.3.20] - 2026-08-27

### Added

- **Stop Conversion Button:** Dynamic button toggle during conversion—shows red "⏹️ Stop Conversion" button while processing and switches back to green "▶️ Start Conversion" when complete. Users can cleanly abort batch processing by clicking the stop button, which sets a `stop_requested` flag that's checked between files.
- **High-DPI Awareness:** Added `SetProcessDpiAwareness(2)` Windows API call at startup for per-monitor DPI awareness, enabling crisp, razor-sharp font rendering on high-DPI displays (4K, Surface, etc.) instead of blurry scaled text.

### Fixed

- **Clean Build Pipeline:** Added explicit cleanup of `build/` and `dist/` directories at the start of `build_exe.py` before PyInstaller runs, ensuring the resulting executable always reflects the current code version without stale cache artifacts.
- **Stale Binary Cache:** Prevents version mismatch where dist/doc2md.exe was from v0.3.18 but claimed to be v0.3.20. Build now always starts fresh.

## [0.3.19] - 2026-08-27

### Fixed

- **Force Kill Process Before Setup Extraction:** Enhanced installer robustness by executing `taskkill.exe /F /IM doc2md.exe /T` at the start of installation (`ssInstall` step), ensuring all running instances (including background worker threads) are forcefully terminated before file extraction. Fixes edge cases where standard `CloseApplications` fails when background threads are active.
- **Complete Process Tree Termination:** The `/T` flag ensures the entire process tree is killed (parent + all child threads), preventing locked file handles from blocking file replacement during updates.

## [0.3.18] - 2026-08-27

### Fixed

- **Automatic Process Closure During Setup:** Updated Inno Setup installer to automatically detect and terminate running `doc2md.exe` instances before file extraction, eliminating `DeleteFile failed; code 5` (access denied) errors during updates or repairs. New configuration: `CloseApplications=yes`, `CloseApplicationsFilter=*doc2md.exe*`, `RestartApplications=no`, `AppMutex=doc2md_Single_Instance_Mutex`.
- **Installer Robustness:** Single-instance mutex prevents multiple installer instances; users can safely run the installer while the application is active without triggering file lock errors.

## [0.3.16] - 2026-08-27

### Changed

- **Explicit Conversion Workflow:** Drag-and-drop or file browser selections no longer auto-convert immediately. Instead, files are staged and a status label shows `"X file(s) ready for conversion."` Users can adjust settings (model, OCR) before clicking the new `Start Conversion` button.
- **Fixed Progress Bar Logic:** Progress bar now uses indeterminate mode (pulsing between 30% and 70%) during conversion instead of jumping instantly to 100%. Only reaches 100% when the background worker thread completes successfully, providing accurate visual feedback for long-running operations like audio transcription.

## [0.3.15] - 2026-08-27

### Fixed

- **Audio Transcribe Generator Bug:** Fixed `AttributeError: 'generator' object has no attribute 'start'` in `audio_engine.py`. `model.transcribe()` returns a `(segments_generator, info)` tuple; the generator is now explicitly unpacked and consumed into a list before segments are iterated for timestamp formatting.

### Added

- **Model Pre-loading / Warm-up:** The GUI now asynchronously loads (and caches) the selected Whisper model on startup and whenever the model dropdown changes, instead of paying the load cost lazily on the first conversion. A status indicator (`⏳ Warming up...` / `✅ model ready`) shows progress next to the model selector. `AudioEngine` gained a model instance cache (`_model_cache`) and a public `preload_model()` method.
- **Inno Setup Post-Install Launch Option:** The installer now offers a "Launch doc2md Converter" checkbox (`Flags: postinstall nowait skipifsilent`) on the final wizard page.

## [0.3.14] - 2026-08-27

### Fixed

- **Build-Time Audio Dependency Injection:** `build_exe.py` now runs `pip install ffmpeg-python faster-whisper` in the build environment before invoking PyInstaller, so its import scanner can always find these modules — fixing exe builds where the build machine hadn't manually installed the `[audio]` extra beforehand.
- **Icon-Text Alignment:** All buttons, checkboxes, the version badge, and the drag-and-drop zone now use explicit `anchor="center"`/`anchor="w"` plus a consistent height (buttons: 38px, checkboxes: 20px boxes) and the Windows-native "Segoe UI" font family, eliminating inconsistent vertical/horizontal centering of emoji icons versus label text.

### Changed

- **Modern Clean UI (Tailwind-inspired):** Replaced the pastel theme with a sharp, high-contrast interface — slate-50 page background, crisp white cards, slate-800 text, slate-200 borders, and vibrant blue-600/teal-600/red-500 primary buttons with matching hover states.

## [0.3.13] - 2026-08-27

### Changed

- **Native Drag-and-Drop (windnd):** Replaced `tkinterdnd2` with `windnd`, a lightweight Windows-native drop hook (`windnd.hook_dropfiles`), guaranteeing drag-and-drop works on compiled `.exe` builds regardless of UAC/Tcl-package limitations that previously affected `tkinterdnd2` in frozen bundles.
- **Pastel UI Redesign:** Overhauled the CustomTkinter color palette to a soft, modern pastel aesthetic — warm off-white background (`#faf7f5`), white cards, pastel indigo/mint/pink accents, and dark-plum text for readability.

### Fixed

- **Audio Dependency Bundling:** `build_exe.py` now forces `--hidden-import` for `ffmpeg` (ffmpeg-python) and `faster_whisper`, eliminating the "missing ffmpeg-python module" error in standalone `.exe` builds.
- **Runtime PATH Injection:** `doc2md_exe_entry.py` now injects `sys._MEIPASS` (the PyInstaller bundle directory) into `os.environ["PATH"]` at process startup, before any audio module import, ensuring bundled `ffmpeg.exe`/`ffprobe.exe` resolve correctly regardless of which code path triggers the import first.

### Removed

- `tkinterdnd2` dependency and all related Tcl/Tk data-file bundling in `build_exe.py`.

## [0.3.12] - 2026-08-27

### Added

- **macOS Modern UI Overhaul:** Completely redesigned dark theme with sleek charcoal background (#0a0e27), modern card styling, improved border radii (12px), and refined typography using Helvetica font family.
- **Version Badge:** Application now displays version (`v0.3.12`) in a subtle badge in the header for quick identification.
- **Embedded Progress Percentage:** Progress bar now displays percentage (`0%`, `50%`, `100%`) directly centered inside the progress bar track instead of floating outside.

### Enhanced

- Improved visual hierarchy with better spacing (padx/pady), refined accent colors, and modern macOS-inspired card design.
- Enhanced drop zone with hover effects: border color changes from subtle gray to vibrant blue on mouse enter/leave.
- Better typography: updated fonts to Helvetica with improved font sizes and weights for readability.
- Refined color palette: new border color (#2d3748) and secondary text color (#a0aec0) for better visual balance.
- Drag-and-drop zone more intuitive with visual feedback on hover.

## [0.3.11] - 2026-08-27

### Fixed

- **FFmpeg Path Resolution:** Hardcoded bundled FFmpeg runtime detection in audio processing. When running as PyInstaller bundle, audio engine now automatically detects and uses `ffmpeg.exe` and `ffprobe.exe` from `sys._MEIPASS` (bundled location) or system PATH, ensuring audio transcription works out-of-the-box without requiring separate FFmpeg installation.
- **Audio Engine Robustness:** Both ffmpeg-python and faster-whisper now have proper FFmpeg path resolution through environment variable setup before initialization.

### Enhanced

- Audio processing now logs FFmpeg path resolution for debugging: shows whether bundled or system FFmpeg is used.
- Improved error messages when FFmpeg is not available in either bundled or system location.

## [0.3.10] - 2026-08-27

### Added

- **FFmpeg Binary Bundling:** PyInstaller now attempts to bundle `ffmpeg.exe` and `ffprobe.exe` binaries if available on system PATH. Inno Setup installer includes bundled binaries for out-of-the-box audio conversion.
- **Version Embedding in GUI:** Application title now displays the current version (e.g., "doc2md Converter v0.3.10"), providing clear version visibility to users.
- **Enhanced Standalone Build:** Audio processing now works without requiring separate FFmpeg installation on target systems (if bundled during build).

### Enhanced

- Build scripts now gracefully handle FFmpeg availability with informative logging.
- Improved documentation for optional dependencies and bundled binaries.
- Version tracking: `__version__` from `doc2md/__init__.py` now displayed in GUI title bar.

## [0.3.9] - 2026-08-26

### Fixed

- **Resilient Click-to-Browse Drop Zone:** Updated drop zone UI to indicate clicking is available. Entire drop card now responds to clicks and opens file browser, providing reliable fallback when TkDND fails.
- **Transparent Conversion Error Handling:** All conversion errors now display detailed error messages in popup dialogs instead of silently failing. Error tracking collects all failures and shows them to user with file names and error types.
- **Partial Conversion Feedback:** When some files convert successfully and others fail, user sees status showing both successes and failures with error details.

### Enhanced

- Drop zone text updated: "Click or Drag & Drop Files Here" for better UX clarity.
- Error messages now include file name, exception type, and detailed message for debugging.
- Graceful handling of edge cases: missing dependencies, corrupted files, permission errors.

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
```````````````````````
````````````````````````
`````````````````````````
``````````````````````````
```````````````````````````
````````````````````````````
`````````````````````````````
``````````````````````````````
```````````````````````````````
````````````````````````````````
`````````````````````````````````
``````````````````````````````````
```````````````````````````````````
````````````````````````````````````
`````````````````````````````````````
``````````````````````````````````````
```````````````````````````````````````
