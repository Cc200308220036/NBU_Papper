"""Analyze new measurements; no model calls and no historical episode replay."""
from pathlib import Path
import json,hashlib,collections,copy
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
EXP=ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_SPATIAL_LOCAL_20261027_01'
REAL=ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_090_REAL_20261026_01'
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def boundary_groups(c,placed):
    x,y=c['pose']['x_mm'],c['pose']['y_mm'];dx,dy,_=c.get('oriented_size_mm',c.get('size'));a0,a1,b0,b1=x-dx/2,x+dx/2,y-dy/2,y+dy/2;groups=set()
    for o in placed:
        p=o['pose'];lx,ly,_=o['oriented_size_mm'];x0,x1,y0,y1=p['x_mm']-lx/2,p['x_mm']+lx/2,p['y_mm']-ly/2,p['y_mm']+ly/2
        for g in (0,50,100):
            for side,dist,overlap in [('left',x0-a1,min(b1,y1)-max(b0,y0)),('right',a0-x1,min(b1,y1)-max(b0,y0)),('front',y0-b1,min(a1,x1)-max(a0,x0)),('back',b0-y1,min(a1,x1)-max(a0,x0))]:
                if abs(dist-g)<=1e-6 and overlap>1e-6:groups.add(f'{g}:{side}')
    return groups

coverage=[];records=[]
for f in sorted((EXP/'episodes').glob('*.json')):
    r=read(f);records.append(r['measurement'])
    for e in r['events']:
        if 'groups' not in e:continue
        for g in e['groups']:
            a=g['generation']
            if 'retention' not in a:continue
            all_groups=set().union(*(boundary_groups(c,e['request']['placed_objects']) for c in a['retention']))
            kept_groups=set().union(*(boundary_groups(c,e['request']['placed_objects']) for c in g['candidates']))
            coverage.append({'job_id':r['job_id'],'request_id':e['request']['request_id'],'pick':g['pick_item_id'],
                'pool_direction_gap_groups':sorted(all_groups),'kept_direction_gap_groups':sorted(kept_groups),'dropped_direction_gap_groups':sorted(all_groups-kept_groups),
                'legacy_region_yaw_alignment_coverage':a['legacy_coverage'],'selected_region_yaw_alignment_coverage':a['selected_coverage']})
write(OUT/'coverage.json',coverage)
# Fixed-prefix decision comparison: fresh local Oracle AST, not stale model responses.
from semantic_pallet_planner.o4.extensions.e5.spatial.config import settings,ARMS
from semantic_pallet_planner.o4.extensions.e5.spatial.planning import choose
from semantic_pallet_planner.o4.extensions.e5.spatial.quality import quality
from semantic_pallet_planner.o4.extensions.e5.backends import LocalCompiler
old=read(REAL/'episodes/E5_SRC02_C0_remote_text_single.json');event=[e for e in old['events'] if 'compilation_metrics' in e][1]
task=next(t for t in read(REAL/'private/tasks.json') if t['task_id']=='E5_SRC02_C0');base=read(REAL/'config.snapshot.json')
comp=LocalCompiler('oracle_ast',task['reference_policy']).compile(event['request'],'fixed_prefix',0)
local=[]
for arm in ARMS:
    cfg=copy.deepcopy(base);cfg['o4_e5_spatial']=settings(arm)
    selected,gs,tr,reason=choose(event['before'],event['request'],comp['response']['policy_ast'],cfg,'single')
    q=quality(event['request'],selected,settings())
    local.append({'arm':arm,'chosen':selected,'aligned_left_available':any(c['pose']=={'x_mm':-105.,'y_mm':-240.,'yaw_deg':0,'z_base_mm':0.} for c in gs[0]['candidates']),
                  'selected_spatial_quality':q,'evaluations':tr['evaluations'],'stop':reason})
write(OUT/'local_decision.json',local)
# Compare legacy source files to the previously sealed real-plan snapshot.
package=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner';frozen=ROOT/'semantic_pallet_planner/outputs/PLAN_O4_E5_090_ONLINE_READY_20261026_01/code_snapshot/semantic_pallet_planner/src/semantic_pallet_planner'
paths=list((package/'o4/extensions/e2').glob('*.py'))+list((package/'o4/extensions/e5').glob('*.py'))+[package/'planner/scoring.py',package/'planner/constraints.py',package/'runners/o4_e5.py']
changed=[];checked=0
for p in paths:
    rel=p.relative_to(package);oldp=frozen/rel
    if not oldp.exists():continue
    checked+=1
    if p.read_bytes()!=oldp.read_bytes():changed.append(str(rel))
assert changed==['o4/extensions/e5/planning.py'],changed
write(OUT/'legacy_source_protection.json',{'checked':checked,'intentional_dispatch_change':changed,'all_other_compared_legacy_sources_unchanged':True})
paired=[]
for task_id in sorted({r['task_id'] for r in records if r['source_kind']=='development_order'}):
    for method in ['single','buffer_search']:
        rs=[r for r in records if r['task_id']==task_id and r['planner']==method and r['backend']=='oracle_ast']
        if not rs:continue
        b=next(r for r in rs if r['arm']=='baseline');n=next(r for r in rs if r['arm']=='combined')
        paired.append({'task_id':task_id,'planner':method,'baseline_items':b['placed_items'],'new_items':n['placed_items'],'delta':n['placed_items']-b['placed_items']})
write(OUT/'paired.json',paired)
write(OUT/'delivery.json',{'acceptance':read(EXP/'acceptance_report.json'),'summary':read(EXP/'metrics/summary.json'),
    'paired':paired,'case_alignment_available':local[-1]['aligned_left_available'],'case_selected_aligned':local[-1]['selected_spatial_quality']['alignment']['aligned_edges']>0,
    'dropped_gap_group_decisions':sum(bool(c['dropped_direction_gap_groups']) for c in coverage),'coverage_decisions':len(coverage),
    'legacy_protection':read(OUT/'legacy_source_protection.json'),'limitations':['known development sources only','fixed footprint probes estimate geometric potential, not hard feasibility','10mm grid is conservative; top support seams may be underestimated','latencies include fixed execution order and caches','new planner opt-in; original real Text/Image scores remain unchanged'],
    'real_api_attempts':0,'historical_batch_recheck':'NOT_RUN'})
print('Saved spatial delivery, local decision, source protection and coverage reports')
