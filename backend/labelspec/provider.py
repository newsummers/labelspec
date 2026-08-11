from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import AppSettings

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    pass


class MissingApiKeyError(ProviderError):
    pass


class QianfanProvider:
    def __init__(self, settings: AppSettings):
        self.settings = settings

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
        async with httpx.AsyncClient(timeout=30) as client:
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
            content = await self._chat(payload)
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
            content = await self._chat(payload)
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
                content = await self._chat(
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
                    }
                )
        raise ProviderError(
            f"模型返回内容不符合 {response_model.__name__} 结构: {last_error}"
        )

    async def embeddings(self, model: str, inputs: List[str]) -> List[List[float]]:
        if not inputs:
            return []
        vectors: List[List[float]] = []
        async with httpx.AsyncClient(timeout=120) as client:
            for start in range(0, len(inputs), 16):
                batch = inputs[start : start + 16]
                try:
                    response = await client.post(
                        f"{self.settings.qianfan_base_url.rstrip('/')}/embeddings",
                        headers=self._headers(),
                        json={"model": model, "input": batch, "encoding_format": "float"},
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise ProviderError(self._http_error("Embedding 请求失败", exc)) from exc
                rows = sorted(response.json().get("data", []), key=lambda row: row.get("index", 0))
                vectors.extend(row.get("embedding", []) for row in rows)
        if len(vectors) != len(inputs) or any(not vector for vector in vectors):
            raise ProviderError("Embedding 返回数量或向量内容不完整")
        return vectors

    async def _chat(self, payload: Dict[str, Any]) -> str:
        async with httpx.AsyncClient(timeout=180) as client:
            try:
                response = await client.post(
                    f"{self.settings.qianfan_base_url.rstrip('/')}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(self._http_error("文本生成请求失败", exc)) from exc
        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("千帆返回了无法识别的响应结构") from exc

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
        return f"{prefix}: {exc}"
