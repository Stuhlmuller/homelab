"""Authenticate file-backed app keys and attach trusted Langfuse attribution."""

from hashlib import sha256
from pathlib import Path
from secrets import compare_digest

from fastapi import HTTPException, Request
from litellm.integrations.custom_logger import CustomLogger
from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger
from litellm.integrations.opentelemetry import OpenTelemetryConfig
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth

KEY_DIRECTORY = Path("/var/run/secrets/litellm-apps")
APPS = ("openclaw", "nofx", "multica")
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
        for key in ("success_callback", "failure_callback", "callbacks", "no-log"):
            if key in data:
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
        # LiteLLM's Langfuse integration lets these headers override metadata.
        headers = snapshot.get("headers", {})
        for key in list(headers):
            if key.lower().startswith("langfuse_") or key.lower() in {
                "authorization", "x-api-key", "x-litellm-api-key", "api-key",
            }:
                del headers[key]
        return data


class SafeLangfuseLogger(LangfuseOtelLogger):
    def __init__(self):
        config = self.get_langfuse_otel_config()
        super().__init__(
            config=OpenTelemetryConfig(exporter=config.protocol, headers=config.otlp_auth_headers),
            callback_name="langfuse_otel",
        )

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
