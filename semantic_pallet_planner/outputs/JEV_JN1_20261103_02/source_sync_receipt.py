from pathlib import Path
import hashlib,json,subprocess,difflib
root=Path('semantic_pallet_planner/outputs/JEV_JN1_20261103_01')
out=Path('semantic_pallet_planner/outputs/JEV_JN1_20261103_02')
pkg=Path('semantic_pallet_planner/src/semantic_pallet_planner')
report=Path('docs/03_阶段产出分析/Jev/Jev_JN1-A协议适配与最小真实调用验收_20261103.md')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,v):
 p=out/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
assert not out.exists()
status=subprocess.check_output(['git','status','--porcelain'],text=True)
assert status==''
expected=json.loads((root/'source_manifest.json').read_text())
m=json.loads((root/'delivery_manifest.json').read_text())
assert len(expected)==358 and len(m['files_sha256'])==406
assert all(sha(root/n)==h for n,h in m['files_sha256'].items())
assert all(sha(root/'code_snapshot'/n)==h for n,h in expected.items())
current={p.relative_to(pkg).as_posix():sha(p) for p in pkg.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(pkg).parts)}
names=[n for n,h in expected.items() if current.get(n)!=h]
review={
'candidates.py':'v6候选封装仍要求selectable池等于原physical池，仅补校验路由；不改枚举或排序',
'config.py':'protocol_suffix显式识别remote_v6，保留原v1-v5分派',
'context.py':'v6上下文进入原包装校验与重建，保留state/mapping/bundle身份校验',
'contracts.py':'注册六份独立Schema并增加v6后缀分派，不放宽旧Schema',
'episode.py':'v6深拷贝配置及使用独立注册方法表，沿用公共监测提交恢复',
'packaging_experiment.py':'仅保存记录校验按配置选择checkpoint_v6，未开发整单远程路由',
'packaging_protocol.py':'v6 selector工厂显式config/transport/ledger/job_id注入，旧默认v5仍封闭',
'packaging_runtime.py':'显式v6包装识别、上下文后缀、请求model绑定及真实来源/调用统计与独立指标Schema',
'selector.py':'v6选择结果保存network_attempted/error_stage/error_code；保留原packaging远程拒绝',
'monitor.py':'v6预检及无重执行保存记录校验路由；不改算法、容差或稳定提交门槛'}
assert len(names)==10 and {Path(n).name for n in names}==set(review)
jn0=json.loads(Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_02/plan/plan.json').read_text())['source_manifest']
assert all(current[n]==jn0[n] for n in names)
out.mkdir()
write('source_manifest_before.json',current)
protected={str(p):sha(p) for p in root.rglob('*') if p.is_file()}
protected[str(report)]=sha(report)
write('protected_before.json',protected)
write('baseline_verification.json',{'version':'jev_jn1_source_baseline_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
'git_status_before':status,'parent':str(root),'parent_receipt_sha256':sha(root/'handoff.json'),'parent_manifest_sha256':sha(root/'delivery_manifest.json'),
'parent_manifest_file_count':406,'parent_manifest_verified':True,'snapshot_files_verified':358,'source_file_count':len(current),
'differences':names,'all_different_files_match_JN0':True,'extra_production_files':sorted(set(current)-set(expected)),
'parent_real_requests':1,'new_real_request_authorization':0,'historical_report_sha256':sha(report),
'parent_external_documents_note':'原manifest内外部文档摘要为原交付时身份；现索引在后续提交变更，本次只保护原报告与原包，不重签历史外部摘要'})
rows=[];diffs=[]
for n in names:
 old=(pkg/n).read_text();new=(root/'code_snapshot'/n).read_text()
 diffs.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='before/'+n,tofile='accepted/'+n))
 rows.append({'path':n,'before_sha256':current[n],'accepted_sha256':expected[n],'review':review[Path(n).name],
              'later_edits_detected':False,'resolution':'restore only reviewed missing integration diff'})
(out/'reviewed_changes.patch').write_text(''.join(diffs))
# No blind checkout restore: every target must still equal its reviewed baseline.
for r in rows:
 target=pkg/r['path'];assert sha(target)==r['before_sha256']
 target.write_bytes((root/'code_snapshot'/r['path']).read_bytes())
after={p.relative_to(pkg).as_posix():sha(p) for p in pkg.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(pkg).parts)}
assert after==expected
write('source_manifest.json',after)
write('source_sync_review.json',{'version':'jev_jn1_source_sync_review_v1','reviewed_files':rows,'before_matches':348,'restored':10,'after_matches':358,
'missing_after':[],'different_after':[],'extra_after':[],
'new_modules_and_six_schemas':'already match snapshot; not rewritten',
'old_schemas_physical_algorithm_data':'all existing remaining production files unchanged; data identities retained; no new protocol design'})
# Test is absent from production source manifest: bind committed test bytes and archived JUnit case names separately.
test=Path('semantic_pallet_planner/tests/unit/test_packaging_remote.py')
write('test_source_identity.json',{'path':str(test),'sha256':sha(test),'git_head_blob_matches_worktree':subprocess.check_output(['git','show','HEAD:'+str(test)])==test.read_bytes(),
'archived_test_count':'original JUnit is evidence only, current tests rerun separately'})
print({'restored':len(rows),'all_production_files_match':len(after),'output':str(out)})
