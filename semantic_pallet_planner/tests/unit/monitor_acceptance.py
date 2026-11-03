"""Export constructed P2 integration evidence; never runs source orders."""
from dataclasses import replace
from pathlib import Path
import argparse
import copy
import json
import pytest
from test_stability_monitor import mechanism_task,item,config,run,fixture_provider,unstable_task
from semantic_pallet_planner.jev_select.ledger import write
from semantic_pallet_planner.jev_select.stability.monitor import validate_checkpoint
from semantic_pallet_planner.jev_select.stability.runtime import environment
from semantic_pallet_planner.jev_select.stability import balance_adapter as ba


def export(root):
    root.mkdir(parents=True,exist_ok=False)
    write(root/'environment.json',environment())
    task=mechanism_task([item('a')]);cfg=config(task)
    write(root/'config.json',cfg)
    write(root/'stable.json',dict(origin='CONSTRUCTED_NOT_ORDER',task=task,config=cfg,episode=run(task,cfg)))
    with pytest.MonkeyPatch.context() as mp:
        fixture_provider(mp);t=unstable_task();c=config(t);e=run(t,c)
        validate_checkpoint(e['checkpoint'],t,c,'P',c['selector'])
        write(root/'ancestor_stop.json',dict(origin='CONSTRUCTED_ORACLE_ADMISSIBLE_POOL_NOT_ORDER',
            basis='base contact [-70,70]; shelf self1kg at x30, top100kg at x100; combined x=10030/101>70; 70% original shelf support retained',task=t,config=c,episode=e))
    for status in ('UNASSESSABLE','ERROR'):
        with pytest.MonkeyPatch.context() as mp:
            actual=ba.assess_candidate
            def fault(*a,**kw):return replace(actual(*a,**kw),status=status,reason_code='EXPLICIT_TEST_FAULT')
            mp.setattr(ba,'assess_candidate',fault)
            e=run(task,cfg)
            write(root/(status.lower()+'_injected.json'),dict(origin='EXPLICIT_FAULT_INJECTION_NOT_PHYSICS',episode=e))
    for phase,hookname in [('SELECTED','after_selected_checkpoint'),('MONITORED','after_monitored_checkpoint'),('COMMITTED','after_commit_checkpoint')]:
        saved=[]
        class Cut(RuntimeError):pass
        def hook(name,cp):
            if name==hookname:saved.append(copy.deepcopy(cp));raise Cut()
        try:run(task,cfg,hook=hook)
        except Cut:pass
        cp=saved[0];validate_checkpoint(cp,task,cfg,'P',cfg['selector'])
        restored=run(task,cfg,resume=cp)
        assert restored['final_state']['placed_count']==1
        write(root/('recovery_'+phase+'.json'),dict(origin='CONSTRUCTED_RECOVERY_ONLY',checkpoint=cp,resumed=restored))
    print(json.dumps({'constructed_evidence':str(root),'physical_stop':'PREDICTED_STATIC_INSTABILITY'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    export(parser.parse_args().output)
