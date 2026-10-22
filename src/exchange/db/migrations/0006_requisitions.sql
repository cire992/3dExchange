-- Requisitions (Roadmap phase 4): conversion jobs, their items, and every file they wrote.

CREATE TABLE requisition (
    id           INTEGER PRIMARY KEY,
    uid          TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN ('queued', 'held', 'running', 'needs_attention', 'fulfilled',
                                                'partially_fulfilled', 'failed', 'stale', 'removed', 'replaced')),
    position     INTEGER NOT NULL,                       -- order in the queue
    environment_id INTEGER NOT NULL,                     -- the target environment
    endpoint     TEXT NOT NULL,                          -- JSON: where output goes (see requisitions.endpoints)
    on_collision TEXT NOT NULL DEFAULT 'ask' CHECK (on_collision IN ('ask', 'overwrite', 'rename', 'skip')),
    message      TEXT,                                   -- why it needs attention or failed
    replaces     INTEGER,                                -- the requisition a rebuild replaces
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);
CREATE INDEX requisition_state ON requisition(state, position);

CREATE TABLE requisition_item (
    id              INTEGER PRIMARY KEY,
    requisition_id  INTEGER NOT NULL REFERENCES requisition(id),
    dossier_uid     TEXT NOT NULL,                       -- what is converted
    source_entry_id INTEGER,                             -- which copy of it
    pipelines       TEXT NOT NULL,                       -- JSON [{"id", "version"}]: one, or a chain
    params          TEXT NOT NULL,                       -- JSON {pipeline id: {parameter: value}}
    include         INTEGER NOT NULL DEFAULT 1,
    state           TEXT NOT NULL CHECK (state IN ('queued', 'running', 'needs_attention', 'done', 'failed', 'skipped')),
    message         TEXT,
    source_fingerprint TEXT,                             -- the source files when it ran, for staleness
    outputs         TEXT                                 -- JSON: files written, relative to the endpoint
);
CREATE INDEX requisition_item_requisition ON requisition_item(requisition_id);

-- Every file a requisition wrote, so its output can be removed cleanly (moved to the recycle
-- folder, never deleted) and an overwritten file put back.
CREATE TABLE requisition_write (
    id             INTEGER PRIMARY KEY,
    requisition_id INTEGER NOT NULL REFERENCES requisition(id),
    item_id        INTEGER,
    path           TEXT NOT NULL,                        -- absolute
    action         TEXT NOT NULL CHECK (action IN ('created', 'overwritten', 'sidecar')),
    recycled_to    TEXT,                                 -- the overwritten file's previous version
    written_at     TEXT NOT NULL,
    removed_at     TEXT
);
CREATE INDEX requisition_write_requisition ON requisition_write(requisition_id);
CREATE INDEX entry_requisition ON entry(requisition_id);
