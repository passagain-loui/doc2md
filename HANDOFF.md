# Handoff - doc2md v1.5.6

Written 2026-10-04, updated 2026-10-21. Read this first, then README.md (what
the tool does) and CLAUDE.md (the release pipeline rules).

> **CI note (2026-10-19):** the 1.5.4 release commit `5b55aeb` failed GitHub CI
> in one test, `test_real_tesseract_reads_the_thai_image` ("no readable text").
> Real cause: that test had never run on CI. Before 1.5.4 its `shutil.which`
> skip always fired there (choco does not install Tesseract into the folder the
> workflow adds to PATH). The new `real_tesseract` fixture finds Tesseract the
> way the app does, so the test ran for the first time, on a choco Tesseract
> with English data only. Two guesses (`4f87207`, `a2b8b32`) were wrong. The
> fix: the fixture lifts the whole app-style lookup (install folders and
> doc2md's per-user tessdata, where this machine keeps Thai) and skips when
> Tesseract has no `tha`. Locally the test runs and passes; with no Thai data
> it skips. Gate passed (EXIT_CODE 0), installer rebuilt.

## 1. State right now

| Item | Value |
| --- | --- |
| Version | 1.5.6 |
| Last release commit | `f51a2e5` (v1.5.6; CI green on 3.11-3.13, run 39620872708) |
| Branch | `main` |
| Remote | `origin` = https://github.com/passagain-loui/doc2md.git - check `git status -sb` for unpushed commits; GitHub CI (Python 3.11-3.13) green since commit `8d9adde` |
| Gate | `tools/verify.ps1` passed (EXIT_CODE 0) for 1.5.6 on 2026-10-21; 2 expected skips (symlink, RapidOCR not installed) - the real-Tesseract test now runs |
| Installer | built 2026-10-21 from the gated 1.5.6 tree: `dist/doc2md_Setup_v1.5.6.exe` (69 MB), `dist/doc2md.exe` (95 MB), `dist/doc2md/` - git-ignored, rebuild with `python build.py` on another machine |
| Tesseract | **installed and working on this machine** (checked 2026-10-17): v5.4.0 at `C:/Program Files/Tesseract-OCR/tesseract.exe`, languages `eng` + `tha`. It is not on PATH, but `find_tesseract()` locates it in the standard install folder, so the app uses it. A real Thai test image and scanned PDF converted correctly apart from a lost tone mark (นี้ read as นี). The gate's one 'Tesseract not installed' skip (`tests/test_thai_documents.py`) checks `shutil.which("tesseract")`, i.e. PATH only, so it skips here; add the folder to PATH if you want that real-OCR test to run |

### What changed in 1.5.6

Scan OCR fixes in `doc2md/core/ocr_text.py` (no engine changes). New tests:
`tests/test_ocr_rescue.py` (71) and `tests/test_ocr_thai_reread.py` (40), both
synthetic only. The OCR test set is 329 passing.

- Ink-limited autocontrast: `prepare_for_ocr` stretches only when the 1% dark point
  would fall on paper (gray >= 160). Constants `AUTOCONTRAST_INK_SHARE = 0.1` and
  `AUTOCONTRAST_CUTOFF = 1.0`; switch `LIMIT_CONTRAST`. Unrestricted, it damaged
  "TOPSERV" and "ของ" on other samples.
- Unread-run rescue: `_unread_runs` finds line-sized ink bands that no read word
  covers and whose ink share is text-like (`RESCUE_INK = (0.09, 0.62)`);
  `_reread_run` re-reads each with ruling lines removed (`--psm 6`);
  `_splice_rescued` places the results by vertical position. A rescued row must
  hold a real word (Thai 3+ letters, Latin 4+), an ASCII number, a Latin code, or a
  Thai phrase with a number. It replaces a shaky existing line only if it covers at
  least 60% of that line's width. Caps: `MAX_RUN_RESCUES`, `RESCUE_MAX_MISSES`.
  Switch `RESCUE_UNREAD`.
- Thai re-read of short Latin tokens: `_reread_thai_words`, switch `THAI_REREAD`.
  A lowercase Latin token of 2-3 letters (confidence < 90) next to a number is
  re-read Thai-only, and accepted when a Thai word comes back at confidence >= 80.
  Uppercase codes are never touched.
- Dropped after testing: an edge-shadow trim for `find_vertical_gutters`. It changed
  band splitting on an approved brochure and moved a block of text to the top of a
  page.
- Method: each factor was measured alone on all 9 samples (ablation); only the
  clean ones were kept.
- Results are in section 7, known limits in section 8, and approvals pending in
  section 9.
- Not done for 1.5.6: the version bump (`pyproject.toml` and `doc2md/__init__.py`
  still say 1.5.5), the gate, and the release build.

### What changed in 1.5.5

Dingbat symbols, OCR table labels and symbols, logo rows, and the legacy Office
readers (`doc2md/core/pdf_text.py`, `doc2md/engine/pdf_engine.py`,
`doc2md/core/ocr_text.py`, `doc2md/engine/doc_engine.py`, `doc2md/engine/ppt_engine.py`):

- Dingbat symbols in text-layer PDFs: `map_dingbat` in `doc2md/core/pdf_text.py`
  maps Wingdings (0xFC ✓, 0xFB ✗, 0xFE ☑, 0xFD ☒, 0xA8 ☐, 0x6C ●), Wingdings 2
  (0x52 ☑, 0x54 ☒), Webdings (0xE3 🛏) and ZapfDingbats (0x33 ✓, 0x34 ✔, 0x35 ✕,
  0x36 ✖, 0x37 ✗, 0x38 ✘). It applies only when the character's own font is a
  dingbat font. Unverified codes are left out, and only pages that use a dingbat
  font are read character by character. EU2043 meal table: 31 invisible
  characters before; now ✓/✗, 🛏 and ☑/☒.
- Drawn ✓/✗ in OCR'd table cells: `_symbol_in_cell` also recognises a single ink
  stroke shaped like ✓ or ✗, sized in PDF points. Shapes that must not match: V,
  /, \, +, L, and x in "4 x 4". A lone "X"/"x" in a cell reads as ✗. Synthetic
  images only.
- Short table labels: `_reread_short_cell` re-reads a short cell alone first and
  keeps the result if it has Thai. If that is empty or Latin-only, the cell is
  cropped to ink, upscaled to about 45 px high (at most 4x), read with `--psm 7`
  and Thai only, and accepted with Thai letters and mean confidence 50 or more.
  Constants `TABLE_SHORT_REREAD_*`. `_invert_dark_bands` inverts a section-bar band
  inside a tall light cell where pdfplumber merged a heading bar; `_join_label_words`
  fixes "มม ." spacing. Fortuner p1 table 1: 0.941 -> 0.945 (0.940 -> 0.944 with
  symbols kept); rows below 0.8: 8 -> 6. "สี" fixed; "อัตโนมัติ" now reads
  "อฮิตโนมัติ" (see section 8).
- Logo noise rows: `_is_logo_noise` in `doc2md/core/ocr_text.py` drops a row only
  when all hold: mean confidence < 75; at least 2 tokens; no word (3+ letters in
  one script), number or list marker (ก., a), (ข)); at least 60% of tokens stray
  (symbols, lone letters that are not Thai one-letter words, unknown 2-letter
  Latin). Protected: ที่ นี้ ดี ปี ผู้ ก็ ณ ๆ and page numbers like "- 2 -". Time
  change under 1%.
- Legacy `.doc` bold/italic: read from the CHPX sprms 0x0835, 0x0836 and 0x4A30
  (`PlcBteChpx`) and the style sheet. Toggles 0x80/0x81 are folded through the
  paragraph style, character style and direct run. Emitted at word level, never
  inside a Thai syllable, and not in headings or the table header row. Malformed
  structures fall back to plain text. An RTF saved as `.doc` gets `RTF_NOTE` (no
  emphasis).
- Legacy `.ppt` speaker notes: `SlideAtom.notesIdRef` -> notes list
  (`SlideListWithText` instance 2) -> persist directory -> Notes container body,
  through the current edit chain only. Output: `> Speaker notes: …` under the slide.
- Tests: new `tests/test_legacy_emphasis_notes.py` (57), `tests/test_ocr_logo_noise.py`
  (93) and `tests/test_pdf_dingbats.py`; extended `tests/test_table_ocr.py`. Real
  Word/PowerPoint fixtures (made-up text, author metadata scrubbed) are in
  `tests/fixtures/`, with generators in `tests/fixtures/make_legacy_fixtures/`.
  Full suite: 1410 passed, 2 skipped.
- Regression: all 8 approved samples re-run with `tools/regress.py`; none REGRESSED.
  Changed on purpose: Fortuner, QP 7, camry, EU2043. Unchanged: mu-X, QMEL, quote,
  guideline. The user approved those four; they were re-approved from run
  `.runs\20261019-203414` on 2026-10-19, so all 8 references hold 1.5.5 output.

### What changed in 1.5.4

Mis-encoded Thai marks, table symbols and two OCR fixes (`doc2md/core/pdf_text.py`,
`doc2md/engine/pdf_engine.py`, `doc2md/core/ocr_text.py`, `doc2md/core/review.py`):

- Thai marks mis-encoded in a text layer are repaired, not re-read. Detection
  (`has_latin_mojibake`, `has_lost_marks` in `doc2md/core/pdf_text.py`) looks for
  Latin-1 and Latin Extended letters U+00C0-U+024F (except × and ÷) attached to
  Thai letters, and PUA U+F700-F8FF. A page is flagged at 3 or more hits and at
  least 1 per 500 Thai letters (`MOJIBAKE_MIN_HITS`). The page is OCR'd once as a
  reference; `learn_mojibake_map` votes a mapping (`MOJIBAKE_MAP_MIN_VOTES = 2`,
  `MOJIBAKE_MAP_MIN_AGREEMENT = 0.75`); `repair_mojibake` writes the marks back
  into the PDF's own text layer, tables included.
- Marks that cannot be learned are left out and their lines flagged, while they
  are at most `MOJIBAKE_MAX_UNMAPPED_SHARE = 0.2` of the swapped characters.
  Above that, the page falls back to full OCR. A repaired page carries the note
  "> Thai marks on this page were mis-encoded in the PDF and were repaired; N
  character(s) could not be recovered (highlighted lines)."
- `REPAIR_LOSS_CONFIDENCE = 0` (`doc2md/core/review.py`): repair-loss lines are
  highlighted like uncertain OCR lines, with the tooltip "Thai marks were lost in
  the PDF here - check this line against the original". With the flag option on,
  they get a bare " ⚠" instead of " ⚠NN%".
- Table symbol cells (`pdf_engine.py`): `_symbol_in_cell` and `TABLE_SYMBOL_CELLS`
  decide a cell whose whole ink is one small dot or one short dash as "•" or "–".
  Sizes are in PDF points, and such cells are never re-read.
- Short table labels (`pdf_engine.py`): `_needs_short_reread`, with
  `TABLE_SHORT_TEXT_MAX_CHARS = 3` and `TABLE_SHORT_LATIN_MAX_CHARS = 6` (no
  digits). The cell is re-read alone.
- Upper-mark rejoin (`ocr_text.py`): when the disagreement is only a look-alike
  pair (ซ/ช, ข/ฃ, ด/ต, บ/ป, พ/ฟ, ถ/ภ), the base letter is kept and the marks are
  still merged. Exact letter matches are aligned first.
- Latin words read as Thai: `_reread_latin_runs` (`ocr_text.py`) re-reads a short
  low-confidence Thai run next to a Latin word of 3 or more letters with English
  only (`--psm 8`). The re-read is accepted only as one uppercase word of 2-5
  letters at confidence 85 or more, at most 20 per band.
- Maintenance: `_pixel_values` in `ocr_text.py` replaces `Image.getdata()` with
  `get_flattened_data()` and a fallback. The `real_tesseract` fixture in
  `tests/conftest.py` finds Tesseract as the app does, and the real-Tesseract test
  in `tests/test_thai_documents.py` uses it.
- Tests: new `tests/test_pdf_mojibake.py`, `tests/test_pdf_mojibake_repair.py` (33)
  and `tests/test_ocr_latin_reread.py` (26); extended `tests/test_table_ocr.py`
  (64), `tests/test_ocr_thai_marks.py` (65), `tests/test_review.py` and
  `tests/test_gui_review_flags.py`.
- Regression: all 8 approved samples re-run with `tools/regress.py`; none
  REGRESSED. QP 7 is "fixed" (all 24 expected phrases now, 22 before). EU2043
  changed by one word on a low-resolution page. Fortuner changed as intended.

### What changed in 1.5.3

Table OCR on pages read by OCR, and layout frames (`doc2md/engine/pdf_engine.py`):

- A table on an OCR'd page is read with one Tesseract pass (`--psm 6`) instead
  of one call per cell (`_grid_from_table_ocr`). Cell borders are whitened
  first; dark header and section-bar cells are inverted and contrast-stretched.
  Each word goes to the cell holding its box centre.
- A cell is re-read alone only if it has ink but no words, or its words' mean
  confidence is below 50 (`TABLE_CELL_MIN_CONFIDENCE`). Symbol-only cells
  (`_is_symbol_only`: bullets, dashes, dots) are never re-read alone. If the
  single pass fails or finds nothing, the table falls back to the per-cell
  reader (`_grid_from_cell_ocr`, kept).
- A detected table with at most 4 cells (`FRAME_TABLE_MAX_CELLS`) that contains
  another detected table, within 2 pt (`FRAME_TABLE_TOLERANCE_PT = 2.0`), is a
  layout frame: it is not rendered as a table and its prose is kept
  (`_without_frame_tables`). This applies to OCR pages (`_ocr_page_with_tables`)
  and text-layer pages (`_extract_tables`). Real tables of 5 or more cells that
  contain a small table are kept; EU2043 page 2 is unchanged.
- Tests: `tests/test_table_ocr.py` (44, synthetic images, mocked Tesseract) and
  `tests/test_pdf_frame_tables.py` (5, synthetic PDF). Full suite: 1030 passed,
  3 skipped, plus 44 GUI review-flag tests.
- Regression: all 8 approved samples in `D:\AI\OpenCode\doc2md-samples\` were
  re-run with `tools/regress.py`; none REGRESSED. Fortuner and mu-X changed as
  intended. Other changes, if any, will be recorded by the maintainer.

### What changed in 1.5.2

Image-only pages inside text PDFs are now read by OCR (`doc2md/engine/pdf_engine.py`):

- Routing is per page inside a text PDF too. A page with under 16 characters of
  its own text layer, and images covering at least 25% of it (overlaps counted
  once), is image-only.
- Image-only and mis-encoded pages share one OCR pass (one combined page
  progress, same DPI and table handling). Metrics add both kinds into
  `ocr_pages_success` / `ocr_pages_empty` / `ocr_pages_failed`.
- The page keeps its footer, then "> This page has no text layer (it is an
  image); it was read by OCR.", then the OCR text. If OCR finds nothing, the
  page says so and is not counted as content. If OCR is off or unavailable, the
  result is a Warning naming the pages as ranges.
- At most 100 image-only pages are OCR'd per document, with a warning beyond that.
- `pages_with_content` no longer counts a footer-only image page unless OCR
  found text on it.

### What changed in 1.5.1

Fix for detached Thai upper marks and sara am on scans (`doc2md/core/ocr_text.py`):

- A low-confidence row directly above a line is re-read together with that line
  (Tesseract `--psm 7`) and merged at character-cluster level: letters from the
  first read, marks from the re-read only where the letters agree, and the junk
  mark row dropped. Words where the letters disagree keep the first read.
- `normalize_thai` runs on all OCR output: nikhahit + sara aa becomes sara am,
  a doubled identical mark collapses, and tone + same tone + sara aa becomes
  tone + sara am.
- Re-reads are capped at 40 per band, which costs time (section 7).
- Measured on one real scanned procedure (section 7). Not yet tried by the user.

### What changed in 1.5.0

Clean output by default, with the review done in the app (the user's design
choice; the reasoning is in HISTORY.md):

- **Exported and copied Markdown has no `⚠` flags by default.** 1.4.11 wrote
  ` ⚠NN%` into the text itself, which an AI reads as data and which costs
  tokens. Flags now travel beside the text: `doc2md/core/review.py`
  (`ReviewLine(line, confidence, text)`, `extract`, `with_inline_flags`),
  exposed as `ConversionResult.review_lines`. Engines mark lines with two
  private-use characters that `Converter` removes after cleaning.
  `QualityMetrics.ocr_review_lines` always equals the number of review lines
  in the final text.
- **Changes exported content versus 1.4.11**, which is why this is a MINOR bump.
- **GUI preview:** amber full-width background on each flagged line, hover
  shows the confidence; a "⚠ N lines to review" chip with "‹" and "Next ›"
  buttons (both wrap; the chip shows "⚠ 1 / 2"-style position while the cursor
  is on a flagged line; hidden when nothing is flagged). The quality summary
  says "N line(s) to review" and has its own full-width row under the toolbar
  (long text cut with "…", full text on hover).
- **Opt-in inline flags:** checkbox "Flag uncertain OCR lines in output" (off by
  default, remembered between runs) makes Copy Markdown, Copy Selected, Export…
  and Export Each File… append ` ⚠NN%`. CLI: `--mark-uncertain/--no-mark-uncertain`
  on `convert`; with neither given, the `mark_uncertain` key in `doc2md.toml`
  applies, and `--no-mark-uncertain` forces flags off. With flags on, a flagged
  pipe-table row gets its flag inside the last cell, before the closing pipe.
- **Send to Sandbox / `bridge` is always clean**, whatever the setting.
- Flag sources are unchanged: OCR'd PDF pages only. The threshold
  `REVIEW_LINE_CONFIDENCE = 70.0` in `doc2md/core/ocr_text.py` is still untuned
  against real bad scans.

### 1.4.11 (still not tried by a real user)

Three features: "Export Each File…" writes each converted file to its own `.md`
in a chosen folder; OCR lines Tesseract was unsure of were flagged (now clean by
default, see 1.5.0); and the two PDF OCR loops report real "Page N/M" progress
instead of a busy spinner. All covered by tests and the gate passed for 1.4.11,
but none of the three has been tried by the user on a real document yet - see
section 9.

Not in the repo, and therefore not on the new machine unless you copy them:

- The sample documents used for testing (Toyota brochure, price quotes, poster,
  company certificate, letters, the CAR/OBS workbook, the 220-file legacy Office
  library). The test suite does **not** need them: it builds its own fixtures
  (`tests/legacy_builders.py` writes synthetic .doc/.ppt/.xls, other tests
  generate PDFs with a Thai font).
- Claude's per-machine memory notes (`~/.claude/projects/.../memory/`). Their
  content that still matters is copied into section 6 below.
- Tesseract and its language data (installed per machine, see section 2).

## 2. Setting up the new machine

1. **Python 3.14** (development used 3.14.7) with `pip`.
2. From the repo root:

   ```
   pip install -r requirements-dev.txt
   ```

   This brings PyQt6, typer, PyMuPDF, pdfplumber, python-docx, openpyxl,
   python-pptx, xlrd, olefile, pytesseract, pyinstaller, pytest (+ timeout, cov),
   and `xlwt` (dev only, writes .xls fixtures).
   Versions used so far: PyMuPDF 1.28.2, pdfplumber 0.11.10, PyQt6 6.11.0,
   openpyxl 3.1.5, python-docx 1.2.0, python-pptx 1.0.2, xlrd 2.0.2,
   olefile 0.47, PyInstaller 6.22.2, pytest 9.1.1.
3. **Inno Setup 6** for the installer. `build_installer.py` looks in the usual
   Program Files locations and falls back to `winget install JRSoftware.InnoSetup`.
4. **Tesseract** (only needed to run OCR, not the tests): launch the app, open
   **OCR Diagnostics...**, press **Install OCR (Thai + English)...**. It runs
   `winget install --id UB-Mannheim.TesseractOCR` (Windows asks for admin) and
   downloads `tha` and `eng` from `tessdata_fast` 4.1.0 into
   `%LOCALAPPDATA%\doc2md\tessdata`.
5. Optional: `tiktoken` gives exact token counts. It is **not** a dependency;
   without it the app uses a fitted heuristic (`doc2md/core/tokens.py`).
6. Confirm everything is healthy:

   ```
   powershell -ExecutionPolicy Bypass -File ./tools/verify.ps1
   ```

   Expect `ALL CHECKS PASSED` and `EXIT_CODE: 0`. The pytest suite is roughly
   600+ tests and takes a few minutes. If a test needs Tesseract it skips or is
   isolated by `tests/conftest.py` (see gotchas).

## 3. Everyday commands

```
python -m doc2md gui                                   # desktop app
python -m doc2md convert file.pdf --stdout             # CLI
python -m doc2md convert scan.pdf --ocr-lang tha+eng --report q.json
python -m doc2md --version
powershell -ExecutionPolicy Bypass -File ./tools/verify.ps1   # the gate
python build.py                                        # onedir -> onefile -> installer
```

## 4. Release pipeline (from CLAUDE.md - it is binding)

1. Edit code. 2. Purge caches (`__pycache__`, `build/`, `dist/`, `.cache`).
3. Run `tools/verify.ps1`. 4. Read the live `EXIT_CODE` and log; any
`VALIDATION FAILED`, `No command given`, `is not recognized` or
`Background task failed` means fix and rerun - never skip to the build, never
substitute another script, never cite "sandbox limits". 5. `python build.py`.
6. Bump the version in `pyproject.toml` **and** `doc2md/__init__.py`, and add
an entry headed `[x.y.z]` to **both** `CHANGELOG.md` and `HISTORY.md` (the gate's
"Changelog coverage" check fails otherwise).

## 5. Architecture in one page

- `doc2md/core/router.py` - decides the file kind from extension plus magic
  bytes (OLE files: the extension separates .doc / .xls / .ppt).
- `doc2md/engine/*` - one engine per format; the registry is in
  `engine/__init__.py`. `pdf_engine.py` is the largest and most delicate.
- `doc2md/core/converter.py` - runs an engine, isolates PDF/OCR in a spawned
  worker process, honours a cancel event (`ConversionCancelledError`).
- `doc2md/core/exporter.py` - atomic output writing, output policies,
  all-or-nothing commit of chunk sets (`PartialCommitError`).
- `doc2md/core/tables.py` - the one Markdown table renderer (Thai-aware width).
- OCR: `ocr_setup.py` (find/install Tesseract), `ocr_text.py` (page and poster
  reading), `ocr_diagnostics.py`, `engine/ocr_engine.py` (images).
- PDF text repair: `core/pdf_text.py`.
- `gui/main_window.py`, `gui/ocr_dialog.py`, `gui/theme.py` - PyQt6 app; the
  whole window accepts drops.
- `cli/main.py` - typer CLI; default output policy is `overwrite` for the CLI
  and "Converted folder" for the GUI.

## 6. Gotchas that cost time before

- **Bash heredocs lose a level of backslashes on the old machine.** A patch
  script holding `"\n"` wrote a real newline into source files. Use the
  Edit/Write tools, or `chr(92)`, for anything with escape sequences, and
  `ast.parse` the result. Confirmed on the new machine too (2026-10-16).
- **Scripts that spawn processes must be guarded** with
  `if __name__ == "__main__":` - the converter uses the `spawn` start method, so
  an unguarded script re-imports itself and appears to hang (one PDF run took
  over 10 minutes).
- **Printing Thai on a cp1252 console** raises `UnicodeEncodeError`; set
  `PYTHONIOENCODING=utf-8`.
- **Tesseract isolation in tests:** `tests/conftest.py` has an autouse fixture
  that sets `DOC2MD_NO_TESSERACT_SEARCH` so a developer's real install does not
  change test results. Remember it when debugging OCR behaviour by hand.
- **`.md` mirror files:** on the old machine some tool wrote a `.md` sibling
  beside source files and re-wrapped existing `.md` files in nested code fences.
  The repo ignores those mirrors and `tests/test_documentation_integrity.py`
  fails if README/CHANGELOG/HISTORY/CLAUDE.md get wrapped again. If it
  reappears, peel the fences rather than blaming an edit, and find the step that
  regenerates them.
- `localcore_crash.log` in the repo root is a stray log from an unrelated tool
  (a Rust panic), not from doc2md.
- Downloads of language data or models need the user's explicit say-so. The user
  approved `tessdata_best` once (measured, not adopted); Chinese language data
  was **not** approved.
- **A `verify.ps1` run that crashes natively partway through pytest**
  (exit `-1073740791` / `0xC0000409`, a Windows stack violation) is not
  automatically a flake. 1.4.10's history recorded one as unexplained; in
  1.4.11 the exact same crash turned out to be caused by three earlier
  `pytest`/Qt processes still running, stuck forever in a real modal
  `QMessageBox.exec()` with no one to click it (a test bug - see the next
  bullet). Before re-running and shrugging it off as a flake, check for
  and kill stray `python.exe` pytest processes first:
  `powershell -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Select-Object ProcessId, CommandLine"`.
- **A GUI test that triggers `self._warn(...)` hangs forever in a headless
  run**, not just "runs slowly" - `_warn()` is a real `QMessageBox.warning()`,
  a blocking modal with no one to dismiss it under the offscreen Qt
  platform. Stub `QMessageBox.warning`/`.question` via monkeypatch (see
  `test_closing_window_during_conversion_does_not_force_delete_thread` and
  `test_export_each_file_refuses_when_nothing_converted` in
  `tests/test_gui_qt.py`) before writing a test for any "nothing to do"
  refusal path that does not already take a `quiet=` flag.

## 7. What was measured (so it is not redone)

- **Token counts:** without tiktoken the heuristic uses script-class weights
  fitted to cl100k: Thai base .877, Thai mark 1.069, Latin .160, digit .715,
  space .644, newline 1.604, ASCII punctuation .865, pipe/dash .44, other 1.0.
- **OCR resolution:** 300 DPI default for Balanced AI and Thai Scanned Document
  (High Fidelity 400, Fast Text 150).
- **`tessdata_best` vs `tessdata_fast`:** equal or slightly worse on the Thai
  scans tried, about 2x slower. Not adopted.
- **ข read as ย** on grey scans: 8 wrong readings unprocessed, 11 with the 1.3.2
  "whiten every light pixel" fix, 4 with the 1.3.5 colour-aware fill fix plus
  contrast stretch and a median filter (only on pages 2500 px or taller).
- **Mis-encoded Thai text layers:** about 4.6% of 345 Thai-heavy PDF pages in the
  user's own library; detected by `thai_text_is_corrupt` and re-read by OCR.
- **Legacy Office on 220 real files:** all 90 `.xls` and all 40 `.ppt` converted;
  79 of 90 `.doc` (the other 11 contain only pictures and are reported as such).
- **Detached upper marks (1.5.1), `QP 7.pdf` in the samples folder** (a real
  seven-page scanned procedure). Page 1 checked against 24 phrases read from the
  scan by eye: 14/24 found in 1.5.0, 22/24 in 1.5.1. Review-flagged lines 102 ->
  63. Seven pages 36 s -> 52.5 s (extra single-line re-reads, capped at 40 per
  band). Every changed line across all 7 pages was compared; no correctly read
  base word was replaced. The phrase list is the samples folder's `.expect.txt`.
- **Image-only pages in text PDFs (1.5.2), real samples:** the 29-page tour
  brochure's pages 19-29 (images, footer-only text layer), the 4-page company
  guide's pages 3-4 and a car brochure's cover are all read now. Nothing else
  changed; the approved scanned reference is identical. The brochure took 2 s
  before (pages skipped) and 92 s now. Before the fix its report said 29/29
  pages with content, because each image page's footer counted.
- **Table OCR (1.5.3), `Fortuner_Leader_Catalog_2025.pdf` page 1:** table
  reading 93 s -> 18 s; whole file 118.6 s -> 51.3 s (part of the rest is page
  prose that was never read before, see frame tables below). Accuracy against a
  hand-transcribed 74-row table 0.831 -> 0.934, mainly because values spanning
  several columns are now read whole.
- **Frame tables (1.5.3):** affected pages are Fortuner 1, 5 and 6 and mu-X
  brochure page 8. Their prose was hidden inside one giant cell; it is now kept.
- **Table symbol cells (1.5.4), Fortuner page 1's second table:** 178 bullet and
  dash cells now read correctly.
- **Short table labels (1.5.4):** accuracy on the hand-transcribed Fortuner table
  0.934 -> 0.941. "สี" and "สีภายใน" still read as "a".
- **Mis-encoded marks (1.5.4), Fortuner pages 3-6:** now correct Thai. Characters
  not recovered, highlighted: 4, 4, 2 and 4 (pages 3 to 6 in order). Page 3 is a
  photo layout where full OCR was mostly noise. Fortuner takes about 86 s, against
  39 s in 1.5.3, because of the reference OCR.
- **Regression (1.5.4):** 8 approved samples, none REGRESSED. QP 7 finds 24 of 24
  expected phrases (was 22). EU2043 changed by one word on a low-resolution page.
  Fortuner changed as intended.

- **Dingbat symbols (1.5.5), EU2043 meal table:** 31 invisible characters before;
  now ✓/✗, 🛏 and ☑/☒.
- **Short table labels (1.5.5), Fortuner page 1 table 1:** 0.941 -> 0.945 (0.940 ->
  0.944 with symbols kept). Rows below 0.8: 8 -> 6. "สี", "สีภายใน", "4สูบ", "พร้อม"
  and "ปรับ" read correctly; "อัตโนมัติ" now reads "อฮิตโนมัติ".
- **Logo noise rows (1.5.5), QP 7, camry, EU2043:** 27 junk rows dropped (QP 7 10,
  EU2043 7, camry 10), 0 real rows dropped (checked by eye). QP 7 still 24/24.
  Review lines: QP 7 63 -> 55, camry 97 -> 87, EU2043 60 -> 53. Time change under 1%.
- **Regression (1.5.5):** 8 approved samples, none REGRESSED. Changed on purpose:
  Fortuner, QP 7, camry, EU2043. Unchanged: mu-X, QMEL, quote, guideline.
- **Scan text kept (1.5.6), HR manual** (9th sample, confidential, 27-phrase
  `.expect.txt`, not approved): 11 -> 22 of 27 phrases. Table of contents, severance
  table and overtime rates now read. Still missing: cover display type and address
  line, one section heading, one vacation line (median filter).
- **Scan text kept (1.5.6), QP 7 / camry / EU2043:** QP 7 still 24/24 and gains
  header-table text (document number, date, company name). camry gains "4 ล้อ" and
  "4.2 นิ้ว". EU2043 gains a price table and form text.
- **Time (1.5.6):** QP 7 +6%, HR manual +5%, EU2043 +12-15% (most rescue reads).
- **Regression (1.5.6):** 8 approved samples, none REGRESSED, no previously good line
  worse. Changed: QP 7, camry, EU2043, guideline. Unchanged: Fortuner, mu-X, QMEL,
  quote.

## 8. Known limits and open ideas

Not solved:

- Stylised display text and headers on dark gradient buttons in posters.
- Chinese text is not read (no language data; the user decided not to add it).
- Drawn ✓/✗ detection in OCR'd tables is tested only on synthetic images; no real
  sample has drawn ticks yet.
- A lone "X" or "x" in a table cell reads as ✗.
- Residual ข/ย errors on poor scans.
- Legacy `.doc`: no headers/footers, footnotes, text boxes. Legacy `.ppt`: no
  table grids, bullet levels, pictures.
- Low-resolution embedded images: the brochure's terms pages embed their images
  at 96 dpi, so small Thai text OCRs poorly (e.g. "รายสะเอียด" for
  "รายละเอียด"). Rendering at a higher DPI cannot recover detail the file does
  not contain.
- In the table read, "สี" is fixed (1.5.5), but "อัตโนมัติ" comes out as
  "อฮิตโนมัติ" and the section bar "ภายในและอุปกรณ์อำนวยความสะดวก" is still unread.
  Bullet and dash cells are read as symbols (1.5.4).
- A repaired page can lose up to 20% of its swapped Thai marks (1.5.4). Those
  lines are highlighted for review.
- The mu-X page 8 text layer has labels clipped by the PDF itself.
- Cover pages with large display type still split into fragments. On the HR manual
  sample, the cover title and address line and one section heading are still
  missing (1.5.6).
- One vacation line in the HR manual sample is lost to the median filter. Removing
  the filter costs QP 7 3-7 phrases, so it stays (1.5.6).
- Rescued text on low-quality scans can be garbled but real: camry and EU2043 each
  gained a few such lines (1.5.6).
- The row rescue adds up to about 15% time on form-heavy scans (1.5.6).

Small maintenance items seen in the last gate run (2026-10-16, v1.4.11):

- `pytest-timeout` is installed (per `requirements-dev.txt`) - no more
  "Unknown pytest.mark.timeout" warnings.
- Expected skips: the real-Tesseract test in `tests/test_thai_documents.py` now
  runs when Tesseract is installed in its standard folder, not only when it is on
  PATH (via the `real_tesseract` fixture in `tests/conftest.py`).

Ideas not started:

- A vision-model route for posters and other design-heavy images.
- Per-cell vertical alignment for merged cells in tables.

Decided against by the user (2026-10-17) - do not propose again:

- Chinese (and other extra) OCR language data.
- Code-signing the installer.

## 9. Waiting on real-world testing by the user

The suite cannot cover these; nobody has done them on the built exe yet:

1. Five to ten scanned Thai documents (different scanners and paper).
2. PDFs exported from Excel and from Word with Thai tables.
3. Real mouse drag-and-drop onto the installed exe.
4. Cancel during a large scanned PDF.
5. Legacy .doc / .xls / .ppt through the GUI.
6. Very large files (memory and time).
7. **(new in 1.4.11) "Export Each File…"** on a batch of several real,
   differently-named documents - confirm the files land correctly and
   `unique` numbering kicks in if two share a stem.
8. **(1.4.11, changed in 1.5.0) OCR review highlights** on a real poor-quality
   Thai scan - confirm the amber highlights in the preview land on lines that
   are genuinely wrong, not on clean text (the threshold,
   `REVIEW_LINE_CONFIDENCE = 70.0` in `ocr_text.py`, was picked to avoid
   false positives on the synthetic test fixtures, never tuned against a
   real bad scan). Also confirm that Copy Markdown and Export output has no
   ` ⚠NN%` marks by default, and that they appear only with the "Flag
   uncertain OCR lines in output" checkbox on.
9. **(new in 1.4.11) Real page-count progress** on a large real scanned
   PDF - confirm "Page N/M" tracks correctly and the bar does not get
   stuck between files in a batch.
10. **(done 2026-10-17) `QP 7.pdf` approved** in the samples folder as the
    regression reference, by the user's decision, from a fresh run of the
    released 1.5.1 code (22/24 expected phrases; the two known misses are
    listed in section 8). Every `python tools/regress.py run` now compares
    against it - run it before each release build. Add more real scans the
    same way so one document's fix cannot quietly break another.
11. **(done 2026-10-17) Seven more real samples approved** in
    `D:\AI\OpenCode\doc2md-samples\` by the user's decision, from a fresh run of
    the 1.5.2 code; all 8 samples are now regression references. The 1.5.3 run
    `.runs\20261017-215241` changes Fortuner and mu-X on purpose (one-pass table
    OCR, frame tables; checked by eye, no REGRESSED file). The user approved
    both, and they were re-approved from that run on 2026-10-17, so all 8
    references now hold 1.5.3 output.
12. **(done 2026-10-19) 1.5.4 regression approvals.** From run
    `.runs\20261019-065516` (1.5.4 code): QP 7 fixed (24/24 phrases), Fortuner
    changed on purpose (repaired Thai marks on pages 3-6, bullet cells),
    EU2043 one word better, the rest identical, no REGRESSED file. The user
    approved all three; all 8 references now hold 1.5.4 output.
13. **(pending, 2026-10-21) 1.5.6 regression approvals.** From run
    `.runs\20261021-212030` (1.5.6 code). The new HR manual (the 9th sample, with its
    27-phrase `.expect.txt`) is not approved yet. The changed QP 7, camry, EU2043 and
    guideline references await the user's approval. Fortuner, mu-X, QMEL and the
    quote are unchanged.

Report findings as: file type, what the output should have said, what it said.
Fixes so far came from exactly that kind of sample.

**Make each tested sample permanent (added after 1.4.11).** Put the file in
`D:\AI\OpenCode\doc2md-samples\` (outside git, the default for
`tools/regress.py`), add `<file>.expect.txt` with a few phrases that must
appear (names, amounts, the words OCR tends to get wrong), run
`python tools/regress.py run`, check the output against the original, and
`python tools/regress.py approve <file>` once it is right. From then on every
`run` compares against it, and anything that gets worse shows as REGRESSED.
Run it before every release build, alongside the gate. The README's
"Real-document regression check" section has the details.

## 10. Developer tooling not yet in a release

- `tools/regress.py` + `tests/test_regress_tool.py` (CHANGELOG/HISTORY
  `[1.5.0]`, under developer tooling). Dev-only, under `tools/`.
- GitHub CI (`.github/workflows/ci.yml`, Python 3.11-3.13) had failed on
  every push since 1.3.0 on one timing-dependent cancel test; fixed in the
  test (see CHANGELOG `[1.5.0]`). Check `gh run list` after each push -
  the local gate passing does not mean CI does, and nobody had looked.
- Decided in 1.5.0 (was an open question): the ` ⚠NN%` flags are kept out of
  exported Markdown by default, because they cost tokens and can confuse an AI
  reading it. They show as highlights in the app's preview, and can be written
  into the text on request (GUI checkbox, `--mark-uncertain/--no-mark-uncertain`, `mark_uncertain`
  in `doc2md.toml`). Sandbox output is always clean.

## 11. First steps on the new machine

1. Get the code: `git clone` (after pushing) or copy the folder.
2. Section 2 setup, then run the gate.
3. `python build.py` and install the result; try the section 9 checks.
4. Read `HISTORY.md` for the story of each release and `CHANGELOG.md` for the
   precise list of changes.
