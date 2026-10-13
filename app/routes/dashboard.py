from datetime import datetime, timedelta

from flask import Blueprint, render_template

from app.models import (
    Allocation, AuditLog, Event, EventStatus, Resource, ResourceRequest, RequestStatus,
)
from app.utils.auth import current_user, is_admin

dashboard_bp = Blueprint("dashboard", __name__)


def _utilization(days=7, limit=6):
    """
    Share of each active resource's capacity that is booked over the next
    `days` days: sum(overlap hours x quantity) / (total units x window hours).
    """
    window_start = datetime.now()
    window_end = window_start + timedelta(days=days)
    window_hours = days * 24

    resources = Resource.query.filter_by(is_active=True).all()
    allocations = Allocation.query.filter(
        Allocation.is_active.is_(True),
        Allocation.start_datetime < window_end,
        Allocation.end_datetime > window_start,
    ).all()

    booked_hours = {}
    for alloc in allocations:
        start = max(alloc.start_datetime, window_start)
        end = min(alloc.end_datetime, window_end)
        hours = max(0.0, (end - start).total_seconds() / 3600)
        booked_hours[alloc.resource_id] = booked_hours.get(alloc.resource_id, 0.0) + hours * alloc.quantity

    rows = []
    for res in resources:
        capacity_hours = max(1, res.total_quantity) * window_hours
        pct = min(100, round(booked_hours.get(res.id, 0.0) / capacity_hours * 100))
        rows.append({"resource": res, "pct": pct})
    rows.sort(key=lambda r: (-r["pct"], r["resource"].name))
    return rows[:limit]


def _admin_context():
    status_counts = {s.value: Event.query.filter_by(status=s.value).count() for s in EventStatus}
    return dict(
        total_events=Event.query.count(),
        total_resources=Resource.query.count(),
        active_resources=Resource.query.filter_by(is_active=True).count(),
        pending_requests_count=ResourceRequest.query.filter_by(status=RequestStatus.PENDING.value).count(),
        ready_to_allocate_count=ResourceRequest.query.filter_by(status=RequestStatus.APPROVED.value).count(),
        active_allocations_count=ResourceRequest.query.filter_by(status=RequestStatus.ALLOCATED.value).count(),
        pending_requests=(
            ResourceRequest.query.filter_by(status=RequestStatus.PENDING.value)
            .order_by(ResourceRequest.created_at.asc())
            .limit(5)
            .all()
        ),
        upcoming_events=(
            Event.query.filter(Event.status.in_([EventStatus.APPROVED.value, EventStatus.PENDING.value]))
            .order_by(Event.start_datetime.asc())
            .limit(6)
            .all()
        ),
        status_counts=status_counts,
        utilization=_utilization(),
        recent_activity=AuditLog.query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(6).all(),
    )


def _organizer_context(user):
    my_events = Event.query.filter(Event.owner_id == user.id)
    status_counts = {s.value: my_events.filter(Event.status == s.value).count() for s in EventStatus}

    my_requests = (
        ResourceRequest.query.join(Event, ResourceRequest.event_id == Event.id)
        .filter(Event.owner_id == user.id)
    )

    # Things that need the organizer's attention, most urgent first.
    rejected_events = (
        my_events.filter(Event.status == EventStatus.REJECTED.value)
        .order_by(Event.start_datetime.asc()).all()
    )
    draft_events = (
        my_events.filter(Event.status == EventStatus.DRAFT.value)
        .order_by(Event.start_datetime.asc()).all()
    )

    upcoming = (
        my_events.filter(
            Event.status.in_([EventStatus.APPROVED.value, EventStatus.PENDING.value, EventStatus.DRAFT.value]),
            Event.end_datetime >= datetime.now(),
        )
        .order_by(Event.start_datetime.asc())
        .limit(6)
        .all()
    )

    # Campus schedule: upcoming events across all organizers so organizers can track other departments' events & dates
    all_campus_upcoming = (
        Event.query.filter(
            Event.status.in_([EventStatus.APPROVED.value, EventStatus.PENDING.value]),
            Event.end_datetime >= datetime.now(),
        )
        .order_by(Event.start_datetime.asc())
        .limit(10)
        .all()
    )

    return dict(
        my_total_events=my_events.count(),
        status_counts=status_counts,
        my_pending_count=my_requests.filter(ResourceRequest.status == RequestStatus.PENDING.value).count(),
        my_approved_count=my_requests.filter(
            ResourceRequest.status.in_([RequestStatus.APPROVED.value, RequestStatus.ALLOCATED.value])
        ).count(),
        rejected_events=rejected_events,
        draft_events=draft_events,
        upcoming_events=upcoming,
        all_campus_upcoming=all_campus_upcoming,
        recent_requests=my_requests.order_by(ResourceRequest.created_at.desc()).limit(5).all(),
    )


@dashboard_bp.route("/")
def index():
    """Role-specific home page: a Control Center for admins, a workspace for organizers."""
    user = current_user()
    if is_admin():
        return render_template("dashboard.html", user=user, **_admin_context())
    return render_template("dashboard.html", user=user, **_organizer_context(user))
