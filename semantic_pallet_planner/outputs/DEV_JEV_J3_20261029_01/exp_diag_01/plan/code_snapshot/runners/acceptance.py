"""可执行的验收矩阵；所有门槛均依据已保存的实验凭据评价。"""
import copy
import json
import subprocess
import sys
import os
from pathlib import Path
from ..config import generator_config
from ..planner.generator import ExtremePointGenerator
from ..logging.artifacts import Experiment,dump,digest
from ..evaluation.geometry_oracle import check_candidate
from ..evaluation.replay import validate_experiment
from .core import FixedCaseRunner,EpisodeRunner
from .sweep import sweep_topk


def run_tests(exp):
    root=Path(__file__).resolve().parents[4]
    tests=exp.root/'tests';tests.mkdir()
    env=dict(os.environ,PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    result=subprocess.run([sys.executable,'-m','pytest',str(root/'semantic_pallet_planner/tests'),'-q','--disable-warnings',f'--junitxml={tests / "pytest.xml"}'],cwd=root,env=env,text=True,capture_output=True)
    (tests/'pytest.txt').write_text(result.stdout+'\n'+result.stderr)
    old=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(root/'semantic_pallet_dataset_v1/tests'),'-v'],cwd=root,text=True,capture_output=True)
    (tests/'stage0.txt').write_text(old.stdout+'\n'+old.stderr)
    dump(tests/'status.json',dict(pytest_returncode=result.returncode,stage0_returncode=old.returncode))
    if result.returncode or old.returncode:
        raise RuntimeError(f'acceptance tests failed; see {tests}')
    print('Focused, golden, integration and stage0 tests passed.',flush=True)


def cached_geometry(repo):
    checked=0;upper=0;errors=[]
    for cid in repo.list_cases('all'):
        dc=repo.get_decision_case(cid);sc=repo.get_scenario(dc['base_scenario_id']);cs=repo.get_candidate_set(dc['candidate_set_id'])
        for c in cs['candidates']:
            failures=check_candidate(dc,sc,c);checked+=1;upper+=c['pose']['z_base_mm']>0
            if failures:errors.append(dict(case=cid,candidate=c['candidate_id'],errors=failures))
    return dict(checked=checked,multilayer=upper,failure_count=len(errors),examples=errors[:10])


def run_acceptance(repo,exp,stage):
    run_tests(exp)
    dump(exp.root/'stage.json',dict(stage=stage))
    dump(exp.root/'cached_geometry_report.json',cached_geometry(repo))
    generator=ExtremePointGenerator(generator_config(exp.cfg))
    if stage=='1c':
        from .stage1c import register_stage1c_selectors
        from ..evaluation.stage1c import write_stage1c_summaries,write_stage1c_acceptance
        register_stage1c_selectors(exp.cfg,exp)
        methods=['random_valid','geometry_greedy','handcrafted_rule','vlm_text','vlm_visual','candidate_oracle']
        FixedCaseRunner(repo,exp).run(repo.list_cases('all'),methods)
        write_stage1c_summaries(exp)
        exp.finish()
        result=validate_experiment(exp.root,regenerate=True)
        dump(exp.root/'validation_report.json',validate_experiment(exp.root,regenerate=False))
        test_status=json.loads((exp.root/'tests/status.json').read_text())
        report=write_stage1c_acceptance(exp,result['status'],test_status['pytest_returncode']==test_status['stage0_returncode']==0)
        if report['status']!='PASS':raise RuntimeError('stage1C acceptance gates failed')
        return
    if stage=='1a':
        methods=['random_valid','geometry_greedy','handcrafted_rule','candidate_oracle']
        FixedCaseRunner(repo,exp).run(repo.list_cases('validation'),methods)
        EpisodeRunner(repo,generator,exp).run('SCN_0051','geometry_greedy')
        exp.finish()
        # 真正执行第二次实验，而不是重新计算第一次日志的哈希。
        cfg=copy.deepcopy(exp.cfg);cfg['output_root']=str(exp.root/'reproducibility')
        second=Experiment(cfg,'repeat')
        FixedCaseRunner(repo,second).run(repo.list_cases('validation'),methods)
        EpisodeRunner(repo,generator,second).run('SCN_0051','geometry_greedy')
        second.finish()
        dump(exp.root/'reproducibility_report.json',dict(first=exp.manifest['core_result_sha256'],second=second.manifest['core_result_sha256'],equal=exp.manifest['core_result_sha256']==second.manifest['core_result_sha256']))
    elif stage=='1b':
        # 在测试结果参与任何调参决策前，先冻结敏感性分析结果。
        selection=sweep_topk(repo,exp)
        print(f"Validation-only Top-K freeze for 1C: {selection['frozen_top_k']}",flush=True)
        FixedCaseRunner(repo,exp).run(repo.list_cases('all'),['lowest','geometry_greedy','pareto_greedy','candidate_oracle'])
        ids=repo.list_scenarios('all_base')
        for method in ['lowest','geometry_greedy','pareto_greedy']:
            for n,sid in enumerate(ids,1):
                row=EpisodeRunner(repo,generator,exp).run(sid,method)
                if n%10==0:print(f"{method}: {n}/{len(ids)} episodes ({row['termination_reason']})",flush=True)
        from ..visualization.charts import plot_geometry
        plot_geometry(exp.episodes,exp.root/'figures/geometry_comparison.png')
        from ..visualization.renderer import render_episode
        representatives=[]
        for split in ['validation','test_id','test_geometry_ood','test_semantic_ood']:
            row=next(r for r in exp.episodes if r['split']==split and r['method']=='geometry_greedy')
            representatives.append(dict(scenario_id=row['scenario_id'],method=row['method'],category=split))
        failed=next((r for r in exp.episodes if not r['completed'] and (r['scenario_id'],r['method']) not in {(x['scenario_id'],x['method']) for x in representatives}),None)
        if failed:
            representatives.append(dict(scenario_id=failed['scenario_id'],method=failed['method'],category='natural_incomplete'))
        else:
            # 仅在不存在自然未完成案例时构造有界演示，并确保其不污染主基准实验。
            cfg=copy.deepcopy(exp.cfg);cfg['output_root']=str(exp.root/'supplementary');cfg['max_steps']=2
            extra=Experiment(cfg,'bounded_demo')
            EpisodeRunner(repo,generator,extra).run('SCN_0052','lowest',max_steps=2,render=True);extra.finish()
            representatives.append(dict(scenario_id='SCN_0052',method='lowest',category='max_steps_demo',external_directory=str(extra.root/'episodes/lowest/SCN_0052')))
        for entry in representatives:
            path=Path(entry.get('external_directory',exp.root/'episodes'/entry['method']/entry['scenario_id']))
            print(f'Rendering {entry["category"]}: {entry["scenario_id"]} / {entry["method"]}',flush=True)
            render_episode(path)
            entry['directory']=str(path.relative_to(exp.root))
        dump(exp.root/'representative_episodes.json',representatives)
        # 关闭渲染并重新运行一个代表案例，以验证启用和关闭渲染时结果一致。
        cfg=copy.deepcopy(exp.cfg);cfg['output_root']=str(exp.root/'reproducibility')
        second=Experiment(cfg,'render_off_repeat')
        row=representatives[0]
        EpisodeRunner(repo,generator,second).run(row['scenario_id'],row['method']);second.finish()
        first=json.loads((exp.root/row['directory']/'episode.json').read_text())['core_result_sha256']
        other=json.loads((second.root/'episodes'/row['method']/row['scenario_id']/'episode.json').read_text())['core_result_sha256']
        dump(exp.root/'reproducibility_report.json',dict(first=first,second=other,equal=first==other,scope='same representative episode rendered and rerun without renderer'))
    else:
        raise ValueError(f'unsupported acceptance stage: {stage}')
    exp.finish()
    result=validate_experiment(exp.root,regenerate=True)
    dump(exp.root/'validation_report.json',validate_experiment(exp.root,regenerate=False))
    from ..evaluation.reporting import report_existing
    report_existing(exp.root)
    if result['status']!='PASS':raise RuntimeError(f'replay failed: {result}')
    if json.loads((exp.root/'acceptance_report.json').read_text())['status']!='PASS':
        raise RuntimeError('acceptance gates failed; inspect acceptance_report.md')
