import copy
import json
from pathlib import Path
import pytest
from semantic_pallet_planner.o4.common import read,write
from semantic_pallet_planner.o4.fixtures import fixture_request,item,policy,CONTAINER
from semantic_pallet_planner.runners.o4_visual import run,verify_delivery


def test_actual_render_and_read_only_independent_replay(tmp_path):
    source=fixture_request([item('base',category='food')],item('pending',no_top=True),policy([]))
    root=tmp_path/'render';result=run(root,source=source)
    assert result['status']=='PARTIAL' and result['image_consistency']['status']=='PASS'
    assert result['real_api_calls']==0
    before={str(f.relative_to(root)):f.read_bytes() for f in root.rglob('*') if f.is_file()}
    assert verify_delivery(root,repeat=True)['status']=='PASS'
    assert before=={str(f.relative_to(root)):f.read_bytes() for f in root.rglob('*') if f.is_file()}
    assert all(r['detected'] for r in read(root/'audit/tamper.json'))
    with pytest.raises(FileExistsError):run(root,source=source)
    asset=next((root/'public/assets').glob('*.png'));asset.write_bytes(b'tamper')
    assert verify_delivery(root)['status']=='FAIL'
