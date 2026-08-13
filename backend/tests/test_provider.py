import pytest
import httpx

from labelspec.config import AppSettings
from labelspec.provider import MissingApiKeyError, QianfanProvider
from labelspec.domain import CandidateDecision


def test_provider_requires_api_key() -> None:
    provider = QianfanProvider(AppSettings(qianfan_api_key=""))
    with pytest.raises(MissingApiKeyError):
        provider._headers()


def test_json_fence_is_parsed() -> None:
    assert QianfanProvider._extract_json('```json\n{"label": "x"}\n```') == {"label": "x"}


def test_json_with_trailing_text_is_parsed() -> None:
    assert QianfanProvider._extract_json('{"label": "x"}\n完成') == {"label": "x"}


@pytest.mark.asyncio
async def test_chat_does_not_apply_client_timeout(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    provider = QianfanProvider(AppSettings(qianfan_api_key="test"))
    assert await provider._chat({"model": "test"}) == "{}"
    assert captured["timeout"] is None


@pytest.mark.asyncio
async def test_malformed_structured_output_is_repaired() -> None:
    class RepairProvider(QianfanProvider):
        def __init__(self):
            super().__init__(AppSettings(qianfan_api_key="test"))
            self.responses = iter([
                '{"candidates": ["金融/贷款",], "rationale": }',
                '{"candidates": ["金融/贷款"], "rationale": "贷款诉求"}',
            ])
            self.calls = 0

        async def _chat(self, payload):
            self.calls += 1
            return next(self.responses)

    provider = RepairProvider()
    value = await provider.structured("model", "system", "user", CandidateDecision)
    assert value.candidates == ["金融/贷款"]
    assert provider.calls == 2
