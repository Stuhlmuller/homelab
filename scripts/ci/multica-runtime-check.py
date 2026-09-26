"""Exercise first boot, restart, and revoked-token handling without credentials."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import urllib.error


root = Path(__file__).resolve().parents[2]
source = root / "clusters/homelab/apps/multica/runtime"
spec = importlib.util.spec_from_file_location("multica_bootstrap", source / "bootstrap.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
settings = json.loads((source / "settings.json").read_text())

with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary) / "profile"
    code = Path(temporary) / "code"
    code.write_text("012345")
    calls = []

    def api(server, path, token=None, body=None):
        assert server == settings["server_url"]
        calls.append(path)
        if path == "/auth/send-code":
            assert body == {"email": settings["email"]}
            return {}
        if path == "/auth/verify-code":
            assert body == {"email": settings["email"], "code": "012345"}
            return {"token": "test-session", "user": {"email": settings["email"]}}
        if path == "/api/tokens/":
            assert token == "test-session" and body["expires_in_days"] == 90
            return {"token": "test-pat"}
        assert path == "/api/me" and token == "test-pat"
        return {"email": settings["email"]}

    with contextlib.redirect_stdout(io.StringIO()) as output:
        module.bootstrap(settings, directory, code, api)
        assert calls == ["/auth/send-code", "/auth/verify-code", "/api/tokens/"]
        saved = directory / "config.json"
        assert stat.S_IMODE(saved.stat().st_mode) == 0o600
        assert json.loads(saved.read_text())["token"] == "test-pat"
        code.unlink()
        calls.clear()
        module.bootstrap(settings, directory, code, api)
        assert calls == ["/api/me"], "restart must reuse the token without bootstrap code"

        def revoked(*_args, **_kwargs):
            raise urllib.error.HTTPError(settings["server_url"], 401, "revoked", {}, None)

        previous = saved.read_bytes()
        try:
            module.bootstrap(settings, directory, code, revoked)
        except urllib.error.HTTPError:
            pass
        else:
            raise AssertionError("revoked token must fail closed")
        assert saved.read_bytes() == previous
    assert "012345" not in output.getvalue() and "test-pat" not in output.getvalue()

print("Multica runtime bootstrap checks passed")
