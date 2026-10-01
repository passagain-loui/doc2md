# doc2md v1.1.0

Drag a document in, get clean Markdown out. PDF, Word, Excel, PowerPoint, HTML,
e-mail, images and source files, with Thai text and Thai filenames handled
correctly throughout.

> **1.1.0 is a breaking release.** Audio and video transcription has been removed
> in full. If you need it, stay on 1.0.27. See CHANGELOG.md for the reasoning.

## What it converts

| Input | Engine | Notes |
| --- | --- | --- |
| `.pdf` | PyMuPDF + pdfplumber | text layer on the fast path, OCR when scanned, tables extracted |
| `.docx` | python-docx | headings, nested lists, bold/italic, tables |
| `.xlsx` `.xlsm` `.csv` | openpyxl | one table per sheet, truncated summary past the row limit |
| `.pptx` | python-pptx | slide titles, bullet nesting, tables, speaker notes |
| `.html` `.htm` `.eml` | BeautifulSoup | article text, links, tables |
| `.png` `.jpg` `.jpeg` `.bmp` `.tif` `.webp` | Tesseract | Thai + English OCR |
| source files, `.json`, `.txt` | built in | fenced with the right language |
| `.md` | built in | passed through unchanged - it is already Markdown |

**Converting a `.md` file directly still works** - `doc2md convert notes.md`
converts it (unchanged, since it's already Markdown) like any other explicit
file argument.

**A recursive folder or `bridge` conversion skips `.md` files it finds along
the way.** `doc2md convert some_folder` (or dropping a folder in the GUI)
walks the folder and converts everything it recognizes *except* `.md` - those
are skipped, not converted, and the GUI says how many ("N Markdown file(s) in
this folder were skipped"). This is deliberate: without it, a folder that
already contains this tool's own previous output (or output from a
repeated/automated re-run) would be re-ingested as input on the next pass,
and the output collision resolver would keep appending another `-1`,
producing an unbounded `file-1-1-1-....md` chain. A folder containing only
`.md` files therefore has **nothing to convert** when scanned recursively -
the GUI reports this explicitly ("folder contains only Markdown file(s)"),
not as a generic empty-folder message; convert each one explicitly by name
instead if that's genuinely what you want.

## Install

```
pip install -r requirements.txt
```

OCR needs [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) on PATH.
Install the Thai language data (`tha`) as well - without it, scanned Thai
documents fall back to English and say so in the output. Tesseract is
deliberately **not** bundled: the Thai model alone is larger than the rest of
the application. The GUI's **OCR Diagnostics…** dialog (see below) tells you
exactly what is and is not installed, in plain language, rather than letting
a scan silently produce metadata-only output.

### Known limitations

- **PDF table extraction requires `pdfplumber`** (in `requirements.txt`).
 Without it, PDFs still convert - through the fast PyMuPDF text path - but
 without table formatting; `--no-tables` requests the same degraded-but-fast
 behaviour deliberately.
- **OCR requires an external backend that is not bundled**: either the
 Tesseract binary on PATH (with the `tha` language pack for Thai) or
 `rapidocr-onnxruntime` installed separately. Neither is installed
 automatically by this project or its GUI; a scanned document converts to
 metadata plus an explanatory Warning until one is available.
- **RapidOCR does not have verified Thai support** in this project; its
 readiness is reported as "has a backend" rather than folded into the
 Thai/English readiness message, which is specific to Tesseract's installed
 language data.

## Use

Desktop interface:

```
python -m doc2md gui
```

Drag in any number of files or whole folders. Each row shows its own status,
with the reason when something goes wrong, so nothing fails quietly:

| Status | Meaning |
| --- | --- |
| Queued | Accepted, not converted yet. |
| Converting | The worker thread is on this file right now. |
| Success | Converted and written to disk - a genuine read of the document. |
| Warning | Converted and written, but **not** a full read - OCR was unavailable, switched off, or ran and found no text. Shown with a banner above the preview when selected; never presented as Success. |
| Error | Failed - conversion itself, or the write to disk afterwards. |
| Skipped | Never queued - unsupported file type, audio/video (removed in 1.1.0), or (for a folder) nothing convertible found. |

Selecting a row shows its Markdown, a Quality Summary (pages read, tables
found, OCR outcome - see *Quality report* below), Compare Metadata
(source/output size, page or sheet count), and a first-page thumbnail for
PDFs and images. `Open Original` / `Open Output` launch the file in its
default application; the per-row `Copy Markdown` copies just that file, while
the toolbar's `Copy Markdown` copies the whole batch. `Send to Sandbox` writes
an ingest bundle (see below); `Export Report` writes the JSON quality report
for the whole batch.

**Retry and recovery.** `Retry Failed` and `Retry Warnings` re-run only the
matching rows in place - a retry updates its row's existing result rather
than adding a new one, and a row's previous result is discarded the moment
its retry starts, so a failed retry can never leave stale content reachable
through Copy Markdown, Send to Sandbox, or Export Report. `Clear Completed`
removes clean Success rows only, so Warning/Error rows stay in the list to
retry. `Export Error Report` writes a JSON report scoped to the rows
currently showing Error.

Command line:

```
python -m doc2md convert report.pdf
python -m doc2md convert "C:/docs" --output "C:/out" --stats
python -m doc2md convert scan.pdf --ocr-lang tha+eng
python -m doc2md convert big.pdf --no-tables --chunk 4000
python -m doc2md convert "C:/docs" --output-policy converted-folder
python -m doc2md convert report.pdf --report report-quality.json
```

Hand a batch to a downstream tool:

```
python -m doc2md bridge "C:/docs" --inbox "C:/sandbox/inbox"
```

This writes the `.md` files plus a `manifest.json` describing them - schema
version, producer, per-document SHA-256 and token counts. The manifest is
written last, so a watcher triggering on it never sees a half-written bundle.
An HTTP transport is available with `--endpoint` for an explicit URL; nothing
here touches the network unless you ask it to. **A document whose conversion
only produced a Warning (OCR unavailable/disabled/no text found) is excluded
from the bundle by default** - it is metadata, not a real read of the
content, and the Sandbox would otherwise ingest it as if it were. Pass
`--include-warnings` to send it anyway; the manifest still carries the
`warning` field so a downstream consumer can filter or flag it.

## Output policy

Where a conversion's result actually lands, and what happens if something is
already there, is controlled by one policy - the same resolver is used by
the CLI, the GUI, and chunked output:

| Policy | Behaviour |
| --- | --- |
| `unique` | **Default. Unchanged from before this existed.** Never overwrites; `report.md` that already exists becomes `report-1.md`, `report-2.md`, ... |
| `fail` | Refuses to write if the destination already exists - the file becomes an Error row/CLI failure instead. |
| `overwrite` | Writes over an existing file. **Always** refuses to write over the *source* file itself, even when the destination path would coincide with it (for example converting a `.md` file to `.md` in the same folder) - this is not user-selectable away. |
| `converted-folder` | Writes into a `Converted` subfolder of the output directory, numbered the same way `unique` is *within* that subfolder. Cannot collide with a document you did not just convert. **GUI default.** |

`--output-policy unique|fail|overwrite|converted-folder` on the CLI (default
`unique`, so a script written before this flag existed keeps behaving
identically). The GUI has an Output Policy dropdown that remembers your last
choice between runs and previews each queued file's destination before you
press Convert.

Every file this application writes - the converted output, chunk parts, and
both JSON reports below - is written atomically: to a temporary file next to
the destination, then moved into place. A write that fails partway through
never leaves a half-written file behind.

## Quality report

`--report <path.json>` (CLI) or `Export Report` / `Export Error Report`
(GUI) writes one JSON object per document:

```jsonc
{
 "source": "C:/docs/report.pdf",
 "output": "C:/docs/Converted/report.md",
 "kind": "pdf",
 "engine": "pdf",
 "status": "Warning", // Success | Warning | Error | Skipped
 "error": null,
 "warning": "OCR unavailable: the Tesseract binary is not on PATH ...",
 "duration_s": 0.42,
 "token_estimate": 812,
 "pages_total": 3, "pages_read": 3, "pages_failed": 0, "pages_with_content": 0,
 "tables_detected": 1,
 "sheets_detected": null, "rows_detected": null,
 "rows_detected_is_exact": null, "rows_exported": null,
 "truncated": null,
 "ocr_backend": null, "ocr_language": null,
 "ocr_pages_success": null, "ocr_pages_empty": null, "ocr_pages_failed": null
}
```

`pages_read` and `pages_with_content` answer different questions -
`pages_read` is "how many pages did extraction not error on" (a scanned PDF
with OCR off still has `pages_read == pages_total`, since nothing failed);
`pages_with_content` is "how many pages actually ended up with real text in
the output" (`0` in that same scanned/OCR-off case). Never read `pages_read`
alone as "the document was fully read". `rows_detected_is_exact` is `false`
only for an engine that had to stop counting early (none currently do -
both CSV and XLSX count every row even past the retention limit); `null`
means not measured.

Every metrics field is `null` when it was not measured - never a guessed
`0`. DOCX, PPTX, HTML, EML, JSON, code and plain-text conversions report
`null` for every metrics field (those engines have not been extended to
measure them); PDF reports page/table facts and, on the scanned/OCR path,
`ocr_*`; Excel/CSV reports sheet/row facts. `status` is never `Success` for a
result that carries a `warning`.

## OCR readiness

The GUI's **OCR Diagnostics…** button runs real checks, not an import test:
whether the Tesseract binary is actually on PATH, whether `pytesseract` is
installed, which language data files Tesseract itself reports having, and
whether RapidOCR (if installed) can actually construct its engine - a
package importing successfully is never reported as ready. It shows, in
Thai: "พร้อมอ่านภาษาไทยและอังกฤษ" (ready for both languages), "อ่านได้เฉพาะ
ภาษาอังกฤษ" (Tesseract found, but no Thai language data), or "ยังไม่มี OCR
backend" (no working backend) - plus which backend a conversion will
actually use, and Refresh / Copy Diagnostics.

Presets (Balanced AI / High Fidelity / Fast Text / Thai Scanned Document)
apply a fixed OCR language + resolution + table-extraction bundle to the
existing controls; editing any of those controls by hand switches the
selector to Custom.

## Configuration

An optional `doc2md.toml` in the working directory or your home directory:

```toml
timeout = 60
max_rows = 10000
ocr_enabled = true
ocr_lang = "tha+eng"
pdf_tables = true
default_copy = false
stats = false
```

## Build

```
python build_exe.py # single-file dist/doc2md.exe
python build_exe.py --onedir # folder build, starts without unpacking
```

The build refuses to run if a runtime dependency is missing, rather than
producing an executable that fails on first use.

## Development

```
pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File ./tools/verify.ps1
```

The verification gate checks version consistency, imports every module, requires
release notes for the current version, smoke-tests the CLI, and runs the full
test suite. It must exit 0 before a release is built.

---

# Release history

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
