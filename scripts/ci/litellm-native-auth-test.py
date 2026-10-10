"""Exercise pinned native authentication with an in-memory key store, no live keys."""

import asyncio
from hashlib import sha256
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
import httpx
from litellm.caching.caching import DualCache
from litellm.proxy._types import ProxyException, UserAPIKeyAuth

auth = importlib.import_module("litellm.proxy.auth.user_api_key_auth")


async def check():
    token = "sk-" + "a" * 48
    digest = sha256(token.encode()).hexdigest()
    state = {"revoked": False, "blocked": False}
    reads = []

    async def key_object(hashed_token, check_cache_only=False, **kwargs):
        if check_cache_only:
            return None
        reads.append(hashed_token)
        if state["revoked"] or hashed_token != digest:
            raise ProxyException(message="Invalid key", type="auth_error", param=None, code=401)
        return UserAPIKeyAuth(api_key=digest, key_alias="openclaw",
                              models=["openrouter/free"], blocked=state["blocked"],
                              allowed_routes=["/chat/completions", "/v1/chat/completions", "/models", "/v1/models"])

    proxy = SimpleNamespace(
        general_settings={}, jwt_handler=None, litellm_proxy_admin_name="operator",
        llm_model_list=[{"model_name": "openrouter/free"}], llm_router=None,
        master_key="sk-" + "m" * 48, model_max_budget_limiter=None,
        open_telemetry_logger=None, prisma_client=SimpleNamespace(),
        proxy_logging_obj=SimpleNamespace(post_call_failure_hook=AsyncMock()),
        user_api_key_cache=DualCache(), user_custom_auth=None, premium_user=False,
    )
    app = FastAPI()

    @app.exception_handler(ProxyException)
    async def error(request, exception):
        return JSONResponse({"error": "denied"}, status_code=int(exception.code))

    @app.post("/v1/chat/completions")
    @app.post("/key/generate")
    async def endpoint(user=Depends(auth.user_api_key_auth)):
        return {"alias": user.key_alias}

    with patch.dict(sys.modules, {"litellm.proxy.proxy_server": proxy}), \
            patch.object(auth, "enterprise_custom_auth", None), \
            patch.object(auth, "get_key_object", side_effect=key_object), \
            patch.object(auth.verbose_proxy_logger, "error"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://fixture") as client:
            headers = {"Authorization": "Bearer " + token}
            async def request(path="/v1/chat/completions", model="openrouter/free"):
                return await client.post(path, headers=headers, json={"model": model, "messages": []})
            response = await request()
            assert response.status_code == 200, response.text
            assert response.json() == {"alias": "openclaw"}
            assert reads == [digest], "Native authentication must consult the key store"
            assert (await request("/key/generate")).status_code in (400, 401, 403)
            assert (await request(model="paid-model")).status_code in (400, 401, 403)
            state["blocked"] = True
            assert (await request()).status_code in (400, 401, 403)
            state["blocked"] = False
            state["revoked"] = True
            assert (await request()).status_code == 401
    print("Native LiteLLM auth: stored key, model/route limits, blocked and deleted key checks passed")


if __name__ == "__main__":
    asyncio.run(check())
