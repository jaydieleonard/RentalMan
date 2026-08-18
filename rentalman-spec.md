# RentalMan — Project Spec

## 1. Background

Jaydie's parents manage roughly 15 self-catering flats in a coastal town on behalf of the flats' owners, with plans to grow. Today the day-to-day work is:

1. Keep track of which flats are booked and which are open, for any given date.
2. When an enquiry comes in for specific dates, quickly find which flats are free.
3. Once a flat is chosen (based on bed count and availability), generate a price quote for the client, based on that unit's rate for that specific date range (low / medium / high season).
4. Because they manage these units on the owners' behalf rather than owning them, they also need to account back to each owner: what rental income is due to them, less a management fee and any cleaning costs, paid out via a monthly statement.
5. Coordinate cleaning staff around guest check-ins and check-outs, with different types of clean (pre-clean, post-clean, light clean, deep clean) applying depending on the situation.

This spec describes a small web application — **RentalMan** — to support that whole workflow, sized for a family business (not a large property-management company), but built so it can grow past 15 units without a rewrite.

## 2. Who uses this

- 2 primary users (Jaydie's parents), each on their own laptop, working from the coastal town. They are the only users with full access (bookings, rates, owner statements, cleaning schedule).
- Occasionally, one of them may be away and need to check the calendar or send a quote remotely — worth designing for, even if not the primary use case on day one.
- Cleaning staff are referenced in the system (assigned to jobs) but don't need their own login in this version (confirmed) — the parents view and manage the cleaning calendar and communicate jobs to staff directly (phone/WhatsApp/printed list). A simple view for staff to see just their own upcoming jobs is a candidate for later development, not this version.
- No public-facing website or self-service client booking in this version. Clients enquire by phone/email/WhatsApp as they do now; the app is an internal tool.

## 3. Core requirements

### 3.1 Booking calendar (read at a glance)

- One screen shows all flats down the side and dates across the top (a "grid" or "gantt" style calendar), so a booked vs. open flat is visible instantly, without opening each flat individually.
- Color coding: e.g. green = open, red/blue = booked, grey = blocked/maintenance.
- Clicking a booked cell shows the client name, dates, and quote/booking reference.
- Must stay readable as the flat count grows from 15 towards 30+ — so the grid needs to scroll/filter (e.g. filter by number of beds, by owner, or by a group/area tag) rather than becoming one giant unreadable table.
- Default view: current month, with easy navigation to next/previous months and a jump-to-date option.

### 3.2 Availability search

- A search form: check-in date, check-out date, and optionally minimum beds/sleeps required.
- Results: a list of flats that are fully free for that entire date range and meet the bed requirement, each showing name, beds, and a one-click path to "generate quote."
- A flat is unavailable if any part of the requested range overlaps an existing booking, **plus** whatever turnover buffer applies around that booking (§3.10). Some units allow same-day turnover (guest checks out, next guest checks in, same day); others require a full linen/cleaning day free in between. This isn't a single yes/no setting for the whole business — it can vary **unit by unit, and even season by season for the same unit** (e.g. same-day turnover might be fine most of the year but a unit could require a buffer day in high season when cleaning capacity is tighter). The search must check both the booking itself and its buffer before calling a flat "available."
- Must also respect the unit's minimum-stay rule (§3.4) — e.g. a unit with a 2-night minimum shouldn't be offered as available for a 1-night request.

### 3.3 Season / rate calendar (editable)

- A calendar-style editor where low/medium/high season date ranges are defined per year (e.g. "1 Dec–15 Jan = High," "16 Jan–28 Feb = Medium," etc.).
- **One shared season calendar covers every unit** (confirmed) — no per-unit overrides needed. All 15+ flats read from the same set of season dates, which keeps setup and year-to-year updates simple.
- Must be easy to update year to year without technical help — a simple list of "start date, end date, season label" rows that can be added/edited/deleted.
- The same season calendar drives both the client-facing rate (§3.4) and the owner rate (§3.7) — one set of season dates, two rate tables hanging off it.

### 3.4 Rate file per unit (client-facing)

- Each flat has its own rate record: nightly rate for low season, medium season, high season (and room for a minimum-nights rule per season, e.g. "high season = 5-night minimum," if that's how they price today — confirm with parents).
- **Minimum stay:** each unit also has its own general minimum-nights setting, independent of season — confirmed as 2 nights for most units, with one unit allowing 1-night bookings. A season's own minimum-night rule (above) can raise the bar further for that period; see §3.5 for how the two combine on a stay that crosses seasons.
- Rates are versioned by year, so 2026 rates don't overwrite 2027 rates when it's time to update pricing.
- This is the rate charged **to the client**. It is distinct from the owner rate (§3.7), which is what's due back to the owner for the same nights.

### 3.5 Quote generation

- From either the calendar or the availability search, select a flat + date range + client details (name, contact info, number of guests).
- **A single requested stay can span any number of season changes, not just one.** A short weekend booking will usually sit entirely inside one season, but a longer stay — say two weeks over New Year — can start in medium season, cross into high season, and end back in medium season, all within one quote. The system must not assume a stay touches at most two seasons; it needs to walk the full date range night by night (or segment by segment) against the season calendar and handle as many season changes as actually fall within it.
- Calculation logic:
  1. Take the check-in and check-out dates for the requested stay.
  2. Walk through the shared season calendar (§3.3) and break the stay into consecutive segments everywhere the season label changes — one segment per unbroken run of nights in the same season. A stay could produce 1 segment (all one season) or several (e.g. medium → high → medium).
  3. For each segment, multiply its number of nights by that unit's client rate (§3.4) for that segment's season.
  4. Sum all segment subtotals into the quote total.
  5. Validate the requested stay length twice: first against the unit's general minimum-stay rule (§3.4) — e.g. a 2-night-minimum unit simply can't be quoted for 1 night — and then, if the season(s) touched carry their own minimum-night rule, against the higher of that unit minimum and the season minimum. **For a stay spanning more than one season, the minimum-night rule of the season with the highest rate among those touched is the one that governs** (confirmed) — e.g. a stay that dips from high season into medium season is still checked against high season's minimum-night rule, not medium's, since high season is the higher-rated of the two.
  - **Which segment a night belongs to:** a night is attributed to the season covering the date that night *starts* on — so the night of 10 Jan is a High-season night if 10 Jan falls in High season, even though the guest wakes up on the 11th. Check-out day is never charged.
  - Worked example: a stay of 1–20 January where 1–10 Jan is "High" and 11–20 Jan is "Medium" is 19 chargeable nights and produces two segments — **10 nights at the high rate** (nights of 1–10 Jan) and **9 nights at the medium rate** (nights of 11–19 Jan; the night of the 20th is the check-out day and isn't charged) — summed into one total.
- Output: a clean, shareable quote (PDF and/or a formatted message that can be copy-pasted into email/WhatsApp), including flat name, dates, nights, a line per season segment with its rate and subtotal, and the grand total — so the client can see exactly how the price was built up, not just a lump sum.
- Quotes are saved (see §3.6) so they can be reopened, resent, or converted into a confirmed booking later.
- **Follow-up flag:** a quote that's still sitting in "quoted" status (not yet accepted/converted to a booking, and not cancelled) 7 calendar days after it was generated is automatically flagged for follow-up — e.g. highlighted in the quote list — so an enquiry never silently goes cold. This is a reminder only; it doesn't expire, cancel, or delete the quote.
- The same season-segmenting logic (§3.5) is reused for the owner-side calculation in §3.8, just applied to the owner rate table instead of the client rate table — the two calculations only differ in which rate table they read from.

### 3.6 Booking & client records

- Client record: name, contact number/email, and a history of their enquiries/bookings (useful for repeat guests).
- Booking record: flat, dates, client, status (enquiry / quoted / confirmed / cancelled), total price, notes.
- A quote becomes a "confirmed booking" with one action once the client accepts — at that point it should occupy the calendar as booked and block that flat for those dates, and (per §3.9) trigger the relevant cleaning jobs.
- Basic list/search of past and upcoming bookings (by client name, by flat, or by date range) for reference.

### 3.7 Owner records & owner rate

- **Owner record:** name, contact details, banking details (kept for reference so the parents know where to pay — not used for any automated payment), notes.
- Each unit is linked to exactly one owner (confirmed — no joint ownership to design for).
- Each unit gets a second rate table alongside its client rate (§3.4): the **owner rate** — the nightly amount due to the owner for low/medium/high season, versioned by year in the same way. This is a separate figure the parents key in directly; it is not automatically derived as "client rate minus a percentage," since the earnings mechanism here is the flat monthly management fee (§3.8) rather than a per-night margin.

### 3.8 Management fee & owner invoicing (monthly statements)

- Each unit has a **management fee**: a flat monthly amount charged to that unit's owner for managing the property, independent of how many bookings occurred that month (confirmed as the standard arrangement — not a percentage of rental income or a per-booking fee). The amount itself is **individually negotiated per unit and/or per owner** rather than one fixed rate business-wide — so it's stored per unit (an owner with several units can have a different fee on each one if that's what was agreed) and simply edited whenever a fee is renegotiated, with no calculation tying it to anything else.
- Each cleaning job performed on a unit (§3.9) has a cost (§3.10), which is also billed through to the owner as a recoverable expense.
- Owners are invoiced via a **monthly statement**, one per owner (covering every unit that owner has, if more than one), generated for a given calendar month, listing:
  - **Rental income due to owner** — for each unit, the nights actually occupied that month, valued at the owner rate for whichever season each night falls in (same season-segmenting approach as §3.5, but reading the owner rate table instead of the client rate table).
  - **Less: management fee** — that unit's flat monthly fee.
  - **Less: cleaning costs** — every cleaning job completed on that unit during the month, itemized by date and clean type, at its cost (§3.10).
  - **= Net amount due to the owner** for that unit, and a grand total if the owner has multiple units.
- **No VAT/tax line** — statements show a simple net amount (confirmed), not a tax breakdown.
- The statement is a clean, shareable document (PDF), itemized per unit so an owner with several flats can see each one's income and deductions separately, then the total payable across all of them.
- Statements are saved and can be reopened/resent later, the same way quotes are (§3.5–3.6).
- Out of scope for this version unless the parents say otherwise: actually transferring the money to the owner (e.g. bank integration) — the statement tells the parents what's owed; the payment itself happens outside the app. **The app does track a "paid / not yet paid" status per statement (confirmed)**, so the parents can see at a glance which owners have already been settled for a given month, even though the transfer itself happens outside the app — see the Owner Statement entity in §6.

### 3.9 Cleaning calendar & staff scheduling

- A second calendar view, separate from the booking calendar (§3.1): cleaning staff down one axis, dates across the top (or units — whichever reads more clearly once there's real data to test with), so the parents can see at a glance who's cleaning which unit on which day.
- **Cleaning staff record:** name, contact number, notes, optionally which units they usually work.
- **Cleaning job:** a scheduled task — unit, date, clean type (§3.10), assigned staff member, status (scheduled / done / missed), and cost (feeds directly into the owner's monthly statement in §3.8).
- Jobs are normally created automatically from booking dates via the default rules in §3.10, but can always be added, moved, or reassigned manually when reality doesn't match the default (staff sick, guest changes dates, extra clean requested).

### 3.10 Cleaning service types & linking rules

- **Clean types:** changeover clean, post-clean, pre-clean, light clean, deep clean — each a distinct service with its own typical cost, and linked to booking dates and rules as follows (defaults, adjustable per unit):
  - **Changeover clean** — the standard same-day turnover job (confirmed as the common case, see below): one clean, scheduled that day, covering both the departing guest's clean and getting the unit ready for the arriving guest.
  - **Post-clean** — used when there's a genuine gap after checkout (i.e. a buffer of 1+ nights, or simply no new booking booked in yet) rather than an immediate same-day turnover.
  - **Pre-clean** — used the day before check-in when there's a buffer, so the unit gets a final check ahead of the guest's arrival rather than being cleaned same-day.
  - **Light clean** — scheduled automatically partway through any stay longer than a configurable threshold (e.g. a mid-stay tidy every 7 nights for stays over 10 nights), without a full changeover.
  - **Deep clean** — scheduled on a periodic basis independent of specific bookings (e.g. quarterly, or after every N changeover cleans), to cover things a standard clean doesn't (windows, appliances, etc.) — cadence configurable per unit.
- **Same-day turnover is the standard case, not an edge case (confirmed):** especially in high season, the normal pattern is guest A checks out in the morning, the flat is cleaned around midday, and guest B checks in that afternoon — all in one day. So a buffer of **0 nights** is the expected default for most units and most of the year, and the system should be built around that as the common path, with a full buffer day (1+ nights free between bookings) as the exception for whichever specific units genuinely need it.
- **Same-day turnover window:** to make that midday clean schedulable, each unit has a standard checkout time (e.g. 10:00) and check-in time (e.g. 14:00) — a business-wide default that can be overridden per unit if a specific flat runs different times. This gives the cleaning calendar a concrete window (checkout time → check-in time) to slot the changeover clean into on a same-day turnover, and lets the parents see at a glance whether that window is realistically enough time for a given unit.
- **Turnover buffer, and how it drives which clean gets scheduled:** each unit (and optionally each unit+season combination) has a turnover rule (§3.2, §6) stating how many buffer nights, if any, must sit free between one guest's checkout and the next guest's check-in — defaulting to **0 nights (same-day)** per the above, since that's the confirmed norm.
  - Buffer **0** → a single **changeover clean** is scheduled that day, in the checkout-to-check-in window.
  - Buffer **1 or more nights** → the unit isn't being turned around same-day, so the ordinary **post-clean** (right after checkout) and **pre-clean** (ahead of the next check-in) apply instead, with a full day or more to spare in between. Specific units/seasons get flagged for this longer buffer where the same-day window genuinely isn't enough time (e.g. a larger unit that takes longer to clean than the standard window allows).
  - Either way, those buffer nights (when present) must show as unavailable on the booking calendar (§3.1) and availability search (§3.2), not just as a gap between two bookings.
  - Because the buffer can differ by season for the same unit, the cleaning-job rules read the same per-unit/per-season Turnover Rule that the availability search uses, so the two always stay consistent — a unit's buffer rule is defined once and drives both where it can be booked and when it gets cleaned.
- **Cost per clean type:** each service type (changeover clean, post-clean, pre-clean, light clean, deep clean) has one standard cost that applies across all units by default (§6, Cleaning Service Type). In some cases, though, a specific unit's cleaning cost is separately negotiated with that owner and needs to override the standard rate for that unit only — the cost lookup should check for a per-unit override first and fall back to the standard rate when none exists, so most units need no extra setup while the exceptions are still handled cleanly. This feeds directly into the owner invoice calculation in §3.8.

## 4. Non-functional requirements

- **Usability first:** parents are not technical power-users. Every screen should be understandable without training — big clear buttons, minimal jargon, sensible defaults.
- **Shared, always-current data:** both laptops must see the same live calendar — if one parent books a flat, the other must see it as unavailable immediately, not after a manual file sync. Neither laptop should need to be switched on for the other to work — this rules out any "one laptop hosts it for the other" arrangement and is the main constraint driving the technical design in §5.
- **Growth-ready:** the data model and calendar UI should comfortably handle 30+ units, their owners, and a growing cleaning-staff roster without redesign.
- **Clear separation of client-facing and owner-facing money:** client rates, owner rates, management fees, and cleaning costs are distinct figures that must never be confused with one another on-screen or in any generated document.
- **Backups:** booking, rate, owner, and invoice data must be backed up automatically — this is the business's core operational and financial record.
- **Low ongoing effort:** prefer free or near-free hosting tiers and minimal maintenance, since there's no in-house IT support.

## 5. Recommended technical approach

### Why plain "local file" storage doesn't fit

A local SQLite file or spreadsheet on one laptop can't be seen live by the other laptop unless they're constantly copied back and forth — which quickly causes version conflicts (e.g. both parents book different flats at the same time, and one set of changes gets overwritten). Since the explicit requirement is two laptops seeing the same live data, the data needs to live somewhere both machines can reach over the network, not on either laptop's local disk.

### Recommended setup (confirmed: Streamlit + Neon)

- **App type:** [Streamlit](https://streamlit.io) — a Python web app framework well suited to an internal tool like this: a single Python codebase renders the calendar, forms, and PDFs, with no separate frontend/backend split to maintain. Good fit for a two-person team iterating on it themselves in VS Code.
- **Database:** [Neon](https://neon.tech) — a hosted Postgres database (free tier is enough at this scale). Both laptops' browsers talk to the same Streamlit app, which talks to the same Neon database, so a booking made on one laptop appears instantly on the other with no manual syncing, and it works just as well if one parent is travelling (not just on the same home Wi-Fi).
- **Hosting:** [Streamlit Community Cloud](https://streamlit.io/cloud) (free tier) is the simplest way to get the app onto a shared web address both laptops can open in a browser, deployed straight from the project's Git repository with no separate server to manage. One thing worth knowing: a free Community Cloud app can go to sleep after a period of no visits and take a few seconds to "wake up" on the next visit — a minor inconvenience for two internal users, not a blocker, but worth flagging in case it's ever annoying enough to justify a small paid always-on host later.
- **Authentication:** Streamlit supports a simple password/login gate (e.g. the `streamlit-authenticator` package, or Community Cloud's built-in access restriction to specific email addresses) — enough to keep the calendar and owner/financial data private without building a full user-management system.

This keeps monthly cost near zero at this scale (15 units, 2 users) and avoids the parents needing to manage a server themselves.

Neither laptop needs to be switched on, awake, or even in the house for the other to use the app. Both are simply browser clients pointed at the same hosted address; the database and the app both live in the cloud host's data centre, running independently of whether any particular laptop is on. This rules out the "one laptop acts as the server for the other" pattern entirely — that approach was considered and dropped specifically because it would require a designated laptop to stay on and connected, which isn't workable for this household. A cloud-hosted setup, not a home-network one, is the only option carried forward in this spec.

## 6. Data model (entities)

- **Unit (Flat):** id, name, beds/sleeps count, owner id, monthly management fee, general minimum-stay nights (default 2, override to 1 where allowed), standard checkout time and check-in time (override of the business-wide default, e.g. 10:00/14:00), notes, active/inactive flag.
- **Owner:** id, name, contact details, banking details (reference only), notes.
- **Season Definition:** id, label (Low/Medium/High), start date, end date, year — one shared calendar, no per-unit override.
- **Client Rate:** unit id, season label, year, nightly rate (charged to guest), minimum nights (optional).
- **Owner Rate:** unit id, season label, year, nightly rate (due to owner) — same shape as Client Rate, kept as a separate table since the two figures are set independently.
- **Client:** id, name, phone, email, notes.
- **Booking:** id, unit id, client id, check-in date, check-out date, status (enquiry/quoted/confirmed/cancelled), total price, created date, notes.
- **Quote:** id, booking id (or standalone), generated PDF/reference, date generated, breakdown of segments and totals, status (quoted/accepted/cancelled), follow-up-flagged (derived: true once 7 days have passed since generation while still status = quoted).
- **Turnover Rule:** unit id, season label (optional — blank/"all seasons" means it's the unit's default), buffer nights required between a checkout and the next check-in (0 = same-day turnover allowed — the confirmed default — 1+ = that many full nights must be free in between). Read by both the availability search (§3.2) and the cleaning-job rules (§3.10), so a unit's turnover policy is defined once and applied consistently everywhere.
- **Cleaning Staff:** id, name, contact number, notes.
- **Cleaning Service Type:** id, label (changeover clean/post-clean/pre-clean/light clean/deep clean), standard cost, default duration.
- **Unit Cleaning Rate (override):** unit id, service type, negotiated cost — only present for the specific units/owners where a clean type's price was negotiated away from the standard rate; the cost lookup falls back to Cleaning Service Type's standard cost when no override row exists for that unit + service type.
- **Cleaning Rule:** unit id (or "default" for the global rule), service type, trigger (on checkout / before next checkin / stay-length interval / periodic), parameters (e.g. night threshold, interval length, cadence — including the deep-clean cadence, which is customizable per unit rather than fixed business-wide, confirmed).
- **Cleaning Job:** id, unit id, date, service type id, assigned staff id, linked booking id (optional, e.g. blank for a periodic deep clean not tied to a specific stay), status (scheduled/done/missed), cost.
- **Owner Statement (Invoice):** id, owner id, period (month/year), total rental income, total management fees, total cleaning costs, net amount due, status (draft/sent/paid), generated date, date marked paid (blank until settled).
- **Owner Statement Line Item:** statement id, unit id, type (rental income / management fee / cleaning cost), description, amount.

Note on turnover rules: same-day turnover — guest A out in the morning, a changeover clean around midday, guest B in that afternoon — is confirmed as the standard pattern, especially in high season, so it's the default (buffer = 0) rather than an exception. It can still vary by unit, and by season within the same unit, for the specific units where a full buffer day is genuinely needed (e.g. a unit too big to clean within the standard checkout-to-check-in window). The Turnover Rule entity above models this per unit (and optionally per unit+season), defaulting to 0 unless told otherwise. See §8 for what's still needed to finish setting this up.

## 7. Suggested project structure (for building in VS Code)

```
rentalman/
├── app.py                      # Streamlit entry point / landing page
├── pages/                      # One file per screen — Streamlit turns these into the app's navigation automatically
│   ├── 1_Calendar.py            # Booking grid calendar view
│   ├── 2_Search.py              # Availability search
│   ├── 3_Units.py               # Manage flats, client rates, owner rates, management fee
│   ├── 4_Seasons.py             # Editable season calendar
│   ├── 5_Quotes.py              # Quote builder + history
│   ├── 6_Clients.py             # Client records
│   ├── 7_Owners.py              # Owner records
│   ├── 8_Invoices.py            # Monthly owner statements
│   └── 9_Cleaning.py            # Cleaning calendar, staff, service types, rules
├── lib/                         # Shared logic: rate calculation, availability checks, season-segmenting, invoice calculation, cleaning-rule engine
├── db/                          # Database connection helper + schema/migrations against Neon
├── requirements.txt              # streamlit, psycopg2 (or SQLAlchemy), reportlab/weasyprint (PDF), etc.
└── .streamlit/
    └── secrets.toml              # Neon connection string + auth config (kept out of Git)
```

## 8. Open item for Jaydie's parents

Only one item is still open — everything else has been decided (§1–§7 reflect all confirmed answers: one shared season calendar, one owner per unit, negotiated management fees and cleaning costs, per-unit deep-clean cadence, net-amount-only statements, and paid-status tracking).

**Same-day turnover is now confirmed as the default** — guest A checks out in the morning, the flat gets a changeover clean around midday, guest B checks in that afternoon — so every unit is assumed to work this way (buffer = 0 nights) unless flagged otherwise.

**What's still needed:** are there any of the 15 flats where that midday window genuinely isn't enough time — e.g. a bigger unit that takes longer to clean than the standard checkout-to-check-in gap allows — and if so, which ones, and does it apply year-round or only in high season when the cleaning team is busiest across all the units at once? If none come to mind right now, "same-day for all of them, we'll flag exceptions if they come up" is a perfectly fine starting point — this is a data question that can be settled during setup, not something that needs to hold up the build.

## 9. Suggested build phases

1. **Phase 1 — Core data & calendar:** unit records (incl. owner link), season calendar, client rate files, read-only booking grid.
2. **Phase 2 — Search & quoting:** availability search, quote generation (PDF/shareable), quote history.
3. **Phase 3 — Booking lifecycle:** convert quote → confirmed booking, client records, booking status list/search.
4. **Phase 4 — Cleaning calendar:** cleaning staff records, service types, default linking rules, cleaning calendar view, manual job adjustment.
5. **Phase 5 — Owner accounting:** owner records, owner rate tables, management fee setup, monthly owner statements pulling together rental income, management fee, and cleaning costs, and per-statement paid / not-yet-paid status (§3.8 — in scope for this version).
6. **Phase 6 (later, optional):** sync with external booking platforms (Airbnb/Booking.com) to prevent double-bookings if they start listing there; guest communication templates; basic reporting (occupancy %, revenue per unit/owner per season); a full owner payment history / audit trail beyond the single paid-status flag delivered in Phase 5.
