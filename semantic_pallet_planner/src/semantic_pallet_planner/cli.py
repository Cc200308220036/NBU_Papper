"""用于固定案例、在线回合、基准实验、敏感性分析和证据回放的命令行入口。"""
import argparse
import json
import os
from pathlib import Path
from .config import load_config,generator_config
from .repository import DatasetRepository
from .planner.generator import ExtremePointGenerator
from .logging.artifacts import Experiment
from .runners.core import FixedCaseRunner,EpisodeRunner


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    for cmd in ('run-fixed','run-episode','benchmark','sweep-topk','run-stage1c','acceptance'):
        q=sub.add_parser(cmd)
        q.add_argument('--config');q.add_argument('--experiment-id')
        q.add_argument('--output-root');q.add_argument('--dataset');q.add_argument('--seed',type=int)
        q.add_argument('--top-k',type=int);q.add_argument('--topk-mode',choices=['legacy_v01','diverse_v1'])
        q.add_argument('--split',default='validation');q.add_argument('--selectors')
        q.add_argument('--selector',default='geometry_greedy');q.add_argument('--scenario',default='SCN_0051')
        q.add_argument('--render',action='store_true',default=None);q.add_argument('--max-steps',type=int)
        q.add_argument('--all-base-scenarios',action='store_true');q.add_argument('--values',default='4,8,16,32')
        q.add_argument('--stage',choices=['1a','1b','1c'],default='1a')
        if cmd=='run-stage1c':
            q.add_argument('--fake-vlm',action='store_true',help='offline deterministic client; never for thesis results')
            q.add_argument('--case',help='run one Decision Case for an API smoke test')
    for cmd in ('replay','validate','report','render'):
        q=sub.add_parser(cmd);q.add_argument('--experiment',required=True)
        if cmd=='render':q.add_argument('--method',default='geometry_greedy');q.add_argument('--scenario',required=True)
    a=p.parse_args(argv)
    if a.command in ('replay','validate'):
        from .evaluation.replay import validate_experiment
        result=validate_experiment(a.experiment,regenerate=a.command=='replay')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if result['status']!='PASS':raise SystemExit(1)
        return
    if a.command=='report':
        from .evaluation.reporting import report_existing
        print(report_existing(Path(a.experiment)));return
    if a.command=='render':
        from .visualization.renderer import render_episode
        print(render_episode(Path(a.experiment)/'episodes'/a.method/a.scenario));return
    cfg=load_config(a.config,**{k:getattr(a,k) for k in ('output_root','dataset','seed','top_k','topk_mode','render','max_steps')})
    if a.command=='acceptance' and cfg['max_steps'] is not None:
        raise ValueError('acceptance requires complete episodes; max_steps must be null')
    repo=DatasetRepository(cfg['dataset'])
    generator=ExtremePointGenerator(generator_config(cfg))
    if (a.command=='run-stage1c' and not a.fake_vlm) or (a.command=='acceptance' and a.stage=='1c'):
        if 'vlm' not in cfg:raise ValueError('run-stage1c requires a vlm config section')
        env_name=cfg['vlm']['api_key_env']
        if not os.environ.get(env_name):raise ValueError(f'missing environment variable {env_name}')
    exp=Experiment(cfg,a.experiment_id)
    if a.command=='acceptance':
        from .runners.acceptance import run_acceptance
        run_acceptance(repo,exp,a.stage)
    elif a.command=='run-fixed':
        FixedCaseRunner(repo,exp).run(repo.list_cases(a.split),(a.selectors or 'random_valid,geometry_greedy,handcrafted_rule,candidate_oracle').split(','))
    elif a.command=='run-stage1c':
        from .runners.stage1c import register_stage1c_selectors
        if a.fake_vlm:
            from .vlm.client import FakeClient
            register_stage1c_selectors(cfg,exp,client=FakeClient('C01'))
        else:register_stage1c_selectors(cfg,exp)
        methods=(a.selectors or 'random_valid,geometry_greedy,handcrafted_rule,vlm_text,vlm_visual,candidate_oracle').split(',')
        case_ids=[a.case] if a.case else repo.list_cases(a.split)
        FixedCaseRunner(repo,exp).run(case_ids,methods)
    elif a.command=='run-episode':
        print(EpisodeRunner(repo,generator,exp).run(a.scenario,a.selector,max_steps=cfg['max_steps'],render=cfg['render']))
    elif a.command=='benchmark':
        methods=(a.selectors or 'lowest,geometry_greedy,pareto_greedy').split(',')
        ids=repo.list_scenarios('all_base' if a.all_base_scenarios else a.split)
        for method in methods:
            for idx,sid in enumerate(ids):
                row=EpisodeRunner(repo,generator,exp).run(sid,method,max_steps=cfg['max_steps'],render=cfg['render'])
                print(f"{method} {idx+1}/{len(ids)} {sid}: {row['termination_reason']}",flush=True)
        from .visualization.charts import plot_geometry
        plot_geometry(exp.episodes,exp.root/'figures/geometry_comparison.png')
    elif a.command=='sweep-topk':
        from .runners.sweep import sweep_topk
        values=tuple(int(x) for x in a.values.split(','))
        if not values or min(values)<1 or len(set(values))!=len(values):raise ValueError('positive unique K values required')
        sweep_topk(repo,exp,values,a.split)
    if a.command=='run-stage1c':
        from .evaluation.stage1c import write_stage1c_summaries
        write_stage1c_summaries(exp)
    exp.finish()
    print(f'OUTPUT: {exp.root}',flush=True)


if __name__=='__main__':main()
