"""Create descriptive plots and per-order tables from completed layout runs."""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from semantic_pallet_planner.runners.attribute_pilot_v2 import write_csv, write_json, sha
from semantic_pallet_planner.selectors.layout_preserving import VARIANTS, SOFT_BUDGETS
from semantic_pallet_planner.visualization.primitives import draw_pallet

LABELS={'original':'Original','strict_layout':'Strict layout','relaxed_geometry':'Budget + geometry',
        'relaxed_full':'Budget + full layout','relaxed_wo_floor':'w/o floor','relaxed_wo_support':'w/o support',
        'relaxed_wo_capacity':'w/o capacity','relaxed_wo_height':'w/o height','relaxed_floor_only':'Floor only'}


def run(root):
    summary=json.loads((root/'metrics/summary.json').read_text())
    rows=[]
    for path in sorted((root/'episodes').glob('*/*/*/episode.json')):
        rows.append(json.loads(path.read_text())['summary'])
    grouped=defaultdict(list)
    for r in rows:
        grouped[r['mode'],r['variant'],r['source_order_key']].append(r)
    write_csv(root/'metrics/per_source_order.csv',[
        {'mode':mode,'variant':variant,'source_order_key':source,'policy_tasks':len(items),
         **{k:float(np.mean([r[k] for r in items])) for k in
            ('completed','clean_completed','placed_item_ratio','placed_volume_ratio','final_business_violation_count')}}
        for (mode,variant,source),items in sorted(grouped.items())])
    checks=[];changes=[]
    for path in sorted((root/'episodes').glob('*/*/*/steps.jsonl')):
        mode,variant,ep=path.relative_to(root/'episodes').parts[:3]
        record=json.loads(path.with_name('episode.json').read_text())
        priorities=record['task']['truth_policy']['soft_priorities']
        for e in map(json.loads,path.read_text().splitlines()):
            if not e['committed_label']:
                continue
            trace=e['trace']
            if trace.get('changed_from_original'):
                changes.append({'mode':mode,'variant':variant,'episode_id':ep,'arrival_number':e['step_index']+1,
                                'baseline_label':trace['baseline_label'],'selected_label':e['committed_label'],
                                'soft_loss_from_anchor':trace['soft_loss_from_anchor']})
            for priority,loss in zip(priorities,trace.get('soft_loss_from_anchor',[])):
                bound=SOFT_BUDGETS[priority['metric']] if variant.startswith('relaxed_') else 1e-6
                checks.append(loss is None or loss<=bound+1e-6)
    assert all(checks)
    write_csv(root/'metrics/changed_actions.csv',changes)
    write_json(root/'audit/soft_budget_checks.json',{'status':'PASS','component_checks':len(checks),
               'failures':0,'note':'Strict variants allow only original numerical equivalence tolerance.'})
    figures=root/'figures';figures.mkdir(exist_ok=True)
    names=[v for v in VARIANTS if v in next(iter(summary.values()))]
    for mode,values in summary.items():
        fig,axes=plt.subplots(1,3,figsize=(16,5),sharey=True)
        for ax,metric,title in zip(axes,('clean_completed','completed','mean_placed_item_ratio'),
                                   ('Clean complete orders','Complete orders','Mean placed-item ratio')):
            vals=[values[v][metric]/values[v]['episodes'] if metric!='mean_placed_item_ratio' else values[v][metric] for v in names]
            ax.barh(range(len(names)),vals,color=['#777777' if v=='original' else '#4776a8' if v=='strict_layout' else '#de9343' for v in names])
            ax.set(yticks=range(len(names)),yticklabels=[LABELS[v] for v in names],xlim=(0,1.16),title=title)
            for i,val in enumerate(vals):
                ax.text(val+.015,i,f'{val:.1%}',va='center',fontsize=8)
            ax.grid(axis='x',alpha=.2)
        axes[0].invert_yaxis()
        fig.suptitle(mode+' | seen validation: 10 source orders x 2 policies; no model calls')
        fig.tight_layout();fig.savefig(figures/f'{mode}_overview.png',dpi=160);plt.close(fig)
    for ep in ('O3_SCN_0052_P0','O3_SCN_0054_P1'):
        fig=plt.figure(figsize=(16,8))
        for index,(mode,variant) in enumerate((m,v) for m in ('safe','observe_business') for v in
                                             ('original','strict_layout','relaxed_geometry','relaxed_full')):
            path=root/'episodes'/mode/variant/ep
            if not path.exists():
                continue
            record=json.loads((path/'episode.json').read_text())
            events=[json.loads(s) for s in (path/'steps.jsonl').read_text().splitlines()]
            ax=fig.add_subplot(2,4,index+1,projection='3d')
            container=events[0]['request']['container']
            draw_pallet(ax,container,events[-1]['after_placed'])
            r=record['summary']
            ax.set_title(f"{mode}\n{LABELS[variant]}\n{r['placed_items']}/{r['planned_items']}; final violations={r['final_business_violation_count']}",fontsize=9)
        fig.suptitle(ep+' | final layouts; predefined diagnostic case, not selected by wins')
        fig.tight_layout(rect=(0,0,1,.95));fig.savefig(figures/f'{ep}_final_layouts.png',dpi=150);plt.close(fig)
    shutil.copyfile(__file__,root/'report_script.snapshot.py')
    return {'rows':len(rows),'changed_actions':len(changes),'soft_checks':len(checks),'figures':len(list(figures.glob('*.png')))}


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,required=True)
    print(json.dumps(run(ap.parse_args().root),indent=2))
