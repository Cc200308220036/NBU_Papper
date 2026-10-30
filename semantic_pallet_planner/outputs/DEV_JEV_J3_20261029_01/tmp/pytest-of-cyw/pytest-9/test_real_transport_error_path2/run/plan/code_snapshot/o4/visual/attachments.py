"""Public visual/text envelopes with checked local PNG bytes; offline transport only."""
import copy
import hashlib
from pathlib import Path
from ..common import O4Error,digest
from ..observation import rebind
from ..buffer.buffer_protocol import validate_state,validate_observation
from .facts import unpack


def safe_asset(root,path):
    root=Path(root).resolve();relative=Path(path)
    if relative.is_absolute() or '..' in relative.parts or relative.suffix!='.png':raise O4Error('unsafe_image_path')
    target=(root/relative).resolve()
    if root not in target.parents or not target.is_file():raise O4Error('unsafe_image_path')
    return target


def checked_bytes(root,asset):
    value=safe_asset(root,asset['path']).read_bytes()
    if hashlib.sha256(value).hexdigest()!=asset['sha256']:raise O4Error('invalid_image_digest')
    return value


def attach(source,facts,assets,root,*,with_images=True):
    """Text and image conditions receive the SAME explicit face/label facts."""
    from .verify import audit_facts
    audit_facts(source,facts);obs,buf=unpack(source)
    for item in assets:checked_bytes(root,item)
    attached=[{'path':x['path'],'sha256':x['sha256']} for x in assets] if with_images else []
    result=copy.deepcopy(source)
    request=result['observation'] if buf else result
    request['images']=attached
    request['observation_digest']=digest({k:v for k,v in request.items() if k not in ('request_id','observation_digest')})
    if buf:
        validate_observation(request)
        result['buffer_state_hash']=digest({k:v for k,v in result.items() if k!='buffer_state_hash'});validate_state(result)
    else:result=rebind(result)
    payload={'schema_version':'o4_visual_input_v1','public_request':result,
             'visual_facts':copy.deepcopy(facts),'visual_facts_digest':facts['facts_digest'],
             'images':attached,'condition':'image' if with_images else 'text'}
    payload['binding_digest']=digest(payload)
    return payload


def offline_transfer(envelope,root,client):
    """A5 proves real byte transport to a test double, not model accuracy."""
    if set(envelope)!={'schema_version','public_request','visual_facts','visual_facts_digest','images','condition','binding_digest'} or envelope['schema_version']!='o4_visual_input_v1' or envelope['condition'] not in ('text','image'):
        raise O4Error('invalid_visual_binding','closed envelope required')
    if (envelope['condition']=='text' and envelope['images']) or (envelope['condition']=='image' and not envelope['images']):raise O4Error('invalid_visual_binding')
    if not getattr(client,'fake',False):raise O4Error('unsupported_construct','real model belongs to O4-D')
    if envelope['binding_digest']!=digest({k:v for k,v in envelope.items() if k!='binding_digest'}):raise O4Error('invalid_visual_binding')
    source=copy.deepcopy(envelope['public_request']);obs,buf=unpack(source)
    if obs['images']!=envelope['images']:raise O4Error('invalid_visual_binding')
    obs['images']=[];obs['observation_digest']=digest({k:v for k,v in obs.items() if k not in ('request_id','observation_digest')})
    if buf:source['buffer_state_hash']=digest({k:v for k,v in source.items() if k!='buffer_state_hash'})
    from .verify import audit_facts
    audit_facts(source,envelope['visual_facts'])
    if envelope['visual_facts_digest']!=envelope['visual_facts']['facts_digest']:raise O4Error('invalid_visual_binding')
    attachments=[{'path':a['path'],'sha256':a['sha256'],'mime_type':'image/png','bytes':checked_bytes(root,a)} for a in envelope['images']]
    reply=client.complete({'public_input':copy.deepcopy(envelope),'image_attachments':attachments})
    return {'fake':True,'image_count':len(attachments),'byte_count':sum(len(a['bytes']) for a in attachments),'reply':reply}
