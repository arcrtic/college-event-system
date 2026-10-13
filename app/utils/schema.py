"""
Idempotent schema upgrades + account bootstrap, safe to run on every startup.

`db.create_all()` creates missing TABLES but never adds new COLUMNS to tables
that already exist (e.g. the production database created before accounts were
introduced). This module adds those columns in place so deployments upgrade
without losing data, and makes sure the demo accounts exist.
"""
from flask import current_app
from sqlalchemy import inspect, text

from app.extensions import db
from app.models import Event, User, UserRole

# (table, column, SQL type) -- all nullable, so existing rows stay valid.
_NEW_COLUMNS = [
    ("events", "owner_id", "INTEGER REFERENCES users(id)"),
    ("resource_requests", "rejection_reason", "TEXT"),
    ("resource_requests", "decided_by", "VARCHAR(40)"),
]


def ensure_columns():
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    added = []
    for table, column, ddl in _NEW_COLUMNS:
        if table not in existing_tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        if column in have:
            continue
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        added.append(f"{table}.{column}")
    if added:
        db.session.commit()
        print(f"[OK] Added missing columns: {', '.join(added)}")
    return added


def ensure_demo_users():
    """Create the `admin` and `organizer` accounts if they don't exist yet.

    Existing accounts are never modified, so a changed password is preserved.
    """
    admin_password = current_app.config.get("ADMIN_PASSCODE", "admin123")
    wanted = [
        ("admin", "Admin User", UserRole.ADMIN.value, admin_password, "Administration"),
        ("organizer", "Event Organizer", UserRole.ORGANIZER.value, "organizer123", "Student Affairs"),
    ]
    created = []
    for username, name, role, password, department in wanted:
        if User.query.filter_by(username=username).first():
            continue
        user = User(username=username, name=name, role=role, department=department)
        user.set_password(password)
        db.session.add(user)
        created.append(username)
    if created:
        db.session.commit()
        print(f"[OK] Created accounts: {', '.join(created)}")

    return User.query.filter_by(username="organizer").first()


def assign_orphan_events(owner):
    """Give pre-accounts events (owner_id IS NULL) to the demo organizer."""
    if owner is None:
        return 0
    count = Event.query.filter(Event.owner_id.is_(None)).update(
        {"owner_id": owner.id}, synchronize_session=False
    )
    if count:
        db.session.commit()
        print(f"[OK] Assigned {count} existing event(s) to '{owner.username}'")
    return count


def upgrade_and_bootstrap():
    """Run all idempotent upgrade steps. Requires an app context."""
    ensure_columns()
    organizer = ensure_demo_users()
    assign_orphan_events(organizer)
