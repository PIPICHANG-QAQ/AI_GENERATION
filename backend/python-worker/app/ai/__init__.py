"""AI runtime modules.

The package is intentionally small at this stage.  ``runtime`` is the stable
home for the shared LLM configuration and routing surface while the legacy
``app.llm_splitter`` module remains the implementation façade.  Keeping the
package boundary additive lets callers migrate imports without changing the
OCR-Flow execution path.
"""

from . import runtime

__all__ = ["runtime"]
