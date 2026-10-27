"""Check only the generated local case UI using the temporary localhost browser."""
from pathlib import Path
import urllib.request,json,time,base64,websocket
HERE=Path(__file__).resolve().parent
pages=json.loads(urllib.request.urlopen('http://127.0.0.1:9334/json/list').read());tab=next(p for p in pages if p['type']=='page')
ws=websocket.create_connection(tab['webSocketDebuggerUrl'],origin='http://localhost:9334',timeout=20)
n=0;errors=[]
def cmd(method,params=None):
 global n
 n+=1;ident=n;ws.send(json.dumps({'id':ident,'method':method,'params':params or {}}))
 while True:
  m=json.loads(ws.recv())
  if m.get('method')=='Runtime.exceptionThrown':errors.append(m['params'])
  if m.get('id')==ident:
   if 'error' in m:raise RuntimeError(m['error'])
   return m.get('result',{})
def js(code):
 r=cmd('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
 if 'exceptionDetails' in r:raise RuntimeError(r['exceptionDetails'])
 return r.get('result',{}).get('value')
cmd('Runtime.enable');cmd('Page.enable');cmd('Emulation.setDeviceMetricsOverride',{'width':1500,'height':1200,'deviceScaleFactor':1,'mobile':False});cmd('Page.navigate',{'url':(HERE/'index.html').as_uri()})
for i in range(100):
 if js('!!window.caseApp?.ready'):break
 time.sleep(.1)
else:raise RuntimeError('Page not ready')
assert not errors,errors
assert js('caseApp.state().placed')==6
assert js('document.querySelectorAll("#candidateTable tr").length')==16
checks=[]
for i in range(8):
 js(f'caseApp.go({i})');state=js('caseApp.state()');assert state['placed']==min(i,6);checks.append(state)
for i in range(16):
 js(f'caseApp.select({i})');assert js('document.getElementById("reason").textContent.includes("业务拒绝")');assert js('document.querySelectorAll("#candidateTable .selected").length')==1
js('caseApp.go(7);caseApp.select(2)')
assert js('document.getElementById("requestJson").textContent.includes("O4F_E0013")')
assert js('JSON.parse(document.getElementById("responseJson").textContent).policy_ast.rules.length')==6
assert js('document.getElementById("actionSummary").textContent.includes("action=null")')
assert not js('document.documentElement.scrollWidth>innerWidth'),'horizontal overflow'
def shot(file,y=0,height=1400):
 r=cmd('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':{'x':0,'y':y,'width':1500,'height':height,'scale':1}});(HERE/file).write_bytes(base64.b64decode(r['data']))
shot('browser_overview.png',0,1650)
y=js('document.getElementById("instruction").closest(".grid").getBoundingClientRect().top+scrollY');shot('browser_input_output.png',y,1500)
cmd('Emulation.setDeviceMetricsOverride',{'width':760,'height':1000,'deviceScaleFactor':1,'mobile':False})
assert not js('document.documentElement.scrollWidth>innerWidth'),'small viewport horizontal overflow'
assert not errors,errors
(HERE/'browser_validation.json').write_text(json.dumps({'status':'PASS','frame_checks':checks,'rejected_candidates_checked':16,'model_input_and_output_panels':'PASS','viewport_widths':[1500,760],'javascript_errors':errors,'new_model_calls':0,'new_episode_replays':0},ensure_ascii=False,indent=2)+'\n')
print('PASS: 8 frames, 16 candidates, full input/output panels, two viewports, no JS errors')
ws.close()
