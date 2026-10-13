# CampusAlloc — College Event Resource Allocation System

CampusAlloc is an enterprise-grade web application built with **Flask**, **SQLAlchemy**, **SQLite** (local) / **PostgreSQL on Neon** (production), and **Tailwind CSS** that enables colleges and universities to manage campus events and shared physical resources (auditoriums, seminar halls, computer/electronics laboratories, projectors, microphones, cameras, and computing equipment fleets).

The system emphasizes robust backend validation, mathematical interval conflict detection, atomic all-or-nothing database transactions, and an intelligent best-fit alternative resource recommendation engine.

---

## 🚀 Live Demo

**Hosted application:** [https://college-event-system-sz4a.onrender.com](https://college-event-system-sz4a.onrender.com)

> Hosted on Render's free tier — the instance spins down after inactivity, so the first request after a period of idleness may take 30–60 seconds to wake up.

---

## 🌟 Key Features

### 1. Event Management Lifecycle
- **Complete CRUD**: Create, view, edit, and cancel events.
- **Strict Validation**: Enforces valid date/time intervals ($T_{\text{start}} < T_{\text{end}}$), non-negative and non-zero expected attendance ($A > 0$), and prevents scheduling past start dates.
- **Lifecycle Statuses**: `Draft` → `Pending` → `Approved` → `Completed` (with `Rejected` and `Cancelled` terminal states).
- **Filtering & Search**: Live keyword search by event name or organizer, filter by status, and filter by specific calendar dates.
- **Cascading Release**: Cancelling an event automatically cascades cancellation to all associated pending/approved requests and deactivates active allocations, freeing locked resources immediately.

### 2. Resource Management & Fleet Inventory
- **Diverse Catalog**: Auditoriums, Laboratories, Projectors, Wireless & Collar Microphones, DSLR/Video Cameras, and Laptop/Workstation Fleets.
- **Capacity vs. Multi-Unit Pool Distinction**:
  - **Venues** (*Auditoriums, Labs*): Constrained by **audience seating capacity** (e.g. 500 seats) with `total_quantity=1`.
  - **Audiovisual/Computing Fleets** (*Microphones, Projectors, Laptops*): Constrained by **physical unit counts** (e.g., 6 wireless microphones) allowing multi-unit requests (`quantity=2`).
- **Administrative Control**: Add new resources, edit properties, and toggle active/inactive status. Inactive resources are strictly excluded from allocation.

### 3. Real-Time Resource Availability Checker
- Interactive search by single calendar day (00:00 to 23:59) or exact start/end datetime window.
- Visual unit counter cards displaying real-time free units (`X / Total Units`), color-coded availability badges (`Available`, `Partially Booked`, `Fully Booked`), and an inspection list of current active bookings for that window.

### 4. Multi-Resource Request Builder
- Step-by-step wizard to request multiple resource types and quantities within an event's time window.
- Asynchronous resource filtering (`/resources/available.json`) that pre-evaluates real-time availability and attendance suitability.

### 5. Double Booking Conflict Prevention
- Real-time backend interval overlap validation ensuring no physical resource is over-allocated across overlapping time windows.
- Back-to-back booking support: 10:00 AM – 2:00 PM followed by 2:00 PM – 4:00 PM is **allowed**; 10:00 AM – 2:00 PM and 12:00 PM – 4:00 PM is **rejected**.

### 6. Resource Suitability & Alternative Suggestions Engine
- Enforces category type matching and capacity sufficiency ($C_{\text{resource}} \ge A_{\text{event}}$).
- When a requested resource is unavailable or unsuitable, automatically identifies active, compatible resources of the same type that fit the attendance requirement and are available during the exact window, ordered by **best-fit capacity** (smallest suitable capacity first to minimize resource waste).

### 7. All-or-Nothing Transactional Approval Workflow
- 3-Stage Administrative Decision Center:
  1. **Pending Review**: Sign-off decision (`Approve` or `Reject`).
  2. **Approved (Awaiting Allocation)**: Atomic allocation step (`Allocate` or `Cancel`).
  3. **Active Allocations**: Live locked resources with instant release option.
- **Transactional Atomicity Guarantee**: If an event requests multiple resources (e.g. Auditorium + Projector + 2 Microphones) and even one resource is unavailable, zero resources are locked in. The entire transaction rolls back cleanly (SQLite locally, PostgreSQL in production).

### 8. Role-Based Access & Demo Accounts
- Built-in roles for **Admin** and **Organizer** with 1-click Quick Demo Sign-In buttons:
  - **Admin**: `admin` / `admin123` (manage resources, approve/reject/allocate requests, mark events completed).
  - **Organizer**: `organizer` / `org123` (create/edit events, submit resource requests, cancel own events).

---

## 🛠️ Technology Stack

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Backend Framework** | Python 3.10+, Flask 3.0.3 | Route handling, request lifecycle, application factory pattern |
| **ORM & Database** | SQLAlchemy 2.0+, Flask-SQLAlchemy 3.1.1, SQLite (local default), PostgreSQL via Neon (production, set through `DATABASE_URL`) | Relational schema, transactions, migrations, integrity constraints |
| **Templating** | Jinja2 | Dynamic HTML rendering with reusable base layout |
| **Styling & UI** | Tailwind CSS (CDN), Custom Royal Indigo Theme | Responsive, modern campus UI (cards, badges, modals, timelines) |
| **Typography** | Google Fonts (*Plus Jakarta Sans*, *Inter*) | Clean, readable hierarchy |
| **Frontend Scripting**| Vanilla JavaScript (ES6+ Fetch API) | Dynamic resource row addition, asynchronous availability querying |

---

## 🚀 Installation & Local Setup

### Prerequisites
- Python 3.10 or higher installed ([python.org](https://www.python.org/))
- Git installed

### Step-by-Step Instructions

1. **Clone the Repository**:
   ```bash
   git clone <repository-url>
   cd college-event-system
   ```

2. **Create and Activate a Virtual Environment**:
   ```bash
   # Windows (PowerShell)
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # macOS / Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Copy the example environment configuration:
   ```bash
   # Windows (PowerShell)
   Copy-Item .env.example .env

   # macOS / Linux
   cp .env.example .env
   ```
   *(The default `.env` leaves `DATABASE_URL` unset, which is intentional — `config.py` then
   uses a safe, absolute SQLite path inside `instance/` that works regardless of your OS or
   the folder you happen to run commands from. You don't need to edit anything to run locally.)*

5. **Start the Flask Development Server**:
   ```bash
   python run.py
   ```
   The database is created and seeded automatically on first startup (a background thread in
   `app/__init__.py` runs `seed.py`'s logic once, and skips it on every future run since the
   data already exists). Open your browser and navigate to: **`http://127.0.0.1:5000`**

   If you'd rather seed explicitly and see the seeding output directly instead of in a
   background thread, you can run `python seed.py` before `python run.py` — it's optional,
   not required.

---

## 🧪 Running Automated Tests

A comprehensive unit and integration test suite is included in `tests/test_system.py`, testing event validation, double-booking prevention, suitability matching, alternative resource suggestions, cascading cancellations, and all-or-nothing transactional rollbacks.

To run the test suite:
```bash
python -m unittest tests/test_system.py
```

---

## 📐 How Conflict Detection Works

Conflict detection is implemented on the backend in [`app/utils/booking.py`](file:///d:/college-event-system/app/utils/booking.py) using mathematical interval overlap checks over the operational `allocations` table.

### 1. Mathematical Interval Overlap Definition
Two time intervals $[S_A, E_A)$ and $[S_B, E_B)$ overlap if and only if:
$$\text{Overlap} \iff S_A < E_B \quad \text{and} \quad S_B < E_A$$

Using strict inequality (`<` instead of `<=`) ensures that **back-to-back bookings are allowed**:
- **Existing Allocation**: 10:00 AM – 2:00 PM ($S_A = 10, E_A = 14$)
- **New Request A (Overlap)**: 12:00 PM – 4:00 PM ($S_B = 12, E_B = 16$) $\implies 10 < 16$ and $12 < 14$ (**True $\rightarrow$ Conflict Detected / Rejected**)
- **New Request B (Back-to-Back)**: 2:00 PM – 4:00 PM ($S_B = 14, E_B = 16$) $\implies 10 < 16$ is True, but $14 < 14$ is **False** (**No Conflict $\rightarrow$ Allowed**)

### 2. Multi-Unit Capacity Tracking
For physical resources with multiple units (e.g. 5 wireless microphones):
1. Query all active allocations (`is_active = True`) for the resource that overlap with the requested window $[S_{\text{req}}, E_{\text{req}})$.
2. Calculate:
   $$\text{Booked Units} = \sum_{\text{overlapping allocs}} Q_{\text{alloc}}$$
   $$\text{Remaining Free Units} = Q_{\text{total}} - \text{Booked Units}$$
3. If $Q_{\text{requested}} > \text{Remaining Free Units}$, the request is rejected with a clear message indicating exact free units vs. requested quantity.

---

## 🔍 How Alternative Resources Are Selected

When a resource is unavailable (fully booked or insufficient units) or unsuitable (capacity smaller than attendance or category type mismatch), the alternative selection engine (`find_alternatives`) executes the following algorithm:

1. **Category Matching**: Filters candidate resources where `Resource.type == requested_type`.
2. **Active Status**: Excludes deactivated resources (`Resource.is_active == True`).
3. **Exclusion**: Excludes the originally requested resource ID.
4. **Attendance Capacity Check**: If the candidate resource has an audience capacity $C$, ensures $C \ge A_{\text{event}}$.
5. **Window Availability Check**: Verifies that the candidate resource has at least $Q_{\text{requested}}$ free units during $[S_{\text{req}}, E_{\text{req}})$.
6. **Best-Fit Ranking (Waste Minimization)**:
   - Candidates are sorted in ascending order of seating capacity:
     $$\text{Sort Key} = (\text{capacity if not None else } 0, \text{name})$$
   - *Rationale*: If an event has 180 attendees, a 200-seat hall is suggested before a 500-seat auditorium, preventing larger venues from being monopolized unnecessarily.
7. **Return Limit**: Returns the top matching alternative recommendations to the user interface.

---

## 🏛️ Architectural Design Decisions & Assumptions

1. **Separation of Requests (`ResourceRequest`) and Commitments (`Allocation`)**:
   - `ResourceRequest` represents the organizer's proposed wish list.
   - `Allocation` is created exclusively when an administrator approves and allocates the request. Double-booking conflict checks query the `allocations` table directly, ensuring high performance without complicated status filtering.
2. **Atomic All-or-Nothing Database Transactions**:
   - In accordance with assignment requirements, if an event requests 3 resources and only 2 are available, **zero resources are allocated**. Availability is verified for all items before any `Allocation` row is committed.
3. **Soft Cancellation & Auditability**:
   - Rather than hard-deleting records, events, requests, and allocations are transitioned to `Cancelled` with allocations set to `is_active = False`. This retains complete audit history while instantly releasing inventory for other organizers.
4. **Timezone Assumption**:
   - All event datetimes are normalized and compared in local campus time.

---

## 👥 Demo User Accounts

| Role | Username | Password | Permissions |
| :--- | :--- | :--- | :--- |
| **Administrator** | `admin` | `admin123` | Full access: Add/Edit/Toggle resources, Approve/Reject requests, Allocate resources, Mark events completed |
| **Organizer** | `organizer` | `org123` | Event creation, edit draft events, submit resource requests, check availability, cancel own events |

---

## 🔄 CI/CD Pipeline

Defined in [`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml) (GitHub Actions → Render).

| Stage | Runs when | What it does |
| :--- | :--- | :--- |
| **Test** | Every push / PR to `main` | Installs deps, syntax-checks, runs the unit tests on Python 3.10 and 3.11 |
| **Deploy** | Push to `main`, only if **Test** passes | Calls the Render Deploy Hook, which rebuilds the production site |

**Docs-only changes never reach production.** Commits that only touch `*.md` files (e.g. `README.md`),
`docs/`, `LICENSE` or `.gitignore` are excluded via `paths-ignore`, so neither tests nor a deploy run.
`render.yaml` also sets `autoDeploy: false`, so Render itself never deploys on a plain push.

### One-time setup
1. Render dashboard → your service → **Settings** → **Build & Deploy** → set **Auto-Deploy** to **Off**
   (needed if the service was created manually rather than from the blueprint).
2. In the same page, copy the **Deploy Hook** URL.
3. GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:
   name `RENDER_DEPLOY_HOOK_URL`, value = the hook URL.

Run the tests locally with: `python -m unittest discover -s tests -t . -v`

---


## 📁 Repository Structure

```
college-event-system/
├── app/
│   ├── __init__.py           # Application factory and error handlers
│   ├── extensions.py         # SQLAlchemy database instance
│   ├── models/
│   │   ├── __init__.py
│   │   └── models.py         # Event, Resource, ResourceRequest, RequestItem, Allocation
│   ├── routes/
│   │   ├── dashboard.py      # Operational metrics, upcoming events, status overview
│   │   ├── events.py         # Event CRUD, search/filter, cascading cancellation
│   │   ├── resources.py      # Resource management, availability checker, JSON API
│   │   ├── requests.py       # Resource request wizard, all-or-nothing submission
│   │   └── approvals.py      # 3-stage admin approvals hub & atomic allocation
│   ├── templates/            # Jinja2 templates styled with Tailwind CSS (Royal Indigo theme)
│   │   ├── auth/login.html
│   │   ├── dashboard.html
│   │   ├── events/
│   │   ├── resources/
│   │   ├── requests/
│   │   ├── approvals/
│   │   └── errors/
│   └── utils/
│       ├── auth.py           # Role management, demo user accounts, admin decorators
│       ├── booking.py        # Overlap interval logic, suitability, alternative engine
│       └── validators.py     # Clean error handling & input validation
├── tests/
│   └── test_system.py        # Automated test suite (100% passing)
├── config.py                 # Environment configuration
├── seed.py                   # Database seeder with sample campus catalog
├── run.py                    # Entry point for development server
├── requirements.txt          # Production & dev dependencies
├── Procfile                  # Production deployment profile
└── README.md                 # Complete technical documentation
```

---

## 📄 License
Created for the Technical Assignment: College Event Resource Allocation System.