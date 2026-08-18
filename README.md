# RentalMan

An internal web app for managing self-catering flats on behalf of their owners:
bookings, seasonal rates, quotes, cleaning and owner statements. Built for two
people on two laptops, working from the same live data.

The full requirements are in [rentalman-spec.md](rentalman-spec.md). Section
numbers referenced in the code point there.

## Status

**Phases 1 and 2 are built** (spec section 9):

- Units and owners, the shared season calendar, client rate files, turnover rules
- The booking grid, and entering bookings by hand
- Availability search: dates and party size in, free flats out, each already priced
- Quotes: saved with their priced lines, sent as a WhatsApp-ready message or a
  PDF, reopened and resent later, and flagged for follow-up after seven days

Bookings can be entered and corrected by hand on the Bookings page, brought
forward from Phase 3 so the flats' existing bookings can be captured now. Every
save is checked against what is already on file, turnover buffers included.
Creating a booking by accepting a quote still belongs to Phase 3, and will run
through the same checks rather than becoming a second way in.

## Running it

You need a Postgres database. The intended host is [Neon](https://neon.tech),
whose free tier is ample here, but any Postgres 12+ will do for local work.

```bash
pip install -r requirements.txt

# 1. Tell the app where the database is.
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
#    ...and paste your Neon connection string into it.
#    The scripts below read DATABASE_URL instead, from the shell or a .env file:
export DATABASE_URL='postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/rentalman?sslmode=require'

# 2. Create the tables.
python -m db.migrate

# 3. Optional: invented demo data, to see the calendar with something on it.
python -m db.seed

# 4. Run it.
streamlit run app.py
```

Deploying to Streamlit Community Cloud: point it at this repository and paste
the same `secrets.toml` contents into the app's secrets box. Add an `[auth]`
section with a `password` to put a shared password in front of the app; without
one the gate stands aside, which is what you want on your own machine.

## Layout

```
app.py            Home: what is connected, what still needs filling in
pages/            One file per screen; Streamlit builds the navigation from it
lib/              Business logic — no database, no Streamlit, fully tested
  models.py         The entities from spec section 6
  seasons.py        The shared season calendar and stay segmenting
  rates.py          Quote pricing and minimum-stay rules
  availability.py   Turnover buffers and what blocks a unit
  quotes.py         The guest-facing message and the follow-up flag
db/               Connection, migrations, and the queries the pages run
  schema/           Numbered .sql files, applied in order and never edited
ui/               Streamlit-side helpers: the grid, PDFs, formatting, login
tests/            pytest — logic tests, plus every page run under AppTest
```

The split between `lib/` and everything else is the important one: the money
calculations and the availability rules take plain objects and return plain
objects, so they can be tested directly and reused by the owner-statement side
in Phase 5 without change.

## Tests

```bash
python -m pytest
```

No database is needed. The logic tests are pure; the page tests run each screen
through Streamlit's `AppTest` with the queries stubbed, including the
day-one case where nothing has been captured yet.

## Decisions worth knowing

- A night belongs to the season covering the date it **starts** on, and the
  check-out date is never charged. Everything downstream depends on this.
- Rates are versioned by year, and the version used is the one on the season
  definition the nights came from — so a season running 1 December into
  15 January prices its January nights at the December year's rate.
- Buffer nights vary by unit and by season. Where they differ, the buffer at a
  given changeover is taken from the season covering **that changeover date**.
- Only `confirmed` bookings hold dates. Enquiries and unaccepted quotes do not
  take a flat off the market (`BLOCKING_STATUSES` in `lib/models.py`).
- Money is `Decimal` everywhere, never `float`.
- A saved quote keeps its own priced lines. Reopening one shows what the guest
  was told, not what today's rate file would charge.
- The follow-up flag is derived on read, never stored — so it is always true
  without anything having to run overnight.
