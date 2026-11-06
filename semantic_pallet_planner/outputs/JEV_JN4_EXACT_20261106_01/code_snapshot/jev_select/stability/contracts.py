"""Independent PCT v1 value contracts. Units: mm, kg, uniform rigid cuboids."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Literal


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def finite(values):
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in values)


@dataclass(frozen=True)
class BoxInput:
    item_id: str
    dimensions_mm: tuple[float, float, float]  # unrotated x, y, z
    mass_kg: float
    bottom_center_mm: tuple[float, float, float]
    yaw_deg: int = 0

    def validate(self):
        if not isinstance(self.item_id, str) or not self.item_id:
            raise ValueError('INVALID_ITEM_ID')
        if len(self.dimensions_mm) != 3 or len(self.bottom_center_mm) != 3:
            raise ValueError('INVALID_GEOMETRY')
        if not finite((*self.dimensions_mm, *self.bottom_center_mm, self.mass_kg)):
            raise ValueError('NONFINITE_OR_NONNUMERIC_INPUT')
        if min(self.dimensions_mm) <= 0 or self.mass_kg <= 0:
            raise ValueError('NONPOSITIVE_SIZE_OR_MASS')
        if isinstance(self.yaw_deg, bool) or self.yaw_deg not in (0, 90):
            raise ValueError('UNSUPPORTED_ORIENTATION')

    @property
    def size_mm(self):
        x, y, z = self.dimensions_mm
        return (x, y, z) if self.yaw_deg == 0 else (y, x, z)


@dataclass(frozen=True)
class PlacedState:
    container_mm: tuple[float, float, float]  # length x, width y, height z
    placed: tuple[BoxInput, ...] = ()  # actual commit order, never sorted

    def validate(self):
        if len(self.container_mm) != 3 or not finite(self.container_mm) or min(self.container_mm) <= 0:
            raise ValueError('INVALID_CONTAINER')
        for box in self.placed:
            box.validate()
        if len({b.item_id for b in self.placed}) != len(self.placed):
            raise ValueError('DUPLICATE_ITEM_ID')


@dataclass(frozen=True)
class StabilityConfig:
    algorithm: str = 'pct_static_v1'
    setting: int = 1
    height_tolerance_mm: float = 1e-6
    mass_atol_kg: float = 1e-9
    mass_rtol: float = 1e-9

    def __post_init__(self):
        # Numeric assumptions are frozen for v1, not tuneable until a new identity.
        if asdict(self) != dict(algorithm='pct_static_v1', setting=1,
                               height_tolerance_mm=1e-6, mass_atol_kg=1e-9, mass_rtol=1e-9) or type(self.setting) is not int:
            raise ValueError('INVALID_PCT_CONFIG: v1 requires setting=1 and frozen tolerances')


@dataclass(frozen=True)
class StabilityResult:
    status: Literal['STABLE', 'UNSTABLE', 'UNASSESSABLE', 'ERROR']
    reason_code: str
    state_digest: str | None
    candidate_digest: str | None
    candidate_id: str | None
    config_digest: str
    algorithm_identity: dict
    baseline_status: str
    first_bad_prefix: str | None
    failed_item_id: str | None
    height_delta_mm: float | None
    evaluated_pose: dict | None
    kernel_calls: int
    diagnostics: dict = field(default_factory=dict)
    duration_s: float = 0.0
    version: str = 'pct_stability_result_v1'

    def to_dict(self):
        return asdict(self)
