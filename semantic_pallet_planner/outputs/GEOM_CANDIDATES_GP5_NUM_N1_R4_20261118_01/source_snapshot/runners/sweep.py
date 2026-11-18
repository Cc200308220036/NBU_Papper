"""仅在验证集上执行 Top-K 敏感性分析，并采用预先声明的选择规则。"""
import copy
import statistics
from ..domain import PalletState
from ..planner.generator import ExtremePointGenerator
from ..config import generator_config
from ..logging.artifacts import dump,write_csv
from .core import EpisodeRunner


def sweep_topk(repository,experiment,values=(4,8,16,32),split='validation'):
    if split!='validation':raise ValueError('Top-K tuning is restricted to validation')
    rows=[]; summaries=[]
    for k in values:
        cfg=copy.deepcopy(experiment.cfg);cfg['top_k']=k
        generator=ExtremePointGenerator(generator_config(cfg))
        for cid in repository.list_cases(split):
            case=repository.get_decision_case(cid);s=repository.get_scenario(case['base_scenario_id'])
            result=generator.generate(PalletState.from_dict(dict(case,request_id=cid,container=s['container'])))
            rows.append(dict(top_k=k,decision_case_id=cid,**{a:result.audit.data[a] for a in ('raw_candidate_count','physical_valid_count','pareto_candidate_count','returned_count','pareto_recall_at_k','epsilon_optimal_recall_at_k')},generation_time_s=result.timing.data['total']))
        group=[r for r in rows if r['top_k']==k]
        summaries.append(dict(top_k=k,n=len(group),pareto_recall=statistics.mean(r['pareto_recall_at_k'] for r in group),
            epsilon_hit_rate=statistics.mean(r['epsilon_optimal_recall_at_k'] for r in group),
            returned_mean=statistics.mean(r['returned_count'] for r in group),generation_mean_s=statistics.mean(r['generation_time_s'] for r in group)))
    # 只依据固定验证状态上的候选覆盖率冻结参数；运行时间仅作报告，不参与调参。
    eligible=[r for r in summaries if r['pareto_recall']>=.90 and r['epsilon_hit_rate']==1.0]
    frozen=min(eligible,key=lambda r:r['top_k'])['top_k'] if eligible else max(values)
    selection=dict(split=split,values=list(values),frozen_top_k=frozen,topk_mode=experiment.cfg['topk_mode'],
        selection_rule='Smallest K with validation mean Pareto recall >= 0.90 and epsilon-optimal hit rate = 1.0; otherwise largest evaluated K.',
        target_met=bool(eligible),scope='Fixed validation states; freeze for 1C. Does not alter frozen 1B K=16 baseline.',results=summaries)
    dump(experiment.root/'metrics/topk_selection.json',selection)
    write_csv(experiment.root/'metrics/topk_sensitivity.csv',rows)
    from ..visualization.charts import plot_topk
    plot_topk(summaries,experiment.root/'figures/topk_sensitivity.png')
    return selection
