# Handoff - doc2md v1.4.0

Written 2026-10-04. Read this first, then README.md (what the tool does) and
CLAUDE.md (the release pipeline rules).

## 1. State right now

| Item | Value |
| --- | --- |
| Version | 1.4.0 (`pyproject.toml` and `doc2md/__init__.py` agree) |
| Last release commit | see `git log` |
| Branch | `main`, working tree clean at the time of writing |
| Remote | `origin` = https://github.com/passagain-loui/doc2md.git |
| Unpushed work | `main` was **19 commits ahead of `origin/main`**. Push before leaving the old machine, or copy the whole folder including `.git`. |
| Gate | `tools/verify.ps1` passed (EXIT_CODE 0) for 1.3.5 |
| Installer | `dist/doc2md_Setup_v1.3.5.exe` (plus `dist/doc2md/` and `dist/doc2md.exe`) - **`dist/` and `build/` are git-ignored; rebuild on the new machine** |

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
  `ast.parse` the result. Check whether the new machine behaves the same.
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

## 8. Known limits and open ideas

Not solved:

- Stylised display text and headers on dark gradient buttons in posters.
- Chinese text (no language data installed).
- Check-mark matrices (tick/cross tables) come out as noise.
- Residual ข/ย errors on poor scans.
- Legacy `.doc`: no bold/italic, headers, footnotes. Legacy `.ppt`: no notes,
  table layout, pictures.

Small maintenance items seen in the last gate run:

- `Image.getdata()` (used in `doc2md/core/ocr_text.py`, two places) is deprecated
  in Pillow 14 (due 2027-10-15); move to `get_flattened_data()` before then.
- On the old machine `pytest-timeout` was not installed, so the gate printed
  "Unknown pytest.mark.timeout" warnings. `requirements-dev.txt` lists it, so a
  fresh install will not show them.
- Expected skips: symlink test, RapidOCR test, and one Thai test that needs a
  real Tesseract.

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

Report findings as: file type, what the output should have said, what it said.
Fixes so far came from exactly that kind of sample.

## 10. First steps on the new machine

1. Get the code: `git clone` (after pushing) or copy the folder.
2. Section 2 setup, then run the gate.
3. `python build.py` and install the result; try the section 9 checks.
4. Read `HISTORY.md` for the story of each release and `CHANGELOG.md` for the
   precise list of changes.
