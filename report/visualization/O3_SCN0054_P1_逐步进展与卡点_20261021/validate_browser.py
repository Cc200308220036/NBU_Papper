"""Verify local file:// page with an existing Chrome CDP endpoint (no external site)."""
from pathlib import Path
import base64
import json
import time
import urllib.request
import websocket

HERE=Path(__file__).resolve().parent
tabs=json.loads(urllib.request.urlopen('http://localhost:9323/json/list').read())
tab=next(t for t in tabs if t['type']=='page')
ws=websocket.create_connection(tab['webSocketDebuggerUrl'],origin='http://localhost:9323',timeout=60)
seq=0;errors=[]
def command(method,params=None):
    global seq
    seq+=1;i=seq;ws.send(json.dumps({'id':i,'method':method,'params':params or {}}))
    while True:
        msg=json.loads(ws.recv())
        if msg.get('method')=='Runtime.exceptionThrown':errors.append(msg['params'])
        if msg.get('id')==i:
            if 'error' in msg:raise RuntimeError(msg['error'])
            return msg.get('result',{})
def js(code):
    r=command('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
    if 'exceptionDetails' in r:raise RuntimeError(r['exceptionDetails'])
    return r.get('result',{}).get('value')
def wait_ready():
    end=time.monotonic()+60
    while time.monotonic()<end:
        if js('!!(window.app?.ready && document.querySelector("#plot0")?.data)'):
            assert js('document.getElementById("renderError").hidden'),js('document.getElementById("renderError").textContent')
            return
        time.sleep(.15)
    raise TimeoutError('Page not ready')
def go(n):
    js(f'app.go({n})');wait_ready()
def snapshot():
    return js('({state:app.state(),counts:[0,1,2].map(i=>document.getElementById("plot"+i).data.filter(t=>t.type==="mesh3d").length),statuses:[0,1,2].map(i=>document.getElementById("status"+i).textContent),title:document.getElementById("storyTitle").textContent})')
def screenshot(name,full=False):
    if full:
        m=command('Page.getLayoutMetrics')['cssContentSize'];clip={'x':0,'y':0,'width':m['width'],'height':m['height'],'scale':1}
    else:
        y=js('document.querySelector(".controls").getBoundingClientRect().top+scrollY')
        clip={'x':0,'y':max(0,y-10),'width':1600,'height':1190,'scale':1}
    r=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':clip})
    (HERE/name).write_bytes(base64.b64decode(r['data']))

command('Page.enable');command('Runtime.enable')
command('Emulation.setDeviceMetricsOverride',{'width':1600,'height':1100,'deviceScaleFactor':1,'mobile':False})
command('Page.navigate',{'url':(HERE/'index.html').as_uri()})
wait_ready();assert snapshot()['counts']==[0,0,0]
results={'initial':snapshot()};print('Initial WebGL render PASS',flush=True)
go(5);assert snapshot()['counts']==[5,5,5];results['step5']=snapshot();screenshot('关键步05_首次分叉.png')
js('document.querySelector("[data-phase=before]").click()');wait_ready();assert snapshot()['counts']==[4,4,4]
js('document.getElementById("candidates").checked=true;document.getElementById("candidates").dispatchEvent(new Event("change"))');wait_ready()
assert js('[0,1,2].every(i=>document.getElementById("plot"+i).data.some(t=>t.mode==="markers"&&t.customdata?.length>0))')
js('document.getElementById("pick2").value="C03";document.getElementById("pick2").dispatchEvent(new Event("change"))');wait_ready()
assert js('document.getElementById("candidate2").textContent.includes("C03")')
results['before_candidates']=snapshot();print('Before / candidate inspection PASS',flush=True)
js('document.getElementById("candidates").checked=false;document.querySelector("[data-phase=after]").click()');wait_ready()
go(6);assert snapshot()['counts']==[6,6,6]
go(12);assert snapshot()['counts']==[11,12,12];results['step12']=snapshot();screenshot('关键步12_原策略停止.png')
go(16);assert snapshot()['counts']==[11,15,16];results['step16_safe']=snapshot();assert '业务拒放' in results['step16_safe']['statuses'][1]
screenshot('关键步16_安全模式.png');print('Key terminal states PASS',flush=True)
go(17);assert snapshot()['counts']==[11,15,17];results['step17_safe']=snapshot()
js('document.querySelector("[data-mode=observe_business]").click()');wait_ready();assert snapshot()['counts']==[11,17,17]
results['step17_observe']=snapshot();assert js('document.querySelectorAll("#results tr")[1].children[2].textContent')=='2'
screenshot('网页完整预览.png',True);screenshot('最终三维对照.png')
go(16);assert snapshot()['counts']==[11,16,16];results['step16_observe']=snapshot()
assert js('document.getElementById("metrics1").textContent.includes("1 实例")')
print('Mode switch and actual business violation PASS',flush=True)
# Synchronization is exercised by the same Plotly event emitted on a real drag.
js('Plotly.relayout("plot0",{"scene.camera":{eye:{x:2.2,y:-1.3,z:1.1},up:{x:0,y:0,z:1},center:{x:0,y:0,z:0}}}).then(()=>true)')
time.sleep(.3)
cameras=js('[0,1,2].map(i=>document.getElementById("plot"+i)._fullLayout.scene.camera.eye.x)')
assert cameras==[2.2,2.2,2.2],cameras
results['camera_sync']=cameras
js('document.getElementById("sync").checked=false;Plotly.relayout("plot0",{"scene.camera":{eye:{x:1.9,y:-1.3,z:1.1},up:{x:0,y:0,z:1},center:{x:0,y:0,z:0}}}).then(()=>true)')
time.sleep(.2)
assert js('[0,1,2].map(i=>document.getElementById("plot"+i)._fullLayout.scene.camera.eye.x)')==[1.9,2.2,2.2]
go(15)
assert js('[0,1,2].map(i=>document.getElementById("plot"+i)._fullLayout.scene.camera.eye.x)')==[1.9,2.2,2.2]
js('document.getElementById("sync").checked=true;document.getElementById("sync").dispatchEvent(new Event("change"))')
time.sleep(.2)
js('document.getElementById("top").click()');time.sleep(.3)
assert js('document.getElementById("plot0")._fullLayout.scene.camera.eye.z')==2.6
js('document.getElementById("iso").click()');time.sleep(.2)
js('document.getElementById("slider").value=8;document.getElementById("slider").dispatchEvent(new Event("input"))');wait_ready();assert snapshot()['state']['step']==8
js('document.getElementById("next").click()');wait_ready();assert snapshot()['state']['step']==9
js('document.getElementById("prev").click()');wait_ready();assert snapshot()['state']['step']==8
go(4);js('document.getElementById("speed").value="800";document.getElementById("play").click()')
deadline=time.monotonic()+20
while time.monotonic()<deadline:
    st=js('app.state()')
    if st['step']==5 and not st['playing']:break
    time.sleep(.2)
else:raise AssertionError('Playback did not pause at key step 5')
wait_ready();results['playback_pause']=snapshot();print('View controls, slider and guided playback PASS',flush=True)
# Exercise every arrival and both phases in both modes, including frozen branches.
frame_checks=0
for m in ['safe','observe_business']:
    js(f'app.setMode("{m}")');wait_ready()
    for p in ['before','after']:
        js(f'document.querySelector("[data-phase={p}]").click()');wait_ready()
        for n in range(18):
            go(n)
            expected=js('app.data.modes[app.state().mode].map(t=>{const n=app.state().step;if(!n)return 0;const e=t.steps[Math.min(n-1,t.steps.length-1)];return (app.state().phase==="before"&&n<=t.steps.length?e.before:e.after).length})')
            assert snapshot()['counts']==expected,(m,p,n,snapshot(),expected)
            frame_checks+=1
    print('All arrivals and phases PASS:',m,flush=True)
results['arrival_phase_checks']=frame_checks
assert js('Plotly.toImage("plot2",{format:"png",width:400,height:300}).then(s=>s.startsWith("data:image/png;base64,"))')
results['png_export']='PASS'
js('document.querySelector("[data-phase=after]").click()');wait_ready();go(17)
screenshot('网页完整预览.png',True);screenshot('最终三维对照.png')
# Responsive layout, no horizontal overflow at a narrow viewport.
command('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
js('window.dispatchEvent(new Event("resize"))');time.sleep(.6)
overflow=js('({scroll:document.documentElement.scrollWidth,width:innerWidth,columns:getComputedStyle(document.getElementById("boards")).gridTemplateColumns})')
assert overflow['scroll']<=overflow['width']+1,overflow
results['mobile']=overflow
mobile=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
(HERE/'移动端预览.png').write_bytes(base64.b64decode(mobile['data']))
assert not errors,errors
results.update(status='PASS',runtime_exceptions=errors,browser=tab['webSocketDebuggerUrl'].split('/devtools/')[0].replace('ws:','http:'),
               source='Real Chrome file:// WebGL / CDP validation; no external requests')
(HERE/'browser_validation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print('All browser assertions PASS',flush=True)
try:command('Browser.close')
except Exception:pass
ws.close()
