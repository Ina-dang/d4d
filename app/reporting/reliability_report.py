"""신뢰도 반환값을 동일 실행의 근거와 연결해 인용을 가진 보고서 초안을 만든다."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, StrictInt

from app.claims.source_analysis import Schema, cache_verified, generate, request
from app.claims.source_analysis_input import CLAIM_FIELDS, analysis_input, verification_input
from app.core.analysis_timing import summarize_timings
from app.core.errors import AnalysisError

SECTION_TITLES = {'key_judgment': '핵심 판단', 'common_facts': '공통 사실 주장',
                  'conflicting_candidates': '상충 후보', 'source_interpretations': '출처별 해석',
                  'analysis_limits': '분석의 한계'}


class ReliabilityClaim(Schema):
    claim_id: str = Field(min_length=1, max_length=120)
    document_id: str = Field(min_length=1, max_length=120)
    tier: int = Field(strict=True, ge=1, le=3)
    event_date: str | None
    paragraph_id: str = Field(min_length=1, max_length=160)
    translated_quote: str = Field(min_length=1, max_length=1600)
    reliability: float | None = Field(strict=True, ge=0, le=1)
    label: str | None = Field(default=None, min_length=1, max_length=50)
    country: str | None = Field(default=None, min_length=1, max_length=20)


class ReliabilityResponse(Schema):
    claims: list[ReliabilityClaim] = Field(min_length=1, max_length=500)
    summary: dict[str, StrictInt] | None = None
    thresholds: dict[str, Annotated[float, Field(strict=True, ge=0, le=1)]] | None = None
    input_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class ReportRequest(Schema):
    reliability_result: ReliabilityResponse
    verification_input_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class Statement(Schema):
    text: str = Field(min_length=1, max_length=1000)
    claim_ids: list[str] = Field(max_length=8)


class GroundedStatement(Statement):
    claim_ids: list[str] = Field(min_length=1, max_length=8)


class ComparedStatement(Statement):
    claim_ids: list[str] = Field(min_length=2, max_length=8)


class ReportDraft(Schema):
    key_judgment: list[GroundedStatement] = Field(min_length=1, max_length=3)
    common_facts: list[ComparedStatement] = Field(max_length=4)
    conflicting_candidates: list[ComparedStatement] = Field(max_length=4)
    source_interpretations: list[GroundedStatement] = Field(max_length=5)
    analysis_limits: list[Statement] = Field(min_length=1, max_length=4)


class ReportCheck(Schema):
    item_id: str
    reason: str = Field(min_length=1, max_length=400)
    verdict: Literal['unsupported', 'uncertain', 'supported']


class ReportChecks(Schema):
    checks: list[ReportCheck]


async def check_report(client, model, context, sections, trace):
    statements = [{'item_id': f'{section}:{index}', 'section': section, **item}
                  for section, items in sections.items() for index, item in enumerate(items)]
    expected = {item['item_id'] for item in statements}
    evidence = {item['claim_id']: item for item in context['evidence']}
    critical = [item for item in statements if item['section'] in {'common_facts', 'conflicting_candidates'}]
    remaining = [item for item in statements if item not in critical]
    # 비교 관계는 같은 경량 모델의 반복 판단으로 확정하지 않는다.
    # 인용 쌍을 사람에게 제안하고, 나머지 문장만 작은 묶음으로 검토한다.
    groups = [remaining[i:i + 3] for i in range(0, len(remaining), 3)]
    all_checks = [ReportCheck(item_id=item['item_id'], verdict='uncertain',
        reason='공통·상충 관계는 사람의 인용 쌍 검토 전까지 LLM 제안으로 보류합니다.') for item in critical]
    for group in groups:
        review_context = {key: context[key] for key in ('question', 'analysis_scope', 'limitations', 'collection_coverage')}
        review_context['statements'] = [{**item, 'cited_evidence': [evidence[cid] for cid in item['claim_ids']]}
                                        for item in group]
        payload = request(model, ReportChecks, 'source_report_review.txt', review_context)
        payload['messages'][1]['content'] = json.dumps(review_context, ensure_ascii=False, separators=(',', ':'))
        payload['options'].update(num_ctx=8192, num_predict=512)
        if getattr(client, 'force_cpu', False):
            payload['options']['num_gpu'] = 0
        group_ids = {item['item_id'] for item in group}
        payload['format']['properties']['checks'].update(minItems=len(group_ids), maxItems=len(group_ids))
        payload['format']['$defs']['ReportCheck']['properties']['item_id']['enum'] = sorted(group_ids)
        group_result = await generate(client, ReportChecks, payload, trace)
        received_group = [item.item_id for item in group_result.checks]
        if len(received_group) != len(set(received_group)) or set(received_group) != group_ids:
            raise AnalysisError('보고서 근거 검토의 항목이 누락·중복·추가되었습니다.')
        cache_verified(client, payload, trace)
        all_checks.extend(group_result.checks)
    result = ReportChecks(checks=all_checks)
    received = [item.item_id for item in result.checks]
    if len(received) != len(set(received)) or set(received) != expected:
        raise AnalysisError('보고서 근거 검토의 항목이 누락·중복·추가되었습니다.')
    checked = {item.item_id: item for item in result.checks}
    retained = {section: [] for section in sections}
    excluded = []
    for item in statements:
        assessment = checked[item['item_id']]
        if item in critical or assessment.verdict == 'supported':
            retained[item['section']].append({key: item[key] for key in ('text', 'claim_ids')})
        else:
            excluded.append({**item, **assessment.model_dump()})
    if not retained['key_judgment']:
        raise AnalysisError('핵심 판단의 원문 근거를 확인하지 못했습니다. 초안을 사용하지 않습니다.')
    if not retained['analysis_limits']:
        retained['analysis_limits'] = [{'text': '자동 분석 초안으로 사람의 원문·번역 검토가 필요합니다.', 'claim_ids': []}]
    return retained, excluded, result.model_dump(mode='json')


def input_digest(analysis):
    encoded = json.dumps(verification_input(analysis), ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def report_evidence(collection, analysis, response, expected_digest=None):
    """반환 주장의 여섯 필드를 원래 검증 입력과 모두 대조한다."""
    fingerprint = input_digest(analysis)
    if expected_digest and expected_digest != fingerprint:
        raise AnalysisError('검증 입력이 변경됐습니다. 최신 JSON의 신뢰도 결과를 사용하세요.')
    if response.input_sha256 and response.input_sha256 != fingerprint:
        raise AnalysisError('신뢰도 응답의 입력 해시가 현재 검증 입력과 다릅니다.')
    question, documents = analysis_input(collection)
    source = {doc['doc_id']: doc for doc in documents}
    exported = verification_input(analysis)
    if set(source) != {doc['id'] for doc in exported['docs']} or (
            analysis.get('analysis_question') and analysis['analysis_question'] != question):
        raise AnalysisError('수집 문서·질문과 분석 결과가 같은 실행의 자료가 아닙니다.')
    expected = {claim['claim_id']: claim for claim in exported['claims']}
    originals = {claim['claim_id']: claim for claim in analysis['claims']}
    scored = {}
    for claim in response.claims:
        if claim.claim_id in scored:
            raise AnalysisError('신뢰도 응답에 중복 주장 ID가 있습니다.')
        if claim.claim_id not in expected:
            raise AnalysisError('신뢰도 응답에 현재 검증 입력에 없는 주장 ID가 있습니다.')
        received = claim.model_dump(mode='json', include=set(CLAIM_FIELDS))
        if received != expected[claim.claim_id]:
            raise AnalysisError('신뢰도 응답의 문서·인용·날짜·근거가 현재 입력과 다릅니다.')
        if claim.country is not None and claim.country != source[claim.document_id].get('country'):
            raise AnalysisError('신뢰도 응답의 출처 국가가 수집 메타데이터와 다릅니다.')
        scored[claim.claim_id] = claim
    if response.summary is not None:
        if any(claim.label is None for claim in response.claims):
            raise AnalysisError('라벨이 없는 신뢰도 응답에는 라벨별 summary를 사용할 수 없습니다.')
        counts = {}
        for claim in response.claims:
            counts[claim.label] = counts.get(claim.label, 0) + 1
        if any(value < 0 for value in response.summary.values()) or any(
                response.summary.get(label, 0) != count for label, count in counts.items()) or any(
                value != counts.get(label, 0) for label, value in response.summary.items()):
            raise AnalysisError('신뢰도 응답 summary가 실제 주장 라벨 개수와 다릅니다.')
    if response.thresholds is not None:
        low, high = response.thresholds.get('low'), response.thresholds.get('high')
        if (low is None or high is None or not 0 <= low < high <= 1):
            raise AnalysisError('신뢰도 임계값 low·high의 범위나 순서가 올바르지 않습니다.')
    evidence = []
    for claim in exported['claims']:
        did, cid = claim['document_id'], claim['claim_id']
        document = source.get(did)
        if document is None:
            raise AnalysisError('보고서 출처를 수집 결과에서 찾지 못했습니다.')
        original = originals[cid]
        if not any(p['paragraph_id'] == claim['paragraph_id']
                   and original['original_quote'] in p['raw_text']
                   for p in analysis.get('analysis_paragraphs', [])):
            raise AnalysisError('보고서 주장 원문의 근거 연결을 확인하지 못했습니다.')
        quote = original['original_quote']
        if not quote or not any(isinstance(document.get(field), str) and quote in document[field]
                                for field in ('text_snippet', 'article_text')):
            # 이전 문단형 수집 파일도 그대로 지원한다.
            if not any(quote in (p.get('raw_text') or p.get('text') or '')
                       for p in document.get('paragraphs', [])):
                raise AnalysisError('대표 인용을 수집 원문에서 찾지 못했습니다.')
        score = scored.get(cid)
        evidence.append({**claim, 'original_quote': original['original_quote'],
            'expression': original.get('expression'),
            'title': document.get('title'), 'url': document.get('url'),
            'source_name': document.get('source_name'), 'country': document.get('country'),
            'reliability': score.reliability if score else None, 'label': score.label if score else None})
    missing = [claim['claim_id'] for claim in evidence if claim['reliability'] is None]
    warnings = [*analysis.get('warnings', []),
                '신뢰도 점수·라벨과 문서 유사도는 사실 일치나 출처 독립성의 증명이 아닙니다.',
                '보고서는 LLM 초안이며 사람이 원문과 번역을 검토·승인해야 합니다.']
    country_counts, language_counts = {}, {}
    platforms = {'x.com', 'twitter.com', 'facebook.com', 'www.facebook.com',
                 'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}
    platform_ids = []
    for did, document in source.items():
        country, language = document.get('country') or 'UNKNOWN', document.get('language') or 'UNKNOWN'
        country_counts[country] = country_counts.get(country, 0) + 1
        language_counts[language] = language_counts.get(language, 0) + 1
        if urlsplit(document.get('url') or '').hostname in platforms:
            platform_ids.append(did)
    if platform_ids:
        warnings.append(f'SNS·영상 플랫폼 문서 {len(platform_ids)}개가 포함됐습니다. '
                        '수집 source_name·source_category만으로 계정의 공식성이나 소재 국가를 확인할 수 없습니다.')
    if missing:
        warnings.append(f'신뢰도 점수를 받지 못한 주장 {len(missing)}개는 미평가로 유지합니다.')
    if any(claim.label is None for claim in response.claims):
        warnings.append('신뢰도 함수가 반환하지 않은 라벨·임계값을 생성하지 않습니다. '
                        '점수와 별개로 원문 내용의 공통점·상충 여부를 검토합니다.')
    if not response.input_sha256:
        warnings.append('신뢰도 응답에 입력 해시가 없어 반환 주장 필드만 동일 실행과 대조했습니다. '
                        '같은 주장에 다른 가중치·sim을 사용했는지는 응답만으로 확인할 수 없습니다.')
    return {'question': question, 'input_sha256': fingerprint, 'evidence': evidence,
            'docs': exported['docs'], 'thresholds': response.thresholds,
            'analysis_scope': analysis.get('analysis_scope'), 'warnings': warnings,
            'collection_coverage': {'source_country_counts': country_counts,
                'language_counts': language_counts, 'platform_document_ids': platform_ids,
                'platform_account_identity_verified': False},
            'documents_without_claims': [doc['id'] for doc in exported['docs']
                if doc['id'] not in {claim['document_id'] for claim in exported['claims']}],
            'missing_scores': missing,
            'confidence_input_binding': 'input_sha256' if response.input_sha256 else 'claim_fields'}


async def generate_report(client, model, packet, trace):
    # 원문 전체·N×N sim 표를 반복 입력하지 않고 검증된 대표 인용을 사용한다.
    context = {key: packet[key] for key in ('question', 'analysis_scope',
                                          'documents_without_claims', 'missing_scores', 'thresholds',
                                          'collection_coverage')}
    # URL·긴 SNS 제목·문서/문단 ID는 보고서 저장 및 화면에 그대로 둔다.
    # 모델에는 모든 대표 인용과 해석에 필요한 출처·날짜·반환 점수를 한 번씩 전달한다.
    fields = ('claim_id', 'original_quote', 'translated_quote', 'expression', 'event_date',
              'reliability', 'label', 'source_name', 'country')
    context['evidence'] = [{key: claim[key] for key in fields} for claim in packet['evidence']]
    context['limitations'] = packet['warnings']
    serialized = json.dumps(context, ensure_ascii=False)
    cjk = sum('\u3400' <= char <= '\u9fff' or '\uac00' <= char <= '\ud7a3'
              or '\u3040' <= char <= '\u30ff' for char in serialized)
    if len(serialized) + 2 * cjk > 24000:
        raise AnalysisError('보고서의 모든 대표 근거가 모델 입력 예산을 초과했습니다. '
                            '근거를 임의로 누락하지 않고 중단했습니다.')
    payload = request(model, ReportDraft, 'source_reliability_report.txt', context)
    payload['messages'][1]['content'] = json.dumps(context, ensure_ascii=False, separators=(',', ':'))
    payload['options'].update(num_ctx=8192, num_predict=2048)
    if getattr(client, 'force_cpu', False):
        payload['options']['num_gpu'] = 0
    ids = {claim['claim_id'] for claim in packet['evidence']}
    for definition in payload['format']['$defs'].values():
        citation = definition['properties']['claim_ids']
        citation['items']['enum'] = sorted(ids)
        citation['uniqueItems'] = True
    for attempt in range(2):
        try:
            draft = await generate(client, ReportDraft, payload, trace)
            generated_record = trace[-1]
            for section, statements in draft.model_dump().items():
                for statement in statements:
                    cited = statement['claim_ids']
                    if not set(cited) <= ids or len(cited) != len(set(cited)):
                        raise AnalysisError('보고서에 알 수 없거나 중복된 근거 주장 ID가 있습니다.')
                    if section in {'common_facts', 'conflicting_candidates'} and len(cited) < 2:
                        raise AnalysisError('공통·상충 판단에는 두 개 이상의 근거 주장이 필요합니다.')
                    if section in {'key_judgment', 'source_interpretations'} and not cited:
                        raise AnalysisError('핵심 판단·출처별 해석에 근거 주장이 없습니다.')
            break
        except AnalysisError as exc:
            trace[-1]['report_validation_error'] = str(exc)
            if attempt:
                raise
            correction = {**context, 'citation_repair': {'reason': str(exc),
                'allowed_claim_ids': sorted(ids),
                'instruction': '현재 허용된 ID만 정확히 사용한다. 같은 항목에 ID를 중복하지 않는다. '
                               '공통·상충의 서로 다른 근거가 없으면 빈 배열로 둔다.'}}
            payload = {**payload, 'messages': [payload['messages'][0],
                {**payload['messages'][1], 'content': json.dumps(correction, ensure_ascii=False,
                                                              separators=(',', ':'))}]}
    sections, excluded, review = await check_report(client, model, context, draft.model_dump(mode='json'), trace)
    proposed = []
    for section in ('common_facts', 'conflicting_candidates'):
        proposed.extend({'item_id': f'{section}:{index}', 'section': section, **item}
                        for index, item in enumerate(sections[section]))
        sections[section] = []
    if not excluded:
        cache_verified(client, payload, [generated_record])
    warnings = [*packet['warnings'], '보고서 근거 검토도 동일 LLM의 별도 판단이며 정확성을 보장하지 않습니다.']
    if excluded:
        warnings.append(f'자동 근거 검토에서 확인되지 않은 보고서 문장 {len(excluded)}개를 보류했습니다. '
                        '원문 근거는 모두 보존하고 보류 문장은 상세 기록에 남겼습니다.')
    if proposed:
        warnings.append('공통·상충 관계에 대한 LLM 비교 제안은 사람이 인용 쌍을 검토해 선택하기 전까지 보류합니다.')
    return {**packet, 'sections': sections, 'warnings': warnings, 'excluded_statements': excluded,
            'proposed_comparisons': proposed, 'report_review': review,
            'comparison_policy': 'human_selection_required', 'status': 'draft', 'version': 1,
            'created_at': datetime.now(UTC).isoformat(), 'audit': [],
            'timings': summarize_timings(trace)}


def report_markdown(report):
    rows = [f"# 근거·신뢰도 보고서\n\n질문: {report['question']}",
            f"상태: {report['status']} · 버전: {report['version']}"]
    for key, title in SECTION_TITLES.items():
        rows.append(f'\n## {title}\n')
        items = report['sections'][key]
        proposed = [item for item in report.get('proposed_comparisons', []) if item['section'] == key]
        if not items and not proposed:
            rows.append('현재 근거 문장에서 같은 내용을 담은 주장 쌍을 찾지 못했습니다.' if key == 'common_facts'
                        else '현재 근거 문장에서 같은 대상·시점·조건에서 충돌하는 주장 쌍을 찾지 못했습니다.'
                        if key == 'conflicting_candidates' else '판단할 근거가 충분하지 않습니다.')
        for item in items:
            refs = ' '.join(f"[{cid}]" for cid in item['claim_ids'])
            rows.append(f"- {item['text']} {refs}".rstrip())
        evidence = {claim['claim_id']: claim for claim in report['evidence']}
        for item in proposed:
            label = '공통 내용 후보 · 원문 대조 전' if key == 'common_facts' else '상충 후보 · 판단 보류'
            refs = ' '.join(f"[{cid}]" for cid in item['claim_ids'])
            rows.append(f"- **{label}**: {item['text']} {refs}")
            for cid in item['claim_ids']:
                claim = evidence[cid]
                rows.append(f"> [{cid}] {claim.get('source_name') or claim['document_id']}: {claim['translated_quote']}")
    rows.append('\n## 근거와 반환된 신뢰도\n')
    for claim in report['evidence']:
        url = claim.get('url') or ''
        title = claim.get('title') or claim['document_id']
        title = title.replace('[', '［').replace(']', '］')
        link = f'[{title}](<{url}>)' if urlsplit(url).scheme in {'http', 'https'} else title
        rows.extend([f"- **{claim['claim_id']}** — {link} · {claim.get('label') or '라벨 미제공'}",
                     f"  - 번역: {claim['translated_quote']}",
                     f"  - 원문: {claim['original_quote']}"])
    rows.append('\n## 처리상의 한계\n')
    rows.extend(f'- {warning}' for warning in report['warnings'])
    if report.get('excluded_statements'):
        rows.append('\n## 근거 검토에서 보류·제외한 문장\n')
        for item in report['excluded_statements']:
            rows.append(f"- {item['text']} — 보류 이유: {item['reason']}")
    if report.get('proposed_comparisons'):
        rows.append('\n## LLM 비교 제안 · 사람 검토 대기\n')
        rows.append('공통·상충 항목에 표시한 후보는 국적·신뢰도 라벨과 별개로 문장을 비교한 제안입니다. '
                    '출처 독립성과 원문·번역을 대조한 뒤 반영·제외 여부를 선택해야 합니다.')
    return '\n\n'.join(rows) + '\n'
