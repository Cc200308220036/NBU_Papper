"""P4-B-0 durable bounded records and atomic update bundles (stdlib only).

No serializer executes an optimizer. Unresolved intents/pending/orphans fail closed.
All mutations require the same live exclusive store lock. No automatic GC.
"""
import gzip
import hashlib
import os
import shutil
from pathlib import Path
from .contracts import canonical, digest, read, require, sha
from .persistence import JobLock, fsync_dir

VERSION = 'pct_p4b_storage_v1'
UPDATE = 'pct_p4b_update_transaction_v1'
FALLBACK = 601166756537
MAX_SHARD = 64 * 1024 * 1024


def encoded(value):
    return (canonical(value)+'\n').encode()


def seal(value):
    return dict(value, seal=digest(value))


def checked(path):
    value=read(path)
    require(value.get('seal')==digest({k:v for k,v in value.items() if k!='seal'}),'P4B_DIGEST')
    return value


def publish(path, data, fault=lambda _:None):
    """Immutable single-file publication; interruption leaves diagnostic evidence."""
    path=Path(path);require(not path.exists(),'P4B_IMMUTABLE')
    pending=path.with_name(path.name+'.pending')
    with pending.open('xb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    fault('bytes_fsynced')
    os.link(pending,path);fsync_dir(path.parent)
    fault('linked')
    pending.unlink();fsync_dir(path.parent)


class Store:
    def __init__(self, root, identity, *, shard_limit=MAX_SHARD, reserve=0,
                 free=None, fault=None):
        self.root=Path(root);self.identity=identity;self.limit=shard_limit
        require(type(shard_limit) is int and 0<shard_limit<=MAX_SHARD,'P4B_SHARD_LIMIT')
        require(type(reserve) is int and reserve>=0,'P4B_RESERVE')
        self.reserve=reserve;self.free=free or (lambda:shutil.disk_usage(self.root).free)
        self.fault=fault or (lambda _:None);self.lock=None

    def __enter__(self):
        self.root.mkdir(parents=True,exist_ok=True)
        self.lock=JobLock(self.root);self.lock.__enter__()
        try:
            header=self.root/'store.json'
            expected={'version':VERSION,'identity':self.identity,'shard_limit':self.limit,'reserve':self.reserve}
            if header.exists():require(checked(header)==seal(expected),'P4B_IDENTITY_DRIFT')
            else:self.put(header,seal(expected))
            for name in ('shards','index','wal','updates'):(self.root/name).mkdir(exist_ok=True)
            self.audit()
            return self
        except BaseException:
            self.lock.__exit__(None,None,None);raise

    def __exit__(self,*args):self.lock.__exit__(*args)

    def guard(self,n):
        require(self.lock is not None and self.lock.stream is not None,'P4B_LOCK_REQUIRED')
        require(self.free()>=self.reserve+n,'P4B_CAPACITY_SAFE_STOP')

    def put(self,path,value):
        data=encoded(value);require(len(data)<=self.limit,'P4B_RECORD_TOO_LARGE')
        self.guard(len(data));publish(path,data,self.fault)

    def append(self, record, *, key):
        """One bounded immutable shard per record; indexed by logical attempt/stage.

        Record refers to content-addressed state/event blobs, not cumulative history.
        A record exceeding the registered limit is refused before writing.
        """
        require(type(key) is str and key and '/' not in key and '\\' not in key and key not in ('.','..'),'P4B_KEY')
        plain=encoded({'version':VERSION,'identity_digest':digest(self.identity),'key':key,'record':record})
        require(len(plain)<=self.limit,'P4B_RECORD_TOO_LARGE')
        data=gzip.compress(plain,mtime=0);content=hashlib.sha256(data).hexdigest()
        target=self.root/'shards'/(content+'.gz');index=self.root/'index'/(key+'.json')
        require(not index.exists(),'P4B_DUPLICATE_RECORD')
        self.guard(len(data)+4096)
        if not target.exists():publish(target,data,self.fault)
        self.fault('shard_published')
        row=seal({'version':VERSION,'key':key,'shard':content+'.gz','compressed_sha256':content,
                  'plain_sha256':hashlib.sha256(plain).hexdigest(),'plain_bytes':len(plain),'offset':0})
        self.put(index,row);return row

    def records(self):
        for path in sorted((self.root/'index').glob('*.json')):
            row=checked(path)
            require(row['shard']==row['compressed_sha256']+'.gz' and len(row['compressed_sha256'])==64
                    and all(c in '0123456789abcdef' for c in row['compressed_sha256']),'P4B_SHARD_PATH')
            raw=(self.root/'shards'/row['shard']).read_bytes()
            require(hashlib.sha256(raw).hexdigest()==row['compressed_sha256'],'P4B_SHARD_DIGEST')
            plain=gzip.decompress(raw)
            require(len(plain)==row['plain_bytes']<=self.limit and hashlib.sha256(plain).hexdigest()==row['plain_sha256'],'P4B_PLAIN_DIGEST')
            import json
            value=json.loads(plain)
            require(value['identity_digest']==digest(self.identity) and value['key']==row['key']==path.stem,'P4B_RECORD_IDENTITY')
            yield value

    def audit(self):
        require(not list(self.root.rglob('*.pending')),'P4B_PENDING_DIAGNOSIS')
        require(not list((self.root/'updates').glob('intent-*.json')),'P4B_UPDATE_OUTCOME_REQUIRES_DIAGNOSIS')
        records=list(self.records())
        refs={checked(p)['shard'] for p in (self.root/'index').glob('*.json')}
        require(refs=={p.name for p in (self.root/'shards').glob('*.gz')},'P4B_ORPHAN_SHARD')
        updates=sorted((self.root/'updates').glob('u[0-9]*'))
        for i,path in enumerate(updates,1):
            require(path.name==f'u{i:06d}','P4B_UPDATE_GAP')
            self.update_record(path,i)
        return {'records':len(records),'updates':len(updates)}

    def update_record(self,path,update_id):
        row=checked(path/'manifest.json')
        require(row['version']==UPDATE and row['identity']==self.identity and row['update_id']==update_id,'P4B_UPDATE_IDENTITY')
        require(set(row['files'])=={'model','adam','rng'},'P4B_UPDATE_COMPONENTS')
        for name,h in row['files'].items():require(sha(path/name)==h,'P4B_UPDATE_BYTES')
        for ref in row['batch_refs']:
            require(type(ref['key']) is str and ref['key'] not in ('.','..') and '/' not in ref['key'] and '\\' not in ref['key'],'P4B_BATCH_PATH')
            require(checked(self.root/'index'/(ref['key']+'.json'))['seal']==ref['seal'],'P4B_BATCH_DRIFT')
        return row

    def publish_update(self, *, update_id, model, adam, rng, policy_snapshot,
                       cursor, batch_refs):
        """Opaque serialized bytes must already contain complete applicable state.

        Caller must discard any in-memory mutated model on exceptions and stop.
        Pending update is NEVER used as a basis for re-applying optimizer.step.
        """
        self.audit()
        completed=len(list((self.root/'updates').glob('u[0-9]*')))
        require(type(update_id) is int and update_id==completed+1 and update_id<=250,'P4B_DUPLICATE_OR_GAPPED_UPDATE')
        require(set(cursor)=={'epoch','attempt','segment'} and 1<=cursor['epoch']<=125
                and 0<=cursor['attempt']<=2000 and type(cursor['segment']) is int and cursor['segment']>=0,'P4B_CURSOR')
        require(bool(policy_snapshot) and bool(batch_refs),'P4B_UPDATE_REFERENCES')
        for ref in batch_refs:
            require(type(ref['key']) is str and ref['key'] not in ('.','..') and '/' not in ref['key'] and '\\' not in ref['key'],'P4B_BATCH_PATH')
            require(checked(self.root/'index'/(ref['key']+'.json'))['seal']==ref['seal'],'P4B_BATCH_DRIFT')
        payload={'model':model,'adam':adam,'rng':rng}
        require(all(type(v) is bytes and v for v in payload.values()),'P4B_SERIALIZED_STATE_REQUIRED')
        self.guard(sum(map(len,payload.values()))+16384)
        root=self.root/'updates';intent=root/f'intent-{update_id:06d}.json'
        self.put(intent,seal({'version':UPDATE,'update_id':update_id,'identity':self.identity}))
        self.fault('intent')
        pending=root/f'u{update_id:06d}.pending';pending.mkdir()
        for name,data in payload.items():
            publish(pending/name,data)
            self.fault(name)
        row=seal({'version':UPDATE,'update_id':update_id,'identity':self.identity,
                  'files':{n:sha(pending/n) for n in payload},'policy_snapshot':policy_snapshot,
                  'cursor':cursor,'batch_refs':batch_refs})
        publish(pending/'manifest.json',encoded(row));fsync_dir(pending)
        self.fault('manifest')
        os.rename(pending,root/f'u{update_id:06d}');fsync_dir(root)
        self.fault('directory_published')
        intent.unlink();fsync_dir(root);self.fault('intent_cleared')
        return row
