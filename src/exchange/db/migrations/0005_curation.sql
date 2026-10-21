-- Exchange library schema, version 5: curation (Roadmap phase 3).
--
-- * dossier.confidence_base: the identification's own confidence; the classification pass adds
--   agreeing evidence on top of it into dossier.confidence (so re-classifying never compounds).
-- * entry.moved_from: set when the user (or duplicate detection) moved the entry onto another
--   dossier; a rescan then leaves that dossier's scanned values to its own entries.
-- * entry.variant: the asset variant an entry is (Pink, Blue), for variant-grouped dossiers.
-- * entry_file role 'linked': files the user linked onto a dossier (e.g. textures onto a mesh).
-- * override_link.role: what a linked file is to its dossier (texture, support, ...).
-- * User layer tables (no foreign keys, keyed by uid, never touched by scans):
--   dossier_alias (merged-away dossiers), collection + collection_member, suggestion decisions.

ALTER TABLE dossier ADD COLUMN confidence_base REAL;
UPDATE dossier SET confidence_base = confidence;

ALTER TABLE entry ADD COLUMN moved_from TEXT;            -- uid of the dossier it came from
ALTER TABLE entry ADD COLUMN variant TEXT;
UPDATE entry SET moved_from = 'duplicate' WHERE status = 'unknown';

CREATE TABLE entry_file_v5 (
    entry_id INTEGER NOT NULL REFERENCES entry(id),
    file_id  INTEGER NOT NULL REFERENCES file(id),
    role     TEXT NOT NULL CHECK (role IN ('primary', 'support', 'linked')),
    PRIMARY KEY (entry_id, file_id)
);
INSERT INTO entry_file_v5 SELECT entry_id, file_id, role FROM entry_file;
DROP TABLE entry_file;
ALTER TABLE entry_file_v5 RENAME TO entry_file;
CREATE INDEX entry_file_file ON entry_file(file_id);

ALTER TABLE override_link ADD COLUMN role TEXT;

-- User layer ---------------------------------------------------------------------------------

CREATE TABLE dossier_alias (
    alias_uid  TEXT PRIMARY KEY,                         -- the dossier merged away
    target_uid TEXT NOT NULL,                            -- the dossier it was merged into
    set_at     TEXT NOT NULL
);

CREATE TABLE collection (
    uid        TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    query      TEXT,                                     -- smart collections: a saved search
    created_at TEXT NOT NULL
);

CREATE TABLE collection_member (
    collection_uid TEXT NOT NULL,
    dossier_uid    TEXT NOT NULL,
    added_at       TEXT NOT NULL,
    PRIMARY KEY (collection_uid, dossier_uid)
);

-- Proposals the user accepts or rejects. key is deterministic, so a rejected proposal is not made
-- again; state 'stale' means the files that prompted it are gone or changed.
CREATE TABLE suggestion (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('texture_link', 'variant_group', 'lexicon_word')),
    key         TEXT NOT NULL UNIQUE,
    subject_uid TEXT,
    payload     TEXT NOT NULL,                           -- JSON
    confidence  REAL NOT NULL,
    state       TEXT NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending', 'accepted', 'rejected', 'stale')),
    created_at  TEXT NOT NULL,
    decided_at  TEXT,
    log_id      INTEGER                                  -- curation_log row of the accepting action
);
CREATE INDEX suggestion_state ON suggestion(state, kind);
