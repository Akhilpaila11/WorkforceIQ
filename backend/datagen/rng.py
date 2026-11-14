"""Deterministic randomness: one NumPy generator / Faker instance per generation stage.

Each stage is seeded from SHA-256(f"{seed}:{stage}"), so changing one stage never shifts the
random stream of another. Nothing in the generator reads the system clock.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

import numpy as np
from faker import Faker


def stage_seed(seed: int, stage: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{stage}".encode()).digest()[:8], "big")


def stage_rng(seed: int, stage: str) -> np.random.Generator:
    return np.random.default_rng(stage_seed(seed, stage))


def stage_faker(seed: int, stage: str) -> Faker:
    fake = Faker("en_US")
    fake.seed_instance(stage_seed(seed, stage))
    return fake


def pick[T](rng: np.random.Generator, items: Sequence[T], p: Sequence[float] | None = None) -> T:
    """Choose one item (works for any Python objects, unlike ``rng.choice``)."""
    if p is None:
        return items[int(rng.integers(len(items)))]
    weights = np.asarray(p, dtype=float)
    return items[int(rng.choice(len(items), p=weights / weights.sum()))]


def sample[T](rng: np.random.Generator, items: Sequence[T], k: int) -> list[T]:
    """k distinct items in random order (k is capped at len(items))."""
    idx = rng.permutation(len(items))[: min(k, len(items))]
    return [items[int(i)] for i in idx]


def round_half(x: float) -> float:
    """Round to the nearest 0.5 hour (half-up, no banker's rounding)."""
    return math.floor(x * 2 + 0.5) / 2
