import asyncio
import json

import pytest
from test_reliability_report import inputs

from app.claims.source_analysis_input import verification_input
from app.config import Settings
from app.core.errors import AnalysisError
from app.reliability.local_reliability import verify_locally
from app.reliability.reliability_worker import invoke
from app.reporting.reliability_report import input_digest


@pytest.mark.parametrize('mode,asynchronous', [('dict', False), ('path', False), ('dict', True)])
def test_configured_python_function_receives_exact_contract_in_isolated_process(tmp_path, mode, asynchronous):
    _, analysis, _ = inputs()
    module = tmp_path / 'fixture_verification.py'
    payload = "json.loads(Path(payload).read_text(encoding='utf-8'))" if mode == 'path' else 'payload'
    # 이 점수는 테스트 fixture에서만 생성하며 실제 시나리오에는 사용하지 않는다.
    module.write_text("import json\nfrom pathlib import Path\n" + ('async ' if asynchronous else '') +
        "def verify(payload):\n" + f"    data = {payload}\n" +
        "    assert set(data) == {'docs', 'claims'}\n" +
        "    assert all(isinstance(d['sim'], dict) for d in data['docs'])\n" +
        "    return {'claims': [{**c, 'reliability': 0.6, 'label': '테스트'} for c in data['claims']]}\n",
        encoding='utf-8')
    settings = Settings(database=tmp_path / 'test.db', reliability_function=f'{module}:verify',
                        reliability_input_mode=mode)
    response = asyncio.run(verify_locally(settings, 'abc', analysis))
    assert response.input_sha256 == input_digest(analysis)
    folders = list((tmp_path / 'reliability-calls' / 'abc').iterdir())
    assert json.loads((folders[0] / 'input.json').read_text(encoding='utf-8')) == verification_input(analysis)
    assert len(response.claims) == 2


def test_stalled_function_is_terminated_without_fabricated_result(tmp_path):
    _, analysis, _ = inputs()
    module = tmp_path / 'fixture_stall.py'
    module.write_text('import time\ndef verify(payload):\n    time.sleep(60)\n', encoding='utf-8')
    settings = Settings(database=tmp_path / 'test.db', reliability_function=f'{module}:verify', reliability_timeout=1)
    with pytest.raises(AnalysisError, match='제한 시간'):
        asyncio.run(verify_locally(settings, 'abc', analysis))
    assert not list((tmp_path / 'reliability-calls').rglob('result.json'))


def test_function_config_cannot_be_client_code_or_invalid_return(tmp_path):
    path = tmp_path / 'input.json'
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='설정'):
        asyncio.run(invoke('exec(1)', path, 'dict'))
    module = tmp_path / 'bad_return.py'
    module.write_text('def verify(payload):\n    return 0.9\n', encoding='utf-8')
    with pytest.raises(ValueError, match='객체'):
        asyncio.run(invoke(f'{module}:verify', path, 'dict'))
