from dataclasses import dataclass
from typing import Optional

import httpx

from ..config import settings


@dataclass(frozen=True)
class AIModelConfig:
    provider: str
    base_url: str
    api_key: str
    model_name: str
    timeout: float

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


ai_service = AIService()
