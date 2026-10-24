-- Pipelines are renamed processes (2026-10). A requisition item's chain is in `processes`, and each
-- of its outputs names its process under "process" instead of "pipeline". Option values in
-- `params` are keyed by process id, which does not change.

ALTER TABLE requisition_item RENAME COLUMN pipelines TO processes;

UPDATE requisition_item
SET outputs = (
    SELECT json_group_array(
        CASE WHEN json_type(value, '$.pipeline') IS NULL THEN json(value)
             ELSE json_remove(json_set(value, '$.process', json_extract(value, '$.pipeline')), '$.pipeline')
        END)
    FROM (SELECT value FROM json_each(requisition_item.outputs) ORDER BY key)
)
WHERE outputs IS NOT NULL AND json_valid(outputs) AND json_type(outputs) = 'array';
