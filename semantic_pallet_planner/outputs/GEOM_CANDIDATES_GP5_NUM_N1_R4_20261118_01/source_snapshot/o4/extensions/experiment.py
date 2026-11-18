"""Sealed E0/E1 development plan and full offline experiment orchestration."""
import copy
import hashlib
import shutil
from pathlib import Path
from ..common import O4Error, read, write, digest
from ...config import load_config, generator_config
from . import validation
from .data import dataset
from .compiler import compile_policy
from .protocol import observation
from .runtime import evaluate_candidates
from .reference import audit
from .planning import METHODS
from .episode import episode, stable, verify_episode
from .visual import render, facts
from .visual_verify import verify as verify_image

VERSION='o4_e0_e1_development_v1'


def files(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob('*')) if p.is_file() and '__pycache__' not in p.parts
            and p.name!='delivery_manifest.json'}


def seal(root):
    write(Path(root)/'delivery_manifest.json',{'files':files(Path(root))})


def verify_seal(root):
    root=Path(root)
    expected=read(root/'delivery_manifest.json')['files']
    if files(root)!=expected:raise O4Error('sealed_artifact_changed',str(root))
    return len(expected)


def new_output(path, protected=()):
    p=Path(path).resolve()
    package=Path(__file__).resolve().parents[2]
    workspace=package.parents[2]
    forbidden=[workspace/'semantic_pallet_planner'/name for name in ('src','tests','configs')]
    forbidden += [workspace/'semantic_pallet_dataset_v1',workspace/'.git']
    sealed_parent=any((parent/'delivery_manifest.json').exists() for parent in p.parents)
    if p.exists() or sealed_parent or any(p.is_relative_to(Path(x).resolve()) or Path(x).resolve().is_relative_to(p) for x in (*protected,package,*forbidden)):
        raise O4Error('unsafe_output','new nonoverlapping output directory required')
    p.mkdir(parents=True)
    return p


def prepare(output):
    root=new_output(output)
    data=dataset();config=generator_config(load_config())
    package=Path(__file__).resolve().parents[2]
    workspace=package.parents[2]
    extension_config=read(workspace/'semantic_pallet_planner/configs/o4_e1_offline_v1.json')
    from .planning import SEARCH
    from .candidates import VERSION as candidate_version
    if (extension_config['search']!=SEARCH or extension_config['planners']!=list(METHODS)
            or extension_config['spatial_eps_mm']!=1e-6 or extension_config['yaw_degrees']!=[0,90]
            or extension_config['per_object_top_k']!=16 or extension_config['candidate_version']!=candidate_version):
        raise O4Error('unsupported_extension_config','E1 capability constants must match frozen implementation')
    config['o4_e1']=extension_config
    write(root/'private/data.json',data);write(root/'config.snapshot.json',config)
    for rel in ('docs/04_运行与复核手册/O4E0与E1区域约束运行及验收手册_20261025.md',
                'docs/03_阶段产出分析/O4/O4E0与E1区域约束开发与离线验收_20261025.md',
                'docs/02_阶段实施方案/O4/O4E区域相对位置与朝向扩展开发及验收规范_20261025.md'):
        target=root/'documentation'/Path(rel).name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(workspace/rel,target)
    import contextlib,io
    from ...runners.o4_extensions import main
    help_text=io.StringIO()
    with contextlib.redirect_stdout(help_text):
        try:main(['--help'])
        except SystemExit as exc:
            if exc.code!=0:raise
    (root/'documentation/cli_help.txt').write_text(help_text.getvalue())
    source=root/'code_snapshot/semantic_pallet_planner/src/semantic_pallet_planner'
    shutil.copytree(package,source,ignore=shutil.ignore_patterns('__pycache__'))
    plan={'version':VERSION,'capability':'o4_e1_v1','e4_status':'OUT_OF_SCOPE',
          'placement_convention':'upright_label_pos_z_v1','data_digest':digest(data),'config_digest':digest(config),
          'jobs':[{'job_id':f'E1_{i:03d}_{b}_{m}','task_id':t['task_id'],'backend':b,'planner':m}
                  for i,t in enumerate(data['constructs']) for b in ('public_parser','oracle_ast') for m in METHODS],
          'planned_gold':24,'planned_invalid':12,'planned_pair_records':48,'planned_episodes':96,
          'planned_oracle_repeats':48,'planned_oracle_restores':48,'new_api_attempts':0,
          'source_files':files(package)}
    write(root/'plan.json',plan);seal(root)
    return {'status':'PASS','plan':str(root),'planned_episodes':96,'new_api_attempts':0}


def validate_plan(root):
    root=Path(root);verify_seal(root)
    plan=read(root/'plan.json');data=read(root/'private/data.json');config=read(root/'config.snapshot.json')
    if plan['version']!=VERSION or plan['data_digest']!=digest(data) or plan['config_digest']!=digest(config):
        raise O4Error('invalid_plan_binding')
    source=Path(__file__).resolve().parents[2]
    if files(source)!=plan['source_files']:
        raise O4Error('code_snapshot_mismatch','use the sealed plan code_snapshot as PYTHONPATH')
    expected=[{'job_id':f'E1_{i:03d}_{b}_{m}','task_id':t['task_id'],'backend':b,'planner':m}
              for i,t in enumerate(data['constructs']) for b in ('public_parser','oracle_ast') for m in METHODS]
    if plan['jobs']!=expected:raise O4Error('invalid_plan_jobs')
    return plan,data,config


def run(plan_root, output, protection=None):
    plan_root=Path(plan_root).resolve();plan,data,config=validate_plan(plan_root)
    root=new_output(output,(plan_root,))
    shutil.copy2(plan_root/'plan.json',root/'plan.json')
    shutil.copy2(plan_root/'config.snapshot.json',root/'config.snapshot.json')
    write(root/'private/data.json',data)
    write(root/'manifest.json',{'version':VERSION,'plan_root':str(plan_root),
                               'plan_delivery_digest':digest(read(plan_root/'delivery_manifest.json')),
                               'evaluator_version':'o4_e1_independent_evaluator_v1','new_api_attempts':0,
                               'real_compile_status':'NOT_RUN','real_online_status':'NOT_RUN',
                               'unseen_generalization':'NOT_MEASURED','visual_increment':'NOT_MEASURED','e4_status':'OUT_OF_SCOPE'})
    gold=validation.gold(data['gold']);bad=validation.invalid(data['invalid'],data['gold'][0]['request'])
    pairs,pair_checks=validation.pairs(data['pairs']);regression=validation.regression()
    write(root/'metrics/gold.json',gold);write(root/'metrics/invalid.json',bad)
    write(root/'metrics/pairs.json',pairs);write(root/'metrics/pair_checks.json',pair_checks)
    write(root/'metrics/legacy_regression.json',regression)
    asset_cache={};visual_records=[]
    def image_for(req):
        f=facts(req);identity=digest(f)
        if identity not in asset_cache:
            asset_cache[identity]=render(req,root,f'public/images/{identity[:24]}.png')
        asset=asset_cache[identity]
        result=verify_image(req,root,asset)
        visual_records.append({'observation_digest':req['observation_digest'],'asset':asset,**result})
    for g in data['gold']:image_for(g['request'])
    for p in data['pairs']:
        for v in p['variants']:image_for(v['request'])
    rows=[];checks=[];repeated=[];restored=[];coverage=[]
    tasks={t['task_id']:t for t in data['constructs']}
    for job in plan['jobs']:
        task=tasks[job['task_id']];result=episode(task,job['backend'],job['planner'],config)
        checkpoint=result.pop('checkpoints')[1]
        audit_result=verify_episode(result,task,config)
        checks.append({'job_id':job['job_id'],**audit_result})
        rows.append({'job_id':job['job_id'],**result['summary']})
        write(root/f"episodes/{job['job_id']}.json",result)
        for e in result['events']:
            if 'request' in e:
                image_for(e['request'])
                for g in e['groups']:
                    old_allowed=evaluate_candidates(e['request'],e['response']['policy_ast'],g['generation']['baseline_candidates'])['allowed_ids']
                    coverage.append({'job_id':job['job_id'],'pick_item_id':g['pick_item_id'],
                                     'baseline_allowed_count':len(old_allowed),'extended_allowed_count':len(g['evaluation']['allowed_ids']),
                                     'physical_enumeration_count':g['generation']['public_enriched_physical_count'],
                                     'topk_truncated':g['generation']['topk_truncated']})
        if job['backend']=='oracle_ast':
            repeat=episode(task,job['backend'],job['planner'],config);repeat.pop('checkpoints')
            restored_result=episode(task,job['backend'],job['planner'],config,resume=checkpoint);restored_result.pop('checkpoints')
            repeated.append({'job_id':job['job_id'],'passed':stable(repeat)==stable(result),'stable_digest':digest(stable(repeat))})
            restored.append({'job_id':job['job_id'],'passed':stable(restored_result)==stable(result),'stable_digest':digest(stable(restored_result))})
            write(root/f"repeats/{job['job_id']}.json",repeat)
            write(root/f"restores/{job['job_id']}.json",{'checkpoint':checkpoint,'result':restored_result})
    write(root/'metrics/episodes.json',rows);write(root/'audit/episode_recomputation.json',checks)
    write(root/'audit/repeats.json',repeated);write(root/'audit/restores.json',restored)
    write(root/'metrics/candidate_coverage.json',coverage);write(root/'audit/visual.json',visual_records)
    from .faults import run_faults
    faults=run_faults(data,config,root)
    write(root/'audit/faults.json',faults)
    # Catch source mutation during a long run; frozen snapshots are preferred.
    if files(Path(__file__).resolve().parents[2])!=plan['source_files']:
        write(root/'audit/source_drift.json',{'status':'FAIL','reason':'source changed during experiment'})
        raise O4Error('code_snapshot_mismatch','source changed during experiment; use frozen snapshot')
    protection_report={'status':'NOT_REQUESTED','changed':[]}
    if protection:
        protected=read(protection)
        changed=[p for p,h in protected.items() if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
        protection_report={'status':'PASS' if not changed else 'FAIL','checked':len(protected),'changed':changed}
    write(root/'audit/protected.json',protection_report)
    correctness=all(r['completed']==tasks[r['task_id']]['expected_completed'] and not r['final_business_violations'] for r in rows)
    recovered_tasks={next(j['task_id'] for j in plan['jobs'] if j['job_id']==c['job_id'])
                     for c in coverage if c['baseline_allowed_count']==0 and c['extended_allowed_count']>0}
    e1_gates={'E1-A':len(gold)==24 and all(r['passed'] for r in gold+bad),
              'E1-B':all(r['passed'] for r in pair_checks) and sum(r['allowed_set_changed'] for r in pair_checks if r['backend']=='public_parser')>=4
                      and sum(r['action_changed'] for r in pair_checks if r['backend']=='public_parser')>=2,
              'E1-C':len(recovered_tasks)>=2 and sum(not t['expected_completed'] for t in tasks.values())>=2 and correctness,
              'E1-D':all(r['passed'] for r in gold+regression) and correctness,
              'E1-E':len(checks)==96 and all(r['passed'] for r in repeated+restored+faults)}
    conditions={
        'EA-01':all(r['passed'] for r in gold+bad),
        'EA-02':all(r['passed'] for r in gold+regression),
        'EA-03':e1_gates['E1-B'],
        'EA-04':correctness and all(r['passed'] for r in faults if r['purpose']=='wrong_ast_visible'),
        'EA-05':correctness and len(rows)==96,
        'EA-06':all(c['conservation'] for c in checks) and all(r['passed'] for r in faults),
        'EA-07':all(r['top_face_labels'] and r['png_bytes_verified'] for r in visual_records),
        'EA-08':len(rows)==plan['planned_episodes'] and len(pairs)==plan['planned_pair_records'],
        'EA-09':all(r['passed'] for r in repeated+restored) and protection_report['status']=='PASS',
        'EA-10':all((plan_root/'documentation'/p).is_file() for p in (
            'O4E0与E1区域约束运行及验收手册_20261025.md',
            'O4E0与E1区域约束开发与离线验收_20261025.md','cli_help.txt'))}
    report={'scope':'O4_E0_E1_OFFLINE_DEVELOPMENT','status':'PASS' if all(conditions.values()) and all(e1_gates.values()) else 'FAIL',
            'gates':conditions,'E1_gates':e1_gates,'gold':len(gold),'invalid':len(bad),'pair_records':len(pairs),'episodes':len(rows),
            'independent_repeats':len(repeated),'restores':len(restored),'legacy_gold_regression':len(regression),
            'unique_png':len(asset_cache),'new_api_attempts':0,'e4_status':'OUT_OF_SCOPE',
            'protected':protection_report,'unseen_generalization':'NOT_MEASURED',
            'E1-C_coverage_recovery_records':sum(c['baseline_allowed_count']==0 and c['extended_allowed_count']>0 for c in coverage)}
    write(root/'acceptance_report.json',report)
    (root/'README.md').write_text('E0/E1 offline development artifacts. Read acceptance_report.json and plan.json.\nReal API NOT_RUN; constructed development tasks are not unseen generalization.\n')
    seal(root)
    return report


def verify_experiment(root):
    root=Path(root);count=verify_seal(root)
    data=read(root/'private/data.json');config=read(root/'config.snapshot.json');tasks={t['task_id']:t for t in data['constructs']}
    checks=[]
    for job in read(root/'plan.json')['jobs']:
        result=read(root/f"episodes/{job['job_id']}.json")
        checks.append(verify_episode(result,tasks[job['task_id']],config))
    return {'status':'PASS','sealed_files':count,'episode_records_recomputed':len(checks),'new_api_attempts':0}
