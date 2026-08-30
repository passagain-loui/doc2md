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
## [1.0.27] (2026-08-30) - LONG-RECORDING PROGRESS AND FFMPEG BUNDLING

- **UX FIX**: A long recording looked frozen. Transcribing a 27-minute file showed "0%" for the
 first half-minute and "1%" for a while after, because one percent of that file is 16 seconds
 of audio - the display could not distinguish "working normally" from "hung". Verified on a
 real 27-minute meeting recording: GPU utilisation held at 26-71% with 1.5-1.8 GB of VRAM in
 use the whole time, so the run was healthy; only the readout was uninformative.
 Progress now shows position and an estimate - `21% (5:40 / 27:01) ~9:12 left` - and the
 media length is logged before transcription starts.
- **BUILD FIX**: The bundled FFmpeg was never found inside the packaged exe. `--add-binary`
 preserves the source basename, so imageio_ffmpeg's `ffmpeg-win-x86_64-v7.1.exe` landed in
 `_MEIPASS` under that name while the runtime looked for `ffmpeg.exe`; the highest-priority
 lookup always missed and fell through to slower fallbacks that may not exist on a user's
 machine at all. It is now staged as `ffmpeg.exe` (and `ffprobe.exe`), and the runtime also
 tolerates a differently-named `ffmpeg*.exe` in the bundle.
- **Cleanup**: Removed `MODEL_CACHE_DIR`, which was created on every model load but never
 passed to `WhisperModel` - models have always been cached by huggingface_hub. Overriding
 `download_root` is deliberately avoided so users are not forced to re-download models they
 already have.
- **Tests**: Replaced two tests that only asserted the unused `MODEL_CACHE_DIR` constant existed
 with ones that check real behaviour (cache reuse, and that `download_root` stays unset), plus
 coverage for the new time formatting.

### Note on reading GPU usage in Task Manager
Task Manager's default GPU panes (3D, Copy, Video Encode, Video Decode) do not show CUDA compute,
so an active transcription can appear to sit near 0%. Switch a pane's dropdown to **Cuda**, or
run `nvidia-smi`, to see the real load.

## [1.0.26] (2026-08-30)

- **CRITICAL**: GPU acceleration never actually engaged - `_has_gpu()` asked PyTorch, but
 faster-whisper runs on CTranslate2 and torch was never installed, so the check always
 returned False. Now asks CTranslate2. Measured 10.65x speedup on an RTX 4060 Laptop.
- **CRITICAL**: CUDA failed with "cublas64_12.dll not found" even on healthy systems - the
 `nvidia-*-cu12` wheel DLL directories were never registered for the Windows DLL search order.
- **Fix**: Detection verifies the float16 backend is loadable, not just that a device exists
- **Fix**: CUDA -> CPU fallback when model construction fails, instead of failing the conversion
- **Fix**: GUI acceleration status now sourced from the engine itself
- **Known limitation**: CTranslate2 supports only `cpu` and `cuda`; AMD and Intel GPUs always
 run on CPU and would need a different inference engine to accelerate.

## [1.0.25] (2026-08-30)

- **CRITICAL**: Drag & drop was broken for every file type, not just MP3 - `shlex.split()`
 stripped Windows backslashes from dropped paths. Replaced with Tcl-aware `tk.splitlist()`.
- **CRITICAL**: PDF/OCR conversion failed from the GUI - unpicklable `progress_callback` was
 sent into spawned worker processes. Options are now pickle-probed before crossing processes.
- **CRITICAL**: The QA gate (`tools/verify.ps1`) never ran anything and always reported
 EXIT_CODE 0, which is why regressions shipped in v1.0.19 through v1.0.24. Rewritten as a
 real gate; it immediately caught a pre-existing changelog test that had never been executed.
- **Fix**: Thread-unsafe Tk calls from the conversion worker (random freezes/crashes)
- **Fix**: AttributeError on `converter.processor.cpu_count` swallowed every conversion
- **Fix**: Cancel now aborts mid-file via `abort_event`, not just between files
- **Fix**: Thai transcriptions no longer report `Language: English`
- **Fix**: Batch conversions no longer overwrite same-stem outputs
- **Fix**: File dialog now covers all ~60 supported extensions instead of 8
- **UI**: Version and branding moved from titlebar into the in-app header
- **Cleanup**: Deleted dead `doc2md/core/audio_engine.py` (imported nonexistent `Transcriber`)

## [1.0.24] (2026-08-30)

- **Critical Fix**: PyInstaller `--collect-all tkinterdnd2` - ensures native tkdnd library bundled in standalone .exe
- **Build System**: Enhanced build_exe.py with explicit tkinterdnd2 collection via PyInstaller.utils.hooks.collect_all()
- **Robustness**: Drag & Drop now guaranteed to work in packaged executable with no missing binaries

## [1.0.23] (2026-08-30)

- **CRITICAL ROOT CAUSE FIX**: DnD initialization - changed from `tk.Tk()` to `TkinterDnD.Tk()` in main.py
- **Critical Fix**: DnD was completely broken because root window lacked DnD support from the start
- **Enhancement**: Dropped file paths now logged with absolute path (e.g., `C:\Users\...\file.pdf`)
- **Enhancement**: Window title now includes branding: `doc2md v1.0.23 by Passagain P.`
- **Robustness**: Graceful fallback to standard Tk if TkinterDnD2 import fails
- **Architecture**: Root cause of DnD failure traced to application entry point, not GUI bindings

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
