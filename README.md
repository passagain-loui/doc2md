# README.md

``````````````````````````text
# README.md

`````````````````````````text
# README.md

````````````````````````text
# README.md

```````````````````````text
# README.md

``````````````````````text
# README.md

`````````````````````text
# README.md

````````````````````text
# README.md

```````````````````text
# README.md

``````````````````text
# README.md

`````````````````text
# README.md

````````````````text
# README.md

```````````````text
# README.md

``````````````text
# README.md

`````````````text
# README.md

````````````text
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
# doc2md

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Coverage: 93.58%](https://img.shields.io/badge/coverage-93.58%25-brightgreen.svg)]()

Universal document-to-Markdown converter built for LLM pipelines: token-optimized,
timeout-guarded, and crash-isolated.

## Supported inputs

| Kind | Formats | Engine | Isolation |
| --- | --- | --- | --- |
| PDF | `.pdf` | PyMuPDF | separate process |
| Word | `.docx` | python-docx | thread |
| Excel | `.xlsx`, `.xlsm`, `.csv` | openpyxl / stdlib csv (streaming) | thread |
| PowerPoint | `.pptx` | python-pptx | thread |
| Web | `.html`, `.eml` | BeautifulSoup / email stdlib | thread |
| Images | `.png`, `.jpg`, `.tif`, ... | Pillow + Tesseract OCR | separate process |
| Code/Text | `.json`, `.py`, any text | stdlib | thread |

## Install

### Windows Installer (Recommended)
Download the latest standalone installer from [Releases](https://github.com/yourusername/doc2md/releases):
```
doc2md_Setup_v0.2.1.exe
```

### Python Package
```bash
# Development install with all optional dependencies
pip install -e ".[docs,ocr-rapid,dev]"

# Production install (docs support required)
pip install -e ".[docs]"

# Minimal install (text/JSON only)
pip install doc2md
```

**Optional:** For full OCR support, install the native Tesseract binary:
- Windows: Download from [UB Mannheim/tesseract-ocr](https://github.com/UB-Mannheim/tesseract/wiki)
- Linux: `sudo apt-get install tesseract-ocr`
- macOS: `brew install tesseract`

Or use the bundled `rapidocr-onnxruntime` backend (no native binary needed):
```bash
pip install -e ".[ocr-rapid]"
```

## Usage

### CLI
```bash
# Basic conversion
doc2md convert report.pdf # -> report.md next to source

# With token stats and clipboard
doc2md convert report.pdf -c -s # copy to clipboard + show stats

# Batch processing
doc2md convert docs/ -o out_md/ # batch a whole folder
doc2md convert "*.pptx" --stdout # glob + stdout

# Advanced options
doc2md convert big.xlsx --max-rows 10000 # row guard (Truncated Summary beyond)
doc2md convert scan.pdf --timeout 60 # hard watchdog per file
doc2md convert output.md --chunk 2048 # semantic token splitting (*.part*.md)

# Windows Explorer integration
doc2md install-context-menu # right-click "Convert to Markdown" option
doc2md uninstall-context-menu # remove the context menu entry
doc2md context-menu-status # check if installed
```

### Python API
```python
from doc2md import Converter

# Basic conversion
cv = Converter(timeout=60, options=)
result = cv.convert_file("report.pdf")
print(result.success, result.engine, result.token_estimate)

# Batch conversion with stats
for path in ["file1.pdf", "file2.docx"]:
 result = cv.convert_file(path)
 if result.success:
 print(f": tokens (~ chars)")
```

### Configuration via `doc2md.toml`
Create `doc2md.toml` in your working directory or home directory:
```toml
default_copy = true # auto-copy to clipboard
stats = true # show token stats
chunk = 2048 # semantic splitting
timeout = 60 # per-file timeout
max_rows = 10000 # spreadsheet row limit
ocr_enabled = true # enable OCR backend
```

## Resilience guarantees

- **Encoding safety:** strict UTF-8 first, `charset_normalizer` fallback (tested with TIS-620/Thai payloads).
- **Watchdog:** every conversion runs under a hard deadline; hung workers are `terminate()`d/killed.
- **Process isolation:** PDF and OCR engines run in spawned worker processes so native segfaults never take down the CLI.
- **Memory guard:** spreadsheets over `--max-rows` switch to a streamed *Truncated Summary* instead of loading fully.
- **Cleanup:** all intermediate artifacts live in `tempfile.TemporaryDirectory()` contexts.

## Development

```bash
pytest tests/ --maxfail=1 --timeout=10
```

Versioning follows SemVer 2.0.0; see `CHANGELOG.md` and `HISTORY.md`.
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
