"""Validate saved-result visualization only; never invoke planner or model."""
from pathlib import Path
import base64, hashlib, json, time, urllib.request, websocket
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
tab = next(p for p in json.loads(urllib.request.urlopen('http://127.0.0.1:9334/json/list').read()) if p['type'] == 'page')
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], origin='http://localhost:9334', timeout=20)
seq = 0
errors = []
def cmd(method, params=None):
    global seq
    seq += 1
    ws.send(json.dumps({'id':seq, 'method':method, 'params':params or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get('method') == 'Runtime.exceptionThrown': errors.append(r['params'])
        if r.get('id') == seq:
            assert 'error' not in r, r
            return r.get('result', {})
def js(code):
    r = cmd('Runtime.evaluate', {'expression':code, 'returnByValue':True})
    assert 'exceptionDetails' not in r, r
    return r.get('result', {}).get('value')
cmd('Runtime.enable'); cmd('Page.enable')
cmd('Emulation.setDeviceMetricsOverride', {'width':1600, 'height':1400, 'deviceScaleFactor':1, 'mobile':False})
cmd('Page.navigate', {'url':(HERE/'index.html').as_uri()})
for _ in range(100):
    if js('!!window.viewer?.ready'): break
    time.sleep(.1)
else: raise RuntimeError('Page not ready')
checks = []
for n in range(10):
    js(f'viewer.go({n})')
    state = js('viewer.state()')
    assert state['counts'] == [min(n,8), min(n,8), min(n,7), min(n,8)], state
    checks.append(state)
candidate_checks = 0
for m in range(4):
    js(f'viewer.go(9);viewer.select({m})')
    assert js('JSON.parse(document.getElementById("input").textContent) !== null')
    assert js('JSON.parse(document.getElementById("output").textContent) !== null')
    count = js('document.querySelectorAll("#candidateTable tr").length')
    for c in range(count):
        js(f'viewer.candidate({c})')
        assert js('viewer.state().ghost') == c
        candidate_checks += 1
for mode in ['top', 'iso']:
    js(f'viewer.view("{mode}")')
    assert js('document.querySelectorAll("#panels svg").length') == 4
js('viewer.select(0);viewer.go(9);viewer.view("iso")')
assert not js('document.documentElement.scrollWidth > innerWidth')
shot = cmd('Page.captureScreenshot', {'format':'png', 'captureBeyondViewport':False})
(HERE/'browser_overview.png').write_bytes(base64.b64decode(shot['data']))
cmd('Emulation.setDeviceMetricsOverride', {'width':760, 'height':1000, 'deviceScaleFactor':1, 'mobile':False})
assert not js('document.documentElement.scrollWidth > innerWidth')
assert not errors, errors
data = json.loads((HERE/'case_data.json').read_text())
for path, digest in data['source_hashes'].items():
    assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest, path
(HERE/'browser_validation.json').write_text(json.dumps({'status':'PASS', 'frame_checks':checks, 'candidate_checks':candidate_checks, 'views':['top','iso'], 'viewport_widths':[1600,760], 'source_hashes_unchanged':True, 'javascript_errors':errors, 'new_api_attempts':0, 'new_episode_runs':0}, ensure_ascii=False, indent=2)+'\n')
print(f'PASS: 10 frames, {candidate_checks} candidates, four input/output panels, two views and viewports; source episodes unchanged.')
ws.close()
