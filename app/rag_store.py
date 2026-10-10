"""선정 사건만 검색하는 SQLite 원문 저장소와 작은 BM25 검색기."""

import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from .rag_schemas import RagDocument, RagEventInput, RagEvidence, RagResult, RagSearch

CHUNK_CHARS = 900
CHUNK_OVERLAP = 120
MAX_EVENT_DOCUMENTS = 500


def terms(text: str) -> list[str]:
    """영문 등은 단어, 띄어쓰기 없는 CJK와 한국어는 문자 bigram. 의미 번역은 하지 않는다."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    words = re.findall(r"[^\W_]+", normalized)
    tokens = []
    for word in words:
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", word):
            tokens.extend(word[i:i + 2] for i in range(len(word) - 1))
        elif len(word) > 1:
            tokens.append(word)
    return tokens


def chunks(doc: RagDocument) -> Iterator[tuple[int, int, str | None]]:
    """문단 경계에서 나누되 길면 겹침 청크를 만든다. 위치는 저장 본문의 Python 문자 기준."""
    paragraph_ranges = []
    cursor = 0
    for paragraph in doc.paragraphs:
        offset = doc.text.find(paragraph.text, cursor)
        if offset >= 0:
            paragraph_ranges.append((offset, offset + len(paragraph.text), paragraph.id))
            cursor = offset + len(paragraph.text)
    for match in re.finditer(r"[^\r\n]+", doc.text):
        start, stop = match.span()
        if not match.group().strip():
            continue
        while start < stop:
            end = min(start + CHUNK_CHARS, stop)
            pid = next((pid for low, high, pid in paragraph_ranges
                        if low <= start and end <= high), None)
            yield start, end, pid
            if end == stop:
                break
            start = end - CHUNK_OVERLAP


class RagStore:
    """별도 테이블만 사용한다. 쓰기는 하나의 트랜잭션이며 같은 사건·문서 ID를 갱신한다."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS rag_events (
                    event_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rag_documents (
                    event_id TEXT NOT NULL, doc_id TEXT NOT NULL,
                    body TEXT NOT NULL, content_hash TEXT NOT NULL,
                    PRIMARY KEY(event_id, doc_id),
                    FOREIGN KEY(event_id) REFERENCES rag_events(event_id));
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    event_id TEXT NOT NULL, doc_id TEXT NOT NULL, chunk_id TEXT NOT NULL,
                    start_char INTEGER NOT NULL, end_char INTEGER NOT NULL,
                    paragraph_id TEXT, tokens TEXT NOT NULL,
                    PRIMARY KEY(event_id, chunk_id),
                    FOREIGN KEY(event_id, doc_id) REFERENCES rag_documents(event_id, doc_id)
                        ON DELETE CASCADE);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, event_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT body FROM rag_events WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            raise KeyError(event_id)
        return {"event_id": event_id, **json.loads(row[0])}

    def events(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""SELECT e.event_id, e.body, COUNT(d.doc_id)
                FROM rag_events e LEFT JOIN rag_documents d ON e.event_id=d.event_id
                GROUP BY e.event_id ORDER BY e.event_id""").fetchall()
        return [{"event_id": eid, **json.loads(body), "document_count": count}
                for eid, body, count in rows]

    def register_event(self, event_id: str, body: RagEventInput) -> dict:
        with self.connect() as db:
            db.execute("""INSERT INTO rag_events VALUES (?, ?)
                ON CONFLICT(event_id) DO UPDATE SET body=excluded.body""",
                       (event_id, body.model_dump_json()))
        return self.event(event_id)

    def ingest(self, event_id: str, documents: list[RagDocument]) -> dict:
        self.event(event_id)
        count = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = {row[0] for row in db.execute(
                "SELECT doc_id FROM rag_documents WHERE event_id=?", (event_id,))}
            if len(existing | {doc.doc_id for doc in documents}) > MAX_EVENT_DOCUMENTS:
                raise ValueError(f"사건당 최대 {MAX_EVENT_DOCUMENTS}문서까지만 저장합니다.")
            for doc in documents:
                digest = sha256(" ".join(doc.text.split()).encode()).hexdigest()
                db.execute("DELETE FROM rag_chunks WHERE event_id=? AND doc_id=?",
                           (event_id, doc.doc_id))
                db.execute("""INSERT INTO rag_documents VALUES (?, ?, ?, ?)
                    ON CONFLICT(event_id, doc_id) DO UPDATE SET
                    body=excluded.body, content_hash=excluded.content_hash""",
                           (event_id, doc.doc_id, doc.model_dump_json(), digest))
                for index, (start, end, pid) in enumerate(chunks(doc), 1):
                    chunk_id = f"{doc.doc_id}::C{index}::{digest[:12]}"
                    token_counts = dict(Counter(terms(doc.text[start:end])))
                    db.execute("INSERT INTO rag_chunks VALUES (?, ?, ?, ?, ?, ?, ?)", (
                        event_id, doc.doc_id, chunk_id, start, end, pid, json.dumps(token_counts),
                    ))
                    count += 1
        return {"event_id": event_id, "ingested_documents": len(documents), "indexed_chunks": count}

    @staticmethod
    def _exclusion(doc: RagDocument, request: RagSearch, demo_event: bool) -> str | None:
        if (doc.is_demo or demo_event) and not request.include_demo:
            return "demo"
        if doc.content_kind == "snippet" and not request.include_snippets:
            return "snippet"
        if request.countries and doc.source_country not in request.countries:
            return "country"
        if request.languages and doc.language not in request.languages:
            return "language"
        for field, low, high in [
            ("published_date", request.published_start, request.published_end),
            ("event_date", request.event_start, request.event_end),
        ]:
            actual = getattr(doc, field)
            if low or high:
                if actual is None:
                    return field + "_unknown"
                if (low and actual < low) or (high and actual > high):
                    return field + "_outside"
        return None

    def search(self, request: RagSearch) -> RagResult:
        event = self.event(request.event_id)
        with self.connect() as db:
            rows = db.execute("SELECT doc_id, body, content_hash FROM rag_documents WHERE event_id=?",
                              (request.event_id,)).fetchall()
            chunk_rows = db.execute("""SELECT doc_id, chunk_id, start_char, end_char,
                paragraph_id, tokens FROM rag_chunks WHERE event_id=?""",
                                   (request.event_id,)).fetchall()
        eligible = {}
        excluded = Counter()
        for doc_id, body, digest in rows:
            doc = RagDocument.model_validate_json(body)
            if event["is_demo"]:
                doc.is_demo = True
            reason = self._exclusion(doc, request, event["is_demo"])
            if reason:
                excluded[reason] += 1
            else:
                eligible[doc_id] = (doc, digest)
        candidates = [(row, json.loads(row[5])) for row in chunk_rows if row[0] in eligible]
        queries = [(query, set(terms(query))) for query in
                   dict.fromkeys([request.question, *request.query_variants])]
        frequencies = Counter(term for _, bag in candidates for term in bag)
        total = len(candidates)
        average_length = sum(sum(bag.values()) for _, bag in candidates) / max(total, 1)
        ranked = []
        for row, bag in candidates:
            best_score, best_query = 0.0, ""
            length = sum(bag.values())
            for query, query_terms in queries:
                score = 0.0
                for term in query_terms & bag.keys():
                    tf = bag[term]
                    idf = math.log(1 + (total - frequencies[term] + 0.5) /
                                   (frequencies[term] + 0.5))
                    denominator = tf + 1.2 * (0.25 + 0.75 * length / max(average_length, 1))
                    score += idf * tf * 2.2 / denominator
                if score > best_score:
                    best_score, best_query = score, query
            if best_score > 0:
                ranked.append((best_score, row, best_query))
        ranked.sort(key=lambda item: (-item[0], item[1][0], item[1][2]))
        evidence = []
        seen_docs, seen_hashes, seen_clusters = set(), set(), set()
        suppressed_docs = set()
        for score, row, matched_query in ranked:
            doc_id, chunk_id, start, end, pid, _ = row
            doc, digest = eligible[doc_id]
            if doc_id in seen_docs:
                continue
            if digest in seen_hashes or (doc.source_cluster and doc.source_cluster in seen_clusters):
                suppressed_docs.add(doc_id)
                continue
            seen_docs.add(doc_id)
            seen_hashes.add(digest)
            if doc.source_cluster:
                seen_clusters.add(doc.source_cluster)
            quote = doc.text[start:end]
            if len(evidence) < request.top_k:
                evidence.append(RagEvidence(
                    **doc.model_dump(), event_id=request.event_id, chunk_id=chunk_id,
                    paragraph_id=pid, quote=quote, start_char=start, end_char=end,
                    content_hash=digest, retrieval_score=round(score, 6), matched_query=matched_query,
                    raw_quote_verified=quote in (doc.raw_content if doc.raw_content is not None
                                                else doc.text if doc.text_origin == "raw" else ""),
                ))
        warnings = [
            "검색 점수는 원문 문자열 관련도이며 의미 검증·진위·정답 확률이 아닙니다.",
            "외국어 근거에는 해당 언어의 query_variants가 필요합니다. 자동 번역·임베딩 검색은 없습니다.",
            "사건 ID는 지정한 자료 범위입니다. 문서의 실제 사건 적합성은 별도 검증해야 합니다.",
            "동일 본문·명시된 그룹을 중복 억제하지만 재인용·독립성을 완전히 판정하지 않습니다.",
        ]
        if excluded:
            warnings.append("일부 자료는 선택 조건 또는 요약·가상 자료 제외 정책으로 검색에서 제외됐습니다.")
        for hit in evidence:
            if hit.content_kind != "full" or hit.needs_review:
                warnings.append(f"{hit.doc_id}: 본문 상태 {hit.content_kind}, 정제 검토 {hit.needs_review}.")
            if not hit.raw_quote_verified:
                warnings.append(f"{hit.doc_id}: 저장 본문 인용은 일치하지만 수집 원본과 직접 대조되지 않았습니다.")
        status = ("empty_event" if not rows else "no_eligible_documents" if not eligible
                  else "evidence_found" if evidence else "no_match")
        return RagResult(
            event_id=request.event_id, question=request.question, status=status,
            total_documents=len(rows), eligible_documents=len(eligible), excluded=dict(excluded),
            duplicates_suppressed=len(suppressed_docs), evidence=evidence, warnings=warnings,
        )
