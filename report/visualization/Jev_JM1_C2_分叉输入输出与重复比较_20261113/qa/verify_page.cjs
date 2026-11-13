// Exercise real rendering functions with DOM/3D substitutes; not a browser test.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const out=path.resolve(__dirname,'..'),web=path.join(out,'web');const nodes=new Map(),listeners={};
const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',checked:true,classList:{toggle(){}},append(){},addEventListener(){},clientWidth:600,clientHeight:330});return nodes.get(id)};
const ctx={console,URLSearchParams,setTimeout,clearInterval,setInterval,location:{hash:''},history:{replaceState(){}},document:{querySelector:node,querySelectorAll:()=>[],addEventListener:(name,f)=>listeners[name]=f,createElement:()=>({}),body:{append(){}}}};ctx.window=ctx;vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(web,'index-data.js'),'utf8'),ctx);vm.runInContext('window.CASES={}',ctx);for(const f of fs.readdirSync(path.join(web,'data')))vm.runInContext(fs.readFileSync(path.join(web,'data',f),'utf8'),ctx);
let app=fs.readFileSync(path.join(web,'app.js'),'utf8');app=app.slice(0,app.indexOf("$('#overview').innerHTML="));app=app.replace('window.CASES={};','');app+='\nmount=()=>{};';vm.runInContext(app,ctx);
let pages=0,eventViews=0;
for(const p of ctx.INDEX.points){vm.runInContext(`S.point=${JSON.stringify(p.id)};S.slot='r0';S.pos={reference:-1,alternative:-1};`,ctx);for(let i=0;i<6;i++){vm.runInContext(`S.page=${i};render()`,ctx);assert(node('#content').innerHTML.length>100);assert(!node('#content').innerHTML.includes('undefined'));pages++}
 for(const slot of p.repeat?['r0','r1']:['r0']){vm.runInContext(`S.slot='${slot}';S.page=3;render()`,ctx);vm.runInContext("S.page=2",ctx);for(const role of ['reference','alternative']){const count=vm.runInContext(`run('${role}').events.length`,ctx);for(let i=-1;i<count;i++)for(const tab of ['input','output','monitor','evidence']){vm.runInContext(`S.pos['${role}']=${i};S.tab='${tab}';eventView('${role}')`,ctx);eventViews++}}}
}
vm.runInContext("S.point=INDEX.points[0].id;S.slot='r0';S.page=2;S.pos={reference:-1,alternative:-1};jump('next')",ctx);assert.equal(vm.runInContext('S.pos.reference',ctx),0);vm.runInContext("jump('next')",ctx);assert.equal(vm.runInContext('S.pos.reference',ctx),2);vm.runInContext("jump('final')",ctx);assert.equal(vm.runInContext("run('reference').events[S.pos.reference].event",ctx),'STOP');
vm.runInContext("S.point=INDEX.points[3].id;S.slot='r0'",ctx);assert(vm.runInContext('repeatPage()',ctx).includes('未登记重复'));
vm.runInContext("S.point=INDEX.points[0].id;S.slot='r0'",ctx);assert(vm.runInContext('repeatPage()',ctx).includes('−40 / +40'));
const result={status:'PASS',scope:'real render functions with DOM/3D substitutes; not browser screenshots or WebGL validation',point_pages:pages,event_tab_views:eventViews,jump_semantics:'PASS',P01_conflict:'PASS',P04_unregistered_repeat:'PASS'};fs.writeFileSync(path.join(__dirname,'render_checks.json'),JSON.stringify(result,null,2)+'\n');console.log(result);
