"""
Database seed script for the College Event Resource Allocation System.

Populates realistic campus venues, equipment fleets, events across different
lifecycle statuses, resource requests, and active allocations to immediately
demonstrate:
1. Double-booking conflict prevention (overlapping time slots rejected, back-to-back allowed)
2. Resource suitability enforcement (capacity checks, category type validation)
3. Alternative resource suggestion algorithms (best-fit capacity matching)
4. Approval and all-or-nothing allocation workflows

Usage:
    python seed.py
"""
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import Resource, ResourceType, Event, EventStatus, ResourceRequest, RequestItem, RequestStatus, Allocation


import sys
import time


def run():
    app = create_app()
    with app.app_context():
        # Retry connecting in case PostgreSQL database is still spinning up
        connected = False
        for attempt in range(1, 10):
            try:
                db.session.execute(db.text("SELECT 1"))
                connected = True
                break
            except Exception as e:
                print(f"[WAIT] Waiting for database to become available (attempt {attempt}/10)...")
                time.sleep(2)

        if not connected:
            print("[WARN] Could not connect to database after retries. Continuing...")
            return

        force_reset = "--reset" in sys.argv
        try:
            if not force_reset and Resource.query.first() is not None:
                print("[INFO] Database already contains data. Skipping seed. (Use --reset to overwrite)")
                return
        except Exception:
            pass

        # Clear existing tables for a clean seed reset
        try:
            db.drop_all()
            db.create_all()
        except Exception as e:
            print(f"[ERROR] Database creation error: {e}")
            return

        print("Seeding campus resources...")
        resources = [
            # 1. Auditoriums & Seminar Halls (Audience capacity constrained)
            Resource(name="Main Auditorium", type=ResourceType.AUDITORIUM.value, capacity=500, total_quantity=1, is_active=True),
            Resource(name="Mini Auditorium", type=ResourceType.AUDITORIUM.value, capacity=200, total_quantity=1, is_active=True),
            Resource(name="Seminar Hall A", type=ResourceType.AUDITORIUM.value, capacity=100, total_quantity=1, is_active=True),
            Resource(name="Seminar Hall B (Maintenance)", type=ResourceType.AUDITORIUM.value, capacity=80, total_quantity=1, is_active=False),

            # 2. Laboratories (Capacity constrained)
            Resource(name="Computer Lab 1", type=ResourceType.LABORATORY.value, capacity=60, total_quantity=1, is_active=True),
            Resource(name="Computer Lab 2", type=ResourceType.LABORATORY.value, capacity=40, total_quantity=1, is_active=True),
            Resource(name="Electronics & Robotics Lab", type=ResourceType.LABORATORY.value, capacity=35, total_quantity=1, is_active=True),

            # 3. Audiovisual Equipment (Multi-unit fleets)
            Resource(name="4K Laser Projector", type=ResourceType.PROJECTOR.value, capacity=None, total_quantity=3, is_active=True),
            Resource(name="Portable HD Projector", type=ResourceType.PROJECTOR.value, capacity=None, total_quantity=4, is_active=True),
            Resource(name="Wireless Handheld Mic Set", type=ResourceType.MICROPHONE.value, capacity=None, total_quantity=6, is_active=True),
            Resource(name="Collar / Lavalier Mic Set", type=ResourceType.MICROPHONE.value, capacity=None, total_quantity=4, is_active=True),
            Resource(name="Professional DSLR Camera", type=ResourceType.CAMERA.value, capacity=None, total_quantity=2, is_active=True),
            Resource(name="4K Video Production Camera", type=ResourceType.CAMERA.value, capacity=None, total_quantity=2, is_active=True),

            # 4. Computing fleets
            Resource(name="Laptop Cart Fleet", type=ResourceType.COMPUTER.value, capacity=None, total_quantity=25, is_active=True),
            Resource(name="Desktop Workstation Lab", type=ResourceType.COMPUTER.value, capacity=None, total_quantity=30, is_active=True),
        ]
        db.session.add_all(resources)
        db.session.flush()

        # Map resources by name for easy relational linking
        res_by_name = {r.name: r for r in resources}

        now = datetime.now().replace(minute=0, second=0, microsecond=0)

        print("Seeding sample events across lifecycle stages...")

        # 1. Approved Event with Allocated Resources (Locked in)
        # Event: Technical Workshop (20 Sep 2026, 10:00 AM - 02:00 PM)
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

        # Requested items: Mini Auditorium (cap 200 fits 180), 1 4K Laser Projector, 2 Wireless Mics
        item1_hall = RequestItem(request_id=req1.id, resource_id=res_by_name["Mini Auditorium"].id, quantity=1)
        item1_proj = RequestItem(request_id=req1.id, resource_id=res_by_name["4K Laser Projector"].id, quantity=1)
        item1_mics = RequestItem(request_id=req1.id, resource_id=res_by_name["Wireless Handheld Mic Set"].id, quantity=2)
        db.session.add_all([item1_hall, item1_proj, item1_mics])
        db.session.flush()

        # Create corresponding active allocations
        db.session.add(Allocation(
            request_item_id=item1_hall.id, resource_id=res_by_name["Mini Auditorium"].id,
            event_id=event1.id, quantity=1, start_datetime=ev1_start, end_datetime=ev1_end, is_active=True
        ))
        db.session.add(Allocation(
            request_item_id=item1_proj.id, resource_id=res_by_name["4K Laser Projector"].id,
            event_id=event1.id, quantity=1, start_datetime=ev1_start, end_datetime=ev1_end, is_active=True
        ))
        db.session.add(Allocation(
            request_item_id=item1_mics.id, resource_id=res_by_name["Wireless Handheld Mic Set"].id,
            event_id=event1.id, quantity=2, start_datetime=ev1_start, end_datetime=ev1_end, is_active=True
        ))

        # 2. Pending Event with Pending Resource Request (Awaiting Admin Review)
        # Event: Cultural Fest (27 Sep 2026, 10:00 AM - 08:00 PM)
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

        db.session.add(RequestItem(request_id=req2.id, resource_id=res_by_name["Main Auditorium"].id, quantity=1))
        db.session.add(RequestItem(request_id=req2.id, resource_id=res_by_name["Professional DSLR Camera"].id, quantity=1))
        db.session.add(RequestItem(request_id=req2.id, resource_id=res_by_name["Wireless Handheld Mic Set"].id, quantity=4))

        # 3. Draft Event (No resources requested yet)
        # Event: Alumni Meet 2026
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

        # 4. Completed Event
        # Event: Hackathon 2026 (Past event)
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

        db.session.commit()
        print("[OK] Database successfully initialized and seeded with:")
        print(f"  - {len(resources)} campus resources")
        print("  - 4 sample events across Draft, Pending, Approved, and Completed")
        print("  - Active allocations demonstrating double-booking locks and suitability validation.")


if __name__ == "__main__":
    run()
