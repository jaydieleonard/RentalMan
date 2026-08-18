-- Saved quotes (spec 3.5, 3.6) - Phase 2.
--
-- The priced lines are stored alongside the quote rather than recalculated
-- when it is reopened. A quote is a promise made on a particular day: editing
-- next year's rates must never change what a guest was told last week.

CREATE TABLE quotes (
    id           SERIAL PRIMARY KEY,
    unit_id      INTEGER NOT NULL REFERENCES units (id) ON DELETE RESTRICT,
    client_id    INTEGER REFERENCES clients (id) ON DELETE SET NULL,
    -- Filled in when the quote is accepted and becomes a booking (Phase 3).
    booking_id   INTEGER REFERENCES bookings (id) ON DELETE SET NULL,
    check_in     DATE NOT NULL,
    check_out    DATE NOT NULL,
    guests       INTEGER CHECK (guests > 0),
    total        NUMERIC(12, 2) NOT NULL CHECK (total >= 0),
    status       TEXT NOT NULL DEFAULT 'quoted'
                 CHECK (status IN ('quoted', 'accepted', 'cancelled')),
    -- The follow-up flag (3.5) is derived from this date and the status, not
    -- stored: a stored flag would need a nightly job to stay true.
    generated_on DATE NOT NULL DEFAULT CURRENT_DATE,
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (check_out > check_in)
);

CREATE INDEX quotes_status_idx ON quotes (status);
CREATE INDEX quotes_generated_idx ON quotes (generated_on);
CREATE INDEX quotes_unit_idx ON quotes (unit_id);
CREATE INDEX quotes_client_idx ON quotes (client_id);

-- One row per season segment of the stay, in the order they were quoted.
CREATE TABLE quote_lines (
    quote_id     INTEGER NOT NULL REFERENCES quotes (id) ON DELETE CASCADE,
    line_number  INTEGER NOT NULL,
    season_label TEXT NOT NULL,
    first_night  DATE NOT NULL,
    last_night   DATE NOT NULL,
    nights       INTEGER NOT NULL CHECK (nights > 0),
    nightly_rate NUMERIC(12, 2) NOT NULL,
    subtotal     NUMERIC(12, 2) NOT NULL,
    PRIMARY KEY (quote_id, line_number)
);
