-- Exchange library schema, version 1.
--
-- Scanned data (environment ... entry_file) is rebuilt by rescans and reconstructible from disk.
-- The override layer (override_* and curation_log) is the user's work. It is keyed by dossier
-- uid with no foreign keys, so nothing the scanner deletes or rebuilds can cascade into it.
-- JSON columns hold UTF-8 JSON text. Timestamps are ISO 8601 UTC.

-- Environments and what is on disk -----------------------------------------------------------

CREATE TABLE environment (
    id                   INTEGER PRIMARY KEY,
    uid                  TEXT NOT NULL UNIQUE,
    type_id              TEXT NOT NULL,                  -- environment definition id
    name                 TEXT NOT NULL,
    root_path            TEXT NOT NULL,
    root_key             TEXT NOT NULL UNIQUE,           -- case-folded root_path
    variant              TEXT,
    layer_config         TEXT NOT NULL DEFAULT '{}',     -- e.g. MO2 selected profile
    detection_confidence REAL NOT NULL,
    detection_signals    TEXT NOT NULL DEFAULT '[]',
    status               TEXT NOT NULL DEFAULT 'online' CHECK (status IN ('online', 'offline')),
    added_at             TEXT NOT NULL,
    last_scanned_at      TEXT
);

CREATE TABLE scan (
    id             INTEGER PRIMARY KEY,
    environment_id INTEGER NOT NULL REFERENCES environment(id),
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    phase_reached  INTEGER NOT NULL DEFAULT 0,
    files_seen     INTEGER NOT NULL DEFAULT 0,
    files_new      INTEGER NOT NULL DEFAULT 0,
    files_changed  INTEGER NOT NULL DEFAULT 0,
    files_gone     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE container (
    id             INTEGER PRIMARY KEY,
    environment_id INTEGER NOT NULL REFERENCES environment(id),
    kind           TEXT NOT NULL,                        -- mod, content_directory, folder, ...
    name           TEXT NOT NULL,
    rel_path       TEXT NOT NULL,                        -- relative to the environment root
    rel_key        TEXT NOT NULL,
    scanned_meta   TEXT NOT NULL DEFAULT '{}',           -- e.g. meta.ini values
    UNIQUE (environment_id, rel_key)
);

CREATE TABLE file (
    id              INTEGER PRIMARY KEY,
    environment_id  INTEGER NOT NULL REFERENCES environment(id),
    container_id    INTEGER REFERENCES container(id),
    rel_path        TEXT NOT NULL,                       -- relative to the environment root
    rel_key         TEXT NOT NULL,
    ext             TEXT NOT NULL,
    size            INTEGER NOT NULL,
    mtime_ns        INTEGER NOT NULL,
    is_archive      INTEGER NOT NULL DEFAULT 0,          -- BSA/BA2/PCC/GMA/VAR: indexed by name only
    hash            TEXT,                                -- filled by scan phase 3
    state           TEXT NOT NULL CHECK (state IN ('present', 'gone', 'ignored')),
    first_seen_scan INTEGER NOT NULL REFERENCES scan(id),
    last_seen_scan  INTEGER NOT NULL REFERENCES scan(id),
    UNIQUE (environment_id, rel_key)
);
CREATE INDEX file_container ON file(container_id);

-- What assets are (scanned layer) ------------------------------------------------------------

CREATE TABLE dossier (
    id          INTEGER PRIMARY KEY,
    uid         TEXT NOT NULL UNIQUE,
    type_id     TEXT NOT NULL,                           -- dossier type definition id
    name        TEXT NOT NULL,
    parent_id   INTEGER REFERENCES dossier(id),          -- product -> child dossiers
    fingerprint TEXT,                                    -- content fingerprint, scan phase 3
    confidence  REAL NOT NULL,
    signals     TEXT NOT NULL DEFAULT '[]',              -- what produced this identification
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX dossier_parent ON dossier(parent_id);

CREATE TABLE dossier_field (
    dossier_id INTEGER NOT NULL REFERENCES dossier(id),
    field      TEXT NOT NULL,
    value      TEXT NOT NULL,                            -- JSON
    source     TEXT NOT NULL,                            -- e.g. scan:mo2, manifest, lookup:nexus
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (dossier_id, field, source)
);

CREATE TABLE dossier_tag (
    dossier_id INTEGER NOT NULL REFERENCES dossier(id),
    tag        TEXT NOT NULL,
    source     TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (dossier_id, tag, source)
);

CREATE TABLE dossier_token (
    dossier_id INTEGER NOT NULL REFERENCES dossier(id),
    position   INTEGER NOT NULL,
    token      TEXT NOT NULL,
    PRIMARY KEY (dossier_id, position)
);
CREATE INDEX dossier_token_token ON dossier_token(token);

-- Where assets are -----------------------------------------------------------------------------

CREATE TABLE ledger (
    id             INTEGER PRIMARY KEY,
    dossier_id     INTEGER NOT NULL REFERENCES dossier(id),
    environment_id INTEGER NOT NULL REFERENCES environment(id),
    UNIQUE (dossier_id, environment_id)
);

CREATE TABLE entry (
    id              INTEGER PRIMARY KEY,
    ledger_id       INTEGER NOT NULL REFERENCES ledger(id),
    container_id    INTEGER NOT NULL REFERENCES container(id),
    identity_key    TEXT NOT NULL,                       -- matches this entry again on rescan
    status          TEXT NOT NULL CHECK (status IN ('origin', 'requisitioned', 'copied', 'unknown',
                                                    'modified', 'stale', 'retired')),
    source_entry_id INTEGER REFERENCES entry(id),        -- provenance for copied/requisitioned
    requisition_id  INTEGER,                             -- table arrives with requisitions
    created_at      TEXT NOT NULL,
    retired_at      TEXT,
    UNIQUE (container_id, identity_key)
);
CREATE INDEX entry_ledger ON entry(ledger_id);

CREATE TABLE entry_file (
    entry_id INTEGER NOT NULL REFERENCES entry(id),
    file_id  INTEGER NOT NULL REFERENCES file(id),
    role     TEXT NOT NULL CHECK (role IN ('primary', 'support')),
    PRIMARY KEY (entry_id, file_id)
);
CREATE INDEX entry_file_file ON entry_file(file_id);

-- User override layer ----------------------------------------------------------------------------

CREATE TABLE override_field (
    dossier_uid TEXT NOT NULL,
    field       TEXT NOT NULL,                           -- name, type_id, or any dossier_field
    value       TEXT NOT NULL,                           -- JSON
    set_at      TEXT NOT NULL,
    PRIMARY KEY (dossier_uid, field)
);

CREATE TABLE override_tag (
    dossier_uid TEXT NOT NULL,
    tag         TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('add', 'remove')),
    set_at      TEXT NOT NULL,
    PRIMARY KEY (dossier_uid, tag)
);

CREATE TABLE override_link (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('file_to_dossier', 'dossier_to_parent')),
    subject    TEXT NOT NULL,           -- dossier uid, or "<environment uid>:<file rel_key>"
    target_uid TEXT,                    -- NULL detaches (e.g. "no parent")
    set_at     TEXT NOT NULL,
    UNIQUE (kind, subject)
);

CREATE TABLE curation_log (
    id      INTEGER PRIMARY KEY,
    at      TEXT NOT NULL,
    action  TEXT NOT NULL,
    payload TEXT NOT NULL                                -- JSON
);

-- Effective values: user overrides win over scanned values -------------------------------------

CREATE VIEW dossier_effective AS
SELECT
    d.id,
    d.uid,
    COALESCE(json_extract(o_name.value, '$'), d.name)   AS name,
    o_name.value IS NOT NULL                            AS name_overridden,
    COALESCE(json_extract(o_type.value, '$'), d.type_id) AS type_id,
    o_type.value IS NOT NULL                            AS type_overridden,
    CASE WHEN l.id IS NULL THEN d.parent_id
         ELSE (SELECT p.id FROM dossier p WHERE p.uid = l.target_uid) END AS parent_id,
    l.id IS NOT NULL                                    AS parent_overridden,
    d.confidence,
    d.signals,
    d.fingerprint,
    d.created_at,
    d.updated_at
FROM dossier d
LEFT JOIN override_field o_name ON o_name.dossier_uid = d.uid AND o_name.field = 'name'
LEFT JOIN override_field o_type ON o_type.dossier_uid = d.uid AND o_type.field = 'type_id'
LEFT JOIN override_link l ON l.kind = 'dossier_to_parent' AND l.subject = d.uid;

CREATE VIEW dossier_tag_effective AS
SELECT d.uid AS dossier_uid, t.tag, t.source
FROM dossier_tag t JOIN dossier d ON d.id = t.dossier_id
WHERE NOT EXISTS (SELECT 1 FROM override_tag o
                  WHERE o.dossier_uid = d.uid AND o.tag = t.tag AND o.action = 'remove')
UNION
SELECT o.dossier_uid, o.tag, 'user' FROM override_tag o WHERE o.action = 'add';
