# History

## [1.4.7] - 2026-10-06 - Corruption worse than the detector expected

The user converted a real Toyota Camry 2019 brochure PDF and pasted back a
page that was pure noise - no Thai, no English, just symbol soup like
"N6B)4<br>A);I115C%584Aē611". Read the page directly with pymupdf instead
of guessing: 4,882 characters of extracted text, 1,368 of them control
characters, and exactly 0 real Thai letters. The page's font
(`HLYROE+DBHeavent`, a Type0/Identity-H embedded font) has no usable
character map at all - not the narrower sara-am/sara-aa swap `pdf_text.py`
already handled, but total loss.

`thai_text_is_corrupt()` existed to catch exactly this family of bug, but
its first line was `thai = len(_THAI_LETTER.findall(text)); if thai < 50:
return False` - a page with no surviving Thai letters never even reached
the control-character check that would have caught it. Reordered so the
control-character check runs unconditionally; the Thai-letter count now
only gates the narrower symbol-sandwiched-in-Thai heuristic, which does
need a real baseline to mean anything. Verified against all 9 pages of the
actual PDF before and after: page 9 (the only one with a text layer at
all) now correctly flags as corrupt and falls back to OCR instead of
emitting the control-character garbage. Added a regression test matching
the real page's shape - heavy control-character noise, zero Thai letters -
since the existing corruption tests all had substantial Thai content and
wouldn't have caught this ordering bug.

Also corrected the previous turn's bad advice: told the user to try "Thai
Scanned Document (High Fidelity, 400 DPI)" as if that were one preset -
it's two. "Thai Scanned Document" forces Thai-only OCR (`tha`), which on
a bilingual document garbles every English word into Thai-shaped noise.
"High Fidelity" is the one that keeps `tha+eng` and raises DPI to 400.

## [1.4.6] - 2026-10-05 - A progress bar that doesn't look stuck

The user tested the app on a real 24-page bilingual lease agreement and
sent a screenshot of the progress bar sitting at "0%" / "0 / 1" during a
long OCR run, asking whether it could show real percentage.

Checked the architecture before promising anything: PDF/OCR conversion
runs in a spawned, isolated worker process (`_run_in_process` in
`converter.py`) that communicates back over a single pipe, read once when
the whole file is done - there is no channel today for that process to
report "page 7 of 24" partway through. Building one would mean touching
the process-isolation plumbing, the PDF/OCR engine's page loop, and the
GUI's signal wiring - a real feature, not a quick fix, and higher-risk
because it touches the well-tested OCR pipeline.

Shipped the honest, low-risk version instead: the bar goes indeterminate
("busy") the moment a file starts converting and back to a real file-level
percentage the moment it finishes, so a long single-file OCR run no longer
looks frozen. Real per-page progress is still open if the user wants it as
its own piece of work.

Separately, caught and corrected a mistake from the previous turn: the
earlier reply told the user to try "Thai Scanned Document (High Fidelity,
400 DPI)" as if that were one preset - it is two different ones.
"Thai Scanned Document" forces `ocr_lang: tha` (Thai-only), which on this
bilingual Thai/English contract made the English text drop out, garbled to
Thai-shaped letters it was never written in. "High Fidelity" is the one
that actually keeps `tha+eng` and raises DPI to 400 - that's the one worth
trying on this document, not the other.

## [1.4.5] - 2026-10-04 - A detailed bug sweep

The user asked for a thorough bug check rather than a specific feature or
report. Read through the whole GUI module end to end and confirmed three
issues before touching any code - each with a repro script, not just a
hunch:

1. `clear_completed()` removed tree rows using each item's position
   *within `self._items`* as if that were also its position in the tree.
   That holds as long as every row the tree shows is also tracked in
   `self._items` - but a skipped-folder explanation row is added straight
   to `file_tree` and deliberately never tracked there (it isn't a file,
   there's nothing to convert or retry). Once one of those sits between
   two tracked rows, the two indexings diverge and `takeTopLevelItem()`
   removes whatever happens to be at that tree position, not the row
   that was meant to go. Fixed by looking up each row's real tree index
   (`indexOfTopLevelItem`) at removal time instead of assuming the two
   orderings match.
2. The thumbnail widget - alive internally since the original redesign
   stopped showing it, kept only so `_update_thumbnail()`'s pixmap-building
   logic stays exercised - was built with `QLabel()` and no parent. An
   unparented `QWidget` is a top-level window to Qt; calling `.show()` on
   it, which `_update_thumbnail()` does for every PDF/image selected, would
   produce a real floating OS window. The test suite is blind to this
   because it runs under `QT_QPA_PLATFORM=offscreen`, where showing a
   top-level widget has no visible effect either way. Fixed by parenting
   the widget to its container and moving it off-screen, so it stays an
   ordinary, invisible child.
3. The cross-drop duplicate check in `_apply_scan` compared `str(path)`
   directly, while `collect_files()`'s own internal dedup resolves paths
   first. Two spellings of the same file across two separate drops (e.g. a
   path with a redundant `.` segment) weren't recognized as the same file
   and would queue - and convert - twice.

All three got a regression test alongside the fix, not just a manual
repro: `test_clear_completed_removes_the_right_rows_around_a_skipped_folder_row`,
`test_thumbnail_label_is_not_a_top_level_window`, and
`test_the_same_file_is_not_queued_twice_via_a_differently_spelled_path`.

## [1.4.4] - 2026-10-04 - The files panel is the drop target

The user wanted the separate "Drag & drop documents here" box gone and the
FILES panel to take over both of its jobs: accept the drop and show what
landed. The window already accepted drops anywhere - that part needed no
new code. What changed is the FILES column itself: it now holds a
`QStackedWidget` with the drop-zone widget on one page and the file tree on
the other, and `_update_actions()` (already called after every state change
that could add or clear files) swaps to whichever one has something to
show. The swap is keyed off the tree's actual row count, not
`self._files`, so a folder drop that resolves to nothing but
already-converted `.md` files still shows its skip-reason row instead of
silently falling back to the empty-state invitation.

## [1.4.3] - 2026-10-04 - One line instead of two

Another screenshot, this time of the toolbar row right under "MARKDOWN
PREVIEW": the Success badge and "1 sheet(s) · rows 141/141" on one line,
then "Source: 19.5 KB · Output: unknown · Sheets: 1 · Rows: 141/141 ·
Warning: none" repeating most of the same facts on the row right below it.
The user wanted the Source fact folded up into the badge's row and the
leftover row gone, so the preview box's top edge could move up to meet it.

"Output: unknown" turned out to be permanently dead text - no code path
has written an output path since 1.4.0 removed auto-save, so it could
never read anything else. Merged what was left (source size) into the
quality-detail label itself, deleted the second line and the method that
built it (`_update_compare_metadata`), and dropped the now-unused
`MetaFooter` stylesheet rule. One line now: `source 6.2 KB · 1 sheet(s) ·
rows 141/141`.

## [1.4.2] - 2026-10-04 - Stale preview, flush panel edges

Two reports against the 1.4.1 layout, both from a screenshot of the real
app: the preview stayed on its placeholder text after a real conversion
succeeded, and the preview box stopped noticeably short of the file list's
bottom edge, leaving a visible strip of dead space under it.

The blank preview turned out to be a genuine bug, not a rendering hiccup -
confirmed with a repro script before touching anything. Selecting a row
*before* its conversion finishes (easy to do with a single file: it auto-
selects into "Converting" almost immediately) means that row is already
`currentItem()` when `_on_file_finished` runs. The code only refreshed the
quality badge for that case, not the preview text - so the badge caught up
but the markdown pane never did, even though `self._markdown[index]` had
the real content the whole time. Fixed by routing that path through the
same full refresh a fresh click gets.

The dead space was a layout ordering issue: the compare-metadata line was
the last widget in the preview column, after the actual text box, so the
box itself stopped short to leave room for it. Moved the metadata line
above the box instead - now the preview box is the last widget, exactly
like the file tree is in its own column, so both bottoms land flush.

## [1.4.1] - 2026-10-04 - Side-by-side layout, fewer buttons

The user looked at a screenshot of the running window and asked for a pass
on button clutter and the cramped preview panel. Files and Preview went from
a vertical stack to a horizontal split, which gives the preview the full
window height instead of half of it. Three buttons came out: "Add files"
(the drop zone already does this on click), "Send to Sandbox" (still works
from the CLI, just not surfaced in the main window), and "Open Output" (it
had been permanently disabled since 1.4.0 removed auto-save — nothing was
ever going to populate a destination path for it to open again).

## [1.4.0] - 2026-10-04 - Export choices, no auto-save

The user asked for two things: be able to choose the export format (md/txt/json),
and stop writing files to disk automatically during conversion. Both are done.

Conversion now keeps everything in memory. The "Export…" button opens a Save
dialog where the user picks a format and location. The settings card is
correspondingly leaner: the output policy dropdown, "save next to source"
checkbox, and "copy to clipboard" checkbox are all gone.

## Where the project stands (2026-10-03, at the move to a new machine)

Since 1.1.0 turned an audio tool into a document converter, the work has run in
three arcs. 1.2.x made the product safe and honest: atomic output sets, truthful
quality reports, a GUI that accepts drops anywhere, and spreadsheets that keep
their titles, merged headers and dates. 1.3.0 closed the gaps a user would hit
first - old Office files, installing OCR from the app, cancelling mid-file, and
a token count that is measured rather than guessed. 1.3.1-1.3.5 were driven by
real documents, one batch at a time, and each taught something the test suite
could not: brochures with panels, fonts whose Thai maps are wrong, text layers
that lie, and a "fix" that made grey scans worse until it was measured.

The pattern worth keeping: run a real file, compare with the original, fix the
cause, then re-run the earlier files before shipping. Open items, setup steps and
gotchas for the next machine are in HANDOFF.md.

## [1.3.5] - 2026-10-02 - Measuring the fix

The 1.3.2 fix for a missing table header worked on the brochure it was built
from and quietly made a different kind of document worse, which only showed up
when a certificate was run through it. Three numbers on one page set were enough
to see it, and enough to fix it: the cure for a coloured bar was never to whiten
light pixels, only coloured ones. The model upgrade everyone expects to help,
`tessdata_best`, was tried the same way and did not, so it was not shipped.

## [1.3.4] - 2026-10-02 - A batch of real files

Six more real documents, run through at once, did more than any single sample:
they showed that the earlier repair for one font was a special case of a more
common problem. In this library about one Thai page in twenty has a text layer
that is wrong in ways that look like text. The honest response was not another
repair rule but a detector and a different route - read the page as an image -
with a flag when that route is not available.

## [1.3.3] - 2026-10-02 - When the text layer lies

A PDF with a real text layer is supposed to be the easy case. This one - a price
quote exported from Excel - extracted to wrong Thai with plausible-looking
letters, and nothing in the output said so. The first guess (fix the extractor)
was wrong; the PDF's own font table was wrong, and the two bugs in it cancelled
into a pattern that can be recognised from the characters themselves. A repair
that rewrites text has to be as narrow as the evidence, so it fires only for a
font in which the pattern was seen. The same afternoon's poster was a reminder
of the opposite: when one reading of an image is unreliable, several are more
honest than a better-tuned one.

## [1.3.2] - 2026-10-02 - The missing header row

Reading the brochure's table output a second time turned up what the first fix
did not: every row was now on its own line, but the row that says which column is
which model was gone. The values were right and unattributable, the worst kind of
correct. Tesseract had classed the pastel header bar as a picture. Making the
fill white was enough; the text was never the problem.

## [1.3.1] - 2026-10-02 - Reading a brochure

The first real scan through the new OCR install was a car brochure, and it
showed what plain OCR does to a catalogue: it reads four side-by-side tables as
one wide table, and turns photographs into lines of symbols. The fix was
measured on the same pages, but the transcription used as ground truth was read
by hand, so the 92-94% accuracy figure is an estimate, not a benchmark.

One attempt was dropped after measuring it: building the text from Tesseract's
word data gave better row structure but put spaces inside Thai words, which
Tesseract's own text output does not. The final version keeps its spacing and
uses the word data only to find noise.

## [1.3.0] - 2026-10-02 - Old files, OCR setup, cancel, counting

A candid assessment of 1.2.2 found four things a user would trip over, and each
one was something the tool had been silent about. It refused `.xls`/`.doc`/`.ppt`
though most Thai offices still have them; it told the user to install a 300 MB
OCR program by hand; Cancel did nothing until the current file finished; and it
reported token counts that were only ever right for English.

The token counts were the one claim nobody had checked, so they were measured:
the old estimate was wrong by 43% on average and by a factor of three on Thai.
The replacement was fitted on real documents and judged only on documents it had
not seen.

The legacy formats were written against real files rather than only synthetic
ones. That mattered: real `.doc` files turned up Word documents that hold nothing
but a scanned picture, HTML pages saved as `.xls`, and a crash in the HTML engine
on pages without a title - none of which a hand-built fixture would have found.

## [1.2.2] - 2026-10-01 - Merged cells

The follow-up the previous release named as its limit. Merges are the only way
a spreadsheet says "this label covers those columns", so ignoring them left
calendar-style sheets as grids of unnamed columns. They are read from the sheet
XML rather than by loading the workbook, which keeps large files streaming.

## [1.2.1] - 2026-10-01 - Spreadsheet output

A real workbook showed what the earlier Excel work had missed: correct cells
are not the same as a readable document. Most of the workbook's sheets were
hidden archives, every sheet began with a title the converter took for the
header, and dates carried a meaningless midnight. None of it was wrong data;
all of it made the result harder for a model to use, which is the point of the
tool.

## [1.2.0] - 2026-10-01 - Product hardening and UX improvement

1.1.0 made doc2md a document converter again. This round asks a different
question: once a conversion finishes, can the user actually trust the
result without opening the output file to check?

Most of the underlying data already existed - the PDF engine already knew
how many pages it read and how many tables pdfplumber found, the Excel
engine already knew whether a sheet was truncated - it just never left the
engine. `doc2md.core.quality` gives that a stable shape (`QualityMetrics`,
carried on every `ConversionResult`) that the CLI (`--report`) and the GUI
(a Quality Summary strip, an Export Report button) read from the same
object, so the two surfaces cannot disagree about what happened. A field is
`null` rather than a guessed `0` for any engine that has not been migrated
to report it - DOCX, PPTX, HTML, EML, JSON, code and plain text stay
string-only and simply report nothing measured, which was the explicit
design goal: extending the pipeline must not force every engine to change
at once, and must never let an unmeasured fact masquerade as a measured
zero.

Output collisions were the other trust gap: the existing `-1`/`-2`
numbering only prevented overwriting, it never gave the user a choice.
`doc2md.core.exporter.OutputPolicy` makes that choice explicit - `unique`
(the old default, unchanged), `fail`, `overwrite` (which still refuses the
one truly dangerous case, overwriting the source file itself), and
`converted-folder` (the new GUI default, since a dedicated subfolder cannot
collide with anything the user did not just convert). Every write in the
application - the main output, chunk parts, both JSON reports - now goes
through one atomic writer, so a failure partway through a write can no
longer leave a half-written file where a reader would find it.

Retry needed the GUI's worker to stop being all-or-nothing. Previously
"Convert" always meant "convert every queued file from scratch"; Retry
Failed/Warnings needed to re-run a *subset* of rows and land each result
back on the same row it came from, not a new one at the end. The fix was
smaller than it sounds: the worker's file list became `{original_row_index:
path}` instead of a plain list, so `file_finished` already carries the
right row index regardless of which subset is running. Building the two
test files for this actually surfaced two unrelated test-harness bugs
worth naming: a PyQt signal spy installed *after* the connection it was
meant to intercept never fires (Qt captures the callable at `.connect()`
time), and a "corrupted file" fixture that used an unsupported extension
never reached the converter at all - the GUI's own pre-filter rejected it
as Skipped before conversion, which produces a different status than
Error. Neither was a product bug; both were fixed in the tests.

The OCR Setup Assistant exists because "the package imported" and "OCR
actually works" are not the same fact, and every prior status message in
this codebase already knew that distinction for individual conversions
(the OCR-warning work from the previous release). `doc2md.core.
ocr_diagnostics` applies the same discipline to the up-front readiness
check: it does not report Ready because `pytesseract` imported, and it
does not report a RapidOCR backend as active unless `RapidOCR()` actually
constructed successfully - importing the package is necessary but not
sufficient, so `rapidocr_initializes` stays `None` ("not attempted") right
up until a real construction is tried.

A review of this round's own work before release found problems worth
recording, because each was a place where the tool would have said something
untrue. A document that converted but failed to save showed Error in the table
yet Success in the exported reports. A failure partway through a chunked
write left the main output behind while reporting that nothing was written.
A spreadsheet with a huge declared range reported a million rows. Table pages
in Thai PDFs took their prose from a different text extractor than the rest of
the document. Each is fixed and has a test.

The largest change is a subtraction: the output writer had grown a placeholder
and polling protocol to stay race-safe. A temp file plus a no-clobber rename
gives the same guarantee with no placeholder to leave behind after a crash, at
roughly half the code.

Dragging a file onto the window only worked on the small drop zone; any
other part of the window showed the no-drop cursor. The whole window accepts
drops now, and dropped folders are scanned off the UI thread.

## [1.1.0] - 2026-08-30

Refocused doc2md from "convert anything, including recordings" to "convert
documents, well".

The audio stack was the source of both problems the tool actually had. It was
responsible for essentially all of the download size - torch, CUDA and MKL
binaries, plus a separate GPU Pack installer - and for the failure mode that
was hardest to diagnose: when a model file or an ffmpeg binary was missing at
runtime, transcription produced an empty document rather than an error, so the
tool looked like it had worked. Removing it took the product back to what it is
used for, and made every remaining failure explicit.

The GUI was rewritten in PyQt6 rather than ported. The Tk implementation
received drag-and-drop payloads as a single brace-delimited string and had to
re-tokenize it; every available splitter applied escape processing, which ate
backslashes and mangled Thai filenames. Qt delivers `QUrl` objects, which
removes that entire class of bug rather than patching it again.

Table extraction was rebuilt around one shared module. Previously each engine
had its own table renderer, and each had a different subset of the same three
bugs: ragged rows emitting different pipe counts, unescaped pipes ending a cell
early, and multi-line cells breaking the row. Thai made all three worse, because
its combining vowel and tone marks are zero-width, so any attempt to align
columns by character count produced visibly crooked output.

Three findings came out of writing the tests and reading the tool's own output
rather than from reports. The sanitizer was flattening nested lists, because it
collapsed the leading indent along with internal double spaces. It was also
deleting every braced run in the document - the stripper meant for leftover CSS
matched any `{...}`, which quietly removed JSON snippets and Thai template
placeholders from ordinary prose; it now requires an actual `property: value;`
declaration. And bundle checksums could never match on Windows, because
`Path.write_text` converted LF to CRLF after the hash had already been taken.

The brace bug is worth noting for how it was found: it damaged this project's
own CHANGELOG when the repository's file-mirroring step ran the document back
through the converter. A tool that quietly eats its own release notes is the
same failure mode as one that quietly produces an empty transcript.

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

### In progress: transcription speed

Verified baseline: 27 minutes of real Thai meeting audio transcribes in 639s
(10.7 min) on an RTX 4060 Laptop with the `small` model - about 2.5x realtime.
GPU utilisation during the run held at 26-71%, so the card is not saturated.

Two levers exist in the installed faster-whisper 1.2.1 and are **not yet enabled**:

- `vad_filter` (currently `False`) - silence is transcribed like speech, and
 meeting recordings contain a lot of it.
- `BatchedInferencePipeline` - batches chunks per GPU pass, targeting the
 utilisation headroom above.

Both are being benchmarked against a 5-minute slice of the same real recording,
measuring wall time **and** transcript character count together, so a speedup
that silently drops content is not mistaken for a win. Nothing ships until those
numbers exist; defaults are unchanged in this release.

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
