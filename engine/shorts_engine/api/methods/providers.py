from __future__ import annotations

import ipaddress
import os
import time
from typing import Any
from urllib.parse import urlparse

from ...common.errors import EngineError
from ...storage.repos import decamelize
from ..params import (
    Empty,
    ProviderIdParams,
    ProviderModelsParams,
    ProviderSaveParams,
    ProviderTestParams,
)
from ..registry import Registry


def register(registry: Registry) -> None:
    registry.add("provider.list", Empty, provider_list)
    registry.add("provider.save", ProviderSaveParams, provider_save)
    registry.add("provider.delete", ProviderIdParams, provider_delete)
    registry.add("provider.test", ProviderTestParams, provider_test)
    registry.add("provider.list_models", ProviderModelsParams, provider_list_models)


def _is_local_host(host: str) -> bool:
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return host.endswith(".local")


def validate_local_base_url(value: str) -> str:
    """Validate the opaque identifier used by the in-process local provider."""
    value = (value or "").strip().rstrip("/")
    name = value[len("local://") :] if value.startswith("local://") else ""
    if not name or not all(ch.isalnum() or ch in "._-" for ch in name):
        raise EngineError(
            "PROVIDER_URL_INVALID",
            "Choose a local model in Model Manager instead of typing an endpoint.",
        )
    return f"local://{name}"


def validate_base_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise EngineError("PROVIDER_URL_INVALID", "Enter a full endpoint URL, for example https://api.groq.com/openai/v1.")
    if parsed.username or parsed.password:
        raise EngineError("PROVIDER_URL_INVALID", "Do not put credentials in the endpoint URL.")
    if parsed.scheme == "http" and not _is_local_host(parsed.hostname or ""):
        raise EngineError(
            "PROVIDER_URL_INVALID",
            "Use https:// for remote endpoints. Plain http:// is allowed only for local servers on this machine or your LAN.",
        )
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    return value


def capabilities_for(adapter: str, model: str | None, stored: Any) -> Any:
    from ...ai.adapter import STRICT_JSON_MODELS
    from ...ai.schemas import ProviderCapabilities

    if adapter == "local":
        from ...models.catalog import LLM_MODELS

        spec = next((m for m in LLM_MODELS if m["name"] == (model or "")), None)
        return ProviderCapabilities(
            supports_json_schema=False,
            supports_json_schema_strict=False,
            supports_json_object=False,
            context_tokens=int(spec.get("context_tokens", 16384) if spec else 16384),
            max_output_tokens=4096,
            probe_note="Local GGUF model; output is constrained by the JSON prompt.",
        )

    if isinstance(stored, dict):
        try:
            caps = ProviderCapabilities.model_validate(stored)
        except Exception:
            caps = ProviderCapabilities()
    else:
        caps = stored or ProviderCapabilities()
    if adapter == "groq" and model:
        if model in STRICT_JSON_MODELS:
            caps.supports_json_schema = True
            caps.supports_json_schema_strict = True
        elif not caps.probed_at:
            caps.supports_json_schema = False
            caps.supports_json_schema_strict = False
        caps.supports_json_object = True
        if model.startswith("whisper"):
            caps.supports_audio_transcription = True
    return caps


def make_adapter(profile: dict[str, Any], api_key: str, model: str, app: Any | None = None) -> Any:
    from ...ai.adapter import CustomEndpointAdapter, GroqAdapter, LocalLlamaAdapter, OpenAICompatibleAdapter

    adapter_name = profile.get("adapter") or "openai_compatible"
    caps = capabilities_for(adapter_name, model, profile.get("capabilities"))
    if adapter_name == "local":
        local_name = model or (profile.get("baseUrl") or "").removeprefix("local://")
        ctx = getattr(app, "ctx", app)
        model_path = ctx.models.llm_path(local_name) if ctx is not None else None
        return LocalLlamaAdapter(model=local_name, model_path=model_path, capabilities=caps)
    kwargs = {
        "base_url": profile["baseUrl"],
        "api_key": api_key,
        "model": model,
        "capabilities": caps,
    }
    if adapter_name == "groq":
        return GroqAdapter(**kwargs)
    if adapter_name == "custom":
        return CustomEndpointAdapter(**kwargs)
    return OpenAICompatibleAdapter(**kwargs)


def resolve_key(profile: dict[str, Any], secrets: dict[str, str], *, required: bool = True) -> str:
    if profile.get("adapter") == "local":
        return "local"
    key = (secrets.get("apiKey") or "").strip()
    if key:
        return key
    if profile.get("adapter") == "groq":
        env = os.environ.get("GROQ_API_KEY", "").strip()
        if env:
            return env
    host = urlparse(profile.get("baseUrl") or "").hostname or ""
    if not required and not key:
        return ""
    if _is_local_host(host):
        return "local"
    raise EngineError(
        "PROVIDER_KEY_MISSING",
        "Add an API key for this provider in Settings. Keys are kept in your operating system's secure storage.",
    )


def default_profile(app) -> dict[str, Any]:
    profiles = app.ctx.providers.list()
    if not profiles:
        raise EngineError("PROVIDER_NOT_FOUND", "Add an AI provider in Settings first.")
    default_id = app.ctx.settings.get("providers", {}).get("defaultProfileId")
    if default_id:
        found = next((p for p in profiles if p["id"] == default_id), None)
        if found:
            return found
    return profiles[0]


def get_profile(app, profile_id: str | None) -> dict[str, Any]:
    if not profile_id:
        return default_profile(app)
    profile = app.ctx.providers.get(profile_id)
    if not profile:
        raise EngineError("PROVIDER_NOT_FOUND", "That provider profile no longer exists.")
    return profile


async def provider_list(app, params: Empty, secrets) -> dict[str, Any]:
    profiles = app.ctx.providers.list()
    default_id = app.ctx.settings.get("providers", {}).get("defaultProfileId")
    env_key = bool(os.environ.get("GROQ_API_KEY"))
    return {
        "providers": [
            {
                **p,
                "default": p["id"] == (default_id or (profiles[0]["id"] if profiles else None)),
                "envKeyAvailable": env_key and p.get("adapter") == "groq",
            }
            for p in profiles
        ],
        "defaultProfileId": default_id or (profiles[0]["id"] if profiles else None),
        "envKeyAvailable": env_key,
    }


async def provider_save(app, params: ProviderSaveParams, secrets) -> dict[str, Any]:
    data = decamelize(dict(params.profile))
    if "apiKey" in data:
        raise EngineError("SECRET_IN_PARAMS", "API keys must be sent through the secure secret channel, not saved with the profile.")
    name = str(data.get("name") or "").strip()
    if not name:
        raise EngineError("PROVIDER_NAME_REQUIRED", "Give this provider a name.")
    adapter = data.get("adapter") or "openai_compatible"
    if adapter not in ("groq", "openai_compatible", "custom", "local"):
        raise EngineError("PROVIDER_ADAPTER_INVALID", "Choose a supported provider type.")
    if adapter == "local":
        local_model = str(data.get("default_model") or "").strip()
        if not local_model:
            raise EngineError("PROVIDER_MODEL_REQUIRED", "Choose a downloaded local model.")
        base_url = f"local://{local_model}"
    else:
        base_url = validate_base_url(str(data.get("base_url") or ("https://api.groq.com/openai/v1" if adapter == "groq" else "")))
    caps = capabilities_for(adapter, data.get("default_model"), data.get("capabilities"))
    saved = app.ctx.providers.save(
        {
            "id": data.get("id"),
            "name": name,
            "adapter": adapter,
            "base_url": base_url,
            "default_model": data.get("default_model") or None,
            "capabilities": caps.model_dump(by_alias=True),
            "enabled": data.get("enabled", True),
        }
    )
    if not app.ctx.settings.get("providers", {}).get("defaultProfileId"):
        app.ctx.settings.set("providers", {"defaultProfileId": saved["id"]})
    if data.get("default"):
        app.ctx.settings.set("providers", {"defaultProfileId": saved["id"]})
    return {"provider": saved}


async def provider_delete(app, params: ProviderIdParams, secrets) -> dict[str, Any]:
    app.ctx.providers.delete(params.profileId)
    current = app.ctx.settings.get("providers", {})
    if current.get("defaultProfileId") == params.profileId:
        remaining = app.ctx.providers.list()
        app.ctx.settings.set("providers", {"defaultProfileId": remaining[0]["id"] if remaining else None})
    return {"ok": True}


async def provider_test(app, params: ProviderTestParams, secrets) -> dict[str, Any]:
    if params.profileId:
        profile = get_profile(app, params.profileId)
    else:
        adapter_name = params.adapter or "openai_compatible"
        profile = {
            "id": None,
            "name": "Test endpoint",
            "adapter": adapter_name,
            "baseUrl": (
                validate_local_base_url(params.baseUrl or f"local://{params.model or ''}")
                if adapter_name == "local"
                else validate_base_url(params.baseUrl or "")
            ),
            "default_model": params.model,
            "capabilities": {},
        }
    if profile.get("adapter") == "local":
        base_url = validate_local_base_url(params.baseUrl or profile["baseUrl"])
    else:
        base_url = validate_base_url(params.baseUrl or profile["baseUrl"])
    profile = {**profile, "baseUrl": base_url}
    key = resolve_key(profile, secrets, required=True)
    model = params.model or profile.get("defaultModel") or profile.get("default_model")
    started = time.monotonic()
    adapter = make_adapter(profile, key, model or "", app=app)
    models = await adapter.list_models()
    if not model and models:
        model = models[0].id
        adapter = make_adapter(profile, key, model, app=app)
    latency_ms = round((time.monotonic() - started) * 1000, 1)
    caps = adapter.capabilities
    probe_error = None
    if params.probe and model:
        try:
            caps = await adapter.probe_capabilities()
        except EngineError as exc:
            # A local model probe is a real setup check; a missing runtime or
            # corrupt GGUF must fail the test, not be hidden behind ok: true.
            if profile.get("adapter") == "local":
                raise
            probe_error = exc.to_dict()
    if params.profileId:
        app.ctx.providers.set_capabilities(params.profileId, caps.model_dump(by_alias=True))
        if params.model:
            saved = app.ctx.providers.get(params.profileId)
            if saved:
                app.ctx.providers.save({**saved, "default_model": params.model})
    return {
        "ok": True,
        "latencyMs": latency_ms,
        "modelCount": len(models),
        "models": [m.model_dump() for m in models[:100]],
        "chosenModel": model,
        "capabilities": caps.model_dump(by_alias=True),
        "rateLimit": adapter.last_snapshot.as_dict() if adapter.last_snapshot else None,
        "probeError": probe_error,
        "baseUrl": base_url,
    }


async def provider_list_models(app, params: ProviderModelsParams, secrets) -> dict[str, Any]:
    profile = get_profile(app, params.profileId)
    key = resolve_key(profile, secrets, required=True)
    model = profile.get("defaultModel") or ""
    adapter = make_adapter(profile, key, model, app=app)
    models = await adapter.list_models()
    return {"models": [m.model_dump() for m in models], "baseUrl": profile["baseUrl"]}
