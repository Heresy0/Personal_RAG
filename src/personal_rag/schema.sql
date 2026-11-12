CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS rag_meta (key text PRIMARY KEY, value text NOT NULL);
CREATE TABLE IF NOT EXISTS notes (
    id uuid PRIMARY KEY,
    space text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    relative_path text NOT NULL UNIQUE,
    tags jsonb NOT NULL DEFAULT '[]',
    event_date date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    revision integer NOT NULL DEFAULT 1,
    file_hash text NOT NULL,
    source_type text NOT NULL DEFAULT 'original',
    source_ids jsonb NOT NULL DEFAULT '[]',
    deleted boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS notes_space_date ON notes(space,event_date) WHERE NOT deleted;
CREATE TABLE IF NOT EXISTS note_versions (
    note_id uuid NOT NULL,
    revision integer NOT NULL,
    body text NOT NULL,
    metadata jsonb NOT NULL,
    saved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(note_id, revision)
);
CREATE TABLE IF NOT EXISTS parents (
    id uuid PRIMARY KEY,
    note_id uuid NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    content text NOT NULL,
    section text NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id uuid PRIMARY KEY,
    note_id uuid NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    parent_id uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    content text NOT NULL,
    metadata jsonb NOT NULL,
    embedding vector(__DIMENSIONS__),
    embedding_key text,
    UNIQUE(note_id, ordinal)
);
CREATE INDEX IF NOT EXISTS chunks_note_id ON chunks(note_id);

-- Preserve history even when a note is physically deleted by an administrator.
ALTER TABLE note_versions DROP CONSTRAINT IF EXISTS note_versions_note_id_fkey;
CREATE TABLE IF NOT EXISTS write_audit (
    id uuid PRIMARY KEY,
    operation_id uuid NOT NULL,
    parent_operation_id uuid,
    event_kind text NOT NULL CHECK (event_kind IN ('attempt','change')),
    operation text NOT NULL,
    connection_name text NOT NULL,
    request_id uuid,
    note_id uuid,
    space text,
    before_revision integer,
    after_revision integer,
    expected_revision integer,
    outcome text NOT NULL CHECK (outcome IN ('started','success','noop','partial','failure','denied','committed_error','unknown')),
    change_kind text,
    error_code text,
    details jsonb NOT NULL DEFAULT '{}',
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS write_audit_note ON write_audit(note_id,recorded_at DESC,id);
CREATE INDEX IF NOT EXISTS write_audit_operation ON write_audit(operation_id,event_kind);
CREATE INDEX IF NOT EXISTS write_audit_parent ON write_audit(parent_operation_id);

CREATE OR REPLACE FUNCTION personal_rag_audit_note() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    ctx jsonb := COALESCE(NULLIF(current_setting('personal_rag.audit_context',true),''),'{}')::jsonb;
    prior jsonb;
    following jsonb;
    subject jsonb;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        prior := to_jsonb(OLD);
        INSERT INTO note_versions(note_id,revision,body,metadata)
            VALUES (OLD.id,OLD.revision,OLD.body,prior - 'body') ON CONFLICT DO NOTHING;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        following := to_jsonb(NEW);
        INSERT INTO note_versions(note_id,revision,body,metadata)
            VALUES (NEW.id,NEW.revision,NEW.body,following - 'body') ON CONFLICT DO NOTHING;
    END IF;
    subject := COALESCE(following,prior);
    INSERT INTO write_audit(id,operation_id,parent_operation_id,event_kind,operation,connection_name,
        request_id,note_id,space,before_revision,after_revision,outcome,change_kind,finished_at)
        VALUES (gen_random_uuid(),COALESCE((ctx->>'operation_id')::uuid,gen_random_uuid()),
            (ctx->>'parent_operation_id')::uuid,'change',COALESCE(ctx->>'operation','database_write'),
            COALESCE(ctx->>'connection_name','database'),(ctx->>'request_id')::uuid,(subject->>'id')::uuid,
            subject->>'space',(prior->>'revision')::integer,(following->>'revision')::integer,
            'success',lower(TG_OP),clock_timestamp());
    RETURN COALESCE(NEW,OLD);
END $$;
CREATE OR REPLACE FUNCTION personal_rag_note_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.revision := OLD.revision + 1;
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS personal_rag_note_revision ON notes;
CREATE TRIGGER personal_rag_note_revision BEFORE UPDATE ON notes
    FOR EACH ROW EXECUTE FUNCTION personal_rag_note_revision();
DROP TRIGGER IF EXISTS personal_rag_note_audit ON notes;
CREATE TRIGGER personal_rag_note_audit AFTER INSERT OR UPDATE OR DELETE ON notes
    FOR EACH ROW EXECUTE FUNCTION personal_rag_audit_note();
-- Migration baseline only: do not invent historical operations for pre-audit data.
INSERT INTO note_versions(note_id,revision,body,metadata)
    SELECT id,revision,body,to_jsonb(notes)-'body' FROM notes ON CONFLICT DO NOTHING;
INSERT INTO rag_meta(key,value) VALUES ('audit_schema','1') ON CONFLICT(key) DO UPDATE SET value=excluded.value;

CREATE TABLE IF NOT EXISTS mail_sources (
    id text PRIMARY KEY,
    identity_hash text NOT NULL,
    uidvalidity bigint NOT NULL,
    baseline_uid bigint NOT NULL,
    next_uid bigint NOT NULL,
    enabled_at timestamptz NOT NULL,
    last_checked_at timestamptz,
    last_error text
);
CREATE TABLE IF NOT EXISTS mail_items (
    source_id text NOT NULL REFERENCES mail_sources(id),
    uidvalidity bigint NOT NULL,
    uid bigint NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','saved','failed','skipped','missing')),
    request_id uuid NOT NULL UNIQUE,
    received_at timestamptz,
    size_bytes bigint,
    raw_sha256 text,
    capture_sha256 text,
    note_id uuid,
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(source_id,uidvalidity,uid)
);
CREATE TABLE IF NOT EXISTS mail_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id text NOT NULL,
    uid bigint,
    outcome text NOT NULL,
    error_code text,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS mail_queue ON mail_items(source_id,status,attempts,uid);
