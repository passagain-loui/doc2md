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
## [1.0.22] (2026-08-30)

- **Critical Fix**: Progress bar jumping to 100% instantly - moved progress calculation from BEFORE conversion to AFTER
- **Enhancement**: Version number now visible in window title
- **Enhancement**: GPU/CUDA detection status logged to Status Log at conversion start
- **Enhancement**: Drag & Drop verification message shown at startup in Status Log
- **Robustness**: Progress tracking now reflects actual work done, preventing false 100% signals

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
