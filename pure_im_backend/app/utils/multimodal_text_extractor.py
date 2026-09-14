import base64
import hashlib
import hmac
import json
import mimetypes
import os
import time
from pathlib import Path

import httpx

from ..config import settings
from .ai_service import ai_service


AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def is_audio_extension(extension: str) -> bool:
    return extension.lower() in AUDIO_EXTENSIONS


def is_image_extension(extension: str) -> bool:
    return extension.lower() in IMAGE_EXTENSIONS


def is_multimodal_extension(extension: str) -> bool:
    return is_audio_extension(extension) or is_image_extension(extension)


def extract_multimodal_file(path: str, extension: str) -> tuple[str, dict]:
    """将音频或图片转换为可切分、可向量化的文本。"""
    extension = extension.lower()
    if is_audio_extension(extension):
        text = _transcribe_audio(path)
        return text, {
            "parser": "iflytek_lfasr",
            "extraction_type": "asr",
            "modality": "audio",
            "text_length": len(text),
        }
    if is_image_extension(extension):
        text = _describe_image(path)
        return text, {
            "parser": "openai_compatible_vision",
            "extraction_type": "vision",
            "modality": "image",
            "text_length": len(text),
        }
    raise ValueError(f"暂不支持多模态文件类型: {extension}")


def _transcribe_audio(path: str) -> str:
    app_id = settings.XF_APPID
    secret_key = settings.XF_ASR_SECRET_KEY
    if not app_id or not secret_key:
        raise RuntimeError(
            "ASR 未配置，请设置 XF_APPID 和 XF_ASR_SECRET_KEY"
        )
    if not os.path.isfile(path):
        raise FileNotFoundError("音频文件不存在")

    audio_data = Path(path).read_bytes()
    timestamp = str(int(time.time()))
    digest = hashlib.md5(f"{app_id}{timestamp}".encode("utf-8")).hexdigest()
    signa = base64.b64encode(
        hmac.new(
            secret_key.encode("utf-8"),
            digest.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")
    params = {
        "appId": app_id,
        "signa": signa,
        "ts": timestamp,
        "fileSize": len(audio_data),
        "fileName": os.path.basename(path),
        "duration": "0",
    }
    headers = {"Content-Type": "application/octet-stream"}
    base_url = settings.ASR_IFLYTEK_URL.rstrip("/")

    with httpx.Client(timeout=settings.MULTIMODAL_TIMEOUT) as client:
        upload_response = client.post(
            f"{base_url}/upload",
            params=params,
            headers=headers,
            content=audio_data,
        )
        upload_response.raise_for_status()
        upload_body = upload_response.json()
        order_id = (upload_body.get("content") or {}).get("orderId")
        if not order_id:
            raise RuntimeError(f"ASR 上传失败: {str(upload_body)[:500]}")

        result_params = {
            "appId": app_id,
            "signa": signa,
            "ts": timestamp,
            "orderId": order_id,
            "resultType": "transfer",
        }
        deadline = time.monotonic() + settings.ASR_POLL_TIMEOUT
        result_body = {}
        while time.monotonic() < deadline:
            time.sleep(settings.ASR_POLL_INTERVAL)
            result_response = client.post(
                f"{base_url}/getResult",
                params=result_params,
                headers=headers,
            )
            result_response.raise_for_status()
            result_body = result_response.json()
            order_info = (result_body.get("content") or {}).get("orderInfo") or {}
            status = str(order_info.get("status"))
            if status == "4":
                break
            if status not in {"0", "1", "2", "3", "4"}:
                raise RuntimeError(f"ASR 处理失败: {str(result_body)[:500]}")
        else:
            raise TimeoutError("ASR 处理超时")

    text = _parse_iflytek_result(result_body)
    if not text:
        raise ValueError("ASR 没有识别到有效文本")
    return text


def _parse_iflytek_result(result_body: dict) -> str:
    order_result = (result_body.get("content") or {}).get("orderResult") or ""
    if not order_result:
        return ""
    try:
        parsed_result = json.loads(order_result)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ASR 返回结果无法解析") from exc

    words = []
    for lattice in parsed_result.get("lattice", []):
        try:
            best = json.loads(lattice.get("json_1best", "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        for sentence in best.get("st", {}).get("rt", []):
            for word in sentence.get("ws", []):
                candidates = word.get("cw") or []
                if candidates and candidates[0].get("w"):
                    words.append(str(candidates[0]["w"]))
    return "".join(words).strip()


def _describe_image(path: str) -> str:
    config = ai_service.get_default_config()
    model_name = settings.VISION_MODEL_NAME or config.model_name
    if not config.base_url or not config.api_key or not model_name:
        raise RuntimeError(
            "视觉模型未配置，请设置 AI_BASE_URL、AI_API_KEY 和 VISION_MODEL_NAME"
        )
    if not os.path.isfile(path):
        raise FileNotFoundError("图片文件不存在")

    image_data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    mime_type = mimetypes.guess_type(path)[0] or "image/png"
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "请详细描述这张图片中与知识检索有关的内容。"
                            "如果包含文字，请尽量完整识别；如果包含表格、"
                            "流程或结构，请按清晰的文本结构输出。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_data}",
                        },
                    },
                ],
            },
        ],
        "temperature": 0.2,
        "max_tokens": settings.VISION_MAX_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=settings.MULTIMODAL_TIMEOUT) as client:
        response = client.post(
            f"{config.base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()

    choices = body.get("choices") or []
    content = (choices[0].get("message") or {}).get("content") if choices else None
    if isinstance(content, list):
        content = "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("text")
        )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("视觉模型没有返回有效描述")
    return content.strip()
