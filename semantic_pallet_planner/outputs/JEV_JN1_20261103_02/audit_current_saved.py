"""Current checkout validators; original JN1-A artifacts opened read-only.

No execute/prepare/send and no original audit_saved.py: those write receipts.
Only a temporary external ledger copy exercises stored-selection recovery.
"""
import sys
sys.dont_write_bytecode=True
import os
from pathlib import Path
import hashlib
import json
import shutil
import tempfile
from contextlib import ExitStack
from unittest.mock import patch

OUT=Path(__file__).resolve().parent
REPO=OUT.parents[2]
OLD=OUT.parent/'JEV_JN1_20261103_01'
REPORT=REPO/'docs/03_阶段产出分析/Jev/Jev_JN1-A协议适配与最小真实调用验收_20261103.md'
counters={'network_attempts':0,'credential_reads':0,'historical_writes':0}
blocked={}

def audit(event,args):
    if event in ('socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.sendto','socket.bind'):
        counters['network_attempts']+=1;raise AssertionError('network forbidden')
    if event=='open' and isinstance(args[0],(str,bytes)):
        name=os.fsdecode(args[0]);lower=name.lower()
        if any(s in lower for s in ('typesafe_api_key','deepseek_api.md','.env','credentials')):
            counters['credential_reads']+=1;raise AssertionError('credential read forbidden')
        mode,flags=args[1:3]
        writing=(isinstance(mode,str) and any(x in mode for x in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        target=Path(name).resolve()
        if writing and (target.is_relative_to(OLD) or target==REPORT):
            counters['historical_writes']+=1;raise AssertionError('historical write forbidden')
    if event in ('os.remove','os.rename','os.rmdir','os.mkdir','os.chmod','os.link','os.symlink'):
        for arg in args[:2]:
            if isinstance(arg,(str,bytes)):
                target=Path(os.fsdecode(arg)).resolve()
                if target.is_relative_to(OLD) or target==REPORT:
                    counters['historical_writes']+=1;raise AssertionError('historical mutation forbidden')
sys.addaudithook(audit)
from semantic_pallet_planner.jev_select.contracts import digest,DecisionContext
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.packaging_experiment import validate_saved_checkpoint
from semantic_pallet_planner.jev_select.packaging_remote import RequestLedger,preflight_remote,remote_selector_factory,decision_record
from semantic_pallet_planner.jev_select.selector import parse_response
from semantic_pallet_planner.jev_select.transport import validate_transport
from semantic_pallet_planner.jev_select.packaging_runtime import summary
from semantic_pallet_planner.jev_select.packaging_api import parent_check

sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def protected():
    return {**{str(p.relative_to(REPO)):sha(p) for p in OLD.rglob('*') if p.is_file()},str(REPORT.relative_to(REPO)):sha(REPORT)}
before=protected()
assert before==read(OUT/'protected_before.json')
assert source_manifest()==read(OLD/'source_manifest.json')==read(OUT/'source_manifest.json')
manifest=read(OLD/'delivery_manifest.json')
assert all(sha(OLD/n)==h for n,h in manifest['files_sha256'].items())

def forbidden(name):
    blocked[name]=0
    def call(*args,**kw):
        blocked[name]+=1
        raise AssertionError('forbidden entry: '+name)
    return call

entries=[
 'semantic_pallet_planner.jev_select.episode.run_episode',
 'semantic_pallet_planner.jev_select.episode._run_episode_v2',
 'semantic_pallet_planner.jev_select.episode.decision_inputs',
 'semantic_pallet_planner.jev_select.packaging_api.run_episode',
 'semantic_pallet_planner.jev_select.packaging_api.prepare',
 'semantic_pallet_planner.jev_select.packaging_api.execute',
 'semantic_pallet_planner.jev_select.packaging_experiment.run_packaging_plan',
 'semantic_pallet_planner.jev_select.packaging_experiment._run_job',
 'semantic_pallet_planner.jev_select.candidates.CandidateProvider.build',
 'semantic_pallet_planner.jev_select.candidates.generate',
 'semantic_pallet_planner.jev_select.execution.commit_physical',
 'semantic_pallet_planner.o4.buffer.buffer_state.place',
 'semantic_pallet_planner.jev_select.stability.monitor.monitor_selected_action',
 'semantic_pallet_planner.jev_select.stability.balance_adapter.assess_candidate',
 'semantic_pallet_planner.jev_select.stability.balance_network.solve_network',
 'semantic_pallet_planner.jev_select.stability.assess_candidate',
 'scipy.optimize.linprog',
 'semantic_pallet_planner.jev_select.transport.JevTransport.complete',
 'semantic_pallet_planner.jev_select.transport.credential']
with ExitStack() as stack:
    for name in entries:stack.enter_context(patch(name,forbidden(name)))
    config=read(OLD/'config.snapshot.json');task=read(OLD/'task.snapshot.json');ctx=DecisionContext.from_dict(read(OLD/'frozen/context.json'))
    preflight_remote(config)
    assert parent_check()[0]==read(OLD/'baseline_verification.json')
    verified=[]
    for name in ['prefix/checkpoint.json','stages/SELECTED.json','stages/MONITORED.json','stages/COMMITTED.json','checkpoint.json']:
        validate_saved_checkpoint(read(OLD/name),task,config,'A_SMOKE');verified.append(name)
    ledger_data=read(OLD/'request_ledger/requests.json');assert len(ledger_data['requests'])==1
    attempt=ledger_data['requests'][0]
    identity=RequestLedger.identity(ctx,'A_SMOKE','A_SMOKE_D0000')
    assert all(attempt[k]==v for k,v in identity.items())
    assert validate_transport(attempt['transport'])==(OLD/'response.raw.json').read_bytes()
    assert attempt['origin']=='jev' and attempt['send_started'] and attempt['model']=='jev-1.14.0'
    selected=parse_response(ctx,attempt,config)
    assert selected.data==read(OLD/'selection.json')==attempt['selection']
    with tempfile.TemporaryDirectory(prefix='jn1-source-ledger-') as name:
        tmp=Path(name);shutil.copyfile(OLD/'request_ledger/requests.json',tmp/'requests.json')
        ledger=RequestLedger(tmp,max_sends=1)
        transport=type('NeverSend',(),{'origin':'jev','complete':forbidden('temporary_transport.complete')})()
        selector=remote_selector_factory('jev_no_memory',config=config,transport=transport,ledger=ledger,job_id='A_SMOKE')
        copied_before=sha(tmp/'requests.json')
        one=selector.select(ctx,decision_id='A_SMOKE_D0000').data
        two=selector.select(ctx,decision_id='A_SMOKE_D0000').data
        assert one==two==selected.data and sha(tmp/'requests.json')==copied_before
        stats=ledger.statistics();assert stats==read(OLD/'request_statistics.json')
    event=read(OLD/'event.json');assert event==read(OLD/'checkpoint.json')['events'][-1]
    assert decision_record(event)==read(OLD/'decision_record.json')
    cp=read(OLD/'checkpoint.json')
    expected=summary(task,config,'jev_no_memory',cp['state'],cp['events'],cp['reason'] or 'JN1_A_SINGLE_DECISION_BOUNDARY')
    assert expected==read(OLD/'metrics.json')['loading']
    resolved=read(OLD/'resolved_action.json')
    candidate=next(c for c in event['bundle']['physical_candidates'] if c['candidate_id']==selected.data['selected_candidate_id'])
    assert candidate==resolved['exact_candidate'] and digest(candidate)==resolved['candidate_digest']
    assert resolved['execution_credential']==event['action']==event['proposed_action']
    execution=read(OLD/'execution.json')
    assert execution=={k:event[k] for k in ('action','proposed_action','event','reason','before','after')}
    assert event['monitor']==read(OLD/'monitor.json') and event['monitor']['status']=='STABLE'
    assert selected.data['selected_display_id']=='C14' and selected.data['selected_candidate_id']=='E2_405e193bc2c793bf'
    assert len(event['after']['placed_items'])==1 and not event['before']['placed_items']
    assert read(OLD/'scope_stop.json')['order_complete'] is False
assert all(n==0 for n in blocked.values()) and all(n==0 for n in counters.values())
after=protected();assert after==before
write(OUT/'saved_record_validation.json',{'version':'jev_jn1_source_saved_validation_v1','status':'PASS',
 'production_import_root':'semantic_pallet_planner/src','production_source_digest':digest(source_manifest()),
 'original_package_manifest_files_verified':406,'checkpoints_verified':verified,
 'checks':['current preflight and original parent admission','five saved checkpoint stages','raw response bytes and transport digest',
 'request context/body/state/mapping identities','native response strict parsing equals saved selection','temporary copied ledger repeated recovery no writes',
 'DecisionRecord and exact candidate binding','monitor and execution transition','saved metrics recomputation','single-decision scope boundary'],
 'blocked_entry_calls':blocked,'guards':counters,'historical_real_requests_referenced':1,'historical_monitor_status':'STABLE',
 'new_real_requests':0,'new_monitor_evaluations':0,'new_commits':0,'historical_bytes_unchanged':True,
 'original_audit_not_executed':'audit_saved.py writes recovery_validation.json and execute rewrites output files; independent read-only standard validators used instead',
 'no_full_order_or_historical_replay':True})
write(OUT/'protected_before_after.json',{'version':'jev_jn1_source_protection_v1','status':'PASS','before':before,'after':after,'unchanged':True})
print('PASS: current-source saved-record validation; history unchanged; new API/monitor/commit = 0/0/0')
