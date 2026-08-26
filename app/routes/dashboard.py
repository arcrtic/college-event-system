from datetime import datetime
from flask import Blueprint, render_template

from app.models import Event, EventStatus, Resource, ResourceRequest, RequestStatus
from app.utils.auth import is_admin, current_user

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    """
    Comprehensive dashboard providing key operational metrics, quick actions,
    pending approvals list, upcoming scheduled events, and status breakdowns.
    """
    # Key operational metrics
    total_events = Event.query.count()
    total_resources = Resource.query.count()
    active_resources = Resource.query.filter_by(is_active=True).count()
    
    pending_requests_count = ResourceRequest.query.filter_by(status=RequestStatus.PENDING.value).count()
    approved_requests_count = ResourceRequest.query.filter(
        ResourceRequest.status.in_([RequestStatus.APPROVED.value, RequestStatus.ALLOCATED.value])
    ).count()
    total_requests_count = ResourceRequest.query.count()

    # Pending requests awaiting review (up to 5)
    pending_requests = (
        ResourceRequest.query.filter_by(status=RequestStatus.PENDING.value)
        .order_by(ResourceRequest.created_at.asc())
        .limit(5)
        .all()
    )

    # Upcoming events (Pending or Approved)
    upcoming_events = (
        Event.query.filter(Event.status.in_([EventStatus.APPROVED.value, EventStatus.PENDING.value, EventStatus.DRAFT.value]))
        .order_by(Event.start_datetime.asc())
        .limit(6)
        .all()
    )

    # Event status breakdown
    status_counts = {}
    for status_enum in EventStatus:
        count = Event.query.filter_by(status=status_enum.value).count()
        status_counts[status_enum.value] = count

    return render_template(
        "dashboard.html",
        total_events=total_events,
        total_resources=total_resources,
        active_resources=active_resources,
        pending_requests_count=pending_requests_count,
        approved_requests_count=approved_requests_count,
        total_requests_count=total_requests_count,
        pending_requests=pending_requests,
        upcoming_events=upcoming_events,
        status_counts=status_counts,
        user=current_user(),
    )
