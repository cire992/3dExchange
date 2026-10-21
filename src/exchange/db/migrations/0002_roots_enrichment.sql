-- Exchange library schema, version 2.
--
-- * An environment can span several folders (roots): one Daz Studio environment holds every
--   content directory. Containers and files now belong to a root, and paths are relative to it.
-- * Roots can go offline (a disconnected drive) without their entries being retired.
-- * Per-environment user configuration (ignore rules, MO2 profile, endpoint, visibility).
-- * Scan phase 3 output: dependencies, thumbnails, and a full-text search index.
--
-- Tables are rebuilt where SQLite cannot alter constraints; the migration runner turns foreign
-- keys off around migrations and checks them afterwards.

-- Roots --------------------------------------------------------------------------------------

CREATE TABLE environment_root (
    id                   INTEGER PRIMARY KEY,
    environment_id       INTEGER NOT NULL REFERENCES environment(id),
    path                 TEXT NOT NULL,
    root_key             TEXT NOT NULL UNIQUE,           -- case-folded path
    variant              TEXT,
    detection_confidence REAL NOT NULL,
    detection_signals    TEXT NOT NULL DEFAULT '[]',
    status               TEXT NOT NULL DEFAULT 'online' CHECK (status IN ('online', 'offline')),
    offline_since        TEXT,
    added_at             TEXT NOT NULL,
    last_scanned_at      TEXT
);
CREATE INDEX environment_root_environment ON environment_root(environment_id);

INSERT INTO environment_root (environment_id, path, root_key, variant, detection_confidence,
                              detection_signals, status, added_at, last_scanned_at)
SELECT id, root_path, root_key, variant, detection_confidence, detection_signals, status,
       added_at, last_scanned_at
FROM environment;

CREATE TABLE environment_v2 (
    id              INTEGER PRIMARY KEY,
    uid             TEXT NOT NULL UNIQUE,
    type_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    layer_config    TEXT NOT NULL DEFAULT '{}',          -- what the layer reported, per scan
    user_config     TEXT NOT NULL DEFAULT '{}',          -- ignore rules, profile, endpoint, ...
    added_at        TEXT NOT NULL,
    last_scanned_at TEXT
);
INSERT INTO environment_v2 (id, uid, type_id, name, layer_config, added_at, last_scanned_at)
SELECT id, uid, type_id, name, layer_config, added_at, last_scanned_at FROM environment;
DROP TABLE environment;
ALTER TABLE environment_v2 RENAME TO environment;

-- Containers and files belong to a root ------------------------------------------------------

CREATE TABLE container_v2 (
    id             INTEGER PRIMARY KEY,
    environment_id INTEGER NOT NULL REFERENCES environment(id),
    root_id        INTEGER NOT NULL REFERENCES environment_root(id),
    kind           TEXT NOT NULL,
    name           TEXT NOT NULL,
    rel_path       TEXT NOT NULL,                        -- relative to the root
    rel_key        TEXT NOT NULL,
    scanned_meta   TEXT NOT NULL DEFAULT '{}',
    UNIQUE (root_id, rel_key)
);
INSERT INTO container_v2 (id, environment_id, root_id, kind, name, rel_path, rel_key, scanned_meta)
SELECT c.id, c.environment_id, r.id, c.kind, c.name, c.rel_path, c.rel_key, c.scanned_meta
FROM container c JOIN environment_root r ON r.environment_id = c.environment_id;
DROP TABLE container;
ALTER TABLE container_v2 RENAME TO container;

CREATE TABLE file_v2 (
    id              INTEGER PRIMARY KEY,
    environment_id  INTEGER NOT NULL REFERENCES environment(id),
    root_id         INTEGER NOT NULL REFERENCES environment_root(id),
    container_id    INTEGER REFERENCES container(id),
    rel_path        TEXT NOT NULL,                       -- relative to the root
    rel_key         TEXT NOT NULL,
    ext             TEXT NOT NULL,
    size            INTEGER NOT NULL,
    mtime_ns        INTEGER NOT NULL,
    is_archive      INTEGER NOT NULL DEFAULT 0,
    hash            TEXT,                                -- BLAKE2b-128 hex, scan phase 3
    state           TEXT NOT NULL CHECK (state IN ('present', 'gone', 'ignored')),
    first_seen_scan INTEGER NOT NULL REFERENCES scan(id),
    last_seen_scan  INTEGER NOT NULL REFERENCES scan(id),
    UNIQUE (root_id, rel_key)
);
INSERT INTO file_v2 (id, environment_id, root_id, container_id, rel_path, rel_key, ext, size,
                     mtime_ns, is_archive, hash, state, first_seen_scan, last_seen_scan)
SELECT f.id, f.environment_id, r.id, f.container_id, f.rel_path, f.rel_key, f.ext, f.size,
       f.mtime_ns, f.is_archive, f.hash, f.state, f.first_seen_scan, f.last_seen_scan
FROM file f JOIN environment_root r ON r.environment_id = f.environment_id;
DROP TABLE file;
ALTER TABLE file_v2 RENAME TO file;
CREATE INDEX file_container ON file(container_id);
CREATE INDEX file_hash ON file(hash) WHERE hash IS NOT NULL;
CREATE INDEX file_environment ON file(environment_id);

ALTER TABLE scan ADD COLUMN root_id INTEGER REFERENCES environment_root(id);
UPDATE scan SET root_id = (SELECT r.id FROM environment_root r WHERE r.environment_id = scan.environment_id);

-- Scanned fields are now recorded per container ("scan:<handler>:<container id>"); the old
-- per-handler rows are regenerated by the next scan.
DELETE FROM dossier_field WHERE source IN ('scan:daz', 'scan:mo2', 'scan:folder');

-- Scan phase 3 output ------------------------------------------------------------------------

CREATE TABLE dossier_dependency (
    id                INTEGER PRIMARY KEY,
    dossier_id        INTEGER NOT NULL REFERENCES dossier(id),
    reference         TEXT NOT NULL,                     -- decoded path as written in the file
    target_file_id    INTEGER REFERENCES file(id),
    target_dossier_id INTEGER REFERENCES dossier(id),
    status            TEXT NOT NULL CHECK (status IN ('ok', 'broken')),
    UNIQUE (dossier_id, reference)
);
CREATE INDEX dossier_dependency_target ON dossier_dependency(target_dossier_id);

CREATE TABLE thumbnail (
    dossier_id     INTEGER PRIMARY KEY REFERENCES dossier(id),
    rel_path       TEXT NOT NULL,                        -- inside the thumbnail cache folder
    source_kind    TEXT NOT NULL,                        -- preview, embedded, image, render, child
    source_file_id INTEGER REFERENCES file(id),
    source_hash    TEXT,                                 -- regenerated when this changes
    made_at        TEXT NOT NULL
);

-- Full-text search over effective names, filename tokens, tags and containers. rowid = dossier id.
CREATE VIRTUAL TABLE dossier_fts USING fts5(name, tokens, tags, places,
                                            tokenize = 'unicode61 remove_diacritics 2');
