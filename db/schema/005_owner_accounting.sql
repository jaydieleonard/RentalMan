-- Owner rates and monthly statements (spec 3.7, 3.8) - Phase 5.

-- What is due to the owner per night, per season, per year. The same shape as
-- client_rates and deliberately a separate figure: the business earns from the
-- monthly management fee, not from a margin between the two, so one is never
-- worked out from the other.
CREATE TABLE owner_rates (
    unit_id      INTEGER NOT NULL REFERENCES units (id) ON DELETE CASCADE,
    season_label TEXT NOT NULL CHECK (season_label IN ('Low', 'Medium', 'High')),
    year         INTEGER NOT NULL,
    nightly_rate NUMERIC(12, 2) NOT NULL CHECK (nightly_rate >= 0),
    PRIMARY KEY (unit_id, season_label, year)
);

CREATE TABLE owner_statements (
    id              SERIAL PRIMARY KEY,
    owner_id        INTEGER NOT NULL REFERENCES owners (id) ON DELETE RESTRICT,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    -- Totals are stored as they were worked out, not recomputed on the way
    -- out. A statement sent to an owner is a statement of what was owed that
    -- month; editing a rate afterwards must not rewrite history.
    rental_income   NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    management_fees NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    cleaning_costs  NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    net_due         NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'sent', 'paid')),
    generated_on    DATE NOT NULL DEFAULT CURRENT_DATE,
    -- Blank until the money has actually gone across, which happens outside
    -- this app - nothing here moves anything (3.8).
    paid_on         DATE,
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One statement per owner per month; regenerating replaces its lines
    -- rather than quietly producing a second copy.
    UNIQUE (owner_id, year, month)
);

CREATE INDEX owner_statements_period_idx ON owner_statements (year, month);
CREATE INDEX owner_statements_status_idx ON owner_statements (status);

CREATE TABLE owner_statement_lines (
    id           SERIAL PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES owner_statements (id) ON DELETE CASCADE,
    unit_id      INTEGER NOT NULL REFERENCES units (id) ON DELETE RESTRICT,
    line_number  INTEGER NOT NULL,
    -- Which of the three figures this is. They are kept apart everywhere,
    -- on screen and on the document, because confusing them is the one
    -- mistake an owner statement must never make.
    kind         TEXT NOT NULL
                 CHECK (kind IN ('rental income', 'management fee', 'cleaning cost')),
    description  TEXT NOT NULL DEFAULT '',
    amount       NUMERIC(12, 2) NOT NULL,
    UNIQUE (statement_id, line_number)
);

CREATE INDEX owner_statement_lines_statement_idx ON owner_statement_lines (statement_id);
