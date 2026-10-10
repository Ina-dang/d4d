"""동일 모델·프롬프트·입력의 완료 응답만 재사용하는 로컬 캐시."""

import hashlib
import json
from uuid import uuid4


class AnalysisCache:
    def __init__(self, directory, model_digest):
        self.directory = directory
        self.model_digest = model_digest

    def path(self, payload):
        key = json.dumps({'digest': self.model_digest, 'request': payload},
                         sort_keys=True, ensure_ascii=False)
        return self.directory / (hashlib.sha256(key.encode('utf-8')).hexdigest() + '.json')

    def read(self, payload):
        try:
            raw = json.loads(self.path(payload).read_text(encoding='utf-8'))
            return raw if isinstance(raw, dict) else None
        except (OSError, ValueError):
            return None

    def write(self, payload, raw):
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.path(payload)
            temporary = target.with_suffix(f'.{uuid4().hex}.tmp')
            temporary.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
            temporary.replace(target)
        except OSError:
            # 캐시 저장 문제로 이미 완료된 분석을 실패시키지 않는다.
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
