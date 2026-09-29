"""Run on Python 3.13 with litellm[proxy]==1.80.8, openai==2.8.0,
httpx==0.28.1 and opentelemetry-sdk==1.25.0.
"""

import asyncio
from contextvars import ContextVar
from datetime import datetime
from hashlib import sha256
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import click
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
import litellm
import yaml
from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger
from litellm.integrations.opentelemetry import OpenTelemetryConfig
from litellm.litellm_core_utils.litellm_logging import StandardLoggingPayloadSetup
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from litellm.llms.openai.openai import OpenAIChatCompletion
from litellm.proxy._types import ProxyException
from litellm.proxy.common_utils.http_parsing_utils import _read_request_body
from litellm.proxy.litellm_pre_call_utils import add_litellm_data_to_request
from litellm.proxy.types_utils.utils import get_instance_fn
from litellm.proxy.utils import ProxyLogging
from litellm.types.utils import StandardCallbackDynamicParams
from litellm.utils import get_optional_params
from opentelemetry.sdk.trace import TracerProvider

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "clusters/homelab/apps/litellm"))
gateway_launcher = importlib.import_module("gateway")
assert "tag: main-v1.80.8-stable@" in (ROOT / "clusters/homelab/apps/litellm/values.yaml").read_text(), \
    "Update the attribution check and CI dependency when changing the gateway version"
values = yaml.safe_load((ROOT / "clusters/homelab/apps/litellm/values.yaml").read_text())
assert values["command"] == ["python", "/etc/litellm-hooks/gateway.py"], "Native CLI alone bypasses admission"
assert values["numWorkers"] == 1, "Guarded gateway scales Pods, not worker processes"
kustomization = yaml.safe_load((ROOT / "clusters/homelab/apps/litellm/kustomization.yaml").read_text())
hook_map = next(item for item in kustomization["configMapGenerator"] if item["name"] == "litellm-app-identity")
assert {"gateway.py", "app_identity.py"} <= set(hook_map["files"]), "Mount launcher and callback together"
spec = importlib.util.spec_from_file_location(
    "app_identity", ROOT / "clusters/homelab/apps/litellm/app_identity.py"
)
identity = importlib.util.module_from_spec(spec)
# Import-time exporter setup needs runtime credentials; no collector in this check.
# Exercise file-backed exporter setup without publishing credentials or contacting a collector.
with patch.object(Path, "read_text", side_effect=["pk-fixture", "sk-fixture"]):
    exporter_config = gateway_launcher.langfuse_config()
assert exporter_config.endpoint == "http://langfuse-web.langfuse.svc.cluster.local:3000/api/public/otel/v1/traces"
assert exporter_config.headers == "Authorization=Basic cGstZml4dHVyZTpzay1maXh0dXJl"
with patch.object(Path, "read_text", side_effect=["REPLACE_ME", "sk-fixture"]):
    try:
        gateway_launcher.langfuse_config()
    except ValueError:
        pass
    else:
        raise AssertionError("Placeholder Langfuse credentials accepted")
fixture_config = OpenTelemetryConfig(exporter="otlp_http", headers="Authorization=Basic fixture")
with patch.object(gateway_launcher, "langfuse_config", return_value=fixture_config), \
        patch.object(LangfuseOtelLogger, "__init__", return_value=None) as initialize:
    spec.loader.exec_module(identity)
assert initialize.call_args.kwargs["callback_name"] == "langfuse_otel"
assert initialize.call_args.kwargs["config"].headers == fixture_config.headers
assert initialize.call_args.kwargs["config"].exporter == fixture_config.exporter
# Initialize native callback bookkeeping without networking or proxy globals.
with patch.object(LangfuseOtelLogger, "_init_otel_logger_on_litellm_proxy"):
    LangfuseOtelLogger.__init__(identity.langfuse, callback_name="langfuse_otel",
        config=OpenTelemetryConfig(headers=fixture_config.headers), tracer_provider=TracerProvider())


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
    async def receive():
        return {"type": "http.request", "body": b"{}"}
    return Request({"type": "http", "path": path, "method": method,
                    "headers": [(key.encode(), value.encode()) for key, value in (headers or {}).items()],
                    "query_string": b"", "scheme": "http", "server": ("fixture", 80)}, receive=receive)


async def denied(awaitable, status):
    try:
        await awaitable
    except HTTPException as error:
        assert error.status_code == status, error
    else:
        raise AssertionError(f"Expected HTTP {status}")


async def check_admission():
    """Pure ASGI admission preserves raw bodies, context and response streaming."""
    state = ContextVar("admission_fixture", default="outside")
    reached, outgoing = [], []
    async def downstream(scope, receive, send):
        reached.append(scope["type"])
        state.set("inside")
        if scope["type"] != "http":
            return
        frame = await receive()
        assert frame["body"] == b'{"model":"fixture"}' and frame["more_body"] is False
        assert await receive() == {"type": "http.disconnect"}
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"data: first\n\n", "more_body": True})
        await send({"type": "http.response.body", "body": b"data: [DONE]\n\n"})
    guard = gateway_launcher.TelemetryAdmission(downstream)
    async def invoke(raw, cached=None, content_type=b"application/json", path="/v1/chat/completions", root_path=""):
        frames = iter(({"type": "http.request", "body": raw[:4], "more_body": True},
                       {"type": "http.request", "body": raw[4:], "more_body": False},
                       {"type": "http.disconnect"}))
        async def receive():
            return next(frames)
        async def send(message):
            outgoing.append(message)
        scope = dict(request().scope)
        scope["path"] = path
        scope["root_path"] = root_path
        scope["headers"] = [(b"content-type", content_type), (b"content-length", b"1")]
        if cached is not None:
            scope["parsed_body"] = (tuple(cached), cached)
        outgoing.clear()
        await guard(scope, receive, send)
        return outgoing[0]["status"]
    assert await invoke(b'{"model":"fixture"}') == 200
    assert state.get() == "inside"
    assert outgoing[1]["more_body"] and outgoing[1]["body"] == b"data: first\n\n"
    for raw, cache, content_type in (
        (b'{"model":"fixture"}', {"langfuse_secret_key": None}, b"application/json"),
        (b"callbacks=langfuse_otel", None, b"application/x-www-form-urlencoded"),
        (b"[]", None, b"application/json"), (b"{", None, b"application/json"),
    ):
        assert await invoke(raw, cache, content_type) == 400
    assert reached == ["http"]
    for path in ("/v1beta/models/fixture:generateContent", "/guardrails/apply_guardrail",
                 "/openai/v1/chat/completions", "/openai/deployments/fixture/chat/completions"):
        assert await invoke(b'{"callbacks":[]}', path=path) == 400
    assert await invoke(b'{"callbacks":[]}', path="/gateway/v1/chat/completions", root_path="/gateway") == 400
    with patch.object(gateway_launcher, "MAX_BODY_BYTES", 16):
        assert await invoke(b'{"model":"fixture"}') == 413, "Count bytes, not the misleading Content-Length"
    async def disconnected():
        return {"type": "http.disconnect"}
    outgoing.clear()
    await guard(request().scope, disconnected, outgoing.append)
    assert not outgoing
    assert reached == ["http"]
    await guard({"type": "lifespan"}, None, None)
    assert reached == ["http", "lifespan"]


def check_launcher():
    """Run native CLI/lifespan/HTTP with fixture secrets and inert network sinks."""
    from litellm.proxy import proxy_server
    import uvicorn
    from uvicorn.importer import import_from_string
    from uvicorn.lifespan.on import LifespanOn
    native_app = proxy_server.app
    native_lifespan = native_app.router.lifespan_context
    native_init = LangfuseOtelLogger.__init__
    def initialize_logger(self, *args, **kwargs):
        kwargs["tracer_provider"] = TracerProvider()
        native_init(self, *args, **kwargs)
    async def exercise(kwargs):
        lifespan = LifespanOn(uvicorn.Config(**kwargs, lifespan="on"))
        await lifespan.startup()
        assert not lifespan.should_exit, "Native proxy startup failed"
        try:
            proxy_server.user_custom_auth.__globals__["KEY_DIRECTORY"] = Path(directory)
            assert proxy_server.general_settings["custom_auth"] == fixture_auth
            assert len(proxy_server.llm_router.model_list) == 2
            logger = next(callback for callback in litellm.callbacks
                          if isinstance(callback, LangfuseOtelLogger))
            spans, attempts = [], []
            finished = asyncio.Event()
            def start_span(**kwargs):
                span = Span()
                spans.append(span)
                return span
            logger.tracer = SimpleNamespace(start_span=start_span)
            success = logger.async_log_success_event
            async def exported(**kwargs):
                await success(**kwargs)
                finished.set()
            def respond(request):
                attempts.append(request)
                assert request.url == "https://openrouter.ai/api/v1/chat/completions"
                assert request.headers["authorization"] == "Bearer fixture-upstream"
                assert "x-litellm-api-key" not in request.headers
                assert json.loads(request.content)["model"] == "openrouter/free"
                return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 1,
                    "model": "openrouter/free", "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9},
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]})
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as provider_client, \
                    httpx.AsyncClient(transport=httpx.ASGITransport(native_app), base_url="http://fixture") as http:
                with patch.object(OpenAIChatCompletion, "_get_async_http_client", return_value=provider_client), \
                        patch.object(logger, "async_log_success_event", side_effect=exported):
                    body = {"model": "openrouter/free", "messages": [{"role": "user", "content": "Reply OK"}]}
                    headers = {"Authorization": "Bearer fixture-upstream", "x-litellm-api-key": fixture_key}
                    rejected = await http.post("/v1/chat/completions", headers=headers,
                        json={**body, "callbacks": ["langfuse_otel"]})
                    assert rejected.status_code == 400 and not attempts
                    result = await http.post("/v1/chat/completions", headers=headers, json=body)
                    assert result.status_code == 200, result.text
                    assert result.json()["usage"]["total_tokens"] == 9
                    await asyncio.wait_for(finished.wait(), 5)
            assert len(attempts) == 1
            assert sum(span.attributes.get("llm.token_count.prompt") == 8 for span in spans) == 1
            assert fixture_key not in str([span.attributes for span in spans])
            assert "fixture-upstream" not in str([span.attributes for span in spans])
        finally:
            await lifespan.shutdown()
            assert not lifespan.should_exit, "Native proxy shutdown failed"
    def run_uvicorn(**kwargs):
        assert kwargs["workers"] == 1 and kwargs["port"] == 4888
        assert import_from_string(kwargs["app"]) is native_app
        assert native_app.router.lifespan_context is native_lifespan
        assert native_app.user_middleware[0].cls is gateway_launcher.TelemetryAdmission
        async def exercise_all():
            await exercise(kwargs)
            # LiteLLM's global logging worker belongs to one event loop, as in
            # production; keep the remaining SDK fixtures in that same loop.
            await check()
        asyncio.run(exercise_all())
    with tempfile.TemporaryDirectory(dir="/tmp") as directory, \
            patch.dict(os.environ, {"NUM_WORKERS": "7", "WEB_CONCURRENCY": "8", "OPENAI_API_KEY": "unused"}, clear=True), \
            patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")), \
            patch.object(gateway_launcher, "langfuse_config", return_value=fixture_config), \
            patch.object(LangfuseOtelLogger, "_init_otel_logger_on_litellm_proxy"), \
            patch.object(LangfuseOtelLogger, "__init__", new=initialize_logger), \
            patch.object(uvicorn, "run", side_effect=run_uvicorn) as serve:
        fixture_key = "sk-openclaw-" + "x" * 48
        for name in (*identity.APPS, "operator"):
            (Path(directory) / name).write_text(fixture_key if name == "openclaw" else "sk-other-" + name + "x" * 48)
        shutil.copyfile(identity.__file__, Path(directory) / "app_identity.py")
        config = yaml.safe_load((ROOT / "clusters/homelab/apps/litellm/values.yaml").read_text())["proxy_config"]
        fixture_auth = str(Path(directory) / "app_identity") + ".authenticate"
        config["general_settings"]["custom_auth"] = fixture_auth
        config["litellm_settings"]["callbacks"] = [str(Path(directory) / "app_identity") + suffix
                                                    for suffix in (".attribution", ".langfuse")]
        config_path = Path(directory) / "config.yaml"
        config_path.write_text(yaml.safe_dump(config))
        gateway_launcher.main(["--config", str(config_path), "--port", "4888", "--num_workers", "3"])
        serve.assert_called_once()
        config = json.loads(os.environ["WORKER_CONFIG"])
        assert config["config"] == str(config_path)
        for flag in ("--run_gunicorn", "--run_hypercorn", "--local"):
            try:
                gateway_launcher.main([flag])
            except click.ClickException:
                pass
            else:
                raise AssertionError(f"Launcher accepted alternate server {flag}")
        serve.assert_called_once()
    print("Native CLI, ASGI lifespan, app-key loading and mocked inference passed with one guarded Uvicorn worker")


async def check_openclaw_gateway():
    """Real SDK auth, preprocessing, Router and streaming; inert HTTP/exporter."""
    auth = importlib.import_module("litellm.proxy.auth.user_api_key_auth")
    gateway = (identity.KEY_DIRECTORY / "openclaw").read_text()
    provider = "sk-or-test-openrouter-provider-key"
    (identity.KEY_DIRECTORY / "openrouter").write_text(provider)
    model = "openrouter/free"
    spans, attempts, prepared, logging_setups = [], [], [], []
    finished = asyncio.Event()
    logger = identity.langfuse
    logger.callback_name, logger.message_logging, logger.turn_off_message_logging = "langfuse_otel", True, False
    logger._operation_duration_histogram = logger._token_usage_histogram = logger._cost_histogram = None
    def start_span(**kwargs):
        span = Span()
        spans.append(span)
        return span
    logger.tracer = SimpleNamespace(start_span=start_span)
    native_success, native_failure = logger.async_log_success_event, logger.async_log_failure_event
    async def success(**kwargs):
        await native_success(**kwargs)
        finished.set()
    async def failure(**kwargs):
        await native_failure(**kwargs)
        finished.set()
    usage = {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9}
    def respond(incoming):
        payload = json.loads(incoming.content)
        attempts.append(payload)
        assert incoming.url == "https://openrouter.ai/api/v1/chat/completions"
        assert incoming.headers["authorization"] == f"Bearer {provider}"
        assert "x-litellm-api-key" not in incoming.headers
        assert gateway not in str(incoming.headers) + incoming.content.decode()
        assert payload["model"] == model and "api_key" not in payload
        if payload["messages"][0]["content"] == "NOFX strict fixture":
            assert payload["response_format"] == {"type": "json_schema", "json_schema": {
                "name": "decision", "strict": True, "schema": {"type": "object"}}}
            assert payload["provider"] == {"require_parameters": True}
        if payload["messages"][0]["content"] == "failure fixture":
            return httpx.Response(400, json={"error": {"message": provider, "code": 400}}, request=incoming)
        common = {"id": "fixture-1", "model": model, "created": 0}
        if payload.get("stream"):
            assert payload.get("stream_options", {}) in ({}, {"include_usage": True})
            # OpenRouter repeats the terminal choice in its final usage chunk:
            # https://openrouter.ai/docs/api_reference/streaming
            terminal = {"index": 0, "delta": {"role": "assistant", "content": ""},
                        "finish_reason": "stop", "native_finish_reason": "stop"}
            chunks = [
                {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "OK"}, "finish_reason": None}]},
                {"choices": [terminal]},
                {"choices": [terminal], "usage": usage},
            ]
            events = ["data: " + json.dumps({**common, "object": "chat.completion.chunk", **chunk}) for chunk in chunks]
            events.insert(2, ": OPENROUTER PROCESSING")  # SSE heartbeat must not terminate usage collection.
            body = "\n\n".join(events) + "\n\ndata: [DONE]\n\n"
            return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}, request=incoming)
        return httpx.Response(200, json={**common, "object": "chat.completion", "usage": usage,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]},
            request=incoming)
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    model_list = yaml.safe_load((ROOT / "clusters/homelab/apps/litellm/values.yaml").read_text())["proxy_config"]["model_list"]
    router = litellm.Router(model_list=[entry for entry in model_list if entry["model_name"] == model],
                           num_retries=0, disable_cooldowns=True, default_litellm_params={"num_retries": 0})
    proxy = SimpleNamespace(
        general_settings={}, jwt_handler=None, litellm_proxy_admin_name="operator", llm_model_list=router.model_list,
        llm_router=router, master_key="unused", model_max_budget_limiter=None, open_telemetry_logger=None,
        prisma_client=None, proxy_logging_obj=SimpleNamespace(post_call_failure_hook=AsyncMock()),
        user_api_key_cache=None, user_custom_auth=identity.authenticate, premium_user=False,
    )
    app = FastAPI()
    app.add_middleware(gateway_launcher.TelemetryAdmission)
    @app.exception_handler(ProxyException)
    async def proxy_error(request, error):
        return JSONResponse({"error": error.message}, status_code=int(error.code))
    @app.post("/v1/responses")
    @app.post("/v1/embeddings")
    @app.post("/v1/completions")
    @app.post("/v1/chat/completions")
    async def completion(request: Request, user=Depends(auth.user_api_key_auth)):
        data = await add_litellm_data_to_request(await _read_request_body(request), request, user, SimpleNamespace(), {}, "fixture")
        assert "authorization" not in data["proxy_server_request"]["headers"]
        # Production initializes Logging (and extracts dynamic callback controls)
        # BEFORE invoking the custom pre-call hook.
        data["litellm_call_id"] = str(uuid4())
        logging_obj, data = litellm.utils.function_setup(
            original_function="acompletion", rules_obj=litellm.utils.Rules(), start_time=datetime.now(), **data,
        )
        data["litellm_logging_obj"] = logging_obj
        logging_setups.append(logging_obj)
        data = await identity.attribution.async_pre_call_hook(user, None, data, "acompletion")
        assert logger.get_tracer_to_use_for_request({
            "standard_callback_dynamic_params": logging_obj.standard_callback_dynamic_params,
        }) is logger.tracer
        assert logger._get_headers_dictionary(logger.OTEL_HEADERS) == {"Authorization": "Basic fixture"}
        prepared.append(data)
        if user.key_alias != "openclaw" and "api_key" not in data:
            return {"unaffected": user.key_alias}
        finished.clear()
        try:
            result = await router.acompletion(**data)
            if data.get("stream"):
                chunks = [chunk async for chunk in result]
                assert "".join(choice.delta.content or "" for chunk in chunks for choice in chunk.choices) == "OK"
                if data.get("stream_options", {}).get("include_usage"):
                    assert any(getattr(chunk, "usage", None) and chunk.usage.total_tokens == 9 for chunk in chunks), \
                        [chunk.model_dump(exclude_none=True) for chunk in chunks]
            else:
                assert result.usage.total_tokens == 9 and result.choices[0].message.content == "OK"
        except litellm.BadRequestError as error:
            assert provider in str(error), "Caller retains original provider error, unlike telemetry"
            await asyncio.wait_for(finished.wait(), 5)
            return {"expected_failure": True}
        await asyncio.wait_for(finished.wait(), 5)
        return {"ok": True}
    try:
        with patch.dict(sys.modules, {"litellm.proxy.proxy_server": proxy}), \
                patch.object(auth, "enterprise_custom_auth", None), \
                patch.object(auth.verbose_proxy_logger, "error") as auth_errors, \
                patch.object(OpenAIChatCompletion, "_get_async_http_client", return_value=client), \
                patch.object(litellm, "callbacks", [logger]), \
                patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")), \
                patch.object(logger, "async_log_success_event", side_effect=success), \
                patch.object(logger, "async_log_failure_event", side_effect=failure), \
                patch.object(logger, "_get_tracer_with_dynamic_headers", return_value=logger.tracer) as dynamic_tracer:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as gateway_client:
                headers = {"Authorization": f"Bearer {provider}", "x-litellm-api-key": gateway}
                body = {"model": model, "messages": [{"role": "user", "content": "Reply OK"}]}
                # Auth failures also run function_setup on the original body.
                rejected = asyncio.Event()
                async def log_rejection(**kwargs):
                    await ProxyLogging._handle_logging_proxy_only_error(
                        proxy.proxy_logging_obj, request_data=kwargs["request_data"],
                        user_api_key_dict=kwargs["user_api_key_dict"], route=kwargs["route"],
                        original_exception=kwargs["original_exception"],
                    )
                    rejected.set()
                with patch.object(proxy.proxy_logging_obj, "post_call_failure_hook", side_effect=log_rejection) as auth_failure, \
                        patch.object(auth, "pre_db_read_auth_checks", wraps=auth.pre_db_read_auth_checks) as pre_auth:
                    for credentials in (headers, {"Authorization": "Bearer wrong"}, {}):
                        for extra in ({}, {"api_base": "https://untrusted.invalid"}):
                            result = await gateway_client.post("/v1/chat/completions", headers=credentials, json={
                                **body, **extra, "langfuse_public_key": "fixture-public", "langfuse_secret_key": "fixture-secret",
                            })
                            assert result.status_code == 400
                    pre_auth.assert_not_called()
                    auth_failure.assert_not_called()
                    assert not rejected.is_set(), "Admission must reject before native auth failure logging"
                    assert not dynamic_tracer.called, "Auth rejection re-extracted caller collector credentials"
                    # Ordinary auth errors still use the native failure pipeline;
                    # even an echoed provider credential must not reach spans.
                    for credentials, extra, expected in (
                        ({"Authorization": "Bearer wrong"}, {"api_key": provider}, 401),
                        ({}, {"api_key": provider}, 401), (headers, {"api_base": "https://untrusted.invalid"}, 401),
                    ):
                        rejected.clear()
                        result = await gateway_client.post("/v1/chat/completions", headers=credentials,
                            json={**body, **extra})
                        assert result.status_code == expected, result.text
                        await asyncio.wait_for(rejected.wait(), 5)
                        assert not dynamic_tracer.called
                controls = [{"langfuse_public_key": "fixture-public", "langfuse_secret_key": "fixture-secret"}]
                controls += [{key: None} for key in StandardCallbackDynamicParams.__annotations__]
                controls += [{key: []} for key in ("callbacks", "success_callback", "failure_callback")]
                controls += [{"no-log": True}]
                for caller in (*identity.APPS, "operator"):
                    for path in ("/v1/chat/completions", "/v1/completions", "/v1/responses", "/v1/embeddings"):
                        for override in controls:
                            result = await gateway_client.post(path, headers={
                                **headers, "x-litellm-api-key": (identity.KEY_DIRECTORY / caller).read_text()},
                                json={**body, **override})
                            assert result.status_code == 400, f"{caller} accepted logging override; collector redirected={dynamic_tracer.called}"
                            assert not logging_setups, "Reject before function_setup extracts callback controls"
                            assert not attempts and not dynamic_tracer.called
                for stream, include_usage in ((False, False), (True, True), (True, False)):
                    for fail in (False, True):
                        candidate = {**body, "stream": stream,
                                     **({"stream_options": {"include_usage": True}} if include_usage else {}),
                                     "messages": [{"role": "user", "content": "failure fixture" if fail else "Reply OK"}]}
                        result = await gateway_client.post("/v1/chat/completions", headers=headers, json=candidate)
                        assert result.status_code == 200, result.text
                        assert result.json() == ({"expected_failure": True} if fail else {"ok": True})
                assert len(attempts) == 6
                for bearer, status in ((provider, 401), (gateway, 400)):
                    result = await gateway_client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {bearer}"}, json=body)
                    assert result.status_code == status, result.text
                for path in ("/v1/responses", "/v1/embeddings"):
                    result = await gateway_client.post(path, headers=headers, json=body)
                    assert result.status_code == 400, result.text
                for invalid_headers, invalid_body, status in (
                    ({"x-litellm-api-key": "wrong", "Authorization": f"Bearer {gateway}"}, {}, 401),
                    ({"Authorization": ""}, {}, 400), ({"Authorization": f"Basic {provider}"}, {}, 400),
                    ({"Authorization": "Bearer malformed token"}, {}, 400),
                    ({"Authorization": f"Bearer {gateway}"}, {}, 400),
                    ({}, {"model": "openai-default"}, 400), ({}, {"api_key": provider}, 400),
                    ({}, {"headers": {"Authorization": "override"}}, 400),
                    ({}, {"extra_headers": {"Authorization": "override"}}, 400),
                    ({}, {"fallbacks": ["openai-default"]}, 400),
                    ({}, {"extra_body": {"model": "openai-default"}}, 400),
                    ({}, {"models": ["openai-default"]}, 400), ({}, {"route": "fallback"}, 400),
                    ({}, {"deployment_id": "other"}, 400), ({}, {"azure": True}, 400),
                    ({}, {"mock_response": "synthetic"}, 400), ({}, {"mock_timeout": True}, 400),
                    ({}, {"mock_tool_calls": []}, 400), ({}, {"ssl_verify": False}, 400),
                    ({}, {"provider_specific_header": {"Authorization": "override"}}, 400),
                    ({}, {"api_base": "http://untrusted.invalid"}, 401),
                ):
                    result = await gateway_client.post("/v1/chat/completions", headers={**headers, **invalid_headers},
                                                       json={**body, **invalid_body})
                    assert result.status_code == status, result.text
                result = await gateway_client.post("/v1/chat/completions", headers={
                    **headers, "x-litellm-api-key": (identity.KEY_DIRECTORY / "nofx").read_text()}, json=body)
                assert result.status_code == 200 and result.json() == {"unaffected": "nofx"}
                assert len(attempts) == 6
                result = await gateway_client.post("/v1/chat/completions", headers={
                    "Authorization": "Bearer " + (identity.KEY_DIRECTORY / "nofx").read_text()}, json={
                        **body, "api_key": provider, "messages": [{"role": "user", "content": "NOFX strict fixture"}],
                        "response_format": {"type": "json_schema", "json_schema": {
                            "name": "decision", "strict": True, "schema": {"type": "object"}}},
                        "provider": {"require_parameters": True},
                    })
                assert result.status_code == 200 and result.json() == {"ok": True}, result.text
                assert len(attempts) == 7
                multica_key = (identity.KEY_DIRECTORY / "multica").read_text()
                multica_headers = {"Authorization": "Bearer " + multica_key}
                for stream in (False, True):
                    result = await gateway_client.post("/v1/chat/completions", headers=multica_headers,
                        json={**body, "stream": stream, "stream_options": {"include_usage": True}})
                    assert result.status_code == 200 and result.json() == {"ok": True}, result.text
                assert len(attempts) == 9
                for override in ({"api_key": "attacker"}, {"base_url": "https://untrusted.invalid"},
                                 {"model": "openai-default"}, {"extra_body": {}}, {"mock_response": "fake"},
                                 {"fallbacks": ["openai-default"]}):
                    result = await gateway_client.post("/v1/chat/completions", headers=multica_headers,
                                                       json={**body, **override})
                    assert result.status_code == (401 if "base_url" in override else 400), result.text
                for path in ("/v1/responses", "/v1/embeddings"):
                    result = await gateway_client.post(path, headers=multica_headers, json=body)
                    assert result.status_code == 400
                (identity.KEY_DIRECTORY / "openrouter").write_text("REPLACE_ME")
                result = await gateway_client.post("/v1/chat/completions", headers=multica_headers, json=body)
                assert result.status_code == 503 and len(attempts) == 9
                assert multica_key not in str([span.attributes for span in spans])
                assert any(span.attributes.get("user.id") == "multica" for span in spans)
                assert provider not in str(auth_errors.call_args_list) and gateway not in str(auth_errors.call_args_list)
                assert not dynamic_tracer.called, "Requests must retain the operator-configured Langfuse destination"
    finally:
        await client.aclose()
        router.reset()
    exported = json.dumps([span.attributes for span in spans])
    assert provider not in exported and gateway not in exported, [
        key for span in spans for key, value in span.attributes.items()
        if provider in str(value) or gateway in str(value)
    ]
    assert sum(span.attributes.get("llm.token_count.prompt") == 8 for span in spans) == 6
    assert sum(span.attributes.get("llm.token_count.completion") == 1 for span in spans) == 6
    for span in spans:
        if span.attributes.get("llm.token_count.prompt") == 8:
            assert span.attributes["llm.model_name"] == model
            assert span.attributes["llm.provider"] == "openai"  # SDK transport; upstream URL asserted separately.
    assert any(span.attributes.get("error.type") == "BadRequestError" for span in spans)
    assert "Reply OK" in exported and "OK" in exported
    for data in prepared:
        assert gateway not in json.dumps(data["metadata"], default=str)
        assert provider not in json.dumps(data["proxy_server_request"], default=str)


async def check():
    await check_admission()
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
        with patch.object(gateway_launcher, "langfuse_config", return_value=fixture_config), \
                patch.object(LangfuseOtelLogger, "__init__", return_value=None):
            assert callable(get_instance_fn(module_path + ".authenticate", config_file_path="/etc/litellm/config.yaml"))
            assert hasattr(get_instance_fn(module_path + ".attribution", config_file_path="/etc/litellm/config.yaml"), "async_pre_call_hook")
            assert isinstance(get_instance_fn(module_path + ".langfuse", config_file_path="/etc/litellm/config.yaml"), LangfuseOtelLogger)
        identity.KEY_DIRECTORY = Path(directory)
        for app in (*identity.APPS, "operator"):
            (identity.KEY_DIRECTORY / app).write_text(f"sk-{app}-" + "x" * 48)
        await check_openclaw_gateway()
        for app in identity.APPS:
            token = (identity.KEY_DIRECTORY / app).read_text()
            user = await identity.authenticate(request("/models", "GET"), token)
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
                # SDK ingestion maintains both request and metadata header snapshots.
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
    check_launcher()
