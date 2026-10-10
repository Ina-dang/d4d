"""Atomic JSON persistence shared by web jobs and command-line tools."""

import json
from uuid import uuid4


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f'.{uuid4().hex}.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                             encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
