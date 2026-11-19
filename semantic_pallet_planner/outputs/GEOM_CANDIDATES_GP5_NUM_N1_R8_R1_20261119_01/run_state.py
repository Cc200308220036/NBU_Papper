"""Stdlib-only isolation, complete denominator and independent attempt accounting."""
import hashlib,json,traceback
from pathlib import Path
from contextlib import contextmanager

def read(p):return json.loads(Path(p).read_bytes())
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def file_hashes(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
def overlap(a,b):return a==b or a in b.parents or b in a.parents

def case_rows(scope):
    rows=[{'id':'C/'+n,'group':'C'} for n in scope['C']]
    rows += [{'id':'E/J%02d'%i,'group':'E'} for i in range(8)]
    rows += [{'id':'R/'+j+'/'+p,'group':'R'} for j in ('J01','J03') for p in ('SELECTED','MONITORED','COMMITTED')]
    rows += [{'id':'X_H_ADMIN/'+v['name'],'group':'X_H_ADMIN'} for v in scope['X_H_names']]
    assert len(rows)==35 and len({r['id'] for r in rows})==35
    return [{**r,'status':'NOT_RUN','attempts':0,'evidence':[],'error':None} for r in rows]

class RunState:
    def __init__(self,sealed,output,scope,*,protected=(),authorization=None):
        self.sealed=Path(sealed).resolve();self.root=Path(output).resolve()
        if self.root.exists():raise FileExistsError('FRESH_RUN_ROOT_REQUIRED')
        for p in (self.sealed,*map(lambda x:Path(x).resolve(),protected)):
            if overlap(self.root,p):raise ValueError('OUTPUT_OVERLAPS_SEALED_INPUT')
        self.before={str(p):file_hashes(p) for p in (self.sealed,*map(lambda x:Path(x).resolve(),protected))}
        self.rows=case_rows(scope);self.stopped=False
        for row in self.rows:
            if row['group']=='E' and row['id'] not in ('E/J01','E/J03'):row['status']='NOT_RUN_OUT_OF_PROPOSED_MINIMUM_SCOPE'
        self.root.mkdir(parents=False,exist_ok=False)
        write(self.root/'execution_started.json',{'authorization':authorization,'sealed_input':str(self.sealed),'new_output_root':str(self.root),'one_shot':True})
        write(self.root/'sealed_input_identity.json',self.before)
        write(self.root/'call_accounting.json',{'historical_E_used':21,'old17_receipt_preserved':True,'new_E':0,'cross_history_E':21,'new_R_monitors':0,'new_R_commits':0,'R_resumes_attempted':0,'R_resumes_passed':0,'new_X_H_monitors':0,'dispatch_records':[],'real_calls':0})
        self.save()
    def verify_archives(self):
        for p,expected in self.before.items():
            if file_hashes(Path(p))!=expected:raise AssertionError('SEALED_ARCHIVE_CHANGED:'+p)
    def save(self):
        counters={g:{'attempted':sum(r['attempts'] for r in self.rows if r['group']==g),'passed':sum(r['status']=='PASS' for r in self.rows if r['group']==g),'failed':sum(r['status']=='FAIL' for r in self.rows if r['group']==g),'not_run':sum(r['status']=='NOT_RUN' for r in self.rows if r['group']==g)} for g in ('C','E','R','X_H_ADMIN')}
        write(self.root/'case_results.json',{'rows':self.rows,'counts':counters,'stopped':self.stopped,'R_attempts':counters['R']['attempted'],'R_passes':counters['R']['passed']})
    @contextmanager
    def case(self,identity):
        if self.stopped:raise RuntimeError('FIRST_FAILURE_ALREADY_STOPPED')
        row=next(r for r in self.rows if r['id']==identity)
        if row['status']!='NOT_RUN':raise RuntimeError('NO_CASE_RETRY:'+identity)
        row.update(status='RUNNING',attempts=1);self.save()
        try:
            self.verify_archives()
            yield row['evidence']
            self.verify_archives()
        except BaseException as exc:
            self.stopped=True;row.update(status='FAIL',error={'type':type(exc).__name__,'code':getattr(exc,'code',None),'detail':str(exc),'traceback':traceback.format_exc()})
            self.save();write(self.root/'stop.json',{'case_id':identity,'original_error':row['error'],'first_failure':True,'no_retry':True})
            raise
        else:row['status']='PASS';self.save()
