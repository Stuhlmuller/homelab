"""Import fixture keys into disposable PostgreSQL using the pinned native schema."""

import asyncio
import importlib
import json
import hashlib
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

from fastapi import HTTPException
from prisma import Json, Prisma
from litellm.proxy import proxy_server
from litellm.proxy.common_utils.encrypt_decrypt_utils import decrypt_value_helper, encrypt_value_helper
from litellm.proxy.db.prisma_client import PrismaWrapper
from litellm_proxy_extras.utils import ProxyExtrasDBManager
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "clusters/homelab/apps/litellm"))
native_keys = importlib.import_module("native_keys")


def run(*command):
    return subprocess.run([str(part) for part in command], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)


async def check_database(url, directory):
    database = Prisma(datasource={"url": url})
    await database.connect()
    client = SimpleNamespace(db=PrismaWrapper(original_prisma=database, iam_token_db_auth=False))
    try:
        for index, app in enumerate(native_keys.APPS):
            (directory / app).write_text("sk-" + str(index) * 48)
        (directory / "operator").write_text("sk-" + "m" * 48)
        with patch.object(native_keys, "KEY_DIRECTORY", directory):
            await asyncio.gather(native_keys.import_service_keys(client), native_keys.import_service_keys(client))
            keys = await database.litellm_verificationtoken.find_many()
            assert len(keys) == 4
            for key in keys:
                raw = (directory / key.key_alias).read_text()
                assert key.token == native_keys.hash_token(raw) and key.token != raw
                assert key.models == ["openrouter/free"]
                assert key.allowed_routes == native_keys.ALLOWED_ROUTES
                user = await database.litellm_usertable.find_unique(where={"user_id": key.user_id})
                assert user.user_role == "internal_user"
            first, second = keys[:2]
            await database.litellm_verificationtoken.update(where={"token": first.token}, data={"blocked": True})
            await database.litellm_verificationtoken.delete(where={"token": second.token})
            await native_keys.import_service_keys(client)
            assert await database.litellm_verificationtoken.count() == 3
            assert (await database.litellm_verificationtoken.find_unique(where={"token": first.token})).blocked
            assert await database.litellm_verificationtoken.find_unique(where={"token": second.token}) is None
            await check_provider_database(database, client, directory)

            await database.litellm_verificationtoken.delete_many()
            await database.litellm_usertable.delete_many()
            await database.litellm_usertable.create(data={"user_id": "nofx", "models": []})
            try:
                await native_keys.import_service_keys(client)
            except Exception:
                pass
            else:
                raise AssertionError("Existing user collision must reject import")
            assert await database.litellm_verificationtoken.count() == 0, "Partial import was not rolled back"
            users = await database.litellm_usertable.find_many()
            assert [user.user_id for user in users] == ["nofx"], "Import marker or users escaped rollback"
    finally:
        await database.disconnect()


async def provider_unavailable():
    try:
        await native_keys.provider_api_key()
    except HTTPException as error:
        assert error.status_code == 503
        assert error.detail == "OpenRouter credential is unavailable"
    else:
        raise AssertionError("Unavailable provider credential must fail closed")


async def check_provider_database(database, client, directory):
    credential_file = directory / "openrouter"
    original, rotated = "sk-or-" + "a" * 48, "sk-or-" + "b" * 48
    credential_file.write_text(original)
    credentials = database.litellm_credentialstable
    credential_where = {"credential_name": "openrouter"}
    marker_where = {"user_id": native_keys.PROVIDER_IMPORT_MARKER}
    assert native_keys.PROVIDER_IMPORT_MARKER == "homelab-provider-credential-import-v1"
    assert native_keys.PROVIDER_IMPORT_MARKER != native_keys.IMPORT_MARKER
    with patch.object(proxy_server, "master_key", "sk-" + "m" * 48), \
            patch.object(proxy_server, "prisma_client", client):
        await asyncio.gather(native_keys.import_provider_credential(client),
                             native_keys.import_provider_credential(client))
        assert await credentials.count() == 1
        assert await database.litellm_usertable.count(where=marker_where) == 1
        credential = await credentials.find_unique(where=credential_where)
        encrypted = credential.credential_values["api_key"]
        assert encrypted != original and original not in json.dumps(credential.credential_values)
        assert decrypt_value_helper(encrypted, "api_key") == original
        assert credential.credential_info["custom_llm_provider"] == "Openrouter"
        assert await native_keys.provider_api_key() == original

        rotated_values = {"api_key": encrypt_value_helper(rotated)}
        await credentials.update(where=credential_where, data={"credential_values": Json(rotated_values)})
        assert await native_keys.provider_api_key() == rotated, "Provider reads must see UI rotations immediately"
        await native_keys.import_provider_credential(client)
        assert (await credentials.find_unique(where=credential_where)).credential_values == rotated_values

        for invalid in (None, {}, "", "sk-or-short", "sk-" + "x" * 48):
            await credentials.update(where=credential_where, data={
                "credential_values": Json({"api_key": encrypt_value_helper(invalid)}),
            })
            await provider_unavailable()
        await credentials.update(where=credential_where, data={"credential_values": Json({"api_key": original})})
        await provider_unavailable()
        await credentials.delete(where=credential_where)
        await provider_unavailable()
        credential_file.unlink()
        await native_keys.import_provider_credential(client)
        assert await credentials.count() == 0, "Startup recreated a credential deleted in the UI"
        await provider_unavailable()

        failing_client = SimpleNamespace(db=SimpleNamespace(litellm_credentialstable=SimpleNamespace(
            find_unique=AsyncMock(side_effect=RuntimeError("database detail " + original)),
        )))
        with patch.object(proxy_server, "prisma_client", failing_client):
            await provider_unavailable()
        with patch.object(proxy_server, "prisma_client", None):
            await provider_unavailable()

        await database.litellm_usertable.delete(where=marker_where)
        credential_file.write_text(original)
        await credentials.create(data={
            "credential_name": "openrouter", "credential_values": Json(rotated_values),
            "credential_info": Json({"custom_llm_provider": "Openrouter"}),
            "created_by": "fixture", "updated_by": "fixture",
        })
        try:
            await native_keys.import_provider_credential(client)
        except Exception:
            pass
        else:
            raise AssertionError("Existing provider credential collision must reject import")
        assert await credentials.count() == 1
        assert (await credentials.find_unique(where=credential_where)).credential_values == rotated_values
        assert await database.litellm_usertable.find_unique(where=marker_where) is None
        await credentials.delete(where=credential_where)
        for invalid in ("REPLACE_ME", "sk-or-short", "sk-" + "x" * 48):
            credential_file.write_text(invalid)
            try:
                await native_keys.import_provider_credential(client)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid provider credential was imported")
            assert await credentials.count() == 0
            assert await database.litellm_usertable.find_unique(where=marker_where) is None


def check_config(directory):
    source = directory / "config.yaml"
    source.write_text("general_settings: {}\n")
    password = directory / "password"
    password.write_text("p" * 32 + ":/@?")
    with patch.object(native_keys, "PASSWORD_FILE", password):
        with native_keys.database_config(source) as generated:
            path = Path(generated)
            assert path.stat().st_mode & 0o777 == 0o600
            assert path.parent.stat().st_mode & 0o777 == 0o700
            url = yaml.safe_load(path.read_text())["general_settings"]["database_url"]
            assert quote(password.read_text(), safe="") in url
            assert password.read_text() not in url
        assert not path.exists()
        assert source.read_text() == "general_settings: {}\n"
        source.write_text("general_settings: {custom_auth: forbidden}\n")
        try:
            with native_keys.database_config(source):
                raise AssertionError("Custom authentication bypass accepted")
        except ValueError:
            pass


def check_upgrade(directory, socket, wheel):
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == "ef63f497e46b2ed856c6e94802357b34ffcf29bef77c9993081fb355bba2f1e4", "Use the reviewed 0.4.11 migration wheel"
    legacy = directory / "legacy"
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith("litellm_proxy_extras/") and (name.endswith("schema.prisma") or "/migrations/" in name) and not name.endswith("/"):
                relative = Path(name).relative_to("litellm_proxy_extras")
                assert ".." not in relative.parts and not relative.is_absolute()
                target = legacy / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
    run("createdb", "-h", socket, "-U", "fixture", "-O", "litellm", "litellm-upgrade")
    url = "postgresql://litellm@localhost/litellm-upgrade?host=" + quote(str(socket), safe="")
    candidate = directory / "candidate"
    shutil.copytree(ProxyExtrasDBManager._get_prisma_dir(), candidate)
    history_command = ("psql", "-X", "-h", socket, "-U", "litellm", "-d", "litellm-upgrade", "-tA", "-c",
                       'SELECT migration_name || \':\' || checksum FROM "_prisma_migrations" ORDER BY migration_name')
    legacy_token = hashlib.sha256(b"synthetic legacy fixture").hexdigest()
    for source in (legacy, candidate):
        schema = source / "schema.prisma"
        schema.write_text(schema.read_text().replace('env("DATABASE_URL")', json.dumps(url)))
        run(sys.executable, "-m", "prisma", "migrate", "deploy", "--schema", schema)
        if source == legacy:
            legacy_history = set(run(*history_command).stdout.splitlines())
            assert legacy_history, "Previous migration history must exist before upgrading"
            run("psql", "-X", "-h", socket, "-U", "litellm", "-d", "litellm-upgrade", "-v", "ON_ERROR_STOP=1", "-c", f'''
                INSERT INTO "LiteLLM_UserTable" (user_id,user_role,models)
                VALUES ('legacy-app','internal_user',ARRAY['openrouter/free']);
                INSERT INTO "LiteLLM_VerificationToken" (token,key_alias,user_id,models,allowed_routes,blocked,metadata)
                VALUES ('{legacy_token}','legacy-fixture','legacy-app',ARRAY['openrouter/free'],
                        ARRAY['/v1/chat/completions'],true,'{{"fixture":"Unicode λ"}}'::jsonb);
            ''')
    assert legacy_history <= set(run(*history_command).stdout.splitlines()), "Upgrade must preserve the previous migration ledger"

    async def verify():
        client = Prisma(datasource={"url": url})
        await client.connect()
        try:
            key = await client.litellm_verificationtoken.find_unique(where={"token": legacy_token})
            user = await client.litellm_usertable.find_unique(where={"user_id": "legacy-app"})
            assert key.key_alias == "legacy-fixture" and key.blocked
            assert key.models == ["openrouter/free"] and key.allowed_routes == ["/v1/chat/completions"]
            assert key.metadata == {"fixture": "Unicode λ"} and user.user_role == "internal_user"
        finally:
            await client.disconnect()

    asyncio.run(verify())


def check_runtime_database(directory, socket, image):
    assert image == "fixture/litellm-remediated:local", "Only the disposable CI runtime image is allowed"
    run("createdb", "-h", socket, "-U", "fixture", "-O", "litellm", "litellm-runtime")
    # The private parent remains 0700; expose only this socket to the non-root container.
    socket.chmod(0o755)
    code = '''import asyncio,json,runpy,shutil,tempfile
from pathlib import Path
fixture=runpy.run_path('scripts/ci/litellm-native-database-test.py')
url='postgresql://litellm@localhost/litellm-runtime?host=%2Ffixture-postgres'
with tempfile.TemporaryDirectory(dir='/tmp') as temporary:
 directory=Path(temporary);migrations=directory/'migrations'
 shutil.copytree(fixture['ProxyExtrasDBManager']._get_prisma_dir(),migrations)
 schema=migrations/'schema.prisma';schema.write_text(schema.read_text().replace('env("DATABASE_URL")',json.dumps(url)))
 fixture['run']('/opt/prisma/binaries/node_modules/.bin/prisma','migrate','deploy','--schema',schema)
 asyncio.run(fixture['check_database'](url,directory))
print('Non-root remediated runtime: packaged migrations, query engine, native key/provider persistence passed')
'''
    run("docker", "run", "--rm", "--network", "none", "--user", "65532:65532", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=256m",
        "--mount", f"type=bind,source={ROOT / 'scripts/ci'},target=/workspace/scripts/ci,readonly",
        "--mount", f"type=bind,source={ROOT / 'clusters/homelab/apps/litellm'},target=/workspace/clusters/homelab/apps/litellm,readonly",
        "--mount", f"type=bind,source={socket},target=/fixture-postgres,readonly",
        "--workdir", "/workspace", "--entrypoint", "/app/.venv/bin/python", image, "-c", code)


def main():
    assert len(sys.argv) in (2, 3), "Pass the pinned previous migration wheel and optional disposable runtime image"
    with tempfile.TemporaryDirectory(prefix="litellm-db-", dir="/tmp") as temporary:
        directory = Path(temporary)
        data, socket = directory / "data", directory / "socket"
        socket.mkdir()
        check_config(directory)
        run("initdb", "-D", data, "-U", "fixture", "--auth-local=trust", "--auth-host=reject",
            "--locale=C", "--encoding=UTF8")
        try:
            run("pg_ctl", "-D", data, "-l", directory / "postgres.log", "-w", "-t", "30",
                "-o", f"-c listen_addresses= -c unix_socket_directories={socket} -c shared_buffers=16MB", "start")
            run("psql", "-X", "-h", socket, "-U", "fixture", "-d", "postgres", "-v", "ON_ERROR_STOP=1",
                "-c", "CREATE ROLE litellm LOGIN")
            run("createdb", "-h", socket, "-U", "fixture", "-O", "litellm", "litellm")
            url = "postgresql://litellm@localhost/litellm?host=" + quote(str(socket), safe="")
            migrations = directory / "migrations"
            shutil.copytree(ProxyExtrasDBManager._get_prisma_dir(), migrations)
            fixture_schema = migrations / "schema.prisma"
            fixture_schema.write_text(fixture_schema.read_text().replace('env("DATABASE_URL")', json.dumps(url)))
            run(sys.executable, "-m", "prisma", "migrate", "deploy", "--schema", fixture_schema)
            asyncio.run(check_database(url, directory))
            check_upgrade(directory, socket, Path(sys.argv[1]))
            if len(sys.argv) == 3:
                check_runtime_database(directory, socket, sys.argv[2])
        finally:
            run("pg_ctl", "-D", data, "-w", "-t", "30", "-m", "immediate", "stop")
    print("Native PostgreSQL keys: atomic import, concurrency, UI revocation/rotation, provider encryption and fail-closed reads passed")
    print("Previous migrations to candidate: persisted key identity, restrictions, blocking and Unicode metadata preserved")


if __name__ == "__main__":
    main()
