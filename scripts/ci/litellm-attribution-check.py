"""Run with the gateway's pinned litellm[proxy]==1.80.8 Python environment."""

import asyncio
import importlib.util
from pathlib import Path
import shutil
import tempfile

from fastapi import HTTPException, Request
from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger
from litellm.proxy.types_utils.utils import get_instance_fn

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "app_identity", ROOT / "clusters/homelab/apps/litellm/app_identity.py"
)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def request(path="/v1/chat/completions", method="POST"):
    return Request({"type": "http", "path": path, "method": method, "headers": []})


async def denied(awaitable, status):
    try:
        await awaitable
    except HTTPException as error:
        assert error.status_code == status, error
    else:
        raise AssertionError(f"Expected HTTP {status}")


async def check():
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        # Like the container mount, the module path must not contain dots.
        shutil.copyfile(identity.__file__, Path(directory) / "app_identity.py")
        module_path = str(Path(directory) / "app_identity")
        assert callable(get_instance_fn(module_path + ".authenticate", config_file_path="/etc/litellm/config.yaml"))
        assert hasattr(get_instance_fn(module_path + ".attribution", config_file_path="/etc/litellm/config.yaml"), "async_pre_call_hook")
        identity.KEY_DIRECTORY = Path(directory)
        for app in (*identity.APPS, "operator"):
            (identity.KEY_DIRECTORY / app).write_text(f"sk-{app}-" + "x" * 48)
        for app in identity.APPS:
            token = (identity.KEY_DIRECTORY / app).read_text()
            user = await identity.authenticate(request(), token)
            assert user.key_alias == app and user.user_id == app
            assert user.api_key != token, "LiteLLM must hash the key before logging"
            for path in ("/key/generate", "/config/update", "/user/new"):
                await denied(identity.authenticate(request(path), token), 403)
            await denied(identity.authenticate(request("/v1/models", "DELETE"), token), 403)
            for call_type, metadata_key in (("acompletion", "metadata"), ("aresponses", "litellm_metadata")):
                data = {
                    metadata_key: {"trace_user_id": "spoofed", "session_id": "session-1"},
                    "proxy_server_request": {"headers": {"langfuse_trace_user_id": "spoofed"}},
                }
                result = await identity.attribution.async_pre_call_hook(user, None, data, call_type)
                metadata = result[metadata_key]
                assert metadata["session_id"] == "session-1"
                exported = LangfuseOtelLogger._extract_langfuse_metadata({"litellm_params": {
                    "metadata": metadata, "proxy_server_request": result["proxy_server_request"],
                }})
                assert exported["trace_user_id"] == app
                assert exported["trace_metadata"] == {"app": app}
                assert exported["tags"] == [f"app:{app}"]
            await denied(identity.attribution.async_pre_call_hook(user, None, {"no-log": True}, "acompletion"), 400)
        await denied(identity.authenticate(request(), "wrong"), 401)
        await denied(identity.authenticate(request(), None), 401)
        await identity.authenticate(request("/health/readiness", "GET"), None)
        # Secret volume rotation takes effect without restarting the gateway.
        old = (identity.KEY_DIRECTORY / "openclaw").read_text()
        (identity.KEY_DIRECTORY / "openclaw").write_text("sk-rotated-" + "y" * 48)
        await denied(identity.authenticate(request(), old), 401)
        (identity.KEY_DIRECTORY / "openclaw").write_text("REPLACE_ME")
        await denied(identity.authenticate(request(), old), 503)
    print("LiteLLM app authentication, rotation, route isolation and Langfuse attribution passed")


if __name__ == "__main__":
    asyncio.run(check())
