"""Export all six frozen task comparisons and one detailed 3D regression view."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXP = ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_LAYOUT_V2_L2_20261027_01'


def record(task, group, method):
    return json.loads((EXP/'episodes'/f'L2_{task}_{group}_{method}_oracle_ast.json').read_text())


def top(ax, result):
    state = result['final_state']; container = state['container']; s = result['summary']
    ax.add_patch(Rectangle((-600,-500),1200,1000,facecolor='#f8f9fa',edgecolor='#333'))
    for i, obj in enumerate(state['placed_items']):
        p = obj['pose']; dx,dy,_ = obj['oriented_size_mm']; color = plt.cm.tab20(i%20)
        ax.add_patch(Rectangle((p['x_mm']-dx/2,p['y_mm']-dy/2),dx,dy,facecolor=color,edgecolor='#333',alpha=.8))
        ax.text(p['x_mm'],p['y_mm'],obj['item_id'].replace('item_','')+f'\nz={p["z_base_mm"]:g}',ha='center',va='center',fontsize=7)
    ax.set_xlim(-620,620);ax.set_ylim(-520,520);ax.set_aspect('equal');ax.set_xticks([-600,0,600]);ax.set_yticks([-500,0,500])
    ax.set_title(f'{s["task_id"]} / {s["placed_items"]}/{s["planned_items"]}; volume={s["placed_volume_ratio"]:.1%}',fontsize=9)


tasks = sorted({json.loads(p.read_text())['summary']['task_id'] for p in (EXP/'episodes').glob('L2_*_A_single_oracle_ast.json')})
assert len(tasks) == 6
fig, axes = plt.subplots(6,4,figsize=(16,23))
for row,task in enumerate(tasks):
    for col,(method,group) in enumerate([('single','A'),('single','D'),('buffer_search','A'),('buffer_search','D')]):
        top(axes[row,col],record(task,group,method))
        if row == 0: axes[row,col].set_xlabel(method+' / '+group)
fig.suptitle('Frozen development tasks: actual final placements from an empty pallet\nColumns: single A, single D, search A, search D. Equal x/y scale in mm; z is base height.',fontsize=14)
fig.tight_layout(rect=(0,0,1,.965));fig.savefig(HERE/'all_order_comparisons.png',dpi=130);plt.close(fig)

fig = plt.figure(figsize=(12,5))
for i,group in enumerate(('A','D')):
    result=record('E5_SRC00_C0',group,'single');ax=fig.add_subplot(1,2,i+1,projection='3d')
    for n,obj in enumerate(result['final_state']['placed_items']):
        p=obj['pose'];dx,dy,dz=obj['oriented_size_mm'];x=p['x_mm']-dx/2;y=p['y_mm']-dy/2;z=p['z_base_mm']
        v=[(x,y,z),(x+dx,y,z),(x+dx,y+dy,z),(x,y+dy,z),(x,y,z+dz),(x+dx,y,z+dz),(x+dx,y+dy,z+dz),(x,y+dy,z+dz)]
        faces=[[v[j] for j in face] for face in [(0,1,2,3),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]]
        ax.add_collection3d(Poly3DCollection(faces,facecolors=[plt.cm.tab20(n%20)],edgecolors='#333',linewidths=.5,alpha=.8))
        ax.text(p['x_mm'],p['y_mm'],z+dz+15,obj['item_id'].replace('item_',''),ha='center',fontsize=8)
    ax.set_xlim(-600,600);ax.set_ylim(-500,500);ax.set_zlim(0,850);ax.set_box_aspect((1200,1000,850))
    ax.set_xlabel('x mm');ax.set_ylabel('y mm');ax.set_zlabel('z mm');ax.view_init(elev=27,azim=-55)
    s=result['summary'];ax.set_title(f'00101152/C0 single {group}: {s["placed_items"]}/12\norder volume {s["placed_volume_ratio"]:.2%}')
fig.suptitle('Actual 3D regression: solid boxes are committed placements; no hypothetical boxes')
fig.tight_layout();fig.savefig(HERE/'regression_3d.png',dpi=150);plt.close(fig)
print('rendered all six task pairs and detailed 3D regression')
