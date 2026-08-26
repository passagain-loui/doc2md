# __init__.py

```python
"""doc2md: universal document to Markdown converter."""

from doc2md.core.converter import Converter, ConversionResult
from doc2md.core.errors import (
    ConversionError,
    ConversionTimeoutError,
    EngineUnavailableError,
)

__version__ = "0.3.0"

__all__ = [
    "Converter",
    "ConversionResult",
    "ConversionError",
    "ConversionTimeoutError",
    "EngineUnavailableError",
    "__version__",
]
```
