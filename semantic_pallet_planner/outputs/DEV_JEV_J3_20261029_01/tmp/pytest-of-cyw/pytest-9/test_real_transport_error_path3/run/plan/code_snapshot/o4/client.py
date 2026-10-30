"""Offline-only model boundary. No provider/network implementation in A/B."""
import copy
import json
from .common import O4Error
from .compiler import validate_response
from .observation import validate_observation

class OfflineClient:
    fake=True
    def __init__(self,responses):
        self.responses=list(responses);self.calls=[]
    def complete(self,prompt):
        self.calls.append(copy.deepcopy(prompt))
        if not self.responses:raise O4Error('provider_error','no offline response')
        response=self.responses.pop(0)
        if isinstance(response,Exception):raise response
        return copy.deepcopy(response)


def compile_with_client(req,client):
    validate_observation(req)
    if not getattr(client,'fake',False):raise O4Error('unsupported_construct','real API deferred')
    attempts=[];error=None
    for _ in range(2):
        prompt={'public_request':copy.deepcopy(req),'images':copy.deepcopy(req['images']),'repair_error':error}
        raw=None
        try:
            raw=client.complete(prompt)
            try:
                response=json.loads(raw) if isinstance(raw,str) else raw
            except (ValueError,TypeError) as exc:
                raise O4Error('invalid_ast','malformed JSON') from exc
            validate_response(response,req)
            attempts.append({'valid':True,'raw_response':copy.deepcopy(raw)})
            return {'fake':True,'response':response,'attempts':attempts,'status':None}
        except O4Error as exc:
            error=exc.code
            attempt={'valid':False,'code':error}
            if 'raw' in locals():attempt['raw_response']=copy.deepcopy(raw)
            attempts.append(attempt)
            if error not in ('invalid_ast','invalid_binding'):break
        except (TimeoutError,OSError):
            attempts.append({'valid':False,'code':'provider_error'});break
    return {'fake':True,'response':None,'attempts':attempts,'status':attempts[-1]['code']}
