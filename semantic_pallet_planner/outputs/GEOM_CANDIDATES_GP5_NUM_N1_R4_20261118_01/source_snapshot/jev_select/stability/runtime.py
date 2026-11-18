"""Bounded local CLI and saved-record verification, reusing the shared runner."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import copy
import hashlib
import platform
import shutil
import subprocess
import sys

from ..contracts import digest,JevSelectError,validate_schema
from ..ledger import read,write,exclusive
from .monitor import load_monitor_config,preflight,validate_checkpoint


def require(ok,code):
    if not ok:raise JevSelectError(code)


def environment():
    import numpy
    return {'python':sys.version,'executable':sys.executable,'platform':platform.platform(),
            'numpy':numpy.__version__,
            'numpy_core_sha256':hashlib.sha256(Path(numpy._core._multiarray_umath.__file__).read_bytes()).hexdigest()}


def smoke(dataset,output,*,enabled=None,options=None,event_limit=8):
    from ..dataset_j4 import offline_dataset_guard
    from ..packaging_runtime import load_runtime_dataset,LocalPackagingDouble,summary,physical_manifest
    from ..episode import run_episode
    from ..experiment import source_manifest,file_manifest
    repo=Path(__file__).resolve().parents[5];root=Path(output).resolve();allowed=repo/'semantic_pallet_planner/outputs'
    require(root.is_relative_to(allowed) and root!=allowed,'monitor_output_directory')
    require(not root.exists(),'monitor_output_exists')
    require(type(event_limit) is int and 1<=event_limit<=8,'monitor_smoke_event_limit')
    require(subprocess.run(['git','check-ignore','-q',str(root)],cwd=repo).returncode==0,'monitor_output_not_ignored')
    with offline_dataset_guard() as counters:
        data=load_runtime_dataset(dataset)
        key=min(t['source_order_key'] for t in data['tasks'])
        tasks=[next(t for t in data['tasks'] if t['source_order_key']==key and t['layer']==layer)
               for layer in ('source_difficult','controlled_heterogeneous')]
        configs=[load_monitor_config(data_identity=data['data_identity'],task_digest=digest(t),
                  enabled=enabled,monitor_config=options) for t in tasks]
        # All startup checks happen before a run directory or selection is created.
        for cfg in configs:preflight(cfg)
        root.mkdir(parents=True)
        with exclusive(root):
            write(root/'scope.json',{'version':'packaging_monitor_smoke_v1','dataset':str(Path(dataset).resolve()),
                'data_identity':data['data_identity'],'selected_task_ids':[t['task_id'] for t in tasks],
                'event_limit':event_limit,'enabled':configs[0]['stability_monitor']['enabled'],
                'origin':'LOCAL_TEST_DOUBLE_NOT_JEV','full_order_rollout':False})
            write(root/'environment.json',environment())
            write(root/'physical_manifest.json',physical_manifest())
            write(root/'target_one_receipt.json',{'handoff':data['target_one_handoff'],
                'manifest_sha256':hashlib.sha256((Path(dataset)/'manifest.json').read_bytes()).hexdigest()})
            for i,(task,cfg) in enumerate(zip(tasks,configs)):
                jid=f'P{i:02d}';job=root/'jobs'/jid
                write(job/'task.snapshot.json',task);write(job/'config.snapshot.json',cfg)
                def checkpoint(cp):
                    write(job/'checkpoint.json',cp)
                    # Each durable stage is retained for review, alongside the
                    # atomic checkpoint which owns both state and commit status.
                    if cp['pending_event'] is not None:
                        ev=cp['pending_event'];write(job/'stages'/ev['decision_id']/(cp['phase']+'.json'),cp)
                ep=run_episode(task,LocalPackagingDouble(cfg['selector']),cfg,job_id=jid,method=cfg['selector'],
                    on_checkpoint=checkpoint,event_limit=event_limit)
                write(job/'checkpoint.json',ep['checkpoint']);write(job/'episode.json',ep)
                metrics=summary(task,cfg,cfg['selector'],ep['final_state'],ep['events'],
                    ep['checkpoint']['reason'] or 'SMOKE_EVENT_LIMIT_NOT_ORDER_TERMINATION')
                write(job/'metrics.json',metrics)
                for e in ep['events']:
                    if e.get('decision_id'):write(job/'actions'/f"{e['decision_id']}.json",e)
            write(root/'offline_guards.json',dict(counters))
            source=source_manifest();write(root/'source_manifest.json',source)
            package=Path(__file__).resolve().parents[2]
            for name in source:
                target=root/'code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(package/name,target)
            write(root/'aggregate.json',aggregate(root))
        # Lock file is part of final artifact, immutable after release.
        write(root/'delivery_manifest.json',file_manifest(root))
        return validate(root)


def aggregate(root):
    rows=[read(p) for p in sorted(Path(root).glob('jobs/*/metrics.json'))]
    terms=Counter(r['termination_reason'] for r in rows)
    counts={k:sum(r['monitor_statistics'][k] for r in rows) for k in
        ('planned_orders','selected_actions','actual_assessments','saved_result_reuses','successful_commits')}
    statuses={k:sum(r['monitor_statistics']['statuses'][k] for r in rows) for k in
        ('DISABLED','STABLE','UNSTABLE','UNASSESSABLE','ERROR')}
    categories=Counter(r['monitor_statistics']['termination_category'] for r in rows)
    counts.update(statuses=statuses,termination_counts=dict(terms),
        termination_categories={k:categories[k] for k in ('COMPLETE','PREDICTED_STATIC_INSTABILITY','MONITOR_UNASSESSABLE','MONITOR_ERROR','EMPTY_POOL','SELECTION_ERROR','COMMIT_ERROR','SMOKE_EVENT_LIMIT')},
        completed_orders=sum(r['completed'] for r in rows),
        stable_complete_rate=(sum(r['monitor_statistics']['stable_complete_rate'] for r in rows)/len(rows)
            if rows and rows[0]['stability_algorithm']!='DISABLED' else 'NOT_APPLICABLE'),
        coverage='bounded prefix only; every planned task remains in denominator',
        actual_order_coverage='NOT_ESTABLISHED',policy_effect='NOT_MEASURED')
    return counts


def validate(root):
    """Authenticate saved records only: no candidate generation, selection or LP."""
    from ..experiment import source_manifest,file_manifest
    from ..packaging_runtime import summary,physical_manifest,load_runtime_dataset
    from ..dataset_j4 import offline_dataset_guard
    root=Path(root).resolve()
    with offline_dataset_guard():
        require(file_manifest(root)==read(root/'delivery_manifest.json'),'monitor_delivery_digest_changed')
        require(source_manifest()==read(root/'source_manifest.json'),'monitor_source_changed_use_frozen_snapshot')
        for name,sha in read(root/'source_manifest.json').items():
            require(hashlib.sha256((root/'code_snapshot'/name).read_bytes()).hexdigest()==sha,'monitor_snapshot_changed')
        scope=read(root/'scope.json');data=load_runtime_dataset(scope['dataset'])
        require(scope['data_identity']==data['data_identity'],'monitor_dataset_changed')
        key=min(t['source_order_key'] for t in data['tasks'])
        expected=[next(t for t in data['tasks'] if t['source_order_key']==key and t['layer']==layer)
                  for layer in ('source_difficult','controlled_heterogeneous')]
        require(scope['selected_task_ids']==[t['task_id'] for t in expected] and
                type(scope['enabled']) is bool and 1<=scope['event_limit']<=8 and
                scope['full_order_rollout'] is False,'monitor_scope_changed')
        require(read(root/'physical_manifest.json')==physical_manifest(),'monitor_physics_changed')
        for i,task in enumerate(expected):
            jid=f'P{i:02d}';job=root/'jobs'/jid
            require(read(job/'task.snapshot.json')==task,'monitor_task_changed')
            cfg=read(job/'config.snapshot.json')
            require(cfg==load_monitor_config(data_identity=data['data_identity'],task_digest=digest(task),
                method=cfg['selector'],enabled=scope['enabled']),'monitor_config_changed')
            cp=read(job/'checkpoint.json');ep=read(job/'episode.json')
            validate_checkpoint(cp,task,cfg,jid,cfg['selector'])
            require(cp==ep['checkpoint'] and cp['state']==ep['final_state'] and cp['events']==ep['events'] and
                    len(cp['events'])<=scope['event_limit'],'monitor_episode_changed')
            for e in cp['events']:
                if e.get('decision_id'):
                    require(read(job/'actions'/f"{e['decision_id']}.json")==e,'monitor_action_changed')
            for stage in sorted((job/'stages').glob('*/*.json')):
                saved=read(stage);validate_checkpoint(saved,task,cfg,jid,cfg['selector'])
                require(saved['events']==cp['events'][:len(saved['events'])],'monitor_stage_prefix_changed')
                pending=saved['pending_event'];final=next(e for e in cp['events'] if e.get('decision_id')==pending['decision_id'])
                for k in ('proposed_action','selection','context','bundle','before'):
                    require(pending[k]==final[k],'monitor_saved_stage_changed')
                if pending['monitor'] is not None:require(pending['monitor']==final['monitor'],'monitor_saved_result_overwritten')
            metrics=summary(task,cfg,cfg['selector'],cp['state'],cp['events'],
                cp['reason'] or 'SMOKE_EVENT_LIMIT_NOT_ORDER_TERMINATION')
            require(metrics==read(job/'metrics.json'),'monitor_metrics_changed')
        require(aggregate(root)==read(root/'aggregate.json'),'monitor_aggregate_changed')
        return {'status':'PASS','verification':'saved records; no solver, selector or candidate generation',
                'jobs':len(expected),'aggregate':aggregate(root),'output':str(root)}
