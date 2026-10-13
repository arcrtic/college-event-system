
"""
Database seed script for the College Event Resource Allocation System.

Initializes the database and populates campus resources, sample events,
resource requests, and allocations.

Usage:
    python seed.py
    python seed.py --reset

WARNING:
    --reset deletes existing database tables and their data.
    Do not use --reset on a database containing data you need to keep.
"""

import os
import sys
import time
from datetime import datetime, timedelta

from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import (
    Resource,
    ResourceType,
    Event,
    EventStatus,
    ResourceRequest,
    RequestItem,
    RequestStatus,
    Allocation,
    User,
)
from app.utils.schema import assign_orphan_events, upgrade_and_bootstrap


def seed_data(app):
    """Initialize missing tables and seed the database safely."""

    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "<unset>")

        # Never print database credentials.
        safe_uri = db_uri
        if "@" in db_uri and "://" in db_uri:
            scheme, rest = db_uri.split("://", 1)
            _, host_part = rest.split("@", 1)
            safe_uri = f"{scheme}://***@{host_part}"

        print(f"[INFO] Connecting to database: {safe_uri}")

        # Retry the database connection.
        connected = False
        last_error = None

        for attempt in range(1, 11):
            try:
                db.session.execute(text("SELECT 1"))
                db.session.rollback()
                connected = True
                print("[OK] Database connection successful.")
                break

            except Exception as exc:
                last_error = exc

                # A failed SQL statement can leave the transaction aborted.
                db.session.rollback()

                print(
                    f"[WAIT] Connection attempt "
                    f"{attempt}/10 failed: {exc}"
                )

                if attempt < 10:
                    time.sleep(2)

        if not connected:
            print("[ERROR] Could not connect to the database.")
            print(f"[ERROR] Last error: {last_error}")
            return False

        force_reset = "--reset" in sys.argv

        try:
            # Only an explicit --reset is allowed to delete tables.
            if force_reset:
                print("[WARN] Reset requested. Dropping existing tables.")
                db.drop_all()
                db.session.commit()

            # Create any missing tables without deleting existing data.
            db.create_all()
            db.session.commit()

            print("[OK] Database tables are ready.")

        except Exception as exc:
            db.session.rollback()
            print(f"[ERROR] Database table initialization failed: {exc}")
            return False

        # Add any new columns to pre-existing tables and make sure the admin /
        # organizer accounts exist. Idempotent, so it runs on every boot.
        try:
            upgrade_and_bootstrap()
        except Exception as exc:
            db.session.rollback()
            print(f"[ERROR] Schema upgrade / account bootstrap failed: {exc}")
            return False

        # Check whether initial resources already exist.
        try:
            existing_resource = Resource.query.first()

            if existing_resource is not None:
                print(
                    "[INFO] Database already contains resources. "
                    "Skipping seed."
                )
                return True

        except Exception as exc:
            db.session.rollback()
            print(f"[ERROR] Could not check existing resources: {exc}")
            return False

        try:
            print("Seeding campus resources...")

            resources = [
                Resource(
                    name="Main Auditorium",
                    type=ResourceType.AUDITORIUM.value,
                    capacity=500,
                    total_quantity=1,
                    is_active=True,
                ),
                Resource(
                    name="Mini Auditorium",
                    type=ResourceType.AUDITORIUM.value,
                    capacity=200,
                    total_quantity=1,
                    is_active=True,
                ),
                Resource(
                    name="Seminar Hall A",
                    type=ResourceType.AUDITORIUM.value,
                    capacity=100,
                    total_quantity=1,
                    is_active=True,
                ),
                Resource(
                    name="Seminar Hall B (Maintenance)",
                    type=ResourceType.AUDITORIUM.value,
                    capacity=80,
                    total_quantity=1,
                    is_active=False,
                ),
                Resource(
                    name="Computer Lab 1",
                    type=ResourceType.LABORATORY.value,
                    capacity=60,
                    total_quantity=1,
                    is_active=True,
                ),
                Resource(
                    name="Computer Lab 2",
                    type=ResourceType.LABORATORY.value,
                    capacity=40,
                    total_quantity=1,
                    is_active=True,
                ),
                Resource(
                    name="Electronics & Robotics Lab",
                    type=ResourceType.LABORATORY.value,
                    capacity=35,
                    total_quantity=1,
                    is_active=True,
                ),
                Resource(
                    name="4K Laser Projector",
                    type=ResourceType.PROJECTOR.value,
                    capacity=None,
                    total_quantity=3,
                    is_active=True,
                ),
                Resource(
                    name="Portable HD Projector",
                    type=ResourceType.PROJECTOR.value,
                    capacity=None,
                    total_quantity=4,
                    is_active=True,
                ),
                Resource(
                    name="Wireless Handheld Mic Set",
                    type=ResourceType.MICROPHONE.value,
                    capacity=None,
                    total_quantity=6,
                    is_active=True,
                ),
                Resource(
                    name="Collar / Lavalier Mic Set",
                    type=ResourceType.MICROPHONE.value,
                    capacity=None,
                    total_quantity=4,
                    is_active=True,
                ),
                Resource(
                    name="Professional DSLR Camera",
                    type=ResourceType.CAMERA.value,
                    capacity=None,
                    total_quantity=2,
                    is_active=True,
                ),
                Resource(
                    name="4K Video Production Camera",
                    type=ResourceType.CAMERA.value,
                    capacity=None,
                    total_quantity=2,
                    is_active=True,
                ),
                Resource(
                    name="Laptop Cart Fleet",
                    type=ResourceType.COMPUTER.value,
                    capacity=None,
                    total_quantity=25,
                    is_active=True,
                ),
                Resource(
                    name="Desktop Workstation Lab",
                    type=ResourceType.COMPUTER.value,
                    capacity=None,
                    total_quantity=30,
                    is_active=True,
                ),
            ]

            db.session.add_all(resources)
            db.session.flush()

            res_by_name = {resource.name: resource for resource in resources}
            now = datetime.now().replace(
                minute=0, second=0, microsecond=0
            )

            print("Seeding sample events...")

            # 1. Approved technical workshop with allocated resources.
            ev1_start = (now + timedelta(days=7)).replace(hour=10)
            ev1_end = ev1_start + timedelta(hours=4)

            event1 = Event(
                name="Technical Workshop 2026",
                organizer="CS Department",
                expected_attendance=180,
                start_datetime=ev1_start,
                end_datetime=ev1_end,
                status=EventStatus.APPROVED.value,
            )
            db.session.add(event1)
            db.session.flush()

            req1 = ResourceRequest(
                event_id=event1.id,
                start_datetime=ev1_start,
                end_datetime=ev1_end,
                status=RequestStatus.ALLOCATED.value,
                decided_at=now,
            )
            db.session.add(req1)
            db.session.flush()

            item1_hall = RequestItem(
                request_id=req1.id,
                resource_id=res_by_name["Mini Auditorium"].id,
                quantity=1,
            )
            item1_proj = RequestItem(
                request_id=req1.id,
                resource_id=res_by_name["4K Laser Projector"].id,
                quantity=1,
            )
            item1_mics = RequestItem(
                request_id=req1.id,
                resource_id=res_by_name[
                    "Wireless Handheld Mic Set"
                ].id,
                quantity=2,
            )

            db.session.add_all([item1_hall, item1_proj, item1_mics])
            db.session.flush()

            db.session.add_all([
                Allocation(
                    request_item_id=item1_hall.id,
                    resource_id=res_by_name["Mini Auditorium"].id,
                    event_id=event1.id,
                    quantity=1,
                    start_datetime=ev1_start,
                    end_datetime=ev1_end,
                    is_active=True,
                ),
                Allocation(
                    request_item_id=item1_proj.id,
                    resource_id=res_by_name["4K Laser Projector"].id,
                    event_id=event1.id,
                    quantity=1,
                    start_datetime=ev1_start,
                    end_datetime=ev1_end,
                    is_active=True,
                ),
                Allocation(
                    request_item_id=item1_mics.id,
                    resource_id=res_by_name[
                        "Wireless Handheld Mic Set"
                    ].id,
                    event_id=event1.id,
                    quantity=2,
                    start_datetime=ev1_start,
                    end_datetime=ev1_end,
                    is_active=True,
                ),
            ])

            # 2. Pending cultural fest.
            ev2_start = (now + timedelta(days=14)).replace(hour=10)
            ev2_end = ev2_start + timedelta(hours=10)

            event2 = Event(
                name="Cultural Fest 2026",
                organizer="Student Council",
                expected_attendance=450,
                start_datetime=ev2_start,
                end_datetime=ev2_end,
                status=EventStatus.PENDING.value,
            )
            db.session.add(event2)
            db.session.flush()

            req2 = ResourceRequest(
                event_id=event2.id,
                start_datetime=ev2_start,
                end_datetime=ev2_end,
                status=RequestStatus.PENDING.value,
            )
            db.session.add(req2)
            db.session.flush()

            db.session.add_all([
                RequestItem(
                    request_id=req2.id,
                    resource_id=res_by_name["Main Auditorium"].id,
                    quantity=1,
                ),
                RequestItem(
                    request_id=req2.id,
                    resource_id=res_by_name[
                        "Professional DSLR Camera"
                    ].id,
                    quantity=1,
                ),
                RequestItem(
                    request_id=req2.id,
                    resource_id=res_by_name[
                        "Wireless Handheld Mic Set"
                    ].id,
                    quantity=4,
                ),
            ])

            # 3. Draft alumni meet.
            ev3_start = (now + timedelta(days=21)).replace(hour=11)
            ev3_end = ev3_start + timedelta(hours=5)

            event3 = Event(
                name="Alumni Meet 2026",
                organizer="Admin Office",
                expected_attendance=300,
                start_datetime=ev3_start,
                end_datetime=ev3_end,
                status=EventStatus.DRAFT.value,
            )
            db.session.add(event3)

            # 4. Completed campus hackathon.
            ev4_start = (now - timedelta(days=5)).replace(hour=8)
            ev4_end = ev4_start + timedelta(hours=12)

            event4 = Event(
                name="Campus Hackathon 2026",
                organizer="IT Department",
                expected_attendance=120,
                start_datetime=ev4_start,
                end_datetime=ev4_end,
                status=EventStatus.COMPLETED.value,
            )
            db.session.add(event4)

            # Commit all seed data as a single transaction.
            db.session.commit()

            print("[OK] Database initialized and seeded successfully.")
            print(f"  - {len(resources)} campus resources")
            print("  - 4 sample events")
            print("  - Resource requests and active allocations")

            # Hand the freshly seeded sample events to the demo organizer.
            assign_orphan_events(User.query.filter_by(username="organizer").first())

            return True

        except Exception as exc:
            # Roll back every uncommitted seed operation on failure.
            db.session.rollback()
            print(f"[ERROR] Database seeding failed: {exc}")
            return False

        finally:
            db.session.remove()


def run():
    """Run the database initializer as a standalone script."""

    # Prevent a second background seeding process from racing this script.
    os.environ["AUTO_SEED"] = "0"

    app = create_app()
    success = seed_data(app)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    run()
