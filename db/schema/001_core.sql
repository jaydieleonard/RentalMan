-- RentalMan core schema (spec section 6), Phase 1-2 entities.
--
-- Later phases add their own numbered file rather than editing this one:
--   quotes, owner rates, cleaning staff/jobs/rules, owner statements.
--
-- Money is NUMERIC, never float. Dates that name a departure (bookings.check_out,
-- unit_blocks.end_date) are EXCLUSIVE - the guest does not sleep there that night.

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE owners (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    phone           TEXT NOT NULL DEFAULT '',
    email           TEXT NOT NULL DEFAULT '',
    -- Reference only, so the parents know where to pay. Nothing in this app
    -- moves money (spec 3.7, 3.8).
    banking_details TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE units (
    id                     SERIAL PRIMARY KEY,
    name                   TEXT NOT NULL UNIQUE,
    beds                   INTEGER NOT NULL DEFAULT 1 CHECK (beds > 0),
    sleeps                 INTEGER NOT NULL DEFAULT 2 CHECK (sleeps > 0),
    -- Exactly one owner per unit - joint ownership is out of scope (3.7).
    owner_id               INTEGER NOT NULL REFERENCES owners (id) ON DELETE RESTRICT,
    monthly_management_fee NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (monthly_management_fee >= 0),
    -- 2 nights for most units, 1 for the one that takes single nights (3.4).
    min_nights             INTEGER NOT NULL DEFAULT 2 CHECK (min_nights >= 1),
    -- NULL means "use the business-wide changeover window" (3.10).
    checkout_time          TIME,
    checkin_time           TIME,
    -- Free-text grouping for filtering a grid that has to stay readable past
    -- 30 units (3.1) - block, area, building, whatever they actually use.
    group_tag              TEXT NOT NULL DEFAULT '',
    notes                  TEXT NOT NULL DEFAULT '',
    active                 BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX units_owner_idx ON units (owner_id);

-- One shared season calendar for every unit (3.3). Both dates INCLUSIVE.
CREATE TABLE season_definitions (
    id         SERIAL PRIMARY KEY,
    label      TEXT NOT NULL CHECK (label IN ('Low', 'Medium', 'High')),
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL,
    -- The rate version these dates price against. A season running 1 Dec into
    -- 15 Jan is one row, filed under the year it starts in.
    year       INTEGER NOT NULL,
    CHECK (end_date >= start_date),
    -- No date may belong to two seasons; the Seasons page reports this in
    -- plain English before the database has to refuse it.
    EXCLUDE USING gist (daterange(start_date, end_date, '[]') WITH &&)
);

CREATE INDEX season_definitions_year_idx ON season_definitions (year);

-- The nightly figure charged to the guest (3.4). The owner rate (3.7) is a
-- separate table added in the Phase 5 migration, deliberately not derived.
CREATE TABLE client_rates (
    unit_id      INTEGER NOT NULL REFERENCES units (id) ON DELETE CASCADE,
    season_label TEXT NOT NULL CHECK (season_label IN ('Low', 'Medium', 'High')),
    year         INTEGER NOT NULL,
    nightly_rate NUMERIC(12, 2) NOT NULL CHECK (nightly_rate >= 0),
    -- The season's own minimum, which can raise the unit's bar but never lower
    -- it. NULL means the season asks for nothing extra.
    min_nights   INTEGER CHECK (min_nights >= 1),
    PRIMARY KEY (unit_id, season_label, year)
);

CREATE TABLE clients (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL DEFAULT '',
    email      TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX clients_name_idx ON clients (lower(name));

CREATE TABLE bookings (
    id          SERIAL PRIMARY KEY,
    unit_id     INTEGER NOT NULL REFERENCES units (id) ON DELETE RESTRICT,
    client_id   INTEGER REFERENCES clients (id) ON DELETE SET NULL,
    check_in    DATE NOT NULL,
    -- Departure date, exclusive: the last charged night is the day before.
    check_out   DATE NOT NULL,
    status      TEXT NOT NULL DEFAULT 'enquiry'
                CHECK (status IN ('enquiry', 'quoted', 'confirmed', 'cancelled')),
    total_price NUMERIC(12, 2),
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (check_out > check_in),

    -- Two people booking at the same moment on two laptops is the exact
    -- scenario 4 and 5 worry about, so the last line of defence against a
    -- double-booking is the database itself, not the screen that got there
    -- first. Only confirmed stays hold dates; enquiries and quotes do not.
    -- Turnover buffers are enforced in lib/availability.py rather than here:
    -- they vary by unit and season, which a constraint cannot see.
    EXCLUDE USING gist (
        unit_id WITH =,
        daterange(check_in, check_out) WITH &&
    ) WHERE (status = 'confirmed')
);

CREATE INDEX bookings_unit_dates_idx ON bookings (unit_id, check_in, check_out);
CREATE INDEX bookings_status_idx ON bookings (status);
CREATE INDEX bookings_client_idx ON bookings (client_id);

-- How many nights must sit free between one guest leaving and the next
-- arriving (3.10). Read by both the availability search and, from Phase 4, the
-- cleaning-job rules, so the policy is stated once.
CREATE TABLE turnover_rules (
    id            SERIAL PRIMARY KEY,
    unit_id       INTEGER NOT NULL REFERENCES units (id) ON DELETE CASCADE,
    -- NULL is the unit's all-seasons default; a label overrides it for that
    -- season only.
    season_label  TEXT CHECK (season_label IN ('Low', 'Medium', 'High')),
    -- 0 is same-day turnover: the confirmed norm, not the exception.
    buffer_nights INTEGER NOT NULL DEFAULT 0 CHECK (buffer_nights >= 0)
);

-- One default row and at most one row per season, per unit. Two partial
-- indexes rather than one constraint, because a plain UNIQUE would treat every
-- NULL season_label as distinct and let duplicate defaults through.
CREATE UNIQUE INDEX turnover_rules_season_idx
    ON turnover_rules (unit_id, season_label) WHERE season_label IS NOT NULL;
CREATE UNIQUE INDEX turnover_rules_default_idx
    ON turnover_rules (unit_id) WHERE season_label IS NULL;

-- Nights held off the market for the unit's own reasons: maintenance, the
-- owner using their own flat. 3.1 asks the grid to show these in grey; 6 has
-- no entity for them, so this is the one addition to the documented model.
CREATE TABLE unit_blocks (
    id         SERIAL PRIMARY KEY,
    unit_id    INTEGER NOT NULL REFERENCES units (id) ON DELETE CASCADE,
    start_date DATE NOT NULL,
    -- Exclusive, like a check-out date.
    end_date   DATE NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date > start_date)
);

CREATE INDEX unit_blocks_unit_dates_idx ON unit_blocks (unit_id, start_date, end_date);
