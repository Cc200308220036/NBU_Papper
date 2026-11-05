from pathlib import Path
import pytest
from semantic_pallet_planner.o4.common import read,write
from semantic_pallet_planner.runners.o4_buffer import run,recompute,resume,config


def test_f_runner_matrix_smoke_repeat_resume_and_tamper(tmp_path):
    root=tmp_path/'smoke';result=run(root,limit=1,workers=1)
    assert result['status']=='PARTIAL' and result['logical_episodes']==5
    assert all(v for k,v in result['criteria'].items() if k!='F3')
    assert recompute(root,rerun=True)['status']=='PASS'
    assert all(x['detected'] for x in read(root/'audit/tamper.json'))
    cp=next((root/'checkpoints/buffer_search__oracle_ast').glob('*.json'))
    resumed=resume(cp,tmp_path/'resumed')
    assert resumed['status']=='PASS'
    with pytest.raises(FileExistsError):run(root,limit=1)


def test_f_config_cannot_silently_expand_budget(tmp_path):
    import yaml
    cfg=config();cfg['max_successor_evaluations']=512;p=tmp_path/'bad.yaml';p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError):config(p)
