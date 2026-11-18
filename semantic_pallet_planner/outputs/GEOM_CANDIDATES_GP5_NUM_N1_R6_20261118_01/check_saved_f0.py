"""Full saved episode/config in, new read-only F0 receipt out; no replay."""
import hashlib,json
from pathlib import Path
from f0_receipts import f0_receipt
I=Path(__file__).resolve().parent;ROOT=Path.cwd()
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,v):(I/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
rows=[]
for label,rel in [('R1_J00','GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01/E/jobs/J00'),('R2_J01','GEOM_CANDIDATES_GP5_NUM_N1_R2_20261118_01/continuation/jobs/J01')]:
    root=I.parent/rel;before={str(p.relative_to(ROOT)):sha(p) for p in root.rglob('*') if p.is_file()}
    episode=read(root/'episode.json');config=read(root/'config.json')
    receipt=f0_receipt(episode,config)
    assert receipt['context_count']==sum(e.get('context') is not None for e in episode['events'])==2
    assert [r['route'] for r in receipt['contexts']]==['CHOICE_REQUIRED','SINGLETON_BYPASS']
    after={str(p.relative_to(ROOT)):sha(p) for p in root.rglob('*') if p.is_file()};assert before==after
    write(label+'_f0_receipt.json',receipt)
    rows.append({'label':label,'root':str(root.relative_to(ROOT)),'full_episode_sha256':sha(root/'episode.json'),'original_config_sha256':sha(root/'config.json'),'all_original_members':before,'original_bytes_unchanged':True,'complete_saved_event_count':len(episode['events']),'decision_context_count':receipt['context_count'],'route_counts':receipt['route_counts'],'status':'PASS_COMPLETE_SAVED_F0_RECEIPT','receipt':label+'_f0_receipt.json','business_replay':False,'production_current_source_e2e_claim':False})
for rel,h in read(I/'archive_member_identity.json')['files'].items():assert sha(Path(rel))==h
write('saved_f0_revalidation.json',{'scope':'complete saved episodes/configs, every context retained, pure read-only F0 check','rows':rows,'business_calls_added':0,'original_R5_QA_probe_preserved':True})
print('PASS full R1/J00 and R2/J01: choice + singleton, original nulls retained; all saved member bytes unchanged; no replay')
