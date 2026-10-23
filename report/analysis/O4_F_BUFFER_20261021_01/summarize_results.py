"""Descriptive paired effects, clustered source denominators; no significance claim."""
import json
from pathlib import Path
from collections import defaultdict
from statistics import mean
ROOT=Path('semantic_pallet_planner/outputs/EXP_O4_F_BUFFER_20261021_01')
OUT=Path('report/analysis/O4_F_BUFFER_20261021_01')
def main():
 rows=json.loads((ROOT/'metrics/per_episode.json').read_text());groups=defaultdict(list)
 for row in rows:
  if row['backend']=='oracle_ast':groups[row['method']].append(row)
 baseline={r['task_id']:r for r in groups['single_greedy']};summaries=[];effects=[];by_config=[]
 for method,values in groups.items():
  summaries.append({'method':method,'planned_orders':len(values),'completed':sum(r['completed'] for r in values),'clean_completed':sum(r['clean_completed'] for r in values),
    'mean_item_ratio':mean(r['placed_item_ratio'] for r in values),'mean_volume_ratio':mean(r['placed_volume_ratio'] for r in values),
    'placed_items':sum(r['placed_items'] for r in values),'reordered_orders':sum(r['inversions']>0 for r in values),
    'non_head_commits':sum(r['non_head_commits'] for r in values),'physical_violations':sum(r['physical_violations'] for r in values),
    'reference_violations':sum(r['final_business_violation_count'] for r in values)})
  effects.append({'method':method,'compared_orders':len(values),
    'more_items':sum(r['placed_items']>baseline[r['task_id']]['placed_items'] for r in values),
    'same_items':sum(r['placed_items']==baseline[r['task_id']]['placed_items'] for r in values),
    'fewer_items':sum(r['placed_items']<baseline[r['task_id']]['placed_items'] for r in values),
    'more_volume':sum(r['placed_volume_ratio']>baseline[r['task_id']]['placed_volume_ratio']+1e-12 for r in values),
    'same_volume':sum(abs(r['placed_volume_ratio']-baseline[r['task_id']]['placed_volume_ratio'])<=1e-12 for r in values),
    'less_volume':sum(r['placed_volume_ratio']<baseline[r['task_id']]['placed_volume_ratio']-1e-12 for r in values),
    'mean_item_ratio_delta':mean(r['placed_item_ratio']-baseline[r['task_id']]['placed_item_ratio'] for r in values),
    'mean_volume_ratio_delta':mean(r['placed_volume_ratio']-baseline[r['task_id']]['placed_volume_ratio'] for r in values)})
  for c in range(6):
   rs=[r for r in values if r['configuration']==c]
   by_config.append({'method':method,'configuration':c,'planned_orders':len(rs),'completed':sum(r['completed'] for r in rs),
                     'mean_item_ratio':mean(r['placed_item_ratio'] for r in rs),'mean_volume_ratio':mean(r['placed_volume_ratio'] for r in rs)})
 result={'independent_source_orders':12,'configuration_tasks_per_source':6,'role':'seen_train_development',
         'methods':summaries,'paired_against_single':effects,'by_configuration':by_config,
         'interpretation':'descriptive paired development results; six configs from each source are dependent; not unseen/general/global optimum evidence'}
 (OUT/'effect_analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 lines=['| 方法（Oracle语义） | 完整且无违规完成 | 平均件数比例 | 平均体积比例 | 发生改序的订单 |',
 '|---|---:|---:|---:|---:|']
 for r in summaries:lines.append(f"| {r['method']} | {r['clean_completed']}/72 | {r['mean_item_ratio']:.2%} | {r['mean_volume_ratio']:.2%} | {r['reordered_orders']} |")
 search=next(r for r in effects if r['method']=='buffer_search')
 lines.extend(['',f"搜索相对单箱：{search['more_items']}个订单多放、{search['same_items']}个件数持平、{search['fewer_items']}个少放；平均件数比例变化{search['mean_item_ratio_delta']*100:+.2f}个百分点，平均体积比例变化{search['mean_volume_ratio_delta']*100:+.2f}个百分点。",'',
              '这些结果来自12个已使用的train开发来源，六配置并非独立来源；不代表未见订单泛化，也不构成全局最优或真实工厂吞吐率证据。'])
 (OUT/'results_fragment.md').write_text('\n'.join(lines)+'\n')
 print('\n'.join(lines))
if __name__=='__main__':main()
