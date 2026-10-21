-- Exchange library schema, version 3.
--
-- Each scan records how many files belong to no asset, so the sidebar can show the count without
-- counting millions of files live. Existing scans get it from the next rescan.

ALTER TABLE scan ADD COLUMN unattached_files INTEGER NOT NULL DEFAULT 0;
