"""Offline JN5 analysis. Only JSON reads, arithmetic and frozen pure rule functions.
Run from repository root with --output a new directory (never overwrites a sealed package).
No project runtime modules are imported. No credentials, network, solver or replay.
"""
import argparse, ast, csv, hashlib, json, math, statistics, sys, shutil
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
import numpy as np

HERE=Path(__file__).resolve().parent
REPO=next(p for p in HERE.parents if (p/'AGENTS.md').exists())
BASE=Path('semantic_pallet_planner/outputs/JEV_JN4_REMAIN24_RUN_20261106_01')
RULE_PATH=Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_reanalysis.py')
METHODS=['local_geometry_test_double','local_first_test_double','jev_no_memory','jev_with_trajectory','jev_with_contrast_experience','jev_with_unrelated_E_control']
SHORT=['geometry','fixed','none','T','E','unrelated_E']
NAMES=dict(zip(METHODS,SHORT))
COMPS=[('T','none'),('E','none'),('E','T'),('E','unrelated_E')]

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(x): return hashlib.sha256(canonical(x).encode()).hexdigest()
def require(ok,reason):
    if not ok: raise RuntimeError(reason)
def stats(xs):
    return {'n':len(xs),'mean':statistics.mean(xs),'median':statistics.median(xs),'observed_min':min(xs),'observed_max':max(xs),'statistical_ci':'NOT_ESTIMATED'} if xs else {'n':0,'mean':'NA','median':'NA','observed_min':'NA','observed_max':'NA','statistical_ci':'NOT_ESTIMATED'}
def quant(xs):
    return {'n':len(xs),'sum':sum(xs),'p50':float(np.percentile(xs,50)) if xs else 'NA','p95':float(np.percentile(xs,95)) if xs else 'NA'}
def action(c): return {k:c[k] for k in ['pick_item_id','pose','oriented_size_mm']}
def normalized_pool(x): return sorted([action(c) for c in x['bundle']['selectable_candidates']],key=canonical)
def chosen(x):
    cid=(x.get('selection') or {}).get('selected_candidate_id')
    return next((c for c in x['bundle']['selectable_candidates'] if c['candidate_id']==cid),None)
def pointer(x,p):
    for token in p.split('/')[1:]:
        token=token.replace('~1','/').replace('~0','~'); x=x[int(token)] if isinstance(x,list) else x[token]
    return x

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=HERE);args=ap.parse_args();out=Path(__import__("os").path.relpath(args.output,Path.cwd()))
    require(not (out/'delivery_manifest.json').exists(),'sealed_output_refuse_overwrite')
    if not out.exists(): out.mkdir(parents=True)
    if out.resolve()!=HERE:
        for n in ['analysis_scope.json','analyze.py','plot.py','verify.py','visual_review.json']:
            shutil.copyfile(HERE/n,out/n)
    inputs={}; evidence=[];checks=[]
    def read(p):
        p=Path(p); data=json.loads(p.read_text());inputs[str(p)]=sha(p); return data
    def ref(p,ptr='',**kw):
        p=Path(p); data=read(p);pointer(data,ptr)
        return {'path':str(p),'sha256':inputs[str(p)],'pointer':ptr,**kw}
    def ev(name,refs,claim): evidence.append({'id':name,'claim':claim,'sources':refs})
    def write(n,x): (out/n).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    def table(n,rows):
        write(n+'.json',rows)
        with (out/(n+'.csv')).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
            for row in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    scope=read(out/'analysis_scope.json')
    for item in scope['inputs']:require(sha(item['path'])==item['sha256'],'scope_input_changed:'+item['path'])
    # Extract ONLY the unchanged pure metric/ranking functions and RULE assignments.
    # This avoids importing runtime, transport, candidates, memory or solver modules.
    source=RULE_PATH.read_text();inputs[str(RULE_PATH)]=sha(RULE_PATH)
    functions={'numeric','sign','pareto','evaluate','task_denominators','metric_view'}
    nodes=[]
    for n in ast.parse(source).body:
        if isinstance(n,ast.FunctionDef) and n.name in functions: nodes.append(n)
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'RULE','RULE_VERSION'} for t in n.targets):nodes.append(n)
    v1=SimpleNamespace(VALID_CATEGORIES=('COMPLETE','EMPTY_POOL','PREDICTED_STATIC_INSTABILITY'),LABEL_RULE={'version':'jev_branch_comparison_rule_v1'})
    env={'math':math,'digest':digest,'require':require,'v1':v1}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(RULE_PATH),'exec'),env)
    (out/'frozen_rule_functions.py').write_text('# Exact AST-selected pure functions from '+str(RULE_PATH)+'\n'+ '\n\n'.join(ast.get_source_segment(source,n) for n in nodes)+'\n')
    write('evaluation_rule.json',env['RULE'])
    rows=read(BASE/'all_36_slots.json'); archive_pairs=read(BASE/'paired_comparisons_v2.json');cov_archive=read(BASE/'coverage_summary.json')
    require(read(BASE/'new_24_slots.json')==rows[12:],'new24_matches_all36')
    observations=read(BASE/'behavior_observations.json')
    require(len(rows)==36 and len({r['job_id'] for r in rows})==36,'36_identity')
    require(len({(r['task_id'],r['method_id']) for r in rows})==36,'task_method_unique')
    metrics=[];views={};layouts={};coverage=[];latencies=[];taskrefs=[]
    for i,r in enumerate(rows):
        root=Path(r['evidence_root']);task=read(root/'task.snapshot.json');m=read(root/'metrics.json');status=read(root/'status.json');layout=read(root/'final_layout.json');config=read(root/'config.snapshot.json')
        require(m==r['metrics'] and status==r['status'],'archive_original_mismatch')
        den=env['task_denominators'](task);l=m['loading'];volume=sum(math.prod(z['oriented_size_mm']) for z in layout);mass=sum(z['mass_kg'] for z in layout)
        require(len(layout)==len({z['item_id'] for z in layout})==l['placed_items'],'placed_identity')
        byid={z['item_id']:z for z in task['items']}
        require(all(z['dimensions_mm']==byid[z['item_id']]['dimensions_mm'] and z['mass_kg']==byid[z['item_id']]['mass_kg'] for z in layout),'placed_task_identity')
        for a,b in [(den['items'],l['planned_items']),(den['mass_kg'],l['planned_mass_kg']),(volume/den['volume_mm3'],l['placed_volume_ratio']),(mass/den['mass_kg'],l['placed_mass_ratio']),(len(layout)/den['items'],l['placed_item_ratio'])]:require(abs(a-b)<1e-8,'denominator_ratio')
        c=task['container'];L,W,H=c['length_mm'],c['width_mm'],c['max_height_mm'];height=max((z['pose']['z_base_mm']+z['oriented_size_mm'][2] for z in layout),default=0)
        require(abs(height-m['actual_height_mm'])<1e-8 and abs(volume/(L*W*H)-m['fixed_container_utilization'])<1e-8,'height_utilization')
        require(abs(volume/(L*W*height)-m['envelope_utilization'])<1e-8,'envelope')
        group='main_v3_R2' if i>=12 else 'supplement_02_v3' if i>=7 else 'history_01_v2' if i<6 else 'history_02_geometry_v2'
        row={k:r[k] for k in ['job_id','task_id','method_id','algorithm','protocol','source_manifest_digest','source_delivery_commit','run','evidence_root']}
        row.update(method=NAMES[r['method_id']],group=group,category=status['category'],termination_reason=r['termination_reason'],completed=m['completed'],stable_complete=m['stable_complete'],**{k:l[k] for k in ['placed_items','planned_items','placed_item_ratio','placed_volume_ratio','placed_mass_ratio','placed_mass_kg']},planned_volume_mm3=den['volume_mm3'],planned_mass_kg=den['mass_kg'],fixed_container_utilization=m['fixed_container_utilization'],actual_height_mm=m['actual_height_mm'],envelope_utilization=m['envelope_utilization'],monitor_statuses=m['monitor_statuses'],monitor_reasons=m['monitor_reasons'],assessable_coverage=m['assessable_coverage'],first_predicted_instability_progress=m['first_predicted_instability_progress'],technical_failure=status['category'] in ['SELECTION_FAILURE','ERROR','COMMIT_FAILURE','TECHNICAL_LIMIT'],range_failure=status['category']=='UNASSESSABLE')
        metrics.append(row);views[(r['task_id'],row['method'])]=(row,env['metric_view'](r,task,config['runtime_identity']['data_identity']));layouts[r['job_id']]=layout
        ds=m['memory_metrics']['decisions'];a=next(z for z in cov_archive if z['job_id']==r['job_id'])
        mapping={'retrieval_nonempty':'qualified_retrieval_nonempty','view_nonempty':'view_nonempty','body_nonempty':'request_body_nonempty','actually_sent_nonempty':'actually_sent_nonempty'}
        for k,v in mapping.items():require(a[k]==sum(bool(z.get(v)) for z in ds),'memory_coverage_mismatch')
        coverage.append({**a,'library_nonempty_decisions':sum(bool(z.get('library_nonempty')) for z in ds),'entry_count_stats':stats([z['entries'] for z in ds]),'chars_stats':stats([z['chars'] for z in ds]),'library_evidence':'/metrics/memory_metrics/decisions/*/library_nonempty','interpretation':'nonempty injection does not prove effective use'})
        latencies.append({'job_id':r['job_id'],'group':group,'stage_latency_s':m['latency_s'],'api_latency_s':m['cost']['request_latency_s'],'active_wall_s':m['failure_location']['active_wall_s'],'note':'stored per-job quantiles; no averaging quantiles'})
        taskrefs.extend([ref(root/'task.snapshot.json','/items',job_id=r['job_id']),ref(root/'metrics.json','/loading',job_id=r['job_id']),ref(root/'final_layout.json','',job_id=r['job_id']),ref(root/'status.json','/category',job_id=r['job_id'])])
    mainrows=[r for r in metrics if r['group']=='main_v3_R2'];require(len(mainrows)==24 and len({r['algorithm'] for r in mainrows})==len({r['source_manifest_digest'] for r in mainrows})==1,'main_identity')
    require({r['task_id'] for r in mainrows}==set(scope['main_tasks']),'main_tasks')
    for task in scope['main_tasks']:require({r['method'] for r in mainrows if r['task_id']==task}==set(SHORT),'six_methods')
    table('all_36_metrics',metrics);table('main_24_metrics',mainrows);table('historical_and_partial_metrics',[r for r in metrics if r not in mainrows]);table('memory_coverage',coverage);table('latency_by_job',latencies)
    pairs=[]
    for task in sorted({r['task_id'] for r in metrics}):
        for alt,reference in COMPS:
            a,av=views[(task,reference)];b,bv=views[(task,alt)]
            result=env['evaluate'](av,bv,rule_version=env['RULE_VERSION']) if a['algorithm']==b['algorithm'] else {'comparison_valid':False,'label_v2':'INVALID_CROSS_VERSION','decisive_level':'INVALID'}
            archived=next(z for z in archive_pairs if z['task_id']==task and z['comparison']==alt+'/'+reference)
            require(result==archived['evaluation'],'pair_archive_disagreement')
            fields=['placed_item_ratio','placed_volume_ratio','placed_mass_ratio','fixed_container_utilization','actual_height_mm','envelope_utilization','placed_items','placed_mass_kg']
            delta={k: b[k]-a[k] for k in fields}
            pairs.append({'task_id':task,'comparison':alt+'/'+reference,'group':a['group'],'reference_job':a['job_id'],'alternative_job':b['job_id'],'reference_values':{k:a[k] for k in fields},'alternative_values':{k:b[k] for k in fields},'delta':delta,'volume_delta_pp':100*delta['placed_volume_ratio'],'item_ratio_delta_pp':100*delta['placed_item_ratio'],'mass_ratio_delta_pp':100*delta['placed_mass_ratio'],'height_delta_mm':delta['actual_height_mm'],'evaluation':result})
    mainpairs=[p for p in pairs if p['group']=='main_v3_R2'];require(len(mainpairs)==16,'16_pairs')
    require(all(p['evaluation']['comparison_valid'] for p in mainpairs),'main_pairs_valid')
    require(not next(p for p in pairs if p['task_id']=='SYN_COMBO_02' and p['comparison']=='E/unrelated_E')['evaluation']['comparison_valid'],'timeout_not_ranked')
    table('main_16_pairs',mainpairs);table('historical_and_partial_pairs',[p for p in pairs if p not in mainpairs])
    # Explicitly record nonregistered cross-version/invalid comparisons, without ranks.
    write('comparison_exclusions.json',{'SYN_COMBO_02_geometry_vs_v3':'INVALID_CROSS_VERSION; NOT_RANKED','SYN_COMBO_02_E_vs_unrelated_E':'invalid alternative/reference technical category; NOT_RANKED','historical_scope':'SYN_COMBO_01 v2 excluded from main summary'})
    numeric_fields=['placed_item_ratio','placed_volume_ratio','placed_mass_ratio','fixed_container_utilization','actual_height_mm','envelope_utilization','placed_items']
    summary=[{'method':method,'task_ids':scope['main_tasks'],'metrics':{f:stats([r[f] for r in mainrows if r['method']==method]) for f in numeric_fields}} for method in SHORT]
    ps=[{'comparison':alt+'/'+reference,'task_ids':scope['main_tasks'],'label_counts':dict(Counter(p['evaluation']['label_v2'] for p in mainpairs if p['comparison']==alt+'/'+reference)),'metrics':{f:stats([p[f] for p in mainpairs if p['comparison']==alt+'/'+reference]) for f in ['volume_delta_pp','item_ratio_delta_pp','mass_ratio_delta_pp','height_delta_mm']}} for alt,reference in COMPS]
    table('method_summary',summary);table('pair_summary',ps)
    ev('P01_F1_F2_MAIN_AND_HISTORY',taskrefs,'Full-order denominators reconstructed from saved tasks and layouts; main 4x6 v3 identity and all 36 statuses. All main/supplement/historical pair labels match frozen v2 rule and archived results.')
    # Ledger samples are scoped by run, never by attempt ID globally.
    budget=read(BASE/'budget_accounting.json');runstats=[];total=Counter();usage=Counter();allsamples=[];ledger_refs=[]
    for entry in budget['per_run']:
        run=Path(entry['run']);summary_run=read(run/'summary.json');req=read(run/'request_ledger/requests.json')['requests'];rs=summary_run['request_statistics'];require(rs==entry['statistics'],'budget_run_summary')
        require(len(req)==rs['send_reservations'],'reservations')
        require(sum(r['state']=='UNKNOWN_SEND' for r in req)==rs['unknown_real_send_count'],'unknown_send')
        require(sum(r.get('selection') is not None and r['state']!='UNKNOWN_SEND' for r in req)==rs['known_real_model_calls'],'known_calls')
        us={k:sum((r.get('selection') or {}).get('usage',{}).get(k,0) for r in req if (r.get('selection') or {}).get('usage')) for k in ['input_tokens','output_tokens']}
        require(all(us[k]==rs['usage'][k] for k in us),'ledger_usage')
        samples=[{'attempt_id':r['attempt_id'],'decision_id':r['decision_id'],'state':r['state'],'latency_s':r['transport']['latency_s']} for r in req if r['transport'] and isinstance(r['transport'].get('latency_s'),(int,float))]
        allsamps=[r['latency_s'] for r in samples];allsamples.extend(allsamps)
        runstats.append({'run':str(run),'statistics':rs,'api_samples_quantiles':quant(allsamps),'api_samples':samples,'state_counts':dict(Counter(r['state'] for r in req))})
        total.update({k:rs[k] for k in ['send_reservations','network_attempts','known_real_model_calls','unknown_real_send_count']});usage.update(rs['usage'])
        ledger_refs.append(ref(run/'request_ledger/requests.json','/requests'))
    for k,v in total.items():require(v==budget['cumulative'][k],'cumulative_'+k)
    require(dict(usage)==budget['cumulative']['usage'],'cumulative_usage')
    write('cost_and_api_latency.json',{'per_run':runstats,'cumulative':budget['cumulative'],'pooled_actual_transport_latency_s':quant(allsamples),'latency_scope':'saved transport outcomes incl 1 timeout; no average of job/run quantiles','validation_wall_clock':read(BASE/'saved_validation.json'),'jn5_new':scope['operations']})
    ev('COST_USAGE_UNKNOWN',ledger_refs+[ref(BASE/'budget_accounting.json','/cumulative'),ref(BASE/'unknown_sends.json','/0')],'Historical accounting and actual transport samples; UNKNOWN_SEND preserved; costs UNKNOWN; JN5 incremental execution zero.')
    write('coverage_and_status.json',{'all36_statuses':dict(Counter(r['category'] for r in metrics)),'main24_statuses':dict(Counter(r['category'] for r in mainrows)),'all36_monitor_statuses':dict(sum((Counter(r['monitor_statuses']) for r in metrics),Counter())),'main24_monitor_statuses':dict(sum((Counter(r['monitor_statuses']) for r in mainrows),Counter())),'statistical_ci':'NOT_ESTIMATED','unit_of_observation':'4 task-level observations, shared prototypes, one run/method/task'})
    # F3: every actually committed selected action is connected to input, immutable map,
    # raw response ledger, selection, monitor and saved commit/final layout.
    f3=[];sequences={};ledger=read(Path(mainrows[0]['run'])/'request_ledger/requests.json')['requests']
    for jid in ['J0014','J0015','J0016']:
        row=next(r for r in metrics if r['job_id']==jid);root=Path(row['evidence_root']);seq=[];refs=[];traces=[]
        for p in sorted((root/'actions').glob('*.json')):
            x=read(p);seq.append((p,x));candidate=chosen(x)
            if x['event']!='PLACE':continue
            commit_path=root/'stages'/x['decision_id']/'COMMITTED.json';commit=read(commit_path)
            require(candidate is not None and x['monitor']['status']=='STABLE' and commit['phase']=='COMMITTED' and commit['state']==x['after'] and len(x['after']['placed_items'])==len(x['before']['placed_items'])+1,'F3_commit_monitor')
            refs.append(ref(commit_path,'/state/placed_items',job_id=jid,decision_id=x['decision_id']))
            selected=x['selection'];label=selected['selected_display_id'];require(x['context']['display_mapping'][label]['candidate_id']==candidate['candidate_id'],'mapping')
            idx=next(i for i,z in enumerate(layouts[jid]) if z['item_id']==candidate['pick_item_id']);require(action(candidate)=={'pick_item_id':layouts[jid][idx]['item_id'],'pose':layouts[jid][idx]['pose'],'oriented_size_mm':layouts[jid][idx]['oriented_size_mm']},'layout_action')
            refs += [ref(p,ptr,job_id=jid,decision_id=x['decision_id']) for ptr in ['/bundle/selectable_candidates','/context/display_mapping','/context/model_state','/context/request_body','/selection','/monitor','/after/placed_items']]
            attemptids=selected['attempt_ids'];raw=[]
            for aid in attemptids:
                k=next(i for i,z in enumerate(ledger) if z['job_id']==jid and z['attempt_id']==aid)
                require(ledger[k]['selection']['selected_candidate_id']==candidate['candidate_id'],'raw_response_selection')
                raw.append(ref(Path(row['run'])/'request_ledger/requests.json',f'/requests/{k}/transport',job_id=jid,decision_id=x['decision_id'],attempt_id=aid))
            refs+=raw
            archived_decision=next(d for z in observations if z['job_id']==jid for d in z['decisions'] if d['decision_id']==x['decision_id'])
            require(archived_decision['selected_box']==candidate['pick_item_id'] and archived_decision['selected_pose']==candidate['pose'],'behavior_archive_action')
            traces.append({'decision_id':x['decision_id'],'display_id':label,'candidate_id':candidate['candidate_id'],'exact_action':action(candidate),'final_layout_index':idx,'raw_response_sources':raw,'monitor_status':x['monitor']['status'],'committed':True})
        require(len(traces)==len(layouts[jid]),'F3_all_boxes_traced');sequences[jid]=seq
        refs.append(ref(root/'final_layout.json'))
        ev('F3_'+jid,refs,'Each rendered box is an actual saved STABLE commit, connected to public request/candidate map and real output; final layout is not regenerated.')
        f3.append({'job_id':jid,'method':row['method'],'layout':layouts[jid],'container':read(root/'task.snapshot.json')['container'],'metrics':row,'committed_action_trace':traces})
    # First divergence: compare exact physical public pre-state and normalized pool;
    # metadata, observation event IDs and presentation labels are not action identity.
    divergences=[]
    for jid in ['J0015','J0016']:
        base=[z for z in sequences['J0014'] if chosen(z[1])];alt=[z for z in sequences[jid] if chosen(z[1])]
        for (p,a),(q,b) in zip(base,alt):
            ca,cb=chosen(a),chosen(b)
            if action(ca)==action(cb):continue
            fields=['container','placed_items','pending_items','arrived_ids','arrival_count','buffer_capacity','attributes','end_of_stream']
            sa={k:a['before'][k] for k in fields};sb={k:b['before'][k] for k in fields}
            pa,pb=normalized_pool(a),normalized_pool(b)
            shared=sa==sb and pa==pb
            d={'reference_job':'J0014','alternative_job':jid,'reference_decision':a['decision_id'],'alternative_decision':b['decision_id'],'same_physical_public_state':sa==sb,'same_normalized_selectable_action_pool':pa==pb,'physical_state_digests':[digest(sa),digest(sb)],'normalized_pool_digests':[digest(pa),digest(pb)],'pool_sizes':[len(pa),len(pb)],'same_state_choice_difference_supported':shared,'action_relation':'same_box_different_pose' if ca['pick_item_id']==cb['pick_item_id'] else 'different_box','reference_action':action(ca),'alternative_action':action(cb),'alternative_public_selected_features':cb.get('support'),'reference_visible_items':[z['item'] for z in a['before']['pending_items']],'reference_memory_entries':a['context']['memory_view']['entries'],'alternative_memory_entries':b['context']['memory_view']['entries'],'interpretation':'observed action difference; memory use/causation NOT_ESTABLISHED; later diverged trajectories are not same-pool counterfactuals','reason_explanation_status':'ANALYSIS_HYPOTHESIS'}
            divergences.append(d);ev('BEHAVIOR_FIRST_'+jid,[ref(p,'/before'),ref(q,'/before'),ref(p,'/bundle/selectable_candidates'),ref(q,'/bundle/selectable_candidates'),ref(p,'/context/memory_view'),ref(q,'/context/memory_view'),ref(p,'/selection'),ref(q,'/selection')],'First exact-action divergence; same public physical state/action pool claim is conditional on recorded equality checks. No causal mechanism inferred.');break
    write('first_divergence.json',divergences);write('F3_plot_data.json',f3)
    # Fixed old failure cases; no new monitor/candidate construction.
    r6=Path(metrics[6]['evidence_root']);p6=r6/'actions/J0006_D0014.json';x=read(p6);c=chosen(x)
    require(x['before']==x['after'] and not x['monitor']['committed'],'failed_candidate_not_committed')
    r11=Path(metrics[11]['evidence_root']);p11=r11/'actions/J0011_D0006.json';y=read(p11)
    require(y['before']==y['after'] and y['monitor'] is None and y['selection']['selected_candidate_id'] is None,'timeout_no_commit')
    ledger1=read(Path(metrics[11]['run'])/'request_ledger/requests.json')['requests'];index=next(i for i,z in enumerate(ledger1) if z['attempt_id']=='A000057');require(ledger1[index]['state']=='UNKNOWN_SEND','unknown_preserved')
    # Exact y section through center of candidate; keep only intersecting saved boxes.
    cy=c['pose']['y_mm'];section=[z for z in x['before']['placed_items'] if z['pose']['y_mm']-z['oriented_size_mm'][1]/2 <= cy <= z['pose']['y_mm']+z['oriented_size_mm'][1]/2]
    case4={'gap':{'job_id':'J0006','decision_id':x['decision_id'],'method':'geometry','algorithm':'pct_contact_network_v2','status':'UNASSESSABLE','reason':x['monitor']['result']['reason_code'],'before_layout':x['before']['placed_items'],'section_y_mm':cy,'section_boxes':section,'candidate':c,'candidate_committed':False,'monitor_evaluated_pose':x['monitor']['result']['evaluated_pose'],'height_delta_mm':x['monitor']['result']['height_delta_mm'],'progress':metrics[6]},'timeout':{'job_id':'J0011','decision_id':y['decision_id'],'attempt_id':'A000057','status':'SELECTION_FAILURE','reason':y['reason'],'selection':y['selection'],'monitor':None,'placed_before':len(y['before']['placed_items']),'placed_after':len(y['after']['placed_items']),'planned_items':metrics[11]['planned_items'],'ledger_state':'UNKNOWN_SEND','new_action_submitted':False}}
    write('F4_plot_data.json',case4)
    ev('F4_GAP',[ref(p6,p) for p in ['/before/placed_items','/bundle/selectable_candidates','/context/model_state','/selection','/monitor/result/evaluated_pose','/monitor/result/height_delta_mm','/monitor/committed','/after/placed_items']],'J0006_D0014 old v2 exact under-gap placement z=0 vs restored z=490: UNASSESSABLE POSE_HEIGHT_MISMATCH; candidate not submitted. No actual collapse claim.')
    ev('F4_TIMEOUT',[ref(p11,p) for p in ['/selection','/before/placed_items','/after/placed_items','/monitor']]+[ref(Path(metrics[11]['run'])/'request_ledger/requests.json',f'/requests/{index}')],'A000057/J0011_D0006 unknown send timeout; 6/20 committed; no selected new action or monitor/commit; invalid comparison retained.')
    ev('MEMORY_COVERAGE',[ref(BASE/'coverage_summary.json'),ref(BASE/'all_36_slots.json','/15/metrics/memory_metrics'),ref(BASE/'all_36_slots.json','/16/metrics/memory_metrics')],'Library/retrieval/view/body/actual-send/singleton are separately counted, no implication of effective use.')
    write('evidence_index.json',{'version':'jev_jn5_evidence_index_v1','path_base':'repository root','entries':evidence,'generated_artifacts':{'F1':['main_24_metrics.json','main_24_metrics.csv'],'F2':['main_16_pairs.json','main_16_pairs.csv'],'F3':['F3_plot_data.json','first_divergence.json'],'F4':['F4_plot_data.json']}})
    # Input immutability includes all consumed originals; scope local path is excluded
    # from historical-original claim, but its own initial digest is also preserved.
    require(all(sha(p)==h for p,h in inputs.items()),'consumed_input_changed')
    write('input_manifest.json',{'files':[{'path':p,'sha256':h} for p,h in sorted(inputs.items())]})
    checks=['36 unique jobs and task/method slots','saved originals equal aggregate metrics/status','full-order denominators, volume/mass/count ratios, heights/utilizations reconstructed','main 4x6 same v3 and source manifest','16 main pairs valid, delta alternative-reference, labels equal frozen archive','technical timeout invalid; cross-version excluded','ledger reservations, known/unknown, usage and cumulative totals agree','memory nonempty counts agree with archived coverage','F3 all boxes mapped to candidate/public input/real response/monitor/commit','first exact-action divergence checked using public physical state and normalized pool','F4 failed/unknown action no commit verified','all consumed input sha256 unchanged']
    write('analysis_checks.json',{'checks':[{'check':c,'status':'PASS'} for c in checks],'scope':'this local offline computation; no historical experiment rerun, no full validate-run','zero_operations':scope['operations']})
    print(json.dumps({'main_rows':len(mainrows),'main_pairs':len(mainpairs),'labels':{p['comparison']:p['label_counts'] for p in ps},'divergences':[{k:d[k] for k in ['alternative_job','reference_decision','alternative_decision','same_state_choice_difference_supported','action_relation']} for d in divergences],'checks':len(checks)},ensure_ascii=False))
if __name__=='__main__':main()
