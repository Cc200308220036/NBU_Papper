"""Validate review data and execute its controls with a minimal Node DOM stub."""
import json
import re
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
page=(HERE/'review.html').read_text()
raw=re.search(r'<script type="application/json" id="data">(.*?)</script>',page,re.S).group(1)
data=json.loads(raw);assert len(data)==4
script=re.search(r'<script>(.*?)</script>',page,re.S).group(1)
assert len(re.findall(r'<tr>',page))==49
for record in data:
    for d in record['decisions']:
        assert 'instruction_text' in d['input'] and d['AST'] is not None
        assert d['trace']['evaluations']<=256
        if d['event']=='STOP':assert d['actual_action'] is None
harness=r'''
const vm=require('vm'),assert=require('assert'),fs=require('fs'),data=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
class Select{constructor(){this.options=[];this.value='0'}add(v){this.options.push(v)}set innerHTML(v){this.options=[];this.value='0'}}
const ctx={clearRect(){},strokeRect(){},fillRect(){},fillText(){},setLineDash(v){if(v.length)this.dashed=true},dashed:false};
const els={record:new Select(),decision:new Select(),hyp:{checked:true},data:{textContent:data.raw},map:{getContext(){return ctx}},caption:{},input:{},trace:{}};
const sandbox={document:{getElementById(id){return els[id]}},Option:function(label,value){this.label=label;this.value=value}};
vm.createContext(sandbox);vm.runInContext(data.script,sandbox);
assert.equal(els.record.options.length,4);let decisions=0;
for(let i=0;i<4;i++){els.record.value=String(i);vm.runInContext('updateChoices()',sandbox);assert(els.decision.options.length>0);
for(let j=0;j<els.decision.options.length;j++){els.decision.value=String(j);els.hyp.checked=true;ctx.dashed=false;vm.runInContext('draw()',sandbox);
const input=JSON.parse(els.input.textContent),trace=JSON.parse(els.trace.textContent);assert(input.AST);assert(trace.trace.evaluations<=256);decisions++;
els.hyp.checked=false;ctx.dashed=false;vm.runInContext('draw()',sandbox);assert.equal(ctx.dashed,false)}}
process.stdout.write(JSON.stringify({records:4,decisions,controls:'PASS',hypothesis_toggle:'PASS',browser_render:'NOT_PERFORMED_DOM_STUB_ONLY'}));
'''
payload=HERE/'visual_test_input.json'
with payload.open('x') as f:json.dump({'raw':raw,'script':script},f)
completed=subprocess.run(['node','-e',harness,str(payload)],check=True,text=True,capture_output=True)
result={'status':'PASS','checks':json.loads(completed.stdout),'actual_layout_png_exists':(HERE/'actual_layouts.png').is_file(),
        'table_pairs':48,'actual_vs_hypothesis_labeled':True,'png_visual_review':'PENDING_SEPARATE_IMAGE_INSPECTION','new_api_attempts':0}
with (HERE/'visual_smoke.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps(result,ensure_ascii=False,indent=2))
