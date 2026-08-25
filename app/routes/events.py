from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.extensions import db
from app.models import Event, EventStatus, RequestStatus, Allocation
from app.utils.validators import (
    ValidationError,
    parse_datetime,
    validate_event_window,
    validate_attendance,
    require_text,
)

events_bp = Blueprint("events", __name__, url_prefix="/events")


def _build_event_from_form(form):
    """
    Shared by create and edit so both paths validate identically -- if we
    only validated on create, an edit could silently introduce an invalid
    state (e.g. end date before start date).
    """
    name = require_text(form.get("name"), "Event name")
    organizer = require_text(form.get("organizer"), "Organizer")
    attendance = validate_attendance(form.get("expected_attendance"))
    start_dt = parse_datetime(form.get("start_datetime"), "Start date/time")
    end_dt = parse_datetime(form.get("end_datetime"), "End date/time")
    validate_event_window(start_dt, end_dt)

    status = form.get("status") or EventStatus.DRAFT.value
    valid_statuses = {s.value for s in EventStatus}
    if status not in valid_statuses:
        raise ValidationError("Invalid event status.")

    return {
        "name": name,
        "organizer": organizer,
        "expected_attendance": attendance,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "status": status,
    }


@events_bp.route("/")
def list_events():
    """
    Filter by status and/or date, per the assignment's requirement.
    Filters are applied only when present in the querystring so the
    default view (no filters) shows everything.
    """
    query = Event.query

    status_filter = request.args.get("status", "")
    if status_filter:
        query = query.filter(Event.status == status_filter)

    date_filter = request.args.get("date", "")
    if date_filter:
        try:
            day = datetime.strptime(date_filter, "%Y-%m-%d").date()
            query = query.filter(db.func.date(Event.start_datetime) == day.isoformat())
        except ValueError:
            flash("Invalid date filter ignored.", "error")

    events = query.order_by(Event.start_datetime.asc()).all()
    return render_template(
        "events/list.html",
        events=events,
        statuses=[s.value for s in EventStatus],
        status_filter=status_filter,
        date_filter=date_filter,
    )


@events_bp.route("/new", methods=["GET", "POST"])
def create_event():
    if request.method == "POST":
        try:
            data = _build_event_from_form(request.form)
            event = Event(**data)
            db.session.add(event)
            db.session.commit()
            flash(f"Event '{event.name}' created.", "success")
            return redirect(url_for("events.list_events"))
        except ValidationError as e:
            flash(e.message, "error")
            return render_template("events/form.html", event=None, statuses=[s.value for s in EventStatus], form_data=request.form)

    return render_template("events/form.html", event=None, statuses=[s.value for s in EventStatus], form_data=None)


@events_bp.route("/<int:event_id>")
def view_event(event_id):
    event = Event.query.get_or_404(event_id)
    return render_template("events/view.html", event=event)


@events_bp.route("/<int:event_id>/edit", methods=["GET", "POST"])
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)

    if request.method == "POST":
        try:
            data = _build_event_from_form(request.form)
            for key, value in data.items():
                setattr(event, key, value)
            db.session.commit()
            flash(f"Event '{event.name}' updated.", "success")
            return redirect(url_for("events.view_event", event_id=event.id))
        except ValidationError as e:
            flash(e.message, "error")
            return render_template("events/form.html", event=event, statuses=[s.value for s in EventStatus], form_data=request.form)

    return render_template("events/form.html", event=event, statuses=[s.value for s in EventStatus], form_data=None)


@events_bp.route("/<int:event_id>/cancel", methods=["POST"])
def cancel_event(event_id):
    """
    Cancelling an event is a status change, not a delete -- historical
    record is kept. But an event isn't cancelled in isolation: any of its
    resource requests that are still Pending, Approved, or Allocated no
    longer make sense once the event itself is cancelled, so we cascade
    the cancellation to them too. For any that were Allocated, this also
    deactivates their Allocation rows, which is what actually frees the
    resource -- otherwise a directly-cancelled event would leave its
    resources permanently locked even though "cancelled allocations
    release the resource" is a hard requirement (see approvals.py for the
    same release logic used when a request is cancelled directly).
    """
    event = Event.query.get_or_404(event_id)

    active_requests = [
        req for req in event.requests
        if req.status in (RequestStatus.PENDING.value, RequestStatus.APPROVED.value, RequestStatus.ALLOCATED.value)
    ]
    for req in active_requests:
        item_ids = [item.id for item in req.items]
        if item_ids:
            Allocation.query.filter(Allocation.request_item_id.in_(item_ids)).update(
                {"is_active": False}, synchronize_session=False
            )
        req.status = RequestStatus.CANCELLED.value

    event.status = EventStatus.CANCELLED.value
    db.session.commit()

    if active_requests:
        flash(
            f"Event '{event.name}' cancelled. {len(active_requests)} associated resource "
            f"request(s) were also cancelled and any allocated resources released.",
            "success",
        )
    else:
        flash(f"Event '{event.name}' cancelled.", "success")
    return redirect(url_for("events.view_event", event_id=event.id))
