"""Run with litellm[proxy]==1.80.8 and opentelemetry-api==1.45.0."""

import asyncio
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Request
import httpx
import litellm
from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger
from litellm.litellm_core_utils.litellm_logging import StandardLoggingPayloadSetup
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from litellm.proxy.litellm_pre_call_utils import add_litellm_data_to_request
from litellm.proxy.types_utils.utils import get_instance_fn
from litellm.utils import get_optional_params

ROOT = Path(__file__).resolve().parents[2]
assert "tag: main-v1.80.8-stable@" in (ROOT / "clusters/homelab/apps/litellm/values.yaml").read_text(), \
    "Update the attribution check and CI dependency when changing the gateway version"
spec = importlib.util.spec_from_file_location(
    "app_identity", ROOT / "clusters/homelab/apps/litellm/app_identity.py"
)
identity = importlib.util.module_from_spec(spec)
# Import-time exporter setup needs runtime credentials; no collector in this check.
fixture_config = SimpleNamespace(protocol="otlp_http", otlp_auth_headers="Basic fixture")
with patch.object(LangfuseOtelLogger, "get_langfuse_otel_config", return_value=fixture_config), \
        patch.object(LangfuseOtelLogger, "__init__", return_value=None) as initialize:
    spec.loader.exec_module(identity)
assert initialize.call_args.kwargs["callback_name"] == "langfuse_otel"
assert initialize.call_args.kwargs["config"].headers == fixture_config.otlp_auth_headers
assert initialize.call_args.kwargs["config"].exporter == fixture_config.protocol


class Span:
    def __init__(self):
        self.attributes = {}
        self.exceptions = []
    def set_attribute(self, key, value):
        self.attributes[key] = value
    def record_exception(self, error):
        self.exceptions.append(str(error))
    def set_status(self, status):
        self.status = status
    def end(self, **kwargs):
        pass


async def check_failure_telemetry():
    marker = "test-provider-key-must-not-be-exported"
    data = {"api_key": marker, "metadata": {}, "proxy_server_request": {
        "headers": {"authorization": marker}, "body": {"api_key": marker},
    }}
    await identity.attribution.async_pre_call_hook(SimpleNamespace(key_alias="nofx"), None, data, "acompletion")
    spans, attempts, captured = [], [], {}
    finished = asyncio.Event()
    logger = identity.langfuse
    logger.config = initialize.call_args.kwargs["config"]
    logger.callback_name = "langfuse_otel"
    def start_span(**kwargs):
        span = Span()
        spans.append(span)
        return span
    logger.tracer = SimpleNamespace(start_span=start_span)
    native_failure = logger.async_log_failure_event
    async def failure(**kwargs):
        captured.update(kwargs)
        await native_failure(**kwargs)
        finished.set()
    def respond(request):
        attempts.append(request)
        assert request.headers["authorization"] == f"Bearer {marker}"
        return httpx.Response(400, json={"error": {"message": marker, "code": 400}}, request=request)
    # Real provider translation and logging; only the transport/exporter are inert.
    client = AsyncHTTPHandler.__new__(AsyncHTTPHandler)
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client.client_alias, client.timeout, client.event_hooks = "fixture", httpx.Timeout(2), None
    with patch.object(litellm, "callbacks", [logger]), \
            patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")), \
            patch.object(logger, "async_log_failure_event", side_effect=failure):
        try:
            await litellm.acompletion(
                model="openrouter/openrouter/free", messages=[{"role": "user", "content": "Reply OK"}],
                client=client, num_retries=0, **data,
            )
        except litellm.BadRequestError as error:
            original = error
        else:
            raise AssertionError("Expected the mock provider failure")
        await asyncio.wait_for(finished.wait(), 5)
    await client.close()
    assert len(attempts) == 1
    assert marker in str(original), "Do not alter the exception returned to the caller"
    assert captured["kwargs"]["exception"] is original
    assert marker in captured["kwargs"]["standard_logging_object"]["error_information"]["error_message"]
    logger.log_failure_event(**captured)  # Sync and async share the same protected path.
    assert len(spans) == 2
    for span in spans:
        assert span.attributes["error.type"] == "BadRequestError"
        assert span.attributes["error.code"] == "400"
        assert "error.message" not in span.attributes and "error.stack_trace" not in span.attributes
        assert not span.exceptions
    await logger.async_post_call_failure_hook(
        data, original, SimpleNamespace(parent_otel_span=Span()), traceback_str=marker,
    )
    assert spans[-1].attributes["exception"] == "BadRequestError 400"
    assert marker not in json.dumps([span.attributes for span in spans])
    assert marker in str(original) and original.__traceback__ is not None
    for status in (True, "400", 99, 600, None):
        error = Exception(marker)
        error.status_code = status
        assert logger._error_summary(error) == {"error_class": "Exception"}


def request(path="/v1/chat/completions", method="POST", headers=None):
    return Request({"type": "http", "path": path, "method": method,
                    "headers": [(key.encode(), value.encode()) for key, value in (headers or {}).items()],
                    "query_string": b"", "scheme": "http", "server": ("fixture", 80)})


async def denied(awaitable, status):
    try:
        await awaitable
    except HTTPException as error:
        assert error.status_code == status, error
    else:
        raise AssertionError(f"Expected HTTP {status}")


async def check():
    # NOFX's strict OpenRouter path must survive the provider translation.
    response_format = {"type": "json_schema", "json_schema": {
        "name": "decision", "strict": True, "schema": {"type": "object"}}}
    params = get_optional_params(model="openrouter/free", custom_llm_provider="openrouter",
                                 response_format=response_format,
                                 provider={"require_parameters": True})
    assert params["response_format"] == response_format
    assert params["provider"] == {"require_parameters": True}
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        # Like the container mount, the module path must not contain dots.
        shutil.copyfile(identity.__file__, Path(directory) / "app_identity.py")
        module_path = str(Path(directory) / "app_identity")
        with patch.object(LangfuseOtelLogger, "get_langfuse_otel_config", return_value=fixture_config), \
                patch.object(LangfuseOtelLogger, "__init__", return_value=None):
            assert callable(get_instance_fn(module_path + ".authenticate", config_file_path="/etc/litellm/config.yaml"))
            assert hasattr(get_instance_fn(module_path + ".attribution", config_file_path="/etc/litellm/config.yaml"), "async_pre_call_hook")
            assert isinstance(get_instance_fn(module_path + ".langfuse", config_file_path="/etc/litellm/config.yaml"), LangfuseOtelLogger)
        identity.KEY_DIRECTORY = Path(directory)
        for app in (*identity.APPS, "operator"):
            (identity.KEY_DIRECTORY / app).write_text(f"sk-{app}-" + "x" * 48)
        for app in identity.APPS:
            token = (identity.KEY_DIRECTORY / app).read_text()
            user = await identity.authenticate(request(), token)
            assert user.key_alias == app and user.user_id == app
            assert user.api_key == sha256(token.encode()).hexdigest()
            for path in ("/key/generate", "/config/update", "/user/new"):
                await denied(identity.authenticate(request(path), token), 403)
            await denied(identity.authenticate(request("/v1/models", "DELETE"), token), 403)
            for call_type, metadata_key in (("acompletion", "metadata"), ("aresponses", "litellm_metadata")):
                marker = "test-provider-key-must-not-be-exported"
                data = {
                    "api_key": marker,
                    metadata_key: {"trace_user_id": "spoofed", "session_id": "session-1",
                                   "user_api_key": user.api_key, "user_api_key_hash": user.api_key,
                                   "user_api_key_auth": user.model_dump(mode="json")},
                }
                # SDK ingestion keeps a second, separately copied metadata.headers.
                incoming = request("/v1/responses" if call_type == "aresponses" else "/v1/chat/completions", headers={
                    "authorization": marker, "x-litellm-api-key": token, "api-key": token,
                    "x-api-key": token, "x-goog-api-key": token, "ocp-apim-subscription-key": token,
                    "x-mcp-auth": token, "langfuse_trace_user_id": "spoofed", "x-request-id": "fixture-request",
                })
                with patch.dict(sys.modules, {"litellm.proxy.proxy_server": SimpleNamespace(
                        llm_router=None, premium_user=False, open_telemetry_logger=None)}):
                    data = await add_litellm_data_to_request(data, incoming, user, SimpleNamespace(), {}, "fixture")
                assert data[metadata_key]["headers"]["x-litellm-api-key"] == token
                result = await identity.attribution.async_pre_call_hook(user, None, data, call_type)
                metadata = result[metadata_key]
                assert metadata["session_id"] == "session-1"
                assert metadata["headers"] == {"x-request-id": "fixture-request"}, "Raw gateway key retained in SDK metadata snapshot"
                assert result["proxy_server_request"]["headers"] == {"x-request-id": "fixture-request"}
                exported = LangfuseOtelLogger._extract_langfuse_metadata({"litellm_params": {
                    "metadata": metadata, "proxy_server_request": result["proxy_server_request"],
                }})
                assert exported["trace_user_id"] == app
                assert exported["trace_metadata"] == {"app": app}
                assert exported["tags"] == [f"app:{app}"]
                assert result["api_key"] == marker, "Provider auth must survive for inference"
                assert marker not in json.dumps(result["proxy_server_request"], default=str)
                span = Span()
                response = {"choices": [{"message": {"role": "assistant", "content": "OK"}}],
                            "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9}}
                LangfuseOtelLogger.set_langfuse_otel_attributes(span, {
                    "model": "test", "messages": [{"role": "user", "content": "Reply OK"}],
                    "standard_logging_object": {"call_type": call_type,
                                                "metadata": StandardLoggingPayloadSetup.get_standard_logging_metadata(metadata),
                                                "model_parameters": {}},
                    "litellm_params": {"api_key": marker, "metadata": metadata,
                                       "proxy_server_request": result["proxy_server_request"]},
                }, response)
                assert marker not in json.dumps(span.attributes)
                assert token not in json.dumps(span.attributes)
                assert "Reply OK" in json.dumps(span.attributes)
                assert "OK" in json.dumps(span.attributes)
                assert span.attributes["llm.token_count.prompt"] == 8
                assert span.attributes["llm.token_count.completion"] == 1
                assert not span.exceptions
            await denied(identity.attribution.async_pre_call_hook(user, None, {"no-log": True}, "acompletion"), 400)
        await denied(identity.authenticate(request(), "wrong"), 401)
        await denied(identity.authenticate(request(), None), 401)
        await identity.authenticate(request("/health/readiness", "GET"), None)
        # LiteLLM hashes only sk-/JWT keys itself. Arbitrary rotated keys must
        # still remain absent from the returned auth object and log metadata.
        unprefixed = "operator-fixture-" + "z" * 48
        (identity.KEY_DIRECTORY / "operator").write_text(unprefixed)
        operator = await identity.authenticate(request(), unprefixed)
        assert operator.api_key == sha256(unprefixed.encode()).hexdigest()
        assert unprefixed not in operator.model_dump_json()
        # Secret volume rotation takes effect without restarting the gateway.
        old = (identity.KEY_DIRECTORY / "openclaw").read_text()
        (identity.KEY_DIRECTORY / "openclaw").write_text("sk-rotated-" + "y" * 48)
        await denied(identity.authenticate(request(), old), 401)
        (identity.KEY_DIRECTORY / "openclaw").write_text("REPLACE_ME")
        await denied(identity.authenticate(request(), old), 503)
    await check_failure_telemetry()
    print("LiteLLM app authentication, rotation, route isolation and safe Langfuse success/failure telemetry passed")


if __name__ == "__main__":
    asyncio.run(check())
