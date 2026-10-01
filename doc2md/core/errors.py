"""Shared exception hierarchy for doc2md."""


class ConversionError(Exception):
    """Raised when a document cannot be converted."""


class ConversionTimeoutError(ConversionError):
    """Raised when conversion exceeds the configured hard timeout."""


class EngineUnavailableError(ConversionError):
    """Raised when the optional backend library for an engine is missing."""


# --- non-fatal warnings on otherwise-successful conversions ------------------
#
# An engine can produce usable Markdown (metadata, page structure) while
# still needing to tell the caller "this isn't a real result": OCR was
# unavailable, OCR was switched off, or OCR ran but found no text. That is
# neither an exception (there IS output) nor a plain success (the output
# does not represent the document's actual text). Since OCR/PDF engines run
# in an isolated worker process, the warning has to travel back to the
# parent through the same string returned over the pipe - so it is embedded
# with a marker no real document content would ever contain, and stripped by
# Converter.convert_file() before the caller sees the markdown.
WARNING_MARK = "\x00DOC2MD-WARNING\x00"


def wrap_warning(markdown: str, warning: str) -> str:
    """Prefix *markdown* with *warning* so it survives a process boundary."""
    safe_warning = warning.replace("\x00", " ").replace("\n", " ").strip()
    return f"{WARNING_MARK}{safe_warning}{WARNING_MARK}{markdown}"


def split_warning(raw: str) -> tuple[str | None, str]:
    """Inverse of :func:`wrap_warning`. Returns ``(warning, markdown)``."""
    if raw.startswith(WARNING_MARK):
        rest = raw[len(WARNING_MARK):]
        warning, sep, markdown = rest.partition(WARNING_MARK)
        if sep:
            return warning, markdown
    return None, raw
