import copy
import json
from pathlib import Path
import yaml
from .validation import validate

WORKSPACE=Path(__file__).resolve().parents[3]
DEFAULTS=dict(dataset='semantic_pallet_dataset_v1',seed=20260912,top_k=16,topk_mode='diverse_v1',
              fallback_policy='geometry_greedy',output_root='semantic_pallet_planner/outputs',max_steps=None,render=False)

def load_config(path=None, **overrides):
    cfg=copy.deepcopy(DEFAULTS)
    if path:
        data=yaml.safe_load(Path(path).read_text())
        if not isinstance(data,dict): raise ValueError('configuration must be a mapping')
        cfg.update(data)
    cfg.update({k:v for k,v in overrides.items() if v is not None})
    for key in ('dataset','output_root'):
        value=Path(cfg[key]).expanduser()
        cfg[key]=str((value if value.is_absolute() else WORKSPACE/value).resolve())
    validate('config',cfg)
    return cfg

def generator_config(cfg):
    base=json.loads((Path(cfg['dataset'])/'configs/mvd_v0.1.json').read_text())
    base['candidate_generator']['top_k']=cfg['top_k']
    base['topk_mode']=cfg['topk_mode']
    return base
