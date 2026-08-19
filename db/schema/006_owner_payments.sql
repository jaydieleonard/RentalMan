-- What has actually been paid against each statement (spec 9, Phase 6).
--
-- Phase 5 recorded settlement as one flag on the statement, which cannot hold
-- a part payment, a bank reference, or the fact that a month was settled in
-- two transfers three weeks apart. Payments are recorded one by one here and
-- the statement's flag follows them.

CREATE TABLE owner_payments (
    id           SERIAL PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES owner_statements (id) ON DELETE CASCADE,
    paid_on      DATE NOT NULL,
    -- Not constrained to be positive: a correction after a mistyped transfer
    -- is a negative line, which keeps the history honest rather than editing
    -- away what was recorded at the time.
    amount       NUMERIC(12, 2) NOT NULL,
    -- Whatever the bank calls it, so a payment here can be found on a
    -- statement there.
    reference    TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX owner_payments_statement_idx ON owner_payments (statement_id);
CREATE INDEX owner_payments_date_idx ON owner_payments (paid_on);

-- Anything already marked paid becomes a payment of the full amount on the
-- date it was marked, so no settlement history is lost in the change.
INSERT INTO owner_payments (statement_id, paid_on, amount, notes)
SELECT id, COALESCE(paid_on, generated_on), net_due,
       'Recorded before payments were kept individually'
  FROM owner_statements
 WHERE status = 'paid';
