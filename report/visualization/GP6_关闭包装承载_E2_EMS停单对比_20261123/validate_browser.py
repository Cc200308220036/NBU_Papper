"""Validate local viewer only with existing Firefox WebDriver BiDi."""
import json,base64,hashlib
from pathlib import Path
import websocket
HERE=Path(__file__).parent.resolve();ROOT=HERE.parents[2]
w=websocket.create_connection('ws://127.0.0.1:9335/session',timeout=30,suppress_origin=True)
i=0;logs=[]
def call(m,p):
 global i;i+=1;w.send(json.dumps({'id':i,'method':m,'params':p}))
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
 call('browsingContext.setViewport',{'context':ctx,'viewport':{'width':1600,'height':1300},'devicePixelRatio':1})
 call('browsingContext.navigate',{'context':ctx,'url':(HERE/'index.html').as_uri(),'wait':'complete'})
 def js(code):
  r=call('script.evaluate',{'expression':code,'target':{'context':ctx},'awaitPromise':True})
  assert r['type']=='success',r
  return r['result'].get('value')
 def obj(code):return json.loads(js('JSON.stringify('+code+')'))
 assert js('viewer.ready')
 frames=[]
 for n in range(9):
  js(f'viewer.go({n})');v=obj('viewer.state()');assert v['counts']==[n,min(n,4)]
  assert js('document.querySelectorAll("#panels svg").length')==2
  frames.append(v['counts'])
 for view in ('iso','top','front'):
  js(f'viewer.view("{view}")');assert js('document.querySelectorAll("#panels svg").length')==2
 for k in range(25):
  js(f'viewer.go(8);viewer.select(1);viewer.proposal({k})')
  assert js('document.querySelectorAll(".ghost").length')==1
  assert js('document.getElementById("proposal").value')==str(k)
  assert '70%' in js('document.getElementById("probe").textContent')
 js('viewer.supportOnly(true);viewer.ghost(false)');assert js('document.querySelectorAll(".ghost").length')==0
 js('viewer.ghost(true);viewer.supportOnly(false);viewer.select(0);viewer.demo(true);viewer.view("front")')
 assert js('document.querySelectorAll(".ghost").length')==1
 js('viewer.box(0,"item_06")');assert '第 8 次' in js('document.getElementById("selectedInfo").textContent')
 # Evidence screenshot of both finished layouts, actual EMS proposal with highest support.
 data=json.loads((HERE/'case_data.json').read_text());best=max(range(25),key=lambda n:data['jobs'][1]['proposals'][n]['support_ratio'])
 js(f'viewer.select(1);viewer.proposal({best});viewer.demo(false);viewer.view("iso")')
 assert not js('document.documentElement.scrollWidth>innerWidth')
 shot=call('browsingContext.captureScreenshot',{'context':ctx,'origin':'viewport'})
 (HERE/'browser_overview.png').write_bytes(base64.b64decode(shot['data']))
 js('viewer.view("top")');shot=call('browsingContext.captureScreenshot',{'context':ctx,'origin':'document'})
 (HERE/'browser_support_detail.png').write_bytes(base64.b64decode(shot['data']))
 call('browsingContext.setViewport',{'context':ctx,'viewport':{'width':760,'height':1100},'devicePixelRatio':1})
 assert not js('document.documentElement.scrollWidth>innerWidth')
 call('browsingContext.setViewport',{'context':ctx,'viewport':{'width':390,'height':900},'devicePixelRatio':1})
 assert not js('document.documentElement.scrollWidth>innerWidth')
 assert not [x for x in logs if x.get('level')=='error'],logs
 for name,h in data['source_hashes'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h
 receipt={'status':'PASS','browser':'Firefox WebDriver BiDi','frame_counts':frames,'view_modes':['iso','top','front'],'proposal_checks':25,'E2_demo_is_illustration':True,'responsive_widths':[1600,760,390],'source_hashes_unchanged':True,'javascript_errors':[],'new_model_calls':0,'new_episode_runs':0,'new_kernel_calls':0}
 (HERE/'browser_validation.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt))
try:main()
finally:
 try:call('session.end',{})
 finally:w.close()
