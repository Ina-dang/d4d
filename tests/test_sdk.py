"""로컬 HTTP 대역으로 설치된 OpenAI SDK의 구조화 파싱을 검증한다."""

import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.config import Settings
from app.core.errors import AnalysisError
from app.core.schemas import Report, SearchPlan
from app.legacy.providers import Provider


@pytest.mark.parametrize("refusal", [False, True])
def test_sdk_structured_response_and_refusal(refusal):
    async def scenario():
        payload = {
            "event": "test",
            "event_date": None,
            "queries": [{"language": "ko", "query": "test query"}],
            "targets": [{"id": "T1", "label": "시각", "subject": "test time"}],
        }

        def reply(request):
            sent = json.loads(request.content)
            assert sent["max_output_tokens"] == 2800
            assert sent["text"]["format"]["type"] == "json_schema"
            content = (
                [{"type": "refusal", "refusal": "test refusal"}]
                if refusal
                else [{"type": "output_text", "text": json.dumps(payload), "annotations": []}]
            )
            return httpx.Response(
                200,
                json={
                    "id": "resp_test",
                    "object": "response",
                    "created_at": 0,
                    "status": "completed",
                    "model": "gpt-4.1-mini",
                    "error": None,
                    "incomplete_details": None,
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": [],
                    "output": [
                        {
                            "id": "msg_test",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": content,
                        }
                    ],
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "total_tokens": 150,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens_details": {"reasoning_tokens": 0},
                    },
                },
            )

        provider = Provider(Settings(openai_key="test-key", tavily_key="test-key"))
        await provider.llm.close()
        provider.llm = AsyncOpenAI(
            api_key="test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(reply)),
        )
        report = Report(
            id="sdk-test", question="SDK 대역 테스트 질문", mode="live", created_at="now"
        )
        try:
            if refusal:
                with pytest.raises(AnalysisError):
                    await provider.parse(SearchPlan, "test", {}, report)
            else:
                result = await provider.parse(SearchPlan, "test", {}, report)
                assert isinstance(result, SearchPlan) and result.targets[0].id == "T1"
            assert report.input_tokens == 100 and report.output_tokens == 50
            assert report.model_calls == 1
        finally:
            await provider.close()

    asyncio.run(scenario())
