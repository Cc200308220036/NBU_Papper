"""Check the packaged single HTML file using the existing local Chrome."""
from pathlib import Path
import subprocess,tempfile,json,re
from html.parser import HTMLParser
root=Path('semantic_pallet_planner/outputs/JEV_JN0_VISUAL_20261103_01').resolve()
class Parsed(HTMLParser):
 def __init__(self):super().__init__();self.jobs=0;self.external=[]
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag=='button' and 'data-job' in d:self.jobs+=1
  if tag=='script' and d.get('src'):self.external.append(d['src'])
  if tag=='link' and d.get('rel')=='stylesheet':self.external.append(d.get('href'))
with tempfile.TemporaryDirectory(prefix='jn0-standalone-') as profile:
 r=subprocess.run(['/usr/bin/google-chrome','--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-background-networking','--disable-extensions','--no-first-run','--user-data-dir='+profile,'--virtual-time-budget=2500','--dump-dom',(root/'JN0_interactive.html').as_uri()],text=True,capture_output=True,timeout=40)
 assert r.returncode==0,r.stderr[-500:]
 p=Parsed();p.feed(r.stdout)
 assert p.jobs==8 and not p.external,(p.jobs,p.external)
 title=re.search(r'<h2 id="jobTitle">(.*?)</h2>',r.stdout,re.S).group(1)
 assert '几何基线' in title,title
 assert '准静态可平衡' in r.stdout
 receipt={'status':'PASS','entry':'JN0_interactive.html','actual_rendered_job_buttons':p.jobs,'actual_rendered_title':title,'external_scripts_or_styles':p.external,'browser':'existing Chrome headless, file://','server_required':False}
 (root/'qa/standalone_acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
 print('PASS standalone HTML: eight jobs rendered, no external scripts/styles/server')
