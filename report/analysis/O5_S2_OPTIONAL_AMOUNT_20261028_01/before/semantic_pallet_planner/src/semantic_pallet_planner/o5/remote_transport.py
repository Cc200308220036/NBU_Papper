"""Unverified generic chat-completions adapter; one HTTP POST, no redirects/retries."""
import base64
import copy
import json
import os
import time
import urllib.error
import urllib.request
from .common import O5Error, canonical, digest
from .public_request import envelope
from .remote_config import require_cost, charge


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class HTTPWire:
    test_double = False

    def post(self, endpoint, body, credential, timeout):
        request = urllib.request.Request(endpoint, data=canonical(body).encode(), method='POST',
                                         headers={'Content-Type':'application/json', 'Authorization':'Bearer '+credential})
        # No SDK, redirect, proxy discovery, authentication challenge handler or retry middleware.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()


def prepare_body(req, directory, physical, profile, repair=None):
    require_cost(profile)
    body = envelope(req, directory, physical, repair)
    body.update(model=profile['model'], temperature=profile['temperature'])
    if profile['seed'] is not None:
        body['seed'] = profile['seed']
    # Count all message text, including system/repair, not base64 as text tokens.
    text_bytes = 0
    images = []
    for message in body['messages']:
        content = message['content']
        if isinstance(content, str):
            text_bytes += len(content.encode())
        else:
            for part in content:
                if part['type'] == 'text':
                    text_bytes += len(part['text'].encode())
                else:
                    data = base64.b64decode(part['image_url']['url'].split(',')[1], validate=True)
                    import hashlib
                    images.append(hashlib.sha256(data).hexdigest())
    if len(images) != 2 or images != [asset['sha256'] for asset in req['images']]:
        raise O5Error('IMAGE_TRANSMISSION_BINDING_FAILED')
    bound = text_bytes + profile['token_bound']['framing_tokens'] + 2*profile['token_bound']['per_image_tokens']
    if bound > profile['input_limit']:
        raise O5Error('INPUT_BOUND_EXCEEDED')
    if len(canonical(body).encode()) > profile['max_request_bytes']:
        raise O5Error('REQUEST_TOO_LARGE')
    return body, {'input_upper':bound, 'output_upper':256, 'image_sha256':images,
                  'algorithm':profile['token_bound']['algorithm'],
                  'bound_evidence':profile['token_bound']['evidence'], 'body_digest':digest(body),
                  'maximum_amount':charge(profile,bound,256)}


class ChatHTTPTransport:
    def __init__(self, profile, wire=None):
        require_cost(profile)
        self.profile = copy.deepcopy(profile)
        self.wire = wire if wire is not None else HTTPWire()
        self.test_double = self.wire.test_double
        self.calls = 0

    def precheck(self):
        if not self.test_double and not os.environ.get(self.profile['credential_env']):
            raise O5Error('MISSING_CREDENTIAL')

    def complete(self, body):
        self.precheck()
        credential = 'OFFLINE_HTTP_FIXTURE' if self.test_double else os.environ[self.profile['credential_env']]
        start = time.perf_counter()
        self.calls += 1
        # No exception details/headers are persisted: they can contain credentials.
        status, headers, raw = self.wire.post(self.profile['endpoint'], body, credential, self.profile['timeout_seconds'])
        text = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
        if not isinstance(text, str):
            raise O5Error('INVALID_WIRE_RESPONSE')
        text = text.replace(credential, '[REDACTED_CREDENTIAL]')
        lowered = {k.lower():str(v).replace(credential,'[REDACTED_CREDENTIAL]') for k,v in headers.items()}
        result = {'schema_version':'o5_s2_transport_result_v1', 'http_status':status,
                  'provider_request_id':lowered.get('x-request-id'), 'raw_body':text,
                  'model':None, 'finish_reason':None, 'text':None, 'usage':None,
                  'error':None, 'latency_seconds':time.perf_counter()-start}
        if status != 200:
            result['error'] = 'SYSTEM_HTTP_'+str(status) if 300<=status<400 or status in (401,403,404,429) else 'HTTP_'+str(status)
            return result
        try:
            data = json.loads(text)
            result['model'] = data.get('model')
            result['usage'] = data.get('usage')
            if result['provider_request_id'] is None:
                result['provider_request_id'] = data.get('id')
            choices = data['choices']
            choice = choices[0]
            result['finish_reason'] = choice.get('finish_reason')
            message = choice['message']
            if result['model'] != self.profile['returned_model']:
                result['error'] = 'SYSTEM_MODEL_DRIFT'
            elif len(choices) != 1 or message.get('refusal') or message.get('tool_calls'):
                result['error'] = 'MODEL_REFUSAL_OR_TOOL_OUTPUT'
            elif choice.get('finish_reason') != 'stop':
                result['error'] = 'MODEL_TRUNCATED_OR_UNEXPECTED_FINISH'
            elif not isinstance(message.get('content'), str) or not message['content'].strip():
                result['error'] = 'EMPTY_MODEL_OUTPUT'
            else:
                result['text'] = message['content']
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            result['error'] = 'MALFORMED_PROVIDER_RESPONSE'
        return result
