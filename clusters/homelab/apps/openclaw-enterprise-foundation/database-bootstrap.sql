\set ON_ERROR_STOP on
\set QUIET on
\set migrator_password `cat /run/secrets/occ-postgres-migrator/password`
\set app_password `cat /run/secrets/occ-postgres-app/password`
\set backup_password `cat /run/secrets/occ-postgres-backup/password`

REVOKE ALL ON DATABASE openclaw_enterprise FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
SELECT 'CREATE ROLE occ_migrator' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'occ_migrator') \gexec
SELECT 'CREATE ROLE occ_app' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'occ_app') \gexec
SELECT 'CREATE ROLE occ_backup' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'occ_backup') \gexec
ALTER ROLE occ_migrator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'migrator_password';
ALTER ROLE occ_app LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
ALTER ROLE occ_backup LOGIN INHERIT BYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'backup_password';
GRANT pg_read_all_data TO occ_backup;
GRANT CONNECT, CREATE ON DATABASE openclaw_enterprise TO occ_migrator;
GRANT CONNECT ON DATABASE openclaw_enterprise TO occ_app, occ_backup;
CREATE SCHEMA IF NOT EXISTS occ AUTHORIZATION occ_migrator;
CREATE SCHEMA IF NOT EXISTS drizzle AUTHORIZATION occ_migrator;
REVOKE ALL ON SCHEMA occ, drizzle FROM PUBLIC;
GRANT USAGE ON SCHEMA occ TO occ_app;
ALTER DEFAULT PRIVILEGES FOR ROLE occ_migrator IN SCHEMA occ
  REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE occ_migrator IN SCHEMA drizzle
  REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE occ_migrator
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
-- Written last so an interrupted first-run bootstrap cannot pass readiness.
COMMENT ON DATABASE openclaw_enterprise IS 'occ-bootstrap-v1';
