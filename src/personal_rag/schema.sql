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
    note_id uuid NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
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
