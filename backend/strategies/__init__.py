"""Strategy registry. Every non-underscore module in this package is imported on load, so a new
strategy file only needs `@register` on its class — nothing else to wire up."""
import importlib
import pkgutil

from .registry import REGISTRY, get_strategy, list_strategies, register

for _m in pkgutil.iter_modules(__path__):
    if not _m.name.startswith("_") and _m.name != "registry":
        importlib.import_module(f"{__name__}.{_m.name}")

__all__ = ["REGISTRY", "get_strategy", "list_strategies", "register"]
