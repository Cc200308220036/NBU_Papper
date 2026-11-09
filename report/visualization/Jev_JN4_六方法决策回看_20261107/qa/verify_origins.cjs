/* Independent source-pointer checks plus real UI-function interaction tests.
   This uses a minimal DOM/World stub, not a browser or layout test. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const output=path.resolve(__dirname,'..'),repo=path.resolve(process.argv[2]||path.join(__dirname,'../../../..'));
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const exported=fs.readFileSync(path.join(output,'web/origins-data.js'),'utf8');
const data=JSON.parse(exported.slice(exported.indexOf('=')+1).replace(/;\n$/,''));
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const cache=new Map();
function pointer(source){const file=path.join(repo,source.path);assert.equal(hash(file),source.sha256);if(!cache.has(file))cache.set(file,read(file));return source.pointer.split('/').slice(1).reduce((a,k)=>a[k.replace(/~1/g,'/').replace(/~0/g,'~')],cache.get(file));}
let frames=0,requests=0;
for(const [p,h]of Object.entries(data.source_files))assert.equal(hash(path.join(repo,p)),h,p);
for(const c of data.cases){
 assert.deepEqual(pointer(c.T_source),c.T);assert.deepEqual(pointer(c.E_source),c.E);
 for(const trace of [c.parent,...Object.values(c.branches)]){
  const original=pointer(trace.source);assert.equal(trace.frames.length,original.events.length+1);
  for(const f of trace.frames){const s=pointer(f.source);assert.equal(f.state.placed_count,s.placed_count);assert.equal(f.state.arrival_count,s.arrival_count);assert.equal(f.state.placed_items.length,s.placed_items.length);for(let i=0;i<s.placed_items.length;i++){assert.equal(f.state.placed_items[i].item_id,s.placed_items[i].item_id);assert.deepEqual(f.state.placed_items[i].pose,s.placed_items[i].pose);assert.deepEqual(f.state.placed_items[i].oriented_size_mm,s.placed_items[i].oriented_size_mm);}frames++;}
  assert.equal(trace.metrics.loading.placed_items,original.state.placed_count);
 }
 for(const mode of ['T','E']){const x=c.examples[mode];assert.deepEqual(pointer(x.request_source),x.request);assert.deepEqual(pointer(x.memory_source),mode==='T'?c.T:c.E);assert.deepEqual(x.request.state.memories,[mode==='T'?c.T:c.E]);assert.ok(!('frames'in x.request.state.memories[0]));requests++;}
}
const nodes=new Map(),listeners={};
function node(selector){if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',textContent:'',value:0,max:13,classList:{toggle(){}},dataset:{},style:{}});return nodes.get(selector);}
const document={querySelector:node,querySelectorAll(){return [];},addEventListener(type,fn){(listeners[type]??=[]).push(fn);}};
class SavedWorld{constructor(el){this.el=el;this.meshes=[];}draw(e,j){this.lastState=e.after;}dispose(){this.disposed=true;}resize(){}tick(){}}
const sandbox=vm.createContext({window:{},document,console,World:SavedWorld,history:{replaceState(){}},setTimeout(){},clearInterval(){},setInterval(){return 1;}});
const run=s=>vm.runInContext(s,sandbox);
run(fs.readFileSync(path.join(output,'web/index-data.js'),'utf8'));run(exported);
const app=fs.readFileSync(path.join(output,'web/app.js'),'utf8');run(app.split('class World{')[0]);
run(fs.readFileSync(path.join(output,'web/memory-review.js'),'utf8'));run(fs.readFileSync(path.join(output,'web/experience-origins.js'),'utf8'));
const checks=[];
function check(name,f){f();checks.push(name);}
check('both cases render complete source lanes and plain explanation',()=>{
 for(const c of data.cases){run(`originState.caseId=${JSON.stringify(c.id)};renderOrigins()`);const html=node('#originsContent').innerHTML;assert.ok(html.includes('原动作＋几何后续')&&html.includes('替代动作＋相同几何后续'));assert.ok(html.includes('真正进入新订单请求'));assert.ok(!html.includes('undefined'));assert.ok(html.includes(`${c.branches.reference.event_count} 个事件`));assert.ok(html.includes(`${c.branches.alternative.event_count} 个事件`));}
});
check('synchronized first action and final endpoints',()=>{for(const c of data.cases){run(`originState.caseId=${JSON.stringify(c.id)};renderOrigins();originSetProgress(1)`);assert.deepEqual([...run('originWorlds.slice(0,2).map(w=>w.lastState.placed_count)')],[1,1]);run(`originSetProgress(${c.branches.alternative.final_state.placed_count})`);assert.deepEqual([...run('originWorlds.slice(0,2).map(w=>w.lastState.placed_count)')],[c.branches.reference.final_state.placed_count,c.branches.alternative.final_state.placed_count]);}});
check('all individual saved event frames can be displayed',()=>{for(const c of data.cases){run(`originState.caseId=${JSON.stringify(c.id)};renderOrigins()`);for(const role of ['reference','alternative','parent']){const trace=role==='parent'?c.parent:c.branches[role];for(let i=0;i<trace.frames.length;i++){run(`originState.positions[${JSON.stringify(role)}]=${i};updateOriginFrames()`);assert.ok(node('#originFrame-'+role).innerHTML.includes(`本画面已放 ${trace.frames[i].state.placed_count} 箱`));}}}});
check('actual T/E inputs remain separate, highlighted, downloadable',()=>{for(const c of data.cases){run(`originState.caseId=${JSON.stringify(c.id)};renderOrigins()`);for(const mode of ['T','E']){run(`originState.mode=${JSON.stringify(mode)};renderOriginRequest()`);const html=node('#originRequestExample').innerHTML;assert.ok(html.includes(c.examples[mode].decision_id));assert.ok(html.includes('state.memories[0] = '+c.examples[mode].entry_ref));assert.ok(html.includes('没有放入完整分支轨迹'));assert.ok(html.includes('下载这次实际请求JSON'));assert.ok(!html.includes('undefined'));}}});
check('navigation and event listeners are wired',()=>{assert.ok(app.includes("if(p==='origins')renderOrigins()"));assert.ok(app.includes('originWorlds.forEach(w=>w.tick())'));assert.ok(listeners.input.length&&listeners.change.length&&listeners.click.length);const html=fs.readFileSync(path.join(output,'web/index.html'),'utf8');assert.ok(html.includes('data-page="origins"'));for(const f of ['origins-data.js','experience-origins.js'])assert.ok(html.includes(f));});
const receipt={date:'2026-11-09',status:'PASS_SOURCE_AND_UI_LOGIC',source_hashes:Object.keys(data.source_files).length,saved_frames_verified:frames,actual_requests_verified:requests,ui_logic_checks:checks,browser_visual_validation:'NOT_RUN',scope:'Original source hashes and pointers plus actual UI functions with DOM/World stubs; no simulation/model/solver/retrieval dispatch'};
fs.writeFileSync(path.join(output,'qa/origins_checks.json'),JSON.stringify(receipt,null,2)+'\n');console.log(receipt);
