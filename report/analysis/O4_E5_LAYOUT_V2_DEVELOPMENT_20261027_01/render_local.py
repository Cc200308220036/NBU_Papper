"""Export equal-scale local decision comparisons from already saved records."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
cases = json.loads((ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_LAYOUT_V2_L0_20261027_01/fixed_decisions.json').read_text())
fig, axes = plt.subplots(2, 2, figsize=(12, 10))
for row, case in enumerate(cases):
    for col, group in enumerate(('A', 'D')):
        ax = axes[row, col]; state = case['state']; c = state['container']
        ax.add_patch(Rectangle((-c['length_mm']/2, -c['width_mm']/2), c['length_mm'], c['width_mm'], facecolor='#f6f7f9', edgecolor='#333'))
        for obj in state['placed_items']:
            p = obj['pose']; dx, dy, _ = obj['oriented_size_mm']
            ax.add_patch(Rectangle((p['x_mm']-dx/2, p['y_mm']-dy/2), dx, dy, facecolor='#bad8e9', edgecolor='#345', linewidth=1.5))
            ax.text(p['x_mm'], p['y_mm'], obj['item_id'], ha='center', va='center')
        selected = case['results'][group]['selected']; p = selected['pose']; dx, dy, _ = selected['oriented_size_mm']
        ax.add_patch(Rectangle((p['x_mm']-dx/2, p['y_mm']-dy/2), dx, dy, facecolor='#e9c9ac', alpha=.8, edgecolor='#b53', linestyle='--', linewidth=2))
        ax.text(p['x_mm'], p['y_mm'], 'proposed '+selected['pick_item_id'], ha='center', va='center', fontsize=9)
        ax.set_title(f'{case["case"]} / {group}\n({p["x_mm"]:g}, {p["y_mm"]:g}, {p["z_base_mm"]:g}), yaw={p["yaw_deg"]}')
        ax.set_xlim(-650,650); ax.set_ylim(-550,550); ax.set_aspect('equal')
        ax.set_xlabel('x (mm, right)'); ax.set_ylabel('y (mm, back)'); ax.grid(alpha=.2)
fig.suptitle('Same public state: baseline A vs layout-v2 D\nDashed box = proposed placement; this is not an order-completion result')
fig.tight_layout(rect=(0,0,1,.94)); fig.savefig(HERE/'local_decisions.png', dpi=150); plt.close(fig)
print(HERE/'local_decisions.png')
