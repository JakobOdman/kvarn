-- Kvarn's tables in Postgres (Supabase). Run with: venv/bin/python -m api.db schema
-- The accounts are Supabase Auth's (auth.users); user_id is their id.

CREATE TABLE IF NOT EXISTS folders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created TEXT NOT NULL,
    user_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    seq BIGINT GENERATED ALWAYS AS IDENTITY,  -- order within the same second
    name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created TEXT NOT NULL,
    options JSONB NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    result JSONB,
    folder_id TEXT NOT NULL REFERENCES folders (id)
);

CREATE TABLE IF NOT EXISTS extractions (
    id TEXT PRIMARY KEY,
    seq BIGINT GENERATED ALWAYS AS IDENTITY,
    template_id TEXT NOT NULL,
    template JSONB NOT NULL,
    created TEXT NOT NULL,
    status TEXT NOT NULL,
    documents JSONB NOT NULL,
    tables JSONB NOT NULL,
    folder_id TEXT,  -- kept when the folder is deleted
    user_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    template JSONB NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

-- Saved AI answers, per owner: the same prompt, schema and model again costs nothing (llm.py)
CREATE TABLE IF NOT EXISTS llm_cache (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    model TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    answer JSONB NOT NULL,
    created TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- AI spending per owner and month, checked against the budget in limits.py
CREATE TABLE IF NOT EXISTS usage (
    user_id TEXT NOT NULL,
    month TEXT NOT NULL,  -- 2026-10
    usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    tokens_in BIGINT NOT NULL DEFAULT 0,
    tokens_out BIGINT NOT NULL DEFAULT 0,
    model_pages INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, month)
);

-- Added later. A folder's template, and whether its documents are extracted as soon as they are read, into the
-- folder's live extraction (at most one per folder)
ALTER TABLE folders ADD COLUMN IF NOT EXISTS template_id TEXT;
ALTER TABLE folders ADD COLUMN IF NOT EXISTS auto_extract BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE extractions ADD COLUMN IF NOT EXISTS live BOOLEAN NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS extractions_live ON extractions (folder_id) WHERE live;
-- The folder's API key, for reading its live extraction from other systems. Only its sha256 is kept.
ALTER TABLE folders ADD COLUMN IF NOT EXISTS api_key_hash TEXT;
ALTER TABLE folders ADD COLUMN IF NOT EXISTS api_key_created TEXT;

CREATE INDEX IF NOT EXISTS folders_user ON folders (user_id);
CREATE INDEX IF NOT EXISTS documents_folder ON documents (folder_id);
CREATE INDEX IF NOT EXISTS extractions_user ON extractions (user_id);
CREATE INDEX IF NOT EXISTS templates_user ON templates (user_id);

-- Supabase exposes tables in public through its REST API with the public anon key. Row level security without
-- any policies closes that road completely. The backend connects as the owner and is not affected.
ALTER TABLE folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE extractions ENABLE ROW LEVEL SECURITY;
ALTER TABLE templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage ENABLE ROW LEVEL SECURITY;
