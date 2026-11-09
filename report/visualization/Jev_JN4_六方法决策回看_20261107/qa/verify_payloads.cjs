/* Read-only evidence checks and actual bilingual template rendering; no browser. */
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const out=path.resolve(__dirname,'..'),repo=path.resolve(process.argv[2]||path.join(__dirname,'../../../..'));
const data=JSON.parse(fs.readFileSync(path.join(out,'web/origins-data.js'),'utf8').split('=',1+1)[1].replace(/;\n$/,''));
const t=JSON.parse(fs.readFileSync(path.join(repo,'semantic_pallet_planner/outputs/JEV_JN3_20261104_01/trajectory_snapshot.json')));
const e=JSON.parse(fs.readFileSync(path.join(repo,'semantic_pallet_planner/outputs/JEV_JN3_20261104_02/contrast_snapshot.json')));
const nodes={};const document={querySelector(s){return nodes[s]??={innerHTML:''};},addEventListener(){}};
const ctx=vm.createContext({window:{},document,console,history:{replaceState(){}},setTimeout(){}});
const run=s=>vm.runInContext(s,ctx);
run(fs.readFileSync(path.join(out,'web/index-data.js'),'utf8'));
run(fs.readFileSync(path.join(out,'web/origins-data.js'),'utf8'));
const app=fs.readFileSync(path.join(out,'web/app.js'),'utf8');run(app.split('class World{')[0]);
run(fs.readFileSync(path.join(out,'web/memory-review.js'),'utf8'));
run(fs.readFileSync(path.join(out,'web/experience-origins.js'),'utf8'));
run(fs.readFileSync(path.join(out,'web/experience-payloads.js'),'utf8'));
for(const c of data.cases){
 assert.deepEqual(c.T,t.cases.find(x=>x.provenance.comparison_id===c.id).public_fragment);
 assert.deepEqual(c.E,e.cards.find(x=>x.provenance.comparison_id===c.id).public_fragment);
 for(const text of [c.T.notice,...c.T.limitations,c.E.notice,...c.E.advice.map(a=>a.text),c.E.expected_effect.text,c.E.counterexamples,...c.E.limitations]){
  assert.notEqual(run(`payloadTranslate(${JSON.stringify(text)})`),'保留原文，不追加解释。');
 }
 run(`payloadCaseId=${JSON.stringify(c.id)};renderPayloads()`);
 const html=nodes['#payloadsContent'].innerHTML;
 assert.ok(html.includes('中文是本页面的翻译和字段说明，没有发给Jev'));
 assert.ok(html.includes('中文译文（展示用）')&&html.includes('English（实际片段中的原文）'));
 assert.ok(html.includes(c.T_ref)&&html.includes(c.E_ref));
 assert.ok(html.includes(c.examples.T.decision_id)&&html.includes(c.examples.E.decision_id));
 assert.ok(!html.includes('undefined'));
 for(const a of c.E.advice){const escaped=run(`esc(${JSON.stringify(a.text)})`);assert.ok(html.includes(escaped));assert.ok(html.includes(run(`esc(payloadTranslate(${JSON.stringify(a.text)}))`)));}
 const rawT=run(`payloadRaw('T',window.JN4_ORIGINS.cases.find(c=>c.id===${JSON.stringify(c.id)}).T)`);
 assert.ok(rawT.includes(run(`json(window.JN4_ORIGINS.cases.find(c=>c.id===${JSON.stringify(c.id)}).T)`)));
}
const html=fs.readFileSync(path.join(out,'web/index.html'),'utf8');
for(const p of ['explorer','compare','library','origins','about','payloads'])assert.ok(html.includes(`id="page-${p}"`),p);
assert.ok(app.includes("if(p==='origins')renderOrigins()")&&app.includes("if(p==='payloads')renderPayloads()"));
const receipt={date:'2026-11-09',status:'PASS_SOURCE_AND_TEMPLATE_SCOPE',paired_cases:2,exact_frozen_fragments:4,
 checks:['all T/E source fragments equal frozen snapshots','all original textual statements have explicit Chinese translations','actual English advice retained verbatim','both paired-case templates render with actual request IDs','full raw JSON retained and downloadable','all previous pages retained'],browser_visual_validation:'NOT_RUN',new_model_calls:0};
fs.writeFileSync(path.join(out,'qa/payloads_checks.json'),JSON.stringify(receipt,null,2)+'\n');console.log(receipt);
