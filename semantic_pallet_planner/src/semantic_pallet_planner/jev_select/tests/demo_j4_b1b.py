"""Reproducible B1-B engineering evidence, all nonempty memory fixture_only.

PYTHONPATH=src python -m semantic_pallet_planner.jev_select.tests.demo_j4_b1b --output outputs/<new-id>
Excluded from the production wheel with tests/. Does not call models or read keys.
"""
import argparse
import subprocess
import sys
from pathlib import Path
from .integration.test_j4_b1b import fixture_memory,CHILD
from ..batch_j4 import prepare_j4,preflight_j4,run_j4,REGISTERED_METHODS
from ..diagnostics import inspect_experiment
from ..experiment import _new_output
from ..ledger import read,write


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    root=_new_output(parser.parse_args().output);root.mkdir(parents=True)
    fixture_memory(root/'memory')
    prepare_j4(root/'plan',methods=REGISTERED_METHODS,memory=root/'memory',task_limit=1)
    write(root/'preflight.json',preflight_j4(root/'plan'))
    run=run_j4(root/'plan',root/'run',offline=True)
    inspect_experiment(root/'run',root/'inspect')
    cases=[]
    for method in ('jev_raw_history','jev_memory_cards'):
        for phase in ('after_reserve','after_response','after_commit_checkpoint'):
            case=root/'recovery'/f'{method}_{phase}';case.mkdir(parents=True)
            prepare_j4(case/'plan',methods=[method],memory=root/'memory',task_limit=1)
            args=[sys.executable,'-c',CHILD,str(case/'plan'),str(case/'run'),str(case/'protocol.json'),phase]
            interrupted=subprocess.run(args,capture_output=True,text=True)
            (case/'interrupted.log').write_text(interrupted.stdout+interrupted.stderr)
            assert interrupted.returncode==75
            write(case/'checkpoint.interrupted.json',read(case/'run/checkpoints/J0000.json'))
            resumed=subprocess.run(args,capture_output=True,text=True)
            (case/'resumed.log').write_text(resumed.stdout+resumed.stderr)
            assert resumed.returncode==0,resumed.stderr
            log=read(case/'protocol.json');attempts=read(case/'run/audit/attempts.json')['attempts']
            assert len(log['queries'])==len(set(log['queries']))
            assert len(log['commits'])==len(set(log['commits']))
            assert len(log['sends'])==(0 if phase=='after_reserve' else len(attempts))
            cases.append({'method':method,'phase':phase,'status':'PASS','attempts':len(attempts),
                'offline_sends':len(log['sends']),'durable_commits':len(log['commits']),
                'queries':len(log['queries']),'unknown_delivery':sum(a['state']=='UNKNOWN_IN_FLIGHT' for a in attempts),
                'saved_query_not_retrieved_again':True,'fixture_only':True})
    report={'status':'PASS','scope':'B1_B_OFFLINE_ENGINEERING','fixture_only':True,
        'five_method_run':run,'recovery_cases':cases,'model_api_calls':0,
        'generation_status':'NOT_RUN','reme_status':'NOT_RUN','benefit_status':'NOT_ESTABLISHED'}
    write(root/'demo_report.json',report);print(report)


if __name__=='__main__':main()
