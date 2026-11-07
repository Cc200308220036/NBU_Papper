import json,urllib.request,websocket,time,base64
from pathlib import Path
class CDP:
 def __init__(self):
  req=urllib.request.Request('http://127.0.0.1:9227/json/new?http://127.0.0.1:8767',method='PUT');t=json.load(urllib.request.urlopen(req));self.ws=websocket.create_connection(t['webSocketDebuggerUrl']);self.id=0;self.errors=[];self.call('Runtime.enable');self.call('Page.enable')
 def call(self,m,p={}):
  self.id+=1;target=self.id;self.ws.send(json.dumps({'id':target,'method':m,'params':p}))
  while True:
   r=json.loads(self.ws.recv())
   if r.get('method')=='Runtime.exceptionThrown':self.errors.append(r)
   if r.get('id')==target:return r.get('result',r)
 def ev(self,s):
  r=self.call('Runtime.evaluate',{'expression':s,'awaitPromise':True,'returnByValue':True});
  if 'exceptionDetails' in r:raise Exception(r)
  return r.get('result',{}).get('value')
 def shot(self,p):Path(p).write_bytes(base64.b64decode(self.call('Page.captureScreenshot',{'captureBeyondViewport':False})['data']))
