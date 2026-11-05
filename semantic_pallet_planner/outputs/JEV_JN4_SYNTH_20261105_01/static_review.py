"""Static reconstruction/tamper verification; formal dispatch is patched closed."""
import contextlib
import copy
import json
from pathlib import Path
import shutil
import socket
import tempfile
from unittest.mock import patch
from semantic_pallet_planner.jev_select import packaging_synthetic_data as data
from semantic_pallet_planner.jev_select import packaging_synthetic_orders as plans
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as orders
from semantic_pallet_planner.jev_select import packaging_evaluation_memory as memory
from semantic_pallet_planner.jev_select import episode,execution,transport
from semantic_pallet_planner.jev_select.candidates import CandidateProvider
from semantic_pallet_planner.jev_select.stability import balance_adapter
from semantic_pallet_planner.jev_select.contracts import JevSelectError,digest
from semantic_pallet_planner.jev_select.experiment import file_manifest
from semantic_pallet_planner.jev_select.ledger import read,write

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]

def forbidden(*a,**k):raise AssertionError('formal static audit dispatched runtime/network/credentials')


def main():
    with contextlib.ExitStack() as stack:
        for obj,name in [(socket.socket,'connect'),(transport,'credential'),(CandidateProvider,'build'),
                         (memory.MemoryDriver,'resolve'),(episode,'run_episode'),(execution,'commit_physical'),
                         (balance_adapter,'assess_candidate'),(orders.common,'_run_job')]:
            stack.enter_context(patch.object(obj,name,forbidden))
        loaded=data.load_dataset(HERE/'data',repo=REPO)
        p=plans.validate_plan(HERE/'plan_final')
        assert len(loaded['tasks'])==6 and sum(len(t['items']) for t in loaded['tasks'])==164
        assert len(p['jobs'])==36 and p['request_budget']['global']==656
        assert all(j['config']['evaluation_purpose']==plans.PURPOSE for j in p['jobs'])
        assert all(j['config']['source_relation_digest']==digest(loaded['relations'][j['task_id']]) for j in p['jobs'])
        try:orders.run_validation(HERE/'plan_final',HERE/'run',transport_factory=forbidden)
        except JevSelectError as e:assert 'FORMAL_TEST_EXECUTION_FORBIDDEN' in str(e)
        else:raise AssertionError('formal run accepted')
        assert not (HERE/'run').exists()
        attacks=[]
        for kind in ('task_physics','task_file_only','relation_exclusion','history_mapping'):
            with tempfile.TemporaryDirectory(prefix='jev-synthetic-static-') as temp:
                out=Path(temp)/'data';shutil.copytree(HERE/'data',out)
                d=read(out/'dataset.json')
                if kind=='task_physics':
                    d['tasks'][0]['items'][0]['mass_kg']+=1
                    write(out/'tasks/SYN_COMBO_01.json',d['tasks'][0])
                elif kind=='task_file_only':
                    t=read(out/'tasks/SYN_COMBO_01.json');t['items'][0]['mass_kg']+=1
                    write(out/'tasks/SYN_COMBO_01.json',t)
                elif kind=='relation_exclusion':
                    d['relations']['SYN_COMBO_01']['order_related_source_groups']=['SG_FABRICATED']
                    write(out/'relations.json',d['relations'])
                else:
                    h=read(out/'historical_inputs.json');h['group_to_forks']={}
                    write(out/'historical_inputs.json',h);d['historical_inputs_digest']=digest(h)
                d['data_identity']=digest({k:v for k,v in d.items() if k!='data_identity'})
                write(out/'dataset.json',d);write(out/'delivery_manifest.json',file_manifest(out))
                try:data.load_dataset(out,repo=REPO)
                except JevSelectError as e:attacks.append({'case':kind,'rejected':True,'reason':str(e)})
                else:raise AssertionError('resealed tamper accepted: '+kind)
        # Plan resealing cannot change order/fork exclusion or budget either.
        with tempfile.TemporaryDirectory(prefix='jev-synthetic-plan-') as temp:
            out=Path(temp)/'plan';shutil.copytree(HERE/'plan_final',out);bad=read(out/'plan.json')
            bad['jobs'][4]['config']['excluded_fork_digests']=['a'*64]
            write(out/'plan.json',bad);write(out/'plan_receipt.json',{'plan_digest':digest(bad)})
            write(out/'delivery_manifest.json',file_manifest(out))
            try:plans.validate_plan(out)
            except JevSelectError as e:attacks.append({'case':'plan_fork_exclusion','rejected':True,'reason':str(e)})
            else:raise AssertionError('plan exclusion reseal accepted')
    result={'status':'PASS_STATIC_ONLY','task_count':6,'box_count':164,'job_slots':36,'future_shared_send_cap':656,
            'formal_model_api_calls':0,'formal_jobs_executed':0,'formal_retrievals':0,'formal_candidates_or_monitor_dispatch':0,
            'formal_execution_rejected':True,'tamper_rejections':attacks,'actual_injection_gate':'NOT_RUN',
            'scope':'full raw/pool/attributes/history/order/fork reconstruction and plan validation; no runtime dispatch'}
    write(HERE/'static_validation.json',result)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
