"""仅用于回放的确定性三维帧；渲染不能改变决策。"""
import json
import math
from pathlib import Path
from PIL import Image
from .primitives import plt,draw_box,draw_pallet,setup_pallet,color_for
from ..logging.artifacts import dump,file_hash

WIDTH,HEIGHT=1800,1100


def _font():
    from matplotlib import font_manager
    # 字体枚举顺序可能随进程变化，因此优先使用确定的、完整覆盖拉丁字符和中日韩字符的字体。
    paths = sorted(font_manager.findSystemFonts(), key=lambda p: (
        0 if 'notosanscjk' in p.lower() else 1,
        0 if 'regular' in p.lower() else 1, p))
    from matplotlib.ft2font import FT2Font
    required = set(map(ord, 'PALLET 0123456789码垛候选'))
    for path in paths:
        if not any(x in path.lower() for x in ('notosanscjk','wqy','droidsansfallback')):
            continue
        if not required.issubset(FT2Font(path).get_charmap()):
            continue
        font_manager.fontManager.addfont(path)
        plt.rcParams['font.family']=[font_manager.FontProperties(fname=path).get_name(), 'DejaVu Sans']
        break
    else:
        plt.rcParams['font.family']=['DejaVu Sans', 'Droid Sans Fallback']
    plt.rcParams['axes.unicode_minus']=False


def render_episode(directory):
    _font()
    directory=Path(directory)
    episode=json.loads((directory/'episode.json').read_text())
    events=[json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines() if line]
    frames=directory/'frames';frames.mkdir(exist_ok=True)
    outputs=[];mapping=[]
    for event in events:
        out=frames/f"step_{event['step_index']:03d}";out.mkdir(exist_ok=True)
        request=event['request'];before=event['before'];container=before['container']
        candidates=request['candidates'] if request else []
        label_map={c['candidate_id']:c['display_label'] for c in candidates}
        mapping.append(dict(step_index=event['step_index'],candidate_labels=label_map))
        fig=plt.figure(figsize=(18,11),dpi=100,facecolor='#f5f7fa')
        fig.text(.035,.96,'SEMANTIC PALLET PLANNER  /  真值码垛规划',fontsize=20,weight='bold',color='#172f48')
        header=fig.text(.035,.925,f"{episode['scenario_id']}  |  {episode['method']}  |  step {event['step_index']}  |  {event['termination_reason'] or 'running'}",fontsize=12)
        fig.text(.035,.89,'确定性3D规划可视化（非Gazebo物理仿真）',fontsize=12,color='#455a64')
        supply=fig.add_axes([.035,.57,.20,.25],projection='3d')
        setup_pallet(supply,container,'取料区 / CURRENT ITEM')
        for item in before['available_items']:
            dims=[item['dimensions_mm'][k] for k in ('length','width','height')]
            draw_box(supply,dict(pose=dict(x_mm=0,y_mm=0,z_base_mm=0),oriented_size_mm=dims),color_for(item))
            flags=f"{item['weight_class']} | fragile={item['fragile']} | stackable={item['stackable']}"
            fig.text(.04,.46,f"{item['item_id']}  {dims[0]}×{dims[1]}×{dims[2]} mm\n{item['mass_kg']:.2f} kg | {item['product_category']}\n{flags}",fontsize=9,linespacing=1.7)
        pallet=fig.add_axes([.225,.34,.36,.49],projection='3d')
        draw_pallet(pallet,container,before['placed_items'])
        pallet.set_title('码垛区 / PALLET',fontsize=13)
        # 为固定容器显式绘制包围盒边线。
        l,w,h=container['length_mm'],container['width_mm'],container['max_height_mm']
        for z in [0,h]:
            pallet.plot([-l/2,l/2,l/2,-l/2,-l/2],[-w/2,-w/2,w/2,w/2,-w/2],[z]*5,color='#607d8b',alpha=.45,lw=.7)
        for x in [-l/2,l/2]:
            for y in [-w/2,w/2]:pallet.plot([x,x],[y,y],[0,h],color='#607d8b',alpha=.45,lw=.7)
        cols=4; rows=max(4,math.ceil(len(candidates)/cols))
        for index,c in enumerate(candidates):
            col=index%cols;row=index//cols
            ax=fig.add_axes([.605+col*.095,.81-(row+1)*(.72/rows),.092,.72/rows-.014],projection='3d')
            setup_pallet(ax,container)
            # 缩略图显示当前状态，并且只高亮一个候选。
            for p in before['placed_items']:draw_box(ax,p,color_for(p),alpha=.45)
            draw_box(ax,c,'#ffd54f',alpha=.60,edge='#b96000')
            ax.set_xticks([]);ax.set_yticks([]);ax.set_zticks([])
            ax.set_xlabel('');ax.set_ylabel('');ax.set_zlabel('')
            ax.set_title(f"{c['display_label']}  z={c['pose']['z_base_mm']:g}\nyaw={c['pose']['yaw_deg']}  S={c['support']['support_ratio']:.2f}",fontsize=8,pad=0)
        fig.text(.61,.845,f'TOP-{len(candidates)}  /  候选编号与JSON一致',fontsize=12,weight='bold')
        meta=fig.text(.04,.24,'',fontsize=11,linespacing=1.8,color='#243b53')
        fig.text(.04,.11,f"指令：{before['instruction_text']}",fontsize=11,wrap=True)
        fig.text(.04,.065,'蓝：重物   橙：易碎   青：电子产品   紫：易碎电子产品   灰：普通物料',fontsize=10)
        generation=event['timing'].get('total',0)*1000;selection=event['timing'].get('selection',0)*1000
        candidate=next((c for c in candidates if c['candidate_id']==event['candidate_id']),None)
        for phase in ['before','selected']:
            phase_status=event['termination_reason'] if phase=='selected' or not candidates else 'running'
            header.set_text(f"{episode['scenario_id']}  |  {episode['method']}  |  step {event['step_index']}  |  {phase_status or 'running'}")
            if phase=='selected' and candidate:
                draw_box(pallet,candidate,'#48aa74',alpha=.60,edge='#005a35',label=label_map[candidate['candidate_id']])
            state=before if phase=='before' else event['after']
            from ..evaluation.state import state_metrics
            m=state_metrics(container,state['placed_items'])
            selected_text='等待选择 / before' if phase=='before' else (f"{label_map[candidate['candidate_id']]} / {candidate['candidate_id']}\n位置 x={candidate['pose']['x_mm']:g}, y={candidate['pose']['y_mm']:g}, z={candidate['pose']['z_base_mm']:g} mm; yaw={candidate['pose']['yaw_deg']}° | 支撑率 {candidate['support']['support_ratio']:.3f}" if candidate else '无可行候选 / NO FEASIBLE CANDIDATE')
            meta.set_text(f"{selected_text}\n完成 {m['placed_count']}/{len(episode['initial_scenario']['items'])}  |  体积率 {m['volume_utilization']:.1%}  |  最高 {m['max_height_mm']:g} mm\n候选生成 {generation:.2f} ms  |  选择 {selection:.2f} ms")
            path=out/f'frame_{phase}.png'
            fig.savefig(path,dpi=100) # 不进行紧致裁剪，确保所有帧均为 1800×1100。
            outputs.append(path)
        plt.close(fig)
        if request:dump(out/'request.json',request)
    fig=plt.figure(figsize=(18,11),dpi=100,facecolor='#f5f7fa')
    ax=fig.add_axes([.15,.10,.7,.76],projection='3d')
    draw_pallet(ax,episode['final_state']['container'],episode['final_state']['placed_items'])
    fig.text(.06,.94,f"FINAL | {episode['scenario_id']} | {episode['method']} | {episode['termination_reason']}",fontsize=18,weight='bold')
    fig.text(.06,.90,'确定性3D规划可视化（非Gazebo物理仿真）',fontsize=13)
    fig.savefig(directory/'final_layout.png');plt.close(fig)
    outputs.append(directory/'final_layout.png')
    images=[]
    for path in outputs:
        with Image.open(path) as im:images.append(im.convert('RGB').resize((1080,660)).quantize(colors=128))
    if images:
        images[0].save(directory/'animation.gif',save_all=True,append_images=images[1:],duration=[650]*(len(images)-1)+[1800],loop=0,optimize=False,disposal=2)
    for im in images:im.close()
    dump(directory/'render_manifest.json',dict(renderer='matplotlib_3d',frame_size=[WIDTH,HEIGHT],gif_size=[1080,660],
        camera=dict(elevation_deg=25,azimuth_deg=-55),label_mapping=mapping,
        frame_checksums={str(p.relative_to(directory)):file_hash(p) for p in outputs},
        numeric_core_sha256=episode['core_result_sha256']))
    return str(directory/'animation.gif')


def prepare_visual_request(request,directory):
    """为未来 requires_images=True 的选择器提供按需输入钩子。

    该渲染器只接收输入，不接收已选 ID、标注、反馈或未来物料。
    """
    import copy
    from .primitives import render_workspace,render_montage
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    q=copy.deepcopy(request)
    case=dict(q,decision_case_id=q['request_id'],step_index=0)
    scenario={'container':q['container']}
    render_workspace(case,scenario,directory/'workspace.png')
    render_montage(case,scenario,{'candidates':q['candidates']},directory/'candidates_montage.png')
    q['visual_inputs']={'workspace_image':str((directory/'workspace.png').resolve()),'candidate_montage':str((directory/'candidates_montage.png').resolve())}
    return q
