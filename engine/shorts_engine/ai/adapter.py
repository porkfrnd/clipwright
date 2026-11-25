from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..common.errors import CancelledError, EngineError, RateLimited
from ..common.logging import redact_text
from ..common.util import estimate_tokens
from .ratelimit import RateLimitSnapshot, TokenBudget, parse_rate_limit_headers
from .schemas import ProviderCapabilities, ProviderModel

T = TypeVar("T", bound=BaseModel)

STRICT_JSON_MODELS = {
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-safeguard-20b",
}


@dataclass
class ChatResult:
    parsed: BaseModel
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    rate_limit: RateLimitSnapshot | None = None
    mode: str = "json_schema_strict"


@dataclass
class AdapterHooks:
    on_wait: Callable[[float, str], Any] | None = None
    on_usage: Callable[[dict[str, Any]], None] | None = None
    on_request: Callable[[str, str | None, str, int, list[str], str], None] | None = None
    cancel: asyncio.Event | None = None
    alpha: float = 1.0


def _strip_json(text: str) -> str:
    """Return the JSON payload even when a model wraps it in prose or a fence."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        json.loads(text)
        return text
    except (json.JSONDecodeError, ValueError):
        pass
    # Find the first object or array and decode exactly that value.
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        return text
    start = min(starts)
    try:
        value, end = json.JSONDecoder().raw_decode(text[start:])
        return text[start:start + end]
    except (json.JSONDecodeError, ValueError):
        return text


class OpenAICompatibleAdapter:
    """Thin, provider-independent client for OpenAI-compatible chat endpoints."""

    adapter_name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        capabilities: ProviderCapabilities | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.capabilities = capabilities or ProviderCapabilities()
        self.timeout = timeout
        self.max_retries = max_retries
        self.budget = TokenBudget()
        self.last_snapshot: RateLimitSnapshot | None = None

    # ---- discovery -------------------------------------------------------
    async def list_models(self) -> list[ProviderModel]:
        url = f"{self.base_url}/models"
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.get(url, headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.RequestError as exc:
            raise EngineError(
                "PROVIDER_UNREACHABLE",
                "The provider could not be reached. Check the base URL and your connection.",
                details={"error": str(exc)[:300]},
                retryable=True,
            ) from exc
        if response.status_code in (401, 403):
            raise EngineError("PROVIDER_AUTH_FAILED", "The provider rejected this API key.")
        if response.status_code != 200:
            raise EngineError(
                "PROVIDER_MODELS_FAILED",
                "The provider did not return a model list.",
                details={"status": response.status_code, "body": response.text[:300]},
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise EngineError("PROVIDER_BAD_RESPONSE", "The provider returned unreadable model data.") from exc
        rows = data.get("data") if isinstance(data, dict) else data
        models: list[ProviderModel] = []
        for item in rows or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            context = None
            for key in ("context_window", "context_length", "max_context_tokens", "max_model_len"):
                if isinstance(item.get(key), (int, float)):
                    context = int(item[key])
                    break
            models.append(ProviderModel(id=str(item["id"]), owned_by=item.get("owned_by"), context_window=context))
        models.sort(key=lambda m: m.id)
        return models

    async def probe_capabilities(self, hooks: AdapterHooks | None = None) -> ProviderCapabilities:
        hooks = hooks or AdapterHooks()
        caps = ProviderCapabilities(
            supports_json_schema=False,
            supports_json_schema_strict=False,
            supports_json_object=True,
            context_tokens=self.capabilities.context_tokens,
            max_output_tokens=self.capabilities.max_output_tokens,
            supports_vision=self.capabilities.supports_vision,
            supports_audio_transcription=self.capabilities.supports_audio_transcription,
        )
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        try:
            await self._chat_raw(
                messages=[
                    {"role": "system", "content": "Reply with JSON only."},
                    {"role": "user", "content": "Return true."},
                ],
                response_format={"type": "json_schema", "json_schema": {"name": "probe", "strict": True, "schema": schema}},
                max_tokens=320,
                hooks=hooks,
                operation="capability_probe",
            )
            caps.supports_json_schema = True
            caps.supports_json_schema_strict = True
            caps.probe_note = "Strict JSON schema accepted."
        except EngineError as strict_error:
            if strict_error.code in ("PROVIDER_AUTH_FAILED", "PROVIDER_MODEL_NOT_FOUND", "PROVIDER_UNREACHABLE"):
                raise
            try:
                await self._chat_raw(
                    messages=[
                        {"role": "system", "content": "Reply with JSON only."},
                        {"role": "user", "content": 'Return {"ok": true}.'},
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=320,
                    hooks=hooks,
                    operation="capability_probe",
                )
                caps.supports_json_object = True
                caps.probe_note = "Strict JSON schema rejected; JSON object mode accepted."
            except EngineError as obj_error:
                caps.supports_json_object = False
                caps.probe_note = "Structured output rejected; using prompt-constrained JSON."
                if obj_error.code in ("PROVIDER_AUTH_FAILED", "PROVIDER_MODEL_NOT_FOUND", "PROVIDER_UNREACHABLE"):
                    raise
        caps.probed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.capabilities = caps
        return caps

    # ---- structured chat -------------------------------------------------
    async def chat_structured(
        self,
        *,
        schema_model: type[T],
        system: str,
        user: str,
        operation: str,
        hooks: AdapterHooks | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> ChatResult:
        hooks = hooks or AdapterHooks()
        schema = schema_model.model_json_schema()
        attempts: list[str] = []
        if self.capabilities.supports_json_schema_strict:
            attempts = ["json_schema_strict", "json_object", "prompt"]
        elif self.capabilities.supports_json_schema:
            attempts = ["json_schema", "json_object", "prompt"]
        elif self.capabilities.supports_json_object:
            attempts = ["json_object", "prompt"]
        else:
            attempts = ["prompt"]

        last_error: Exception | None = None
        repair_note = ""
        for attempt_index, mode in enumerate(attempts):
            system_prompt = system
            if mode in ("json_object", "prompt"):
                system_prompt += (
                    "\n\nReturn a single JSON object that exactly matches this JSON Schema. "
                    "Do not add markdown fences or commentary.\n"
                    + json.dumps(schema, separators=(",", ":"))
                )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user + repair_note},
            ]
            response_format = None
            if mode == "json_schema_strict":
                response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_model.__name__, "strict": True, "schema": schema},
                }
            elif mode == "json_schema":
                response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_model.__name__, "strict": False, "schema": schema},
                }
            elif mode == "json_object":
                response_format = {"type": "json_object"}
            try:
                raw, usage, snapshot = await self._chat_raw(
                    messages=messages,
                    response_format=response_format,
                    max_tokens=max_tokens
                    or min(self.capabilities.max_output_tokens, 4096),
                    temperature=temperature,
                    hooks=hooks,
                    operation=operation,
                    estimated_tokens=estimate_tokens(system_prompt + user) + 900,
                )
            except EngineError as err:
                last_error = err
                if err.code in (
                    "PROVIDER_AUTH_FAILED",
                    "PROVIDER_MODEL_NOT_FOUND",
                    "PROVIDER_RATE_LIMITED",
                    "PROVIDER_UNREACHABLE",
                    "JOB_CANCELLED",
                ):
                    raise
                if mode != "prompt":
                    # The endpoint rejected this structured mode. Degrade once and remember.
                    if "response_format" in str(err.details).lower() or err.code in (
                        "PROVIDER_BAD_REQUEST",
                        "PROVIDER_SCHEMA_REJECTED",
                    ):
                        if mode.startswith("json_schema"):
                            self.capabilities.supports_json_schema = False
                            self.capabilities.supports_json_schema_strict = False
                        elif mode == "json_object":
                            self.capabilities.supports_json_object = False
                        continue
                continue
            content = _strip_json(raw)
            try:
                parsed = schema_model.model_validate_json(content)
            except (ValidationError, ValueError) as exc:
                last_error = exc
                if attempt_index < len(attempts) - 1 and mode == "json_schema_strict":
                    continue
                repair_note = (
                    "\n\nYour previous answer did not match the schema. Fix it and return only JSON. "
                    f"Validation error: {str(exc)[:900]}"
                )
                continue
            return ChatResult(
                parsed=parsed,
                model=self.model,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                rate_limit=snapshot,
                mode=mode,
            )
        if isinstance(last_error, EngineError):
            raise last_error
        raise EngineError(
            "PROVIDER_SCHEMA_FAILED",
            "The AI returned an answer this app could not validate. Try again, or choose a different model.",
            details={"error": str(last_error)[:500] if last_error else "unknown"},
            retryable=True,
        )

    async def _chat_raw(
        self,
        *,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None,
        max_tokens: int,
        temperature: float = 0.2,
        hooks: AdapterHooks | None = None,
        operation: str = "chat",
        estimated_tokens: int | None = None,
    ) -> tuple[str, dict[str, Any], RateLimitSnapshot | None]:
        hooks = hooks or AdapterHooks()
        estimated = estimated_tokens or estimate_tokens(
            " ".join(m["content"] for m in messages)
        ) + max_tokens
        wait = self.budget.wait_seconds(estimated)
        if wait > 0:
            await self._announce_wait(wait, "Waiting for this provider's token budget…", hooks)
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        attempt = 0
        while True:
            if hooks.cancel and hooks.cancel.is_set():
                raise CancelledError()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    await self._backoff(attempt, None, hooks)
                    continue
                self._log_request(hooks, operation, estimated, "timeout")
                raise EngineError(
                    "PROVIDER_TIMEOUT", "The AI provider did not answer in time.", retryable=True
                ) from exc
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    await self._backoff(attempt, None, hooks)
                    continue
                self._log_request(hooks, operation, estimated, "network_error")
                raise EngineError(
                    "PROVIDER_UNREACHABLE",
                    "The AI provider could not be reached. Check your connection.",
                    details={"error": str(exc)[:300]},
                    retryable=True,
                ) from exc

            snapshot = parse_rate_limit_headers(response.headers)
            self.last_snapshot = snapshot
            self.budget.update(snapshot)
            if response.status_code == 200:
                try:
                    data = response.json()
                    content = data["choices"][0]["message"].get("content") or ""
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise EngineError(
                        "PROVIDER_BAD_RESPONSE", "The AI provider returned an unreadable response."
                    ) from exc
                usage = data.get("usage") or {}
                actual_tokens = self.budget.record_usage(
                    usage, snapshot, fallback_tokens=estimated
                )
                self._log_request(hooks, operation, actual_tokens, "ok")
                if hooks.on_usage and usage:
                    hooks.on_usage(usage)
                if not content.strip():
                    raise EngineError(
                        "PROVIDER_EMPTY_RESPONSE",
                        "The AI provider returned an empty answer. Try again.",
                        retryable=True,
                    )
                return content, usage, snapshot

            body = response.text[:800]
            if response.status_code in (401, 403):
                self._log_request(hooks, operation, estimated, "auth_failed")
                raise EngineError("PROVIDER_AUTH_FAILED", "The AI provider rejected this API key.")
            if response.status_code == 404 or (
                response.status_code == 400 and "model" in body.lower() and "not" in body.lower()
            ):
                self._log_request(hooks, operation, estimated, "model_not_found")
                raise EngineError(
                    "PROVIDER_MODEL_NOT_FOUND",
                    "That model is not available on this provider. Choose another model in Settings.",
                    details={"model": self.model, "body": body},
                )
            if response.status_code == 429:
                retry_after = snapshot.retry_after_s
                if retry_after is None and snapshot.tokens_reset_s is not None:
                    retry_after = snapshot.tokens_reset_s
                retry_after = max(1.0, retry_after or 5.0)
                self._log_request(hooks, operation, estimated, "rate_limited")
                if attempt >= self.max_retries + 2:
                    raise RateLimited(retry_after, "The AI provider's rate limit was reached.")
                attempt += 1
                await self._announce_wait(
                    retry_after,
                    f"Waiting for the provider's rate limit ({int(retry_after)} s)…",
                    hooks,
                )
                continue
            if response.status_code >= 500:
                if attempt < self.max_retries:
                    attempt += 1
                    await self._backoff(attempt, snapshot.retry_after_s, hooks)
                    continue
                self._log_request(hooks, operation, estimated, "server_error")
                raise EngineError(
                    "PROVIDER_UNAVAILABLE",
                    "The AI provider is having trouble right now. Try again shortly.",
                    details={"status": response.status_code},
                    retryable=True,
                )
            self._log_request(hooks, operation, estimated, "bad_request")
            low = body.lower()
            if "response_format" in low or "json_schema" in low or "schema" in low:
                raise EngineError(
                    "PROVIDER_SCHEMA_REJECTED",
                    "This model does not accept the requested structured output format.",
                    details={"status": response.status_code, "body": body},
                )
            raise EngineError(
                "PROVIDER_BAD_REQUEST",
                "The AI provider rejected the request. Try a different model or provider.",
                details={"status": response.status_code, "body": redact_text(body)},
            )

    async def _announce_wait(self, seconds: float, reason: str, hooks: AdapterHooks) -> float:
        seconds = max(0.0, seconds)
        if hooks.on_wait:
            result = hooks.on_wait(seconds, reason)
            if asyncio.iscoroutine(result):
                await result
        await self._sleep_cancellable(seconds, hooks.cancel)
        self.budget.reset()
        return seconds

    async def _sleep_cancellable(self, seconds: float, cancel: asyncio.Event | None) -> None:
        if seconds <= 0:
            return
        if not cancel:
            await asyncio.sleep(seconds)
            return
        try:
            await asyncio.wait_for(cancel.wait(), timeout=seconds)
            raise CancelledError()
        except asyncio.TimeoutError:
            return

    async def _backoff(self, attempt: int, retry_after: float | None, hooks: AdapterHooks) -> None:
        delay = retry_after if retry_after else min(30.0, (2**attempt) + random.random())
        await self._sleep_cancellable(delay, hooks.cancel)

    def _log_request(self, hooks: AdapterHooks, operation: str, tokens: int, outcome: str) -> None:
        if hooks.on_request:
            try:
                hooks.on_request(self.adapter_name, self.model, operation, tokens, ["transcript", "clip metadata"], outcome)
            except Exception:
                pass

    async def generate_metadata(self, schema_model: type[T], system: str, user: str, hooks: AdapterHooks) -> ChatResult:
        return await self.chat_structured(
            schema_model=schema_model,
            system=system,
            user=user,
            operation="metadata",
            hooks=hooks,
            temperature=0.5,
        )


class GroqAdapter(OpenAICompatibleAdapter):
    adapter_name = "groq"

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("base_url", "https://api.groq.com/openai/v1")
        super().__init__(**kwargs)
        if self.model in STRICT_JSON_MODELS:
            self.capabilities.supports_json_schema = True
            self.capabilities.supports_json_schema_strict = True


class CustomEndpointAdapter(OpenAICompatibleAdapter):
    adapter_name = "custom"


class LocalLlamaAdapter(OpenAICompatibleAdapter):
    """Run a downloaded GGUF model in-process with llama.cpp.

    This adapter deliberately does not use any HTTP endpoint or API key. It is
    opt-in: the model and the optional llama-cpp runtime are installed locally,
    and the caller gets a clear setup error when either is missing.
    """

    adapter_name = "local"

    def __init__(
        self,
        *,
        model: str,
        model_path: Path | None = None,
        capabilities: ProviderCapabilities | None = None,
        llama_factory: Callable[..., Any] | None = None,
        context_tokens: int | None = None,
    ) -> None:
        caps = capabilities or ProviderCapabilities(
            supports_json_schema=False,
            supports_json_schema_strict=False,
            supports_json_object=False,
            supports_vision=False,
            supports_audio_transcription=False,
            context_tokens=context_tokens or 16384,
            max_output_tokens=4096,
            probe_note="Local GGUF model; structured output is prompt-constrained.",
        )
        super().__init__(
            base_url="local://llama",
            api_key="local",
            model=model,
            capabilities=caps,
        )
        self.model_path = Path(model_path) if model_path else None
        self._llama_factory = llama_factory
        self._llm: Any | None = None
        self._load_lock = asyncio.Lock()
        self._generate_lock = asyncio.Lock()

    async def list_models(self) -> list[ProviderModel]:
        return [
            ProviderModel(
                id=self.model,
                owned_by="local",
                context_window=self.capabilities.context_tokens,
            )
        ]

    async def _ensure_ready(self) -> None:
        """Check the file and runtime without loading the weights."""
        if self._llm is not None:
            return
        if self.model_path is None or not self.model_path.exists():
            raise EngineError(
                "LOCAL_MODEL_NOT_INSTALLED",
                "That local AI model is not installed. Download it in Model Manager first.",
                details={"model": self.model},
            )
        try:
            import llama_cpp  # noqa: F401
        except ImportError as exc:
            raise EngineError(
                "LOCAL_LLM_RUNTIME_MISSING",
                "Local AI is not available in this build. Reinstall Clipwright, or use a Groq/OpenAI-compatible provider.",
                details={"error": str(exc)[:300]},
            ) from exc

    async def _ensure_model(self) -> Any:
        if self._llm is not None:
            return self._llm
        async with self._load_lock:
            if self._llm is not None:
                return self._llm
            await self._ensure_ready()
            try:
                import llama_cpp

                factory = self._llama_factory or llama_cpp.Llama
                n_threads = max(1, min(8, os.cpu_count() or 4))
                model = await asyncio.to_thread(
                    factory,
                    model_path=str(self.model_path),
                    n_ctx=max(4096, int(self.capabilities.context_tokens or 16384)),
                    n_threads=n_threads,
                    n_batch=512,
                    verbose=False,
                    # CPU-only is intentional: it works on every supported
                    # machine and does not depend on a CUDA/ROCm build.
                    n_gpu_layers=0,
                )
            except EngineError:
                raise
            except Exception as exc:
                raise EngineError(
                    "LOCAL_LLM_LOAD_FAILED",
                    "The local AI model could not be loaded. Verify the model in Model Manager and try again.",
                    details={"error": str(exc)[:500]},
                ) from exc
            self._llm = model
            return model

    async def probe_capabilities(self, hooks: AdapterHooks | None = None) -> ProviderCapabilities:
        # Loading and generating once is the only honest test that the runtime
        # and GGUF actually work on this machine. It is still a tiny request.
        await self._ensure_ready()
        content, _usage = await self._generate(
            messages=[
                {"role": "system", "content": "Return only this JSON object: {\"ok\": true}"},
                {"role": "user", "content": "Return the object.\n\n/no_think"},
            ],
            max_tokens=24,
            temperature=0,
            hooks=hooks or AdapterHooks(),
            operation="probe",
        )
        try:
            json.loads(_strip_json(content))
        except (json.JSONDecodeError, ValueError) as exc:
            raise EngineError(
                "LOCAL_LLM_BAD_RESPONSE",
                "The local AI loaded but did not return JSON. Verify the model file and try again.",
                details={"error": str(exc)[:300]},
            ) from exc
        self.capabilities.probed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.capabilities.probe_note = "Local GGUF model loaded and answered a JSON probe."
        return self.capabilities

    async def _generate(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        hooks: AdapterHooks,
        operation: str,
    ) -> tuple[str, dict[str, Any]]:
        if hooks.cancel and hooks.cancel.is_set():
            raise CancelledError()
        model = await self._ensure_model()
        if hooks.cancel and hooks.cancel.is_set():
            raise CancelledError()
        async with self._generate_lock:
            if hooks.cancel and hooks.cancel.is_set():
                raise CancelledError()
            try:
                data = await asyncio.to_thread(
                    model.create_chat_completion,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=max(0.05, min(1.0, temperature)),
                    top_p=0.9,
                    repeat_penalty=1.05,
                )
                content = data["choices"][0]["message"].get("content") or ""
                usage = data.get("usage") or {}
            except (KeyError, IndexError, TypeError) as exc:
                raise EngineError(
                    "LOCAL_LLM_BAD_RESPONSE",
                    "The local AI returned an unreadable answer. Try again.",
                    details={"error": str(exc)[:300]},
                    retryable=True,
                ) from exc
            except Exception as exc:
                raise EngineError(
                    "LOCAL_LLM_FAILED",
                    "The local AI could not finish this request. Try again, or use a smaller transcript window.",
                    details={"error": str(exc)[:500]},
                    retryable=True,
                ) from exc
        if hooks.on_usage and usage:
            try:
                hooks.on_usage(usage)
            except Exception:
                pass
        self._log_request(hooks, operation, int(usage.get("total_tokens") or 0), "ok" if content.strip() else "empty")
        if not content.strip():
            raise EngineError(
                "LOCAL_LLM_EMPTY_RESPONSE",
                "The local AI returned an empty answer. Try again.",
                retryable=True,
            )
        return content, usage

    async def chat_structured(
        self,
        *,
        schema_model: type[T],
        system: str,
        user: str,
        operation: str,
        hooks: AdapterHooks | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> ChatResult:
        hooks = hooks or AdapterHooks()
        schema = schema_model.model_json_schema()
        system_prompt = (
            system
            + "\n\nReturn exactly one JSON object that matches this JSON Schema. "
            "Do not include markdown fences, commentary, or analysis. "
            "start_seg and end_seg must be only IDs such as \"s0000\"; "
            "never copy the pipe or timestamp from a transcript line.\n"
            + json.dumps(schema, separators=(",", ":"))
        )
        # Qwen3 supports a soft switch that suppresses its thinking block. We
        # tested the GGUF with /no_think; without it the 0.6B model can spend
        # the whole output budget reasoning instead of answering.
        last_error: Exception | None = None
        repair = ""
        for attempt in range(2):
            user_prompt = user + repair
            if "/no_think" not in user_prompt:
                user_prompt += "\n\n/no_think"
            content, usage = await self._generate(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens or min(int(self.capabilities.max_output_tokens or 4096), 4096),
                temperature=temperature,
                hooks=hooks,
                operation=operation,
            )
            try:
                parsed = schema_model.model_validate_json(_strip_json(content))
            except (ValidationError, ValueError) as exc:
                last_error = exc
                repair = (
                    "\n\nYour previous answer was not valid JSON for the schema. "
                    "Return only the corrected JSON object. Validation error: "
                    + str(exc)[:900]
                )
                continue
            return ChatResult(
                parsed=parsed,
                model=self.model,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                rate_limit=None,
                mode="prompt",
            )
        raise EngineError(
            "LOCAL_LLM_SCHEMA_FAILED",
            "The local AI could not produce a valid answer for this schema. Try a cloud provider for this analysis.",
            details={"error": str(last_error)[:500] if last_error else "unknown"},
            retryable=True,
        )
