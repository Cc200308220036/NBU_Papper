"""Fresh-process replay of exactly one saved public input; no order replay."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import torch
from pct_baseline.contracts import sha
from pct_baseline.geo_model import load_model
from pct_baseline.geo_selector import PCTGeoSelector
from semantic_pallet_planner.jev_select.contracts import DecisionContext


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--evidence',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    def forbidden(*a,**k):raise AssertionError('P2B_FORBIDDEN_NETWORK')
    socket.socket.connect=forbidden;socket.socket.connect_ex=forbidden
    # Profile guards trigger before a forbidden business function executes.
    def guard(frame,event,arg):
        if event=='call':
            module=frame.f_globals.get('__name__','');name=frame.f_code.co_name
            if (name in ('credential','run_episode','monitor_selected_action','commit_physical','linprog') or
                (name in ('build','generate') and module in ('semantic_pallet_planner.jev_select.candidates','semantic_pallet_planner.o4.extensions.e2.candidates'))):
                raise AssertionError('P2B_FORBIDDEN_ENTRY '+module+'.'+name)
        return guard
    sys.setprofile(guard)
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    v=json.loads((args.evidence/'public_context_builder.json').read_text())
    weights=Path('PCT/outputs/PCT_P2_A_20261114_01/weight_tensors.json')
    model=load_model(args.evidence/'model_manifest.json',weights,expected_manifest_sha256=sha(args.evidence/'model_manifest.json'))
    selector=PCTGeoSelector(v['config'],model);ctx=DecisionContext.from_dict(v['context'])
    selector.bind_candidates(ctx,v['bundle']['physical_candidates'])
    selector.select(ctx,decision_id=ctx.data['local_binding']['decision_id'])
    record=selector.last_record;old=v['record']
    for field in ['encoding','output','selected_mapping','exact_candidate','context_digest','model_manifest_sha256','weights_sha256']:
        assert record[field]==old[field],field
    assert model.calls==1
    result={'pid':os.getpid(),'matches_saved_single_step':True,'model_calls':model.calls,'record':record,'forbidden_calls':[]}
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'pid':os.getpid(),'matches_saved_single_step':True,'model_calls':1}))


if __name__=='__main__':main()
