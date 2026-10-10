"""Ollama 출력 조각을 보존하고 수신 활동을 진행 화면에 알린다."""
import json
import time


async def stream_chat(http, payload, activity=None):
    # 캐시 키와 보존 요청은 그대로 두고 전송 방식만 스트리밍으로 바꾼다.
    parts, final, size, last_update = [], {}, 0, 0.0
    async with http.stream('POST', '/api/chat', json={**payload, 'stream': True}) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get('error'):
                raise ValueError('Ollama stream error')
            content = row.get('message', {}).get('content', '')
            parts.append(content)
            size += len(content)
            now = time.monotonic()
            if activity and (now - last_update >= 1 or row.get('done')):
                activity({'received_chars': size, 'last_received_at': now})
                last_update = now
            final = row
    return {**final, 'message': {**final.get('message', {}), 'content': ''.join(parts)}}
