"""Read-only O3 order evidence: offline interactive 3D, GIF and metric tables."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from PIL import Image
from plotly.offline import get_plotlyjs

from .primitives import plt, setup_pallet, draw_box, color_for
from ..evaluation.attribute_metrics_v2 import reconstruct, raw_metrics
from ..evaluation.policy_v2 import evaluate, violations
from ..evaluation.replay_values_v2 import replay_values_equal
from ..evaluation.state import state_metrics
from ..vlm.pilot_protocol_v2 import digest

METHODS = [('geometry_greedy', 'Geometry', '几何贪心'),
           ('fixed_attribute', 'Fixed Attribute', '固定属性启发式'),
           ('public_parser', 'Public Parser', '公开解析器＋Executor'),
           ('flash_policy_parser', 'Flash AST', 'Flash AST＋Executor'),
           ('truth_ast_executor', 'Truth AST', '真值 AST＋Executor（特权参考）')]


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_data(experiment, scenario, policy_id):
    episode_id = f'O3_{scenario}_{policy_id}'
    data = {'scenario': scenario, 'policy_id': policy_id, 'episode_id': episode_id,
            'source_experiment': str(experiment), 'methods': []}
    sources, step_rows, metric_rows = {}, [], []
    def track(path):
        sources[str(path.relative_to(experiment))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for method, name, label in METHODS:
        folder = experiment/'episodes'/method/episode_id
        info_path, events_path = folder/'episode.json', folder/'steps.jsonl'
        info = read(info_path)
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line]
        assert digest(events) == info['core_result_sha256'], method+': event digest'
        track(info_path); track(events_path)
        task, summary, states = info['task'], info['summary'], []
        assert summary['execution_mode'] == 'observe_business'
        if not data.get('instruction'):
            data.update(instruction=task['instruction_text'], source_order_key=task['source_order_key'],
                        truth_policy=task['truth_policy'], attribute_source=task['attribute_source'],
                        planned_items=summary['planned_items'])
        assert data['instruction'] == task['instruction_text']
        previous = []
        for index, event in enumerate(events):
            assert event['step_index'] == index and event['before_placed'] == previous
            req_path = folder/'selector_inputs'/event['request_id']/'public_request.json'
            req = read(req_path); track(req_path)
            assert digest(req['candidates']) == event['candidate_set_digest']
            assert req['state_hash'] == event['state_hash'] and req['policy_digest'] == event['policy_digest']
            selected = next((c for c in req['candidates'] if c['display_label'] == event['proposed_label']), None)
            assert not event['screen_intervened']
            if selected:
                assert event['proposed_label'] == event['committed_label']
                placed = event['after_placed'][-1]
                assert placed['pose'] == selected['pose'] and placed['item_id'] == event['current_item_id']
                evaluation = evaluate(req, selected, task['truth_policy'], req['container'])
                assert evaluation['new_business_violation_count'] == event['raw_new_business_violations']
                assert evaluation['worsened_existing_violation_count'] == event['raw_worsened_business_violations']
            else:
                assert not event['committed_label']
                evaluation = None
            after_ids, _ = violations(reconstruct(event['after_placed']), task['truth_policy'])
            before_ids, _ = violations(reconstruct(event['before_placed']), task['truth_policy'])
            assert replay_values_equal(raw_metrics(reconstruct(event['after_placed'])), event['attribute_after'])
            data['container'] = req['container']
            state = {k: event[k] for k in (
                'step_index', 'request_id', 'state_hash', 'policy_digest', 'current_item_id',
                'before_placed', 'after_placed', 'attribute_before', 'attribute_after',
                'proposed_label', 'committed_label', 'status', 'raw_new_business_violations',
                'raw_worsened_business_violations', 'raw_post_business_violations',
                'would_screen_block', 'screen_intervened', 'diagnostic_continuation',
                'raw_priority_regret', 'parsed_ast', 'candidate_count', 'topk_feasible_count')}
            state.update(current_item=req['available_items'][0], selected_candidate=selected,
                         candidates=req['candidates'], violations_before=before_ids,
                         violations_after=after_ids,
                         new_violation_ids=evaluation['new_violation_instances'] if evaluation else [],
                         worsened_violation_ids=evaluation['worsened_existing_violation_instances'] if evaluation else [])
            states.append(state)
            pose = selected['pose'] if selected else {}
            step_rows.append({'method': method, 'step': index+1, 'item': event['current_item_id'],
                              'proposed': event['proposed_label'], 'committed': event['committed_label'],
                              **{key: pose.get(key) for key in ('x_mm','y_mm','z_base_mm','yaw_deg')},
                              'candidate_count': event['candidate_count'],
                              'business_feasible_count': event['topk_feasible_count'],
                              'new_violations': event['raw_new_business_violations'],
                              'worsened_violations': event['raw_worsened_business_violations'],
                              'post_violations': len(after_ids), 'status': event['status'],
                              'request_id': event['request_id']})
            previous = event['after_placed']
        assert previous == info['final_placed']
        final_ids, _ = violations(reconstruct(previous), task['truth_policy'])
        assert final_ids == summary['final_business_violation_ids']
        assert replay_values_equal(state_metrics(data['container'], previous), summary['final_geometry_metrics'])
        assert replay_values_equal(raw_metrics(reconstruct(previous)), summary['final_attribute_metrics'])
        row = {'method': method, 'label': label, 'placed': summary['placed_items'],
               'planned': summary['planned_items'], 'completed': summary['completed'],
               'clean_completion': summary['episode_attribute_success'],
               'item_ratio': summary['placed_item_ratio'], 'volume_ratio': summary['placed_volume_ratio'],
               'violation_steps': summary['committed_business_violation_steps'],
               'violation_step_rate': summary['business_violation_step_rate'],
               'final_violations': len(final_ids),
               'fragile_overload_count': sum(':load:' in key for key in final_ids),
               'forbidden_contact_pairs': sum(':contact:' in key for key in final_ids),
               'new_violation_instances': summary['new_business_violation_instances_total'],
               'worsened_instances': summary['worsened_business_violation_instances_total'],
               'max_fragile_load_kg': max(summary['final_attribute_metrics']['fragile_load_by_item_kg'].values(), default=None),
               **{k: summary['final_attribute_metrics'][k] for k in (
                   'fragile_load_ratio_max','heavy_mass_weighted_z_mm','heavy_center_distance_mm')},
               **summary['final_geometry_metrics'],
               'physical_violations': summary['committed_physical_violations'],
               'screen_interventions': summary['screen_interventions'],
               'termination': summary['termination_reason']}
        metric_rows.append(row)
        data['methods'].append({'method': method, 'name': name, 'label': label,
                                'summary': summary, 'metrics': row, 'steps': states})
    return data, sources, step_rows, metric_rows


HTML = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>O3 完整订单 · 五方法 3D 回放</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f6f8;color:#20333e;font:15px/1.6 system-ui,"Noto Sans CJK SC",sans-serif}
main{max-width:1720px;margin:auto;padding:26px}h1{margin:0;font-size:28px}h2{font-size:20px;margin:20px 0 8px}
.muted{color:#607580}.banner,.controls,.panel,.results{background:white;border:1px solid #dbe4e9;border-radius:12px;padding:18px;margin-top:14px}
.banner{border-left:5px solid #117981}.controls{position:sticky;top:0;z-index:5;box-shadow:0 3px 12px #20333e13}
.row{display:flex;align-items:center;gap:14px;flex-wrap:wrap}button,select{padding:7px 13px;border:1px solid #bfd0d7;background:#fff;border-radius:6px;color:#20333e;cursor:pointer}button.primary{background:#117981;color:white}input[type=range]{flex:1;min-width:200px;accent-color:#117981}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.panel{margin-top:0;padding:12px;min-width:0}.panel h3{font-size:16px;margin:0}.plot{height:340px}.detail{font-size:13px;min-height:112px}.red{color:#b53636}.tag{font-size:12px;padding:2px 7px;background:#eef4f5;border-radius:4px}pre{font:12px/1.45 monospace;white-space:pre-wrap;max-height:220px;overflow:auto}.legend span{display:inline-flex;align-items:center;margin-right:15px}.dot{width:12px;height:12px;display:inline-block;margin-right:5px;border-radius:2px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:13px}td,th{text-align:left;padding:9px 12px;border-bottom:1px solid #e3eaee}th{background:#eef4f5}a{color:#117981}.note{font-size:13px}.readme{padding:8px 14px}.readme li{margin:10px 0}
@media(max-width:1250px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){main{padding:12px}.grid{grid-template-columns:1fr}.controls{position:static}h1{font-size:22px}}
</style>
<main><h1>完整订单：五方法逐步 3D 回放</h1><div id="subtitle" class="muted"></div>
<div class="banner"><b>本单公开政策</b><div id="instruction"></div><div class="note muted">业务违规直接执行；物理检查保留。这里展示实验完成后的回放与评价，未向决策模型提供未来物料。候选 Cxx 编号只在本方法当前状态内有效。</div></div>
<div class="controls"><div class="row"><button id="play" class="primary">▶ 播放</button><button id="prev">上一步</button><button id="next">下一步</button><b id="progress"></b><input type="range" id="slider" min="0" value="0"><select id="speed"><option value="1800">1.8 秒/步</option><option value="3000">3 秒/步</option><option value="900">0.9 秒/步</option></select></div>
<div class="row note" style="margin-top:10px"><label>视图 <select id="phase"><option value="after">放置后</option><option value="before">放置前＋所选位置</option></select></label><label><input id="candidates" type="checkbox">显示本步候选中心点</label><label><input id="sync" type="checkbox" checked>同步旋转视角</label><button id="reset">重置视角</button><button id="final">查看最终布局</button><span>拖动旋转；滚轮缩放；悬停查看箱体属性和候选。</span></div></div>
<div class="legend note" style="margin:14px 0"><span><i class="dot" style="background:#78909c"></i>普通</span><span><i class="dot" style="background:#355c9a"></i>重箱</span><span><i class="dot" style="background:#ef8a32"></i>易碎（也可能是重箱）</span><span><i class="dot" style="background:#31a9b8"></i>电子产品</span><span><i class="dot" style="background:#8e63b0"></i>易碎电子产品</span><span>金色框＝本步选中；红框＝参与业务违规；红线＝禁止接触关系连线，非接触面积。</span></div>
<div class="grid" id="boards"></div>
<div class="results"><h2>最终指标：同一个订单的五方法结果</h2><div class="note muted">以下指标始终对应最终布局，不随滑块变化。步骤违规率＝新增或加重违规的提交步数 / 实际提交步数。承载比例是相对物理承重上限；业务限载仍为 1 kg。体积利用率以整个容器体积为分母。</div><div class="scroll"><table id="metrics"></table></div><p class="note"><a href="final_metrics.csv">下载最终指标 CSV</a> · <a href="final_metrics.png">打开指标表图片</a> · <a href="final_metrics.json">完整原始指标 JSON</a> · <a href="step_choices.csv">下载逐步选址 CSV</a> · <a href="five_methods.gif">打开同步动图</a> · <a href="final_layouts.png">打开最终布局大图</a> · <a href="case_data.json">完整案例数据 JSON</a></p></div>
<div class="results"><h2>本案例怎么解释</h2><div id="conclusion"></div><p class="note muted">该案例用于解释布局、承载和接触之间的取舍，不代表全数据平均表现。公开 Parser、Flash 与真值参考布局相同，不表示它们拥有相同输入权限。真值 AST 为特权逐步参考。</p></div></main>
<script>__PLOTLY__</script><script id="evidence" type="application/json">__DATA__</script><script>
const D=JSON.parse(document.getElementById('evidence').textContent),N=D.planned_items;
const $=id=>document.getElementById(id),pct=x=>x==null?'N/A':(x*100).toFixed(2)+'%',num=x=>x==null?'N/A':Number(x).toFixed(2);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let step=Math.max(0,Math.min(N,Number(new URLSearchParams(location.hash.slice(1)).get('step'))||0)),timer=null,painting=false,pending=false,cameraBusy=false;
const defaultCamera={eye:{x:1.55,y:-1.7,z:1.25}};
$('subtitle').textContent=`${D.scenario} / ${D.policy_id} · 来源订单 ${D.source_order_key} · ${N} 箱 · 真实实验轨迹 · 属性感知标注 ${D.attribute_source}`;
$('instruction').textContent=D.instruction;$('slider').max=N;
function vertices(p){let {x_mm:x,y_mm:y,z_base_mm:z}=p.pose,[l,w,h]=p.oriented_size_mm;return [[x-l/2,y-w/2,z],[x+l/2,y-w/2,z],[x+l/2,y+w/2,z],[x-l/2,y+w/2,z],[x-l/2,y-w/2,z+h],[x+l/2,y-w/2,z+h],[x+l/2,y+w/2,z+h],[x-l/2,y+w/2,z+h]]}
const edges=[[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]];
function wire(p,color,width){const v=vertices(p),xyz=[[],[],[]];for(const [a,b] of edges){for(let k=0;k<3;k++)xyz[k].push(v[a][k],v[b][k],null)}return {type:'scatter3d',mode:'lines',x:xyz[0],y:xyz[1],z:xyz[2],line:{color,width},hoverinfo:'skip',showlegend:false}}
function color(p){return p.fragile?(p.product_category==='electronics'?'#8e63b0':'#ef8a32'):(p.product_category==='electronics'?'#31a9b8':p.weight_class==='heavy'?'#355c9a':'#78909c')}
function involved(ids){return new Set(ids.flatMap(id=>id.split(':').slice(2)))}
function traces(m){const e=step?m.steps[Math.min(step-1,m.steps.length-1)]:null,after=$('phase').value==='after',placed=e?(after?e.after_placed:e.before_placed):[],ids=e?(after?e.violations_after:e.violations_before):[],bad=involved(ids),out=[];
 const c=D.container;out.push({type:'scatter3d',mode:'lines',x:[-c.length_mm/2,c.length_mm/2,c.length_mm/2,-c.length_mm/2,-c.length_mm/2],y:[-c.width_mm/2,-c.width_mm/2,c.width_mm/2,c.width_mm/2,-c.width_mm/2],z:[0,0,0,0,0],line:{color:'#8fa3ad',width:4},hoverinfo:'skip',showlegend:false});
 for(const p of placed){const v=vertices(p),current=after&&e.committed_label&&p.item_id===e.current_item_id;
  out.push({type:'mesh3d',x:v.map(a=>a[0]),y:v.map(a=>a[1]),z:v.map(a=>a[2]),i:[0,0,4,4,0,0,1,1,2,2,3,3],j:[1,2,5,6,1,5,2,6,3,7,0,4],k:[2,3,6,7,5,4,6,5,7,6,4,7],color:color(p),opacity:current?0.95:0.72,flatshading:true,showlegend:false,hovertemplate:`${esc(p.item_id)}<br>质量 ${num(p.mass_kg)} kg · ${esc(p.weight_class)}<br>易碎 ${p.fragile?'是':'否'} · ${esc(p.product_category)}<br>承载 ${num(p.supported_load_kg)} kg<br>尺寸 ${p.oriented_size_mm.join('×')} mm<br>底面 (${num(p.pose.x_mm)}, ${num(p.pose.y_mm)}, ${num(p.pose.z_base_mm)})<extra></extra>`});
  out.push(wire(p,bad.has(p.item_id)?'#d43636':'#536570',bad.has(p.item_id)?6:1.6));if(current)out.push(wire(p,'#e8b022',9));
  out.push({type:'scatter3d',mode:'text',x:[p.pose.x_mm],y:[p.pose.y_mm],z:[p.pose.z_base_mm+p.oriented_size_mm[2]+16],text:[p.item_id.replace('item_','')],textfont:{size:12,color:'#182c38'},hoverinfo:'skip',showlegend:false});
 }
 const by=Object.fromEntries(placed.map(p=>[p.item_id,p]));for(const id of ids){if(!id.includes(':contact:'))continue;const [a,b]=id.split(':').slice(2).map(x=>by[x]);if(a&&b)out.push({type:'scatter3d',mode:'lines+markers',x:[a.pose.x_mm,b.pose.x_mm],y:[a.pose.y_mm,b.pose.y_mm],z:[a.pose.z_base_mm+a.oriented_size_mm[2]/2,b.pose.z_base_mm+b.oriented_size_mm[2]/2],line:{color:'#d43636',width:9},marker:{size:3,color:'#d43636'},text:[id,id],hovertemplate:'%{text}<extra>禁止接触关系</extra>',showlegend:false})}
 if(e&&!after&&e.selected_candidate)out.push(wire(e.selected_candidate,'#e8b022',8));
 if(e&&$('candidates').checked){const cs=e.candidates;out.push({type:'scatter3d',mode:'markers',x:cs.map(c=>c.pose.x_mm),y:cs.map(c=>c.pose.y_mm),z:cs.map(c=>c.pose.z_base_mm+c.oriented_size_mm[2]/2),marker:{size:cs.map(c=>c.display_label===e.proposed_label?8:4),color:cs.map(c=>c.display_label===e.proposed_label?'#e8b022':'#808d98'),opacity:.65},text:cs.map(c=>`${c.display_label}<br>底面 (${c.pose.x_mm},${c.pose.y_mm},${c.pose.z_base_mm}) mm<br>yaw ${c.pose.yaw_deg}° · 几何分 ${num(c.geometry_score)}`),hovertemplate:'%{text}<extra>本步候选中心</extra>',showlegend:false})}
 return out;
}
function layout(){const c=D.container;return {margin:{l:0,r:0,t:0,b:0},paper_bgcolor:'white',uirevision:'keep-camera',showlegend:false,scene:{xaxis:{title:'X / mm',range:[-c.length_mm/2,c.length_mm/2]},yaxis:{title:'Y / mm',range:[-c.width_mm/2,c.width_mm/2]},zaxis:{title:'Z / mm',range:[0,c.max_height_mm]},aspectmode:'manual',aspectratio:{x:c.length_mm/c.max_height_mm,y:c.width_mm/c.max_height_mm,z:1}}}}
function detail(m){if(!step)return '初始空托盘；各方法从同一物料到货顺序开始。';const e=m.steps[Math.min(step-1,m.steps.length-1)],c=e.selected_candidate,p=c?.pose,metric=$('phase').value==='after'?e.attribute_after:e.attribute_before,ids=$('phase').value==='after'?e.violations_after:e.violations_before;
 return `<b>第 ${e.step_index+1} 箱：${esc(e.current_item_id)}</b> · ${esc(e.current_item.weight_class)} / ${e.current_item.fragile?'易碎':'非易碎'} / ${esc(e.current_item.product_category)}<br>提议 <b>${esc(e.proposed_label??'无')}</b> → 提交 <b>${esc(e.committed_label??'无')}</b> · 候选 ${e.candidate_count} / 业务可行 ${e.topk_feasible_count}<br>${p?`底面 (${p.x_mm}, ${p.y_mm}, ${p.z_base_mm}) mm · yaw ${p.yaw_deg}°`:'未提交动作'}<br><span class="${ids.length?'red':''}">放置后新增 ${e.raw_new_business_violations??'N/A'} / 加重 ${e.raw_worsened_business_violations??'N/A'}；当前视图累计违规 ${ids.length}</span><br>当前视图重箱底面均高 ${num(metric.heavy_mass_weighted_z_mm)} mm · 中心距离 ${num(metric.heavy_center_distance_mm)} mm<br>屏障实际干预：否 · 状态 ${esc(e.status)}<details><summary>违规实例、原始 AST 与请求绑定</summary><pre>${esc(JSON.stringify({violations:ids,new:e.new_violation_ids,request_id:e.request_id,state_hash:e.state_hash,policy_digest:e.policy_digest,parsed_ast:e.parsed_ast},null,2))}</pre></details>`;
}
for(const [i,m] of D.methods.entries()){const p=document.createElement('section');p.className='panel';p.innerHTML=`<h3>${esc(m.name)} <span class="tag">${esc(m.label)}</span></h3><div class="plot" id="plot${i}"></div><div class="detail" id="detail${i}"></div>`;$('boards').append(p)}
const note=document.createElement('section');note.className='panel readme';note.innerHTML='<h3>读图顺序</h3><ol><li>先播放，观察五种方法从空托盘逐箱放置。</li><li>切到“放置前”，打开候选中心点，查看该方法本步选了哪个位置。</li><li>红框找参与违规的箱体；红线找禁止接触关系；金框找本步新增箱体。</li><li>展开卡片中的原始 AST，查看 Flash 与公开 Parser 的规则来源差别。</li><li>最后看表：违规实例更少，不一定表示易碎箱承载或重箱位置更好。</li></ol><div class="muted note">编号在各方法状态内重新映射；不能仅凭 Cxx 相同认定是相同物理位置。数字标签对应 item_XX。三种语义方法轨迹相同时，页面仍分别保留其真实记录。</div>';$('boards').append(note);
async function render(){if(painting){pending=true;return}painting=true;const current=step;$('progress').textContent=current?`第 ${current} / ${N} 箱`:'初始状态';$('slider').value=current;try{await Promise.all(D.methods.map((m,i)=>{ $('detail'+i).innerHTML=detail(m);return Plotly.react('plot'+i,traces(m),layout(),{responsive:true,displaylogo:false,modeBarButtonsToRemove:['toImage']})}))}catch(err){$('progress').textContent='渲染失败：'+err.message;console.error(err)}finally{painting=false;if(pending){pending=false;render()}}}
async function init(){await render();await Promise.all(D.methods.map((_,i)=>Plotly.relayout('plot'+i,{'scene.camera':defaultCamera})));D.methods.forEach((_,i)=>$('plot'+i).on('plotly_relayout',async e=>{const c=e['scene.camera'];if(!c||cameraBusy||!$('sync').checked)return;cameraBusy=true;try{await Promise.all(D.methods.map((_,j)=>j===i?Promise.resolve():Plotly.relayout('plot'+j,{'scene.camera':c})))}finally{cameraBusy=false}}));window.caseReady=true;document.body.dataset.ready='true'}
function stop(){clearInterval(timer);timer=null;$('play').textContent='▶ 播放'}
$('play').onclick=()=>{if(timer){stop();return}if(step===N)step=0;render();$('play').textContent='暂停';timer=setInterval(()=>{if(painting)return;if(step>=N){stop();return}step++;render()},Number($('speed').value))};
$('slider').oninput=e=>{stop();step=Number(e.target.value);render()};$('prev').onclick=()=>{stop();step=Math.max(0,step-1);render()};$('next').onclick=()=>{stop();step=Math.min(N,step+1);render()};$('final').onclick=()=>{stop();step=N;render()};$('speed').onchange=()=>{if(timer){stop();$('play').click()}};$('phase').onchange=render;$('candidates').onchange=render;$('reset').onclick=()=>Promise.all(D.methods.map((_,i)=>Plotly.relayout('plot'+i,{'scene.camera':defaultCamera})));
const fields=[['方法',m=>m.label],['放置数',m=>m.metrics.placed+'/'+m.metrics.planned],['无违规完成',m=>m.metrics.clean_completion?'是':'否'],['违规步骤',m=>m.metrics.violation_steps+'/'+m.metrics.placed],['步骤违规率',m=>pct(m.metrics.violation_step_rate)],['最终违规数',m=>m.metrics.final_violations],['业务超载箱数',m=>m.metrics.fragile_overload_count],['禁止接触对',m=>m.metrics.forbidden_contact_pairs],['易碎最大承载 kg',m=>num(m.metrics.max_fragile_load_kg)],['物理承载比 max',m=>pct(m.metrics.fragile_load_ratio_max)],['重箱均高 mm',m=>num(m.metrics.heavy_mass_weighted_z_mm)],['重箱中心距 mm',m=>num(m.metrics.heavy_center_distance_mm)],['垛高 mm',m=>num(m.metrics.max_height_mm)],['最小支撑率',m=>pct(m.metrics.minimum_support_ratio)],['体积利用率',m=>pct(m.metrics.volume_utilization)],['整体质心偏移 mm',m=>num(m.metrics.center_of_mass_offset_mm)],['物理违规',m=>m.metrics.physical_violations]];
$('metrics').innerHTML='<thead><tr>'+fields.map(([n])=>'<th>'+n+'</th>').join('')+'</tr></thead><tbody>'+D.methods.map(m=>'<tr>'+fields.map(([,f])=>'<td>'+esc(f(m))+'</td>').join('')+'</tr>').join('')+'</tbody>';
$('conclusion').textContent=D.explanation;init();
</script></html>'''


def static_render(data, output):
    from matplotlib import font_manager
    font = Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        family = font_manager.FontProperties(fname=str(font)).get_name()
    else:
        family = 'Noto Sans CJK SC'
    plt.rcParams['font.family'] = ['sans-serif']
    plt.rcParams['font.sans-serif'] = [family, 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    frames = []
    for progress in range(data['planned_items']+1):
        fig = plt.figure(figsize=(18,10), dpi=105, facecolor='#f7f9fa')
        for index, method in enumerate(data['methods']):
            ax = fig.add_subplot(2,3,index+1,projection='3d')
            event = method['steps'][min(progress-1,len(method['steps'])-1)] if progress else None
            state = event['after_placed'] if event else []
            ids = event['violations_after'] if event else []
            involved = {item for key in ids for item in key.split(':')[2:]}
            setup_pallet(ax,data['container'])
            for box in state:
                draw_box(ax,box,color_for(box),alpha=.88,
                         edge='#c63030' if box['item_id'] in involved else '#4b5b65',
                         label=box['item_id'].replace('item_',''))
                if event and box['item_id']==event['current_item_id'] and event['committed_label']:
                    vertices = box_vertices(box)
                    for a,b in BOX_EDGES:
                        ax.plot(*zip(vertices[a],vertices[b]),color='#d5a000',linewidth=2.5)
            by = {p['item_id']:p for p in state}
            for key in ids:
                if ':contact:' not in key:continue
                a,b=(by[i] for i in key.split(':')[2:])
                ax.plot([a['pose']['x_mm'],b['pose']['x_mm']],
                        [a['pose']['y_mm'],b['pose']['y_mm']],
                        [a['pose']['z_base_mm']+a['oriented_size_mm'][2]/2,
                         b['pose']['z_base_mm']+b['oriented_size_mm'][2]/2],color='#d43636',linewidth=3)
            action = f"{event['current_item_id']} → {event['committed_label']}" if event else '初始空托盘'
            ax.set_title(f"{method['name']} | {action}\n已放 {len(state)} / {data['planned_items']} · 累计业务违规 {len(ids)}",fontsize=10,pad=1)
        ax = fig.add_subplot(2,3,6);ax.axis('off')
        lines = [f"当前进度：{progress}/{data['planned_items']}",'',
                 '金色框：本步新增箱体','红色边框：参与业务违规的箱体',
                 '红线：禁止接触关系连线（非接触面积）','橙色：易碎；蓝色：重物；青色：电子产品','',
                 '最终结果（固定显示）','方法              放置    违规实例   违规步率']
        for m in data['methods']:
            r=m['metrics'];lines.append(f"{m['name']:<16} {r['placed']}/{r['planned']}      {r['final_violations']}      {r['violation_step_rate']:.1%}")
        lines += ['', '全部方法实际放完 17 箱；语义方法最终布局相同。',
                  '几何：3 对禁止接触；易碎承载 0 kg。',
                  '语义：1 对禁止接触＋1 个业务超载箱。',
                  '语义违规实例少，但易碎箱承载升至 9.48 kg。',
                  '查看 HTML 可旋转、切换放置前后及显示候选。']
        ax.text(0,.97,'\n'.join(lines),va='top',fontsize=10,linespacing=1.25)
        fig.suptitle(f"完整订单五方法回放 · {data['scenario']} / {data['policy_id']} · 来源 {data['source_order_key']}",fontsize=19,y=.98)
        fig.subplots_adjust(left=.025,right=.98,bottom=.045,top=.91,hspace=.20,wspace=.08)
        path=output/'frames'/f'step_{progress:02d}.png'
        fig.savefig(path);plt.close(fig)
        if progress==data['planned_items']:
            Image.open(path).save(output/'final_layouts.png')
        with Image.open(path) as image:
            frames.append(image.convert('RGB').quantize(colors=192))
    frames[0].save(output/'five_methods.gif',save_all=True,append_images=frames[1:],
                   duration=[1400]+[1100]*(len(frames)-2)+[3500],loop=0,optimize=False)
    for frame in frames:frame.close()
    fields = [
        ('实际放置 / 订单总数',lambda r:f"{r['placed']}/{r['planned']}"),
        ('无违规完成',lambda r:'是' if r['clean_completion'] else '否'),
        ('违规步骤 / 已提交步骤',lambda r:f"{r['violation_steps']}/{r['placed']}"),
        ('步骤业务违规率',lambda r:f"{r['violation_step_rate']:.2%}"),
        ('最终业务违规实例',lambda r:str(r['final_violations'])),
        ('易碎业务超载箱数',lambda r:str(r['fragile_overload_count'])),
        ('禁止接触箱体对数',lambda r:str(r['forbidden_contact_pairs'])),
        ('易碎最大承载 / kg',lambda r:f"{r['max_fragile_load_kg']:.2f}"),
        ('易碎物理承载比例最大值',lambda r:f"{r['fragile_load_ratio_max']:.2%}"),
        ('重箱质量加权底面高度 / mm',lambda r:f"{r['heavy_mass_weighted_z_mm']:.2f}"),
        ('重箱质量加权中心距离 / mm',lambda r:f"{r['heavy_center_distance_mm']:.2f}"),
        ('最终垛高 / mm',lambda r:f"{r['max_height_mm']:.0f}"),
        ('最小支撑率',lambda r:f"{r['minimum_support_ratio']:.2%}"),
        ('平均支撑率',lambda r:f"{r['mean_support_ratio']:.2%}"),
        ('容器体积利用率',lambda r:f"{r['volume_utilization']:.2%}"),
        ('整体质心偏移 / mm',lambda r:f"{r['center_of_mass_offset_mm']:.2f}"),
        ('已放总体质量 / kg',lambda r:f"{r['total_mass_kg']:.2f}"),
        ('已放数量比例 / 已放体积比例',lambda r:f"{r['item_ratio']:.0%} / {r['volume_ratio']:.0%}"),
        ('提交物理违规 / 屏障干预',lambda r:f"{r['physical_violations']} / {r['screen_interventions']}")]
    fig,ax=plt.subplots(figsize=(16,10),dpi=140);ax.axis('off')
    table=ax.table(cellText=[[name]+[fn(m['metrics']) for m in data['methods']] for name,fn in fields],
                   colLabels=['最终指标']+[m['name'] for m in data['methods']],
                   colWidths=[.30]+[.14]*5,cellLoc='center',loc='center')
    table.auto_set_font_size(False);table.set_fontsize(10);table.scale(1,1.9)
    for (r,c),cell in table.get_celld().items():
        cell.set_edgecolor('#dce5e9')
        cell.set_facecolor('#dceff0' if r==0 else '#f4f7f8' if r%2 else 'white')
    ax.set_title('SCN_0054 / P0 · 17 箱完整订单最终指标',fontsize=20,pad=22)
    fig.text(.05,.045,'业务限载为 1 kg，物理承载比例小于 100% 仍可能违反业务要求。\n'
             '同一案例用于解释取舍；真值 AST 为特权逐步参考，不能视为全订单最优。',fontsize=11)
    fig.savefig(output/'final_metrics.png',bbox_inches='tight');plt.close(fig)


BOX_EDGES = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]


def box_vertices(p):
    x,y,z=(p['pose'][k] for k in ('x_mm','y_mm','z_base_mm'))
    l,w,h=p['oriented_size_mm']
    return [(x-l/2,y-w/2,z),(x+l/2,y-w/2,z),(x+l/2,y+w/2,z),(x-l/2,y+w/2,z),
            (x-l/2,y-w/2,z+h),(x+l/2,y-w/2,z+h),(x+l/2,y+w/2,z+h),(x-l/2,y+w/2,z+h)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',type=Path,required=True)
    parser.add_argument('--scenario',default='SCN_0054')
    parser.add_argument('--policy',default='P0')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    # This case narrative deliberately names the selected order, not arbitrary
    # future cases. Geometry/statistics extraction itself is reusable.
    if (args.scenario,args.policy)!=('SCN_0054','P0'):
        raise ValueError('This illustrated narrative is frozen to SCN_0054 / P0')
    data,sources,choices,metrics=build_data(args.experiment.resolve(),args.scenario,args.policy)
    data['explanation']='本案例五种方法都完成17/17，比较分母一致。Geometry 有3对禁止接触，易碎箱无承载；其余四方法有1对禁止接触，并给易碎箱 item_12 累计承载9.48 kg（业务上限1 kg），合计2个违规实例。它们的重箱高度、中心距离和垛高也更差，因此不能只用违规总数认定布局全面更好。Flash 与公开 Parser、真值参考选择相同，未表现独有收益。本例用于解释机制，不替代全部订单统计。'
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False);(output/'frames').mkdir()
    write(output/'case_data.json',data);write_csv(output/'step_choices.csv',choices)
    write_csv(output/'final_metrics.csv',metrics)
    write(output/'final_metrics.json',{m['method']:m['summary'] for m in data['methods']})
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    (output/'index.html').write_text(HTML.replace('__PLOTLY__',get_plotlyjs()).replace('__DATA__',payload))
    static_render(data,output)
    write(output/'evidence_manifest.json',{'source_experiment':str(args.experiment.resolve()),
          'renderer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'scenario':args.scenario,'policy':args.policy,'source_sha256':sources,
          'episode_core_digests':{m['method']:read(args.experiment/'episodes'/m['method']/data['episode_id']/'episode.json')['core_result_sha256'] for m in data['methods']},
          'rendered_steps':data['planned_items']+1,'method_step_records':len(choices),
          'checks':{'event_digest':True,'request_candidate_binding':True,'committed_equals_proposed':True,
                    'transition_chain':True,'recomputed_violations':True,'recomputed_final_metrics':True},
          'scope':'single_order_explanatory_case_not_population_estimate'})
    print(json.dumps({'output':str(output),'frames':data['planned_items']+1,'methods':len(METHODS),'checks':'PASS'},ensure_ascii=False))


if __name__=='__main__':main()
