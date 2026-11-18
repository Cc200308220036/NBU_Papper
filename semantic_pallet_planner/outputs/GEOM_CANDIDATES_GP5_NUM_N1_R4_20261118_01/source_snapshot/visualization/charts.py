from pathlib import Path
from .primitives import plt


def plot_topk(rows,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(10,4),dpi=130)
    k=[r['top_k'] for r in rows]
    axes[0].plot(k,[r['pareto_recall'] for r in rows],'o-',label='Pareto recall')
    axes[0].plot(k,[r['epsilon_hit_rate'] for r in rows],'s-',label='Epsilon-optimal hit')
    axes[0].set_ylim(0,1.05);axes[0].legend();axes[0].set_ylabel('Validation candidate coverage')
    axes[1].plot(k,[r['generation_mean_s']*1000 for r in rows],'o-');axes[1].set_ylabel('Mean generation time / ms')
    for ax in axes:ax.set_xlabel('Top-K');ax.set_xticks(k);ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(path);plt.close(fig)


def plot_geometry(rows,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    import statistics
    methods=sorted({r['method'] for r in rows})
    fig,axes=plt.subplots(1,3,figsize=(13,4),dpi=130)
    for ax,key,title in zip(axes,['completed','placed_item_ratio','max_height_mm'],['Completion rate','Placed item ratio','Max height / mm']):
        vals=[statistics.mean(float(r[key]) for r in rows if r['method']==m) for m in methods]
        ax.bar(methods,vals,color=['#507eaa','#57a08a','#d9a24a'][:len(methods)])
        ax.set_title(title);ax.tick_params(axis='x',labelrotation=15);ax.grid(axis='y',alpha=.2)
    fig.tight_layout();fig.savefig(path);plt.close(fig)
