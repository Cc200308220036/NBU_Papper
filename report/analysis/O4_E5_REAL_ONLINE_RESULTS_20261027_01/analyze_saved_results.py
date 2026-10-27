"""Aggregate saved E5 outputs only; no API, planner, episode replay or output mutation."""
from pathlib import Path
import collections,json
ROOT=Path(__file__).resolve().parents[3]
p=ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_090_REAL_20261026_01'
out=Path(__file__).resolve().parent
read=lambda q:json.loads(q.read_text())
s=read(p/'metrics/summary.json'); ledger=read(p/'audit/ledger.json'); fails=read(p/'metrics/failure_attribution.json')
backends={}
for b in sorted({g['backend'] for g in s['groups']}):
 gs=[g for g in s['groups'] if g['backend']==b]
 backends[b]={'planned_episodes':sum(g['planned_episodes'] for g in gs),'completed':sum(g['completed'] for g in gs),'violating_steps':sum(g['violating_steps'] for g in gs),'compilation':{k:sum(g['compilation'][k] for g in gs) for k in ['decisions','first_valid','repaired_valid','final_valid','final_invalid_or_failed']},'components':{k:{f:sum(g['components'][k][f] for g in gs) for f in ['correct','comparable','not_comparable']} for k in ['raw_ast_equal','semantic_equal','allowed_set_equal']}}
methods=[]
for b in sorted(backends):
 for method in sorted({g['planner'] for g in s['groups'] if g['backend']==b}):
  gs=[g for g in s['groups'] if g['backend']==b and g['planner']==method];n=sum(g['planned_episodes'] for g in gs)
  methods.append({'backend':b,'planner':method,'episodes':n,'completed':sum(g['completed'] for g in gs),'clean_completed':sum(g['clean_completed'] for g in gs),'placed_items':sum(g['placed_items'] for g in gs),'planned_items':sum(g['planned_items'] for g in gs),'mean_placed_volume_ratio':sum(g['mean_placed_volume_ratio']*g['recorded_episodes'] for g in gs)/n})
repairs=[{k:a.get(k) for k in ['attempt_id','job_id','compilation_id','status','repair','repair_diagnostic']} for a in ledger['attempts'] if a['status']!='valid']
result={'analysis_scope':'saved metrics, ledger and failure-attribution aggregation; no new replay or API','experiment':str(p.relative_to(ROOT)),'acceptance':read(p/'acceptance_report.json'),'budget':{k:v for k,v in read(p/'audit/budget.json').items() if k!='per_job'},'backends':backends,'methods':methods,'attempt_statuses':dict(collections.Counter(a['status'] for a in ledger['attempts'])),'repairs':repairs,'termination_reasons':dict(collections.Counter(x['reason'] for x in fails)),'diagnostic_counts':{k:sum(bool(x.get('final_diagnostics',{}).get(k)) for x in fails) for k in ['fifo_head_blocked','sampled_physical_empty','topk_coverage_limited','search_truncated']},'legal_ast_semantic_error_steps':sum(x['legal_ast_semantic_error_steps'] for x in fails),'previously_generated_by_runner':read(p/'audit/online_recomputation.json'),'usage':{k:sum((a.get('usage') or {}).get(k,0) or 0 for a in ledger['attempts']) for k in ['prompt_tokens','completion_tokens','total_tokens']},'limitations':['12 known development sources; 24 configurations are not independent sources','Image is measured only for single, not buffer planners','offline_status PASS in frozen runner is hardcoded; offline full recheck USER_WAIVED remains unchanged','runner had already automatically generated online_recomputation.json; analysis does not invoke it again']}
(out/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':'saved_result_analysis_complete','real_api_attempts':len(ledger['attempts']),'compilations':sum(backends[b]['compilation']['decisions'] for b in ['remote_text','remote_image']),'new_api_attempts':0,'new_replays':0},ensure_ascii=False))
