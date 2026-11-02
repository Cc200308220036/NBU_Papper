import urllib.error
import pytest
from semantic_pallet_planner.jev_select.config import load_v3_config
from semantic_pallet_planner.jev_select.contracts import canonical
from semantic_pallet_planner.jev_select.transport import JevTransport


@pytest.mark.parametrize('stage',['connection_and_headers','response_read'])
def test_error_stage_is_observable_and_exception_text_is_not_logged(monkeypatch,stage):
    cfg=load_v3_config();monkeypatch.setenv(cfg['api_key_env'],'fixture-secret-do-not-log')
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,size):raise TimeoutError('fixture-secret-do-not-log')
    class Opener:
        def open(self,*a,**k):
            if stage=='connection_and_headers':raise urllib.error.URLError(TimeoutError('fixture-secret-do-not-log'))
            return Response()
    monkeypatch.setattr('urllib.request.build_opener',lambda *a:Opener())
    value=JevTransport(cfg).complete({'model':cfg['model'],'state':{},'questions':{}})
    assert value['status']=='UNKNOWN_IN_FLIGHT' and value['error_stage']==stage
    assert value['error_code']=='TIMEOUT' and value['stage_timings']
    assert 'fixture-secret-do-not-log' not in canonical(value)
