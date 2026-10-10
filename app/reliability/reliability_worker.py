"""서버 설정에 지정된 로컬 Python 함수만 별도 프로세스에서 호출한다."""

import argparse
import asyncio
import importlib
import importlib.util
import inspect
import json
import sys
from pathlib import Path

from app.core.json_io import save_json


async def invoke(target, input_path, input_mode):
    module_name, separator, function_name = target.rpartition(':')
    if not separator or not function_name.isidentifier():
        raise ValueError('신뢰도 함수 설정은 module:함수명 또는 파일.py:함수명이어야 합니다.')
    if module_name.endswith('.py'):
        path = Path(module_name).resolve(strict=True)
        spec = importlib.util.spec_from_file_location('skytrace_local_reliability', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_name)
    function = getattr(module, function_name)
    payload = str(input_path.resolve()) if input_mode == 'path' else json.loads(input_path.read_text(encoding='utf-8'))
    result = function(payload)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, str):
        result = json.loads(result)
    if not isinstance(result, dict):
        raise ValueError('신뢰도 함수는 JSON 객체(dict)를 반환해야 합니다.')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--function', required=True)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--input-mode', choices=['dict', 'path'], default='dict')
    args = parser.parse_args()
    result = asyncio.run(invoke(args.function, args.input, args.input_mode))
    save_json(args.output, result)


if __name__ == '__main__':
    main()
