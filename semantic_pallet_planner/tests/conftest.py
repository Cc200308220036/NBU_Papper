from pathlib import Path
import pytest
from semantic_pallet_planner.config import load_config,generator_config
from semantic_pallet_planner.repository import DatasetRepository
from semantic_pallet_planner.planner.generator import ExtremePointGenerator

@pytest.fixture
def cfg(tmp_path):return load_config(output_root=str(tmp_path/'outputs'))
@pytest.fixture
def repo(cfg):return DatasetRepository(cfg['dataset'])
@pytest.fixture
def generator(cfg):return ExtremePointGenerator(generator_config(cfg))
