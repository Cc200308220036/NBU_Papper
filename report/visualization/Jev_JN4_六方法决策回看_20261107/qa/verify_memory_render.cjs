/* Render all saved hit cases using the actual UI templates, without a browser,
   model, DOM emulation or planner. Complements the recorded live UI checks. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const context=vm.createContext({console,window:{JN4_JOBS:{}},document:{addEventListener(){}},setTimeout(){}});
const run=s=>vm.runInContext(s,context);
run(fs.readFileSync(path.join(root,'web/index-data.js'),'utf8'));
const app=fs.readFileSync(path.join(root,'web/app.js'),'utf8');
run(app.split('class World{')[0]);
run(fs.readFileSync(path.join(root,'web/memory-review.js'),'utf8'));
for(const name of ['topTie','tieNotice','experienceOriginHTML','fragmentHTML','memoryHTML']){
 const line=app.split('\n').find(l=>l.startsWith(`function ${name}(`));assert.ok(line,name);run(line);
}
for(const name of fs.readdirSync(path.join(root,'web/data')))run(fs.readFileSync(path.join(root,'web/data',name),'utf8'));
const audit=JSON.parse(fs.readFileSync(path.join(root,'memory_hit_audit.json'),'utf8'));
for(const r of audit.records){
 const html=run(`state.job=window.JN4_JOBS[${JSON.stringify(r.job_id)}];state.step=${r.step};memoryHTML(event())`);
 assert.ok(html.includes(r.decision_id)&&html.includes(r.entry_ref));
 assert.ok(html.includes('NOT_ESTABLISHED'));
 assert.ok(!html.includes('undefined'));
 if(r.delivery==='SINGLETON_NOT_SENT')assert.ok(html.includes('已准备片段（未发送）'));
 if(r.mode==='CONTROL_REFERENCE')assert.ok(html.includes('实际请求中的文字是placebo'));
}
assert.equal(run("memoryFilter.mode='T';memoryFilter.choice='DIFFERENT_ACTION_SAME_STATE_POOL';filteredHits().length"),6);
assert.equal(run("memoryFilter.mode='E';filteredHits().length"),6);
assert.equal(run("memoryFilter.mode='T';memoryFilter.choice='all';memoryFilter.entry='T-2';filteredHits().length"),54);
const overview=run('memoryOverviewHTML()');assert.ok(overview.includes('100/106')&&overview.includes('94/100'));
const receipt={date:'2026-11-09',status:'PASS',actual_ui_template_records_rendered:audit.records.length,
 checks:['all hit templates render with concrete IDs and causality limits','no undefined template fields',
 'singleton prepared-only label','placebo reference label','T/E same-state difference filters','T-2 count and stage denominators'],
 scope:'Node VM rendering of actual UI functions; not browser, layout or mobile validation'};
fs.writeFileSync(path.join(root,'qa/memory_hit_render_checks.json'),JSON.stringify(receipt,null,2)+'\n');
console.log(receipt);
