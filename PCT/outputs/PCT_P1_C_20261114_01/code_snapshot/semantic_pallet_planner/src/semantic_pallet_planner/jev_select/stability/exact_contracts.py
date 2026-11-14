"""Independent exact-pose geometry revision; v2 numerical constants retained."""
from dataclasses import dataclass, asdict
from .balance_contracts import BalancedConfig
from .contracts import StabilityResult

@dataclass(frozen=True)
class ExactConfig(BalancedConfig):
    algorithm: str = 'pct_exact_pose_network_v3'

    def __post_init__(self):
        expected = asdict(BalancedConfig())
        expected['algorithm'] = 'pct_exact_pose_network_v3'
        if asdict(self) != expected or type(self.setting) is not int or type(self.presolve) is not bool:
            raise ValueError('INVALID_EXACT_CONFIG')

@dataclass(frozen=True)
class ExactResult(StabilityResult):
    version: str = 'pct_stability_result_v3'

def load_config():
    return ExactConfig()
