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
 call('browsingContext.setViewport',{'context':ctx,'viewport':{'width':1560,'height':1180},'devicePixelRatio':1})
 call('browsingContext.navigate',{'context':ctx,'url':(HERE/'index.html').as_uri(),'wait':'complete'})
 def js(s):
  r=call('script.evaluate',{'expression':s,'target':{'context':ctx},'awaitPromise':True})
  assert r['type']=='success',r
  return r['result'].get('value')
 def obj(s):return json.loads(js('JSON.stringify('+s+')'))
 assert js('viewer.ready')
 frames=[]
 for n in range(5):
  js(f'viewer.go({n})');v=obj('viewer.state()');assert v['counts']==[n,n]
  assert js('document.querySelectorAll("#panels svg").length')==2
  assert js('document.querySelectorAll(".placed-box").length')==n*2
  frames.append(v['counts'])
 for mode in ('top','iso','front'):
  js(f'viewer.view("{mode}")');assert js('document.querySelectorAll("svg").length')==2
 js('viewer.go(1);viewer.view("top");viewer.options(true)')
 assert js('document.querySelectorAll(".candidate-outline").length')==4
 js('viewer.options(false)');assert js('document.querySelectorAll(".candidate-outline").length')==0
 js('viewer.options(true);viewer.box(1,0)');assert 'C17' in js('document.getElementById("boxInfo").textContent')
 assert js('document.getElementById("full").textContent')==json.loads((HERE/'case_data.json').read_text())['actual_instruction']
 assert len(obj('Array.from(document.querySelectorAll("tr.difference"))'))==2
 js('viewer.go(3)');assert '箱05' in js('document.getElementById("stepNote").textContent')
 js('viewer.play()');assert js('document.getElementById("play").textContent')=='暂停'
 js('viewer.play()');assert js('document.getElementById("play").textContent')=='播放对比'
 js('viewer.go(1);viewer.view("top")')
 shot=call('browsingContext.captureScreenshot',{'context':ctx,'origin':'viewport'})
 (HERE/'browser_first_box.png').write_bytes(base64.b64decode(shot['data']))
 js('viewer.go(4);viewer.view("iso")')
 shot=call('browsingContext.captureScreenshot',{'context':ctx,'origin':'viewport'})
 (HERE/'browser_final_layout.png').write_bytes(base64.b64decode(shot['data']))
 for width in (1560,760,390):
  call('browsingContext.setViewport',{'context':ctx,'viewport':{'width':width,'height':1000},'devicePixelRatio':1})
  assert not js('document.documentElement.scrollWidth>innerWidth'),width
 assert not [x for x in logs if x.get('level')=='error'],logs
 data=json.loads((HERE/'case_data.json').read_text())
 for p,h in data['source_hashes'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h
 receipt={'status':'PASS','browser':'Firefox WebDriver BiDi','frames':frames,'views':['top','iso','front'],'candidate_overlay':True,'box_details':True,'play_pause':True,'actual_full_instruction_matches':True,'divergent_steps':2,'responsive_widths':[1560,760,390],'source_hashes_unchanged':True,'javascript_errors':[],'new_model_calls':0,'new_episode_runs':0,'new_monitor_calls':0}
 (HERE/'browser_validation.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt))
try:main()
finally:
 try:call('session.end',{})
 finally:w.close()
