"""Cross-Python replay comparison; only finite floats have absolute tolerance.

This is not policy/geometry tolerance. Bindings, types, counts and N/A are exact.
"""
import math

REPLAY_ABS_TOL = 1e-9
REPLAY_COMPARISON_VERSION = 'finite_float_abs_1e-9_v1'


def replay_values_equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(replay_values_equal(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(replay_values_equal(a, b) for a, b in zip(actual, expected))
    if isinstance(actual, float):
        return math.isfinite(actual) and math.isfinite(expected) and abs(actual-expected) <= REPLAY_ABS_TOL
    return actual == expected
