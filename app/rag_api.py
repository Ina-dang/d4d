"""미니 RAG API. 외부 URL을 수집하거나 LLM을 호출하지 않는다."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse

from .rag_adapters import collection_documents, report_documents
from .rag_schemas import RagEventInput, RagIngest, RagResult, RagSearch
from .rag_store import RagStore
from .storage import Store

EventPath = Annotated[str, ApiPath(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")]


def create_rag_router(database: Path, report_store: Store) -> APIRouter:
    router = APIRouter(tags=["mini-rag"])
    store = RagStore(database)

    @router.get("/rag", include_in_schema=False)
    def page():
        return FileResponse(Path(__file__).parent / "static" / "rag.html")

    @router.get("/api/rag/events")
    def events():
        return store.events()

    @router.put("/api/rag/events/{event_id}")
    def register(event_id: EventPath, body: RagEventInput):
        return store.register_event(event_id, body)

    @router.post("/api/rag/events/{event_id}/documents")
    def ingest(event_id: EventPath, body: RagIngest):
        try:
            return store.ingest(event_id, body.documents)
        except KeyError:
            raise HTTPException(404, "사건을 먼저 등록하세요.") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.post("/api/rag/search", response_model=RagResult)
    def search(body: RagSearch):
        try:
            return store.search(body)
        except KeyError:
            raise HTTPException(404, "등록된 사건을 찾을 수 없습니다.") from None

    @router.post("/api/rag/events/{event_id}/import")
    def import_collection(event_id: EventPath, body: dict):
        if "output" in body and body.get("status", "completed") != "completed":
            raise HTTPException(409, "수집을 완료한 결과만 적재할 수 있습니다.")
        try:
            documents, queries = collection_documents(body)
            validated = RagIngest(documents=documents)
            return {**store.ingest(event_id, validated.documents), "query_variants": queries}
        except KeyError:
            raise HTTPException(404, "사건을 먼저 등록하세요.") from None
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(422, "수집 JSON의 문서·본문·링크·메타데이터 형식을 확인하세요.") from None

    @router.post("/api/rag/events/{event_id}/reports/{report_id}")
    def import_report(event_id: EventPath, report_id: str):
        report = report_store.get(report_id)
        if report is None:
            raise HTTPException(404, "보고서를 찾을 수 없습니다.")
        if report.status in {"running", "failed"}:
            raise HTTPException(409, "완료한 보고서의 원문만 적재할 수 있습니다.")
        try:
            return store.ingest(event_id, RagIngest(documents=report_documents(report)).documents)
        except KeyError:
            raise HTTPException(404, "사건을 먼저 등록하세요.") from None
        except ValueError:
            raise HTTPException(422, "적재 가능한 원문이 없거나 문서 형식이 맞지 않습니다.") from None

    return router
