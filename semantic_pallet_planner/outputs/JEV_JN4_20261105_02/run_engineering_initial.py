"""Persist one CONSTRUCTED source x six methods. Never formal test input."""
from pathlib import Path
import json
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as p
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.ledger import write
from test_packaging_remote import Fake
root=Path(__file__).resolve().parent/'engineering'
task=mechanism_task([item(str(i),size=(20,20,20)) for i in range(3)])
task.update(task_id='CONSTRUCTED_JN4_SIX_METHODS',source_group_id='CONSTRUCTED_JN4_ENGINEERING',partition='train')
plan=p.prepare({'data_identity':digest('CONSTRUCTED_JN4_ENGINEERING_ONLY'),'fixture_only':True,'tasks':[task]},root/'plan')
fake=Fake();summary=p.run_validation(root/'plan',root/'run',transport_factory=lambda *a:fake)
assert summary['categories']['COMPLETE']==6 and fake.calls==12 and summary['actual_model_api_calls']==0
assert p.validate_run(root/'run')['status']=='PASS'
write(root/'receipt.json',{'version':'jev_six_method_engineering_receipt_v1','purpose':'FIXTURE_ENGINEERING',
 'plan_digest':digest(plan),'methods':p.METHODS,'jobs_finished':6,'simulated_transport_calls':fake.calls,
 'actual_model_api_calls':0,'actual_formal_test_jobs_executed':0,'research_benefit':'NOT_ESTABLISHED',
 'local_calls':0,'all_six_execution_version':p.VERSION,'status':'PASS_CONSTRUCTED_FAKE_ONLY'})
print(json.dumps({'status':'PASS_CONSTRUCTED_FAKE_ONLY','jobs':6,'fake_calls':fake.calls,'actual_api_calls':0}))
