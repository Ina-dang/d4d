"""가상 원문으로 사건 검색·인용·수집 연동의 실제 HTTP 계약을 검증한다."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.demo import fixtures
from app.main import create_app
from app.schemas import Report


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(
        openai_key="", tavily_key="", database=tmp_path / "test.sqlite3",
    ))) as client:
        yield client


def event(client, event_id="strait"):
    response = client.put(f"/api/rag/events/{event_id}", json={
        "label": "선정 사건", "description": "팀에서 범위를 확인한 가상 테스트 사건",
    })
    assert response.status_code == 200, response.text


def document(doc_id="one", **extra):
    return {
        "doc_id": doc_id, "title": "Statement", "url": "https://example.org/" + doc_id,
        "text": "Authorities reported military activities in the Taiwan Strait.\n"
                "The statement did not confirm the number of aircraft.",
        "language": "en", "source_country": "TW", "published_date": "2026-10-01",
        "publisher_group": "example.org", "content_kind": "full", **extra,
    }


def ingest(client, documents, event_id="strait"):
    response = client.post(f"/api/rag/events/{event_id}/documents", json={"documents": documents})
    assert response.status_code == 200, response.text
    return response.json()


def search(client, **extra):
    response = client.post("/api/rag/search", json={
        "event_id": "strait", "question": "대만해협 군사활동 근거는?",
        "query_variants": ["Taiwan Strait military activities"], **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_exact_evidence_and_separate_scores(client):
    event(client)
    doc = document(tavily_score=0.2, credibility_weight=0.95, source_tier=1)
    ingest(client, [doc])
    result = search(client)
    assert result["status"] == "evidence_found"
    hit = result["evidence"][0]
    assert hit["quote"] == doc["text"][hit["start_char"]:hit["end_char"]]
    assert hit["doc_id"] == "one" and hit["url"] == doc["url"]
    assert hit["tavily_score"] == 0.2 and hit["credibility_weight"] == 0.95
    assert hit["retrieval_score"] > 0 and hit["llm_relevance"] is None
    assert "confidence" not in hit


def test_event_boundary_no_evidence_and_unknown_event(client):
    event(client)
    event(client, "border")
    ingest(client, [document()], event_id="border")
    assert search(client)["status"] == "empty_event"
    assert search(client, event_id="border", query_variants=[], question="banana orchard")["status"] == "no_match"
    assert client.post("/api/rag/search", json={"event_id": "missing", "question": "test"}).status_code == 404


def test_filters_keep_publication_and_event_dates_separate(client):
    event(client)
    ingest(client, [document(event_date="2026-09-29"),
                    document("unknown", published_date=None, event_date=None),
                    document("china", source_country="CN", language="zh")])
    assert search(client, countries=["TW"], languages=["en"])["eligible_documents"] == 2
    result = search(client, countries=["TW"], published_start="2026-10-01")
    assert result["eligible_documents"] == 1
    assert result["excluded"]["published_date_unknown"] == 1
    result = search(client, event_start="2026-10-01")
    assert result["status"] == "no_eligible_documents"
    assert result["excluded"]["event_date_unknown"] == 2


def test_snippet_and_demo_are_opt_in_and_truncation_is_visible(client):
    event(client)
    ingest(client, [document("snippet", content_kind="snippet"),
                    document("demo", is_demo=True),
                    document("clip", content_kind="truncated")])
    result = search(client)
    assert [hit["doc_id"] for hit in result["evidence"]] == ["clip"]
    assert result["evidence"][0]["content_kind"] == "truncated"
    assert result["excluded"] == {"snippet": 1, "demo": 1}


def test_duplicate_and_rank_are_independent_of_source_weights(client):
    event(client)
    ingest(client, [document("low", tavily_score=0.1, credibility_weight=0.1),
                    document("copy", tavily_score=0.99, credibility_weight=0.99),
                    document("noise", text="Military personnel visited an orchard.",
                             tavily_score=1.0, credibility_weight=1.0)])
    result = search(client)
    assert result["evidence"][0]["doc_id"] in {"low", "copy"}
    assert len({hit["content_hash"] for hit in result["evidence"]}) == len(result["evidence"])
    assert result["duplicates_suppressed"] == 1


def test_upsert_replaces_old_chunks_and_survives_restart(tmp_path):
    settings = Settings(openai_key="", tavily_key="", database=tmp_path / "persist.sqlite3")
    with TestClient(create_app(settings)) as client:
        event(client)
        ingest(client, [document()])
        ingest(client, [document(text="Updated statement about an orchard.")])
        assert search(client, query_variants=["Taiwan Strait"], question="Taiwan Strait")["status"] == "no_match"
    with TestClient(create_app(settings)) as client:
        assert search(client, question="orchard", query_variants=[])["status"] == "evidence_found"


@pytest.mark.parametrize("changes", [
    {"text": "  "}, {"tavily_score": 2}, {"url": "javascript:alert(1)"},
    {"published_date": "2026-02-30"},
])
def test_invalid_document_rejected(client, changes):
    event(client)
    response = client.post("/api/rag/events/strait/documents", json={"documents": [document(**changes)]})
    assert response.status_code == 422


def test_invalid_date_range_and_same_origin(client):
    event(client)
    assert client.post("/api/rag/search", json={
        "event_id": "strait", "question": "test", "published_start": "2026-10-10",
        "published_end": "2026-10-01",
    }).status_code == 422
    assert client.put("/api/rag/events/strait", headers={"Origin": "https://evil.example"},
                      json={"label": "overwrite"}).status_code == 403


def test_frame_json_import_preserves_paragraph_metadata_and_queries(client):
    event(client)
    body = "Authorities reported military activities in the Taiwan Strait."
    response = client.post("/api/rag/events/strait/import", json={"output": {
        "event_date": "2026-10-01",  # 요청 날짜를 문서의 확인된 사건일로 복사하면 안 된다.
        "queries": {"en": "Taiwan Strait military activities"},
        "documents": [{
            "doc_id": "frame-one", "title": "Notice", "url": "https://example.org/notice",
            "article_text": body, "raw_content": "Header\n" + body,
            "paragraphs": [{"paragraph_id": "frame-one_p1", "raw_text": body}],
            "country": "TW", "language": "en", "source_name": "Agency",
            "source_category": "party_official", "tier": 2, "credibility_weight": 0.85,
            "score": 0.73, "query": "Taiwan Strait", "status": "success_full",
            "published_date": "2026-10-01T12:00:00+08:00", "event_date": None,
            "is_reprint_likely": True, "quoted_source": "Other agency",
            "cleaning": {"needs_review": True},
        }],
    }})
    assert response.status_code == 200, response.text
    assert response.json()["query_variants"] == ["Taiwan Strait military activities"]
    hit = search(client)["evidence"][0]
    assert hit["paragraph_id"] == "frame-one_p1"
    assert hit["tavily_score"] == 0.73 and hit["source_tier"] == 2
    assert hit["source_country"] == "TW" and hit["event_date"] is None
    assert hit["published_date"] == "2026-10-01" and hit["raw_quote_verified"]
    assert hit["needs_review"] and hit["is_reprint_likely"]


def test_tavily_summary_is_not_imported_as_full_body(client):
    event(client)
    response = client.post("/api/rag/events/strait/import", json={"results": [{
        "url": "https://example.org/summary", "title": "Summary",
        "content": "Taiwan Strait military activities", "score": 0.9,
    }]})
    assert response.status_code == 200, response.text
    assert search(client)["status"] == "no_eligible_documents"
    hit = search(client, include_snippets=True)["evidence"][0]
    assert hit["content_kind"] == "snippet"


def test_invalid_import_is_atomic_and_unfinished_job_rejected(client):
    event(client)
    payload = {"documents": [document(), document("bad", url="javascript:alert(1)")]}
    assert client.post("/api/rag/events/strait/import", json=payload).status_code == 422
    assert search(client)["total_documents"] == 0
    assert client.post("/api/rag/events/strait/import", json={
        "status": "running", "output": {"documents": [document()]},
    }).status_code == 409


def test_demo_event_label_cannot_be_bypassed_by_document_flag(client):
    client.put("/api/rag/events/demo-event", json={"label": "가상", "is_demo": True})
    ingest(client, [document()], event_id="demo-event")
    assert search(client, event_id="demo-event")["status"] == "no_eligible_documents"
    hit = search(client, event_id="demo-event", include_demo=True)["evidence"][0]
    assert hit["is_demo"]


def test_long_cjk_quote_offsets_and_original_paragraph_id(client):
    event(client)
    body = "大規模な軍事活動について当局が発表しました。" * 100
    ingest(client, [document(text=body, language="ja", paragraphs=[{"id": "P-long", "text": body}])])
    hit = search(client, query_variants=["軍事活動"])["evidence"][0]
    assert 0 < len(hit["quote"]) <= 900
    assert hit["quote"] == body[hit["start_char"]:hit["end_char"]]
    assert hit["paragraph_id"] == "P-long"


def test_report_import_preserves_source_paragraph_ids_and_demo_flag(client):
    event(client)
    plan, sources, _ = fixtures("2026-10-10T00:00:00+00:00")
    report = Report(id="saved-report", question="가상 자료", mode="demo", status="draft",
                    created_at="2026-10-10T00:00:00+00:00", plan=plan, sources=sources)
    client.app.state.store.save(report)
    response = client.post("/api/rag/events/strait/reports/saved-report")
    assert response.status_code == 200, response.text
    assert search(client)["excluded"] == {"demo": 4}
    result = search(client, question=sources[0].paragraphs[0].text, query_variants=[], include_demo=True)
    hit = result["evidence"][0]
    assert hit["doc_id"].startswith("saved-report:")
    assert hit["paragraph_id"] in {p.id for source in sources for p in source.paragraphs}


def test_rag_page_and_fixture_are_served_with_local_assets(client):
    page = client.get("/rag")
    assert page.status_code == 200
    assert "검색할 사건" in page.text
    assert client.get("/static/rag.js").status_code == 200
    assert client.get("/static/rag.css").status_code == 200
    fixture = client.get("/static/rag-demo.json").json()
    assert fixture["event"]["is_demo"]
    assert all(doc["is_demo"] for doc in fixture["documents"])
