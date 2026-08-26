"""Shared exception hierarchy for doc2md."""


class ConversionError(Exception):
    """Raised when a document cannot be converted."""


class ConversionTimeoutError(ConversionError):
    """Raised when conversion exceeds the configured hard timeout."""


class EngineUnavailableError(ConversionError):
    """Raised when the optional backend library for an engine is missing."""
