# Changelog

## [1.4.10] (2026-10-09) - TABLE STRUCTURE ON SCANNED PAGES TOO

### Added

- **A table on a fully scanned page (no text layer at all - a print
  brochure/catalogue exported straight to PDF) now keeps its grid instead
  of flattening into running text, the same benefit 1.4.8 gave to
  mis-encoded-text-layer pages.** These are two different code paths
  (`_render_scanned_pdf` vs `_reread_corrupt_pages`) that shared the same
  gap: plain whole-page OCR with no concept of a table. Both now call the
  same table-aware OCR helper, so a spec-comparison table reads correctly
  regardless of which path a given PDF takes to get there.

## [1.4.9] (2026-10-09) - RELIABLE ROW-SELECTION HIGHLIGHT

### Fixed

- **The selected row in the FILES list could be hard to tell apart from the
  rest.** The highlight colour was set with the widget-level
  `selection-background-color` style property, which Qt applies to
  `QTreeWidget` inconsistently across native styles - it can read correctly
  in one rendering path and fail to paint in another. Replaced with
  explicit `QTreeWidget::item:selected` rules (Qt's documented, reliable
  way to style tree-row selection), covering both the focused and
  unfocused state explicitly, so clicking between converted files always
  shows clearly which one is currently selected.

## [1.4.8] (2026-10-06) - OCR KEEPS TABLE STRUCTURE ON CORRUPT PAGES

### Added

- **A table on a page re-read by OCR (mis-encoded text layer) now keeps its
  grid instead of flattening into one wall of running text.** A table's
  ruling lines are vector drawing, not text, so they survive a broken
  font's character map exactly as they would on a correctly-encoded page -
  pdfplumber's cell geometry is kept, and each cell is OCR'd from its own
  cropped region instead of being read from the font's garbage text. The
  table region is masked out of the page before the surrounding prose is
  OCR'd, so content is never read (and duplicated) twice. Any failure in
  this path - pdfplumber unavailable, no table found, a crop or mask
  operation raising - falls back to the plain whole-page OCR this always
  did; nothing about reading a corrupt page without a table changes.

## [1.4.7] (2026-10-06) - WORST-CASE TEXT-LAYER CORRUPTION NOW CAUGHT

### Fixed

- **A PDF text layer broken badly enough to lose every Thai character went
  undetected and was used as-is instead of falling back to OCR.** The
  corruption check required at least 50 real Thai letters to still be
  present before it would even look at the control-character count - on a
  real document (an Identity-H/Type0 embedded font with no usable ToUnicode
  map) one page extracted as 1,368 control characters and exactly 0 Thai
  letters, so the check bailed out early and that garbage went straight
  into the Markdown output. The control-character check now runs
  regardless of how much Thai survived - that's the more severe corruption
  case, not a reason to skip the check.

## [1.4.6] (2026-10-05) - BUSY PROGRESS BAR FOR SLOW FILES

### Changed

- **Progress bar no longer sits frozen at a stale percentage while a single
  slow file (a long OCR scan) converts.** It switches to an indeterminate
  "busy" animation the moment a file starts, and back to the real,
  file-level percentage the moment it finishes. True per-page progress
  inside one file isn't available yet - OCR runs in an isolated worker
  process that only reports back once, when the whole file is done; getting
  true page-level numbers would need a new progress channel across that
  process boundary.

## [1.4.5] (2026-10-04) - THREE BUGS FROM A DETAILED REVIEW

### Fixed

- **Clear Completed could delete the wrong row.** It removed rows by their
  position within the internal tracking list, but a skipped-folder
  explanation row (shown directly in the FILES list, never tracked
  internally) can sit between tracked rows and throw that position out of
  sync with the row's real position on screen. Confirmed with a repro: a
  Success file would survive as an orphaned, unremovable row while the
  skip-row explanation got deleted in its place. Now removes each row by
  its own identity, never by a position that could point somewhere else.
- **A real floating window could pop up when selecting a PDF or image.**
  The hidden thumbnail widget (kept internally since the UI redesign that
  removed it from view) had no parent widget, which in Qt means a real
  top-level window - `.show()` on it would display a small floating window
  next to the main one. The test suite never caught this because it always
  runs headless, where a shown top-level widget has no visible effect.
  Fixed by giving the widget a parent and moving it off-screen.
- **The same file queued twice from two different-but-equivalent paths.**
  Re-adding an already-queued file is supposed to be a no-op, but the check
  compared raw path strings instead of resolved ones, so two paths
  pointing at the same file (e.g. one with a redundant `.` segment) weren't
  recognized as duplicates.

## [1.4.4] (2026-10-04) - FILES PANEL IS THE DROP TARGET

### Changed

- **Removed the standalone "Drag & drop documents here" box.** The FILES
  panel now does both jobs: empty, it shows the drag-and-drop/click-to-browse
  invitation; the moment there is a file (or even just a skipped-folder
  explanation row), it swaps to the file list. One panel instead of two
  stacked boxes competing for vertical space.

## [1.4.3] (2026-10-04) - ONE-LINE QUALITY SUMMARY

### Changed

- **Merged the quality detail line and the compare-metadata line into one.**
  "Source: ... · Output: ... · Sheets: 1 · Rows: 141/141 · Warning: none"
  sat on its own row directly below "1 sheet(s) · rows 141/141", repeating
  the sheet/row counts that were already shown next to the Success badge.
  "Output: unknown" was dead text besides — nothing has populated an output
  path since 1.4.0 removed auto-save. Now there is one line next to the
  badge: `source 6.2 KB · 1 sheet(s) · rows 141/141`. Dropping the row
  moves the preview box's top edge up to sit right under the badge row
  instead of two rows down.

## [1.4.2] (2026-10-04) - STALE PREVIEW, FLUSH PANEL EDGES

### Fixed

- **Preview stayed blank after conversion finished, if the row was already
  selected.** Selecting a file while it was still Queued/Converting (or it
  being the already-current row) meant `_on_file_finished` only refreshed
  the quality badge, not the preview text, once conversion completed -
  leaving a real result sitting in memory with nothing shown for it. Fixed
  by running the full row-selected refresh (preview included) whenever the
  just-finished row is the one on screen.
- **Markdown Preview's bottom edge didn't line up with the file list's.**
  The compare-metadata line sat *below* the preview box, so the box itself
  stopped short of the panel's bottom with dead space underneath. Moved
  that line above the preview box instead, so the preview - like the file
  list - is the last (and therefore full-height) widget in its column.

## [1.4.1] (2026-10-04) - LAYOUT CLEANUP

### Changed

- **Files and Preview sit side by side now**, not stacked. The Markdown
  preview was cramped under the file list; a horizontal split gives both
  the full window height, with extra width weighted toward the preview.
- **Removed "Add files" button.** The drop zone has accepted a click to
  browse for files since it was built; the separate button was a duplicate
  entry point.
- **Removed "Send to Sandbox" button** from the main window to cut toolbar
  clutter. The underlying bridge feature (`send_to_bridge`) is unchanged and
  still reachable from the CLI.
- **Removed "Open Output" button.** It has had nothing to open since 1.4.0
  stopped auto-saving to disk — it was dead ever since.

## [1.4.0] (2026-10-04) - EXPORT FORMATS, NO AUTO-SAVE

### Changed

- **Multi-format export.** The "Export…" button now opens a Save dialog with
  format choice: Markdown (`.md`), Plain text (`.txt`), or JSON quality
  report (`.json`). All converted results are combined into the chosen file.
- **No auto-save to disk.** Converted documents are held in memory only;
  nothing is written to disk until the user clicks "Export…". The output
  folder setting now sets the default directory for the export dialog.
- **Settings card simplified.** Removed: "Save next to source file" checkbox,
  "Output Policy" dropdown, "Copy result to clipboard" checkbox. Destination
  previews (the `→ path/to/output.md` text on queued rows) are also removed.

## [1.3.5] (2026-10-02) - ข/ย ON SCANS

### Fixed

- **A regression from 1.3.2 on grey scans.** The pastel-header fix whitened every
  light pixel on a light page. On a grey scan that thins the strokes and makes
  Tesseract read ข as ย: on three pages of a company certificate the wrong
  readings ("ยอง", "ยาย", "ยนส่ง") went from 8 (unprocessed) to 11. The fix now
  whitens only pixels that are both light *and coloured*, so a pastel bar is
  still removed (the spec-table header rows are all still found) and grey scans
  keep every stroke.
- **Cleaner input for scans.** Light pages get a contrast stretch, and large pages
  (2,500 px tall and up, i.e. a 300 DPI page) a 3x3 median filter against scanner
  speckle. On the certificate the wrong readings fell from 11 to 4 and the right
  ones rose from 14 to 20 (8/17 unprocessed). Small text is not median-filtered:
  on a 200 DPI page it erased the table header row.

### Tried and not adopted

- **`tessdata_best`** (the higher-accuracy Thai and English models, 23 MB against
  5 MB). Measured on the same three tests (certificate ข/ย, brochure captions,
  poster phrases) it was identical or marginally lower (certificate 11 vs 11
  wrong; captions 0.936 vs 0.941; poster 0.755 vs 0.765) and took about twice
  as long. The installer keeps downloading the fast models.

## [1.3.4] (2026-10-02) - UNREADABLE TEXT LAYERS, SCAN RESOLUTION

Found by running a batch of real documents: a price quote, a flood notice, a
company certificate and two posters.

### Fixed

- **A text layer that is mis-encoded Thai is detected and read by OCR instead.**
  A flood notice (a Ghostscript rewrite) extracted as "น้ำท!วมป5 2569": tone
  marks and vowels had become `!`, `?`, digits and control characters, which no
  rule can repair. A page with Thai letters sandwiching symbols, or with stray
  control characters, is now treated as unreadable text and recognised from an
  image of the page; the result says so. If OCR is unavailable (or switched off)
  the text is kept and the result is marked Warning rather than passed off as
  clean. Across 345 Thai-heavy pages of real PDFs, 16 (4.6%) were of this kind;
  the ones inspected were genuinely corrupt.
- **The sara aa repair covers a font's bold face too.** `Angsana New,Bold` and
  `Angsana New` share one bad character map, but the pattern had been found
  only in the bold face, so regular text was left broken. Faces are now one
  family.
- **Scans are read at 300 DPI, not 200.** On three pages of a company
  certificate, ข read as ย ("ของ" as "ยอง", "ขาย" as "ยาย") 60% of the time at
  200 DPI, 44% at 300 and 40% at 400. 300 costs about 15% more time per page.
- **White text on dark bars** (table headers, buttons on a poster) is read
  through an extra inverted pass in the image reader; "Leader G Plus" in a
  banner on a car-price poster is now read.

### Known limits

- ข/ย confusion on scans is reduced, not gone; the higher-accuracy Thai model
  (`tessdata_best`) is the next lever and is not downloaded by the app.
- Headers on dark gradient buttons ("ดาวน์", "จำนวนงวดผ่อน") are still missed.
- Chinese text is not read (no Chinese language data is installed).

## [1.3.3] (2026-10-02) - BROKEN THAI IN EXCEL PDFS, POSTERS

### Fixed

- **Thai in PDFs exported from Excel with AngsanaUPC was garbled** even though
  the PDF has a text layer: every sara aa came out as sara am ("ค่าขนส่ง" as
  "ค่ำขนส่ง", "บางโฉลง" as "บำงโฉลง"), a real sara am as a space plus sara am
  ("ต ำบล"), and table numbers had spaces in them ("1 0,400.00"). The font maps
  the sara aa glyph to sara am and draws a real sara am as a zero-width space
  plus that glyph. The pattern is decidable from the characters, so a font is
  repaired only when the pattern is actually seen in it; correctly encoded PDFs
  are untouched. Table cells are now filled from the PDF's own text clipped to
  the cell, not from pdfminer's, which also removes the spaces inside words and
  numbers, and fragments on one visual row (a label and a right-aligned note)
  stay on one line so neighbouring cells line up. On the sample price quote
  every Thai word and every figure now matches the page.
- **Posters and photographs read more of their text.** Text scattered over a
  picture is read differently by each Tesseract page mode, and no single setting
  read more than about 70% of the phrases on a product poster. Images are now
  read in three ways (auto layout, sparse text, and an enlarged contrast-
  stretched copy), the readings pooled, and the more confident one kept wherever
  two cover the same region; lines that are mostly symbols are dropped. On that
  poster the phrases matched rose from 64% to 77%.

### Known limits

- Large decorative display type (the poster's title) and wide-spaced headings on
  photographs are still often missed.
- A table cell's vertical alignment is by text line, so a cell with a heading
  line above its items is one line longer than its neighbours.

## [1.3.2] (2026-10-02) - TABLE HEADER ROWS ON SCANNED PAGES

### Fixed

- **The row that names the columns is no longer lost.** On the same brochure,
  the specification table's header row ("Model | 2.8 Legender 4WD | 2.8
  Legender | 2.4 Legender 4WD | 2.4 Legender") was missing from the OCR, so no
  value could be attributed to a model. Tesseract's layout analysis treats a
  pastel header bar as a picture. Pale fills on light pages are now whitened
  before recognition (pixels at or above 175/255 become white; text is darker
  and untouched; dark pages are left alone). All four panels now start with
  their header row.

### Known limits

- Stylised display text is still missed: the large "150 PS / 400 NM / 204 PS /
  500 NM" figures on the engine page were not recognised (the same numbers are
  in the specification table, which is read correctly). White wide-spaced
  headings on photographs come out garbled.
- Check marks in feature matrices are read as dots, so which model has which
  feature cannot be recovered from the text.

## [1.3.1] (2026-10-02) - OCR ON BROCHURES AND TABLES

Found by converting a real 8-page Thai car brochure, scanned, with the OCR
installed by 1.3.0 and reading the result against the pages.

### Fixed

- **Side-by-side panels are read one at a time.** A specification table laid
  out in four panels came out with each line mixing fragments of four
  different rows. Pages are now cut at blank vertical gutters (found from edge
  density, so dark pages work too) and each panel is read on its own, left to
  right: on that brochure every spec row (`ความจุกระบอกสูบ ซีซี 2,755 2,393`) is
  one clean line.
- **Noise from pictures is dropped.** Photographs and logos produced lines of
  stray symbols. Lines Tesseract itself is unsure of (mean confidence under 40,
  60 for lines of 3 characters or fewer) are removed. Tesseract's own spacing is
  kept; the word data is used only to decide which lines to drop.
- **Tests no longer depend on, or change, an OCR install on the dev machine**,
  including inside the worker processes.

### Known limits

- Thai OCR is not perfect: on that brochure, caption text matched a hand-read
  transcription about 92-94% (typical slips: ข/ห and tone marks). Table cell
  borders are not recovered on scanned pages - rows come out as lines of text.
  Bullet dots in tables are read as stray characters.
- Reading the panels separately makes a scanned page take about 70% longer.

## [1.3.0] (2026-10-02) - LEGACY OFFICE FILES, OCR INSTALL, CANCEL, TOKEN COUNTS

### Added

- **Legacy `.xls`, `.doc` and `.ppt`.** Thai offices still hold thousands of
  them, and they were rejected outright.
  - `.xls` is read with xlrd and goes through the same pipeline as `.xlsx`:
    dates, percentages, merged headers, hidden-sheet handling.
  - `.doc` (Word 97-2003) is read straight from the file's piece table and
    paragraph records, so tables keep their cells (empty ones included),
    headings and list items come through, and field codes are dropped. Not
    recovered: bold/italic, headers/footers, footnotes, text boxes. A `.doc`
    that is really RTF (or a `.docx`/HTML renamed) is detected and converted as
    what it is. A `.doc` holding only a scanned picture says so instead of
    returning nothing.
  - `.ppt` follows PowerPoint's own edit chain, so an incrementally saved deck
    shows the current slides, not stale copies. Titles and text come through;
    notes, table layout, bullet levels and pictures do not.
  Every `.doc`/`.ppt` result carries a one-line note saying what was not
  recovered. Tried against 220 real files (90 `.doc`, 90 `.xls`, 40 `.ppt`):
  all `.xls` and `.ppt` converted; 79 of 90 `.doc` converted, the 11 others were
  Word files that contain only a scanned picture (reported as such).
- **Install OCR from the app.** The OCR Diagnostics dialog has an "Install OCR
  (Thai + English)" button: it installs Tesseract with winget (the manifest
  pins the installer's hash) and downloads the Thai and English language data
  into a per-user folder, then asks Tesseract itself which languages it can
  load. Tesseract is also found in its default install folder when it is not on
  PATH. Windows asks for administrator approval for the installer.
- **Cancel stops a conversion in flight.** A large scanned PDF no longer has to
  finish before Cancel takes effect: the worker process is terminated, and
  spreadsheet scans check for cancellation as they read.

### Changed

- **Token counts are measured, not `chars / 4`.** On 2,501 segments (1.34M
  tokens) of real converted documents, `chars / 4` was off by 43% on average
  and undercounted Thai-heavy text about threefold (Thai runs near one token
  per character). The built-in estimate now weights characters by class; on
  documents held out from the fitting it is off by 5.7% on average. It is
  calibrated to OpenAI's `cl100k_base`; Claude's tokenizer is not public, so the
  figure is an estimate of the same order, not a count. tiktoken is still used
  when installed. Chunk sizes follow the new estimate, so Thai documents split
  into more, smaller chunks than before.

### Fixed

- HTML without a `<title>` (including Excel's HTML exports saved as `.xls`)
  crashed the HTML engine.

### Dependencies

- Added `xlrd` and `olefile`.

## [1.2.2] (2026-10-01) - MERGED CELLS IN SPREADSHEETS

### Fixed

- **Merged header cells are unfolded.** A merged range taller than one row near
  the top of a sheet marks a multi-row header. Rows above it become title
  lines; the header rows fold into one row whose column names join the labels
  top-down (`Period / Internal Audit 10-31 August 2026 / Mon / 10`), so a
  calendar or comparison table no longer comes out as `col1..colN` with its
  real headers left in the data. Vertical merges below the header repeat their
  value on every row they cover.
- Merges are read from the sheet XML directly, so large sheets still stream
  and nothing is loaded whole into memory. If the merge data cannot be read the
  sheet converts as in 1.2.1.

### Known limits

- A merge that is shorter than the columns it visibly labels (a source quirk)
  leaves the extra column without that label; horizontal merges in data rows
  are not repeated.

## [1.2.1] (2026-10-01) - SPREADSHEET OUTPUT FIXES

Found by converting a real audit workbook (24 sheets, 21 of them hidden
archives) and reading the result as an AI would.

### Fixed

- **Title rows no longer become the header.** A sheet opening with a report
  name (one value, usually a merged cell) had that name used as the table
  header, with the real header pushed into the data and columns named
  `col2..colN`. Leading single-value rows (up to 5) are now text above the
  table when a header row of 3 or more values follows.
- **Hidden worksheets are skipped by default**, with a note naming them, so an
  old archive no longer buries the current data (that workbook went from
  148,000 to 34,000 characters). `--include-hidden` on the CLI and the
  "Hidden sheets" checkbox in the GUI convert them.
- **Cell values read as they do in Excel:** midnight datetimes are plain
  dates (`2026-08-17`, not `2026-08-17 00:00:00`), percentage cells keep their
  percent (`-17%`, not `-0.1724137931034483`), floats lose binary noise, and
  padded text is trimmed.
- Sheet names with stray spaces are trimmed; sheets declared out to column
  XFC are read at most 1,024 columns wide.

### Known limits

- Merged header cells and multi-row headers are not unfolded (openpyxl's
  read-only mode does not expose merges); calendar-style sheets still convert
  to a wide grid.

## [1.2.0] (2026-10-01) - PRODUCT HARDENING & UX IMPROVEMENT

Trust and transparency pass on top of 1.1.0: every conversion now reports
what it actually did, output can no longer silently collide with an
existing file, a failed batch can be retried without redoing the whole run,
OCR readiness is a real check instead of an assumption, and the review
panel shows enough to judge a result without opening the output file.

### Added

- **Structured quality report** (`doc2md.core.quality`). Every conversion now
 carries a `QualityMetrics` object - pages read/failed, tables detected,
 sheets/rows detected vs. exported, truncation, and OCR backend/language/
 outcome - alongside the Markdown. A field is `null` when an engine has not
 been migrated to report it, never a guessed `0`. PDF, Excel/CSV and OCR
 engines populate real numbers; DOCX/PPTX/HTML/EML/JSON/code/text engines
 report `null` metrics and are otherwise unaffected.
 - CLI: `--report <path.json>` writes one JSON object per document
 (status, source/output paths, engine, duration, token estimate, plus the
 metrics above), written atomically. A report write failure is a hard
 error (non-zero exit) and never mixes into `--stdout`.
 - GUI: a Quality Summary strip above the preview shows a colour-coded
 Success/Warning/Error badge plus the measured facts for the selected
 file, and an **Export Report** button writes the same JSON for the whole
 batch.
- **Safe output policy** (`doc2md.core.exporter.OutputPolicy`), one resolver
 shared by the CLI, the GUI and chunked output:
 - `unique` - never overwrites; appends `-1`, `-2`, ... (the GUI's safe
 default is `converted-folder`; the CLI default stays `overwrite`, as in
 1.1.0, so re-running refreshes `<name>.md` - except that a `.md` source is
 numbered rather than overwritten).
 - `fail` - refuses to write if the destination already exists.
 - `overwrite` - writes over an existing file, but **never** over the
 source file itself, even when the destination path would coincide with
 it (e.g. converting a `.md` file to `.md` in place).
 - `converted-folder` - writes into a `Converted` subfolder, which by
 construction cannot collide with a document the user did not just
 convert. This is the GUI's default.
 Every write (main output, chunk parts, the quality/error report) now goes
 through one atomic writer (`atomic_write_text` / `write_report_atomic`):
 content is written to a temp file next to the destination and moved into
 place with `os.replace`, so a failure mid-write never leaves a partial
 file - the destination is either the old content or the complete new
 content, nothing in between.
 - CLI: `--output-policy unique|fail|overwrite|converted-folder`.
 - GUI: an Output Policy dropdown (remembered across restarts via
 `QSettings`), a live destination preview per queued row before Convert
 is pressed, and a status-bar note when the output folder is nested
 inside a folder being converted.
- **Retry and batch recovery** (GUI). **Retry Failed** and **Retry
 Warnings** re-run only the matching rows and update them in place - a
 retry never adds a duplicate row, and a prior round's result for a
 retried row is discarded before the retry starts, so it can never reach
 Copy Markdown / Send to Sandbox / Export Report if the retry fails again.
 **Clear Completed** removes clean Success rows only, leaving Warning and
 Error rows in place so they stay retryable. **Export Error Report** writes
 a JSON quality report scoped to the rows currently showing Error.
- **OCR Setup Assistant** (`doc2md.core.ocr_diagnostics`, GUI **OCR
 Diagnostics…** dialog). Every fact is a real, live check - a package
 importing successfully is never reported as "Ready": the Tesseract binary
 must actually be found on PATH, and RapidOCR must actually construct its
 engine. The dialog reports, in Thai: "พร้อมอ่านภาษาไทยและอังกฤษ" (Tesseract
 found with both `tha` and `eng` language data), "อ่านได้เฉพาะภาษาอังกฤษ"
 (Tesseract found, but no Thai language data), or "ยังไม่มี OCR backend" (no
 working backend at all) - plus which backend the program will actually
 use, the real installed Tesseract language list, and a Refresh / Copy
 Diagnostics pair.
- **Conversion presets** (`doc2md.core.presets`): Balanced AI, High
 Fidelity, Fast Text, and Thai Scanned Document, each a fixed OCR
 language/resolution/table-extraction bundle. Selecting one applies its
 values to the GUI's existing controls; editing any of those controls by
 hand switches the preset selector to Custom automatically.
- **Review experience** additions to the GUI preview pane:
 - A Warning banner above the preview when the selected row is a Warning
 (OCR unavailable/disabled/found nothing) - separate from, and more
 visible than, the quality badge.
 - **Open Original** and **Open Output** buttons (via the OS's default
 application) and a per-row **Copy Markdown** that copies only the
 selected file, distinct from the batch-wide Copy Markdown.
 - **Compare Metadata**: source size vs. output size, page/sheet count,
 extracted rows/tables, and the warning (if any), for the selected file.
 - A first-page-only thumbnail for PDF (rendered with pymupdf, already a
 dependency) and images (Qt's own image loader) - no new dependency
 added. Never shown as a stand-in for the rest of the document; hidden
 outright if it cannot be generated, rather than showing a placeholder.
 - A folder scan that finds only `.md` files (or a mix that includes some)
 now says so explicitly - "folder contains only Markdown file(s) - N
 skipped" / "N Markdown file(s) in this folder were skipped" - instead of
 the misleading "folder contains no files" for the all-Markdown case, or
 silence for the mixed case.

### Fixed

- **Drag & drop onto the window.** Only the small drop zone accepted files;
 dropping on the file list, the preview or anywhere else showed the no-drop
 cursor. The whole window accepts drops now.
- **GUI reports after a write failure.** A document converted but not saved
 (unwritable folder, full disk) showed Error in the table yet appeared as
 Success in the quality report and error report. The stored result is now
 flipped to failed with the write error.
- **Output writing simplified.** `doc2md.core.exporter` no longer reserves a
 destination with a placeholder file and a polling/identity protocol (about
 700 lines). Content is written to a hidden temp file and published with a
 no-clobber rename (`os.rename` on Windows, `os.link` on POSIX), so unique and
 fail stay race-safe, and a crash can leave only a hidden `.tmp` file, never
 a token-only file at the real name. A failure while writing any chunk now
 removes the main output and earlier chunks.
- **Bridge schema 1.1.** The HTTP body's `contents` map is keyed by the
 manifest `file` name; the schema version is bumped accordingly, and
 `to_manifest` rejects a dict for `filenames` with a clear error.
- **XLSX/CSV row counting.** Trailing blank rows are no longer counted, and the
 walk stops after 1000 consecutive blank rows (reported as inexact) instead
 of iterating to row 1,048,576.
- **Dropping a large folder** is scanned on a background thread (no frozen
 window) and no longer does a quadratic filter.
- **Table pages in Thai PDFs** keep PyMuPDF's text for the non-table area
 (words outside the table boxes) instead of switching to pdfplumber's
 glyph-by-glyph reconstruction.
- **`tables_detected`** is `null`, not `0`, when pdfplumber is not installed.
- **OCR backend choice** uses Tesseract only when both the binary and
 pytesseract are present, otherwise falls through to RapidOCR, matching the
 setup assistant.

### Notes

- No Office-document renderer was added this round (PDF/DOCX/XLSX/PPTX are
 still reviewed as their converted Markdown, plus the new PDF/image
 thumbnail) - scope explicitly deferred, tracked as a roadmap item rather
 than attempted partially.
- Known limitations carried over from 1.1.0, unchanged: PDF table
 extraction requires `pdfplumber`; OCR requires either the Tesseract binary
 on PATH (with the `tha` language pack for Thai) or `rapidocr-onnxruntime`
 installed separately - neither is bundled, and this release does not
 install them automatically. The OCR Setup Assistant surfaces which of
 these is missing instead of letting a scan silently produce metadata-only
 output.

## [1.1.0] (2026-08-30) - CLEAN DOCUMENT CONVERTER

Breaking release. doc2md is now a document converter only; audio and video
transcription has been removed in full.

### Removed
- **Audio/video transcription.** `doc2md/engine/audio_engine.py`, the GPU Pack
 build (`build_gpu_pack.py`, `setup_gpu_pack.iss`) and the `FileKind.AUDIO` /
 `FileKind.VIDEO` routes are gone, along with the dependencies that made the
 installer enormous: faster-whisper, ctranslate2, torch, torchaudio,
 ffmpeg-python and imageio-ffmpeg. These accounted for roughly 2 GB of CUDA and
 MKL binaries, the separate GPU Pack installer, and the long class of silent
 failures where a model or an ffmpeg binary was missing at runtime and the
 conversion produced an empty file instead of an error.
- **CustomTkinter/TkinterDnD GUI.** Replaced, not ported - see below.

### Added
- **PyQt6 interface.** Dark themed, inline SVG icons, multi-file and whole-folder
 drag & drop, a per-file status table (Queued / Converting / Success / Skipped /
 Error) with the reason shown in the row, a batch progress bar, a Markdown
 preview pane, a Copy Markdown button and a Send to Sandbox button.
 Conversion runs on a `QThread` and communicates through signals, so no widget is
 ever touched from a worker.
- **PDF table extraction.** pdfplumber recovers ruled tables page by page and
 they are emitted as real Markdown tables. Disable with `--no-tables`.
- **Automatic text-vs-scanned PDF routing.** A document whose text layer yields
 almost nothing is rasterized and sent to OCR; everything else takes the fast
 PyMuPDF text path. No switch to set, and a scan can no longer convert to an
 empty document without saying why.
- **Thai OCR by default.** `tha+eng` is the default language for scanned PDFs and
 images (`--ocr-lang` to change it). If the Thai model is not installed the run
 falls back to English and says so in the output instead of failing.
- **Shared Markdown table builder** (`doc2md.core.tables`). One implementation for
 PDF, DOCX, XLSX and PPTX: ragged rows are padded to a single width, pipes,
 backslashes and control characters are escaped, and multi-line cells become
 `<br>` so they stay in their column.
- **Integration bridge** (`doc2md.core.bridge`) and a `doc2md bridge` command.
 Writes a bundle of `.md` files plus a `manifest.json` (schema, producer,
 per-document SHA-256, token counts) into a folder the Mediplex AI Sandbox
 watches; the manifest is written last so a watcher never sees a half-written
 bundle. An opt-in HTTP transport is available for an explicit endpoint.
- **`requirements.txt` / `requirements-dev.txt`**, which the project never had.
- Test suites for the table builder, Thai documents end to end, the bridge, and
 the PyQt6 window.

### Fixed
- **Nested lists were flattened.** The output sanitizer collapsed runs of two or
 more spaces anywhere in a line, including the leading indent that makes a
 sub-bullet a sub-bullet. Leading whitespace is now preserved.
- **Table rows were treated as prose.** The sanitizer's duplicate-line pass
 deleted a table row that legitimately repeated the row above it, and its
 CSS-residue pass ate any cell containing braces. Table blocks are now
 excluded from both.
- **The sanitizer deleted braces from prose.** The CSS-residue stripper matched
 any braced run at all, so a JSON snippet, set notation, or a Thai template
 placeholder was silently removed from the output. It now only matches a block
 containing at least one `property: value;` declaration.
- **Bundle hashes never matched on Windows.** Markdown was written with
 `Path.write_text`, whose default newline handling converts LF to CRLF on
 Windows, so the file on disk did not match the SHA-256 recorded in the
 manifest. All Markdown output is now written with LF explicitly.
- **Emphasis markers had stray whitespace.** Word splits a styled phrase across
 several runs; wrapping each run individually produced `** bold **`, which
 renders as literal asterisks. Adjacent runs with the same formatting are now
 merged before the markers are added.
- **Drag & drop path handling.** Qt hands over `QUrl` objects, so there is no
 re-tokenizing of a flat string and no escape processing - Thai names, spaces,
 `#`, `&`, `%` and backslashes all survive intact.
- **A dropped recording now explains itself.** Audio and video extensions are
 still detected and produce "transcription was removed in 1.1.0" rather than the
 generic "unrecognized file type".
- Excel sheets no longer emit phantom `col3..col8` headers for the empty columns
 Excel reports in its used range.
- PPTX shapes nested inside groups are no longer dropped.
- One unreadable PDF page no longer fails the whole document; only a document
 whose every page is unreadable is an error.

### Changed
- Default per-file timeout stays 60s, with 600s for the OCR path.
- `build_exe.py` excludes the scientific and audio stacks plus the unused Qt
 modules, and accepts `--onedir`.
- **The installer now ships the folder build.** Measured with `--version`, five
 runs each on a warm cache: the folder build reaches its first window in
 ~0.15 s, the single-file build in ~1.7 s - the whole difference is the
 single-file archive being unpacked into a temp directory on every launch. The
 single-file executable is still published as a portable download (85 MB); the
 folder build is 184 MB on disk. For comparison, 1.0.27 shipped a base
 executable plus a separate 758 MB GPU Pack.
- `build.py` now produces the complete release set: both executables and the
 installer.
- The build now fails up front if a runtime dependency is missing, rather than
 producing an executable that crashes on first use.

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
