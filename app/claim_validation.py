"""잘못된 주장만 재추출하고 원문 인용·번역 의미를 확인한 뒤 반환한다."""
import asyncio
import json
import time
from typing import Literal

from pydantic import Field, ValidationError

from .errors import AnalysisError
from .source_analysis import (
    PROMPTS,
    QUOTE_CHARS,
    ClaimDraft,
    Extraction,
    Schema,
    cache_verified,
    generate,
    request,
)
from .source_dates import explicit_date
from .source_quotes import restore_markdown_quote, restore_transcript_quote
from .source_selection import SourceSelections, selected_claim, source_candidates
from .source_translation import KoreanTranslations

MAX_REPAIRS = 2
REVIEW_CHARS = 18000
Issue = Literal['quote_mismatch', 'translation_not_korean', 'subject', 'time', 'negation',
                'modality', 'numbers', 'scope', 'conditions', 'attribution', 'event_date',
                'same_claim', 'uncertain']


class MeaningCheck(Schema):
    claim_index: int = Field(ge=1, le=12, strict=True)
    verdict: Literal['pass', 'fail', 'uncertain']
    issues: list[Issue] = Field(max_length=13)


class MeaningChecks(Schema):
    checks: list[MeaningCheck] = Field(min_length=1, max_length=12)


class Correction(Schema):
    claim_index: int = Field(ge=1, le=12, strict=True)
    claim: ClaimDraft | None


class Corrections(Schema):
    corrections: list[Correction] = Field(min_length=1, max_length=12)


class VerifiedBlock(Schema):
    extraction: Extraction
    repair_count: int = Field(ge=0, le=MAX_REPAIRS, strict=True)
    validation_trace: list[dict] = Field(min_length=1)


def verified_cache_key(payload, block):
    return {'verified_extraction_version': 2, 'request': payload, 'paragraphs': block,
            'verification_prompts': {name: (PROMPTS / name).read_text(encoding='utf8')
                for name in ('source_meaning_check.txt', 'source_claim_repair.txt',
                             'source_select_quote.txt', 'source_translate.txt')}}


def cached_verified_block(raw, block):
    try:
        saved = VerifiedBlock.model_validate(raw)
    except ValidationError:
        return None
    for claim in saved.extraction.claims:
        if not any(p['paragraph_id'] == claim.paragraph_id and claim.original_quote in p['raw_text']
                   for p in block):
            return None
        if not any('\uac00' <= c <= '\ud7a3' for c in claim.translated_quote):
            return None
        if claim.event_date and not explicit_date(claim.original_quote, claim.event_date):
            return None
    return saved


def batches(base, key, items):
    """전체 문맥은 유지하고 검증·수정할 주장 목록만 크기별로 나눈다."""
    batch = []
    for item in items:
        if len(json.dumps({**base, key: [item]}, ensure_ascii=False)) > REVIEW_CHARS:
            raise AnalysisError('원문·번역 검증 입력 한도를 초과했습니다. 유사도를 산출하지 않습니다.')
        if batch and len(json.dumps({**base, key: [*batch, item]}, ensure_ascii=False)) > REVIEW_CHARS:
            yield {**base, key: batch}
            batch = []
        batch.append(item)
    if batch:
        yield {**base, key: batch}


def exact_indices(items, expected):
    indices = [item.claim_index for item in items]
    if len(indices) != len(set(indices)) or set(indices) != set(expected):
        raise AnalysisError('주장 검증·재추출 응답에 누락·중복 또는 요청하지 않은 주장 번호가 있습니다.')


async def verified_extraction(client, model, payload, block, trace, notify, transcript=False):
    started = time.perf_counter()
    trace_start = len(trace)
    cache = getattr(client, 'cache', None)
    cache_key = verified_cache_key(payload, block) if cache is not None else None
    saved = cached_verified_block(cache.read(cache_key), block) if cache is not None else None
    if saved is not None:
        # This is the validated pipeline result, not an invented raw model response.
        trace.append({'request': payload, 'response': None, 'phase': 'extraction',
                      'cache_hit': True, 'cache_kind': 'verified_block',
                      'validated_result': saved.extraction.model_dump(mode='json'),
                      'validation_history': saved.validation_trace,
                      'elapsed_seconds': round(time.perf_counter() - started, 3)})
        return saved.extraction, saved.repair_count
    source = json.loads(payload['messages'][1]['content'])
    initial = await generate(client, Extraction, payload, trace)
    initial_record = trace[-1]
    drafts = dict(enumerate(initial.claims, 1))
    originals = drafts.copy()
    origins = {index: initial_record for index in drafts}
    verified = set()
    unavailable = set()
    repairs = []
    for attempt in range(MAX_REPAIRS + 1):
        failures = {}
        for index, claim in drafts.items():
            if index in verified:
                continue
            if index in unavailable:
                failures[index] = ['uncertain']
                continue
            issues = []
            if claim.event_date and not explicit_date(claim.original_quote, claim.event_date):
                origins[index].setdefault('date_normalizations', []).append({
                    'claim_index': index, 'model_date': claim.event_date.isoformat(),
                    'reason': 'complete_date_not_explicit_in_quote'})
                claim = claim.model_copy(update={'event_date': None})
                drafts[index] = claim
            paragraph = next((p for p in block if p['paragraph_id'] == claim.paragraph_id), None)
            if paragraph and claim.original_quote not in paragraph['raw_text']:
                method = 'exact_markdown_label_match'
                restored = restore_markdown_quote(paragraph['raw_text'], claim.original_quote)
                if not restored and transcript:
                    restored = restore_transcript_quote(paragraph['raw_text'], claim.original_quote)
                    method = 'exact_transcript_text_match'
                if restored and len(restored) <= QUOTE_CHARS:
                    origins[index].setdefault('quote_restorations', []).append({
                        'claim_index': index, 'paragraph_id': claim.paragraph_id,
                        'method': method,
                        'model_quote': claim.original_quote, 'original_quote': restored})
                    claim = claim.model_copy(update={'original_quote': restored})
                    drafts[index] = claim
            if not any(p['paragraph_id'] == claim.paragraph_id
                       and claim.original_quote in p['raw_text'] for p in block):
                issues.append('quote_mismatch')
            if not any('\uac00' <= char <= '\ud7a3' for char in claim.translated_quote):
                issues.append('translation_not_korean')
            if issues:
                failures[index] = issues
                origins[index].setdefault('validation_errors', []).append({
                    'document_id': source.get('document_id'),
                    'claim_index': index, 'paragraph_id': claim.paragraph_id,
                    'reason': 'quote_not_in_paragraph' if 'quote_mismatch' in issues
                    else 'translation_not_korean', 'issues': issues})

        review = [{'claim_index': i, 'claim': c.model_dump(mode='json'),
                   'repair_target': originals[i].model_dump(mode='json') if attempt else None}
                  for i, c in drafts.items() if i not in verified and i not in failures]
        if review:
            notify('원문·번역 의미 검증 중')
        for data in batches({'operation': 'verify_translation', 'paragraphs': block}, 'claims', review):
            review_payload = request(model, MeaningChecks, 'source_meaning_check.txt', data)
            # Bind the generation grammar to this batch, so the model cannot stop after
            # checking only one claim. exact_indices still rejects duplicated IDs.
            expected_indices = [item['claim_index'] for item in data['claims']]
            review_payload['format']['properties']['checks'].update(
                minItems=len(expected_indices), maxItems=len(expected_indices))
            review_payload['format']['$defs']['MeaningCheck']['properties']['claim_index'][
                'enum'] = expected_indices
            checked = await generate(client, MeaningChecks, review_payload, trace)
            exact_indices(checked.checks, expected_indices)
            for check in checked.checks:
                if check.verdict == 'pass' and not check.issues:
                    verified.add(check.claim_index)
                else:
                    failures[check.claim_index] = check.issues or ['uncertain']
                    trace[-1].setdefault('validation_errors', []).append({
                        'document_id': source.get('document_id'),
                        'claim_index': check.claim_index, 'reason': 'meaning_not_preserved',
                        'verdict': check.verdict, 'issues': failures[check.claim_index]})
            if all(check.verdict == 'pass' and not check.issues for check in checked.checks):
                cache_verified(client, review_payload, trace)

        if not failures:
            if not attempt:
                cache_verified(client, payload, [initial_record])
            for repair_payload, record, corrected in repairs:
                # 나중에 다시 수정된 응답 또는 미확인 주장은 캐시에 저장하지 않는다.
                if all(i in verified and drafts[i] == c for i, c in corrected.items()):
                    cache_verified(client, repair_payload, [record])
            result = Extraction(claims=list(drafts.values()))
            if cache is not None:
                cache.write(cache_key, VerifiedBlock(extraction=result, repair_count=attempt,
                    validation_trace=trace[trace_start:]).model_dump(mode='json'))
            return result, attempt
        if attempt == MAX_REPAIRS:
            raise AnalysisError(f'원문 인용·번역 의미가 {MAX_REPAIRS}회 재추출 후에도 '
                                '확인되지 않았습니다. 해당 근거를 빼고 유사도를 산출하지 않습니다.')

        notify(f'인용·번역 재추출 중 · {attempt + 1}/{MAX_REPAIRS}회')
        failed = [{'claim_index': i, 'draft': drafts[i].model_dump(mode='json'),
                   'original_target': originals[i].model_dump(mode='json'),
                   'issues': issues} for i, issues in failures.items()]
        base = {'operation': 'repair_claims', 'paragraphs': block,
                'question': source['question']}
        selection_items, copying_items, translation_items = [], [], []
        for item in failed:
            if item['issues'] == ['translation_not_korean']:
                translation_items.append({'claim_index': item['claim_index'],
                                          'source_quote': item['draft']['original_quote']})
                continue
            candidates = await asyncio.to_thread(source_candidates, block, item['draft']['original_quote']) if (
                'quote_mismatch' in item['issues']) else []
            if candidates:
                selection_items.append({**item, 'candidates': candidates})
            else:
                copying_items.append(item)
        requests = [
            (Corrections, 'source_claim_repair.txt', data)
            for data in batches(base, 'failed_claims', copying_items)]
        requests.extend((SourceSelections, 'source_select_quote.txt', data) for data in batches(
            {**base, 'operation': 'select_source_quote'}, 'failed_claims', selection_items))
        requests.extend((KoreanTranslations, 'source_translate.txt', data) for data in batches(
            # Give the translator only the exact, already restored quotes. Supplying
            # the full paragraph caused it to continue beyond the requested excerpt.
            # The subsequent meaning check still receives the full source context.
            {'operation': 'translate_claims'}, 'quotes', translation_items))
        for schema, prompt, data in requests:
            repair_payload = request(model, schema, prompt, data)
            corrected = await generate(client, schema, repair_payload, trace)
            record = trace[-1]
            if schema is KoreanTranslations:
                exact_indices(corrected.translations, [c['claim_index'] for c in data['quotes']])
                corrected = Corrections(corrections=[Correction(claim_index=c.claim_index,
                    claim=drafts[c.claim_index].model_copy(update={'translated_quote': c.korean_text}))
                    for c in corrected.translations])
                data = {**data, 'failed_claims': data['quotes']}
            if schema is SourceSelections:
                exact_indices(corrected.selections, [c['claim_index'] for c in data['failed_claims']])
                candidates_by_index = {c['claim_index']: c['candidates'] for c in data['failed_claims']}
                corrected = Corrections(corrections=[Correction(claim_index=c.claim_index,
                    claim=selected_claim(c, candidates_by_index[c.claim_index]))
                    for c in corrected.selections])
            exact_indices(corrected.corrections, [item['claim_index'] for item in data['failed_claims']])
            corrected_claims = {}
            for item in corrected.corrections:
                verified.discard(item.claim_index)
                if item.claim is not None:
                    unavailable.discard(item.claim_index)
                    drafts[item.claim_index] = item.claim
                    origins[item.claim_index] = record
                    corrected_claims[item.claim_index] = item.claim
                else:
                    unavailable.add(item.claim_index)
                    record.setdefault('validation_errors', []).append({
                        'claim_index': item.claim_index, 'reason': 'repair_unavailable'})
            # null을 보낸 항목이 있는 응답도 캐시하지 않는다.
            if len(corrected_claims) == len(corrected.corrections):
                repairs.append((repair_payload, record, corrected_claims))
    raise AssertionError('unreachable')
