"""Offline engineering evidence only. No real API/preflight/Pilot, no model performance."""
import json
from pathlib import Path
from semantic_pallet_planner.o5.common import ROOT, read, atomic, offline_guard, O5Error, digest
from semantic_pallet_planner.o5 import remote_experiment as ex, remote_authorized as au
from semantic_pallet_planner.o5.remote_transport import HTTPWire
from semantic_pallet_planner.o5.remote_config import require_cost
from semantic_pallet_planner.runners.o5_direct_text import DATASET, PROFILE, operator_record


class OfflineWire(ex.FixtureWire):
    test_double = True

    def post(self, endpoint, body, credential, timeout):
        status, headers, raw = super().post(endpoint, body, credential, timeout)
        value = json.loads(raw)
        value.update(model='deepseek-flash', id='OFFLINE_SIMULATED_NOT_PROVIDER_RECEIPT')
        return status, {'x-request-id':'OFFLINE_SIMULATED_NOT_PROVIDER_RECEIPT'}, json.dumps(value)


def forbid_real_wire(*args, **kwargs):
    raise AssertionError('REAL_HTTP_FORBIDDEN_IN_OFFLINE_ACCEPTANCE')


if __name__ == '__main__':
    report = Path(__file__).parent
    outputs = ROOT/'semantic_pallet_planner/outputs'
    suffix = '20261028_02'
    plan = outputs/f'PLAN_O5_DIRECT_TEXT_OFFLINE_PREFLIGHT_{suffix}'
    run = outputs/f'EXP_O5_DIRECT_TEXT_OFFLINE_PREFLIGHT_{suffix}'
    campaign = outputs/f'CAMPAIGN_O5_DIRECT_TEXT_OFFLINE_{suffix}'
    fixture_plan = outputs/f'PLAN_O5_DIRECT_TEXT_HTTP_FIXTURE_{suffix}'
    fixture_run = outputs/f'EXP_O5_DIRECT_TEXT_HTTP_FIXTURE_{suffix}'
    fixture_report = ROOT/f'report/analysis/O5_DIRECT_TEXT_HTTP_FIXTURE_{suffix}'
    HTTPWire.post = forbid_real_wire
    with offline_guard():
        profile = require_cost(read(PROFILE))
        ex.prepare(DATASET, plan, profile, stage='preflight')
        authorization = operator_record(plan, campaign, 'preflight', 'OFFLINE_ONLY')
        authorization['instruction_reference'] = 'OFFLINE_ENGINEERING_TEST_DOUBLE_ONLY_NOT_REAL_OPERATOR_RUN'
        atomic(report/'offline_authorization.json', authorization)
        wire = OfflineWire(['invalid', 'valid', 'valid'])
        executed = au.preflight(plan, run, report/'offline_authorization.json', _offline_wire=wire)
        checked = au.verify_preflight(run)
        assert checked['status']=='PASS' and checked['test_double'] is True
        assert executed['real_api_attempts']==0 and len(wire.calls)==3
        try:
            au.prepare_pilot_from_preflight(run, outputs/f'PLAN_O5_DIRECT_TEXT_FORBIDDEN_PILOT_{suffix}')
        except O5Error as error:
            assert error.code=='PREFLIGHT_NOT_REAL'
        else:
            raise AssertionError('Offline double unlocked real Pilot')
        ex.prepare(None, fixture_plan, profile, fixture=True)
        fixture_wire = OfflineWire()
        partial = ex.execute_fixture(fixture_plan, fixture_run, stop_after=2, wire=fixture_wire)
        prefix = ex.verify(fixture_run)
        completed = ex.execute_fixture(fixture_plan, fixture_run, resume=True, wire=fixture_wire)
        verified = ex.verify(fixture_run)
        report_result = ex.report(fixture_run, fixture_report)
        before = len(fixture_wire.calls)
        ex.execute_fixture(fixture_plan, fixture_run, resume=True, wire=fixture_wire)
        assert len(fixture_wire.calls)==before
        assert verified['status']=='PASS' and verified['verified_jobs']==4
        assert all(result['test_double'] for result in verified['results'])
        assert not list(plan.rglob('*.png')) and not list(fixture_run.rglob('*.png'))
        assert all(len(body['messages'][1]['content'])==1 for body in wire.calls+fixture_wire.calls)
        atomic(report/'offline_preflight_verification.json', {k:v for k,v in checked.items() if k!='plan'})
        atomic(report/'offline_fixture_verification.json', verified)
        atomic(report/'offline_lifecycle.json', {
            'status':'PASS_OFFLINE_ENGINEERING_ONLY', 'test_double':True,
            'protocol_version':'o5_direct_text_v1','real_api_attempts':0,
            'actual_text_preflight':'NOT_RUN_USER_EXECUTES','actual_D0_Pilot':'NOT_RUN',
            'preflight_plan':str(plan),'preflight_run':str(run),'offline_preflight':executed,
            'fixture_plan':str(fixture_plan),'fixture_run':str(fixture_run),'fixture_report':str(fixture_report),
            'partial':partial,'verified_prefixes':prefix['verified_prefixes'],
            'complete':completed,'report':report_result,'idempotent_resume':True,
            'real_pilot_gate':'PREFLIGHT_NOT_REAL',
            'all_provider_messages_text_only':True,'image_files_created':0,
            'fixture_commits':sum(r['summary']['placed_items'] for r in verified['results']),
            'model_performance':'NOT_MEASURED','offline_fixture_wire_attempts':len(fixture_wire.calls)})
        print(json.dumps({'status':'PASS_OFFLINE_ENGINEERING_ONLY','real_api_attempts':0,
                          'offline_preflight_attempts':len(wire.calls),'fixture_attempts':len(fixture_wire.calls),
                          'verified_fixture_jobs':verified['verified_jobs']},indent=2))
