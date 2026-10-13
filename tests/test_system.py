import os
import unittest
from datetime import datetime, timedelta

# Must be set before create_app() is called: the app otherwise starts a
# background seeding thread that races with the in-memory test database.
os.environ["AUTO_SEED"] = "0"

from app import create_app
from app.extensions import db
from app.models import Event, EventStatus, Resource, ResourceType, ResourceRequest, RequestItem, RequestStatus, Allocation
from app.utils.booking import (
    overlaps,
    booked_quantity,
    check_suitability,
    check_availability,
    find_alternatives,
    validate_request_rows,
)
from app.utils.validators import (
    ValidationError,
    validate_event_window,
    validate_attendance,
)


class TestCollegeEventSystem(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # Seed test resources
        self.auditorium_large = Resource(
            name="Main Auditorium", type=ResourceType.AUDITORIUM.value, capacity=500, total_quantity=1, is_active=True
        )
        self.auditorium_small = Resource(
            name="Mini Auditorium", type=ResourceType.AUDITORIUM.value, capacity=200, total_quantity=1, is_active=True
        )
        self.auditorium_inactive = Resource(
            name="Old Hall", type=ResourceType.AUDITORIUM.value, capacity=150, total_quantity=1, is_active=False
        )
        self.projector = Resource(
            name="Laser Projector", type=ResourceType.PROJECTOR.value, capacity=None, total_quantity=2, is_active=True
        )
        self.microphone = Resource(
            name="Wireless Mic Set", type=ResourceType.MICROPHONE.value, capacity=None, total_quantity=5, is_active=True
        )

        db.session.add_all([
            self.auditorium_large,
            self.auditorium_small,
            self.auditorium_inactive,
            self.projector,
            self.microphone,
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    # 1. Event Validation & Management Tests
    def test_event_date_validation(self):
        now = datetime.now()
        # End time before start time must fail
        with self.assertRaises(ValidationError):
            validate_event_window(now + timedelta(hours=4), now + timedelta(hours=2))

        # End time equal to start time must fail
        with self.assertRaises(ValidationError):
            validate_event_window(now, now)

        # End time after start time must pass
        try:
            validate_event_window(now, now + timedelta(hours=2))
        except ValidationError:
            self.fail("validate_event_window raised ValidationError unexpectedly.")

    def test_event_attendance_validation(self):
        # Positive whole number succeeds
        self.assertEqual(validate_attendance("150"), 150)

        # Negative and zero attendance must fail
        with self.assertRaises(ValidationError):
            validate_attendance("0")
        with self.assertRaises(ValidationError):
            validate_attendance("-10")
        with self.assertRaises(ValidationError):
            validate_attendance("not_a_number")

    def test_event_cancellation_cascades_to_allocations(self):
        # Create event with an allocated resource request
        now = datetime.now() + timedelta(days=1)
        start = now.replace(hour=10, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=4)

        event = Event(
            name="Robotics Fest",
            organizer="Robotics Club",
            expected_attendance=150,
            start_datetime=start,
            end_datetime=end,
            status=EventStatus.APPROVED.value,
        )
        db.session.add(event)
        db.session.flush()

        req = ResourceRequest(
            event_id=event.id,
            start_datetime=start,
            end_datetime=end,
            status=RequestStatus.ALLOCATED.value,
        )
        db.session.add(req)
        db.session.flush()

        item = RequestItem(request_id=req.id, resource_id=self.auditorium_small.id, quantity=1)
        db.session.add(item)
        db.session.flush()

        alloc = Allocation(
            request_item_id=item.id,
            resource_id=self.auditorium_small.id,
            event_id=event.id,
            quantity=1,
            start_datetime=start,
            end_datetime=end,
            is_active=True,
        )
        db.session.add(alloc)
        db.session.commit()

        # Auditorium should currently be booked
        self.assertEqual(booked_quantity(self.auditorium_small.id, start, end), 1)

        # Cancel event via route
        with self.client.session_transaction() as sess:
            sess["role"] = "organizer"
        res = self.client.post(f"/events/{event.id}/cancel", follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Event and request should be cancelled
        updated_event = Event.query.get(event.id)
        updated_req = ResourceRequest.query.get(req.id)
        self.assertEqual(updated_event.status, EventStatus.CANCELLED.value)
        self.assertEqual(updated_req.status, RequestStatus.CANCELLED.value)

        # Allocation must be deactivated and resource freed
        self.assertEqual(booked_quantity(self.auditorium_small.id, start, end), 0)

    # 2. Resource Management & Inactivity Checks
    def test_inactive_resource_cannot_be_allocated(self):
        reasons = check_suitability(self.auditorium_inactive, ResourceType.AUDITORIUM.value, 50)
        self.assertTrue(any("is inactive" in r for r in reasons))

    # 3. Double Booking Prevention (Conflict Checking)
    def test_conflict_detection_overlaps(self):
        t10 = datetime(2026, 9, 20, 10, 0)
        t12 = datetime(2026, 9, 20, 12, 0)
        t14 = datetime(2026, 9, 20, 14, 0)
        t16 = datetime(2026, 9, 20, 16, 0)

        # [10:00 - 14:00] overlaps with [12:00 - 16:00]
        self.assertTrue(overlaps(t10, t14, t12, t16))

        # [10:00 - 14:00] does NOT overlap with back-to-back [14:00 - 16:00] (Allow)
        self.assertFalse(overlaps(t10, t14, t14, t16))

        # [14:00 - 16:00] does NOT overlap with [10:00 - 14:00]
        self.assertFalse(overlaps(t14, t16, t10, t14))

    def test_multi_unit_quantity_conflict_checking(self):
        t10 = datetime(2026, 9, 20, 10, 0)
        t14 = datetime(2026, 9, 20, 14, 0)

        # Allocate 1 of 2 Laser Projectors
        item = RequestItem(request_id=1, resource_id=self.projector.id, quantity=1)
        # Fake allocation in memory
        alloc = Allocation(
            request_item_id=1,
            resource_id=self.projector.id,
            event_id=1,
            quantity=1,
            start_datetime=t10,
            end_datetime=t14,
            is_active=True,
        )
        db.session.add(alloc)
        db.session.commit()

        # Requesting 1 projector should pass (1 free)
        reasons_1 = check_availability(self.projector, t10, t14, 1)
        self.assertEqual(len(reasons_1), 0)

        # Requesting 2 projectors should fail (only 1 free out of 2)
        reasons_2 = check_availability(self.projector, t10, t14, 2)
        self.assertTrue(len(reasons_2) > 0)

    # 4. Resource Suitability Checks
    def test_resource_suitability_capacity_and_type(self):
        # Event attendance 300 vs Mini Auditorium capacity 200 -> Fail
        reasons_cap = check_suitability(self.auditorium_small, ResourceType.AUDITORIUM.value, 300)
        self.assertTrue(any("is below expected attendance" in r for r in reasons_cap))

        # Event attendance 200 vs Mini Auditorium capacity 200 -> Pass
        reasons_fit = check_suitability(self.auditorium_small, ResourceType.AUDITORIUM.value, 200)
        self.assertEqual(len(reasons_fit), 0)

        # Type mismatch: Projector vs Microphone -> Fail
        reasons_type = check_suitability(self.microphone, ResourceType.PROJECTOR.value, 50)
        self.assertTrue(any("is a Microphone, not a Projector" in r for r in reasons_type))

    # 5. Alternative Resource Suggestions Engine
    def test_alternative_resource_selection(self):
        t10 = datetime(2026, 9, 20, 10, 0)
        t14 = datetime(2026, 9, 20, 14, 0)

        # Mini Auditorium (cap 200) is requested for attendance 250 (unsuitable)
        alternatives = find_alternatives(
            required_type=ResourceType.AUDITORIUM.value,
            expected_attendance=250,
            start_dt=t10,
            end_dt=t14,
            requested_qty=1,
            exclude_resource_id=self.auditorium_small.id,
        )
        # Main Auditorium (cap 500) must be suggested
        self.assertEqual(len(alternatives), 1)
        self.assertEqual(alternatives[0].name, "Main Auditorium")

        # Inactive Old Hall (cap 150) and under-capacity Mini Auditorium must NOT be suggested
        alt_names = [a.name for a in alternatives]
        self.assertNotIn("Old Hall", alt_names)
        self.assertNotIn("Mini Auditorium", alt_names)

    # 6. All-or-Nothing Transactional Allocation
    def test_all_or_nothing_allocation_failure(self):
        now = datetime.now() + timedelta(days=2)
        start = now.replace(hour=10, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=4)

        # Pre-book all 2 Laser Projectors
        alloc = Allocation(
            request_item_id=99,
            resource_id=self.projector.id,
            event_id=99,
            quantity=2,
            start_datetime=start,
            end_datetime=end,
            is_active=True,
        )
        db.session.add(alloc)

        # Create new Approved request that asks for:
        # 1. Main Auditorium (Available)
        # 2. 1 Laser Projector (UNAVAILABLE - 0 free)
        # 3. 2 Microphones (Available)
        event = Event(
            name="Annual Convocation",
            organizer="Dean Office",
            expected_attendance=400,
            start_datetime=start,
            end_datetime=end,
            status=EventStatus.APPROVED.value,
        )
        db.session.add(event)
        db.session.flush()

        req = ResourceRequest(
            event_id=event.id,
            start_datetime=start,
            end_datetime=end,
            status=RequestStatus.APPROVED.value,
        )
        db.session.add(req)
        db.session.flush()

        item_hall = RequestItem(request_id=req.id, resource_id=self.auditorium_large.id, quantity=1)
        item_proj = RequestItem(request_id=req.id, resource_id=self.projector.id, quantity=1)
        item_mics = RequestItem(request_id=req.id, resource_id=self.microphone.id, quantity=2)
        db.session.add_all([item_hall, item_proj, item_mics])
        db.session.commit()

        # Admin tries to allocate
        with self.client.session_transaction() as sess:
            sess["role"] = "admin"
        res = self.client.post(f"/approvals/{req.id}/allocate", follow_redirects=True)

        # Allocation must fail because projector is unavailable
        updated_req = ResourceRequest.query.get(req.id)
        self.assertEqual(updated_req.status, RequestStatus.APPROVED.value)

        # Zero allocations should be created for this request (All-or-Nothing rule)
        req_allocations = Allocation.query.filter(
            Allocation.request_item_id.in_([item_hall.id, item_proj.id, item_mics.id])
        ).all()
        self.assertEqual(len(req_allocations), 0)

        # Main Auditorium and Microphones must NOT have partial locks
        self.assertEqual(booked_quantity(self.auditorium_large.id, start, end), 0)
        self.assertEqual(booked_quantity(self.microphone.id, start, end), 0)


if __name__ == "__main__":
    unittest.main()
