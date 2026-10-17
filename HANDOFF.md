# Handoff - doc2md v1.5.1

Written 2026-10-04, updated 2026-10-17. Read this first, then README.md (what
the tool does) and CLAUDE.md (the release pipeline rules).

## 1. State right now

| Item | Value |
| --- | --- |
| Version | 1.5.1 (`pyproject.toml` and `doc2md/__init__.py` agree) |
| Last release commit | `a70613f` - "release: v1.5.1 rejoin Thai upper marks on scans, normalise sara am" (CI green on 3.11-3.13) |
| Branch | `main` |
| Remote | `origin` = https://github.com/passagain-loui/doc2md.git - check `git status -sb` for unpushed commits; GitHub CI (Python 3.11-3.13) green since commit `8d9adde` |
| Gate | `tools/verify.ps1` passed (EXIT_CODE 0) for 1.5.1 on 2026-10-17; 3 expected skips (symlink, RapidOCR not installed, PATH-only Tesseract check) |
| Installer | built 2026-10-17 from the gated 1.5.1 tree: `dist/doc2md_Setup_v1.5.1.exe` (69 MB), `dist/doc2md.exe` (95 MB), `dist/doc2md/` - git-ignored, rebuild with `python build.py` on another machine |
| Tesseract | **installed and working on this machine** (checked 2026-10-17): v5.4.0 at `C:/Program Files/Tesseract-OCR/tesseract.exe`, languages `eng` + `tha`. It is not on PATH, but `find_tesseract()` locates it in the standard install folder, so the app uses it. A real Thai test image and scanned PDF converted correctly apart from a lost tone mark (นี้ read as นี). The gate's one 'Tesseract not installed' skip (`tests/test_thai_documents.py`) checks `shutil.which("tesseract")`, i.e. PATH only, so it skips here; add the folder to PATH if you want that real-OCR test to run |

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

## 8. Known limits and open ideas

Not solved:

- Stylised display text and headers on dark gradient buttons in posters.
- Chinese text (no language data installed).
- Check-mark matrices (tick/cross tables) come out as noise.
- Residual ข/ย errors on poor scans.
- Legacy `.doc`: no bold/italic, headers, footnotes. Legacy `.ppt`: no notes,
  table layout, pictures.
- Upper marks on a letter Tesseract misread: the re-read is used only where the
  letters agree, so "รายซ้ำ" comes out as "รายซำ" (the re-read saw ช, so no marks
  could be merged).
- Latin read as Thai: "QM" comes out as Thai "อห". A Latin-vs-Thai disagreement
  keeps the first read.
- Logo noise rows with no line under them remain.

Small maintenance items seen in the last gate run (2026-10-16, v1.4.11):

- `Image.getdata()` (used in `doc2md/core/ocr_text.py`, two places) is still
  deprecated in Pillow 14 (due 2027-10-15, confirmed still raising the
  `DeprecationWarning` in the pytest output); move to `get_flattened_data()`
  before then. Not urgent.
- `pytest-timeout` is installed (per `requirements-dev.txt`) - no more
  "Unknown pytest.mark.timeout" warnings.
- Expected skips on this machine: just the one Thai test that needs a real
  Tesseract binary (tessdata is present but `tesseract.exe` itself is not on
  PATH here - see section 1). The symlink and RapidOCR tests ran rather than
  skipped this time, so whatever made them skip before no longer applies.

Ideas not started:

- A vision-model route for posters and other design-heavy images.
- Chinese (and other) language data, with the user's permission to download.
- Code-signing the installer.
- Per-cell vertical alignment for merged cells in tables.

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
