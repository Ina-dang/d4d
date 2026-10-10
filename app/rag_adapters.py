"""기존 frame/Tavily JSON과 보고서 원문을 RAG 계약으로 변환한다."""

from datetime import date, datetime
from hashlib import sha256
from urllib.parse import urlsplit

from .rag_schemas import RagDocument, RagParagraph
from .schemas import Report


def _date(value, warnings: list[str]):
    if not value:
        return None
    try:
        if len(str(value)) == 10:
            return date.fromisoformat(value)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        warnings.append("해석할 수 없는 날짜를 미확인으로 보존했습니다.")
        return None


def collection_documents(payload: dict) -> tuple[list[RagDocument], list[str]]:
    data = payload.get("output", payload)
    if not isinstance(data, dict):
        raise ValueError("수집 결과 output은 객체여야 합니다.")
    items = data.get("all_documents", data.get("documents", data.get("results")))
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError("all_documents/documents/results에 원문 1~100개가 필요합니다.")
    documents = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("각 문서는 객체여야 합니다.")
        # 정규 RAG 계약은 그대로 검증한다. 잘못된 문서를 조용히 삭제하지 않는다.
        if "text" in item and "doc_id" in item:
            documents.append(RagDocument.model_validate(item))
            continue
        paragraphs = [RagParagraph(id=p.get("paragraph_id") or p.get("id"),
                                   text=p.get("raw_text") or p.get("text"))
                      for p in item.get("paragraphs", [])]
        raw = item.get("raw_content") or None
        cleaned = item.get("article_text") or None
        if cleaned:
            text, origin, kind = cleaned, "cleaned", "full"
        elif raw:
            text, origin, kind = raw, "raw", "full"
        elif paragraphs:
            text, origin, kind = "\n".join(p.text for p in paragraphs), "paragraphs", "unknown"
        else:
            text, origin, kind = item.get("content") or "", "raw", "snippet"
        warnings = []
        if item.get("status") in {"success_truncated", "truncated"} or len(text) > 60000:
            kind = "truncated"
        if len(text) > 60000:
            warnings.append("RAG 저장 제한 60,000자로 본문을 잘랐습니다.")
        url = item.get("url") or None
        doc_id = item.get("doc_id") or "url-" + sha256((url or text).encode()).hexdigest()[:20]
        published = _date(item.get("published_date"), warnings)
        event_date = _date(item.get("event_date"), warnings)
        documents.append(RagDocument(
            doc_id=doc_id, title=item.get("title") or doc_id, url=url,
            text=text[:60000], raw_content=raw[:60000] if raw else None, text_origin=origin,
            paragraphs=paragraphs, language=item.get("language") or "unknown",
            source_country=item.get("country") or "UNKNOWN",
            publisher_group=item.get("source_name") or (urlsplit(url).hostname if url else "unknown"),
            source_category=item.get("source_category"), source_cluster=item.get("source_cluster"),
            source_tier=item.get("tier"), tier_reason=item.get("tier_reason"),
            credibility_weight=item.get("credibility_weight"), tavily_score=item.get("score"),
            tavily_query=item.get("query"), llm_relevance=item.get("llm_relevance"),
            published_date=published, event_date=event_date,
            collected_at=item.get("collected_at"), content_kind=kind,
            is_demo=item.get("is_demo", False),
            needs_review=item.get("cleaning", {}).get("needs_review", False),
            is_reprint_likely=item.get("is_reprint_likely", False),
            quoted_source=item.get("quoted_source"), warnings=warnings,
        ))
    collection_request = payload.get("collection_request") or {}
    queries = data.get("queries") or collection_request.get("queries") or []
    if isinstance(queries, dict):
        queries = list(queries.values())
    if not isinstance(queries, list):
        queries = []
    variants = [q.get("query") if isinstance(q, dict) else q for q in queries]
    return documents, list(dict.fromkeys(q for q in variants if isinstance(q, str) and q.strip()))[:8]


def report_documents(report: Report) -> list[RagDocument]:
    return [RagDocument(
        doc_id=f"{report.id}:{source.id}", title=source.title, url=source.url,
        text="\n".join(p.text for p in source.paragraphs), text_origin="paragraphs",
        paragraphs=[RagParagraph(id=p.id, text=p.text) for p in source.paragraphs],
        language=source.language, publisher_group=source.publisher_group,
        published_date=_date(source.published_at, []), collected_at=source.collected_at,
        content_kind="truncated" if source.truncated else "unknown", is_demo=source.is_demo,
    ) for source in report.sources if source.paragraphs]
