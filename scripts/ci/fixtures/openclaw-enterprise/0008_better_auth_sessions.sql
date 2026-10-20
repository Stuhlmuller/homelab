CREATE TABLE occ."user" (
  id text PRIMARY KEY,
  name text COLLATE "C" NOT NULL,
  email text COLLATE "C" NOT NULL UNIQUE,
  email_verified boolean NOT NULL DEFAULT false,
  image text,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT auth_user_id_length CHECK (char_length(id) BETWEEN 1 AND 200),
  CONSTRAINT auth_user_name_length CHECK (char_length(name) BETWEEN 1 AND 200),
  CONSTRAINT auth_user_email_length CHECK (char_length(email) BETWEEN 3 AND 320),
  CONSTRAINT auth_user_email_normalized CHECK (
    email = lower(btrim(email)) AND email LIKE '%@%'
  ),
  CONSTRAINT auth_user_timestamp_order CHECK (updated_at >= created_at)
);
--> statement-breakpoint
CREATE TABLE occ.session (
  id text PRIMARY KEY,
  expires_at timestamptz NOT NULL,
  token text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  ip_address text,
  user_agent text,
  user_id text NOT NULL REFERENCES occ."user"(id)
    ON UPDATE RESTRICT ON DELETE CASCADE,
  CONSTRAINT auth_session_id_length CHECK (char_length(id) BETWEEN 1 AND 200),
  CONSTRAINT auth_session_token_length CHECK (char_length(token) BETWEEN 1 AND 512),
  CONSTRAINT auth_session_timestamp_order CHECK (updated_at >= created_at)
);
--> statement-breakpoint
CREATE INDEX session_user_id_idx ON occ.session (user_id);
--> statement-breakpoint
CREATE TABLE occ.account (
  id text PRIMARY KEY,
  account_id text NOT NULL,
  provider_id text NOT NULL,
  user_id text NOT NULL REFERENCES occ."user"(id)
    ON UPDATE RESTRICT ON DELETE CASCADE,
  access_token text,
  refresh_token text,
  id_token text,
  access_token_expires_at timestamptz,
  refresh_token_expires_at timestamptz,
  scope text,
  password text,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT auth_account_id_length CHECK (char_length(id) BETWEEN 1 AND 200),
  CONSTRAINT auth_account_provider_length CHECK (char_length(provider_id) BETWEEN 1 AND 200),
  CONSTRAINT auth_account_external_id_length CHECK (char_length(account_id) BETWEEN 1 AND 512),
  CONSTRAINT auth_account_timestamp_order CHECK (updated_at >= created_at)
);
--> statement-breakpoint
CREATE INDEX account_user_id_idx ON occ.account (user_id);
--> statement-breakpoint
CREATE UNIQUE INDEX account_provider_account_unique ON occ.account (provider_id, account_id);
--> statement-breakpoint
CREATE TABLE occ.verification (
  id text PRIMARY KEY,
  identifier text NOT NULL,
  value text NOT NULL,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT auth_verification_id_length CHECK (char_length(id) BETWEEN 1 AND 200),
  CONSTRAINT auth_verification_identifier_length CHECK (
    char_length(identifier) BETWEEN 1 AND 512
  ),
  CONSTRAINT auth_verification_value_length CHECK (char_length(value) BETWEEN 1 AND 4096),
  CONSTRAINT auth_verification_timestamp_order CHECK (updated_at >= created_at)
);
--> statement-breakpoint
CREATE INDEX verification_identifier_idx ON occ.verification (identifier);
--> statement-breakpoint
REVOKE ALL ON
  occ."user",
  occ.session,
  occ.account,
  occ.verification
FROM PUBLIC, occ_app;
--> statement-breakpoint
GRANT SELECT, INSERT, UPDATE, DELETE ON
  occ."user",
  occ.session,
  occ.account,
  occ.verification
TO occ_app;
