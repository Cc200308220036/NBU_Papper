from cdp_client import CDP
import time,json
from pathlib import Path
c=CDP();c.call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False});time.sleep(2)
checks=[]
def check(name,script):
 result=c.ev(script);checks.append({'name':name,'result':result});assert result, name
check('36 slots', 'D.jobs.length===36')
check('all initial candidates represented', 'document.querySelectorAll("[data-candidate]").length===event().candidates.length')
c.ev("document.querySelector('[data-candidate=\"C01\"]').click()")
check('candidate inspection keeps actual selection',"state.candidate==='C01' && actual(event())==='C18'")
c.ev("state.sort='prob';renderDetail()")
check('probability sorting',"document.querySelector('[data-candidate]').dataset.candidate==='C18'")
c.ev("state.filter='C01';renderDetail()")
check('candidate filtering',"document.querySelectorAll('[data-candidate]').length===1")
c.ev("state.filter='';state.sort='label';state.phase='after';render()")
check('after phase one committed item',"mainWorld.meshes.length===event().after.placed_items.length+1")
# One extra mesh here is the explicitly inspected alternative, which remains uncommitted.
c.ev("state.phase='monitored';state.candidate=null")
c.ev("setStep(8);state.tab='pct';renderDetail();document.querySelector('#detailContent').scrollIntoView()");time.sleep(.5)
check('PCT balance nodes', "document.querySelectorAll('#pctNode option').length===diag(event()).nodes.length")
c.shot('report/visualization/Jev_JN4_六方法决策回看_20261107/qa/pct.png')
c.ev("choose('J0016',2)");time.sleep(.5);c.ev("state.tab='memory';renderDetail()");check('actual E fragment shown', "event().request.state.memories.length>0 && document.querySelector('#detailContent').innerText.includes('HYPOTHESIS')")
c.ev("choose('J0027',21)");time.sleep(.5);check('singleton probability absent',"event().selection.source==='singleton' && event().selection.probabilities===null && document.querySelector('#selectionSummary').innerText.includes('未调用Jev')")
c.ev("choose('J0006',14)");time.sleep(.5);c.ev("state.tab='pct';renderDetail()");check('old mismatch preserved', "document.querySelector('#detailContent').innerText.includes('POSE_HEIGHT_MISMATCH')")
c.ev("choose('J0011',6)");time.sleep(.5);check('unknown send preserved', "event().request_state==='UNKNOWN_SEND' && !event().monitor?.result && !actual(event())")
c.ev("choose('J0014',0)");time.sleep(.5);c.ev("page('compare')");time.sleep(1.5);check('six method views', "document.querySelectorAll('.mini-scene canvas').length===6")
c.ev("document.querySelector('#page-compare').scrollIntoView()");c.shot('report/visualization/Jev_JN4_六方法决策回看_20261107/qa/comparison.png')
c.ev("page('library')");check('all frozen memory cards', "document.querySelectorAll('#libraryContent .memory-card').length===4")
c.ev("page('about')");check('36 provenance rows', "document.querySelectorAll('#aboutContent tbody tr').length===36")
c.ev("page('explorer');choose('J0014',0)");time.sleep(.5);c.ev("state.tab='candidates';renderDetail();window.scrollTo(0,0)")
c.call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True});time.sleep(.5)
check('mobile no horizontal overflow', 'document.documentElement.scrollWidth<=390')
c.shot('report/visualization/Jev_JN4_六方法决策回看_20261107/qa/mobile.png')
c.call('Page.navigate',{'url':(Path('report/visualization/Jev_JN4_六方法决策回看_20261107/web/index.html').resolve().as_uri())});time.sleep(2);check('offline file entry', 'state.job.id==="J0014" && document.querySelectorAll("[data-candidate]").length>0')
for p in ['library','about','compare','explorer']:
 c.ev(f"page('{p}')");time.sleep(.4);check('mobile '+p+' width','document.documentElement.scrollWidth<=390')
c.ev("page('explorer');state.phase='after';document.querySelector('#compareFinal').checked=false;page('compare')");time.sleep(.6);check('ordinal comparison uses before state',"miniWorlds[2].meshes.length===window.JN4_JOBS['J0014'].events[0].before.placed_items.length+1")
check('no uncaught errors',str(not c.errors).lower());Path('report/visualization/Jev_JN4_六方法决策回看_20261107/qa/browser_checks.json').write_text(json.dumps({'checks':checks,'uncaught_errors':c.errors},ensure_ascii=False,indent=2));print(checks)
