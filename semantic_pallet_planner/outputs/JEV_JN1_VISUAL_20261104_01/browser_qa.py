"""QA through existing local Chrome CDP; no dependency installation or order execution."""
import subprocess,tempfile,time,json,urllib.request,base64,shutil
from pathlib import Path
import websocket
ROOT=Path('semantic_pallet_planner/outputs/JEV_JN1_VISUAL_20261104_01').resolve();QA=ROOT/'qa';QA.mkdir(exist_ok=True)
profile=tempfile.mkdtemp(prefix='jn1-viewer-chrome-')
log=(QA/'chrome.log').open('w');proc=subprocess.Popen(['/usr/bin/google-chrome','--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-background-networking','--disable-default-apps','--disable-extensions','--no-first-run','--no-default-browser-check','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--remote-allow-origins=*','--user-data-dir='+profile,'--window-size=1600,1200',(ROOT/'JN1_interactive.html').as_uri()],stdout=log,stderr=log)
ws=None;seq=0;errors=[];assertions=[]
def command(method,params=None):
 global seq
 seq+=1;idx=seq;ws.send(json.dumps({'id':idx,'method':method,'params':params or {}}))
 while True:
  msg=json.loads(ws.recv())
  if msg.get('method')=='Runtime.exceptionThrown':errors.append(msg['params'])
  if msg.get('id')==idx:
   assert 'error' not in msg,msg
   return msg.get('result',{})
def evaluate(expression):
 r=command('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
 assert 'exceptionDetails' not in r,r
 return r.get('result',{}).get('value')
def check(label,expr):
 value=evaluate(expr);assert value, (label,value);assertions.append({'check':label,'status':'PASS'})
try:
 for _ in range(100):
  port=Path(profile)/'DevToolsActivePort'
  if port.exists():break
  time.sleep(.1)
 assert port.exists(),'Chrome debug endpoint unavailable'
 url='http://127.0.0.1:'+port.read_text().splitlines()[0]
 for _ in range(100):
  pages=json.loads(urllib.request.urlopen(url+'/json').read());page=next((p for p in pages if p['type']=='page'),None)
  if page and page.get('webSocketDebuggerUrl'):break
  time.sleep(.1)
 ws=websocket.create_connection(page['webSocketDebuggerUrl'],timeout=60,suppress_origin=True)
 command('Runtime.enable');command('Page.enable');command('Network.enable');command('Network.setBlockedURLs',{'urls':['http://*','https://*','ws://*','wss://*']})
 command('Emulation.setDeviceMetricsOverride',{'width':1600,'height':1150,'deviceScaleFactor':1,'mobile':False})
 for _ in range(100):
  if evaluate('!!window.JN1_VIEWER'):break
  time.sleep(.1)
 check('Six jobs and initial viewer rendered',"window.JN1_DATA.jobs.length===6 && document.querySelectorAll('[data-job]').length===6 && document.getElementById('boxTable').children.length===15")
 check('All 122 saved events / four phases render with correct committed counts',"""(()=>{let count=0;const V=window.JN1_VIEWER;for(let j=0;j<6;j++){V.pickJob(j);for(let i=0;i<V.job().events.length;i++){V.goStep(i);for(const phase of ['before','selected','monitored','after']){V.state.phase=phase;V.render();const e=V.event(),st=V.visibleState();if(st.placed_items.length!==(phase==='after'?e.after:e.before).placed_items.length)throw Error('state count');if(!document.getElementById('monitorPanel').textContent.trim())throw Error('empty panel');count++;}}}return count===488;})()""")
 check('Unavailable result shows mismatch and no fabricated final reaction table',"(()=>{const V=JN1_VIEWER;V.pickJob(2);V.goStep(V.job().events.length-1);V.state.phase='monitored';V.render();const t=document.getElementById('monitorPanel').textContent;return t.includes('620')&&t.includes('不可评价')&&!t.includes('该箱的角点反力');})()")
 check('Empty-pool event has no selected candidate or monitor',"(()=>{const V=JN1_VIEWER;V.pickJob(0);V.goStep(V.job().events.length-1);V.state.phase='after';V.render();return !V.event().monitor&&!V.event().candidate&&document.getElementById('monitorPanel').textContent.includes('monitor 为 null');})()")
 check('Box search and state filter',"(()=>{document.getElementById('boxSearch').value='B01';document.getElementById('boxSearch').dispatchEvent(new Event('input'));const ok=document.querySelectorAll('#boxTable tr[data-box]').length===1;document.getElementById('boxSearch').value='';document.getElementById('boxFilter').value='future';document.getElementById('boxFilter').dispatchEvent(new Event('change'));return ok&&document.querySelectorAll('#boxTable tr[data-box]').length===JN1_VIEWER.job().items.length-JN1_VIEWER.visibleState().arrival_count;})()")
 check('Formula and source tabs render',"(()=>{const V=JN1_VIEWER;V.state.tab='formula';V.render();const ok=document.getElementById('monitorPanel').textContent.includes('239');V.state.tab='evidence';V.render();return ok&&document.getElementById('monitorPanel').textContent.includes('SHA256');})()")
 check('Playback advances saved events and stops',"""(async()=>{const V=JN1_VIEWER;V.pickJob(0);V.goStep(0);document.getElementById('speed').value='400';document.getElementById('play').click();await new Promise(r=>setTimeout(r,850));document.getElementById('play').click();return V.state.step>=1&&!V.state.timer;})()""")
 check('Overview contains six rows',"(()=>{JN1_VIEWER.overview();const ok=document.querySelectorAll('[data-open-job]').length===6;document.getElementById('closeOverview').click();return ok;})()")
 check('All 17 native requests and output panels render',"""(()=>{let n=0;const V=JN1_VIEWER;for(let j=0;j<6;j++){V.pickJob(j);V.state.tab='jev';for(let i=0;i<V.job().events.length;i++){if(!V.job().events[i].io)continue;V.goStep(i);const e=V.event(),io=e.io;if(io.request.state.memories.length!==0||io.response.answers.next_action.choice!==e.selection.selected_display_id)throw Error('native mapping');const text=document.getElementById('monitorPanel').textContent;if(!text.includes('实际发送的请求 JSON')||!text.includes(e.selection.selected_candidate_id))throw Error('IO missing');n++;}}return n===17;})()""")
 check('Local baseline explicitly has no API output',"(()=>{JN1_VIEWER.pickJob(1);JN1_VIEWER.state.tab='jev';JN1_VIEWER.render();return document.getElementById('monitorPanel').textContent.includes('没有原生输出');})()")
 check('Side-by-side layouts switch both source orders',"(()=>{const el=document.getElementById('compareTask');for(const v of ['0','1']){el.value=v;el.dispatchEvent(new Event('change'));if(document.querySelectorAll('.comparison-card img').length!==3||![...document.querySelectorAll('.comparison-card img')].every(x=>x.src.startsWith('data:image/png')))return false;}el.value='0';el.dispatchEvent(new Event('change'));return true;})()")
 # Actual hit-testing through Chrome input events, not a direct state setter.
 evaluate("JN1_VIEWER.pickJob(0);JN1_VIEWER.state.tab='monitor';JN1_VIEWER.render();document.getElementById('canvasWrap').scrollIntoView();")
 target=evaluate("(()=>{const f=JN1_VIEWER.hitFaces().at(-1),r=document.getElementById('scene').getBoundingClientRect();return {id:f.id,x:r.left+f.pts.reduce((a,p)=>a+p[0],0)/f.pts.length,y:r.top+f.pts.reduce((a,p)=>a+p[1],0)/f.pts.length};})()")
 command('Input.dispatchMouseEvent',{'type':'mousePressed','x':target['x'],'y':target['y'],'button':'left','clickCount':1})
 command('Input.dispatchMouseEvent',{'type':'mouseReleased','x':target['x'],'y':target['y'],'button':'left','clickCount':1})
 assert evaluate('JN1_VIEWER.state.box')==target['id']
 assertions.append({'check':'Actual canvas click selects the visible box','status':'PASS'})
 check('Phase controls hide monitor results before selection',"(()=>{document.querySelector('[data-phase=before]').click();const ok=!JN1_VIEWER.ghost()&&!document.getElementById('monitorPanel').textContent.includes('全局地面反力');document.querySelector('[data-phase=monitored]').click();return ok&&document.getElementById('monitorPanel').textContent.includes('全局地面反力');})()")
 downloads=Path(profile)/'downloads';downloads.mkdir()
 command('Page.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads)})
 evaluate("JN1_VIEWER.state.tab='evidence';JN1_VIEWER.render();document.querySelector('[data-download=result]').click()")
 for _ in range(50):
  files=list(downloads.glob('*.json'))
  if files:break
  time.sleep(.1)
 assert files and json.loads(files[0].read_text())['status']=='STABLE'
 assertions.append({'check':'Download button produces saved monitor JSON','status':'PASS'})
 evaluate("JN1_VIEWER.pickJob(0);JN1_VIEWER.state.tab='monitor';document.getElementById('boxFilter').value='all';JN1_VIEWER.render();document.getElementById('canvasWrap').scrollIntoView();")
 time.sleep(.3)
 (QA/'desktop.png').write_bytes(base64.b64decode(command('Page.captureScreenshot',{'format':'png'})['data']))
 evaluate("window.scrollTo(0,0)")
 time.sleep(.2)
 (QA/'comparison.png').write_bytes(base64.b64decode(command('Page.captureScreenshot',{'format':'png'})['data']))
 check('Desktop no horizontal overflow',"document.documentElement.scrollWidth<=innerWidth+1")
 command('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
 time.sleep(.3)
 check('Mobile no horizontal overflow',"document.documentElement.scrollWidth<=innerWidth+1")
 evaluate("JN1_VIEWER.pickJob(2);JN1_VIEWER.goStep(JN1_VIEWER.job().events.length-1);JN1_VIEWER.state.phase='monitored';JN1_VIEWER.render();document.getElementById('canvasWrap').scrollIntoView();")
 time.sleep(.2)
 (QA/'mobile.png').write_bytes(base64.b64decode(command('Page.captureScreenshot',{'format':'png'})['data']))
 # Independent JS recomputation must pass the saved tolerance for every stable node.
 check('All browser recomputed saved node balances within frozen tolerance',"""(()=>{let n=0;for(const j of JN1_DATA.jobs)for(const e of j.events){const r=e.monitor?.result;if(r?.status!=='STABLE')continue;const d=r.diagnostics;for(const node of d.nodes){const out=d.reactions.filter(x=>x.upper===node.item_id),ins=d.reactions.filter(x=>x.lower===node.item_id);const sum=a=>a.reduce((v,x)=>v+x.mass_kg,0);if(Math.abs(sum(out)-sum(ins)-node.own_mass_kg)>node.mass_tolerance_kg)return false;for(let k=0;k<2;k++){const a=out.reduce((v,x)=>v+x.mass_kg*(x.point_mm[k]-node.own_center_mm[k]),0),b=ins.reduce((v,x)=>v+x.mass_kg*(x.point_mm[k]-node.own_center_mm[k]),0);if(Math.abs(a-b)>node.moment_tolerance_kg_mm)return false;}n++;}}return n===239;})()""")
 assert not errors,errors
 result={'status':'PASS','browser':'existing Google Chrome headless/CDP, file://','checks':assertions,'js_exceptions':errors,'data_events':122,'rendered_event_phase_combinations':488,'order_runs':0,'LP_calls':0,'new_model_calls':0,'network_policy':'Page HTTP/HTTPS/WS/WSS blocked via CDP; local file only','screenshots':['qa/desktop.png','qa/mobile.png','qa/comparison.png']}
 (QA/'browser_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('PASS',len(assertions),'browser checks; 488 event/phase combinations; no JavaScript exceptions')
finally:
 if ws:ws.close()
 proc.terminate()
 try:proc.wait(timeout=8)
 except subprocess.TimeoutExpired:proc.kill();proc.wait()
 log.close();shutil.rmtree(profile,ignore_errors=True)
