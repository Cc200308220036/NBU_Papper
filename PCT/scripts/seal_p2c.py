"""Seal P2-C evidence without executing business/model paths."""
import json
import hashlib
from pathlib import Path
import subprocess
OUT=Path('PCT/outputs/PCT_P2_C_20261115_01')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,v):(OUT/name).write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n')
def read(p):return json.loads(p.read_text())

def main():
    previous=[]
    for pkg in ['PCT_P2_B_20261115_01','PCT_P2_B_QA_20261115_01']:
        root=Path('PCT/outputs')/pkg;manifest=read(root/'delivery_manifest.json');mismatches=[]
        for row in manifest['files']:
            p=Path(row['path'])
            if not p.is_file() or sha(p)!=row['sha256']:mismatches.append(str(p))
        previous.append({'package':pkg,'files_checked':len(manifest['files']),'mismatches':mismatches})
    # Complete JSON decoding of archived single-step evidence, not historical rerun.
    records=[]
    for p in Path('PCT/outputs/PCT_P2_B_20261115_01/attempt_06').rglob('*.json'):
        d=read(p);records.append({'path':str(p),'sha256':sha(p),'top_level':list(d) if isinstance(d,dict) else 'list'})
    save('predecessor_checks.json',{'manifests':previous,'complete_single_step_json_read':records,'historical_network_rerun':False,'note':'shared navigation changes from later QA are reported; frozen archive untouched'})
    a=OUT/'attempt_03';assert read(a/'commands_and_results.json')['exit_code']==0
    save('identity.json',{'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'model_manifest_sha256':sha(a/'tests/model_manifest.json'),'weights_sha256':sha(a/'tests/weight_tensors.json'),'pre_execution_identity':'attempt_03/pre_execution_identity.json','pre_inference_weights_identity':'attempt_03/tests/pre_inference_weights_identity.json','model_contract':'attempt_03/tests/model_manifest.json','source_unchanged':read(a/'commands_and_results.json')['source_unchanged']})
    p0=read(Path('PCT/outputs/PCT_P0_CONTRACT_20261114_01/p0_contract.json'))
    save('p0_contract_reference.json',{'path':'PCT/outputs/PCT_P0_CONTRACT_20261114_01/p0_contract.json','sha256':sha(Path('PCT/outputs/PCT_P0_CONTRACT_20261114_01/p0_contract.json')),'features':p0.get('features'),'encoding':p0.get('encoding'),'model':p0.get('model')})
    # Each token column has a public path, physical unit and scaling.
    fields=[]
    for kind,counts in [('placed',11),('leaf',12),('current',6)]:
        if kind=='placed':
            names=['x0','y0','z0','x1','y1','z1','mass','stackable','capacity','current_top_load','remaining_top_load']
            paths=['model_state.placed_objects[].pose + oriented_size_mm + container']*6+['model_state.placed_objects[].'+x for x in ['mass_kg','stackable','max_top_load_kg','current_top_load_kg','remaining_top_load_kg']]
            units=['mm']*6+['kg','bool','kg','kg','kg'];scales=['Lref']*6+[9,1,9,9,9]
        elif kind=='leaf':
            names=['x0','y0','z0','x1','y1','z1','support_ratio','com_margin','resulting_max_height','max_after_area_load_utilization','min_affected_remaining','affected_support_applicable']
            paths=['criteria[Cxx].pose + oriented_size_mm + model_state.container']*6+['criteria[Cxx].features.'+x for x in ['support_ratio','com_margin_mm','resulting_max_height_mm']]+['criteria[Cxx].load_changes: max(after/max_top) over increment>0','criteria[Cxx].load_changes: min(remaining_top_load_kg) over increment>0','criteria[Cxx].load_changes: positive set nonempty']
            units=['mm']*6+['1','mm','mm','1','kg','bool'];scales=['Lref']*6+[1,'Lref','Lref',1,9,1]
        else:
            names=['l','w','h','mass','stackable','capacity'];paths=['model_state.available_objects[0].dimensions_mm.'+x for x in ['length','width','height']]+['model_state.available_objects[0].'+x for x in ['mass_kg','stackable','max_top_load_kg']];units=['mm']*3+['kg','bool','kg'];scales=['Lref']*3+[9,1,9]
        for i in range(counts):fields.append({'token':kind,'index':i,'name':names[i],'public_path':paths[i],'unit':units[i],'divide_by':scales[i],'applicability':'leaf aggregate columns9/10 use column11; empty 0/0/false' if kind=='leaf' and i>=9 else 'required on valid real node; no missing-value fill'})
    save('field_sources.json',{'producer':'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_runtime.py','producer_functions':['resources lines134-140','public_facts/_public_facts lines169-233'],'public_context_dispatch':'semantic_pallet_planner.jev_select.context.ContextBuilder.build delegates packaging protocol','fields':fields,'capacity':'synthetic max_top_load_kg; stackable false retains capacity token but effective permission0','aggregation':'positive increments only including affected ancestors, not only direct contacts; no PCT reaction/LP','geometry':'float64 actual corner then scale; actual z1 retained, not H','effective_validation_tolerance_kg':1e-9,'no_denominator_epsilon':True})
    save('acceptance.json',{'status':'DEVELOPMENT_PASS_PENDING_INDEPENDENT_QA','matrix':[{'id':i,'status':'PASS','evidence':e} for i,e in [('B26',['attempt_03/tests/p0.json','attempt_03/tests/nonzero.json','attempt_03/tests/positive_set_only.json','field_sources.json']),('B27',['attempt_03/tests/b27.json']),('B28',['attempt_03/tests/b28.json','attempt_03/tests/rejections.json'])]],'tests':{'methods':5,'skips':0,'rejections':len(read(a/'tests/rejections.json'))},'network_and_binding':['attempt_03/tests/batch.json','attempt_03/tests/route_0.json','attempt_03/tests/route_1.json','attempt_03/tests/route_3.json','attempt_03/tests/capacity40.json'],'historical_attempts':[{'attempt':1,'passed':4,'errors':1,'cause':'numpy int64 evidence serialization'},{'attempt':2,'passed':5,'errors':0},{'attempt':3,'passed':5,'errors':0,'reason':'add nested-field isolation, exact error codes, reload and load-contract geo weight shape rejection'}],'remote_requests':0,'training_updates':0,'order_execution':'NOT_RUN_NOT_ADMITTED','independent_QA':'PENDING'})
    limits=['随机工程权重，无训练、策略收益或原生成绩结论','仅构造公开输入及单步网络/保存绑定；fixture不证明物理可达','未运行订单、候选生成、LP、监测、提交、22任务矩阵或P3','旧P1-B/P1-C仅geometry_b1；模型订单执行/恢复未准入','P1C-Q01 OPEN，P3成本分析前澄清，历史封印不变','公开面积账本与PCT反力独立；合成包装容量、可满足性UNKNOWN、独立留出来源0','保存事实验证不是密码学签名，不证明任意重签输出确实由网络生成','CPU float32 Torch2.15.0固定环境；未新增跨设备兼容或承载版原生数值等价声明']
    save('limitations.json',{'limitations':limits})
    save('handoff.json',{'status':'B26_B28_DEVELOPMENT_PASS_PENDING_INDEPENDENT_QA','report':'PCT/docs/PCT_P2C承载编码网络与验收_20261115_01.md','manifest':str(OUT/'delivery_manifest.json'),'interfaces':{'encoding':'pct_baseline.load_encoding.encode_load','network':'pct_baseline.load_network.LoadDRLGAT','model':'pct_baseline.load_model.load_model','selection':'pct_baseline.load_selector.PCTLoadSelector','saved_validation':'pct_baseline.load_selector.validate_saved_selection'},'identity':'identity.json','contract':'attempt_03/tests/model_manifest.json','single_step_record_version':'pct_load_single_step_v1','next_action':'Independent quality review only','order_execution_admitted':False,'P3_authorized':False,'P1C_Q01':'OPEN','next_task_prompt':'NOT_CREATED','stop':True})
    files=list(OUT.rglob('*'))+[Path('PCT/README.md'),Path('PCT/docs/README.md'),Path('PCT/docs/PCT_P2C承载编码网络与验收_20261115_01.md'),Path('PCT/scripts/verify_p2c.py'),Path(__file__).relative_to(Path.cwd()),Path('PCT/tests/test_p2c_load.py')]+list(Path('PCT/src/pct_baseline').glob('load_*.py'))
    files=sorted(set(p for p in files if p.is_file() and p.name!='delivery_manifest.json'))
    save('delivery_manifest.json',{'version':'pct_p2c_delivery_manifest_v1','self_excluded':True,'no_cyclic_hash':True,'files':[{'path':str(p),'size':p.stat().st_size,'sha256':sha(p)} for p in files]})
if __name__=='__main__':main()
