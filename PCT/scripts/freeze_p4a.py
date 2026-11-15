"""P4-A offline freeze and verification. No dispatch command is provided."""
import argparse
import ast
import importlib.metadata as metadata
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'PCT/src'))
FORBIDDEN={'torch','numpy','scipy','semantic_pallet_planner'}
def guard(event,args):
    if event=='import' and args[0].split('.')[0] in FORBIDDEN:raise RuntimeError('P4A_FORBIDDEN_IMPORT:'+args[0])
    if event in ('socket.connect','socket.getaddrinfo'):raise RuntimeError('P4A_NETWORK_FORBIDDEN')
sys.addaudithook(guard)
from pct_baseline import p4a
from pct_baseline.contracts import read,write_new,sha,digest,require
from pct_baseline.p4a_storage import validate_saved_training

def save(root,name,value):
    target=root/name;target.parent.mkdir(parents=True,exist_ok=True);write_new(target,value)


def predecessor_checks():
    records=[]
    for package in ('PCT_P3_20261115_01','PCT_P3_QA_20261115_01'):
        manifest=Path('PCT/outputs')/package/'delivery_manifest.json';value=read(manifest)
        differences=[]
        for row in value['files']:
            if not Path(row['path']).is_file() or sha(row['path'])!=row['sha256']:differences.append(row['path'])
        require(all(p in ('PCT/README.md','PCT/docs/README.md') for p in differences),'P4A_PREDECESSOR_DRIFT')
        records.append({'package':package,'manifest_sha256':sha(manifest),'files_checked':len(value['files']),
                        'navigation_differences':differences,'history_resigned':False})
    # Consume all required semantic records without importing their validators.
    for prefix,names in [(p4a.P3,['acceptance','identity','handoff','saved_audit','final_saved_audit','resource_metrics']),
                         (p4a.QA,['quality_review','next_stage_admission','handoff'])]:
        for name in names:read(prefix+name+'.json')
    require(read(p4a.P3+'saved_audit.json')['status']=='FAIL','P4A_ORIGINAL_FAIL_MISSING')
    require(read(p4a.P3+'final_saved_audit.json')['status']=='PASS_SAVED_FACTS','P4A_FINAL_AUDIT')
    return records


def cards():
    models=[]
    for kind,path in [('geometry','PCT/outputs/PCT_P2_B_20261115_01/attempt_06/tests/model_manifest.json'),
                      ('load','PCT/outputs/PCT_P2_C_20261115_01/attempt_03/tests/model_manifest.json')]:
        manifest=read(path)
        models.append({'kind':kind,'method':'PCT-adapted','model_version':manifest['model_version'],
                       'source_manifest':path,'manifest_sha256':sha(path),
                       'features':manifest['feature_contract'],'architecture':manifest['architecture'],
                       'formal_weight_status':'PENDING_TRAINING; P2 seed0 and P3 small-step weights are engineering artifacts only'})
    return {'version':'pct_p4a_method_cards_v1','models':models,
        'common_mechanism':'three token types, separate token MLPs, graph attention, valid-node global context, dot-product candidate pointer and critic; no new independent glimpse head',
        'native_differences':['public feasible candidate pool replaces native EMS/virtual stability candidate generation; no native step/drop/environment truth',
            'strict valid/padding masks and padding-safe context differ from upstream default finite masking',
            'exact original candidate ID and pose, upright yaw0/90; public post-selection exact-v3 monitor, original commit checks',
            'capacity1 public observation only; no future boxes/source IDs/reference actions/monitor prelabels/reaction data in input'],
        'feature_comparison':'whole feature packages, not one-factor load ablation: geo leaf top slot uses container H, load uses real z1 plus support/COM/height; geo current sorted dimensions/constant slots vs load original dimensions/mass/stackable/capacity',
        'load_boundaries':'area-ledger positive-increment affected set (including ancestors), kg/9 and Lref; no PCT reaction prediction; synthetic packaging attributes',
        'a2c':{'algorithm':'PCT-adapted+A2C','optimizer':'Adam lr1e-4 clip0.5 vs upstream use_acktr default True/KFAC',
            'upstream_source':'Online-3D-BPP-PCT/Tools.py:143-145','source_sha256':sha('Online-3D-BPP-PCT/Tools.py'),
            'collection_difference':'upstream default64 vector environments x5 steps; here8 complete orders/fixed snapshot, disjoint <=5 segments,250 updates/model; changed update size and training amount, not native reproduction',
            'loss':'choice mean actor with detached advantage + valid-transition mean detached-target critic MSE; singleton actor0; entropy coefficient0 and entropy tracked',
            'training_budget':'six seeds/models,125epochs,2000orders/33000actions/250updates per model; fixed final epoch125'},
        'adequacy_review':{'selection':'never choose best epoch/seed using evaluation; all six final seeds retained incl failed/incomplete',
            'evidence':'per-epoch reward/completion/loading, actor/critic loss, entropy, gradients, technical rates, seed variability and wall/resources; evaluate convergence/stability and comparison with fixed geometry',
            'negative_results':'report nonconvergence, collapse, seed failures, worse-than-geometry and weak baseline explicitly; completing budget is not sufficient strong-baseline evidence',
            'conclusion_limits':['training16 retest is in-sample; six exposed prototype combinations are not independent generalization',
                'predicted static instability is not real collapse rate','full loading gives equal fixed-container utilization; layout needs height/envelope/additional audited metrics',
                'capacity1 position-selection conclusions do not substitute capacity3 experience effects','no native original-paper score replication or global optimality claim']}}


def gates(catalog):
    estimate=read(p4a.P3+'resource_metrics.json')['formal_collection_estimate']
    bytes_per=estimate['bytes_per_monitored_training_action'];raw_training=estimate['198000_action_storage_bytes_estimate']
    raw_evaluation=4280*bytes_per
    largest_snapshot=max(p.stat().st_size for p in Path(p4a.P3+'attempt_02/training/snapshots').glob('*/state.pt'))
    max_boxes=max(t['box_count'] for t in catalog['tasks'] if t['training_eligible'])
    hot_reserve=math.ceil(2*8*max_boxes*bytes_per)
    checkpoint_reserve=36*largest_snapshot*2
    retained=sum(p.stat().st_size for p in Path(p4a.P3).rglob('*') if p.is_file())
    fallback=math.ceil(1.25*(raw_training+raw_evaluation)+hot_reserve+checkpoint_reserve+retained)
    free=shutil.disk_usage('.').free
    preconditions=[
        {'id':'FORMAL_PROTOCOL','status':'NOT_IMPLEMENTED','requirement':'new formal training/execution/recovery schemas and APIs, immutable versions; keep P3 2-task/16-attempt/2-update guards unchanged'},
        {'id':'P3-Q01_OBSERVER','status':'SPECIFIED_NOT_EXECUTED','requirement':'observe every JournalSink durable stage; actual candidate/choice/singleton/critic/monitor/commit and reuse receipts independent of immutable events; verify READY/DECISION_READY/SELECTED/MONITORED/COMMITTED cuts, identity drift/lock/error stop on NEW protocol before long run; do not claim final P3 rerun'},
        {'id':'STOP_RESUME','status':'SPECIFIED_NOT_EXECUTED','requirement':'no re-inference after SELECTED, no re-monitor after MONITORED, no re-commit after COMMITTED; local forward before durable selection reconstruct from saved RNG; commit intent unknown stops; UNKNOWN_SEND no retry; halt campaign on technical/nonfinite errors'},
        {'id':'TRAINING_RECOVERY','status':'NOT_IMPLEMENTED_FORMAL','requirement':'exclusive campaign/job/update writers, fsync/hash/atomic publication; all applicable RNG, model+Adam+policy/update/cursors+batch refs; ambiguous update publication stops; never apply a published update twice or re-sign older orders'},
        {'id':'P3-Q02_STORAGE','status':'PLAN_PLUS_SAVED_ROUNDTRIP_ONLY','requirement':'bounded shards, attempt index, immutable manifests and crash-safe journal/update transaction integration; P4-A gzip audit capsules are NOT a runtime resume format'},
        {'id':'RESOURCES','status':'BLOCKED_PENDING_PROSPECTIVE_PREFLIGHT','requirement':'measure NEW writer on worst registered task sizes and updated observers with bounded separate authorization; profile collection/gradient/optimizer/checkpoint wall and RSS separately, disk growth, crash recovery; actual formal budget still UNKNOWN'},
        {'id':'MODEL_COMPLETION','status':'NOT_RUN','requirement':'all six genuine final epoch125 models with source/feature/tensor/weights identities, seed statuses and adequate convergence review; no P3 random/small-step substitution'},
        {'id':'EVALUATION_DERIVATION','status':'NOT_IMPLEMENTED','requirement':'new child plan adds genuine weights/approval/runtime identities; exact original220 slots/caps/order and first Jev r0 prefix retained; original template remains false'},
        {'id':'REMOTE','status':'NOT_ADMITTED','requirement':'later authorized P4-C verifies official API and credentials loading; max1 send in original first slot, no extra success sample; P4-A never reads credentials'}]
    return {'version':'pct_p4a_formal_prerequisites_v1','formal_execution_admitted':False,'training_executor':'NOT_IMPLEMENTED',
        'preconditions':preconditions,'P3_original_failure':'preserved without rewrite; corrected final source not fully rerun on six jobs/training',
        'baseline_resource':estimate,'collection_hours_approx':estimate['198000_action_collection_seconds_estimate']/3600,
        'cost_scope':'30.2h/470GB is P3 collection-only linear extrapolation; optimizer/gradient/longer-state cost and all-in wall UNKNOWN',
        'capacity_gate':{'basis':'conservative uncompressed P3 training+4280 evaluation action fallback,1.25 safety,2 hot batch shards,36 checkpoints x2 measured P3 state.pt maximum,retain entire P3',
            'required_free_bytes_fallback':fallback,'observed_free_bytes':free,'observed_free_sufficient_for_fallback':free>=fallback,
            'checkpoint_size_reference':largest_snapshot,'hot_shard_reserve_bytes':hot_reserve,
            'compression_policy':'do not lower capacity threshold from P4-A observed gzip ratio; a new formally accepted worst-case writer benchmark is required',
            'runtime_stop':'reserve free space before each shard/update; when next atomic write+hot rollback+checkpoint reserve unavailable stop at safe boundary, preserve remaining NOT_RUN; never delete archived evidence or silently reduce epochs'},
        'storage_contract':{'version':'pct_formal_storage_design_v1','implementation':'DESIGN_ONLY',
            'units':'per attempt header+event/transition stream and bounded <=8-order or64MiB uncompressed shards (whichever first); split oversized attempt into indexed segments without splitting transition records',
            'representation':'canonical UTF8 JSONL gzip deterministic header; exact coordinate/float facts and explicit field/schema versions, no quantization; content digest on both plain and compressed bytes',
            'index':'campaign/model/seed/epoch/attempt/decision/segment -> shard+record offset, hashes, policy/config/task/source identities; each transition once, no cumulative full-history duplication',
            'audit_retention':'retain full denominators and failures, current public contexts/candidate IDs/actions, monitor receipts, before/after state refs, reward/done/truncated/next value, update input logprob/value, source/model/optimizer/RNG identities; no winner-only retention',
            'hot_durable':'active attempt WAL stores READY/DECISION_READY/SELECTED/MONITORED/COMMITTED; fsync before each external/physical action, immutable finalized capsules referenced by batch manifest; checkpoint optimizer states as separate hashed binary blobs',
            'transaction':'write .pending then fsync bytes/index/directory then publish immutable manifest atomically under lock; orphan pending/quarantine never counted as completed; incomplete commit/update intent stops for diagnosis',
            'resume':'last committed manifest and validated hot WAL establish cursors; validate all identity/hash chains; no old source resigning; references to earlier frozen policy remain immutable',
            'validation_scope':'P4-A pack/unpack only preserves existing saved JSON bytes and semantics, not formal WAL/step/update crash integration or throughput',
            'retention_policy':'no automatic history deletion/GC; disk-limited stop rather than purge; future archive migration must retain hashes and source locators'},
        'prospective_preflight_proposal':{'authorization':'NOT_GRANTED_NOT_RUN','scope':'proposal only: new formal protocol, engineering seed11, geo/load each one attempt on NEW_00100027_controlled_base(19) and SYN_COMBO_06(40), four attempts,118 action/monitor/choice cap; four saved one-action prefix cases stop at next READY',
            'tasks':['NEW_00100027_controlled_base','SYN_COMBO_06'],
            'caps':{'complete_attempts':4,'actions':118,'candidate_generations_including_empty_pools':122,'monitors_including_prefixes':120,'network_choices_including_prefixes':119,'prefix_physical_commits':3,'remote_requests':0,'optimizer_updates':0},
            'training_update_budget':'NOT_GRANTED; separate explicit numerical cap needed if optimizer crash/throughput testing requires updates',
            'purpose':'worst-size writer/observer/timing/RSS/disk and update-transaction verification, not performance tuning or repeating P3 matrix'}}


def build(output):
    output.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    save(output,'baseline.json',{'branch':subprocess.check_output(['git','branch','--show-current'],text=True).strip(),
        'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'provided_qa_baseline':'116f022e81cd782975436bfa5906b23b18cde64a','initial_session_worktree':'CLEAN','initial_session_index':'EMPTY'})
    require(read(output/'baseline.json')['branch']=='dev/PCT','P4A_BRANCH')
    save(output,'predecessor_checks.json',predecessor_checks())
    catalog,tasks=p4a.authenticated_catalog(ROOT);spec=p4a.build_spec(ROOT);identity=p4a.input_identity(ROOT)
    p4a.check_input_identity(ROOT,identity)
    training=p4a.build_training(catalog,identity,spec);evaluation=p4a.build_evaluation(catalog,identity,spec,training)
    results=[p4a.validate_plan('training',training,catalog,identity,spec),p4a.validate_plan('evaluation',evaluation,catalog,identity,spec,training)]
    save(output,'data_catalog.json',catalog)
    for task in tasks:save(output,'data/tasks/'+task['task_id']+'.json',task)
    save(output,'training_plan.json',training);save(output,'evaluation_template.json',evaluation)
    save(output,'method_cards.json',cards());save(output,'formal_prerequisites.json',gates(catalog))
    for name,expected in identity.items():
        p=Path(name)
        if name.startswith(('PCT/src/','PCT/scripts/','PCT/tests/','PCT/configs/')):
            target=output/'source_snapshot'/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
    save(output,'input_identity.json',{'files':identity,'catalog_digest':catalog['catalog_digest'],
                                     'legacy_derived_data_identity':catalog['legacy_derived_data_identity']})
    roundtrip=validate_saved_training(Path(p4a.P3+'attempt_02/training'),output/'storage_validation')
    require(roundtrip['transitions']==147 and roundtrip['attempts']==16,'P4A_STORAGE_DENOMINATOR')
    save(output,'storage_roundtrip.json',roundtrip)
    save(output,'plan_validation.json',{'results':results,'model_attempt_slots':12000,'evaluation_slots':220,
        'training_action_cap':198000,'jev_send_cap':1284,'network_choice_cap':2568,
        'forbidden_module_imports':[n for n in sys.modules if n.split('.')[0] in FORBIDDEN],
        'new_orders':0,'candidate_generations':0,'LP_calls':0,'model_forwards':0,'optimizer_updates':0,'remote_requests':0,
        'elapsed_s':time.perf_counter()-started,'formal_execution_admitted':False})
    print(json.dumps({'status':'PLANS_AND_SAVED_ROUNDTRIP_READY','output':str(output),'execution_admitted':False}))


def verify(root):
    identity=read(root/'input_identity.json');p4a.check_input_identity(ROOT,identity['files'])
    catalog,tasks=p4a.authenticated_catalog(ROOT);spec=p4a.build_spec(ROOT)
    require(read(root/'data_catalog.json')==catalog,'P4A_CATALOG_DRIFT')
    for t in tasks:require(read(root/'data/tasks'/(t['task_id']+'.json'))==t,'P4A_DERIVED_FILE_DRIFT')
    training=read(root/'training_plan.json');evaluation=read(root/'evaluation_template.json')
    p4a.validate_plan('training',training,catalog,identity['files'],spec)
    p4a.validate_plan('evaluation',evaluation,catalog,identity['files'],spec,training)
    require(read(root/'method_cards.json')==cards(),'P4A_METHOD_CARD_DRIFT')
    print(json.dumps({'status':'PASS_OFFLINE_PLAN_ONLY','slots':220,'sending_admitted':False,'execution_admitted':False}))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['build','verify']);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.mode=='build':build(args.output)
    else:verify(args.output)
if __name__=='__main__':main()
