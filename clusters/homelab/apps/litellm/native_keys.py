"""Connect the native database and import existing gateway credentials once."""

from contextlib import contextmanager
from pathlib import Path
import os
import tempfile
from urllib.parse import quote

from fastapi import HTTPException
from litellm.proxy._types import LitellmUserRoles, hash_token
from litellm.proxy.common_utils.encrypt_decrypt_utils import decrypt_value_helper, encrypt_value_helper
from prisma import Json
import yaml

APPS = ("openclaw", "nofx", "multica", "n8n")
IMPORT_MARKER = "homelab-native-key-import-v1"
PROVIDER_IMPORT_MARKER = "homelab-provider-credential-import-v1"
KEY_DIRECTORY = Path("/var/run/secrets/litellm-apps")
PASSWORD_FILE = Path("/var/run/secrets/litellm-postgres/password")
ALLOWED_ROUTES = ["/chat/completions", "/v1/chat/completions", "/models", "/v1/models"]


@contextmanager
def database_config(config_path):
    password = PASSWORD_FILE.read_text().strip()
    if len(password) < 32 or password == "REPLACE_ME":
        raise ValueError("LiteLLM database credential is not initialized")
    config = yaml.safe_load(Path(config_path).read_text())
    settings = config["general_settings"]
    if "custom_auth" in settings:
        raise ValueError("Database keys require native authentication")
    settings["database_url"] = (
        "postgresql://litellm:" + quote(password, safe="")
        + "@litellm-postgres.ai.svc.cluster.local:5432/litellm"
    )
    # Native CLI loads this file before schema setup; no plaintext URL in Git or argv.
    with tempfile.TemporaryDirectory(prefix="litellm-config-") as directory:
        path = Path(directory) / "config.yaml"
        with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            yaml.safe_dump(config, stream)
        yield str(path)


async def import_service_keys(client):
    if client is None:
        raise RuntimeError("Native key database is unavailable")
    # Serialize first startup across rolling Pods; marker and all keys commit together.
    async with client.db.tx() as transaction:
        await transaction.execute_raw('LOCK TABLE "LiteLLM_UserTable" IN SHARE ROW EXCLUSIVE MODE')
        marker = await transaction.litellm_usertable.find_unique(where={"user_id": IMPORT_MARKER})
        if marker is not None:
            return
        keys = {app: (KEY_DIRECTORY / app).read_text().strip() for app in APPS}
        operator = (KEY_DIRECTORY / "operator").read_text().strip()
        if (any(not key.startswith("sk-") or len(key) < 32 for key in keys.values())
                or len(set(keys.values())) != len(APPS) or operator in keys.values()):
            raise ValueError("Caller keys must be initialized, distinct and non-administrative")
        for app, key in keys.items():
            await transaction.litellm_usertable.create(data={
                "user_id": app, "user_role": LitellmUserRoles.INTERNAL_USER.value,
                "models": ["openrouter/free"],
            })
            await transaction.litellm_verificationtoken.create(data={
                "token": hash_token(key), "key_alias": app, "key_name": app,
                "user_id": app, "models": ["openrouter/free"],
                "allowed_routes": ALLOWED_ROUTES, "blocked": False,
            })
        await transaction.litellm_usertable.create(data={
            "user_id": IMPORT_MARKER, "models": [],
        })
    # Once the marker exists, never recreate deleted keys or undo UI blocks/rotations.


async def import_provider_credential(client):
    # A separate marker also migrates databases that already imported caller keys.
    async with client.db.tx() as transaction:
        await transaction.execute_raw('LOCK TABLE "LiteLLM_UserTable" IN SHARE ROW EXCLUSIVE MODE')
        marker = await transaction.litellm_usertable.find_unique(where={"user_id": PROVIDER_IMPORT_MARKER})
        if marker is not None:
            return
        key = (KEY_DIRECTORY / "openrouter").read_text().strip()
        if not key.startswith("sk-or-") or len(key) < 32:
            raise ValueError("OpenRouter credential is not initialized")
        await transaction.litellm_credentialstable.create(data={
            "credential_name": "openrouter",
            "credential_values": Json({"api_key": encrypt_value_helper(key)}),
            "credential_info": Json({"custom_llm_provider": "Openrouter"}),
            "created_by": "operator", "updated_by": "operator",
        })
        await transaction.litellm_usertable.create(data={
            "user_id": PROVIDER_IMPORT_MARKER, "models": [],
        })


async def provider_api_key():
    from litellm.proxy.proxy_server import prisma_client

    # Read the authoritative row: native credential caches can lag UI edits/deletes.
    try:
        credential = await prisma_client.db.litellm_credentialstable.find_unique(
            where={"credential_name": "openrouter"})
        key = decrypt_value_helper(credential.credential_values["api_key"], "api_key", exception_type="debug")
        if isinstance(key, str) and key.startswith("sk-or-") and len(key) >= 32:
            return key
    except Exception:
        pass
    raise HTTPException(503, "OpenRouter credential is unavailable") from None
