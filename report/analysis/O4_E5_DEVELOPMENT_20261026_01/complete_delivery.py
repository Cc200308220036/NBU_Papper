"""Wait for the running frozen matrix, then perform read-only/API-plan handoff.

This script never invokes remote-run or a transport completion method.
"""
import json
import os
from pathlib import Path
import subprocess
import time

WS = Path('/home/cyw/NBU_Papper')
ROOT = WS/'semantic_pallet_planner/outputs'
PLAN = ROOT/'PLAN_O4_E5_090_OFFLINE_READY_20261026_06'
EXP = ROOT/'EXP_O4_E5_090_OFFLINE_20261026_06'
ONLINE = ROOT/'PLAN_O4_E5_090_ONLINE_READY_20261026_01'
OUT = WS/'report/analysis/O4_E5_DEVELOPMENT_20261026_01'
PYTHON = '/home/cyw/anaconda3/envs/pallet_vlm/bin/python'
ENV = dict(os.environ, PYTHONPATH=str(PLAN/'code_snapshot/semantic_pallet_planner/src'))

def stage(name, **extra):
    row = {'stage': name, 'plan': str(PLAN), 'experiment': str(EXP), 'updated_unix': time.time(), **extra}
    (OUT/'delivery_stage.json').write_text(json.dumps(row, indent=2)+'\n')
    print(json.dumps(row), flush=True)

def command(args, filename):
    with (OUT/filename).open('w') as stream:
        result = subprocess.run([PYTHON, '-P', *args], cwd=WS, env=ENV, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        stage('FAILED', command=args, exit_code=result.returncode, log=filename)
        raise SystemExit(result.returncode)

stage('WAITING_FOR_FROZEN_OFFLINE_MATRIX')
while not (EXP/'delivery_manifest.json').exists():
    if (EXP/'acceptance_report.json').exists():
        report = json.loads((EXP/'acceptance_report.json').read_text())
        if report.get('offline_status') == 'FAIL':
            stage('OFFLINE_FAILED', report=report)
            raise SystemExit(1)
    time.sleep(20)
report = json.loads((EXP/'acceptance_report.json').read_text())
if report.get('offline_status') != 'PASS' or not all(report.get('gates', {}).values()):
    stage('OFFLINE_FAILED', report=report)
    raise SystemExit(1)
stage('READONLY_VERIFY')
command(['-m', 'semantic_pallet_planner.runners.o4_e5', 'verify', '--experiment', str(EXP)], 'readonly_verify.json')
stage('PREPARING_API_PLAN_NO_REQUESTS')
command(['-m', 'semantic_pallet_planner.runners.o4_e5', 'remote-prepare',
         '--development-plan', str(PLAN), '--offline-experiment', str(EXP),
         '--model-config', str(WS/'semantic_pallet_planner/configs/o4_d_deepseek_flash.yaml'),
         '--output', str(ONLINE)], 'remote_prepare.json')
stage('FINAL_EXTERNAL_AUDIT')
command([str(OUT/'fault_coverage_mapping.py')], 'fault_coverage_mapping_stdout.json')
command([str(OUT/'audit_delivery.py')], 'audit_delivery_stdout.json')
command([str(OUT/'summarize_delivery.py')], 'descriptive_summary_stdout.json')
stage('AUDITS_COMPLETE_REAL_API_NOT_RUN')
