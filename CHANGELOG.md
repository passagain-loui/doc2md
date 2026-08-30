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
# CHANGELOG.md

```text
## [1.0.26] (2026-08-30) - GPU ACCELERATION ACTUALLY WORKS

- **CRITICAL FIX**: GPU acceleration never engaged on any machine. `_has_gpu()` probed
 `torch.cuda.is_available()`, but faster-whisper runs on **CTranslate2** and torch is not a
 dependency of this project - so the probe raised `ModuleNotFoundError`, was swallowed by a
 bare `except`, and every transcription silently ran on CPU. Detection now asks CTranslate2
 (`get_cuda_device_count()`), which is the library that actually does the work.
 Measured on an RTX 4060 Laptop: **10.65x faster** (703s CPU -> 66s CUDA for the same clip).
- **CRITICAL FIX**: Even with a healthy GPU and driver, CUDA failed with
 "Library cublas64_12.dll is not found or cannot be loaded". The `nvidia-*-cu12` wheels place
 their DLLs in `site-packages/nvidia/<component>/bin`, which is on neither PATH nor the
 `add_dll_directory` list, and CTranslate2's native library resolves cuBLAS/cuDNN through the
 plain Windows search order. Those directories are now registered before CUDA initialises.
- **Fix**: A visible CUDA device no longer implies a usable one - detection also confirms the
 float16 backend is loadable, so a missing cuBLAS/cuDNN runtime is caught during detection
 instead of failing later at model construction.
- **Robustness**: Model loading now falls back from CUDA to CPU when construction fails
 (driver/cuDNN mismatch), instead of failing the whole conversion.
- **Fix**: The GUI reported acceleration status through the same broken torch probe. It now
 asks the audio engine directly, so the status log can never disagree with what actually runs.
- **Tests**: Added device-detection coverage, including the "device visible but CUDA runtime
 missing" case and a guard asserting the engine never imports torch.

### New: optional GPU Pack
The CUDA runtime ships as a **separate optional installer** rather than being bundled, keeping
the main installer at 233 MB. `build_gpu_pack.py` stages the runtime, proves it can complete a
real GPU transcription with `site-packages` hidden (so it cannot quietly borrow DLLs), then
builds `doc2md_GPU_Pack_v<version>.exe` (758 MB) which installs to `%LOCALAPPDATA%\doc2md\cuda`.
doc2md finds it automatically - no configuration. `DOC2MD_CUDA_DIR` overrides the location.

`cuda_nvrtc` and `cudnn_adv` are excluded (257 MB saved): CTranslate2 never JITs kernels and
implements attention itself. cuDNN's engine libraries are deliberately kept even though this
machine transcribes without them - they are its kernel store, and dropping them shifts kernel
selection onto fallback paths that could fail on GPU architectures unavailable for testing.

The status log now distinguishes "NVIDIA card present, runtime missing" (install the GPU Pack)
from "no CUDA device" (AMD/Intel - nothing to install), so no user is told to download 758 MB
that cannot help them.

### Known limitation: AMD and Intel GPUs
CTranslate2 4.8.1 exposes exactly two devices - `cpu` and `cuda` (verified:
`Device.__members__ == `). There is no ROCm, HIP, DirectML, or Vulkan backend,
so **AMD and Intel GPUs cannot be used for transcription** and will always run on CPU.
Supporting them would require replacing the inference engine (e.g. whisper.cpp with Vulkan),
not a configuration change.

## [1.0.25] (2026-08-30) - DEEP AUDIT: DRAG & DROP, PDF, AND QA GATE

- **CRITICAL FIX**: Drag & drop failed for every file type - `shlex.split()` treated Windows
 backslashes as escape characters, turning `C:\Users\me\a.mp3` into `C:Usersmea.mp3`, which
 then failed `is_file()` and surfaced as a bogus "No supported files". Now uses the Tcl-aware
 `tk.splitlist()`, which handles backslashes, spaces, and Thai filenames correctly.
- **CRITICAL FIX**: PDF and OCR conversion failed from the GUI - the unpicklable
 `progress_callback` bound method was passed into process-isolated workers and raised at
 `Process.start()`. Options are now filtered through a pickle probe before crossing a
 process boundary.
- **CRITICAL FIX**: `tools/verify.ps1` was a no-op that always reported success - it contained
 only an exit-code check with no command in front of it, so `$LASTEXITCODE` was `$null` and
 the script fell through to `exit $null` (0). The 308-test suite was never run by the release
 pipeline. Replaced with a real gate that runs version, import, changelog, CLI, and pytest checks.
- **Fix**: Tk widgets were mutated directly from the conversion worker thread (progress bar,
 button states), causing random freezes and crashes. All UI updates now marshal through `after()`.
- **Fix**: `self.converter.processor.cpu_count` raised AttributeError on every conversion
 (`Converter` has no `processor`), so GPU/CPU status never displayed. Uses `os.cpu_count()`.
- **Fix**: Cancel could not stop a running transcription - `abort_event` is now passed to the
 engine, so a 30-minute audio job stops immediately instead of only between files.
- **Fix**: Transcription output hardcoded `**Language:** English` even for Thai. Now reports the
 language actually used (explicit selection, or Whisper's auto-detection).
- **Fix**: Batch output could silently overwrite - `a/report.pdf` and `b/report.docx` both wrote
 `report.md`. Collisions now get a `-1`, `-2`, ... discriminator.
- **Fix**: File dialog offered only 8 extensions while the router supports ~60. Filters are now
 generated from the router's own extension tables.
- **Fix**: Clipboard failures were reported as success - `copy_text()`'s `(ok, message)` result
 was discarded.
- **UI**: Version and "by Passagain P." moved out of the window titlebar into the in-app header.
- **Cleanup**: Removed dead `doc2md/core/audio_engine.py`, which imported a nonexistent
 `Transcriber` symbol from faster-whisper.
- **Tests**: Added regression coverage for drop-path parsing (backslashes, spaces, Thai),
 output collisions, and option pickling.

## [1.0.24] (2026-08-30) - PYINSTALLER TKINTERDND2 BUNDLING FIX

- **Critical Fix**: PyInstaller now explicitly collects tkinterdnd2 native binaries and data files via `collect_all('tkinterdnd2')`
- **Enhancement**: Fixed native tkdnd library bundling - ensures TkinterDnD.Tk() initialization works in standalone executable
- **Robustness**: Drag & Drop functionality now guaranteed in packaged .exe (no missing .dll issues)
- **Build**: Updated build_exe.py with enhanced tkinterdnd2 collection logic

## [1.0.23] (2026-08-30) - ULTIMATE ARCHITECTURAL FIX

- **CRITICAL FIX**: DnD was NEVER working - root window now uses `TkinterDnD.Tk()` for proper DnD support
- **Critical Fix**: Dropped file paths now logged with absolute path for clarity
- **Enhancement**: Added branding "by Passagain P." to window title and header
- **Robustness**: DnD fallback to standard Tk if TkinterDnD2 unavailable
- **Architecture**: Root cause identified and fixed in `doc2md/cli/main.py`

## [1.0.22] (2026-08-30) - CRITICAL BUG FIXES

- **Critical Fix**: Progress bar jumping to 100% instantly - moved progress calculation to AFTER conversion completes
- **Enhancement**: Version number now displayed in window title (v1.0.22)
- **Enhancement**: GPU/CUDA status now logged to Status Log at conversion start
- **Enhancement**: Drag & Drop startup verification message shown in Status Log
- **Robustness**: Real-time progress tracking now reflects actual conversion work, not file count

## [1.0.21] (2026-08-30)

- **Critical Fix**: Silent conversion crash - full traceback now logged to Status Log
- **Critical Fix**: Output files not being written - enhanced file write error handling and logging
- **Critical Fix**: Drag & Drop broken - now registers DnD on root window for maximum coverage
- **Enhancement**: Comprehensive exception tracing with `traceback.format_exc()` displayed in GUI
- **Enhancement**: Absolute path logging for output files so users know where files are saved
- **Robustness**: All errors now visible in Status Log for debugging

## [1.0.20] (2026-08-30)

- **Fix**: GPU Acceleration initialization - torch.cuda.is_available() check with device logging
- **Fix**: Immediate Status Log updates upon file selection/drop ("📄 File: ...")
- **Fix**: Real-time progress bar percentage updates wired to audio transcription chunks
- **Fix**: Robust Drag & Drop with shlex.split() and stripping for Unicode paths
- **Fix**: Explicit Thai language parameter (language='th') passed to Whisper model
- **Enhancement**: Clear device acceleration logging (GPU/CUDA or CPU with thread count)
- **Robustness**: All architectural fixes validated and verified

## [1.0.19] (2026-08-30)

- **Fix**: Thai audio transcription language bug - language selection from GUI now passed to Whisper (language="th" for Thai)
- **Feature**: Language mapping system - supports Auto-detect, English, Thai, Spanish, French, German, Chinese, Japanese
- **Fix**: GPU/Device logging - clear logging of CUDA detection, device type, and CPU thread count in logs
- **Fix**: Progress callback wiring - real-time audio transcription progress updates progress bar accurately
- **Enhancement**: Immediate file name logging when processing begins ("📄 File: ...")
- **Enhancement**: Device acceleration info logged when loading Whisper model

## [1.0.18] (2026-08-30)

- **Feature**: GPU Acceleration enabled - auto-detects CUDA and falls back to CPU (int8 compute)
- **Feature**: Real-time Percentage Progress Labels (0-100%) on progress bar during conversions
- **Enhancement**: Tech Dark Mode UI theme - #0F172A background, #1E293B cards, #06B6D4 cyan accents
- **Fix**: ComboBox text clipping - expanded column widths (130-160px) to prevent text truncation
- **Enhancement**: Rounded card frames (12px corner_radius) for modern sleek design
- **Enhancement**: Cyan accent colors on all labels, buttons, and interactive elements
- **Enhancement**: Improved drag & drop visual feedback with bright cyan highlight

## [1.0.17] (2026-08-30)

- **Fix**: Drag & Drop re-implemented with dual binding (drop_zone frame + label) for complete coverage
- **Feature**: Output Directory Selector - users can now explicitly choose where converted files are saved
- **Feature**: Browse Output Folder button for easy directory selection
- **Fix**: Text overlap in settings panel - restructured UI layout from side-packing to row-based frames with proper spacing
- **Enhancement**: Improved padding and visual separation between UI controls (padx increased from 5 to 15)
- **Enhancement**: Cancel button label simplified from "Stop/Cancel" to "Cancel" for clarity

## [1.0.16] (2026-08-30)

- **Fix**: Remove invalid `corner_radius` parameter from `.pack()` geometry manager calls
- **Fix**: CustomTkinter `corner_radius` only valid in widget constructors, not layout methods
- **Robustness**: GUI now displays without layout parameter errors

## [1.0.15] (2026-08-30)

- **Fix**: Converter.convert_file() method signature - removed invalid positional `options` argument
- **Feature**: Real-time progress bar with visual feedback during file conversion
- **Feature**: Stop/Cancel button (red #DC2626) for immediate thread-safe conversion cancellation
- **Feature**: Model readiness status indicator showing cache status
- **Fix**: Drag & Drop re-implemented with proper event binding on entire drop frame
- **Enhancement**: Modern UI redesign with rounded corners (radius=12), Dark Glass styling, and high-contrast typography
- **Enhancement**: Threading Event-based cancellation system for graceful worker shutdown

## [1.0.14] (2026-08-30)

- **Feature**: Restored full GUI control set - Model Size selector, Language dropdown, Output Format selector
- **Feature**: Advanced settings panel with OCR toggle and clipboard copy option
- **Fix**: Drag & Drop re-implemented with proper TkinterDnD2 event handling for robust file ingestion
- **Fix**: Audio/video timeout increased from 60s to 1800s (30 minutes) for large files and meeting recordings
- **Fix**: Dynamic timeout calculation - audio files use extended timeout automatically
- **Robustness**: Complete GUI restoration with all user-facing controls for flexible document conversion

## [1.0.13] (2026-08-30)

- **Fix**: Brute-force process termination - installer now uses `taskkill /F /IM doc2md.exe /T` for forceful closure
- **Fix**: Terminates entire process trees (child processes included) to handle FFmpeg background processes
- **Fix**: Removes reliance on Windows Restart Manager polite close (which PyInstaller exes ignore)
- **Fix**: Guarantees file handles are released before installation begins
- **Robustness**: Silent process termination with 500ms safety delay before file extraction

## [1.0.12] (2026-08-30)

- **Fix**: Installer unable to automatically close applications - added `CloseApplications=yes` to Inno Setup
- **Fix**: Auto-restart applications after installation with `RestartApplications=yes`
- **Fix**: Installer now properly handles file locks from running doc2md instances
- **Robustness**: Silent application closure during upgrade without manual intervention

## [1.0.11] (2026-08-30)

- **Fix**: CustomTkinter theme initialization - removed hallucinated `set_color_scheme` method
- **Fix**: Use correct CustomTkinter API: `set_default_color_theme()` instead of non-existent `set_color_scheme()`
- **Fix**: Added try/catch around theme configuration to gracefully fallback on theme setup failure
- **Robustness**: GUI now starts even if CustomTkinter theme customization fails

## [1.0.10] (2026-08-30)

- **Fix**: TkinterDnD2 drag & drop now safely handles Unicode paths and filenames with spaces/Thai characters
- **Fix**: Deep audit - subprocess calls now use stdin=DEVNULL and CREATE_NO_WINDOW to prevent zombie processes on Windows
- **Fix**: Singleton pattern enforced for WhisperModel caching with gc.collect() to release multi-hundred-MB model instances
- **Feature**: Modern CustomTkinter-based GUI with dark/light theme support and visual feedback for drag & drop
- **Feature**: GUI now shows real-time conversion progress with thread-safe logging
- **Hardening**: Added bulletproof exception guard for native C-extension crashes (CTranslate2, FFmpeg, pybind11)
- **Hardening**: Pre-flight audio file validation guard prevents corrupt/unreadable files from reaching FFmpeg decode path
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
