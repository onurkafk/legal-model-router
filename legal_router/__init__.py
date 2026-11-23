"""Legal Model Router. See legal_router.core for the three calls."""
from .core import MODELS, Route, RouterError, Work, classify, complete, route

__all__ = ["MODELS", "Route", "RouterError", "Work", "classify", "complete", "route"]
