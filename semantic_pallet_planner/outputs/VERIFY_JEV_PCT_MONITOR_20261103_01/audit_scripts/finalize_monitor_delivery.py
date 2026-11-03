from pathlib import Path
import json,hashlib,shutil,subprocess,re
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.experiment import source_manifest,file_manifest
repo=Path('/home/cyw/NBU_Papper');root=repo/'semantic_pallet_planner/outputs/VERIFY_JEV_PCT_MONITOR_20261103_01'
report=repo/'docs/03_阶段产出分析/O4/Jev_J4_PCT选后监测与持久化恢复验收_20261103.md'
text=report.read_text();rows=[]
for line in text.splitlines():
 if re.match(r'\| S\d\d \|',line):
  fields=[v.strip() for v in line.strip('|').split('|')]
  rows.append(dict(id=fields[0],verification_kind=fields[1],evidence=fields[2]))
assert len(rows)==30
identity=read(root/'smoke_on/jobs/P00/config.snapshot.json')['stability_monitor']
write(root/'identity.json',identity);write(root/'environment.json',read(root/'smoke_on/environment.json'))
source=source_manifest();assert source==read(root/'smoke_on/source_manifest.json')==read(root/'smoke_off/source_manifest.json')
write(root/'source_manifest.json',source)
package=repo/'semantic_pallet_planner/src/semantic_pallet_planner'
for name in source:
 target=root/'code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(package/name,target)
for name in ['README.md','stability/README.md']:
 target=root/'documentation'/name;target.parent.mkdir(parents=True,exist_ok=True)
 shutil.copy2(package/'jev_select'/name,target)
shutil.copy2(report,root/'documentation'/report.name)
for filename in ['test_stability_monitor.py','monitor_acceptance.py','test_stability_kernel.py','test_stability_balance.py','pct_ls_reproducer.py']:
 target=root/'test_snapshot'/filename;target.parent.mkdir(parents=True,exist_ok=True)
 shutil.copy2(repo/'semantic_pallet_planner/tests/unit'/filename,target)
for script in ['/tmp/audit_p1_monitor.py','/tmp/verify_monitor_delivery.py','/tmp/protect_monitor.py','/tmp/check_protect_monitor.py','/tmp/finalize_monitor_delivery.py']:
 target=root/'audit_scripts'/Path(script).name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(script,target)
acceptance=dict(engineering_status='PASS_IN_DECLARED_SCOPE',
 monitor_integration_status='PASS_SELECTED_ACTION_V2',
 record_coverage_status='COMPLETE_FOR_NEW_SELECTED_PREFIX_ACTIONS_HISTORICAL_POSTHOC_NOT_RUN',
 p1_gate={'local_tests':80,'fixtures':15,'independent_audits':12,'source_digest':identity['algorithm_identity']['source_digest'],
          'historical_evidence':'historical_handoff_verification.json'},
 final_tests={'total':180,'legacy_kernel':38,'v2_kernel':42,'monitor':28,'packaging':18,'j3_core':39,'j4_memory':15,'failures':0},
 S01_S30=rows,smoke={'task_runs':4,'event_limit':8,'off':read(root/'smoke_off/aggregate.json'),
                   'on':read(root/'smoke_on/aggregate.json')},
 constructed_integration='constructed_integration/ancestor_stop.json',
 recovery='SELECTED/MONITORED/COMMITTED/READY/TERMINATED; repeat; saved stop; identity tamper',
 installation=read(root/'install/probe_result.json')['scope'],protected=read(root/'protected_after.json'),
 not_run=['historical POSTHOC','full orders or order effect matrix','real Jev or paid models','nonempty memory','candidate prefiltering','RL, branch search or full historical replay'],
 limitations=['strict interior and retained hull may be UNASSESSABLE','no natural predicted instability in the two smoke prefixes',
              'assessment wall time includes reconstruction and LP, not isolated solver CPU time',
              'offline wheel uses existing system dependencies, not a clean network install'],
 old_artifacts_rewritten=False,commit_push=False)
write(root/'engineering_acceptance.json',acceptance)
commands={
'p1_regression':'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=semantic_pallet_planner/src python -m pytest -q semantic_pallet_planner/tests/unit/test_stability_kernel.py semantic_pallet_planner/tests/unit/test_stability_balance.py',
'p1_fixtures':'PYTHONPATH=semantic_pallet_planner/src python semantic_pallet_planner/tests/unit/test_stability_balance.py --output <NEW>/p1_fixtures',
'constructed_evidence':'PYTHONPATH=semantic_pallet_planner/src python semantic_pallet_planner/tests/unit/monitor_acceptance.py --output <NEW>/constructed_integration',
'final_tests':'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=semantic_pallet_planner/src python -m pytest -q semantic_pallet_planner/tests/unit/test_stability_kernel.py semantic_pallet_planner/tests/unit/test_stability_balance.py semantic_pallet_planner/tests/unit/test_stability_monitor.py semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_packaging_runtime.py semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_j3_core.py semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_j4_memory.py',
'off':'PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.jev_select smoke-packaging-monitor --dataset semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02 --stability-monitor off --output <NEW_OFF>',
'on':'PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.jev_select smoke-packaging-monitor --dataset semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02 --stability-monitor on --output <NEW_ON>',
'validate':'PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.jev_select validate-stability-report --report <SAVED_ON_OR_OFF>',
'wheel_build':'python -m pip wheel --no-index --no-deps --no-build-isolation <COPIED_BUILD_SOURCE> --wheel-dir <WHEELS>',
'installed_probe':'<INSTALL_VENV>/bin/python -I <INSTALL>/probe.py (cwd=/tmp)',
'protected_inventory':'audit_scripts/protect_monitor.py and check_protect_monitor.py',
'original_defect':'PYTHONPATH=semantic_pallet_planner/src python semantic_pallet_planner/tests/unit/pct_ls_reproducer.py --output <NEW>/upstream_reproduction'}
write(root/'commands.json',commands)
write(root/'handoff.json',dict(date='2026-11-03',artifact=str(root.relative_to(repo)),report=str(report.relative_to(repo)),
 **{k:acceptance[k] for k in ('engineering_status','monitor_integration_status','record_coverage_status')},
 runtime_version='jev_packaging_monitored_v5',enabled_field='stability_monitor.enabled',default_enabled=False,
 algorithm='pct_contact_network_v2',result_version='pct_stability_result_v2',
 public_entry='semantic_pallet_planner.jev_select.stability.balance_adapter.assess_candidate',
 config_loader='semantic_pallet_planner.jev_select.stability.balance_contracts.load_config',
 monitor_entry='semantic_pallet_planner.jev_select.stability.monitor.monitor_selected_action',
 source_manifest_digest=hashlib.sha256((root/'source_manifest.json').read_bytes()).hexdigest(),
 identity=identity,commands=commands,
 next_action='STOP; no real model, memory loop, full-order matrix or candidate filtering authorized',
 model_calls=0,credential_reads=0,git_commit_push=False))
write(root/'delivery_manifest.json',file_manifest(root))
manifest=read(root/'delivery_manifest.json');assert manifest==file_manifest(root)
print(json.dumps({'status':acceptance['engineering_status'],'files':len(manifest),'S_items':len(rows),'source_files':len(source)},indent=2))
