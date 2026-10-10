import asyncio
import json

import pytest
from test_reliability_report import Model, inputs

from app.claims.source_analysis_input import verification_input
from app.cli.analyze_collection import save_json
from app.config import Settings
from app.core.errors import AnalysisError
from app.reporting.reliability_report import generate_report
from app.scenarios.reliability_scenario import complete_scenario


def prepare(tmp_path, monkeypatch):
    directory = tmp_path / 'scenario'
    collection, analysis, _ = inputs()
    save_json(directory / 'collection-run.json', {'id': 'actual-run', 'status': 'completed'})
    save_json(directory / 'collective_live.json', collection)
    save_json(directory / 'all-collected_verification-input-details.json', {'result': analysis})
    save_json(directory / 'all-collected_verification-input.json', verification_input(analysis))
    save_json(directory / 'scenario-checks.json', {'all_checks_passed': True,
        'counts': {'collected_articles': 2}, 'timings': {'through_verification_input_seconds': 1}})

    async def create(settings, packet, trace):
        return await generate_report(Model(), 'fixture', packet, trace)

    monkeypatch.setattr('app.scenarios.reliability_scenario.create_report', create)
    return directory, Settings(database=tmp_path / 'app.db',
                               reliability_function='analysis.reliability:run')


def test_actual_develop_function_is_saved_with_full_calculation_and_unapproved_report(tmp_path, monkeypatch):
    directory, settings = prepare(tmp_path, monkeypatch)
    summary = asyncio.run(complete_scenario(directory, settings))
    load = lambda name: json.loads((directory / name).read_text(encoding='utf-8'))  # noqa: E731
    result, full, report = load('reliability-result.json'), load('reliability-result-full.json'), load('report.json')
    assert [claim['reliability'] for claim in result['claims']] == [0.4, 0.4]
    assert all(claim['label'] == '판단 보류' for claim in result['claims'])
    assert result['thresholds'] == {'low': 0.6, 'high': 0.7}
    assert result['input_sha256'] == report['input_sha256']
    assert full['claims'] == result['claims']
    assert full['countries']['CN']['u'] == 1 and len(full['documents']) == 2
    assert all(claim['label'] == '판단 보류' for claim in report['evidence'])
    assert report['status'] == 'draft' and report['audit'] == []
    assert summary['all_checks_passed'] and summary['labels_returned'] == {'판단 보류': 2}
    assert (directory / 'report.md').is_file()
    assert (settings.database.parent / 'reliability-reports' / 'actual-run.json').is_file()


def test_modified_verification_file_is_rejected_before_function_or_model(tmp_path, monkeypatch):
    directory, settings = prepare(tmp_path, monkeypatch)
    path = directory / 'all-collected_verification-input.json'
    value = json.loads(path.read_text(encoding='utf-8'))
    value['docs'][0]['weight'] = 0.99
    save_json(path, value)
    with pytest.raises(AnalysisError, match='분석 상세 기록'):
        asyncio.run(complete_scenario(directory, settings))
    assert not (directory / 'reliability-result.json').exists()
    assert not (directory / 'report.json').exists()
