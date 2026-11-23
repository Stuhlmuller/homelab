BEGIN;

DO $$
DECLARE
  app_password text := btrim(pg_read_file('/run/immich-secrets/app-password'), chr(10) || chr(13));
BEGIN
  IF app_password !~ '^[a-zA-Z0-9]{40}$' THEN
    RAISE EXCEPTION 'Immich database credential does not match its contract';
  END IF;
  EXECUTE format('CREATE ROLE immich LOGIN PASSWORD %L', app_password);
END
$$;

CREATE EXTENSION IF NOT EXISTS vchord CASCADE;
CREATE EXTENSION IF NOT EXISTS earthdistance CASCADE;
ALTER DATABASE immich OWNER TO immich;
ALTER SCHEMA public OWNER TO immich;
COMMIT;
