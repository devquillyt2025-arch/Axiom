from __future__ import annotations

from typing import Any

from bot.strategy import Strategy

REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    if not cls.key:
        raise ValueError(f"{cls.__name__} must define a non-empty `key`")
    if cls.key in REGISTRY and REGISTRY[cls.key] is not cls:
        raise ValueError(f"Duplicate strategy key '{cls.key}'")
    REGISTRY[cls.key] = cls
    return cls


def get_strategy(key: str, **params: Any) -> Strategy:
    try:
        cls = REGISTRY[key]
    except KeyError:
        raise ValueError(f"Unknown strategy '{key}'. Available: {', '.join(REGISTRY)}") from None
    return cls(**params)


def list_strategies() -> list[dict]:
    return [cls.describe() for cls in REGISTRY.values()]
