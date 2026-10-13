"""
Data model for the College Event Resource Allocation System.

Design decisions:
1. Event and Resource are distinct core entities.
2. ResourceRequest encapsulates an organizer's request for 1 or more resources
   (represented by RequestItems) for a specific time window.
3. Allocation is the operational source-of-truth table for active bookings,
   populated upon approval/allocation and soft-deactivated when cancelled.
4. Python Enums manage statuses for events, requests, and resource types.
"""
from datetime import datetime
from enum import Enum

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class UserRole(str, Enum):
    ADMIN = "admin"
    ORGANIZER = "organizer"


class EventStatus(str, Enum):
    DRAFT = "Draft"
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"
    COMPLETED = "Completed"


class RequestStatus(str, Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    ALLOCATED = "Allocated"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"


class ResourceType(str, Enum):
    AUDITORIUM = "Auditorium"
    LABORATORY = "Laboratory"
    PROJECTOR = "Projector"
    MICROPHONE = "Microphone"
    CAMERA = "Camera"
    COMPUTER = "Computer"


class User(db.Model):
    """A real account. Passwords are stored only as salted hashes."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=UserRole.ORGANIZER.value)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN.value

    def __repr__(self):
        return f"<User {self.username} {self.role}>"


class AuditLog(db.Model):
    """Append-only record of who did what (approvals, allocations, cancellations...)."""
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    username = db.Column(db.String(40), nullable=False, default="system")
    action = db.Column(db.String(60), nullable=False, index=True)
    entity_type = db.Column(db.String(30), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User")

    def __repr__(self):
        return f"<AuditLog {self.action} {self.entity_type}#{self.entity_id} by {self.username}>"


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    organizer = db.Column(db.String(150), nullable=False)
    expected_attendance = db.Column(db.Integer, nullable=False)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=EventStatus.DRAFT.value)
    # The account that created the event. Nullable so legacy rows (created
    # before accounts existed) remain valid; only admins can manage those.
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = db.relationship("User", foreign_keys=[owner_id])

    requests = db.relationship(
        "ResourceRequest", backref="event", cascade="all, delete-orphan", lazy=True,
        order_by="ResourceRequest.created_at.desc()"
    )

    @property
    def rejection_reason(self):
        """Reason given by the admin on the most recent rejected request."""
        rejected = [r for r in self.requests if r.status == RequestStatus.REJECTED.value and r.rejection_reason]
        if not rejected:
            return None
        return max(rejected, key=lambda r: r.decided_at or r.created_at).rejection_reason

    @property
    def is_editable(self):
        # Rejected events can still be edited so the organizer can fix
        # dates/attendance and submit a new resource request.
        return self.status not in (EventStatus.CANCELLED.value, EventStatus.COMPLETED.value)

    @property
    def is_cancellable(self):
        return self.status not in (EventStatus.CANCELLED.value, EventStatus.COMPLETED.value)

    @property
    def is_deletable(self):
        """Draft, Rejected, and Cancelled events can be safely deleted."""
        return self.status in (
            EventStatus.DRAFT.value,
            EventStatus.REJECTED.value,
            EventStatus.CANCELLED.value,
        )

    @property
    def formatted_start(self):
        return self.start_datetime.strftime("%d %b %Y, %I:%M %p")

    @property
    def formatted_end(self):
        return self.end_datetime.strftime("%d %b %Y, %I:%M %p")

    @property
    def formatted_window(self):
        if self.start_datetime.date() == self.end_datetime.date():
            return f"{self.start_datetime.strftime('%d %b %Y')} · {self.start_datetime.strftime('%I:%M %p')} – {self.end_datetime.strftime('%I:%M %p')}"
        return f"{self.formatted_start} – {self.formatted_end}"

    def __repr__(self):
        return f"<Event {self.id} {self.name!r} {self.status}>"


class Resource(db.Model):
    __tablename__ = "resources"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    type = db.Column(db.String(30), nullable=False)  # ResourceType value
    capacity = db.Column(db.Integer, nullable=True)  # audience seating capacity (if applicable)
    total_quantity = db.Column(db.Integer, nullable=False, default=1)  # available units
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_venue(self):
        return self.type in (ResourceType.AUDITORIUM.value, ResourceType.LABORATORY.value)

    def __repr__(self):
        return f"<Resource {self.id} {self.name!r} {self.type}>"


class ResourceRequest(db.Model):
    __tablename__ = "resource_requests"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=RequestStatus.PENDING.value)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)
    decided_by = db.Column(db.String(40), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    items = db.relationship(
        "RequestItem", backref="request", cascade="all, delete-orphan", lazy=True
    )

    @property
    def items_summary(self):
        if not self.items:
            return "No resources"
        return ", ".join(f"{item.quantity}x {item.resource.name}" for item in self.items if item.resource)

    @property
    def formatted_window(self):
        if self.start_datetime.date() == self.end_datetime.date():
            return f"{self.start_datetime.strftime('%d %b %Y')} · {self.start_datetime.strftime('%I:%M %p')} – {self.end_datetime.strftime('%I:%M %p')}"
        return f"{self.start_datetime.strftime('%d %b %Y, %I:%M %p')} – {self.end_datetime.strftime('%d %b %Y, %I:%M %p')}"

    def __repr__(self):
        return f"<ResourceRequest {self.id} event={self.event_id} {self.status}>"


class RequestItem(db.Model):
    __tablename__ = "request_items"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("resource_requests.id"), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    resource = db.relationship("Resource")

    def __repr__(self):
        return f"<RequestItem resource={self.resource_id} qty={self.quantity}>"


class Allocation(db.Model):
    __tablename__ = "allocations"

    id = db.Column(db.Integer, primary_key=True)
    request_item_id = db.Column(db.Integer, db.ForeignKey("request_items.id"), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    resource = db.relationship("Resource")
    event = db.relationship("Event")

    def __repr__(self):
        return f"<Allocation resource={self.resource_id} {self.start_datetime}->{self.end_datetime}>"
