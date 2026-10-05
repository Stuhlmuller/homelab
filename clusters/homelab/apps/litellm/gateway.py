"""Start the native proxy with a pre-authentication telemetry admission guard."""

from pathlib import Path
import json
import logging
import sys

import click
from litellm.proxy._types import LiteLLMRoutes
from litellm.proxy.auth.auth_utils import get_request_route
from litellm.proxy.auth.route_checks import RouteChecks
from litellm.types.utils import StandardCallbackDynamicParams
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse
from starlette.exceptions import HTTPException

LOGGING_OVERRIDES = set(StandardCallbackDynamicParams.__annotations__) | {
    "success_callback", "failure_callback", "callbacks", "no-log",
}
MAX_BODY_BYTES = 32 * 1024 * 1024  # Bounded text/image JSON admission, including chunked uploads.


def langfuse_config():
    from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger
    from litellm.integrations.opentelemetry import OpenTelemetryConfig

    directory = Path("/var/run/secrets/litellm-telemetry")
    public, secret = ((directory / name).read_text().strip() for name in ("public-key", "secret-key"))
    if not public or not secret or "REPLACE_ME" in (public, secret):
        raise ValueError("Langfuse credentials are not initialized")
    auth = LangfuseOtelLogger._get_langfuse_authorization_header(public, secret)
    return OpenTelemetryConfig(
        exporter="otlp_http",
        endpoint="http://langfuse-web.langfuse.svc.cluster.local:3000/api/public/otel/v1/traces",
        headers="Authorization=" + auth,
    )


class RequestTooLarge(Exception):
    pass


class TelemetryAdmission:
    """Reject caller-controlled logging before native auth/failure logging sees it.

    Pure ASGI preserves contextvars and does not intercept streamed responses.
    Like native request parsing, admission buffers the inbound request body.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        route = get_request_route(request)
        if not (RouteChecks.is_llm_api_route(route)
                or RouteChecks.check_route_access(route, LiteLLMRoutes.llm_api_routes.value)):
            return await self.app(scope, receive, send)
        size = 0
        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > MAX_BODY_BYTES:
                    raise RequestTooLarge
            return message
        request = Request(scope, bounded_receive)
        try:
            body = await request.body()
            if "form" in request.headers.get("content-type", ""):
                async with request.form() as form:
                    keys = set(form)
            else:
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
                keys = set(data)
                del data
            # Cover a body cached by another ASGI component as well as the wire.
            cached = scope.get("parsed_body")
            if cached:
                keys.update(cached[1])
        except ClientDisconnect:
            return
        except RequestTooLarge:
            return await JSONResponse({"error": "Request body exceeds 32 MiB"}, status_code=413)(scope, receive, send)
        except (ValueError, UnicodeError, HTTPException):
            return await JSONResponse({"error": "Invalid request body"}, status_code=400)(scope, receive, send)
        if LOGGING_OVERRIDES.intersection(keys):
            return await JSONResponse({"error": "Request-level logging overrides are disabled"},
                                      status_code=400)(scope, receive, send)
        del request

        delivered = False
        async def replay():
            nonlocal delivered, body
            if not delivered:
                delivered = True
                message = {"type": "http.request", "body": body, "more_body": False}
                body = b""
                return message
            return await receive()
        await self.app(scope, replay, send)


def main(args=None):
    # Preserve native CLI initialization and lifespan. Multiple Uvicorn workers
    # import an unguarded app in child processes, so scale Pods, not workers.
    from litellm.proxy.proxy_cli import run_server
    from litellm.proxy.proxy_server import app
    from litellm._logging import verbose_logger, verbose_proxy_logger, verbose_router_logger

    with run_server.make_context("litellm", sys.argv[1:] if args is None else args) as context:
        if any(context.params[key] for key in ("run_gunicorn", "run_hypercorn", "local")):
            raise click.ClickException("The guarded gateway requires native single-process Uvicorn")
        context.params["num_workers"] = 1
        context.params["debug"] = context.params["detailed_debug"] = False
        for logger in (verbose_logger, verbose_proxy_logger, verbose_router_logger):
            logger.setLevel(logging.INFO)
        app.add_middleware(TelemetryAdmission)
        run_server.invoke(context)


if __name__ == "__main__":
    main()
