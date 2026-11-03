"""Package this partial JN0 delivery; never invokes an order or model."""
from pathlib import Path
import hashlib
import xml.etree.ElementTree as ET
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.packaging_runtime import physical_manifest
from semantic_pallet_planner.jev_select.stability.monitor import freeze

root=Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_01')
report='docs/03_阶段产出分析/Jev/Jev_JN0完整订单入口与本地基线开发验收_20261103.md'
tests={}
for name in ('development_tests_01','development_tests_02','final_tests','revision_tests','repair_tests'):
    suite=ET.parse(root/f'{name}.xml').getroot().find('testsuite')
    tests[name]={k:suite.get(k) for k in ('tests','failures','errors','skipped','time')}
write(root/'test_receipts.json',tests)
status={'N01':{'status':'PASS','evidence':['baseline_verification.json','plan_revision_02/task_inventory.json'],
    'gap':None},
    'N02':{'status':'PARTIAL','evidence':['repair_tests.xml','run/jobs/J0000/checkpoint.json','run_command.log'],
    'gap':'Original formal job reached natural empty pool but reporting raised; repaired identity has zero formal orders.'},
    'N03':{'status':'PARTIAL','evidence':['final_tests.xml','repair_tests.xml','diagnostics/verification.json','diagnostics/job_ledger.json'],
    'gap':'Constructed mechanisms pass; original batch canonical finalization aborted. Supplemental saved-record audit does not replace it.'},
    'N04':{'status':'PARTIAL','evidence':['diagnostics/J0000/metrics.json','diagnostics/paired_differences.json','repair/revision_receipt.json'],
    'gap':'One actual job; paired local results and repaired formal end-to-end closure NOT_RUN.'}}
plan=read(root/'plan_revision_02/plan.json');summary=read(root/'diagnostics/summary.json')
write(root/'engineering_acceptance.json',{'version':'jev_jn0_engineering_acceptance_v1','status':'PARTIAL',
    'criteria':status,'tests':tests,'local_mechanism_status':'PASS_IN_CONSTRUCTED_SCOPE',
    'formal_batch_status':'ERROR_1_NOT_RUN_7','saved_evidence_status':'PASS_UNDER_SEPARATE_REPAIR_DERIVATION_IDENTITY',
    'research_benefit':'NOT_ESTABLISHED'})
write(root/'full_order_readiness.json',{'version':'jev_jn0_full_order_readiness_v1','status':'NOT_READY','criteria':status,
    'JN1_admitted':False,'data_identity':plan['data_identity'], 'planned_jobs':8,'actual_jobs':1,'not_run_jobs':7,
    'original_job_category':'ERROR','saved_natural_checkpoint_reason':'STOP_NO_PHYSICAL_CANDIDATE',
    'formal_repaired_identity_jobs':0,'full_order_replays':0,'model_calls':0,'fees_usd':0,
    'critical_issues':[{'issue':'Null monitor in unselected event broke legacy first-instability statistics',
        'code_fix':'IMPLEMENTED','constructed_verification':'PASS','formal_repaired_matrix':'NOT_RUN'},
        {'issue':'Original standard batch aggregate/receipt finalization aborted','state':'UNRESOLVED_FOR_ORIGINAL_FROZEN_BATCH'},
        {'issue':'No two-method completed pair','state':'NOT_RUN'}],
    'not_run':['seven preregistered jobs','repaired formal matrix','real Jev API','nonempty memory','training forks','unseen-source validation','historical full replay'],
    'interfaces':{'plan':plan['version'],'run':'jev_packaging_full_order_run_v1','execution':plan['execution_version'],
        'selector_factory':'semantic_pallet_planner.jev_select.packaging_protocol.selector_factory',
        'registry':'semantic_pallet_planner.jev_select.packaging_protocol.METHOD_REGISTRY',
        'metrics':'jev_packaging_full_order_metrics_v1'},
    'evidence':['runtime_failure_receipt.json','diagnostics/verification.json','diagnostics/job_ledger.json','repair_tests.xml'],
    'next_gate':'Separately determine revised-identity bounded continuation and failed-job disposition; preserve original failure and explicit total budget.'})
write(root/'identity_components.json',{'original_plan_digest':digest(plan),
    'original_source_digest':digest(plan['source_manifest']),'repair_source_digest':digest(source_manifest()),
    'data_identity':plan['data_identity'],'physical_manifest':physical_manifest(),'monitor':freeze(True),
    'original_configs':'plan_revision_02/plan.json#/jobs/*/config','repair_formal_orders':0})
write(root/'revision_history.json',[
    {'revision':'initial plan','path':'plan','state':'CLI_RECEIPT_RETURN_ERROR_NO_ORDERS'},
    {'revision':'02','path':'plan_revision_02','state':'ONE_JOB_REPORTING_ERROR_SEVEN_NOT_RUN'},
    {'revision':'repair','path':'repair','state':'NULL_GUARD_FIXED_CONSTRUCTED_TESTS_ONLY_ZERO_FORMAL_ORDERS'}])
base='PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=semantic_pallet_planner/src python -m pytest -q '
new='semantic_pallet_planner/tests/unit/test_packaging_full_order.py '
legacy=['semantic_pallet_planner/tests/unit/test_stability_kernel.py','semantic_pallet_planner/tests/unit/test_stability_balance.py','semantic_pallet_planner/tests/unit/test_stability_monitor.py','semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_packaging_runtime.py','semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_j3_core.py','semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_j4_memory.py']
prefix=root.as_posix();cli='PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.jev_select '
write(root/'commands.json',{'cwd':'NBU_Papper','commands':[
    {'purpose':'pre-repair joint validation','command':base+new+' '.join(legacy)+' --junitxml='+prefix+'/final_tests.xml','result':'195 passed'},
    {'purpose':'CLI receipt revision','command':base+new+'--junitxml='+prefix+'/revision_tests.xml','result':'17 passed'},
    {'purpose':'null monitor repair validation','command':base+new+' '.join(legacy[2:4])+' --junitxml='+prefix+'/repair_tests.xml','result':'64 passed'},
    {'purpose':'initial plan; no orders','command':cli+'plan-packaging-orders --dataset semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02 --output '+prefix+'/plan','result':'CLI KeyError after writing plan'},
    {'purpose':'freeze revision 02','command':cli+'plan-packaging-orders --dataset semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02 --output '+prefix+'/plan_revision_02','result':'PASS'},
    {'purpose':'bounded formal batch','command':cli+'run-packaging-orders --plan '+prefix+'/plan_revision_02 --output '+prefix+'/run','result':'exit 1; original first job ERROR; remaining seven NOT_RUN'},
    {'purpose':'independent saved audit; zero orders','command':'PYTHONPATH=semantic_pallet_planner/src python '+prefix+'/audit_saved_failure.py','result':'PASS'},
    {'purpose':'package partial delivery','command':'PYTHONPATH=semantic_pallet_planner/src python '+prefix+'/finalize_delivery.py','result':'delivery records only'}],
    'warning':'Historical commands use existing frozen output paths. Do not rerun/overwrite them; source changes must reject old identity.'})
write(root/'handoff.json',{'version':'jev_jn0_handoff_v1','status':'PARTIAL','report':report,
    'report_sha256':hashlib.sha256(Path(report).read_bytes()).hexdigest(),'acceptance':'engineering_acceptance.json',
    'readiness':'full_order_readiness.json','original_frozen_plan':'plan_revision_02/plan.json',
    'original_failed_run':'run','derived_diagnostics':'diagnostics','repair_identity':'repair/revision_receipt.json',
    'source_changes_since_original':['jev_select/stability/metrics.py'],'actual_coverage':summary,
    'JN1_admitted':False,'preserved':'Original plans, configuration, checkpoints, selections, monitor results and error status not re-signed.',
    'git_policy':'New output follows existing ignore rules; no archive exception, commit or push.',
    'stop':'JN0 partial delivery; no further orders or next stage authorized by this receipt.'})
# Hash nested manifests too; exclude only this root manifest itself.
manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(root.rglob('*')) if p.is_file() and p!=root/'delivery_manifest.json'}
write(root/'delivery_manifest.json',{'version':'jev_jn0_delivery_manifest_v1','files_sha256':manifest})
print('packaged PARTIAL delivery:',len(manifest),'files; JN1 NOT_READY')
