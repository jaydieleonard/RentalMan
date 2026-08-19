-- A flat gets at most one clean a day (business rule, confirmed).
--
-- 003 allowed one of each kind per flat per day, which let a deep clean fall
-- on a changeover day: two visits, and two charges to the owner, for a day
-- that needs one. lib/cleaning.py moves the more flexible clean to another
-- day; this is the guarantee underneath it.

ALTER TABLE cleaning_jobs
    DROP CONSTRAINT cleaning_jobs_unit_id_date_service_label_key;

ALTER TABLE cleaning_jobs
    ADD CONSTRAINT cleaning_jobs_one_per_flat_per_day UNIQUE (unit_id, date);
