"""Authenticate file-backed app keys and attach trusted Langfuse attribution."""

from hashlib import sha256
from pathlib import Path
from secrets import compare_digest

from fastapi import HTTPException, Request
from litellm.integrations.custom_logger import CustomLogger
from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.common_utils.http_parsing_utils import (
    _read_request_body, _safe_set_request_parsed_body,
)
from litellm.proxy.litellm_pre_call_utils import clean_headers
from gateway import LOGGING_OVERRIDES, langfuse_config

KEY_DIRECTORY = Path("/var/run/secrets/litellm-apps")
APPS = ("openclaw", "nofx", "multica", "n8n")
INFERENCE_PATHS = {"/chat/completions", "/completions", "/responses", "/embeddings"}


async def authenticate(request: Request, api_key: str) -> UserAPIKeyAuth:
    path = request.url.path.removeprefix("/v1")
    if request.method == "GET" and path in {"/health/liveliness", "/health/readiness"}:
        return UserAPIKeyAuth()
    if not api_key:
        raise HTTPException(401, "Missing gateway API key")
    for app in (*APPS, "operator"):
        token = (KEY_DIRECTORY / app).read_text().strip()
        if len(token) < 32 or token == "REPLACE_ME":
            raise HTTPException(503, "Gateway credentials are not initialized")
        if not compare_digest(api_key.encode(), token.encode()):
            continue
        if app != "operator" and not (
            request.method == "POST" and path in INFERENCE_PATHS
            or request.method == "GET" and path == "/models"
        ):
            raise HTTPException(403, "App keys permit inference and model discovery only")
        if request.method == "POST" and path in INFERENCE_PATHS:
            data = await _read_request_body(request)
            # Defense in depth; gateway admission must reject BEFORE native
            # authentication, including its failure logging, reads the body.
            if LOGGING_OVERRIDES.intersection(data):
                raise HTTPException(400, "Request-level logging overrides are disabled")
        if app != "operator" and request.method == "POST":
            if path != "/chat/completions" or data.get("model") != "openrouter/free":
                raise HTTPException(400, "Apps may call only OpenRouter free chat completions")
            if any(key in data for key in (
                "api_key", "api_base", "base_url", "custom_llm_provider", "headers", "extra_headers",
                "fallbacks", "context_window_fallbacks", "content_policy_fallbacks", "model_list",
                "extra_body", "models", "route", "deployment_id", "azure",
                "mock_response", "mock_tool_calls", "mock_timeout", "provider_specific_header", "ssl_verify",
            )):
                raise HTTPException(400, "Provider routing overrides are disabled")
            provider = (KEY_DIRECTORY / "openrouter").read_text().strip()
            if not provider.startswith("sk-or-") or len(provider) < 32:
                raise HTTPException(503, "OpenRouter credential is not initialized")
            data["api_key"] = provider
            _safe_set_request_parsed_body(request, data)
        return UserAPIKeyAuth(
            api_key=sha256(api_key.encode()).hexdigest(),
            key_alias=app,
            user_id=app,
            user_role=LitellmUserRoles.PROXY_ADMIN if app == "operator" else LitellmUserRoles.INTERNAL_USER,
        )
    raise HTTPException(401, "Invalid gateway API key")


class AppAttribution(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        app = user_api_key_dict.key_alias
        if app not in (*APPS, "operator"):
            raise HTTPException(403, "Missing authenticated app identity")
        # The caller cannot disable telemetry or replace its authenticated identity.
        if LOGGING_OVERRIDES.intersection(data):
            raise HTTPException(400, "Request-level logging overrides are disabled")
        metadata_key = "litellm_metadata" if call_type == "aresponses" else "metadata"
        metadata = data.setdefault(metadata_key, {})
        if not isinstance(metadata, dict):
            raise HTTPException(400, "metadata must be an object")
        metadata.update(trace_user_id=app, trace_name=app, tags=[f"app:{app}"],
                        trace_metadata={"app": app})
        # LiteLLM snapshots the inbound body before this hook. Provider keys
        # forwarded by apps must survive for inference, but never in that log copy.
        snapshot = data.get("proxy_server_request", {})
        body = snapshot.get("body", {})
        if isinstance(body, dict):
            for key in ("api_key", "aws_access_key_id", "aws_secret_access_key", "aws_session_token"):
                body.pop(key, None)
        # The SDK keeps separate header copies in the request and metadata.
        # Reuse its auth-header filter; also prohibit Langfuse identity overrides.
        for stored in (snapshot, metadata):
            stored["headers"] = {
                key: value for key, value in clean_headers(stored.get("headers", {})).items()
                if not key.lower().startswith("langfuse_")
            }
        return data


class SafeLangfuseLogger(LangfuseOtelLogger):
    def __init__(self):
        super().__init__(config=langfuse_config(), callback_name="langfuse_otel")

    def set_attributes(self, span, kwargs, response_obj):
        # Native auth failures can put the ORIGINAL bearer in a field named
        # user_api_key_hash. App attribution needs aliases, never this key field.
        standard = kwargs.get("standard_logging_object")
        if isinstance(standard, dict):
            kwargs = {**kwargs, "standard_logging_object": {**standard, "metadata": {
                key: value for key, value in (standard.get("metadata") or {}).items()
                if key != "user_api_key_hash"
            }}}
        super().set_attributes(span, kwargs, response_obj)
        # Streaming chat is still a model generation, not a generic OTEL span.
        if isinstance(standard, dict) and standard.get("call_type") in {"completion", "acompletion"}:
            span.set_attribute("langfuse.observation.type", "generation")

    @staticmethod
    def _error_summary(error):
        # Provider error bodies can echo credentials. Keep only type and HTTP status.
        summary = {"error_class": type(error).__name__}
        status = getattr(error, "status_code", None)
        if type(status) is int and 100 <= status <= 599:
            summary["error_code"] = str(status)
        return summary

    def _record_exception_on_span(self, span, kwargs):
        super()._record_exception_on_span(span, {"standard_logging_object": {
            "error_information": self._error_summary(kwargs.get("exception")),
        }})

    async def async_post_call_failure_hook(
        self, request_data, original_exception, user_api_key_dict, traceback_str=None,
    ):
        summary = self._error_summary(original_exception)
        # A new, unraised exception has no original context, cause or traceback.
        safe_error = Exception(" ".join(summary.values()))
        await super().async_post_call_failure_hook(
            request_data, safe_error, user_api_key_dict, traceback_str=None,
        )


attribution = AppAttribution()
langfuse = SafeLangfuseLogger()
