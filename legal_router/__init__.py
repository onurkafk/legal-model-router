"""Legal Model Router. See legal_router.core for the three calls."""
from .core import CLASSIFIERS, MODELS, Route, RouterError, Work, classify, complete, route

__all__ = ["CLASSIFIERS", "MODELS", "Route", "RouterError", "Work", "classify", "complete", "route"]
