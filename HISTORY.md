# HISTORY.md

``````````````````````````````````````````````text
# HISTORY.md

`````````````````````````````````````````````text
# HISTORY.md

````````````````````````````````````````````text
# HISTORY.md

```````````````````````````````````````````text
# HISTORY.md

``````````````````````````````````````````text
# HISTORY.md

`````````````````````````````````````````text
# HISTORY.md

````````````````````````````````````````text
# HISTORY.md

```````````````````````````````````````text
# HISTORY.md

``````````````````````````````````````text
# HISTORY.md

`````````````````````````````````````text
# HISTORY.md

````````````````````````````````````text
# HISTORY.md

```````````````````````````````````text
# HISTORY.md

``````````````````````````````````text
# HISTORY.md

`````````````````````````````````text
# HISTORY.md

````````````````````````````````text
# HISTORY.md

```````````````````````````````text
# HISTORY.md

``````````````````````````````text
# HISTORY.md

`````````````````````````````text
# HISTORY.md

````````````````````````````text
# HISTORY.md

```````````````````````````text
# HISTORY.md

``````````````````````````text
# HISTORY.md

`````````````````````````text
# HISTORY.md

````````````````````````text
# HISTORY.md

```````````````````````text
# HISTORY.md

``````````````````````text
# HISTORY.md

`````````````````````text
# HISTORY.md

````````````````````text
# HISTORY.md

```````````````````text
# HISTORY.md

``````````````````text
# HISTORY.md

`````````````````text
# HISTORY.md

````````````````text
# HISTORY.md

```````````````text
# HISTORY.md

``````````````text
# HISTORY.md

`````````````text
# HISTORY.md

````````````text
# HISTORY.md

```````````text
# HISTORY.md

``````````text
# HISTORY.md

`````````text
# HISTORY.md

````````text
# HISTORY.md

```````text
# HISTORY.md

``````text
# HISTORY.md

`````text
# HISTORY.md

````text
# HISTORY.md

```text
# History & Verification Audit Trail

This file records verification runs, timestamps, and quality metrics per release.

## [1.0.9] - 2026-08-29

- **Verification timestamp (UTC+7 local):** 2026-08-29, Gatekeeper Protocol v5.3 (Environment Check & Auto-Fix Loop)
- **Verification Method:** `python -m pytest tests/ -v` (via `tools/verify.ps1` pre-check; LocalCore's own sandboxed environment cannot find `pytest` on its internal PATH regardless of script-level PATH injection — same known limitation diagnosed in prior releases)
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; 307 passed, 1 skipped
- **Loop iterations:** 1 (no fixes needed)
- **Features & Fixes:**
 - `AudioEngine.validate_audio_file()`: lightweight `ffmpeg -i` header probe for container integrity and audio stream presence; verified against valid/corrupt/empty/missing test files (all four cases behaved correctly)
 - GUI `_stage_files()` now validates audio/video files before staging, excluding invalid ones and reporting via message dialog instead of spawning the Audio Worker Thread
 - Same validation added inside `AudioEngine.convert()` as defense-in-depth for CLI/API callers
 - Documented the honest native-crash boundary: existing `BaseException` guard catches pybind11-translated C++ exceptions (the realistic failure mode); true segfault immunity would require per-call process isolation, which was evaluated and rejected due to forcing a full Whisper model reload on every conversion (undoing v1.0.8's model-caching optimization)
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v1.0.9

## [1.0.8] - 2026-08-29

- **Verification timestamp (UTC+7 local):** 2026-08-29, Gatekeeper Protocol v5.2 (Mandatory Auto-Fix Loop)
- **Verification Method:** `python -m pytest tests/ -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**
- **Loop iterations:** 1 (no fixes needed)
- **Features & Fixes:**
 - Auto Hardware Detection: `_load_model()` applies CUDA + `float16` when a GPU is available, else CPU + `int8` + `cpu_threads=os.cpu_count()`
 - `beam_size` default reduced from faster-whisper's default of 5 to 1 (greedy decoding) for significantly faster transcription, overridable via `options["beam_size"]`
 - `_has_gpu()` hardened to catch any exception (not just `ImportError`) from `torch.cuda.is_available()`, falling back cleanly to CPU on a broken CUDA driver
 - Default GUI audio model confirmed already `"small"` (task's suggested target); no change needed
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v1.0.8

## [1.0.7] - 2026-08-29

- **Verification timestamp (UTC+7 local):** 2026-08-29, Gatekeeper Protocol v4.7 (Complete Master Specification)
- **Verification Method:** `powershell -ExecutionPolicy Bypass -File ./tools/verify.ps1` (LocalCore CLI, `--verify --model Qwen-2.5-Coder-7B`) + `python -m pytest tests/ -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; 307 passed, 1 skipped
- **Loop iterations:** 1 (no fixes needed)
- **Root cause investigation:** User-reported bug — progress bar stuck at 0% during audio conversion, app occasionally unclosable while converting. Traced to `ffmpeg-python`'s `ffmpeg.probe()` defaulting to a bare `"ffprobe"` executable that doc2md has never bundled (only `ffmpeg.exe` via `imageio_ffmpeg`) and is not expected on a user's PATH; probing silently failed and returned `duration=0.0`, which permanently disabled the progress-callback guard (`if progress_callback and duration > 0`).
- **Features & Fixes:**
 - `_get_duration()` now probes duration via the bundled `ffmpeg.exe` directly (`ffmpeg -i <file>`, parsing `Duration:` from stderr) - no `ffprobe` dependency; verified against a synthetic test file (correct 2.0s detection vs. previous always-0.0)
 - `kill_all_ffmpeg_processes()` hardened with `creationflags=subprocess.CREATE_NO_WINDOW` and `stdin=subprocess.DEVNULL`, preventing a Windows `--windowed`-build subprocess hang risk on the main thread during window close
 - `_on_exit_request()` now runs its cleanup in a background thread with a 3-second bounded `join()`, guaranteeing `os._exit(0)` fires promptly regardless of cleanup outcome
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v1.0.7

## [1.0.6] - 2026-08-29

- **Verification timestamp (UTC+7 local):** 2026-08-29, Gatekeeper Protocol v4.7 (Complete Master Specification)
- **Verification Method:** `python -m pytest tests/ -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**
- **Loop iterations:** 1 (no fixes needed)
- **Note:** `doc2md/gui/main_window.py` was found truncated to a 16-line raw-tkinter/asyncio stub on disk prior to this task, outside of any edit made in this session. Restored the full 776-line file from git (commit `4d5e505`) before applying this release's refactor, per explicit user confirmation.
- **Features & Fixes:**
 - Decoupled Queue Architecture: Replaced the per-run worker thread that directly mutated Tk widgets with a persistent daemon `task_queue`/`result_queue` consumer, polled non-blockingly via `self.after(100, self._poll_result_queue)` on the main thread only
 - Progress Streaming: Audio/video progress callbacks now push `("PROGRESS", pct)` tuples onto `result_queue` instead of calling `self.root.after(0, ...)` from inside the engine's segment loop
 - Removed the v1.0.0 `convert_thread.is_alive()`/`join(timeout=5)` workaround; task ordering is now guaranteed by the single persistent worker consuming `task_queue` in order
 - `AudioEngine.convert()` signature and `BaseEngine` contract left unchanged (still used synchronously by the CLI and process-isolated PDF/OCR engines)
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v1.0.6

## [1.0.5] - 2026-08-29

- **Verification timestamp (UTC+7 local):** 2026-08-29, Gatekeeper Protocol v4.7 (Complete Master Specification)
- **Verification Method:** `python -m pytest tests/ -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; 307 passed, 1 skipped
- **Loop iterations:** 1 (no fixes needed)
- **Features & Fixes:**
 - Hard Exit Protocol: Overrode `WM_DELETE_WINDOW` and the Exit button so closing the app during an active conversion force-kills any spawned `ffmpeg.exe` processes (`taskkill /F /IM ffmpeg.exe /T`), deletes leftover temp `.wav` chunks from the system Temp folder, then calls `os._exit(0)` to guarantee instant termination even if the main thread is frozen inside a native transcription call
 - Grid Geometry Fix: Removed the "Open Folder" button entirely; the remaining 5 action buttons (Browse, Start/Stop, Copy, Save, Exit) now share equal width via `grid_columnconfigure(weight=1)` instead of left/right-packed uneven spacing
 - Combobox State Fix: Model selector now uses a dark `fg_color` and explicit `text_color_disabled` so it stays legible (no white-box artifact) when locked during an active conversion
 - Progress Label Fix: Percentage overlay on the progress bar now uses an explicit `fg_color="transparent"` so it no longer shows a background box over the progress track
- **Quality Metrics:** 307 tests passed (1 skipped), zero test failures
- **Build:** PyInstaller with force-embedded FFmpeg binary (`--add-binary`), clean build pipeline
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v1.0.5

## [0.3.21] - 2026-08-27

- **Verification timestamp (UTC+7 local):** 2026-08-27, Gatekeeper Protocol v4.7 (Complete Master Specification)
- **Verification Method:** Python pytest with coverage analysis (`python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -q`)
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; 307 passed, 1 skipped in ~45s
- **Loop iterations:** 1 (no fixes needed)
- **Features & Fixes:**
 - Audio Crash Prevention: Wrapped audio transcription threads in comprehensive `try...except Exception` blocks in `audio_engine.py` (convert method and _load_model) and GUI worker threads to prevent background exceptions from terminating the main Python process. Audio errors now trigger graceful UI messages instead of silent crashes
 - Missing Stop Button Binding: Added explicit `update_idletasks()` call after button state change in `_start_conversion()` to ensure the "🟥 Stop Conversion" button UI updates immediately before the worker thread starts, fixing races where button clicks weren't registered
 - Unhandled Audio Worker Exceptions: Enhanced `_convert_worker()` with dual exception handlers (`Exception` and `BaseException`) to catch all possible audio engine failures and log them with full tracebacks instead of crashing silently
- **Quality Metrics:** 307 tests passed (1 skipped), 93.45% code coverage, zero test failures
- **Build:** PyInstaller with clean build pipeline (explicit dist/ cleanup), windnd/ffmpeg/faster_whisper hidden-imports, High-DPI awareness
- **Standalone build:** `dist/doc2md.exe` (172 MB), `dist/doc2md_Setup_v0.3.21.exe`
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.21

## [0.3.16] - 2026-08-27

- **Verification timestamp (UTC+7 local):** 2026-08-27, Gatekeeper Protocol v4.4 (Mandated Roles & Traceability)
- **Gatekeeper:** LocalCore CLI via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; 307 passed, 1 skipped in 63.30s
- **Loop iterations:** 1 (no fixes needed)
- **Features & Fixes:**
 - Explicit Conversion Workflow: Drag-and-drop and file browser no longer auto-convert; files are staged with a status label showing readiness
 - Start Conversion Button: New green button to explicitly trigger the conversion process, allowing users to adjust settings (model, OCR) first
 - Progress Bar Fix: Indeterminate pulsing mode (30%-70%) during conversion, only reaching 100% when worker thread completes
 - Staging UX: Status label shows "X file(s) ready for conversion", Start Conversion button disabled until files are staged
- **Build:** PyInstaller with build-time audio dependency install, windnd/ffmpeg/faster_whisper hidden-imports
- **Standalone build:** `dist/doc2md.exe`, `dist/doc2md_Setup_v0.3.16.exe`
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.16

## [0.3.15] - 2026-08-27

- **Verification timestamp (UTC+7 local):** 2026-08-27, Gatekeeper Protocol v4.4 (Mandated Roles & Traceability)
- **Gatekeeper:** LocalCore CLI via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; 307 passed, 1 skipped in 51.86s
- **Loop iterations:** 1 (no fixes needed)
- **Fixes & Enhancements:**
 - Whisper Generator Bug: `model.transcribe()` tuple `(segments, info)` now explicitly unpacked and consumed to a list before iteration, fixing `AttributeError: 'generator' object has no attribute 'start'`
 - Model Pre-loading: `AudioEngine` gained `_model_cache` instance cache and `preload_model()`; GUI warms up the selected model on startup and on dropdown change via a background thread, with a `⏳ Warming up...` / `✅ ready` status indicator
 - Converter wiring fix: GUI now propagates the selected model into `Converter.options["audio_model"]` so the preloaded model is actually used during conversion
 - Inno Setup Post-Install Launch: Added `Flags: postinstall nowait skipifsilent` Run entry offering a "Launch doc2md Converter" checkbox
- **Build:** PyInstaller with build-time audio dependency install, windnd/ffmpeg/faster_whisper hidden-imports
- **Standalone build:** `dist/doc2md.exe`, `dist/doc2md_Setup_v0.3.15.exe`
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.15

## [0.3.14] - 2026-08-27

- **Verification timestamp (UTC+7 local):** 2026-08-27, Gatekeeper Protocol v4.4 (Mandated Roles & Traceability)
- **Gatekeeper:** LocalCore CLI via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; 307 passed, 1 skipped in 44.11s
- **Loop iterations:** 1 (no fixes needed)
- **Fixes & Enhancements:**
 - Build-Time Audio Dependency Injection: `build_exe.py` runs `pip install ffmpeg-python faster-whisper` before PyInstaller invocation
 - Icon-Text Alignment: Buttons (height=38, anchor=center), checkboxes (20x20 boxes), version badge, and drop zone all use explicit anchor + "Segoe UI" font for consistent icon/text baseline
 - Modern Clean UI: Tailwind-inspired palette — slate-50 bg, white cards, slate-800 text, slate-200 borders, blue-600/teal-600/red-500 buttons with matching hover states
- **Build:** PyInstaller with build-time audio dependency install, windnd/ffmpeg/faster_whisper hidden-imports, FFmpeg binary bundling
- **Standalone build:** `dist/doc2md.exe`, `dist/doc2md_Setup_v0.3.14.exe`
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.14

## [0.3.13] - 2026-08-27

- **Verification timestamp (UTC+7 local):** 2026-08-27, Gatekeeper Protocol v4.4 (Mandated Roles & Traceability)
- **Gatekeeper:** LocalCore CLI via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; 307 passed, 1 skipped in 39.88s
- **Loop iterations:** 1 (no fixes needed)
- **Architecture Changes:**
 - Native Drag-and-Drop: Replaced `tkinterdnd2` with `windnd` (Windows native drop hook) for reliable DnD on compiled .exe
 - Audio Dependency Injection: `build_exe.py` forces `--hidden-import` for `ffmpeg` and `faster_whisper` packages
 - Runtime PATH Injection: `doc2md_exe_entry.py` injects `sys._MEIPASS` into `os.environ["PATH"]` at process startup, before any audio import
 - Pastel UI Redesign: Warm off-white background (#faf7f5), white cards, pastel indigo/mint/pink accents, dark-plum text
- **Removed:** `tkinterdnd2` dependency and all related Tcl/Tk data-file bundling
- **Build:** PyInstaller with forced ffmpeg/faster_whisper hidden-imports, windnd hidden-import, FFmpeg binary bundling
- **Standalone build:** `dist/doc2md.exe`, `dist/doc2md_Setup_v0.3.13.exe`
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.13

## [0.3.12] - 2026-08-27

- **Verification timestamp (UTC+7 local):** 2026-08-27, Gatekeeper Protocol v4.4 (Mandated Roles & Traceability)
- **Gatekeeper:** LocalCore CLI via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; 307 passed, 1 skipped in 45.02s
- **Loop iterations:** 1 (no fixes needed)
- **Features & Enhancements:**
 - macOS Modern UI Overhaul: Redesigned dark theme with deep charcoal (#0a0e27), improved border radii (12px), Helvetica typography
 - Version Badge: Subtle version label (v0.3.12) in header for quick identification
 - Embedded Progress %: Percentage text now centered inside progress bar track instead of floating
 - Enhanced drop zone: Hover effects with border color change (gray → blue) for better visual feedback
 - Refined color palette: New border color (#2d3748) and secondary text color (#a0aec0)
- **Build:** PyInstaller with FFmpeg bundling, Inno Setup with modern installer design
- **Standalone build:** `dist/doc2md.exe` (116.3 MB), `dist/doc2md_Setup_v0.3.12.exe` (117.2 MB)
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.12

## [0.3.11] - 2026-08-27

- **Verification timestamp (UTC+7 local):** 2026-08-27, Gatekeeper Protocol v4.4 (Mandated Roles & Traceability)
- **Gatekeeper:** LocalCore CLI via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; 307 passed, 1 skipped in 44.25s
- **Loop iterations:** 1 (no fixes needed)
- **Features & Fixes:**
 - FFmpeg path resolution: Audio engine now detects bundled ffmpeg.exe from PyInstaller bundle (sys._MEIPASS)
 - Audio engine robustness: Both ffmpeg-python and faster-whisper use resolved FFmpeg path via environment variables
 - Runtime FFmpeg detection: Fallback to system PATH if bundled binary not found
 - Logging: Audio processing now logs FFmpeg path resolution for debugging
- **Build:** PyInstaller with FFmpeg bundling, Inno Setup with conditional FFmpeg inclusion
- **Standalone build:** `dist/doc2md.exe` (116.3 MB), `dist/doc2md_Setup_v0.3.11.exe` (117.2 MB)
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.11

## [0.3.10] - 2026-08-27

- **Verification timestamp (UTC+7 local):** 2026-08-27, Gatekeeper Protocol v4.3 (Strict Anti-Simulation)
- **Gatekeeper:** Direct pytest verification via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; 307 passed, 1 skipped in 35.20s
- **Loop iterations:** 1 (no fixes needed)
- **Features & Fixes:**
 - FFmpeg binary bundling: PyInstaller collects ffmpeg.exe and ffprobe.exe if available
 - Inno Setup enhanced: Installer packages bundled FFmpeg for standalone audio conversion
 - Version embedding in GUI: Application title now displays version (e.g., "doc2md Converter v0.3.10")
 - Build scripts: Graceful handling of FFmpeg availability with informative logging
- **Build:** PyInstaller with optional FFmpeg bundling, Inno Setup with FFmpeg binary inclusion
- **Standalone build:** `dist/doc2md.exe` (116.3 MB), `dist/doc2md_Setup_v0.3.10.exe` (117.2 MB)
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.10

## [0.3.9] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v4.2
- **Gatekeeper:** Direct pytest verification via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; Tests passing
- **Fixes:**
 - Resilient click-to-browse drop zone: Entire drop card clickable, falls back when TkDND unavailable
 - Transparent error handling: Detailed error messages in popups instead of silent failures
 - Partial conversion feedback: Shows successes and failures separately with error details
- **Build:** PyInstaller `--windowed` + `--icon`, CustomTkinter with improved error UI
- **Standalone build:** `dist/doc2md.exe`, `dist/doc2md_Setup_v0.3.9.exe`
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.9

## [0.3.8] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v4.2
- **Gatekeeper:** Direct pytest verification via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; Tests passing
- **Fixes:**
 - GUI Layout Crash: Fixed mixing pack/grid geometry managers, removed invalid `sticky` in .pack() calls
 - Icon Cache Bypass: Standalone icon.ico file in Inno Setup, explicit IconFilename in shortcuts, ie4uinit.exe cache refresh
- **Build:** PyInstaller `--windowed` + `--icon`, icon.ico decoupled from exe
- **Standalone build:** `dist/doc2md.exe`, `dist/doc2md_Setup_v0.3.8.exe`
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.8

## [0.3.7] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v4.2
- **Gatekeeper:** Direct pytest verification via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.45%; Tests passing
- **Fixes & Features:**
 - Multi-Format Export Engine: New `doc2md/core/exporter.py` with .md, .txt, .docx support
 - Progress Overlay: Dynamic % display on progress bar during conversions
 - Soft Dark Dashboard: New color palette (#1B222C, #242D3C, #3B82F6, #06B6D4, #F1F5F9)
 - 2-Column Layout: Reorganized GUI with left drag-zone, right options/analytics
 - Save As Button: `💾 Save As...` with multi-format file dialog
 - Test Coverage: Added test_exporter.py with 5 new tests for export functionality
- **Build:** PyInstaller `--windowed` + `--icon`, CustomTkinter 5.0+, python-docx 1.1+
- **Standalone build:** `dist/doc2md.exe`, `dist/doc2md_Setup_v0.3.7.exe`
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.7

## [0.3.5] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v4.2
- **Gatekeeper:** Real LocalCore.exe binary verification via `cmd /c "C:\Program Files\LocalCore\LocalCore.exe" --verify "python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v" --model "Qwen-2.5-Coder-14B"`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; Coverage: 93.68%; Tests passing
- **Fixes:**
 - CustomTkinter dark UI: Complete GUI redesign with slate dark (#0F172A) + cyan (#06B6D4) theme
 - TkDND crash guard: Wrapped drag-and-drop in try-except with fallback to browse button
 - Icon embedding: Updated Inno Setup to bind assets/icon.ico to shortcuts
 - PyInstaller data collection: Added collect_data_files('tkinterdnd2') for complete bundling
- **Build:** PyInstaller `--windowed` + `--icon`, CustomTkinter 5.0+, tkinterdnd2 with fallback
- **Standalone build:** `dist/doc2md.exe`, `dist/doc2md_Setup_v0.3.5.exe`
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.5

## [0.3.3] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v4.2
- **Gatekeeper:** Real LocalCore.exe binary verification via `cmd /c "C:\Program Files\LocalCore\LocalCore.exe" --verify "python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v" --model "Qwen-2.5-Coder-14B"`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; "Required test coverage of 90% reached. Total coverage: 93.68%"; `302 passed, 1 skipped in ~20s`
- **Test count:** 303 total (302 passed, 1 skipped) — no new tests required; fixes are UI/icon updates
- **Coverage metrics:** 93.68% (1710 core statements, 108 missed) — unchanged from v0.3.2
- **Fixes:**
 - PyInstaller: Changed `--console` to `--windowed` to eliminate terminal window flicker on double-click
 - GUI Exception Handling: Wrapped entry point in try-except with user-friendly error dialogs
 - Icon Redesign: Modern dark slate (#1E1E2E) + cyan (#00F2FE) "MD" branding in 16x16 to 256x256 sizes
- **Standalone build:** `python build_exe.py` -> `dist/doc2md.exe` (115.3 MB), `python build_installer.py` -> `dist/doc2md_Setup_v0.3.3.exe` (116.3 MB)
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.3

## [0.3.2] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v4.1
- **Gatekeeper:** Direct pytest verification via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; "Required test coverage of 90% reached. Total coverage: 93.68%"; `302 passed, 1 skipped in ~20s`
- **Test count:** 303 total (302 passed, 1 skipped) — no new tests required; fix is entry-point logic only
- **Coverage metrics:** 93.68% (1710 core statements, 108 missed) — unchanged from v0.3.1
- **Fix:** Auto-launch GUI when exe is run with zero CLI arguments (double-click from desktop/installer)
- **Entry-point change:** Updated `doc2md_exe_entry.py` to detect `len(sys.argv) == 1` and inject `"gui"` subcommand
- **CLI config change:** Updated `typer.Typer` config `no_args_is_help=False` to allow zero-argument entry
- **Standalone build:** `python build_exe.py` -> `dist/doc2md.exe` (115.3 MB), `python build_installer.py` -> `dist/doc2md_Setup_v0.3.2.exe` (116.3 MB)
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.2

## [0.3.1] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v4.1 (Final Build)
- **Gatekeeper:** Direct pytest verification via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; "Required test coverage of 90% reached. Total coverage: 93.68%"; `302 passed, 1 skipped in 19.45s`
- **Test count:** 303 total (302 passed, 1 skipped; up from 275+ in initial audit), including 20+ new deep-audit edge-case tests
- **Coverage metrics:**

| Module | Statements | Miss | Cover |
| --- | --- | --- | --- |
| doc2md/cli/main.py | 170 | 11 | 94% |
| doc2md/core/chunker.py | 155 | 18 | 88% |
| doc2md/core/converter.py | 132 | 1 | 99% |
| doc2md/core/router.py | 139 | 2 | 99% |
| doc2md/engine/ocr_engine.py | 109 | 7 | 94% |
| All other modules | — | — | 86–100% |
| **TOTAL** | **1710** | **108** | **93.68%** |

- **Deep audit findings:** 20+ edge-case tests verified across GUI threading, Audio Engine resilience, document converter robustness, and file system edge cases. All audit tests PASS with no bugs identified in core conversion logic.
- **Standalone build:** `python build_exe.py` -> `dist/doc2md.exe` (115.3 MB), `python build_installer.py` -> `dist/doc2md_Setup_v0.3.1.exe` (116.3 MB).
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.1

## [0.2.1] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v3.4
- **Gatekeeper:** Direct pytest verification (LocalCore fallback for git)
- **Result:** `EXIT_CODE:0` — VALIDATION PASSED; "Required test coverage of 90% reached. Total coverage: 94.08%"; `252 passed in 20.40s`
- **Test count:** 252 (up from 210 in v0.2.0), including 42 new edge-case tests in `test_edge_bugs.py`
- **Coverage metrics:**

| Module | Statements | Miss | Cover |
| --- | --- | --- | --- |
| doc2md/cli/main.py | 161 | 3 | 98% |
| doc2md/core/chunker.py | 155 | 18 | 88% |
| doc2md/core/clipboard.py | 13 | 0 | 100% |
| doc2md/core/config.py | 72 | 7 | 90% |
| doc2md/core/contextmenu.py | 79 | 7 | 91% |
| doc2md/core/stats.py | 42 | 1 | 98% |
| doc2md/core/tokens.py | 38 | 0 | 100% |
| doc2md/engine/ocr_engine.py | 109 | 7 | 94% |
| All other modules | — | — | 86–100% |
| **TOTAL** | **1688** | **100** | **94.08%** |

- **New stress-test scenarios verified:** OCR pure black/white/noise images, ultra-high-resolution 8K images, palette PNGs, 16-bit TIFFs, transparent WebP, EXIF-rotated JPEGs, 10 parallel OCR threads with zero temp leaks, CLI edge cases (invalid paths, read-only outputs, empty clipboard, glob patterns, timeout/max-rows/chunk validation).
- **GitHub integration:** Added `.gitignore`, `LICENSE` (MIT), enhanced `README.md` with badges & usage examples, and CI/CD workflows (`.github/workflows/ci.yml` for testing, `.github/workflows/release.yml` for auto-release).
- **Standalone build:** `python build_exe.py` -> `dist/doc2md.exe` (PyInstaller onefile), `python build_installer.py` -> `dist/doc2md_Setup_v0.2.1.exe` (Inno Setup).

## [0.2.0] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v3.4
- **Gatekeeper:** LocalCore (`C:\Program Files\LocalCore\LocalCore.exe --verify "pytest --cov=doc2md --cov-fail-under=90 tests/" --model "Qwen-2.5-Coder-14B"`)
- **Result:** `EXIT_CODE:0` — VALIDATION PASSED; "Required test coverage of 90% reached. Total coverage: 93.58%"; `210 passed in 12.19s`
- **Test count:** 210 (up from 135 in v0.1.2)
- **Coverage metrics:**

| Module | Statements | Miss | Cover |
| --- | --- | --- | --- |
| doc2md/cli/main.py | 161 | 8 | 95% |
| doc2md/core/chunker.py | 168 | 21 | 88% |
| doc2md/core/clipboard.py | 13 | 0 | 100% |
| doc2md/core/config.py | 72 | 7 | 90% |
| doc2md/core/contextmenu.py | 76 | 7 | 91% |
| doc2md/core/stats.py | 42 | 1 | 98% |
| doc2md/core/tokens.py | 38 | 0 | 100% |
| doc2md/engine/ocr_engine.py | 93 | 7 | 92% |
| All other modules | — | — | 86–100% |
| **TOTAL** | **1682** | **108** | **93.58%** |

- **New features verified by tests:** clipboard copy (`--copy`), token stats (`--stats`), semantic chunking (`--chunk`), context-menu install/uninstall/status (HKCU), `doc2md.toml` config precedence and malformed-config warning, RapidOCR fallback backend.
- **Standalone build:** `python build_exe.py` -> `dist/doc2md.exe` (PyInstaller onefile), smoke-tested with `dist\doc2md.exe --help`.

## [0.1.2] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v3.4
- **Gatekeeper:** LocalCore (`C:\Program Files\LocalCore\LocalCore.exe --verify "pytest --cov=doc2md --cov-report=term-missing --cov-fail-under=90 tests/" --model "Qwen-2.5-Coder-14B"`)
- **Result:** `EXIT_CODE:0` — VALIDATION PASSED; "Required test coverage of 90% reached. Total coverage: 94.72%"; `135 passed in 9.73s`
- **Test count:** 135 (up from 50 in v0.1.1)
- **Coverage metrics:**

| Module | Statements | Miss | Cover |
| --- | --- | --- | --- |
| doc2md/__init__.py | 4 | 0 | 100% |
| doc2md/cli/main.py | 85 | 1 | 99% |
| doc2md/core/cleaner.py | 71 | 1 | 99% |
| doc2md/core/converter.py | 131 | 1 | 99% |
| doc2md/core/encoding.py | 25 | 0 | 100% |
| doc2md/core/router.py | 131 | 2 | 98% |
| doc2md/engine/code_engine.py | 46 | 0 | 100% |
| doc2md/engine/docx_engine.py | 83 | 7 | 92% |
| doc2md/engine/excel_engine.py | 99 | 6 | 94% |
| doc2md/engine/ocr_engine.py | 53 | 3 | 94% |
| doc2md/engine/pdf_engine.py | 72 | 8 | 89% |
| doc2md/engine/pptx_engine.py | 92 | 13 | 86% |
| doc2md/engine/web_engine.py | 211 | 16 | 92% |
| **TOTAL** | **1156** | **61** | **94.72%** |

- **Newly hardened scenarios:** password-protected PDF (AES-256) and OLE-container DOCX → graceful errors; corrupted OOXML zips; truncated CSV/JSON; >260-char Windows paths incl. `\\?\` fallback; Thai/space paths; concurrent worker temp isolation; child crash (`os._exit`) containment; UTF-8 BOM / CP874 / TIS-620 matrix; PDF OCR fallback success + both failure branches.

## [0.1.1] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v3.4
- **Gatekeeper:** LocalCore (`C:\Program Files\LocalCore\LocalCore.exe --verify "pytest tests/ --maxfail=1 --timeout=10" --model "Qwen-2.5-Coder-14B"`)
- **Result:** `EXIT_CODE:0` — VALIDATION PASSED, `50 passed in 4.67s`
- **Coverage metrics (pytest-cov):**

| Module | Statements | Miss | Cover |
| --- | --- | --- | --- |
| doc2md/__init__.py | 4 | 0 | 100% |
| doc2md/cli/main.py | 85 | 10 | 88% |
| doc2md/core/cleaner.py | 71 | 1 | 99% |
| doc2md/core/converter.py | 129 | 31 | 76% |
| doc2md/core/encoding.py | 25 | 3 | 88% |
| doc2md/core/router.py | 131 | 17 | 87% |
| doc2md/engine/code_engine.py | 46 | 4 | 91% |
| doc2md/engine/docx_engine.py | 83 | 15 | 82% |
| doc2md/engine/excel_engine.py | 99 | 14 | 86% |
| doc2md/engine/ocr_engine.py | 53 | 23 | 57% |
| doc2md/engine/pdf_engine.py | 45 | 12 | 73% |
| doc2md/engine/pptx_engine.py | 85 | 30 | 65% |
| doc2md/engine/web_engine.py | 211 | 60 | 72% |
| **TOTAL** | **1120** | **231** | **79%** |

- **Resilience scenarios verified by tests:**
 - Corrupted PDFs (garbage bytes and truncated real PDF) → graceful failure, no crash
 - Missing/corrupted encodings (TIS-620/cp874 Thai payloads) → charset_normalizer fallback decodes correctly
 - Large files (20,000-row CSV; 200-row workbook with lowered limits) → Truncated Summary, bounded memory
 - Watchdog timeouts in both thread and spawned-process execution → worker terminated, CLI survives
 - Temp artifact cleanup for OCR intermediates → no leftover `doc2md_ocr_*` directories

## [0.1.0] - 2026-08-26

- Initial implementation of all modules (router, engines, cleaner, converter, CLI).
- Local test suite established: 50 tests covering routing, cleaning, engines, resilience, CLI, and version sync.
```
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
````````````````````````````````````````
`````````````````````````````````````````
``````````````````````````````````````````
```````````````````````````````````````````
````````````````````````````````````````````
`````````````````````````````````````````````
``````````````````````````````````````````````
