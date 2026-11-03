"""Versioned configuration and results for the project P1.1 semantic revision."""
from dataclasses import asdict, dataclass
from .contracts import StabilityResult


@dataclass(frozen=True)
class BalancedConfig:
    algorithm: str = 'pct_contact_network_v2'
    setting: int = 1
    height_tolerance_mm: float = 1e-6
    mass_atol_kg: float = 1e-9
    mass_rtol: float = 1e-9
    moment_atol_kg_mm: float = 1e-6
    moment_rtol: float = 1e-9
    solver_tolerance: float = 1e-10
    scaled_residual_tolerance: float = 1e-9
    strict_interior_slack: float = 1e-10
    certificate_gap: float = 1e-8
    presolve: bool = False
    solver: str = 'highs-ds'
    selection: str = 'max_network_interior_then_lexicographic_forces'

    def __post_init__(self):
        expected = dict(algorithm='pct_contact_network_v2', setting=1,
            height_tolerance_mm=1e-6, mass_atol_kg=1e-9, mass_rtol=1e-9,
            moment_atol_kg_mm=1e-6, moment_rtol=1e-9, solver_tolerance=1e-10,
            scaled_residual_tolerance=1e-9, strict_interior_slack=1e-10,
            certificate_gap=1e-8, presolve=False, solver='highs-ds',
            selection='max_network_interior_then_lexicographic_forces')
        if asdict(self) != expected or type(self.setting) is not int or type(self.presolve) is not bool:
            raise ValueError('INVALID_BALANCED_CONFIG: v2 assumptions are frozen')


@dataclass(frozen=True)
class BalancedResult(StabilityResult):
    version: str = 'pct_stability_result_v2'


def load_config():
    """Load and validate the package-local frozen v2 numerical configuration."""
    from importlib.resources import files
    import json
    resource = files(__package__).joinpath('configs/pct_contact_network_v2.json')
    return BalancedConfig(**json.loads(resource.read_text(encoding='utf-8')))
