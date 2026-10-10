import copy

from test_reliability_report import inputs

from app.claims.source_analysis_input import verification_input
from app.collection.collection_export import collection_export
from app.scenarios.scenario_checks import check_scenario


def fixture():
    collection, analysis, _ = inputs()
    for document in collection['output']['documents']:
        document['credibility_weight'] = next(d['weight'] for d in analysis['docs'] if d['id'] == document['doc_id'])
    collection['output']['by_country'] = {d['country']: [d] for d in collection['output']['documents']}
    collection['timings'] = {'total_seconds': 30.0}
    analysis['timings'] = {'total_seconds': 50.0}
    return collection, collection_export(collection), verification_input(analysis), analysis


def test_scenario_records_actual_counts_and_limits_without_assuming_fixed_article_count():
    job, collected, verified, analysis = fixture()
    checks = check_scenario(job, collected, verified, analysis)
    assert checks['all_checks_passed']
    assert checks['counts']['collected_articles'] == checks['counts']['representative_claims'] == 2
    assert checks['timings']['through_verification_input_seconds'] == 80
    assert checks['report_status'] == 'awaiting_current_reliability_result'


def test_modified_reciprocal_sim_or_duplicate_representative_is_detected():
    job, collected, verified, analysis = fixture()
    changed = copy.deepcopy(verified)
    changed['docs'][0]['sim']['b'] = 0.9
    checks = check_scenario(job, collected, changed, analysis)
    assert not checks['all_checks_passed'] and not checks['checks']['sim_reciprocal_and_finite']
    changed = copy.deepcopy(verified)
    changed['claims'].append(copy.deepcopy(changed['claims'][0]))
    checks = check_scenario(job, collected, changed, analysis)
    assert not checks['checks']['representative_max_one_per_article']
