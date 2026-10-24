"""User-facing value formatting shared across modules."""

from __future__ import annotations


def format_file_size(size: int) -> str:
    """Compact binary size label (``1.5GB``, ``512B``) used in errors and URLs."""
    for unit, factor in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size >= factor:
            return f"{size / factor:g}{unit}"
    return f"{size}B"
