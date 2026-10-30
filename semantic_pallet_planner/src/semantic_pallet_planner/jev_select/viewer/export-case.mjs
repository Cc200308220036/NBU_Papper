/** Standalone Jev record viewer exporter. No model, planner, oracle or replay calls. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const repo=path.resolve(here,'../../../../..');
const argv=process.argv.slice(2), arg=(key,fallback)=>{const i=argv.indexOf(key);return i<0?fallback:argv[i+1];};
if(argv.includes('--help')){console.log('node export-case.mjs [--experiment DIR] [--job J0025] [--output NEW_DIR] [--refresh]');process.exit(0);}
const experiment=path.resolve(arg('--experiment',path.join(repo,'semantic_pallet_planner/outputs/EXP_JEV_J3_TEST_20261029_01')));
const output=path.resolve(arg('--output',path.join(repo,'semantic_pallet_planner/outputs/JEV_J3_CASE_VIEWER_20261029_01')));
const job=arg('--job','J0025');
const ensure=(condition,message)=>{if(!condition)throw Error(message);};
ensure(experiment.startsWith(repo+path.sep)&&output.startsWith(repo+path.sep),'All operations must stay inside the repository.');
ensure(output!==experiment&&!output.startsWith(experiment+path.sep),'Never write into a sealed experiment.');
const sha=text=>crypto.createHash('sha256').update(text).digest('hex');
const manifest=JSON.parse(fs.readFileSync(path.join(experiment,'delivery_manifest.json'),'utf8'));
const sourceHashes={};
function source(relative){const raw=fs.readFileSync(path.join(experiment,relative));ensure(manifest[relative]===sha(raw),'Sealed source hash mismatch: '+relative);sourceHashes[relative]=sha(raw);return raw.toString('utf8');}
const ep=JSON.parse(source(`episodes/${job}.json`));
ensure(ep.summary.selector_backend==='jev_choice','Only real Jev cases are supported.');
ensure(ep.summary.completed,'Choose a complete trajectory for this presentation.');
const ledger=JSON.parse(source('audit/attempts.json'));
const attempts=new Map(ledger.attempts.map(a=>[a.attempt_id,a]));
const events=ep.events.filter(e=>e.event==='PLACE');
let previousViolations=new Set(),previousArrived=new Set();
const steps=events.map((e,i)=>{
 const ctx=e.context,s=e.selection;
 ensure(s.source==='jev'&&s.attempt_ids.length===1,'Presentation case must contain a real Choice at every placement.');
 ensure(JSON.stringify(e.bundle.physical_candidates)===JSON.stringify(e.bundle.selectable_candidates),'Business-filtered candidate pool is not supported.');
 const requestRaw=source(`requests/${job}/${e.decision_id}.json`),mappingRaw=source(`mappings/${job}/${e.decision_id}.json`);
 ensure(JSON.stringify(JSON.parse(requestRaw))===JSON.stringify(ctx.request_body),'Saved request differs from event.');
 ensure(JSON.stringify(JSON.parse(mappingRaw))===JSON.stringify(ctx),'Saved mapping differs from event.');
 const attempt=attempts.get(s.attempt_ids[0]);ensure(attempt&&attempt.origin==='jev'&&attempt.transport.http_status===200,'Response is not a real successful HTTP record.');
 const responseRaw=Buffer.from(attempt.transport.raw_body_b64,'base64').toString('utf8');ensure(sha(Buffer.from(responseRaw))===attempt.transport.raw_sha256,'Response digest mismatch.');
 const response=JSON.parse(responseRaw);ensure(response.answers.next_action.choice===s.selected_display_id,'Choice differs from saved response.');
 const byCandidate=new Map(e.bundle.physical_candidates.map(c=>[c.candidate_id,c]));
 const cands=Object.entries(ctx.display_mapping).map(([label,m])=>{const c=byCandidate.get(m.candidate_id),q=ctx.criteria[label];ensure(c&&c.pick_item_id===m.pick_item_id,'Candidate mapping mismatch.');return {label,candidate_id:c.candidate_id,item_id:c.pick_item_id,alias:q.pick_object,pose:c.pose,size:c.oriented_size_mm,geometry:q.features.geometry_score,features:q.features,load_changes:q.load_changes};});
 ensure(cands.length===Object.keys(response.answers.next_action.probabilities).length,'Probability keys differ from pool.');
 const visible=[...e.observation.placed_objects,...e.observation.available_objects],aliasById=Object.fromEntries(visible.map((o,n)=>[o.object_id,'B'+String(n+1).padStart(3,'0')])),idByAlias=Object.fromEntries(Object.entries(aliasById).map(([id,a])=>[a,id]));
 for(const c of cands)ensure(aliasById[c.item_id]===c.alias,'Per-step anonymous object mapping mismatch.');
 const violations=e.business_after.instances,newViolations=violations.filter(v=>!previousViolations.has(v.identity));previousViolations=new Set(violations.map(v=>v.identity));
 const arrivals=e.before.arrived_ids.filter(id=>!previousArrived.has(id));previousArrived=new Set(e.after.arrived_ids);
 return {step:i+1,decision_id:e.decision_id,selected:s.selected_display_id,candidates:cands,before:e.before,after:e.after,alias_by_id:aliasById,id_by_alias:idByAlias,request:JSON.parse(requestRaw),request_raw:requestRaw,response,response_raw:responseRaw,latency_s:attempt.transport.latency_s,violations,new_violations:newViolations,business_raw:e.business_after.raw,new_arrivals:arrivals};
});
const allRows=JSON.parse(source('metrics/rows.json')).filter(r=>r.selector_backend==='jev_choice');
const categories=[...new Set(Object.values(ep.final_state.attributes).map(a=>a.cargo_category))];
const data={version:'jev_case_viewer_v1',job_id:job,task_id:ep.summary.task_id,model:steps[0].response.model,experiment:path.basename(experiment),summary:ep.summary,container:ep.final_state.container,categories,overview:{tasks:allRows.length,completed:allRows.filter(r=>r.completed).length},steps,interpretation:{model_rationale_returned:false,explanation_mode:'observed facts and clearly labelled post-hoc analysis only',counterfactual_rollouts:false,new_model_calls:0,new_environment_steps:0}};
const sources={style:fs.readFileSync(path.join(here,'viewer.css'),'utf8'),three:fs.readFileSync(path.join(here,'vendor/three.min.js'),'utf8'),orbit:fs.readFileSync(path.join(here,'vendor/OrbitControls.js'),'utf8'),app:fs.readFileSync(path.join(here,'viewer.js'),'utf8')};
let html=fs.readFileSync(path.join(here,'template.html'),'utf8');
const tokens={'/*__STYLE__*/':sources.style,'/*__DATA__*/':JSON.stringify(data).replaceAll('<','\\u003c'),'/*__THREE__*/':sources.three,'/*__ORBIT__*/':sources.orbit,'/*__APP__*/':sources.app};
for(const [token,value] of Object.entries(tokens)){ensure(html.includes(token),'Missing template slot '+token);html=html.replace(token,()=>value);}
if(fs.existsSync(output)){
 ensure(argv.includes('--refresh'),'Output exists. Use a new directory or --refresh for this viewer only.');
 const old=JSON.parse(fs.readFileSync(path.join(output,'viewer-manifest.json'),'utf8'));ensure(old.version==='jev_case_viewer_v1'&&old.job_id===job&&old.experiment===path.basename(experiment),'Refusing to replace an unrelated artifact.');
}else fs.mkdirSync(output,{recursive:true});
fs.writeFileSync(path.join(output,'index.html'),html);
const receipt={version:'jev_case_viewer_v1',job_id:job,task_id:data.task_id,experiment:data.experiment,step_count:steps.length,candidate_counts:steps.map(s=>s.candidates.length),source_hashes_verified:sourceHashes,html_sha256:sha(html),source_assets_sha256:Object.fromEntries(Object.entries(sources).map(([k,s])=>[k,sha(s)])),new_model_calls:0,new_environment_steps:0,raw_request_and_response_embedded:true,model_rationale_returned:false,post_hoc_explanation_labelled:true,webgl_engine:'Three.js 0.128.0, MIT, embedded; no runtime CDN',formal_source_manifest_untouched:true};
fs.writeFileSync(path.join(output,'viewer-manifest.json'),JSON.stringify(receipt,null,2)+'\n');
fs.writeFileSync(path.join(output,'README.md'),`# Jev真实案例3D观察页\n\n直接用支持WebGL的浏览器打开index.html；所有资源与数据已内嵌，无需API密钥、网络或后端。也可在此目录运行python -m http.server 8766 --bind 127.0.0.1，通过http://127.0.0.1:8766查看。\n\n案例${data.task_id}，${job}，${steps.length}次真实Choice。逐步播放、每步全部候选、三维预览、真实输入输出和执行后业务评价均来自封存记录。\n\nJev没有返回选择理由；页面的解释是标明来源的事实比较与事后分析，不能当作模型自述。备选未做反事实执行。落箱动画为图示，只有起止坐标来自记录，不代表机械臂运动路径。\n\n模型本轮只见当前状态。页面订单总数、未来步骤和最终结果是离线审计信息，不会反向送给模型。本页没有新增API调用、候选生成、仿真或轨迹重执行。\n`);
console.log(JSON.stringify({status:'PASS',output:path.join(output,'index.html'),bytes:Buffer.byteLength(html),steps:steps.length,candidates:receipt.candidate_counts,new_model_calls:0,source_files_verified:Object.keys(sourceHashes).length}));
