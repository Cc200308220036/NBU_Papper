"""根据实验凭据生成验收报告，并保留所有未通过的门槛。"""
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image
from ..logging.artifacts import dump


def report_existing(root):
    root=Path(root);load=lambda name:json.loads((root/name).read_text())
    manifest=load('manifest.json');cfg=load('config.snapshot.json')
    stage=load('stage.json')['stage'] if (root/'stage.json').exists() else 'ad_hoc'
    decisions=list(csv.DictReader((root/'metrics/per_decision.csv').open()))
    episodes=list(csv.DictReader((root/'metrics/per_episode.csv').open()))
    events=[json.loads(x) for x in (root/'steps.jsonl').read_text().splitlines()]
    checks=[]
    def add(key,ok,evidence):checks.append(dict(check=key,passed=bool(ok),evidence=evidence))
    test_cases=[]
    if (root/'tests/pytest.xml').exists():
        xml=ET.parse(root/'tests/pytest.xml')
        test_cases=list(xml.iter('testcase'))
        bad=[x for x in test_cases if x.find('failure') is not None or x.find('error') is not None or x.find('skipped') is not None]
        status=load('tests/status.json')
        add('unit_golden_integration_stage0_tests',bool(test_cases) and not bad and status['pytest_returncode']==status['stage0_returncode']==0,'tests/pytest.xml; tests/pytest.txt; tests/stage0.txt')
    else:add('unit_golden_integration_stage0_tests',False,'missing recorded tests')
    geometry=load('cached_geometry_report.json') if (root/'cached_geometry_report.json').exists() else {}
    add('cached_5124_geometry',geometry.get('checked')==5124 and geometry.get('failure_count')==0,'cached_geometry_report.json')
    replay=load('replay_report.json') if (root/'replay_report.json').exists() else {}
    add('replay_state_protocol_metrics_visibility',replay.get('status')=='PASS','replay_report.json')
    add('dynamic_commits_and_returned_topk_geometry',replay.get('geometry_failures')==0 and replay.get('returned_candidate_failures')==0,'replay_report.json')
    repeat=load('reproducibility_report.json') if (root/'reproducibility_report.json').exists() else {}
    add('deterministic_repeat',repeat.get('equal') is True,'reproducibility_report.json')
    oracles=[r for r in decisions if r['method']=='candidate_oracle']
    add('oracle_hit_100_percent',bool(oracles) and all(r['oracle_hit']=='True' and float(r['oracle_regret'])==0 for r in oracles),'metrics/per_decision.csv')
    grouped={}
    for r in decisions:grouped.setdefault(r['decision_case_id'],set()).add(r['candidate_set_id'])
    add('fixed_cset_fairness',bool(grouped) and all(len(s)==1 for s in grouped.values()),'metrics/per_decision.csv')
    add('privileged_methods_tagged',all(r['privileged_input']==str(r['method'] in ('candidate_oracle','handcrafted_rule')) and r['future_visible']=='False' for r in decisions+episodes),'metrics/*.csv')
    add('deterministic_baselines_no_unexpected_fallback',all(not e['fallback'] and e['error'] is None for e in events),'steps.jsonl')
    if stage=='1a':
        add('30_validation_cases_four_methods_120_rows',len(decisions)==120 and len(grouped)==30 and {r['method'] for r in decisions}=={'random_valid','geometry_greedy','handcrafted_rule','candidate_oracle'} and all(r['split']=='validation' for r in decisions),'metrics/per_decision.csv')
        add('SCN_0051_online_completed',any(r['scenario_id']=='SCN_0051' and r['method']=='geometry_greedy' and r['completed']=='True' for r in episodes),'episodes/geometry_greedy/SCN_0051/')
    if stage=='1b':
        add('360_cases_four_methods_1440_rows',len(decisions)==1440 and len(grouped)==360 and all(sum(r['method']==m for r in decisions)==360 for m in ['lowest','geometry_greedy','pareto_greedy','candidate_oracle']),'metrics/per_decision.csv')
        add('100_scenarios_three_methods_300_episodes',len(episodes)==300 and all(len({r['scenario_id'] for r in episodes if r['method']==m})==100 for m in ['lowest','geometry_greedy','pareto_greedy']),'metrics/per_episode.csv')
        add('natural_terminal_reasons_no_internal_error',bool(episodes) and all(r['termination_reason'] in ('all_items_placed','no_feasible_candidate') for r in episodes),'metrics/per_episode.csv')
        sweep=load('metrics/topk_selection.json') if (root/'metrics/topk_selection.json').exists() else {}
        add('validation_only_K4_8_16_32_frozen',sweep.get('split')=='validation' and sweep.get('values')==[4,8,16,32] and sweep.get('frozen_top_k') in [4,8,16,32],'metrics/topk_selection.json; figures/topk_sensitivity.png')
        online=[e for e in events if e['track']=='episode']
        funnel=['raw_candidate_count','physical_valid_count','duplicate_count','pareto_candidate_count','returned_count','rejection_histogram','pareto_recall_at_k','epsilon_optimal_recall_at_k']
        add('complete_candidate_funnel_and_phase_timing',all(all(k in e['audit'] for k in funnel) and all(k in e['timing'] for k in ['enumerate','filter','score','top_k','total']) for e in online),'steps.jsonl')
        reps=load('representative_episodes.json') if (root/'representative_episodes.json').exists() else []
        categories={x['category'] for x in reps}
        add('five_representative_categories',len(reps)>=5 and {'validation','test_id','test_geometry_ood','test_semantic_ood'}<=categories and bool(categories&{'natural_incomplete','max_steps_demo'}),'representative_episodes.json')
        valid_visuals=True;gif_info=[]
        for r in reps:
            directory=root/r['directory']
            try:
                with Image.open(directory/'animation.gif') as gif:
                    gif_info.append(dict(directory=r['directory'],size=list(gif.size),frames=gif.n_frames))
                    valid_visuals &= gif.n_frames>1
                    for i in range(gif.n_frames):gif.seek(i);gif.load()
                rm=json.loads((directory/'render_manifest.json').read_text())
                for relative in rm['frame_checksums']:
                    with Image.open(directory/relative) as im:valid_visuals &= im.size==(1800,1100)
                valid_visuals &= (directory/'final_layout.png').exists()
            except Exception:valid_visuals=False
        add('readable_fixed_canvas_gifs_and_final_layout',len(gif_info)>=5 and valid_visuals,'render_manifest.json in representative episode directories')
        dump(root/'visual_validation.json',dict(gifs=gif_info,passed=len(gif_info)>=5 and valid_visuals))
    timings=[e['timing']['total'] for e in events if e['track']=='episode' and 'total' in e['timing']]
    profile=dict(n=len(timings),p50_s=float(np.quantile(timings,.5)),p95_s=float(np.quantile(timings,.95)),max_s=max(timings)) if timings else {}
    status='PASS' if checks and all(x['passed'] for x in checks) else 'FAIL'
    report=dict(stage=stage,status=status,checks=checks,test_count=len(test_cases),fixed_rows=len(decisions),episodes=len(episodes),generation_timing=profile,
        known_limits=['Deterministic geometry, not physical simulation or robot execution.','MVD V0.1 is a selected small benchmark, not final thesis evidence.','Synthetic top-load capacities; no VLM/experience memory/GOPT training/buffer3/beam/MP4 in this stage.','epsilon_optimal_recall_at_k retains V0.1 existence-indicator semantics.','Fixed candidates are frozen V0.1; online diverse_v1 additionally stratifies yaw and Pareto membership.','Oracle regret is soft utility difference; hard-violation regret is reported separately and has lexical priority.'])
    dump(root/'acceptance_report.json',report)
    lines=[f'# 阶段{stage.upper()}开发与验收报告','',f'结论：**{status}**','',f'实验目录：`{root}`',f'数据集：`{cfg["dataset"]}`；Top-K={cfg["top_k"]}；模式={cfg["topk_mode"]}；seed={cfg["seed"]}。','',
        f'记录测试{len(test_cases)}项（另有阶段0测试日志）；固定决策{len(decisions)}条；在线episode {len(episodes)}场。','',
        '## 验收证据','', '| 检查 | 结果 | 证据 |','|---|---|---|']
    lines += [f"| {x['check']} | {'PASS' if x['passed'] else 'FAIL'} | {x['evidence']} |" for x in checks]
    lines += ['','## 耗时与环境','',f'候选生成（秒，不含选择、绘图）：`{profile}`。','',f'Python {manifest["environment"]["python"]}；CPU {manifest["environment"]["cpu"]}。',f'操作系统：{manifest["environment"]["platform"]}。','依赖版本、代码文件哈希和数据文件哈希见`manifest.json`；配置见`config.snapshot.json`。','','## 在线结果','', '| 方法 | 场景数 | 全部放完 | 无候选终止 | 平均放置比率 |','|---|---:|---:|---:|---:|']
    for method in sorted({r['method'] for r in episodes}):
        rows=[r for r in episodes if r['method']==method]
        lines.append(f"| {method} | {len(rows)} | {sum(r['completed']=='True' for r in rows)} | {sum(r['termination_reason']=='no_feasible_candidate' for r in rows)} | {np.mean([float(r['placed_item_ratio']) for r in rows]):.4f} |")
    lines+=['','完整指标按method+split统计，含均值、中位数、标准差和95% bootstrap区间，见`metrics/summary.json`。固定DC的区间按场景聚类，避免将同一场景的3个决策当作独立场景。','','## 未完成场景','']
    failures=[r for r in episodes if r['completed']!='True']
    lines += [f"- {r['method']} / {r['scenario_id']}：{r['termination_reason']}，放置比率{float(r['placed_item_ratio']):.3f}。" for r in failures] or ['无。']
    lines+=['','## 已知限制','']+[f'- {x}' for x in report['known_limits']]
    lines+=['',f"阶段退出条件：{'满足' if status=='PASS' else '尚未满足，见失败项'}。1B通过后可进入1C的VLM选择器实现；本报告不声称已完成VLM或机器人实验。",'']
    (root/'acceptance_report.md').write_text('\n'.join(lines))
    return str(root/'acceptance_report.md')
