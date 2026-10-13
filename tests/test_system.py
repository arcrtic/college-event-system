import os
import unittest
from datetime import datetime, timedelta
#hello checking ci/cd by arcchit
# Must be set before create_app() is called: the app otherwise starts a
# background seeding thread that races with the in-memory test database.
os.environ["AUTO_SEED"] = "0"

from app import create_app
from app.extensions import db
from app.models import Event, EventStatus, Resource, ResourceType, ResourceRequest, RequestItem, RequestStatus, Allocation, User
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

        self.admin_user = User(
            username="testadmin", name="Test Admin", role="admin"
        )
        self.admin_user.set_password("admin123")

        self.organizer_user = User(
            username="testorg", name="Test Organizer", role="organizer"
        )
        self.organizer_user.set_password("organizer123")

        db.session.add_all([
            self.admin_user,
            self.organizer_user,
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
            owner_id=self.organizer_user.id,
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

        # Cancel event via route (as organizer owner)
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.organizer_user.id
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
            owner_id=self.organizer_user.id,
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
            sess["user_id"] = self.admin_user.id
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

    # 7. Role-Based Access Control & Rejection Workflows
    def test_role_based_access_control(self):
        now = datetime.now() + timedelta(days=5)
        # Create an event owned by user 999 (not self.organizer_user)
        other_event = Event(
            name="Other Organizer Event",
            organizer="Other Org",
            expected_attendance=50,
            start_datetime=now,
            end_datetime=now + timedelta(hours=2),
            status=EventStatus.PENDING.value,
            owner_id=999,
        )
        db.session.add(other_event)
        db.session.commit()

        # Organizer cannot cancel another organizer's event (403 Forbidden)
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.organizer_user.id
        res = self.client.post(f"/events/{other_event.id}/cancel")
        self.assertEqual(res.status_code, 403)

        # Organizer cannot access admin approvals hub (403 Forbidden)
        res_approvals = self.client.get("/approvals/")
        self.assertEqual(res_approvals.status_code, 403)

        # Admin can access approvals hub
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.admin_user.id
        res_admin = self.client.get("/approvals/")
        self.assertEqual(res_admin.status_code, 200)

    def test_rejection_workflow_with_reason(self):
        now = datetime.now() + timedelta(days=6)
        event = Event(
            name="Coding Contest",
            organizer="Coding Club",
            expected_attendance=100,
            start_datetime=now,
            end_datetime=now + timedelta(hours=3),
            status=EventStatus.PENDING.value,
            owner_id=self.organizer_user.id,
        )
        db.session.add(event)
        db.session.flush()

        req = ResourceRequest(
            event_id=event.id,
            start_datetime=now,
            end_datetime=now + timedelta(hours=3),
            status=RequestStatus.PENDING.value,
        )
        db.session.add(req)
        db.session.commit()

        # Admin rejects request with a reason
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.admin_user.id
        res = self.client.post(
            f"/approvals/{req.id}/reject",
            data={"reason": "Auditorium is reserved for institutional maintenance."},
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)

        # Verify request and event transition to Rejected and store the reason
        db.session.refresh(req)
        db.session.refresh(event)
        self.assertEqual(req.status, RequestStatus.REJECTED.value)
        self.assertEqual(req.rejection_reason, "Auditorium is reserved for institutional maintenance.")
        self.assertEqual(event.status, EventStatus.REJECTED.value)
        self.assertEqual(event.rejection_reason, "Auditorium is reserved for institutional maintenance.")

    def test_organizer_create_draft_vs_direct_submit(self):
        now = datetime.now() + timedelta(days=2)
        start_str = now.strftime("%Y-%m-%dT%H:%M")
        end_str = (now + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")

        with self.client.session_transaction() as sess:
            sess["user_id"] = self.organizer_user.id

        # 1. Save as Draft
        res = self.client.post("/events/new", data={
            "name": "Draft Tech Symposium",
            "organizer": "Test Organizer",
            "expected_attendance": "150",
            "start_datetime": start_str,
            "end_datetime": end_str,
            "action": "draft",
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        draft_event = Event.query.filter_by(name="Draft Tech Symposium").first()
        self.assertIsNotNone(draft_event)
        self.assertEqual(draft_event.status, EventStatus.DRAFT.value)
        self.assertEqual(len(draft_event.requests), 0)

        # 2. Direct Submit with resources
        res2 = self.client.post("/events/new", data={
            "name": "Submitted Hackathon",
            "organizer": "Test Organizer",
            "expected_attendance": "100",
            "start_datetime": start_str,
            "end_datetime": end_str,
            "action": "submit",
            "required_type[]": [ResourceType.AUDITORIUM.value],
            "resource_id[]": [str(self.auditorium_small.id)],
            "quantity[]": ["1"],
        }, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)

        submitted_event = Event.query.filter_by(name="Submitted Hackathon").first()
        self.assertIsNotNone(submitted_event)
        self.assertEqual(submitted_event.status, EventStatus.PENDING.value)
        self.assertEqual(len(submitted_event.requests), 1)
        self.assertEqual(submitted_event.requests[0].status, RequestStatus.PENDING.value)

    def test_delete_draft_and_rejected_events(self):
        now = datetime.now() + timedelta(days=3)
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.organizer_user.id

        # Create draft event
        draft_event = Event(
            name="Temporary Draft",
            organizer="Test Organizer",
            expected_attendance=50,
            start_datetime=now,
            end_datetime=now + timedelta(hours=2),
            status=EventStatus.DRAFT.value,
            owner_id=self.organizer_user.id,
        )
        db.session.add(draft_event)
        db.session.commit()

        # Organizer deletes their draft event
        res = self.client.post(f"/events/{draft_event.id}/delete", follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(Event.query.get(draft_event.id))

        # Create rejected event with request
        rejected_event = Event(
            name="Rejected Conference",
            organizer="Test Organizer",
            expected_attendance=200,
            start_datetime=now,
            end_datetime=now + timedelta(hours=3),
            status=EventStatus.REJECTED.value,
            owner_id=self.organizer_user.id,
        )
        db.session.add(rejected_event)
        db.session.flush()

        req = ResourceRequest(
            event_id=rejected_event.id,
            start_datetime=now,
            end_datetime=now + timedelta(hours=3),
            status=RequestStatus.REJECTED.value,
            rejection_reason="Schedule conflict",
        )
        db.session.add(req)
        db.session.commit()

        # Organizer deletes the rejected event
        res2 = self.client.post(f"/events/{rejected_event.id}/delete", follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        self.assertIsNone(Event.query.get(rejected_event.id))
        self.assertIsNone(ResourceRequest.query.get(req.id))

    def test_cannot_delete_approved_event(self):
        now = datetime.now() + timedelta(days=4)
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.organizer_user.id

        approved_event = Event(
            name="Official Approved Gala",
            organizer="Test Organizer",
            expected_attendance=300,
            start_datetime=now,
            end_datetime=now + timedelta(hours=4),
            status=EventStatus.APPROVED.value,
            owner_id=self.organizer_user.id,
        )
        db.session.add(approved_event)
        db.session.commit()

        # Try to delete approved event directly -> should be blocked
        res = self.client.post(f"/events/{approved_event.id}/delete", follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(Event.query.get(approved_event.id))
        self.assertEqual(Event.query.get(approved_event.id).status, EventStatus.APPROVED.value)


if __name__ == "__main__":
    unittest.main()
