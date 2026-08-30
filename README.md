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
# doc2md v1.0.17

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
