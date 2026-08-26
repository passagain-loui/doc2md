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
# History & Verification Audit Trail

This file records verification runs, timestamps, and quality metrics per release.

## [0.3.1] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v4.1 (Final Build)
- **Gatekeeper:** Direct pytest verification via `python -m pytest tests/ --cov=doc2md --cov-fail-under=90 -v`
- **Result:** `EXIT_CODE:0` — **VALIDATION PASSED**; "Required test coverage of 90% reached. Total coverage: 93.68%"; `302 passed, 1 skipped in 19.45s`
- **Test count:** 303 total (302 passed, 1 skipped; up from 275+ in initial audit), including 20+ new deep-audit edge-case tests
- **Coverage metrics:**

| Module | Statements | Miss | Cover |
| --- | --- | --- | --- |
| doc2md/cli/main.py | 170 | 11 | 94% |
| doc2md/core/chunker.py | 155 | 18 | 88% |
| doc2md/core/converter.py | 132 | 1 | 99% |
| doc2md/core/router.py | 139 | 2 | 99% |
| doc2md/engine/ocr_engine.py | 109 | 7 | 94% |
| All other modules | — | — | 86–100% |
| **TOTAL** | **1710** | **108** | **93.68%** |

- **Deep audit findings:** 20+ edge-case tests verified across GUI threading, Audio Engine resilience, document converter robustness, and file system edge cases. All audit tests PASS with no bugs identified in core conversion logic.
- **Standalone build:** `python build_exe.py` -> `dist/doc2md.exe` (115.3 MB), `python build_installer.py` -> `dist/doc2md_Setup_v0.3.1.exe` (116.3 MB).
- **GitHub Release:** https://github.com/passagain-loui/doc2md/releases/tag/v0.3.1

## [0.2.1] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v3.4
- **Gatekeeper:** Direct pytest verification (LocalCore fallback for git)
- **Result:** `EXIT_CODE:0` — VALIDATION PASSED; "Required test coverage of 90% reached. Total coverage: 94.08%"; `252 passed in 20.40s`
- **Test count:** 252 (up from 210 in v0.2.0), including 42 new edge-case tests in `test_edge_bugs.py`
- **Coverage metrics:**

| Module | Statements | Miss | Cover |
| --- | --- | --- | --- |
| doc2md/cli/main.py | 161 | 3 | 98% |
| doc2md/core/chunker.py | 155 | 18 | 88% |
| doc2md/core/clipboard.py | 13 | 0 | 100% |
| doc2md/core/config.py | 72 | 7 | 90% |
| doc2md/core/contextmenu.py | 79 | 7 | 91% |
| doc2md/core/stats.py | 42 | 1 | 98% |
| doc2md/core/tokens.py | 38 | 0 | 100% |
| doc2md/engine/ocr_engine.py | 109 | 7 | 94% |
| All other modules | — | — | 86–100% |
| **TOTAL** | **1688** | **100** | **94.08%** |

- **New stress-test scenarios verified:** OCR pure black/white/noise images, ultra-high-resolution 8K images, palette PNGs, 16-bit TIFFs, transparent WebP, EXIF-rotated JPEGs, 10 parallel OCR threads with zero temp leaks, CLI edge cases (invalid paths, read-only outputs, empty clipboard, glob patterns, timeout/max-rows/chunk validation).
- **GitHub integration:** Added `.gitignore`, `LICENSE` (MIT), enhanced `README.md` with badges & usage examples, and CI/CD workflows (`.github/workflows/ci.yml` for testing, `.github/workflows/release.yml` for auto-release).
- **Standalone build:** `python build_exe.py` -> `dist/doc2md.exe` (PyInstaller onefile), `python build_installer.py` -> `dist/doc2md_Setup_v0.2.1.exe` (Inno Setup).

## [0.2.0] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v3.4
- **Gatekeeper:** LocalCore (`C:\Program Files\LocalCore\LocalCore.exe --verify "pytest --cov=doc2md --cov-fail-under=90 tests/" --model "Qwen-2.5-Coder-14B"`)
- **Result:** `EXIT_CODE:0` — VALIDATION PASSED; "Required test coverage of 90% reached. Total coverage: 93.58%"; `210 passed in 12.19s`
- **Test count:** 210 (up from 135 in v0.1.2)
- **Coverage metrics:**

| Module | Statements | Miss | Cover |
| --- | --- | --- | --- |
| doc2md/cli/main.py | 161 | 8 | 95% |
| doc2md/core/chunker.py | 168 | 21 | 88% |
| doc2md/core/clipboard.py | 13 | 0 | 100% |
| doc2md/core/config.py | 72 | 7 | 90% |
| doc2md/core/contextmenu.py | 76 | 7 | 91% |
| doc2md/core/stats.py | 42 | 1 | 98% |
| doc2md/core/tokens.py | 38 | 0 | 100% |
| doc2md/engine/ocr_engine.py | 93 | 7 | 92% |
| All other modules | — | — | 86–100% |
| **TOTAL** | **1682** | **108** | **93.58%** |

- **New features verified by tests:** clipboard copy (`--copy`), token stats (`--stats`), semantic chunking (`--chunk`), context-menu install/uninstall/status (HKCU), `doc2md.toml` config precedence and malformed-config warning, RapidOCR fallback backend.
- **Standalone build:** `python build_exe.py` -> `dist/doc2md.exe` (PyInstaller onefile), smoke-tested with `dist\doc2md.exe --help`.

## [0.1.2] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v3.4
- **Gatekeeper:** LocalCore (`C:\Program Files\LocalCore\LocalCore.exe --verify "pytest --cov=doc2md --cov-report=term-missing --cov-fail-under=90 tests/" --model "Qwen-2.5-Coder-14B"`)
- **Result:** `EXIT_CODE:0` — VALIDATION PASSED; "Required test coverage of 90% reached. Total coverage: 94.72%"; `135 passed in 9.73s`
- **Test count:** 135 (up from 50 in v0.1.1)
- **Coverage metrics:**

| Module | Statements | Miss | Cover |
| --- | --- | --- | --- |
| doc2md/__init__.py | 4 | 0 | 100% |
| doc2md/cli/main.py | 85 | 1 | 99% |
| doc2md/core/cleaner.py | 71 | 1 | 99% |
| doc2md/core/converter.py | 131 | 1 | 99% |
| doc2md/core/encoding.py | 25 | 0 | 100% |
| doc2md/core/router.py | 131 | 2 | 98% |
| doc2md/engine/code_engine.py | 46 | 0 | 100% |
| doc2md/engine/docx_engine.py | 83 | 7 | 92% |
| doc2md/engine/excel_engine.py | 99 | 6 | 94% |
| doc2md/engine/ocr_engine.py | 53 | 3 | 94% |
| doc2md/engine/pdf_engine.py | 72 | 8 | 89% |
| doc2md/engine/pptx_engine.py | 92 | 13 | 86% |
| doc2md/engine/web_engine.py | 211 | 16 | 92% |
| **TOTAL** | **1156** | **61** | **94.72%** |

- **Newly hardened scenarios:** password-protected PDF (AES-256) and OLE-container DOCX → graceful errors; corrupted OOXML zips; truncated CSV/JSON; >260-char Windows paths incl. `\\?\` fallback; Thai/space paths; concurrent worker temp isolation; child crash (`os._exit`) containment; UTF-8 BOM / CP874 / TIS-620 matrix; PDF OCR fallback success + both failure branches.

## [0.1.1] - 2026-08-26

- **Verification timestamp (UTC+7 local):** 2026-08-26, Gatekeeper Protocol v3.4
- **Gatekeeper:** LocalCore (`C:\Program Files\LocalCore\LocalCore.exe --verify "pytest tests/ --maxfail=1 --timeout=10" --model "Qwen-2.5-Coder-14B"`)
- **Result:** `EXIT_CODE:0` — VALIDATION PASSED, `50 passed in 4.67s`
- **Coverage metrics (pytest-cov):**

| Module | Statements | Miss | Cover |
| --- | --- | --- | --- |
| doc2md/__init__.py | 4 | 0 | 100% |
| doc2md/cli/main.py | 85 | 10 | 88% |
| doc2md/core/cleaner.py | 71 | 1 | 99% |
| doc2md/core/converter.py | 129 | 31 | 76% |
| doc2md/core/encoding.py | 25 | 3 | 88% |
| doc2md/core/router.py | 131 | 17 | 87% |
| doc2md/engine/code_engine.py | 46 | 4 | 91% |
| doc2md/engine/docx_engine.py | 83 | 15 | 82% |
| doc2md/engine/excel_engine.py | 99 | 14 | 86% |
| doc2md/engine/ocr_engine.py | 53 | 23 | 57% |
| doc2md/engine/pdf_engine.py | 45 | 12 | 73% |
| doc2md/engine/pptx_engine.py | 85 | 30 | 65% |
| doc2md/engine/web_engine.py | 211 | 60 | 72% |
| **TOTAL** | **1120** | **231** | **79%** |

- **Resilience scenarios verified by tests:**
 - Corrupted PDFs (garbage bytes and truncated real PDF) → graceful failure, no crash
 - Missing/corrupted encodings (TIS-620/cp874 Thai payloads) → charset_normalizer fallback decodes correctly
 - Large files (20,000-row CSV; 200-row workbook with lowered limits) → Truncated Summary, bounded memory
 - Watchdog timeouts in both thread and spawned-process execution → worker terminated, CLI survives
 - Temp artifact cleanup for OCR intermediates → no leftover `doc2md_ocr_*` directories

## [0.1.0] - 2026-08-26

- Initial implementation of all modules (router, engines, cleaner, converter, CLI).
- Local test suite established: 50 tests covering routing, cleaning, engines, resilience, CLI, and version sync.
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
