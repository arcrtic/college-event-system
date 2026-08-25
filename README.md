# College Event Resource Allocation System (CERAS)

A Flask web app for booking shared college resources (auditoriums, labs,
projectors, mics, cameras, computers) for events — with double-booking
prevention, suitability checks, alternative-resource suggestions, and an
approve → allocate workflow.

---

## 1. How to install and run

**Requirements:** Python 3.10+

```bash
# 1. Unzip and enter the project
cd college-event-system

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up your environment file (defaults work fine locally)
cp .env.example .env            # Windows: copy .env.example .env

# 5. Run it
python run.py
```

Open **http://127.0.0.1:5000** in your browser.

**Suggested first walkthrough:**
1. **Resources** → add a couple of resources (e.g. an Auditorium with a
   capacity, a Projector, a Microphone with "Total units" set to 2+).
2. **Events** → create an event.
3. On the event's page, click **Request Resources**, pick a time window
   and add resources to the request.
4. **Approvals** → Approve the request, then Allocate it.
5. Try requesting the same resource again for an overlapping time window
   to see the double-booking rejection and alternative suggestions.
6. Check **Availability** to see live free/booked units per resource for
   any time window you enter.

---

## 2. Database setup

No separate migration tool or step is used. `db.create_all()` runs
automatically inside the app factory (`app/__init__.py`) every time the
app starts, so all 5 tables are created on first run if they don't
already exist. The database is SQLite, stored at
`instance/college_events.db` (created automatically; git-ignored).

**To reset all data:** stop the app, delete `instance/college_events.db`,
and restart — it will be recreated empty.

There is no seed/sample-data script; the walkthrough above is the fastest
way to populate it manually through the UI.

---

## 3. How conflict detection (double-booking prevention) works

All of it lives in `app/utils/booking.py`, used identically at request
creation and at allocation time:

1. **`overlaps(start_a, end_a, start_b, end_b)`** — two time windows
   conflict only if each starts before the other ends
   (`start_a < end_b and start_b < end_a`). This is a **strict**
   inequality, so a booking ending at 2:00 PM and another starting at
   2:00 PM do **not** overlap — back-to-back bookings are allowed, matching
   the assignment's own worked example.
2. **`booked_quantity(resource_id, start, end)`** — walks every **active**
   `Allocation` row for that resource, sums the `quantity` of any whose
   window overlaps the requested one, and returns the total already
   committed. Only active allocations count — a cancelled one is ignored,
   which is what makes cancellation immediately free up the resource.
3. **`check_availability(...)`** — compares `resource.total_quantity -
   booked_quantity(...)` against the quantity being requested. If there
   isn't enough left, it returns a specific reason (e.g. *"Hall A has only
   1 of 1 unit(s) free for that time window"*).

**Why it only checks `Allocation`, not other `ResourceRequest` rows:**
Pending or Rejected requests never block a resource — only requests that
have actually been **allocated** create rows in the `Allocation` table,
so that's the only table this logic ever needs to look at. This also
means the check is naturally re-runnable: it's called once when an
organizer submits a request (fast feedback), and again — against
whatever the database looks like *then* — at the moment an admin clicks
**Allocate**, inside a single DB transaction (`app/routes/approvals.py:
allocate_request`). If any one resource in a multi-resource request fails
that second check, the whole transaction is rolled back and **nothing**
is allocated — this is the "all-or-nothing" requirement.

---

## 4. How alternative resources are selected

Also in `app/utils/booking.py`, function `find_alternatives(...)`. When a
requested resource fails suitability or availability, the system looks at
every other resource and keeps only the ones that are:

1. **The same resource type** (a Projector is never suggested in place of
   an Auditorium).
2. **Active.**
3. **Big enough**, if the resource has a capacity concept — its capacity
   must be ≥ the event's expected attendance. (Resources with no capacity
   concept, like a microphone, always pass this check.)
4. **Actually free** for that exact requested quantity during that exact
   time window (same `check_availability` logic as above).

Survivors are then sorted by **smallest capacity that still fits** (ties
broken alphabetically by name), so the system doesn't suggest a 1000-seat
hall for a 50-person workshop when a 100-seat room is free — it offers
the closest reasonable fit first. Up to 3 suggestions are shown.

---

## 5. Important assumptions

- **"Quantity" of a resource means identical physical units under one
  catalog entry**, not separate rows — e.g. one "Wireless Mic Set" record
  with `total_quantity = 3` represents 3 physical microphones, so a
  request for "2 Microphones" is satisfied by requesting quantity 2 of
  that one resource. This is distinct from `capacity`, which is audience
  size and only meaningful for venues (Auditorium, Lab).
- **Approve and Allocate are deliberately two separate actions**, not one
  button. Approving is a human sign-off; allocating is the actual
  transactional lock-in step, re-checked against live data. This means a
  request can be "Approved" but not yet "Allocated" if a conflict shows up
  at allocation time — it isn't auto-rejected, an admin can retry once
  the conflict clears or cancel it manually.
- **Suitability is validated at request-creation time**, not deferred
  to approval — an organizer sees every problem with their request (plus
  alternatives) immediately, and nothing is saved until every item in the
  request passes. Availability is then re-verified a second time at
  allocation, since time may have passed.
- **Cancelling a request that has an active allocation releases the
  resource immediately** (the `Allocation` row is deactivated, not
  deleted, so history is preserved).
- **No authentication/roles** are implemented — anyone can act as
  "organizer" or "admin". This wasn't in scope for a basic-UI
  functionality assignment, but would be the first thing added for
  real-world use.
- **Cancelling an event cascades to its resource requests.** If an event
  is cancelled directly (not via a request-level cancel in Approvals),
  any of its requests that are still Pending, Approved, or Allocated are
  cancelled too, and any Allocation rows they held are deactivated --
  otherwise a directly-cancelled event could leave resources permanently
  locked with no way to free them.
- **No hosted deployment link is embedded in this submission** — the app
  is deployment-ready (see §6) but was not deployed to a live URL for
  this handoff.

---

## 6. Hosted web application

The app is deployment-ready via `gunicorn` (in `requirements.txt`) and a
`Procfile`, so it can be one-click deployed to Render, Railway, or any
similar platform:

1. Push this repo to GitHub.
2. Create a new **Web Service** on Render (or Railway) pointing at the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn run:app --bind 0.0.0.0:$PORT` (already in the
   `Procfile`, so most platforms detect it automatically).
5. Set environment variables `SECRET_KEY` (a random string) and, optionally,
   `DATABASE_URL` if you want a managed Postgres/other DB instead of the
   default SQLite file. `FLASK_DEBUG` should be left unset or `0` in
   production.
6. Deploy — `db.create_all()` runs automatically on first boot, so no
   separate migration step is needed.

*Hosted link: add here once deployed —* `https://<your-app>.onrender.com`

---

## 7. Project structure and what each file does

```
college-event-system/
├── run.py                     # Entry point — run this to start the server
├── config.py                  # Reads settings from .env (secret key, DB path)
├── requirements.txt           # Python dependencies
├── .env / .env.example        # Environment variables (SECRET_KEY, DATABASE_URL, FLASK_DEBUG)
├── .gitignore
├── instance/                  # SQLite database file lives here (auto-created, git-ignored)
└── app/
    ├── __init__.py             # App factory: wires config + DB + blueprints together
    ├── extensions.py           # The shared `db` (SQLAlchemy) object
    ├── models/
    │   ├── __init__.py         # Re-exports models for cleaner imports elsewhere
    │   └── models.py           # All database tables (Event, Resource, ResourceRequest,
    │                           # RequestItem, Allocation) + their status enums
    ├── routes/                 # One blueprint per feature area
    │   ├── dashboard.py        # "/" — landing page with quick stats
    │   ├── events.py           # "/events/*" — event CRUD, filtering, cancel
    │   ├── resources.py        # "/resources/*" — resource CRUD, activate/deactivate, availability
    │   ├── requests.py         # "/requests/*" — submit a resource request (the booking form)
    │   └── approvals.py        # "/approvals/*" — approve / reject / allocate / cancel
    ├── utils/
    │   ├── validators.py       # Shared input validation (dates, attendance, required fields)
    │   └── booking.py          # THE CORE LOGIC: conflict detection, suitability checks,
    │                           # alternative-resource suggestions
    ├── templates/               # Jinja2 HTML templates (Tailwind CSS via CDN)
    │   ├── base.html            # Shared layout: nav bar, flash messages
    │   ├── dashboard.html
    │   ├── placeholder.html
    │   ├── errors/404.html, errors/500.html
    │   ├── events/list.html, form.html, view.html
    │   ├── resources/list.html, form.html, availability.html
    │   ├── requests/list.html, form.html, view.html
    │   └── approvals/list.html
    └── static/                 # (reserved for any custom CSS/JS/images — currently empty)
```

### File-by-file details

| File | Purpose |
|---|---|
| **`run.py`** | Creates the Flask app via the factory and starts the dev server. |
| **`config.py`** | Central config class. Reads `SECRET_KEY`, `DATABASE_URL`, `FLASK_DEBUG` from `.env` so the same code works locally or deployed without edits. |
| **`app/__init__.py`** | The **app factory** (`create_app()`). Registers the database, imports models (so SQLAlchemy knows about their tables), registers all 5 blueprints, and sets up 404/500 error handlers so users never see a raw Python traceback. |
| **`app/extensions.py`** | Declares the `db = SQLAlchemy()` object on its own, separate from the app factory, to avoid circular imports between models and routes. |
| **`app/models/models.py`** | The data model. See section 8 below for the full schema explanation. |
| **`app/routes/events.py`** | Create/edit/view/list/cancel events. Validates name, organizer, attendance (must be positive), and that the end time is after the start time. Filtering by status and date on the list page. |
| **`app/routes/resources.py`** | Create/edit/list resources, toggle active/inactive, and the availability checker. Deactivating a resource only blocks it from *new* requests — it doesn't touch resources already allocated to upcoming events. |
| **`app/routes/requests.py`** | The booking form. Lets an organizer pick a time window and add multiple resource line-items (with quantities) to one request. Every item is validated for suitability and availability *before* anything is saved — if one item fails, nothing is created (all-or-nothing). |
| **`app/routes/approvals.py`** | The admin workflow: **Approve** (Pending → Approved, just a sign-off), **Allocate** (Approved → Allocated — re-checks availability for every item inside one transaction and only then creates the actual `Allocation` rows), **Reject**, and **Cancel** (releases any allocated resources back to the pool). |
| **`app/routes/dashboard.py`** | Simple landing page: count of pending requests, next 5 upcoming events. |
| **`app/utils/validators.py`** | Shared validation helpers (`parse_datetime`, `validate_event_window`, `validate_attendance`, `require_text`) and a custom `ValidationError` exception that route handlers catch to show a clean flash message instead of crashing. |
| **`app/utils/booking.py`** | **The heart of the system.** Contains: `overlaps()` (time-window overlap check), `booked_quantity()` (sums units of a resource already booked in a given window, counting only active allocations), `check_suitability()` (type match, active check, capacity vs. expected attendance), `check_availability()` (enough free units?), and `find_alternatives()` (suggests other suitable, available resources when the requested one doesn't work). |
| **`app/templates/base.html`** | Shared page shell — nav bar links to every section, and renders flash messages (success/error banners) consistently everywhere. |
| **`app/templates/errors/*.html`** | Friendly error pages instead of stack traces. |

---

## 8. Data model (how the tables relate)

```
Event ──< ResourceRequest ──< RequestItem >── Resource
                                   │
                                   │ (on approval + allocation)
                                   ▼
                              Allocation ── (also references Event, Resource)
```

- **`Event`** — the event itself (name, organizer, attendance, time window, status).
- **`Resource`** — a bookable item (name, type, optional capacity, `total_quantity`
  = how many identical physical units exist — e.g. "Wireless Mic Set" might
  have 3 units under one resource record — and an active/inactive flag).
- **`ResourceRequest`** — one booking "ask": for a given event, during a given
  time window, give me these resources. Goes through
  `Pending → Approved → Allocated`, or `Pending → Rejected`, or
  `Approved/Allocated → Cancelled`.
- **`RequestItem`** — one resource line within a request (e.g. "2x Wireless
  Mic Set"). A request can have several.
- **`Allocation`** — created only once a request is actually **allocated**.
  This is the only table conflict-checking queries against, which is what
  lets pending/rejected requests never block real bookings. Cancelling an
  allocation just flips `is_active` to `False`, instantly freeing those
  units for other requests — history is kept, not deleted.

