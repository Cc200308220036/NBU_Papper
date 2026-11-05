"""Standard-library byte/receipt check. Never imports runtime or a model client."""
from pathlib import Path
import hashlib
import json
import re
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
DOCS=['docs/03_阶段产出分析/Jev/Jev_JN4合成组合新订单与六方法计划准备验收_20261105.md',
      'docs/02_阶段实施方案/Jev/README.md','docs/03_阶段产出分析/Jev/README.md']


def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def tree(p):return {str(f.relative_to(p)):sha(f) for f in sorted(p.rglob('*')) if f.is_file()}


def main():
    protected=read(HERE/'protected_before.json')
    for p,m in protected.items():assert tree(ROOT/p)==m,('protected_changed',p)
    plan=read(HERE/'plan_final/plan.json');source=read(HERE/'source_manifest.json')
    assert plan['source_manifest']==source
    for n,h in source.items():
        assert sha(ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'/n)==h,n
        assert sha(HERE/'code_snapshot'/n)==h,n
    draft=read(HERE/'plan/plan.json')
    for n,h in draft['source_manifest'].items():assert sha(HERE/'development_source_snapshot'/n)==h,n
    for n,h in read(HERE/'algorithm_archive_manifest.json').items():assert sha(HERE/'algorithm_snapshot'/n)==h,n
    receipt=read(HERE/'preparation_receipt.json');handoff=read(HERE/'handoff.json');static=read(HERE/'static_validation.json')
    assert receipt['synthetic_tasks_ready'] is receipt['synthetic_plan_frozen'] is True
    assert receipt['synthetic_execution_admitted'] is receipt['JN4_B_admitted'] is False
    assert handoff['synthetic_execution_admitted'] is handoff['JN4_B_admitted'] is False
    assert receipt['plan']=='plan_final/plan.json' and handoff['plan']=='plan_final'
    assert static['status']=='PASS_STATIC_ONLY' and len(static['tamper_rejections'])==5
    assert len(plan['jobs'])==36 and plan['request_budget']['global']==656
    assert receipt['actual_model_api_calls']==receipt['actual_formal_jobs_executed']==0
    assert receipt['actual_injection_gate']=='NOT_RUN' and not (HERE/'run').exists()
    for doc in DOCS:
        p=ROOT/doc
        for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if '://' not in link:assert (p.parent/link.split('#')[0]).exists(),(doc,link)
    manifest=HERE/'delivery_manifest.json'
    if '--seal' in sys.argv:
        assert not manifest.exists(),'existing_delivery_must_not_be_resealed'
        manifest.write_text(json.dumps({'version':'jev_synthetic_preparation_delivery_v1','files_sha256':tree(HERE),
          'exclusion':'root delivery_manifest.json only','documentation_sha256':{p:sha(ROOT/p) for p in DOCS},
          'synthetic_execution_admitted':False,'JN4_B_admitted':False},ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    m=read(manifest);actual=tree(HERE);actual.pop('delivery_manifest.json')
    assert actual==m['files_sha256'],'delivery_bytes_changed'
    for p,h in m['documentation_sha256'].items():assert sha(ROOT/p)==h,p
    print(json.dumps({'status':'PASS_DELIVERY_BYTES_AND_READINESS','delivery_files':len(actual),'production_files':len(source),
      'protected_files_unchanged':sum(len(v) for v in protected.values()),'formal_model_calls':0,'formal_jobs':0,
      'next':'STOP_AWAIT_INDEPENDENT_QC'},ensure_ascii=False))

if __name__=='__main__':main()
