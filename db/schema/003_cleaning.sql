-- Cleaning staff, services and jobs (spec 3.9, 3.10) - Phase 4.
--
-- One deviation from the entity list in section 6: instead of a general
-- Cleaning Rule table of (trigger, parameters), the two things that are
-- actually configurable per flat - how long a stay must be before it is tidied
-- partway through, and how often a deep clean comes round - are columns on a
-- settings row. Same information, without a parameter bag nobody can read.

CREATE TABLE cleaning_staff (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The standard price of each service, applying to every flat unless a flat
-- has a negotiated one below.
CREATE TABLE cleaning_service_types (
    label           TEXT PRIMARY KEY
                    CHECK (label IN ('changeover clean', 'post-clean', 'pre-clean',
                                     'light clean', 'deep clean')),
    standard_cost   NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (standard_cost >= 0),
    default_minutes INTEGER CHECK (default_minutes > 0)
);

INSERT INTO cleaning_service_types (label, standard_cost, default_minutes) VALUES
    ('changeover clean', 0.00, 180),
    ('post-clean',       0.00, 120),
    ('pre-clean',        0.00, 60),
    ('light clean',      0.00, 60),
    ('deep clean',       0.00, 300);

-- Only where a price was negotiated away from the standard for one flat, so
-- most flats need no row at all (3.10).
CREATE TABLE unit_cleaning_rates (
    unit_id       INTEGER NOT NULL REFERENCES units (id) ON DELETE CASCADE,
    service_label TEXT NOT NULL REFERENCES cleaning_service_types (label) ON DELETE CASCADE,
    cost          NUMERIC(12, 2) NOT NULL CHECK (cost >= 0),
    PRIMARY KEY (unit_id, service_label)
);

CREATE TABLE unit_cleaning_settings (
    unit_id            INTEGER PRIMARY KEY REFERENCES units (id) ON DELETE CASCADE,
    -- A stay longer than this gets tidied partway through, one every
    -- light_every_nights after that.
    light_after_nights INTEGER NOT NULL DEFAULT 10 CHECK (light_after_nights > 0),
    light_every_nights INTEGER NOT NULL DEFAULT 7 CHECK (light_every_nights > 0),
    -- Quarterly by default; 0 means this flat has no periodic deep clean.
    deep_every_days    INTEGER NOT NULL DEFAULT 91 CHECK (deep_every_days >= 0)
);

CREATE TABLE cleaning_jobs (
    id            SERIAL PRIMARY KEY,
    unit_id       INTEGER NOT NULL REFERENCES units (id) ON DELETE CASCADE,
    date          DATE NOT NULL,
    service_label TEXT NOT NULL REFERENCES cleaning_service_types (label),
    staff_id      INTEGER REFERENCES cleaning_staff (id) ON DELETE SET NULL,
    -- Blank for work not tied to a stay, such as a periodic deep clean.
    booking_id    INTEGER REFERENCES bookings (id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'scheduled'
                  CHECK (status IN ('scheduled', 'done', 'missed')),
    -- Stamped when the job is created rather than looked up when the owner is
    -- invoiced: what they are charged should not move because a rate was
    -- edited afterwards.
    cost          NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (cost >= 0),
    notes         TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One visit of a given kind per flat per day. This is what lets the rules
    -- be re-run without scheduling everything a second time.
    UNIQUE (unit_id, date, service_label)
);

CREATE INDEX cleaning_jobs_date_idx ON cleaning_jobs (date);
CREATE INDEX cleaning_jobs_unit_date_idx ON cleaning_jobs (unit_id, date);
CREATE INDEX cleaning_jobs_staff_idx ON cleaning_jobs (staff_id, date);
