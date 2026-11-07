"""Targeted saved-analysis verification; no trajectory replay or runtime imports."""
import argparse, csv, hashlib, json, math, re
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def pointer(x,p):
    for token in p.split('/')[1:]:
        token=token.replace('~1','/').replace('~0','~');x=x[int(token)] if isinstance(x,list) else x[token]
    return x

def verify(b,report=None,deferred=()):
    checked={};cache={};nrefs=0
    def checkfile(p,h):
        p=str(p)
        if p not in checked:checked[p]=sha(p)
        assert checked[p]==h,('sha256',p)
    for x in read(b/'input_manifest.json')['files']:checkfile(x['path'],x['sha256'])
    for x in read(b/'analysis_scope.json')['inputs']:checkfile(x['path'],x['sha256'])
    for entry in read(b/'evidence_index.json')['entries']:
        assert entry['sources'],entry['id']
        for s in entry['sources']:
            checkfile(s['path'],s['sha256'])
            if s['path'] not in cache:cache[s['path']]=read(s['path'])
            pointer(cache[s['path']],s['pointer']);nrefs+=1
    for item in read(b/'visual_review.json')['figures']:checkfile(b/'figures'/item['file'],item['sha256'])
    ms=read(b/'main_24_metrics.json');ps=read(b/'main_16_pairs.json');figs=read(b/'figure_manifest.json')
    assert len(ms)==24 and len(ps)==16
    for p in ps:
        a=p['reference_values'];z=p['alternative_values']
        assert math.isclose(p['volume_delta_pp'],100*(z['placed_volume_ratio']-a['placed_volume_ratio']),abs_tol=1e-10)
        assert math.isclose(p['height_delta_mm'],z['actual_height_mm']-a['actual_height_mm'],abs_tol=1e-10)
    # CSV and JSON must retain exactly the same figure values and states.
    with (b/'main_24_metrics.csv').open() as f:csvrows=list(csv.DictReader(f))
    for a,z in zip(ms,csvrows):
        assert a['job_id']==z['job_id'] and a['category']==z['category']
        assert a['placed_volume_ratio']==float(z['placed_volume_ratio']) and a['placed_items']==int(z['placed_items'])
    for f in figs:
        for s in f['inputs']:checkfile(s['path'],s['sha256'])
        for p in f['files']:assert Path(p).stat().st_size>1000
    f1,f2,f3,f4=[f['settings'] for f in figs]
    assert f1['states']=={r['job_id']:r['category'] for r in ms}
    for i,t in enumerate(f2['task_order']):
        for j,c in enumerate(f2['comparison_order']):
            assert f2['matrix_pp'][i][j]==next(p['volume_delta_pp'] for p in ps if p['task_id']==t and p['comparison']==c)
    assert f2['color_limits_pp'][0]==-f2['color_limits_pp'][1]
    assert len(f3['identity_colors'])==24 and f3['box_aspect']==[1200,1000,850]
    d=read(b/'F4_plot_data.json');assert f4['candidate_actual_z_mm']==d['gap']['candidate']['pose']['z_base_mm']==0
    assert f4['kernel_restored_z_mm']==490 and f4['timeout_progress']==[6,6]
    assert all(not p['evaluation']['comparison_valid'] for p in read(b/'historical_and_partial_pairs.json') if p['task_id']=='SYN_COMBO_02' and p['comparison']=='E/unrelated_E')
    nlinks=0
    if report:
        for target in re.findall(r'\]\(([^)]+)\)',Path(report).read_text()):
            if '://' in target or target.startswith('#'):continue
            target_path=Path(report).parent/target.split('#')[0]
            assert target_path.exists() or target_path.resolve() in deferred,target
            nlinks+=1
    return {'status':'PASS','consumed_files_sha256_checked':len(checked),'evidence_json_pointers_checked':nrefs,'report_links_checked':nlinks,'checks':['input identities unchanged','every evidence source path/hash/JSON pointer resolves','CSV and JSON figure values identical','figure source hashes/current tables/settings agree','PNG/SVG/PDF artifacts exist','all main 16 pair directions retained','invalid timeout not ranked'],'scope':'local saved-analysis checks only; no API, candidates, monitor, commit, replay or validate-run'}
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,default=Path(__file__).parent);ap.add_argument('--report',type=Path);a=ap.parse_args();print(json.dumps(verify(a.input,a.report),ensure_ascii=False))
