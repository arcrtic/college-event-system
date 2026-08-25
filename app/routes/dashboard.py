from flask import Blueprint, render_template

from app.models import Event, ResourceRequest

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    """
    Simple landing page. Full dashboard stats will be revisited if needed,
    but for now it just gives quick counts + links so every feature area
    is reachable from one place.
    """
    upcoming_events = (
        Event.query.filter(Event.status.in_(["Pending", "Approved"]))
        .order_by(Event.start_datetime.asc())
        .limit(5)
        .all()
    )
    pending_requests_count = ResourceRequest.query.filter_by(status="Pending").count()
    return render_template(
        "dashboard.html",
        upcoming_events=upcoming_events,
        pending_requests_count=pending_requests_count,
    )
