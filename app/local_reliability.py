"""현재 docs·대표 claims를 그대로 로컬 검증 함수에 전달한다."""

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from .analyze_collection import save_json
from .errors import AnalysisError
from .reliability_report import ReliabilityResponse, input_digest
from .source_analysis_input import verification_input


async def verify_locally(settings, rid, analysis):
    if not settings.reliability_function:
        raise AnalysisError('SKYTRACE_RELIABILITY_FUNCTION에 실제 로컬 함수의 파일·이름을 설정하세요.')
    directory = settings.database.parent / 'reliability-calls' / rid / uuid4().hex
    directory.mkdir(parents=True)
    source, output = directory / 'input.json', directory / 'result.json'
    digest = input_digest(analysis)
    save_json(source, verification_input(analysis))
    # shell 문자열로 조합하지 않는다. 함수 설정은 서버 .env에서만 읽는다.
    with (directory / 'worker.log').open('wb') as log:
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'app.reliability_worker',
            '--function', settings.reliability_function, '--input', str(source.resolve()),
            '--output', str(output.resolve()), '--input-mode', settings.reliability_input_mode,
            cwd=Path(__file__).resolve().parent.parent, stdout=log, stderr=log)
        try:
            await asyncio.wait_for(process.wait(), settings.reliability_timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            if process.returncode is None:
                process.kill()
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise AnalysisError('신뢰도 함수 제한 시간을 초과해 종료했습니다. 호출 기록을 확인하세요.') from None
    if process.returncode != 0 or not output.is_file():
        raise AnalysisError('로컬 신뢰도 함수 실행에 실패했습니다. reliability-calls 호출 기록을 확인하세요.')
    if output.stat().st_size > 2_000_000:
        raise AnalysisError('신뢰도 함수 결과가 허용 크기를 초과했습니다.')
    try:
        response = ReliabilityResponse.model_validate(json.loads(output.read_text(encoding='utf-8-sig')))
    except (ValueError, ValidationError):
        raise AnalysisError('신뢰도 함수 반환 JSON의 주장·점수 명세가 맞지 않습니다.') from None
    # 직접 넘긴 입력의 해시를 호출 기록에 보존한다. 함수가 반환한 해시는 이후 대조한다.
    save_json(directory / 'binding.json', {'input_sha256': digest, 'input_mode': settings.reliability_input_mode})
    if response.input_sha256 is None:
        response = response.model_copy(update={'input_sha256': digest})
    return response
