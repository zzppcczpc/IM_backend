from dataclasses import dataclass
import json
from typing import AsyncIterator, Optional

import httpx

from ..config import settings


@dataclass(frozen=True)
class AIModelConfig:
    provider: str
    base_url: str
    api_key: str
    model_name: str
    timeout: float
    source: str = "system"

    @property
    def configured(self) -> bool:
        return all([self.base_url, self.api_key, self.model_name])

    def missing_fields(self) -> list[str]:
        fields = []
        if not self.base_url:
            fields.append("AI_BASE_URL")
        if not self.api_key:
            fields.append("AI_API_KEY")
        if not self.model_name:
            fields.append("AI_MODEL_NAME")
        return fields

    def public_dict(self) -> dict:
        return {
            "source": self.source,
            "provider": self.provider,
            "base_url": self.base_url,
            "model_name": self.model_name,
            "configured": self.configured,
            "missing_fields": self.missing_fields(),
        }


class AIService:
    """AI基础服务：负责读取默认模型配置和执行最小健康检查。"""

    # 从全局 settings 中组装默认 AI 配置，后续聊天接口也会复用这份入口。
    def get_default_config(self) -> AIModelConfig:
        return AIModelConfig(
            provider=settings.AI_PROVIDER,
            base_url=settings.AI_BASE_URL.rstrip("/"),
            api_key=settings.AI_API_KEY,
            model_name=settings.AI_MODEL_NAME,
            timeout=settings.AI_HEALTHCHECK_TIMEOUT,
        )

    # 把用户保存的接口配置转换成运行时配置；模型名来自前端选择或保存的 selected_model。
    def build_user_config(self, provider_config: dict, api_key: str, model_name: str) -> AIModelConfig:
        return AIModelConfig(
            provider=provider_config.get("provider", "openai_compatible"),
            base_url=(provider_config.get("base_url") or "").rstrip("/"),
            api_key=api_key,
            model_name=model_name,
            timeout=settings.AI_HEALTHCHECK_TIMEOUT,
            source="user",
        )

    # 健康检查分两层：默认只检查配置是否齐全；probe=True 时才真实请求模型服务。
    async def health_check(self, probe: bool = False) -> dict:
        config = self.get_default_config()
        data = config.public_dict()
        data["available"] = False

        if not config.configured:
            data["error"] = f"AI配置缺失: {', '.join(config.missing_fields())}"
            return data

        if not probe:
            data["available"] = True
            data["probe"] = False
            return data

        probe_error = await self._probe_openai_compatible(config)
        data["probe"] = True
        data["available"] = probe_error is None
        if probe_error:
            data["error"] = probe_error
        return data

    # 使用 OpenAI-compatible 的 /chat/completions 协议做一次最小请求，验证 key、模型名和服务连通性。
    async def _probe_openai_compatible(self, config: AIModelConfig) -> Optional[str]:
        if config.provider != "openai_compatible":
            return f"暂不支持的AI服务提供方: {config.provider}"

        url = f"{config.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.model_name,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
        }

        try:
            async with httpx.AsyncClient(timeout=config.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                return f"AI服务探活失败: HTTP {response.status_code}"
            return None
        except httpx.TimeoutException:
            return "AI服务探活超时"
        except httpx.RequestError as exc:
            return f"AI服务无法连接: {exc.__class__.__name__}"

    # 根据当前接口配置读取可用模型列表；OpenAI-compatible 标准路径是 GET /models。
    async def list_models(self, config: AIModelConfig) -> dict:
        if not config.base_url or not config.api_key:
            return {"ok": False, "error": "AI接口配置缺失: base_url 或 api_key"}
        if config.provider != "openai_compatible":
            return {"ok": False, "error": f"暂不支持的AI服务提供方: {config.provider}"}

        url = f"{config.base_url}/models"
        headers = {"Authorization": f"Bearer {config.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=config.timeout) as client:
                response = await client.get(url, headers=headers)
            if response.status_code >= 400:
                return {"ok": False, "error": f"模型列表读取失败: HTTP {response.status_code}"}
            body = response.json()
            models = []
            for item in body.get("data") or []:
                model_id = item.get("id")
                if model_id:
                    models.append({"id": model_id, "name": model_id})
            return {"ok": True, "data": models}
        except ValueError:
            return {"ok": False, "error": "模型列表接口返回了无法解析的JSON"}
        except httpx.TimeoutException:
            return {"ok": False, "error": "模型列表读取超时"}
        except httpx.RequestError as exc:
            return {"ok": False, "error": f"AI服务无法连接: {exc.__class__.__name__}"}

    # 最小非流式聊天：只把用户问题发给默认模型，并一次性取回完整回答。
    async def chat(
        self,
        message: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        config: Optional[AIModelConfig] = None,
    ) -> dict:
        config = config or self.get_default_config()
        if not config.configured:
            return {
                "ok": False,
                "error": f"AI配置缺失: {', '.join(config.missing_fields())}",
                "data": config.public_dict(),
            }

        if config.provider != "openai_compatible":
            return {
                "ok": False,
                "error": f"暂不支持的AI服务提供方: {config.provider}",
                "data": config.public_dict(),
            }

        payload = {
            "model": config.model_name,
            "messages": [{"role": "user", "content": message}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response_data = await self._post_chat_completions(config, payload)
            content = self._extract_chat_content(response_data)
            return {
                "ok": True,
                "data": {
                    "source": config.source,
                    "model": response_data.get("model") or config.model_name,
                    "content": content,
                    "usage": response_data.get("usage"),
                },
            }
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "data": config.public_dict()}
        except httpx.TimeoutException:
            return {"ok": False, "error": "AI聊天请求超时", "data": config.public_dict()}
        except httpx.RequestError as exc:
            return {
                "ok": False,
                "error": f"AI服务无法连接: {exc.__class__.__name__}",
                "data": config.public_dict(),
            }

    async def stream_chat(
        self,
        message: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        config: Optional[AIModelConfig] = None,
    ) -> AsyncIterator[dict]:
        """以 OpenAI-compatible SSE 格式逐段返回模型输出。"""
        config = config or self.get_default_config()
        if not config.configured:
            raise ValueError(f"AI配置缺失: {', '.join(config.missing_fields())}")
        if config.provider != "openai_compatible":
            raise ValueError(f"暂不支持的AI服务提供方: {config.provider}")

        payload = {
            "model": config.model_name,
            "messages": [{"role": "user", "content": message}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        url = f"{config.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        async with httpx.AsyncClient(timeout=config.timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise ValueError(
                        self._format_stream_error(response.status_code, body)
                    )

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue

                    raw_data = line[5:].strip()
                    if raw_data == "[DONE]":
                        return

                    try:
                        chunk = json.loads(raw_data)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices") or []
                    choice = choices[0] if choices else {}
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield {
                            "content": content,
                            "model": chunk.get("model") or config.model_name,
                            "usage": chunk.get("usage"),
                        }

                    if chunk.get("usage"):
                        yield {
                            "content": "",
                            "model": chunk.get("model") or config.model_name,
                            "usage": chunk["usage"],
                        }

    # 统一发送 Chat Completions 请求，后续流式/多模型能力也可以在这里继续扩展。
    async def _post_chat_completions(self, config: AIModelConfig, payload: dict) -> dict:
        url = f"{config.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=config.timeout) as client:
            response = await client.post(url, headers=headers, json=payload)

        if response.status_code >= 400:
            return self._raise_model_error(response)

        try:
            return response.json()
        except ValueError as exc:
            raise ValueError("AI服务返回了无法解析的JSON") from exc

    # 从 OpenAI-compatible 响应里提取 assistant 的文本内容。
    def _extract_chat_content(self, response_data: dict) -> str:
        choices = response_data.get("choices") or []
        if not choices:
            raise ValueError("AI服务没有返回回答内容")

        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        raise ValueError("AI服务返回的回答内容为空")

    # 错误响应里可能包含服务商细节，但这里不会带出 api_key。
    def _raise_model_error(self, response: httpx.Response):
        detail = ""
        try:
            body = response.json()
            error_body = body.get("error") if isinstance(body, dict) else None
            if isinstance(error_body, dict):
                detail = error_body.get("message") or error_body.get("code") or ""
        except ValueError:
            detail = response.text[:200]

        message = f"AI聊天请求失败: HTTP {response.status_code}"
        if detail:
            message = f"{message}, {detail}"
        raise ValueError(message)

    def _format_stream_error(self, status_code: int, body: bytes) -> str:
        detail = ""
        try:
            data = httpx.Response(status_code=status_code, content=body).json()
            error_body = data.get("error") if isinstance(data, dict) else None
            if isinstance(error_body, dict):
                detail = error_body.get("message") or error_body.get("code") or ""
        except ValueError:
            detail = body.decode("utf-8", errors="ignore")[:200]

        message = f"AI聊天请求失败: HTTP {status_code}"
        return f"{message}, {detail}" if detail else message


ai_service = AIService()
