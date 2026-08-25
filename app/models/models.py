"""
Data model for the College Event Resource Allocation System.

Design decisions (explained here so they're visible right next to the code):

1. Event and Resource are separate entities from the "booking" itself.
   A booking is represented by a ResourceRequest (the organizer's ask for
   one or more resources) which contains RequestItems (one per resource
   requested). This mirrors the real workflow: an organizer requests
   several resources together for one event/time-window, and the whole
   batch must succeed or fail together (see the "all-or-nothing" rule
   in the assignment).

2. Allocation is a SEPARATE table from RequestItem, even though every
   Allocation starts life as an approved RequestItem. Why not just add
   an "allocated" boolean to RequestItem?
   - Conflict checking (double-booking) only ever needs to look at
     *actual allocations*, not every request that was ever submitted
     (including rejected/cancelled ones). Keeping Allocation separate
     means the double-booking query is a simple, fast scan over one
     table with no status filtering gymnastics.
   - It also makes "cancel an allocation releases the resource" a clean
     operation: delete/void the Allocation row, not reinterpret a
     RequestItem's status.

3. Status is modeled with plain string columns + Python enums (not a
   SQL ENUM type) because SQLite's ENUM support is weak/nonexistent --
   Flask-SQLAlchemy would just emulate it with a CHECK constraint anyway.
   Using Python-side enums gives us the same safety (typos caught early)
   without fighting SQLite.
"""
from datetime import datetime
from enum import Enum

from app.extensions import db


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


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    organizer = db.Column(db.String(150), nullable=False)
    expected_attendance = db.Column(db.Integer, nullable=False)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=EventStatus.DRAFT.value)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # cascade="all, delete-orphan": if an event is ever hard-deleted, its
    # requests go with it. In practice we prefer soft states (Cancelled)
    # over deletion, but this keeps the DB consistent if deletion happens.
    requests = db.relationship(
        "ResourceRequest", backref="event", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self):
        return f"<Event {self.id} {self.name!r} {self.status}>"


class Resource(db.Model):
    __tablename__ = "resources"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    type = db.Column(db.String(30), nullable=False)  # ResourceType value
    capacity = db.Column(db.Integer, nullable=True)  # audience capacity; nullable for mic/camera/etc.

    # How many identical physical units this record represents, e.g. a
    # "Wireless Microphone" resource might have total_quantity=5 meaning
    # 5 physical mics share one catalog entry. This is DIFFERENT from
    # `capacity`, which is about audience size for venues (Auditorium,
    # Lab), not unit count. A single Auditorium has total_quantity=1
    # (there's only one of it) but capacity=500 (it seats 500 people).
    # This is what lets "2 Microphones" in one request be satisfied by
    # one Resource row with quantity=2, instead of forcing every mic to
    # be its own separate row.
    total_quantity = db.Column(db.Integer, nullable=False, default=1)

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Resource {self.id} {self.name!r} {self.type}>"


class ResourceRequest(db.Model):
    """
    One 'ask' from an organizer: for a given event, at a given time window,
    give me these N resources. Time window is stored on the request (not
    just inherited from the Event) because a large event might request
    different resources for different sub-slots in principle -- storing it
    explicitly keeps conflict-checking logic independent of how Event
    timing might evolve later.
    """
    __tablename__ = "resource_requests"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=RequestStatus.PENDING.value)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)

    items = db.relationship(
        "RequestItem", backref="request", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self):
        return f"<ResourceRequest {self.id} event={self.event_id} {self.status}>"


class RequestItem(db.Model):
    """
    A single resource line within a ResourceRequest, e.g. '2 Microphones'
    or '1 Auditorium'. Quantity exists because the assignment example asks
    for "2 Microphones" as one line, not two separate lines.
    """
    __tablename__ = "request_items"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("resource_requests.id"), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    resource = db.relationship("Resource")

    def __repr__(self):
        return f"<RequestItem resource={self.resource_id} qty={self.quantity}>"


class Allocation(db.Model):
    """
    The source of truth for 'this resource is booked during this window'.
    Created only when a ResourceRequest is approved. This is the ONLY table
    the double-booking check queries against.
    """
    __tablename__ = "allocations"

    id = db.Column(db.Integer, primary_key=True)
    request_item_id = db.Column(db.Integer, db.ForeignKey("request_items.id"), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)  # False once cancelled

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    resource = db.relationship("Resource")
    event = db.relationship("Event")

    def __repr__(self):
        return f"<Allocation resource={self.resource_id} {self.start_datetime}->{self.end_datetime}>"
