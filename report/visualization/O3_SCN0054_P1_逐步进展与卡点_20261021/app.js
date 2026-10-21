'use strict';
const D=JSON.parse(document.getElementById('case-data').textContent);
const $=id=>document.getElementById(id), COLORS=['#718597','#3673ac','#007e82'];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,d=1)=>v==null?'N/A':Number(v).toFixed(d);
const pct=v=>v==null?'N/A':`${(v*100).toFixed(1)}%`;
const names=D.variants.map(v=>v.name);
const params=new URLSearchParams(location.hash.slice(1));
let mode=params.get('mode')==='observe_business'?'observe_business':'safe';
let step=Math.max(0,Math.min(17,Math.floor(Number(params.get('step'))||0)));
let phase=params.get('phase')==='before'?'before':'after';
let playing=false,timer=null,painting=false,pending=false,initialized=false,syncBusy=false;
let camera={eye:{x:1.55,y:-1.75,z:1.25},up:{x:0,y:0,z:1},center:{x:0,y:0,z:0}};
const cameras=[0,1,2].map(()=>JSON.parse(JSON.stringify(camera)));
const inspection=[null,null,null],keySteps=[5,6,8,12,16,17];
const statusText={select:'已提交',all_items_placed:'全部放完',no_physical_candidate:'无物理候选，停止',no_business_feasible_candidate:'无业务可行候选，停止'};
const shortStatus={select:'进行中',all_items_placed:'完整完成',no_physical_candidate:'物理终止',no_business_feasible_candidate:'业务拒放'};
window.app={ready:false,state:()=>({step,mode,phase,playing}),data:D,go:go,setMode:setMode};

function current(track,n=step,p=phase){
 if(n===0)return {e:null,frozen:false,placed:[],m:D.initial_metrics,active:false};
 const frozen=n>track.steps.length,e=track.steps[Math.min(n-1,track.steps.length-1)];
 const before=p==='before'&&!frozen;
 return {e,frozen,placed:before?e.before:e.after,m:before?e.before_metrics:e.after_metrics,active:!frozen,before};
}
function boxVertices(p){
 const {x_mm:x,y_mm:y,z_base_mm:z}=p.pose,[l,w,h]=p.oriented_size_mm;
 return [[x-l/2,y-w/2,z],[x+l/2,y-w/2,z],[x+l/2,y+w/2,z],[x-l/2,y+w/2,z],
         [x-l/2,y-w/2,z+h],[x+l/2,y-w/2,z+h],[x+l/2,y+w/2,z+h],[x-l/2,y+w/2,z+h]];
}
const EDGES=[[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]];
function wire(p,color,width,dash){
 const vv=boxVertices(p),xyz=[[],[],[]];
 for(const [a,b] of EDGES)for(let k=0;k<3;k++)xyz[k].push(vv[a][k],vv[b][k],null);
 return {type:'scatter3d',mode:'lines',x:xyz[0],y:xyz[1],z:xyz[2],line:{color,width,...(dash?{dash}: {})},hoverinfo:'skip',showlegend:false};
}
function material(p){return p.fragile?(p.product_category==='electronics'?'#956fb2':'#de9b39'):(p.product_category==='electronics'?'#42a3ac':p.weight_class==='heavy'?'#3673ac':'#8096aa');}
function mesh(p,highlight){
 const v=boxVertices(p);
 const hover=`<b>${esc(p.item_id.replace('item_','箱 '))}</b><br>${p.oriented_size_mm.join(' × ')} mm · ${num(p.mass_kg)} kg<br>${p.fragile?'易碎':'非易碎'} / ${p.weight_class==='heavy'?'重箱':p.weight_class==='medium'?'中箱':'轻箱'} / ${p.product_category==='electronics'?'电子产品':'普通品类'}<br>底面 (${num(p.pose.x_mm)}, ${num(p.pose.y_mm)}, ${num(p.pose.z_base_mm)}) mm<br>支撑传递承载 ${num(p.supported_load_kg??0,2)} kg<br>合成物理承载上限 ${num(p.top_load_limit_kg_synthetic)} kg<br>可堆叠：${p.stackable?'是':'否'}<extra></extra>`;
 return {type:'mesh3d',x:v.map(a=>a[0]),y:v.map(a=>a[1]),z:v.map(a=>a[2]),
 i:[0,0,4,4,0,0,1,1,2,2,3,3],j:[1,2,5,6,1,5,2,6,3,7,0,4],k:[2,3,6,7,5,4,6,5,7,6,4,7],
 color:material(p),opacity:highlight?.95:.82,flatshading:true,lighting:{ambient:.72,diffuse:.7,specular:.15},showlegend:false,hovertemplate:hover};
}
function traces(track,i,ctx){
 const s=current(track,ctx.step,ctx.phase),c=D.container,out=[];
 out.push({type:'scatter3d',mode:'lines',x:[-600,600,600,-600,-600],y:[-500,-500,500,500,-500],z:[0,0,0,0,0],line:{color:'#a1b5c1',width:3},hoverinfo:'skip',showlegend:false});
 const bad=new Set(s.m.violation_ids.flatMap(v=>v.split(':').slice(2)));
 for(const p of s.placed){
  const active=s.active&&!s.before&&s.e?.committed&&p.item_id===s.e.item.item_id;
  out.push(mesh(p,active),wire(p,bad.has(p.item_id)?'#cc514c':'#506878',bad.has(p.item_id)?5:1.3));
  if(active)out.push(wire(p,'#00aaa6',7));
 }
 if(ctx.numbers&&s.placed.length)out.push({type:'scatter3d',mode:'text',x:s.placed.map(p=>p.pose.x_mm),y:s.placed.map(p=>p.pose.y_mm),z:s.placed.map(p=>p.pose.z_base_mm+p.oriented_size_mm[2]+14),text:s.placed.map(p=>p.item_id.replace('item_','')),textfont:{size:11,color:'#16374a'},hoverinfo:'skip',showlegend:false});
 const by=Object.fromEntries(s.placed.map(p=>[p.item_id,p]));
 for(const id of s.m.violation_ids){
  if(!id.includes(':contact:'))continue;
  const [a,b]=id.split(':').slice(2).map(x=>by[x]);
  if(a&&b)out.push({type:'scatter3d',mode:'lines+markers',x:[a.pose.x_mm,b.pose.x_mm],y:[a.pose.y_mm,b.pose.y_mm],z:[a.pose.z_base_mm+a.oriented_size_mm[2]/2,b.pose.z_base_mm+b.oriented_size_mm[2]/2],line:{color:'#cc514c',width:7},marker:{color:'#cc514c',size:3},text:[id,id],hovertemplate:'禁止接触关系<br>%{text}<extra></extra>',showlegend:false});
 }
 if(s.active&&s.before&&s.e.selected)out.push(wire(s.e.selected,'#00aaa6',7));
 if(s.active&&s.before&&inspection[i]){
  const candidate=s.e.candidates.find(c=>c.display_label===inspection[i]);
  if(candidate)out.push(wire(candidate,'#956fb2',6));
 }
 if(s.active&&ctx.candidates&&s.e.candidates.length){
  const cs=s.e.candidates;
  out.push({type:'scatter3d',mode:'markers',x:cs.map(c=>c.pose.x_mm),y:cs.map(c=>c.pose.y_mm),z:cs.map(c=>c.pose.z_base_mm+c.oriented_size_mm[2]/2),
   marker:{size:cs.map(c=>c.display_label===s.e.proposed?7:4),color:cs.map(c=>c.feasible?'#007e82':'#cc514c'),opacity:.8},customdata:cs.map(c=>c.display_label),
   text:cs.map(c=>`${c.display_label} · ${c.feasible?'业务可行':'业务违规'}<br>底面 (${c.pose.x_mm}, ${c.pose.y_mm}, ${c.pose.z_base_mm}) mm<br>几何分 ${num(c.geometry_score,4)}${c.layout?'<br>布局分 '+num(c.layout.score,5):''}`),hovertemplate:'%{text}<extra>本次请求候选；点击检查</extra>',showlegend:false});
 }
 return out;
}
function sceneLayout(i){
 return {margin:{l:0,r:0,t:2,b:0},paper_bgcolor:'#fff',showlegend:false,uirevision:'keep-camera',
  scene:{camera:cameras[i],aspectmode:'manual',aspectratio:{x:1.2,y:1,z:.85},
  xaxis:{title:{text:'X / mm',font:{size:10}},range:[-600,600],tickvals:[-600,0,600],tickfont:{size:9},gridcolor:'#e8eef1',showbackground:false},
  yaxis:{title:{text:'Y / mm',font:{size:10}},range:[-500,500],tickvals:[-500,0,500],tickfont:{size:9},gridcolor:'#e8eef1',showbackground:false},
  zaxis:{title:{text:'Z / mm',font:{size:10}},range:[0,850],tickvals:[0,400,850],tickfont:{size:9},gridcolor:'#e8eef1',showbackground:false}}};
}
function describeBoard(track,i,ctx){
 const s=current(track,ctx.step,ctx.phase),e=s.e,m=s.m;
 const stopped=e&&!e.committed,done=e?.status==='all_items_placed';
 $('status'+i).className='status-pill '+(stopped?'stop':done?'done':'');
 $('status'+i).textContent=e?(s.frozen?`已停于第${e.arrival}箱`:shortStatus[e.status]||e.status):'初始状态';
 $('metrics'+i).innerHTML=`<div><div class="value">${s.placed.length}<small> / 17 箱</small></div><span class="label">${s.before?'放置前已放':'当前已放'}</span></div><div><div class="value ${m.violations?'danger':''}">${m.violations}<small> 实例</small></div><span class="label">当前业务违规</span></div><div><div class="value">${num(m.geometry.max_height_mm,0)}<small> mm</small></div><span class="label">当前垛高</span></div>`;
 if(!e){$('info'+i).innerHTML='<p>空托盘，尚未处理第1箱。</p><p class="event-note">三种策略使用同一订单和到货顺序。</p>';$('pick'+i).innerHTML='<option>尚无候选</option>';$('pick'+i).disabled=true;$('candidate'+i).textContent='';$('detail'+i).innerHTML='尚无本步请求。';return;}
 const frozen=s.frozen?`<p class="event-note warn">第${e.arrival}箱已终止。现在显示冻结布局；没有处理第${ctx.step}箱，也没有新的候选。</p>`:'';
 const cand=e.selected,raw=e.raw_evaluation;
 $('info'+i).innerHTML=`${frozen}<p><b>${s.frozen?'最后处理':'当前处理'}：箱${String(e.arrival).padStart(2,'0')}</b> · ${num(e.item.mass_kg)} kg · ${e.item.fragile?'易碎':'非易碎'}</p>
  <p>${cand?`选择 <b>${e.committed}</b> · 底面 z=${num(cand.pose.z_base_mm,0)} mm · yaw=${cand.pose.yaw_deg}°`:`<b class="danger">${statusText[e.status]||esc(e.status)}</b>`}</p>
  <p>全枚举物理可行 ${e.audit.physical_valid_count} → Top-K ${e.candidates.length} → 其中业务可行 <b>${e.feasible_count}</b></p>
  ${s.before?'<p class="event-note">此时显示放置前状态；绿色线框为本步实际选定位置。</p>':raw?`<p class="event-note ${raw.new_business_violation_count||raw.worsened_existing_violation_count?'warn':''}">本次提交：新增违规 ${raw.new_business_violation_count}，加重已有违规 ${raw.worsened_existing_violation_count}。</p>`:'<p class="event-note">没有提交；当前布局与上一箱之后相同。</p>'}`;
 const select=$('pick'+i);
 select.innerHTML='<option value="">检查本步候选位置…</option>'+e.candidates.map(c=>`<option value="${c.display_label}">${c.display_label}${c.display_label===e.proposed?' · 实际选择':''} · ${c.feasible?'业务可行':'业务违规'} · z=${c.pose.z_base_mm}</option>`).join('');
 select.disabled=s.frozen||!e.candidates.length;select.value=inspection[i]||'';
 const inspected=e.candidates.find(c=>c.display_label===inspection[i]);
 $('candidate'+i).textContent=inspected?`紫框 ${inspected.display_label}：几何 ${num(inspected.geometry_score,4)}${inspected.layout?' · 布局 '+num(inspected.layout.score,5):''}；候选仅属于当前方法当前请求。`:'';
 const g=m.geometry,l=m.layout,a=m.attributes,loss=e.trace.soft_loss_from_anchor;
 const harm=raw?`新增${raw.new_business_violation_count} / 加重${raw.worsened_existing_violation_count}`:'未提交';
 const rejectionNames={out_of_bounds:'越界',overlap:'碰撞',insufficient_support:'支撑不足',non_stackable_support:'不可堆叠',overload:'物理超载',over_payload:'托盘超载',com_outside_support:'重心投影不合格'};
 const rejection=Object.entries(e.audit.rejection_histogram).map(([k,v])=>`${rejectionNames[k]||k} ${v}`).join(' · ');
 $('detail'+i).innerHTML=`<div class="facts"><div>最大地面矩形<br><b>${num(l.largest_floor_rectangle_mm2/1e6,4)} m²</b></div><div>最佳同高支撑矩形<br><b>${num(l.best_support_rectangle_mm2/1e6,4)} m²</b></div><div>重箱底面均高<br><b>${num(a.heavy_mass_weighted_z_mm)} mm</b></div><div>重箱平均中心距<br><b>${num(a.heavy_center_distance_mm)} mm</b></div></div>
 <p>本步行为：${harm}。物理拒绝原因（首次拒绝码）：${rejection||'无'}。</p>
 <p>${e.trace.soft_policy_relaxed?`相对同状态原执行器的软目标损失（居中 / 低位）：${loss?loss.map(v=>v==null?'N/A':num(v,5)).join(' / '):'N/A'}；允许预算0.25 / 0.05。允许集合${e.trace.eligible_labels?.length??0}个。`:'本策略按原政策严格排序，未使用软预算。'}${ctx.step===5?' 本步尚无已放重箱，重箱软目标为N/A。':''}</p>
 <p class="muted">布局分只在预算＋布局候选允许集合内计算；各分支状态分叉后，不能直接比较Cxx标签。</p>
 <div class="table-wrap"><table><thead><tr><th>候选</th><th>z/mm</th><th>业务</th><th>几何</th><th>布局分</th></tr></thead><tbody>${e.candidates.map(c=>`<tr class="${c.display_label===e.proposed?'selected-row':''}"><td>${c.display_label}${c.display_label===e.proposed?' ✓':''}</td><td>${c.pose.z_base_mm}</td><td>${c.feasible?'可行':'违规'}</td><td>${num(c.geometry_score,4)}</td><td>${c.layout?num(c.layout.score,5):'未计算'}</td></tr>`).join('')}</tbody></table></div>
 <details><summary>请求绑定与实际选址轨迹</summary><pre>${esc(JSON.stringify({request_id:e.request_id,before_state_hash:e.before_state_hash,after_state_hash:e.after_state_hash,proposed:e.proposed,committed:e.committed,violations:m.violation_ids,eligible_labels:e.trace.eligible_labels,ranking_version:D.ranking_version},null,2))}</pre></details>`;
}
function story(ctx){
 const n=ctx.step,observe=ctx.mode==='observe_business';let title,fact,meaning,chapter;
 if(n===0){chapter='00 / 起点';title='三种策略，从同一空托盘出发';fact='同一份17箱订单、同一到货顺序、同一物理候选器。当前默认安全模式，任何新增业务违规都不应被提交。';meaning='建议先点击“05 · 首次布局分叉”，再沿关键节点走到17箱。也可逐箱播放；绿色线框标出本步放置。';}
 else if(n<5){chapter='01—04 / 共同起点';title='前4箱动作与物理状态一致';fact=`当前处理第${n}箱。三条轨迹在这一阶段仍然相同，为第5箱的同状态选择对照提供基础。`;meaning='候选编号只在本次请求内有效。悬停箱体查看尺寸与承载；切换放置前，可检查当前候选位置。';}
 else if(n===5){chapter='05 / 最新V2首次分叉';title='布局策略先改变第5箱的位置';fact='原策略与预算＋几何选(245, −10, 0) mm、yaw 0°；预算＋布局选(−300, −185, 0) mm、yaw 90°。同一前状态下，动作开始不同。';meaning='当前尚无已放重箱，重箱软目标为N/A；这里的分叉来自布局排序，不能解释成牺牲了重箱目标。后续支撑结构将随之改变。';}
 else if(n===6){chapter='06 / 低位与居中取舍';title='原策略提前堆高，预算控制仍放地面';fact='原策略将第6箱放到160 mm支撑层；预算＋几何和预算＋布局都放地面，但位置不同。原策略与几何预算控制在此首次分叉。';meaning='三种动作当时均没有业务违规。原策略忠实追求居中，并不保证后续整单可放；这是局部目标与长期布局的取舍。';}
 else if(n<=8){chapter='07—08 / 差异累积';title=n===8?'第8箱：原策略在410 mm高处继续堆叠':'第7箱：早期动作开始改变支撑结构';fact=n===8?'原策略第8箱底面410 mm；几何预算控制160 mm；布局方案250 mm。请比较三条轨迹的垛高与顶面形状。':'原策略第7箱底面160 mm，另两方案仍放在地面。三条状态已分叉，各自候选集也随之不同。';meaning='地面净空多不等于未来可放。需要同时考虑同高支撑、箱底长宽、承载与剩余高度；本页不会把描述性指标当作可行性证书。';}
 else if(n<12){chapter='09—11 / 接近瓶颈';title='局部仍能放，后续空间已不同';fact=`第${n}箱的提交仍可保持业务合规。各分支不断使用自己的真实新状态重新生成候选，而非复用同一份候选表。`;meaning='查看“布局指标与本步依据”，比较同高支撑矩形与垛高。第12箱将显示原策略的真实停止记录，而不是人为演示的失败。';}
 else if(n===12){chapter='12 / 原策略停止';title='1192个位姿，最终没有物理候选';fact='原策略第12箱：越界658、碰撞464、支撑不足70，返回候选0；没有提交，停在11/17箱。另两条轨迹均能提交第12箱。';meaning='70个位姿通过边界与碰撞检查后全部因支撑不足被拒。扩大Top-K无法挽救这一步；但这也不证明整个连续空间或订单全局无解。';}
 else if(n<16){chapter='13—15 / 保留失败分母';title='原策略冻结，改进方案继续真实运行';fact=`当前到货第${n}箱。原策略已在第12箱终止，左图保持11箱的最终布局；没有第${n}箱的新动作。另两方案继续提交。`;meaning='“11箱、零违规”不能算无违规整单成功。右侧布局方案的进展必须同时比较完成与最终业务合规。';}
 else if(n===16){chapter='16 / 合规的代价';title=observe?'几何方案继续放，却引入禁止接触违规':'几何方案有物理候选，却没有业务可行候选';fact=observe?'预算＋几何提交第16箱，引入箱09与箱16禁止接触的业务违规；布局方案提交第16箱仍无业务违规。':'预算＋几何返回16个物理候选，其中业务可行0，因此拒放并停在15/17；布局方案仍能合规提交。';meaning=observe?'观察模式保留物理检查，但允许记录业务损害。红框和红连线指出实际参与违规的箱体；红线表示关系，不是接触面积。':'切换“业务观察模式”查看：同一条几何轨迹会继续放，但代价是业务违规。安全拒放与观察继续是协议差异，不是API故障。';}
 else {chapter='17 / 整单结果';title=observe?'同样17箱，业务结果仍然不同':'从11/17箱，推进到17/17箱且无违规';fact=observe?'原策略11/17、0违规；预算＋几何17/17、最终2个违规；预算＋布局17/17、最终0违规。':'原策略11/17、预算＋几何15/17、预算＋布局17/17；安全模式最终均0违规，但只有布局方案完整完成。';meaning='这个案例展示了布局改进；不是Flash增量证据。三策略的Flash与Parser动作、物理状态一致，且整体开发来源只有10个，仍需独立验证。';}
 $('chapter').textContent=chapter;$('storyTitle').textContent=title;$('storyFact').textContent=fact;$('storyMeaning').textContent=meaning;
}
function finalResults(ctx){
 $('results').innerHTML=D.modes[ctx.mode].map((t,i)=>{const s=t.summary;return `<tr><td><b style="color:${COLORS[i]}">${names[i]}</b></td><td>${s.placed_items}/17 ${s.clean_completed?'<span class="badge success">无违规完成</span>':s.completed?'<span class="badge warn">有违规完成</span>':'<span class="badge">未完成</span>'}</td><td class="${s.final_business_violation_count?'danger':''}">${s.final_business_violation_count}</td><td>${s.violating_steps}/${s.placed_items}</td><td>${s.completed?'全部放完':statusText[s.termination_reason]||esc(s.termination_reason)}</td><td>${s.physical_violations}</td></tr>`;}).join('');
 $('resultExplanation').textContent=ctx.mode==='safe'?'安全模式：原策略第12箱物理终止；预算＋几何第16箱因Top-K业务无解拒放；预算＋布局完整放完。0违规只说明提交合规，不能替代完整完成。':'业务观察模式：预算＋几何第16箱新增1个、第17箱再新增1个禁止接触违规；预算＋布局完整完成且无违规。原策略提前停止仍必须计入失败。';
}
function curves(ctx){
 const cfg={responsive:true,displayModeBar:false};
 const common={margin:{l:49,r:16,t:64,b:40},paper_bgcolor:'#fff',plot_bgcolor:'#fff',font:{family:'system-ui, sans-serif',color:'#607b8c',size:11},
  xaxis:{title:{text:'到货箱序号',font:{size:10}},range:[0,17.3],tickvals:[0,5,6,8,12,16,17],gridcolor:'#eff3f5',zeroline:false},
  yaxis:{gridcolor:'#e8eff2',zeroline:false},showlegend:true,legend:{orientation:'h',x:0,y:1.12,yanchor:'bottom',font:{size:10}},
  shapes:[{type:'line',xref:'x',yref:'paper',x0:ctx.step,x1:ctx.step,y0:0,y1:1,line:{color:'#c09348',width:1.5,dash:'dot'}}],uirevision:'metric'};
 const heights=[],feasible=[];
 D.modes[ctx.mode].forEach((t,i)=>{
  heights.push({x:[0,...t.steps.map(e=>e.arrival)],y:[0,...t.steps.map(e=>e.after_metrics.geometry.max_height_mm)],type:'scatter',mode:'lines+markers',name:names[i],line:{color:COLORS[i],width:2},marker:{size:4},hovertemplate:`${names[i]}<br>第%{x}箱 · 垛高%{y} mm<extra></extra>`});
  if(t.steps.length<17)heights.push({x:[t.steps.length,17],y:[t.steps.at(-1).after_metrics.geometry.max_height_mm,t.steps.at(-1).after_metrics.geometry.max_height_mm],type:'scatter',mode:'lines',line:{color:COLORS[i],width:2,dash:'dot'},showlegend:false,hovertemplate:'终止后的冻结布局，无后续提交<extra></extra>'});
  feasible.push({x:t.steps.map(e=>e.arrival),y:t.steps.map(e=>e.feasible_count),type:'scatter',mode:'lines+markers',name:names[i],line:{color:COLORS[i],width:2},marker:{size:4},hovertemplate:`${names[i]}<br>第%{x}箱 · Top-K业务可行%{y}个<extra></extra>`});
 });
 return Promise.all([Plotly.react('heightChart',heights,{...common,title:{text:'提交后的垛高 / mm',font:{size:13,color:'#183448'},x:.02,y:.98,yanchor:'top'},yaxis:{...common.yaxis,range:[0,870]}},cfg),
  Plotly.react('feasibleChart',feasible,{...common,title:{text:'各自状态内的Top-K业务可行候选',font:{size:13,color:'#183448'},x:.02,y:.98,yanchor:'top'},yaxis:{...common.yaxis,range:[-.5,17],dtick:4}},cfg)]);
}
async function render(){
 if(painting){pending=true;return;}
 painting=true;window.app.ready=false;
 const ctx={mode,step,phase,numbers:$('numbers').checked,candidates:$('candidates').checked};
 try{
  $('arrival').textContent=ctx.step?`第 ${ctx.step} / 17 箱`:'初始状态';
  const item=ctx.step?D.modes[ctx.mode][2].steps[ctx.step-1]?.item:null;
  $('currentItem').textContent=item?`${['length','width','height'].map(k=>item.dimensions_mm[k]).join('×')} mm · ${num(item.mass_kg)} kg`:'三条轨迹从空托盘开始';
  $('slider').value=ctx.step;$('prev').disabled=ctx.step===0;$('next').disabled=ctx.step===17;
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===ctx.mode));
  document.querySelectorAll('[data-phase]').forEach(b=>b.classList.toggle('active',b.dataset.phase===ctx.phase));
  document.querySelectorAll('[data-step]').forEach(b=>b.classList.toggle('active',Number(b.dataset.step)===ctx.step));
  $('modeHint').textContent=ctx.mode==='safe'?'业务不合规则拒放；物理检查保留':'允许业务违规继续；物理检查保留';
  story(ctx);finalResults(ctx);
  D.modes[ctx.mode].forEach((t,i)=>describeBoard(t,i,ctx));
  await Promise.all([...D.modes[ctx.mode].map((t,i)=>Plotly.react('plot'+i,traces(t,i,ctx),sceneLayout(i),{responsive:true,displaylogo:false,displayModeBar:false,scrollZoom:true})),curves(ctx)]);
  if(!initialized){bindPlotEvents();initialized=true;}
  $('renderError').hidden=true;
  history.replaceState(null,'',`#step=${ctx.step}&mode=${ctx.mode}&phase=${ctx.phase}`);
 }catch(err){$('renderError').textContent='3D渲染未完成：'+err.message+'。请在支持WebGL的Chrome或Edge中打开。';$('renderError').hidden=false;console.error(err);}
 finally{painting=false;if(pending){pending=false;await render();}else{window.app.ready=true;document.body.dataset.ready='true';}}
}
function bindPlotEvents(){
 for(let i=0;i<3;i++){
  $('plot'+i).on('plotly_relayout',async e=>{
   const c=e['scene.camera'];if(!c||syncBusy)return;camera=c;cameras[i]=c;
   if(!$('sync').checked)return;
   cameras.fill(c);syncBusy=true;try{await Promise.all([0,1,2].filter(j=>j!==i).map(j=>Plotly.relayout('plot'+j,{'scene.camera':c})));}finally{syncBusy=false;}
  });
  $('plot'+i).on('plotly_click',ev=>{const label=ev.points?.[0]?.customdata;if(typeof label==='string'&&/^C\d+$/.test(label)){inspection[i]=label;phase='before';stop();render();}});
 }
 ['heightChart','feasibleChart'].forEach(id=>$(id).on('plotly_click',e=>{const x=e.points?.[0]?.x;if(Number.isFinite(x))go(x);}));
}
function stop(){playing=false;clearTimeout(timer);timer=null;$('play').textContent='▶ 播放';}
function go(n){stop();step=Math.max(0,Math.min(17,Math.round(n)));inspection.fill(null);return render();}
function setMode(value){stop();mode=value==='observe_business'?'observe_business':'safe';inspection.fill(null);return render();}
function schedule(){
 timer=setTimeout(async()=>{if(!playing)return;if(painting){schedule();return;}if(step>=17){stop();return;}step++;inspection.fill(null);await render();
  if($('pauseKeys').checked&&keySteps.includes(step)){stop();return;}if(playing)schedule();},Number($('speed').value));
}
async function togglePlay(){if(playing){stop();return;}if(step>=17){step=0;await render();}playing=true;$('play').textContent='Ⅱ 暂停';schedule();}
async function setCamera(value){camera=value;cameras.fill(value);syncBusy=true;try{await Promise.all([0,1,2].map(i=>Plotly.relayout('plot'+i,{'scene.camera':camera})));}finally{syncBusy=false;}}
for(let i=0;i<3;i++){
 const section=document.createElement('article');section.className='board';section.style.setProperty('--arm',COLORS[i]);
 section.innerHTML=`<div class="board-head"><h3>${names[i]}</h3><span class="status-pill" id="status${i}"></span></div><div class="variant">${['严格软目标排序','相同软预算 · 几何控制臂','相同软预算 · 支撑 / 承载 / 高度'][i]}</div><div class="scene" id="plot${i}"></div><div class="metric-row" id="metrics${i}"></div><div class="board-info" id="info${i}"></div><div class="candidate-controls"><select id="pick${i}" aria-label="检查${names[i]}的候选"></select><button id="export${i}">保存视图</button></div><div class="candidate-description" id="candidate${i}"></div><details class="details"><summary>布局指标与本步依据</summary><div id="detail${i}"></div></details>`;
 $('boards').append(section);
 $('pick'+i).onchange=e=>{stop();inspection[i]=e.target.value||null;if(inspection[i])phase='before';render();};
 $('export'+i).onclick=()=>Plotly.downloadImage('plot'+i,{format:'png',width:1200,height:1000,filename:`SCN0054_P1_${mode}_${D.variants[i].key}_step${step}_${phase}`});
}
$('policy').textContent='易碎承载≤3 kg · 电子品与重箱禁止接触 · 先居中，再低位';
$('policyDetails').onclick=()=>{$('policyBox').hidden=!$('policyBox').hidden;};
$('sourcePath').textContent=`semantic_pallet_planner/outputs/${D.experiment}/episodes/{safe,observe_business}/{original,relaxed_geometry,relaxed_wo_floor}/public_parser/O3_SCN_0054_P1/steps.jsonl`;
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
document.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>go(Number(b.dataset.step)));
document.querySelectorAll('[data-phase]').forEach(b=>b.onclick=()=>{stop();phase=b.dataset.phase;if(phase==='after')inspection.fill(null);render();});
$('slider').oninput=e=>go(Number(e.target.value));$('prev').onclick=()=>go(step-1);$('next').onclick=()=>go(step+1);$('play').onclick=togglePlay;
$('numbers').onchange=render;$('candidates').onchange=()=>{stop();if($('candidates').checked)phase='before';render();};
$('sync').onchange=()=>{if($('sync').checked)setCamera(camera);};
$('speed').onchange=()=>{if(playing){clearTimeout(timer);schedule();}};
$('iso').onclick=()=>setCamera({eye:{x:1.55,y:-1.75,z:1.25},up:{x:0,y:0,z:1},center:{x:0,y:0,z:0}});
$('top').onclick=()=>setCamera({eye:{x:0,y:0,z:2.6},up:{x:0,y:1,z:0},center:{x:0,y:0,z:0}});
$('front').onclick=()=>setCamera({eye:{x:0,y:-2.7,z:.12},up:{x:0,y:0,z:1},center:{x:0,y:0,z:0}});
$('fullscreen').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else document.documentElement.requestFullscreen?.();};
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA','BUTTON'].includes(e.target.tagName))return;if(e.key==='ArrowRight'){e.preventDefault();go(step+1);}if(e.key==='ArrowLeft'){e.preventDefault();go(step-1);}if(e.code==='Space'){e.preventDefault();togglePlay();}});
window.addEventListener('hashchange',()=>{const p=new URLSearchParams(location.hash.slice(1));mode=p.get('mode')==='observe_business'?'observe_business':'safe';phase=p.get('phase')==='before'?'before':'after';go(Number(p.get('step'))||0);});
render();
