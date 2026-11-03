"""Standalone static assessment. Importing this package does not load NumPy/PCT."""
from .contracts import BoxInput, PlacedState, StabilityConfig, StabilityResult


def assess_candidate(placed_state, candidate, config=None):
    from .pct_adapter import assess_candidate as assess
    return assess(placed_state, candidate, config)


__all__ = ['BoxInput', 'PlacedState', 'StabilityConfig', 'StabilityResult', 'assess_candidate']
