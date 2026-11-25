"""Declared directory lookup, never a target-package import."""
from .comparison import compare_routes
from .core import trace_imports

__all__ = ["trace_imports", "compare_routes"]
