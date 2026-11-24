"""Local browser checks only; uses existing Firefox BiDi, no model or experiment."""
import json,base64,hashlib
from pathlib import Path
import websocket
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
w=websocket.create_connection('ws://127.0.0.1:9335/session',timeout=30,suppress_origin=True)
i=0;logs=[]
def call(method,params):
 global i;i+=1;w.send(json.dumps({'id':i,'method':method,'params':params}))
 while True:
  r=json.loads(w.recv())
  if r.get('method')=='log.entryAdded':logs.append(r['params'])
  if r.get('id')==i:
   if r.get('type')=='error':raise RuntimeError(r)
   return r.get('result',{})
def main():
 call('session.new',{'capabilities':{}})
 ctx=call('browsingContext.create',{'type':'tab'})['context']
 call('session.subscribe',{'events':['log.entryAdded']})
 call('browsingContext.setViewport',{'context':ctx,'viewport':{'width':1500,'height':1200},'devicePixelRatio':1})
 call('browsingContext.navigate',{'context':ctx,'url':(HERE/'index.html').as_uri(),'wait':'complete'})
 def js(s):
  r=call('script.evaluate',{'expression':s,'target':{'context':ctx},'awaitPromise':True});assert r['type']=='success',r
  return r['result'].get('value')
 assert js('viewer.ready')
 frames=[]
 for n in range(9):
  js(f'viewer.go({n})');v=json.loads(js('JSON.stringify(viewer.state())'));assert v['counts']==[min(n,4),n];frames.append(v['counts'])
  assert js('document.querySelectorAll(".box-face").length')==(min(n,4)+n)*5
 for mode in ('top','front','iso'):js(f'viewer.view("{mode}")')
 js('viewer.box(1,7)');assert 'STABLE' in js('document.getElementById("info").textContent')
 assert js('document.getElementById("instruction").textContent')==json.loads((HERE/'case_data.json').read_text())['instruction']
 js('document.getElementById("play").click()');assert js('document.getElementById("play").textContent')=='暂停'
 js('document.getElementById("play").click()');assert js('document.getElementById("play").textContent')=='播放'
 js('viewer.go(8);viewer.view("iso")')
 js("document.getElementById('zoom').value=125;document.getElementById('zoom').dispatchEvent(new Event('input'))")
 assert json.loads(js('JSON.stringify(viewer.state())'))['zoom']==1.25
 js("document.getElementById('zoom').value=100;document.getElementById('zoom').dispatchEvent(new Event('input'))")
 js("window.yawBefore=viewer.state().yaw;window.svg=document.querySelector('svg');svg.setPointerCapture=()=>{};svg.dispatchEvent(new PointerEvent('pointerdown',{clientX:100,clientY:100,pointerId:1}));svg.dispatchEvent(new PointerEvent('pointermove',{clientX:150,clientY:120,pointerId:1}));svg.dispatchEvent(new PointerEvent('pointerup',{clientX:150,clientY:120,pointerId:1}))")
 assert js('viewer.state().yaw!==yawBefore')
 assert js('document.querySelectorAll(".box-face").length')==60
 js('viewer.view("iso")')
 shot=call('browsingContext.captureScreenshot',{'context':ctx,'origin':'viewport'});(HERE/'browser_final_layout.png').write_bytes(base64.b64decode(shot['data']))
 for width in (1500,760,390):
  call('browsingContext.setViewport',{'context':ctx,'viewport':{'width':width,'height':1000},'devicePixelRatio':1})
  assert not js('document.documentElement.scrollWidth>innerWidth'),width
 assert not [x for x in logs if x.get('level')=='error'],logs
 data=json.loads((HERE/'case_data.json').read_text())
 for p,h in data['source_hashes'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h
 result={'status':'PASS','browser':'Firefox BiDi','frames':frames,'views':['iso','top','front'],'synchronized_drag':True,'zoom':True,'play_pause':True,'box_details':True,'full_instruction_matches':True,'responsive_widths':[1500,760,390],'source_hashes_unchanged':True,'javascript_errors':[],'new_model_calls':0}
 (HERE/'browser_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result))
try:main()
finally:
 try:call('session.end',{})
 finally:w.close()
