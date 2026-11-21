from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import httpx

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class LLMProviderError(Exception):
    """Normalized provider failure that triggers automatic mid-session rule-based fallback."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass
class LLMGenerationResult:
    message: str
    strategy: Optional[str]
    referenced_arguments: list[str]
    new_arguments: list[str]
    provider: str
    model: str
    latency_ms: int


class BaseLLMProvider(ABC):
    provider_name: str = "base"

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self.api_key = (api_key or "").strip()
        cleaned_model = (model or "").strip()
        if cleaned_model.startswith("models/"):
            cleaned_model = cleaned_model[len("models/") :]
        self.model = cleaned_model
        self.base_url = (base_url or "").strip().rstrip("/")

    @abstractmethod
    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout_seconds: float = 10.0,
    ) -> LLMGenerationResult:
        raise NotImplementedError

    @staticmethod
    def _classify_http_error(status_code: int, body_preview: str) -> LLMProviderError:
        if status_code in (401, 403):
            return LLMProviderError("auth_error", f"Authentication failed (HTTP {status_code}).")
        if status_code == 404:
            return LLMProviderError("model_unavailable", "Configured model unavailable (HTTP 404).")
        if status_code == 429:
            return LLMProviderError("rate_limited", "Provider rate limit or quota exceeded (HTTP 429).")
        if status_code == 400 and "api key" in body_preview.lower():
            return LLMProviderError("auth_error", "Invalid API key reported by provider.")
        if status_code == 400 and "model" in body_preview.lower():
            return LLMProviderError("model_unavailable", "Invalid or unsupported model name.")
        if status_code >= 500:
            return LLMProviderError("server_error", f"Provider upstream error (HTTP {status_code}).")
        return LLMProviderError("server_error", f"Unexpected provider HTTP {status_code}.")

    @staticmethod
    def _parse_structured_output(raw_text: str) -> dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMProviderError("invalid_response", "LLM output was not valid JSON.") from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("message"), str):
            raise LLMProviderError("invalid_response", "LLM JSON missing string 'message' field.")
        return parsed


class GeminiLLMProvider(BaseLLMProvider):
    provider_name = "gemini"

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None) -> None:
        resolved_url = base_url or os.getenv("GEMINI_BASE_URL") or DEFAULT_GEMINI_BASE_URL
        super().__init__(api_key=api_key, model=model, base_url=resolved_url)

    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout_seconds: float = 10.0,
    ) -> LLMGenerationResult:
        if not self.api_key:
            raise LLMProviderError("missing_key", "Gemini API key is not configured.")

        url = f"{self.base_url}/models/{self.model}:generateContent"
        payload = {
         "systemInstruction": {"parts": [{"text": system_prompt}]},
         "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
         "generationConfig": {
             "temperature": 0.65,
             "maxOutputTokens": 600,
             "responseMimeType": "application/json",
         },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMProviderError("timeout", "Gemini request timed out.") from exc
        except httpx.RequestError as exc:
            raise LLMProviderError("server_error", "Network error connecting to Gemini.") from exc

        latency_ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code != 200:
            raise self._classify_http_error(resp.status_code, resp.text[:250])

        try:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("invalid_response", "Malformed Gemini response payload.") from exc

        parsed = self._parse_structured_output(text)
        return LLMGenerationResult(
            message=parsed["message"].strip(),
            strategy=parsed.get("strategy") if isinstance(parsed.get("strategy"), str) else None,
            referenced_arguments=[
                str(x) for x in parsed.get("referenced_arguments", []) if isinstance(x, str)
            ],
            new_arguments=[
                str(x) for x in parsed.get("new_arguments", []) if isinstance(x, str)
            ],
            provider=self.provider_name,
            model=self.model,
            latency_ms=latency_ms,
        )


class OpenAILLMProvider(BaseLLMProvider):
    provider_name = "openai"

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None) -> None:
        resolved_url = base_url or os.getenv("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL
        super().__init__(api_key=api_key, model=model, base_url=resolved_url)

    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout_seconds: float = 10.0,
    ) -> LLMGenerationResult:
        if not self.api_key:
            raise LLMProviderError("missing_key", "OpenAI API key is not configured.")

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.65,
            "max_tokens": 600,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMProviderError("timeout", "OpenAI request timed out.") from exc
        except httpx.RequestError as exc:
            raise LLMProviderError("server_error", "Network error connecting to OpenAI.") from exc

        latency_ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code != 200:
            raise self._classify_http_error(resp.status_code, resp.text[:250])

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("invalid_response", "Malformed OpenAI response payload.") from exc

        parsed = self._parse_structured_output(text)
        return LLMGenerationResult(
            message=parsed["message"].strip(),
            strategy=parsed.get("strategy") if isinstance(parsed.get("strategy"), str) else None,
            referenced_arguments=[
                str(x) for x in parsed.get("referenced_arguments", []) if isinstance(x, str)
            ],
            new_arguments=[
                str(x) for x in parsed.get("new_arguments", []) if isinstance(x, str)
            ],
            provider=self.provider_name,
            model=self.model,
            latency_ms=latency_ms,
        )


def create_llm_provider(
    provider: str,
    api_key: str,
    model: str,
    base_url: Optional[str] = None,
) -> BaseLLMProvider:
    norm = (provider or "").strip().lower()
    if norm == "gemini":
        return GeminiLLMProvider(api_key=api_key, model=model, base_url=base_url)
    if norm == "openai":
        return OpenAILLMProvider(api_key=api_key, model=model, base_url=base_url)
    raise LLMProviderError("model_unavailable", f"Unsupported LLM provider '{provider}'.")