"""Test layer root authority and failure accounting, stdlib only."""
import copy,json,traceback
from pathlib import Path

def read(p):return json.loads(Path(p).read_bytes())
def write(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def job_status(root,job_id):
    rows=read(Path(root)/'run.json')['rows']
    matches=[r for r in rows if r['job_id']==job_id]
    if len(matches)!=1:raise ValueError('JOB_ID_MISSING_OR_DUPLICATE:'+job_id)
    return matches[0]['status']

class JobHarness:
    def __init__(self,root,receipts):self.root=Path(root);self.receipts=Path(receipts)
    def run(self,job_id,runner,calls,*,passthrough=()):
        """Exactly one runner call. Original errors precede status-read failures.

        Runner and snapshot callbacks receive this same root. Calls are copied
        even if neither run.json nor accounting.json could be created.
        """
        row={'job_id':job_id,'root':str(self.root),'production_status':'UNKNOWN','validation_status':'RUNNING'}
        try:
            result=runner(self.root)
            row['production_status']=job_status(self.root,job_id)
            row['validation_status']='RETURNED_PENDING_BEHAVIOR_ASSERTIONS'
        except BaseException as exc:
            if isinstance(exc,passthrough):raise
            row.update(validation_status='FAIL',original_error={'type':type(exc).__name__,'detail':str(exc),'traceback':traceback.format_exc()})
            try:row['production_status']=job_status(self.root,job_id)
            except Exception as secondary:row['status_read_error']={'type':type(secondary).__name__,'detail':str(secondary)}
            row['monitor_dispatch_records']=copy.deepcopy(calls)
            try:write(self.receipts/(job_id+'.json'),row)
            except Exception as archival:exc.add_note('Receipt IO failed: '+repr(archival))
            raise
        row['monitor_dispatch_records']=copy.deepcopy(calls)
        write(self.receipts/(job_id+'.json'),row)
        return result,row
