"""Cache completed report drafts by evidence, scores and policy, not collection IDs."""

import copy
import re

from app.core.paths import PROMPTS

GENERATED = ('sections', 'excluded_statements', 'proposed_comparisons',
             'report_review', 'comparison_policy')
ID_FIELDS = {'id', 'claim_id', 'claim_ids', 'document_id', 'paragraph_id',
             'documents_without_claims', 'missing_scores', 'platform_document_ids'}


def bind_ids(value, mapping, field=''):
    if isinstance(value, list):
        return [bind_ids(item, mapping, field) for item in value]
    if isinstance(value, dict):
        return {(mapping.get(key, key) if field == 'sim' else key): bind_ids(item, mapping, key)
                for key, item in value.items()}
    if not isinstance(value, str):
        return value
    if field in ID_FIELDS:
        return mapping.get(value, value)
    if field in {'warnings', 'additional_warnings', 'text', 'reason'} and mapping:
        pattern = r'(?<![\w-])(?:' + '|'.join(re.escape(key) for key in sorted(mapping, key=len, reverse=True)) + r')(?![\w-])'
        return re.sub(pattern, lambda match: mapping[match.group()], value)
    return value  # Quotes, source names, question and URLs are never rewritten.


def report_cache_identity(client, model, packet):
    mapping = {doc['id']: f'__document_{i}__' for i, doc in enumerate(packet['docs'])}
    for i, claim in enumerate(packet['evidence']):
        mapping[claim['claim_id']] = f'__claim_{i}__'
        mapping[claim['paragraph_id']] = f'__paragraph_{i}__'
    content = {key: value for key, value in packet.items() if key != 'input_sha256'}
    key = {'verified_report_version': 1, 'model': model,
           'force_cpu': getattr(client, 'force_cpu', False),
           'packet': bind_ids(content, mapping),
           'prompts': {name: (PROMPTS / name).read_text(encoding='utf-8') for name in (
               'source_reliability_report.txt', 'source_report_review.txt')}}
    return key, mapping


def store_report_draft(client, model, packet, report, trace):
    cache = getattr(client, 'cache', None)
    if cache is None or report.get('status') != 'draft' or report.get('audit'):
        return
    if report.get('input_sha256') != packet['input_sha256']:
        return
    if report['warnings'][:len(packet['warnings'])] != packet['warnings']:
        return
    key, mapping = report_cache_identity(client, model, packet)
    generated = {field: report[field] for field in GENERATED}
    generated['additional_warnings'] = report['warnings'][len(packet['warnings']):]
    cache.write(key, {'generated': bind_ids(generated, mapping), 'validation_history': trace})


def read_report_draft(client, model, packet, draft_schema, review_schema):
    cache = getattr(client, 'cache', None)
    if cache is None:
        return None
    key, mapping = report_cache_identity(client, model, packet)
    raw = cache.read(key)
    if not isinstance(raw, dict) or not raw.get('validation_history'):
        return None
    try:
        generated = bind_ids(raw['generated'], {v: k for k, v in mapping.items()})
        sections = copy.deepcopy(generated['sections'])
        for item in generated['proposed_comparisons']:
            if item['section'] not in {'common_facts', 'conflicting_candidates'}:
                return None
            sections[item['section']].append({k: item[k] for k in ('text', 'claim_ids')})
        draft_schema.model_validate(sections)
        review_schema.model_validate(generated['report_review'])
        ids = {claim['claim_id'] for claim in packet['evidence']}
        if any(not set(item['claim_ids']) <= ids or len(set(item['claim_ids'])) != len(item['claim_ids'])
               for items in sections.values() for item in items):
            return None
        if generated['sections']['common_facts'] or generated['sections']['conflicting_candidates']:
            return None  # A cached draft never bypasses human comparison approval.
        if generated['comparison_policy'] != 'human_selection_required':
            return None
        return generated, raw['validation_history']
    except (ValueError, KeyError, TypeError):
        return None
