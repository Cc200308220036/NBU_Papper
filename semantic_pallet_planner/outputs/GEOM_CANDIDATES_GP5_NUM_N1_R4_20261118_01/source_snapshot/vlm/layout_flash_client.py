"""Uncached text-only transport retaining the provider response for layout audits.

Kept separate from the frozen historical DeepSeek adapter.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .deepseek_client import DeepSeekClientError


class LayoutFlashClient:
    provider = 'deepseek'
    base_url = 'https://api.deepseek.com/chat/completions'

    def complete(self, request):
        key = os.environ.get('DEEPSEEK_API_KEY')
        if not key:
            raise DeepSeekClientError('missing_api_key', 'DEEPSEEK_API_KEY not configured')
        if request.image_paths:
            raise ValueError('layout policy validation is text-only')
        body = self.body(request)
        call = urllib.request.Request(self.base_url, data=json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+key}, method='POST')
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(call, timeout=request.timeout_s) as response:
                payload = json.load(response)
        except TimeoutError as exc:
            raise DeepSeekClientError('timeout', 'request timed out') from exc
        except urllib.error.HTTPError as exc:
            # Do not persist provider error bodies, which may echo credentials.
            raise DeepSeekClientError('provider_error', 'HTTP '+str(exc.code)) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DeepSeekClientError('transport_error', 'network request failed') from exc
        except (ValueError, TypeError) as exc:
            raise DeepSeekClientError('provider_error', 'non-JSON provider response') from exc
        return {'provider_payload': payload, 'latency_s': time.perf_counter()-started,
                'cache_hit': False}

    @staticmethod
    def body(request):
        return {'model': request.model, 'messages': [
            {'role': 'system', 'content': request.system_prompt},
            {'role': 'user', 'content': [{'type': 'text', 'text': request.user_text}]}],
            'temperature': request.temperature, 'max_tokens': request.max_output_tokens,
            'response_format': {'type': 'json_object'}, 'thinking': {'type': 'disabled'}, 'stream': False}
