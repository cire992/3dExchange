-- Exchange library schema, version 4.
--
-- Library-wide settings, as JSON values. First use: "excluded_roots", folders the user unticked
-- when adding environments; scans skip them entirely.

CREATE TABLE library_setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL                                  -- JSON
);
