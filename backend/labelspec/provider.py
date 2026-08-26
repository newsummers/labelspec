from __future__ import annotations

import asyncio
import json
import inspect
import logging
import random
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import AppSettings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
CallObserver = Callable[[Dict[str, Any]], Awaitable[None]]
_telemetry_context: ContextVar[Dict[str, Any]] = ContextVar(
    "labelspec_telemetry_context", default={}
)

# Running many queries in parallel multiplies request rate, so throttling and
# transient upstream faults have to be absorbed here instead of failing the run.
RETRY_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
MAX_TRANSPORT_ATTEMPTS = 4
RETRY_BASE_DELAY_SECONDS = 1.0
RETRY_MAX_DELAY_SECONDS = 30.0


class ProviderError(RuntimeError):
    pass


class MissingApiKeyError(ProviderError):
    pass


def _is_retryable(exc: httpx.HTTPError) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUS_CODES
    # Timeouts and connection resets are transient by nature.
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))


def _retry_delay(exc: httpx.HTTPError, attempt: int) -> float:
    """Honour Retry-After when present, otherwise exponential backoff with jitter."""
    if isinstance(exc, httpx.HTTPStatusError):
        header = exc.response.headers.get("retry-after")
        if header:
            try:
                return max(0.0, min(RETRY_MAX_DELAY_SECONDS, float(header.strip())))
            except ValueError:
                pass
    backoff = min(RETRY_MAX_DELAY_SECONDS, RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
    # Full jitter keeps parallel workers from retrying in lockstep.
    return backoff * (0.5 + random.random() / 2)


class QianfanProvider:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self._call_observer: Optional[CallObserver] = None

    def set_call_observer(self, observer: Optional[CallObserver]) -> None:
        self._call_observer = observer

    @contextmanager
    def telemetry_context(self, **values: Any):
        current = dict(_telemetry_context.get())
        current.update({key: value for key, value in values.items() if value is not None})
        token = _telemetry_context.set(current)
        try:
            yield
        finally:
            _telemetry_context.reset(token)

    @property
    def configured(self) -> bool:
        return self.settings.has_api_key

    def _headers(self) -> Dict[str, str]:
        if not self.configured:
            raise MissingApiKeyError("未配置 QIANFAN_API_KEY，模型操作无法执行")
        return {
            "Authorization": f"Bearer {self.settings.qianfan_api_key.strip()}",
            "Content-Type": "application/json",
        }

    async def list_models(self) -> List[Dict[str, Any]]:
        # Do not impose a client-side deadline. If Qianfan cannot complete the
        # request, return its actual response or transport error to the caller.
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                response = await client.get(
                    f"{self.settings.qianfan_base_url.rstrip('/')}/models",
                    headers=self._headers(),
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(self._http_error("获取模型列表失败", exc)) from exc
        payload = response.json()
        models = payload.get("data", payload if isinstance(payload, list) else [])
        return [item for item in models if isinstance(item, dict)]

    async def structured(
        self,
        model: str,
        system: str,
        user: str,
        response_model: Type[T],
        temperature: float = 0.1,
    ) -> T:
        schema = response_model.model_json_schema()
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "enable_thinking": False,
            "response_format": {"type": "json_schema", "json_schema": schema},
        }
        try:
            content = await self._structured_chat(payload, response_model.__name__, 1)
        except ProviderError as exc:
            # Some Qianfan-hosted models do not support json_schema. They can still
            # be used with JSON mode, followed by strict local validation.
            if "response_format" not in str(exc) and "json_schema" not in str(exc):
                raise
            payload["response_format"] = {"type": "json_object"}
            payload["messages"][0]["content"] += (
                "\n只输出合法 JSON，且必须严格满足以下 JSON Schema：\n"
                + json.dumps(schema, ensure_ascii=False)
            )
            content = await self._structured_chat(payload, response_model.__name__, 2)
        last_error: Optional[Exception] = None
        for repair_attempt in range(3):
            try:
                raw = self._extract_json(content)
                return response_model.model_validate(raw)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                if repair_attempt == 2:
                    excerpt = str(content).strip().replace("\n", " ")[:240]
                    raise ProviderError(
                        f"模型连续 3 次返回不符合 {response_model.__name__} 的内容: "
                        f"{exc}; response={excerpt!r}"
                    ) from exc
                content = await self._structured_chat(
                    {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "你是 JSON 修复器。只返回一个合法 JSON 对象，不要使用 Markdown，"
                                    "不要添加解释。输出必须严格满足给定 JSON Schema。\n"
                                    + json.dumps(schema, ensure_ascii=False)
                                ),
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"以下输出解析失败（{exc}），请修复：\n{content}"
                                ),
                            },
                        ],
                        "temperature": 0,
                        "enable_thinking": False,
                        "response_format": {"type": "json_object"},
                    },
                    f"{response_model.__name__}_REPAIR",
                    repair_attempt + 1,
                )
        raise ProviderError(
            f"模型返回内容不符合 {response_model.__name__} 结构: {last_error}"
        )

    async def embeddings(self, model: str, inputs: List[str]) -> List[List[float]]:
        if not inputs:
            return []
        vectors: List[List[float]] = []
        for start in range(0, len(inputs), 16):
            batch = inputs[start : start + 16]
            started = time.perf_counter()
            try:
                response = await self._post_with_retry(
                    "embeddings",
                    {"model": model, "input": batch, "encoding_format": "float"},
                    operation="embeddings",
                    attempt=start // 16 + 1,
                )
            except httpx.HTTPError as exc:
                await self._record_call(
                    operation="embeddings",
                    attempt=start // 16 + 1,
                    model=model,
                    started=started,
                    status="error",
                    error=self._http_error("Embedding 请求失败", exc),
                )
                raise ProviderError(self._http_error("Embedding 请求失败", exc)) from exc
            payload = response.json()
            rows = sorted(payload.get("data", []), key=lambda row: row.get("index", 0))
            vectors.extend(row.get("embedding", []) for row in rows)
            await self._record_call(
                operation="embeddings",
                attempt=start // 16 + 1,
                model=model,
                started=started,
                status="success",
                usage=payload.get("usage") or {},
                request_id=self._request_id(response, payload),
            )
        if len(vectors) != len(inputs) or any(not vector for vector in vectors):
            raise ProviderError("Embedding 返回数量或向量内容不完整")
        return vectors

    async def _chat(
        self,
        payload: Dict[str, Any],
        operation: str = "chat",
        attempt: int = 1,
    ) -> str:
        # Large structured compilations can legitimately take several minutes.
        # An unlimited timeout lets the provider decide whether the request can
        # be completed instead of truncating it locally at an arbitrary limit.
        started = time.perf_counter()
        response: Optional[httpx.Response] = None
        response_payload: Dict[str, Any] = {}
        try:
            response = await self._post_with_retry(
                "chat/completions", payload, operation=operation, attempt=attempt
            )
            response_payload = response.json()
            content = response_payload["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            message = self._http_error("文本生成请求失败", exc)
            await self._record_call(
                operation=operation, attempt=attempt, model=payload.get("model", ""),
                started=started, status="error", error=message,
            )
            raise ProviderError(message) from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            message = "千帆返回了无法识别的响应结构"
            await self._record_call(
                operation=operation, attempt=attempt, model=payload.get("model", ""),
                started=started, status="error", error=f"{message}: {exc}",
            )
            raise ProviderError(message) from exc
        await self._record_call(
            operation=operation,
            attempt=attempt,
            model=payload.get("model", ""),
            started=started,
            status="success",
            usage=response_payload.get("usage") or {},
            request_id=self._request_id(response, response_payload),
        )
        return content

    async def _post_with_retry(
        self,
        path: str,
        payload: Dict[str, Any],
        operation: str,
        attempt: int,
    ) -> httpx.Response:
        """POST to Qianfan, retrying throttling and transient upstream faults."""
        url = f"{self.settings.qianfan_base_url.rstrip('/')}/{path}"
        headers = self._headers()
        last_error: httpx.HTTPError
        for transport_attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    return response
            except httpx.HTTPError as exc:
                last_error = exc
                if transport_attempt == MAX_TRANSPORT_ATTEMPTS or not _is_retryable(exc):
                    raise
                delay = _retry_delay(exc, transport_attempt)
                logger.warning(
                    "%s 第 %d/%d 次传输失败（%s），%.1fs 后重试",
                    operation, transport_attempt, MAX_TRANSPORT_ATTEMPTS,
                    self._http_error("请求被拒绝", exc), delay,
                )
                await asyncio.sleep(delay)
        raise last_error

    async def _structured_chat(
        self, payload: Dict[str, Any], operation: str, attempt: int
    ) -> str:
        # Keep compatibility with lightweight provider test doubles that override
        # the historical one-argument _chat method.
        parameters = inspect.signature(self._chat).parameters
        if "operation" not in parameters:
            return await self._chat(payload)
        return await self._chat(payload, operation=operation, attempt=attempt)

    async def _record_call(
        self,
        operation: str,
        attempt: int,
        model: str,
        started: float,
        status: str,
        usage: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        if not self._call_observer:
            return
        normalized = self._normalize_usage(usage or {})
        context = dict(_telemetry_context.get())
        record = {
            **context,
            "stage": context.get("stage", "UNKNOWN"),
            "operation": operation,
            "attempt": attempt,
            "model_id": model,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "status": status,
            "request_id": request_id,
            "error": error,
            "usage": usage or {},
            **normalized,
        }
        try:
            result = self._call_observer(record)
            if inspect.isawaitable(result):
                await result
        except Exception:  # telemetry must never break the model request
            logger.exception("记录模型调用指标失败")

    @staticmethod
    def _request_id(response: Optional[httpx.Response], payload: Dict[str, Any]) -> Optional[str]:
        if response is not None:
            headers = getattr(response, "headers", {})
            value = headers.get("x-request-id") or headers.get("request-id")
            if value:
                return value
        value = payload.get("id") or payload.get("request_id")
        return str(value) if value else None

    @staticmethod
    def _normalize_usage(usage: Dict[str, Any]) -> Dict[str, Optional[int]]:
        details = usage.get("prompt_tokens_details") or usage.get("prompt_token_details") or {}
        cached = (
            usage.get("cached_input_tokens")
            or usage.get("cache_read_input_tokens")
            or details.get("cached_tokens")
        )
        reasoning = usage.get("reasoning_tokens") or usage.get("completion_tokens_details", {}).get("reasoning_tokens")
        return {
            "input_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
            "output_tokens": usage.get("completion_tokens") or usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "cached_input_tokens": cached,
            "reasoning_tokens": reasoning,
        }

    @staticmethod
    def _extract_json(content: Any) -> Any:
        if isinstance(content, dict):
            return content
        text = str(content).strip()
        if text.startswith("```"):
            first_newline = text.find("\n")
            text = text[first_newline + 1 :] if first_newline >= 0 else text[3:]
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3].rstrip()
        starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
        if not starts:
            raise ValueError("响应中没有 JSON 对象或数组")
        value, _ = json.JSONDecoder().raw_decode(text[min(starts) :])
        return value

    @staticmethod
    def _http_error(prefix: str, exc: httpx.HTTPError) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            try:
                detail = exc.response.json()
            except ValueError:
                detail = exc.response.text[:500]
            return f"{prefix} ({exc.response.status_code}): {detail}"
        detail = str(exc).strip() or exc.__class__.__name__
        return f"{prefix}: {detail}"
