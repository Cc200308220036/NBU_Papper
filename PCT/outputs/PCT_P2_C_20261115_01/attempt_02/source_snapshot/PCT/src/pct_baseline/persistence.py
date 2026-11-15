"""POSIX single-writer atomic numbered journal. No planner/business imports."""
import fcntl
import json
import os
from pathlib import Path
from .contracts import canonical,digest,read


class RecoveryError(RuntimeError):
    pass


def require(condition,code):
    if not condition:raise RecoveryError(code)


def fsync_dir(path):
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def atomic_new(path,value):
    path=Path(path);temporary=path.with_name('.'+path.name+'.pending')
    require(not path.exists(),'RECORD_ALREADY_EXISTS')
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            stream.write(canonical(value)+'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path);fsync_dir(path.parent)
    except OSError as exc:
        raise RecoveryError('ATOMIC_SAVE_FAILED:'+type(exc).__name__) from exc


class JobLock:
    """Stable inode retained after unlock; never unlink a contended lock file."""
    def __init__(self,root):self.root=Path(root);self.stream=None
    def __enter__(self):
        self.stream=(self.root/'.writer.lock').open('a+b')
        try:fcntl.flock(self.stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.stream.close();self.stream=None
            raise RecoveryError('JOB_LOCK_CONTENDED') from exc
        return self
    def __exit__(self,*args):
        if self.stream:
            fcntl.flock(self.stream,fcntl.LOCK_UN);self.stream.close();self.stream=None


def read_records(root):
    root=Path(root)
    require(not list(root.rglob('*.pending')),'INCOMPLETE_ATOMIC_WRITE')
    try:header=read(root/'header.json')
    except (OSError,ValueError) as exc:raise RecoveryError('INVALID_OR_MISSING_HEADER') from exc
    paths=sorted((root/'journal').glob('*.json'))
    rows=[];previous=digest(header)
    for i,path in enumerate(paths):
        require(path.name==f'{i:08d}.json','JOURNAL_SEQUENCE_GAP')
        try:row=read(path)
        except (OSError,ValueError) as exc:raise RecoveryError('CORRUPT_JOURNAL_JSON') from exc
        require(set(row)=={'version','sequence','previous_digest','checkpoint_digest','checkpoint','record_digest'},'JOURNAL_FIELDS')
        require(row['version']=='pct_b1_recovery_journal_v1' and type(row['sequence']) is int and row['sequence']==i and row['previous_digest']==previous,'JOURNAL_CHAIN_CHANGED')
        require(row['checkpoint_digest']==digest(row['checkpoint']) and row['record_digest']==digest({k:v for k,v in row.items() if k!='record_digest'}),'JOURNAL_DIGEST_CHANGED')
        rows.append(row);previous=row['record_digest']
    return header,rows


class JournalSink:
    def __init__(self,root,header,rows,lock,cut=None):
        self.root=Path(root);self.header=header;self.rows=list(rows);self.lock=lock;self.cut=cut
    def __call__(self,checkpoint):
        require(self.lock.stream is not None,'JOB_LOCK_REQUIRED')
        if self.rows and self.rows[-1]['checkpoint_digest']==digest(checkpoint):return
        row={'version':'pct_b1_recovery_journal_v1','sequence':len(self.rows),
            'previous_digest':self.rows[-1]['record_digest'] if self.rows else digest(self.header),
            'checkpoint_digest':digest(checkpoint),'checkpoint':checkpoint}
        row['record_digest']=digest(row)
        atomic_new(self.root/'journal'/f'{len(self.rows):08d}.json',row)
        self.rows.append(row)
        intent=self.root/'commit_intent.json'
        if intent.exists() and (checkpoint['phase']=='COMMITTED' or checkpoint['phase']=='TERMINATED'):
            intent.unlink();fsync_dir(self.root)
        if self.cut:self.cut(checkpoint)
    def hook(self,phase,event):
        if phase=='before_commit':
            atomic_new(self.root/'commit_intent.json',{'version':'pct_b1_commit_intent_v1',
                'decision_id':event['decision_id'],'before_digest':digest(event['before']),
                'selection_digest':digest(event['selection'])})
