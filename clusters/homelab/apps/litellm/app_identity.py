"""Attach database-authenticated caller identity to safe Langfuse telemetry."""

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger
from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger
from litellm.proxy._types import LitellmUserRoles
from litellm.proxy.litellm_pre_call_utils import clean_headers
from gateway import LOGGING_OVERRIDES, langfuse_config
from native_keys import APPS, provider_api_key


class AppAttribution(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        app = user_api_key_dict.key_alias
        if user_api_key_dict.user_role == LitellmUserRoles.PROXY_ADMIN:
            app = "operator"
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
        data["api_key"] = await provider_api_key()
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
            # Tool schemas can evict early attributes from the SDK's bounded span.
            if kwargs.get("model"):
                span.set_attribute("llm.model_name", kwargs["model"])

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
