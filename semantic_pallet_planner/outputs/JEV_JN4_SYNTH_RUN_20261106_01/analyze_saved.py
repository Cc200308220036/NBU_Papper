"""Read saved records only; no episode, candidate, retrieval or model dispatch."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.packaging_reanalysis import evaluate, metric_view, RULE_VERSION

OUT = Path(__file__).resolve().parent
REPO = Path.cwd()
PLAN = Path('semantic_pallet_planner/outputs/JEV_JN4_SYNTH_EXEC_20261105_01/plan')
def read(p):
    return json.loads(p.read_text())
def write(n, x):
    (OUT/n).write_text(json.dumps(x, ensure_ascii=False, indent=2)+'\n')
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

p = read(PLAN/'plan.json')
run = Path(p['run_location'])
summary = read(run/'summary.json')
gate = read(run/'first_gate.json') if (run/'first_gate.json').exists() else {'status':'NOT_PUBLISHED_TECHNICAL_STOP'}
rows = []
views = {}
for j in p['jobs']:
    folder = run/'jobs'/j['job_id']
    status = read(folder/'status.json')
    m = read(folder/'metrics.json') if (folder/'metrics.json').exists() else None
    row = {k:j[k] for k in ('job_id','task_id','method_id')}
    row.update(status=status, metrics=m if m is not None else 'NOT_RUN' if status['state']=='NOT_RUN' else 'UNKNOWN_TECHNICAL_FAILURE', metrics_path=str(folder/'metrics.json') if m else None)
    rows.append(row)
    if m:
        task = read(folder/'task.snapshot.json')
        views[j['task_id'],j['method_id']] = metric_view({'metrics':m,'status':status},task,p['data']['data_identity'])
write('all_slots.json',rows)
fields = ['job_id','task_id','method_id','state','category','termination_reason','placed_items','planned_items','placed_item_ratio','placed_volume_ratio','placed_mass_ratio','fixed_container_utilization','actual_height_mm','envelope_utilization','request_statistics','memory_metrics','latency_s']
with (OUT/'all_slots.csv').open('w') as f:
    w = csv.DictWriter(f,fieldnames=fields);w.writeheader()
    for row in rows:
        m = row['metrics']; absent = 'NOT_RUN' if row['status']['state']=='NOT_RUN' else 'UNKNOWN'
        x = {k:row[k] for k in ('job_id','task_id','method_id')}
        x.update(state=row['status']['state'],category=row['status']['category'])
        for key in fields[5:]:
            value = m.get('loading',{}).get(key,m.get(key,absent)) if isinstance(m,dict) else absent
            if key=='request_statistics' and isinstance(m,dict): value=m['cost']
            x[key]=json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else value
        w.writerow(x)
comparisons=[]
for task in p['task_ids']:
    for alt, ref, label in [('jev_with_trajectory','jev_no_memory','T/none'),('jev_with_contrast_experience','jev_no_memory','E/none'),('jev_with_contrast_experience','jev_with_trajectory','E/T'),('jev_with_contrast_experience','jev_with_unrelated_E_control','E/unrelated_E')]:
        a,b=views.get((task,ref)),views.get((task,alt))
        comparisons.append({'task_id':task,'comparison':label,'reference':ref,'alternative':alt,'evaluation':evaluate(a,b,rule_version=RULE_VERSION) if a and b else {'comparison_valid':False,'label_v2':'NOT_RUN','invalid_reasons':['missing_executed_pair']}})
write('paired_comparisons_v2.json',comparisons)
behavior=[]
for task in p['task_ids']:
    taskrows=[r for r in rows if r['task_id']==task]
    sequences={r['method_id']:[{'decision_id':d['decision_id'],'candidate':d['selected_candidate_id'],'box':d['selected_box'],'pose':d['selected_pose']} for d in r['metrics']['memory_metrics']['decisions']] if isinstance(r['metrics'],dict) else 'NOT_RUN' for r in taskrows}
    behavior.append({'task_id':task,'saved_selection_sequences':sequences,'interpretation':'Observed trajectories only. Diverged states/pools are not matched counterfactual decisions; no causal attribution.'})
write('behavior_observations.json',behavior)
coverage=[]
for r in rows:
    m=r['metrics'];item={k:r[k] for k in ('job_id','task_id','method_id')}
    if isinstance(m,dict):
        mem=m['memory_metrics'];ds=mem['decisions']
        item.update(decisions=mem['decision_count'],library_nonempty_decisions=sum(d['library_nonempty'] for d in ds),retrieval_nonempty_decisions=sum(d['qualified_retrieval_nonempty'] for d in ds),view_nonempty_count=mem['view_nonempty_count'],body_nonempty_count=mem['body_nonempty_count'],actually_sent_nonempty_count=mem['actually_sent_nonempty_count'],singleton_decisions=sum(d['route']=='SINGLETON_BYPASS' for d in ds),singleton_nonempty_view_count=mem['singleton_nonempty_view_count'])
    else:item['coverage']='NOT_RUN' if r['status']['state']=='NOT_RUN' else 'UNKNOWN'
    coverage.append(item)
write('coverage_summary.json',coverage)
write('descriptive_summary.json',{'categories':summary['categories'],'completed_slots':sum(r['status']['state']=='FINISHED' for r in rows),'executed_slots':sum(r['status']['state']!='NOT_RUN' for r in rows),'planned_slots':36,'first_gate':gate['status'],'request_statistics':summary['request_statistics'],'paired_labels':dict(Counter(c['evaluation']['label_v2'] for c in comparisons)),'research_benefit':'NOT_ESTABLISHED','interpretation':'Six synthetic orders, one observation per method; familiar prototypes, no unseen-source or causal claim. Invalid/range/technical pairs do not rank policies.'})
write('run_evidence_identity.json',{'plan_sha256':sha(PLAN/'plan.json'),'plan_digest':digest(p),'run_receipt_sha256':sha(run/'run_receipt.json'),'summary_sha256':sha(run/'summary.json'),'run_manifest_sha256':sha(run/'delivery_manifest.json'),'first_gate_sha256':sha(run/'first_gate.json') if (run/'first_gate.json').exists() else None,'continuation':read(run/'continuation.json') if (run/'continuation.json').exists() else 'NOT_RUN'})
print(json.dumps(read(OUT/'descriptive_summary.json'),ensure_ascii=False))
