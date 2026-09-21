"""Authenticate file-backed app keys and attach trusted Langfuse attribution."""

from pathlib import Path
from secrets import compare_digest

from fastapi import HTTPException, Request
from litellm.integrations.custom_logger import CustomLogger
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth

KEY_DIRECTORY = Path("/var/run/secrets/litellm-apps")
APPS = ("openclaw", "nofx", "n8n", "multica")
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
            api_key=api_key,
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
        # LiteLLM's Langfuse integration lets these headers override metadata.
        headers = data.get("proxy_server_request", {}).get("headers", {})
        for key in list(headers):
            if key.lower().startswith("langfuse_"):
                del headers[key]
        return data


attribution = AppAttribution()
