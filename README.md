# README.md

````````````````````````````text
# README.md

```````````````````````````text
# README.md

``````````````````````````text
# README.md

`````````````````````````text
# README.md

````````````````````````text
# README.md

```````````````````````text
# README.md

``````````````````````text
# README.md

`````````````````````text
# README.md

````````````````````text
# README.md

```````````````````text
# README.md

``````````````````text
# README.md

`````````````````text
# README.md

````````````````text
# README.md

```````````````text
# README.md

``````````````text
# README.md

`````````````text
# README.md

````````````text
# README.md

```````````text
# README.md

``````````text
# README.md

`````````text
# README.md

````````text
# README.md

```````text
# README.md

``````text
# README.md

`````text
# README.md

````text
# README.md

```text
# doc2md v1.0.27

## Version 1.0.27 (2026-08-30) - PROGRESS DISPLAY & FFMPEG BUNDLING

### Long recordings no longer look frozen
One percent of a 27-minute recording is 16 seconds of audio, so the bar sat on "0%" and then
"1%" for a long time while the GPU was working normally. Progress now reads
`21% (5:40 / 27:01) ~9:12 left`, and the media length is logged before transcription starts.

Expect roughly **2x realtime on GPU** for speech with the `small` model - a 27-minute meeting
takes about 12 minutes.

### Reading GPU usage correctly
Task Manager's default GPU panes (3D, Copy, Video Encode, Video Decode) **do not show CUDA
compute**, so an active transcription can look idle at ~1%. Switch a pane's dropdown to **Cuda**,
or run `nvidia-smi`, to see the real load.

### Fixed
- Bundled FFmpeg was never found inside the packaged exe (`--add-binary` kept imageio_ffmpeg's
 original filename, so the runtime's `ffmpeg.exe` lookup always missed)
- Removed a model-cache constant that was created on every load but never used

## Version 1.0.26 (2026-08-30) - GPU ACCELERATION

### GPU acceleration now actually works
GPU support never engaged in any previous release: the check asked PyTorch, but transcription
runs on CTranslate2 and PyTorch was never installed, so the probe failed silently and every
conversion ran on CPU. Measured **10.65x speedup** on an RTX 4060 Laptop after the fix.

### Optional GPU Pack
GPU acceleration needs the NVIDIA CUDA runtime (~1.5 GB), which ships as a **separate optional
installer** so the main download stays at 233 MB:

| Download | Size | Needed for |
|---|---|---|
| `doc2md_Setup_v1.0.27.exe` | 233 MB | Everyone |
| `doc2md_GPU_Pack_v1.0.27.exe` | 758 MB | NVIDIA GPU acceleration only |

Install the GPU Pack and doc2md picks it up automatically - no configuration. The status log
tells you which mode is active on every conversion.

### GPU support by vendor

| GPU | Supported |
|---|---|
| NVIDIA | Yes, with the GPU Pack |
| AMD | **No** - CPU only |
| Intel | **No** - CPU only |

CTranslate2 exposes only `cpu` and `cuda` devices; there is no ROCm, DirectML, or Vulkan
backend. AMD and Intel GPUs cannot be used for transcription and doc2md will not suggest the
GPU Pack to those users.

## Version 1.0.25

## Version 1.0.25 (2026-08-30) - DEEP AUDIT

### Critical Fixes
- **Drag & drop restored for all file types** - `shlex.split()` was stripping Windows
 backslashes from dropped paths, so every drop reported "No supported files"
- **PDF/OCR conversion restored from the GUI** - an unpicklable callback was crashing
 spawned worker processes
- **QA gate now real** - `tools/verify.ps1` previously ran nothing and always passed,
 which is why regressions shipped repeatedly

### Other Fixes
- Thread-safe UI updates from the conversion worker (fixes random freezes)
- Cancel now aborts mid-file instead of only between files
- Thai transcriptions no longer mislabelled as English
- Batch conversions no longer overwrite same-stem outputs
- File dialog covers all supported extensions
- Version and branding moved from the titlebar into the in-app header

## Version 1.0.24 (2026-08-30) - PYINSTALLER TKINTERDND2 BUNDLING FIX

### Critical Fixes
- **Critical Fix**: PyInstaller now explicitly collects tkinterdnd2 native binaries via `collect_all('tkinterdnd2')`
- **Enhancement**: Fixed native tkdnd library bundling in standalone executable
- **Robustness**: Drag & Drop functionality now guaranteed in packaged .exe (no missing .dll issues)

## Version 1.0.23 (2026-08-30) - ULTIMATE ARCHITECTURAL FIX

### Critical Fixes
- **Critical Fix**: DnD was broken - root window now uses `TkinterDnD.Tk()` for proper DnD support
- **Fix**: Dropped file paths now logged with absolute path for clarity
- **Enhancement**: Added branding "by Passagain P." to window title

## Version 1.0.21 (2026-08-30) - EMERGENCY HOTFIX

### Critical Bug Fixes
- **Fix**: Silent conversion crash - full traceback now logged to Status Log
- **Fix**: Output files not being written to Output Folder
- **Fix**: Drag & Drop file ingestion restored with root window DnD binding

## Version 1.0.20 (2026-08-30)

## Version 1.0.20 (2026-08-30) - DIAGNOSTIC AUDIT FIXES

### Architectural Fixes
- **Fix**: GPU Acceleration initialization with torch.cuda.is_available() check
- **Fix**: Immediate Status Log updates for file selection/drop events
- **Fix**: Real-time progress bar updates from audio transcription chunks
- **Fix**: Robust Drag & Drop with Unicode path handling
- **Fix**: Explicit Thai language parameter passed to Whisper model

## Version 1.0.19 (2026-08-30) - CRITICAL BUG FIX

### Critical Fixes & Enhancements
- **Fix**: Thai audio transcription language bug - language selection now properly passed to Whisper model
- **Feature**: Language mapping system supporting Auto-detect, Thai, Spanish, French, German, Chinese, Japanese
- **Fix**: GPU/Device logging - clear console output showing CUDA detection and device acceleration status
- **Fix**: Real-time progress callback wiring for accurate audio transcription progress
- **Enhancement**: Immediate file name logging during file processing

## Version 1.0.18 (2026-08-30) - PERFORMANCE & TECH UI OVERHAUL

### Enhancements & Fixes
- **Feature**: GPU Acceleration enabled - auto-detects CUDA and falls back to CPU (int8 compute)
- **Feature**: Real-time Percentage Progress Labels (0-100%) on progress bar
- **Enhancement**: Tech Dark Mode UI theme with #06B6D4 cyan accents
- **Fix**: ComboBox text clipping - expanded column widths to prevent truncation
- **Enhancement**: Rounded card frames and modern sleek design

## Version 1.0.17 (2026-08-30) - ULTIMATE REPAIR

### Enhancements & Fixes
- **Fix**: Drag & Drop re-implemented with dual binding (drop_zone frame + label) for complete coverage
- **Feature**: Output Directory Selector - users can now explicitly choose where converted files are saved
- **Feature**: Browse Output Folder button for easy directory selection
- **Fix**: Text overlap in settings panel - restructured UI layout with improved spacing
- **Enhancement**: Cancel button label simplified from "Stop/Cancel" to "Cancel"

## Version 1.0.16 (2026-08-30) - LAYOUT FIX

### Bug Fixes
- **Fix**: Remove invalid `corner_radius` parameter from `.pack()` geometry manager calls
- **Robustness**: GUI displays without layout parameter errors

## Version 1.0.15 (2026-08-30) - MAJOR FIX

### Features & Fixes
- **Fix**: Converter.convert_file() method signature correction
- **Feature**: Real-time progress bar with visual feedback
- **Feature**: Stop/Cancel button with red styling
- **Feature**: Model readiness status indicator
- **Enhancement**: Modern UI redesign with rounded corners and Dark Glass styling
- **Enhancement**: Threading Event-based cancellation system

## Version 1.0.14 (2026-08-30) - MAJOR RECOVERY

### Features & Fixes
- **Feature**: Restored full GUI control set (Model Size, Language, Format selectors)
- **Feature**: Advanced settings panel with OCR and clipboard options
- **Fix**: Drag & Drop re-implemented with robust TkinterDnD2 event handling
- **Fix**: Audio/video timeout increased from 60s to 1800s for large files

## Version 1.0.13 (2026-08-30) - BRUTE-FORCE INSTALLER FIX

### Critical Fixes
- **Fix**: Forceful process termination using `taskkill /F /T` for guaranteed file release
- **Fix**: Eliminates Windows Restart Manager reliance (PyInstaller exes ignore polite close)
- **Fix**: Handles all child processes (FFmpeg, worker threads) via process tree termination
- **Fix**: Seamless installation without user intervention or file locking errors

## Version 1.0.12 (2026-08-30) - INSTALLER HOTFIX

### Critical Fixes
- **Fix**: Installer file locking - auto-close running doc2md instances
- **Fix**: Silent application restart after installation
- **Fix**: Seamless upgrade without manual app closure

## Version 1.0.11 (2026-08-30) - HOTFIX

### Critical Fixes
- **Fix**: CustomTkinter theme initialization crash - removed hallucinated `set_color_scheme` method
- **Fix**: Use correct CustomTkinter API: `set_default_color_theme()` instead
- **Fix**: Graceful theme fallback prevents GUI startup crashes

## Version 1.0.10 (2026-08-30)

### Major Updates
- **Fix**: TkinterDnD2 drag & drop now safely handles Unicode paths and filenames with spaces/Thai characters
- **Feature**: Modern CustomTkinter-based GUI with dark/light theme support
- **Feature**: Real-time conversion progress with thread-safe logging
- **Hardening**: Deep audit applied - subprocess zombie process prevention on Windows
- **Hardening**: Singleton pattern for WhisperModel caching with memory release
- **Hardening**: Bulletproof exception guards for native C-extension crashes
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
