from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.extensions import db
from app.models import Event, EventStatus, RequestStatus, Allocation, ResourceRequest, RequestItem, ResourceType
from app.utils.auth import admin_required, can_manage_event, current_user, ensure_can_manage_event, is_admin
from app.utils.audit import log_action
from app.utils.booking import validate_request_rows
from app.utils.validators import (
    ValidationError,
    parse_datetime,
    validate_event_window,
    validate_not_in_past,
    validate_attendance,
    require_text,
)

events_bp = Blueprint("events", __name__, url_prefix="/events")


def _build_event_from_form(form, enforce_future=False):
    """
    Shared by create and edit so both paths validate identically -- if we
    only validated on create, an edit could silently introduce an invalid
    state (e.g. end date before start date).

    Status is deliberately NOT read from this form. It used to be a raw
    dropdown anyone could set to any value (including jumping straight to
    "Approved" or "Completed"), which bypassed the whole approval
    workflow. Status is now entirely system-managed: Draft on creation,
    Pending when a resource request is submitted, Approved/Rejected via
    the approval workflow, Cancelled via the Cancel button, and Completed
    only by an admin via the explicit "Mark Completed" action.
    """
    name = require_text(form.get("name"), "Event name")
    organizer = require_text(form.get("organizer"), "Organizer")
    attendance = validate_attendance(form.get("expected_attendance"))
    start_dt = parse_datetime(form.get("start_datetime"), "Start date/time")
    end_dt = parse_datetime(form.get("end_datetime"), "End date/time")
    validate_event_window(start_dt, end_dt)
    if enforce_future:
        validate_not_in_past(start_dt)

    return {
        "name": name,
        "organizer": organizer,
        "expected_attendance": attendance,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
    }


@events_bp.route("/")
def list_events():
    """
    Filter by status, date, and/or keyword search (name or organizer).
    """
    query = Event.query

    # Organizers land on "My Events"; they may switch to the read-only campus
    # calendar (scope=all). Admins always see every event.
    user = current_user()
    scope = request.args.get("scope", "all" if is_admin() else "mine")
    if scope not in ("mine", "all"):
        scope = "mine"
    if scope == "mine":
        query = query.filter(Event.owner_id == user.id)

    search_query = request.args.get("q", "").strip()
    if search_query:
        query = query.filter(
            db.or_(
                Event.name.ilike(f"%{search_query}%"),
                Event.organizer.ilike(f"%{search_query}%"),
            )
        )

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
        search_query=search_query,
        scope=scope,
    )


@events_bp.route("/new", methods=["GET", "POST"])
def create_event():
    resource_types = [t.value for t in ResourceType]

    if request.method == "POST":
        try:
            data = _build_event_from_form(request.form, enforce_future=True)
        except ValidationError as e:
            flash(e.message, "error")
            return render_template("events/form.html", event=None, form_data=request.form, resource_types=resource_types)

        # Resources are optional at creation time -- an organizer can also
        # add them later via "Request Resources" on the event page. Rows
        # where nothing was picked (blank resource_id) are dropped.
        required_types = request.form.getlist("required_type[]")
        resource_ids = request.form.getlist("resource_id[]")
        quantities = request.form.getlist("quantity[]")
        rows = list(zip(required_types, resource_ids, quantities))
        rows = [r for r in rows if r[1]]

        validated_items, item_problems = [], []
        if rows:
            validated_items, item_problems = validate_request_rows(
                rows, data["expected_attendance"], data["start_datetime"], data["end_datetime"]
            )

        if item_problems:
            # All-or-nothing extends to event creation too: if any picked
            # resource is no longer available (it may have just been
            # booked by someone else), the event itself isn't created
            # either -- the organizer fixes the picks and resubmits,
            # rather than ending up with a half-created event with no
            # resources attached to it.
            return render_template(
                "events/form.html", event=None, form_data=request.form,
                resource_types=resource_types, item_problems=item_problems,
            )

        try:
            event = Event(status=EventStatus.DRAFT.value, owner_id=current_user().id, **data)
            db.session.add(event)
            db.session.flush()  # get event.id before creating its request

            if validated_items:
                res_request = ResourceRequest(
                    event_id=event.id,
                    start_datetime=data["start_datetime"],
                    end_datetime=data["end_datetime"],
                    status=RequestStatus.PENDING.value,
                )
                db.session.add(res_request)
                db.session.flush()
                for resource, qty in validated_items:
                    db.session.add(RequestItem(request_id=res_request.id, resource_id=resource.id, quantity=qty))
                event.status = EventStatus.PENDING.value

            log_action("event.create", "Event", event.id, f"Created '{event.name}' ({event.status})")
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Something went wrong creating the event. Please try again.", "error")
            return render_template("events/form.html", event=None, form_data=request.form, resource_types=resource_types)

        if validated_items:
            flash(f"Event '{event.name}' created with {len(validated_items)} resource(s) requested, pending approval.", "success")
        else:
            flash(f"Event '{event.name}' created.", "success")
        return redirect(url_for("events.view_event", event_id=event.id))

    return render_template("events/form.html", event=None, form_data=None, resource_types=resource_types)


@events_bp.route("/<int:event_id>")
def view_event(event_id):
    event = Event.query.get_or_404(event_id)
    return render_template("events/view.html", event=event, can_manage=can_manage_event(event))


@events_bp.route("/<int:event_id>/edit", methods=["GET", "POST"])
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    ensure_can_manage_event(event)

    if request.method == "POST":
        try:
            data = _build_event_from_form(request.form)
            for key, value in data.items():
                setattr(event, key, value)
            log_action("event.update", "Event", event.id, f"Edited '{event.name}'")
            db.session.commit()
            flash(f"Event '{event.name}' updated.", "success")
            return redirect(url_for("events.view_event", event_id=event.id))
        except ValidationError as e:
            flash(e.message, "error")
            return render_template("events/form.html", event=event, form_data=request.form)

    return render_template("events/form.html", event=event, form_data=None)


@events_bp.route("/<int:event_id>/complete", methods=["POST"])
@admin_required
def complete_event(event_id):
    """
    Marking an event Completed is a deliberate, admin-only action (not
    something that happens automatically just because the end time has
    passed) -- an admin should be able to confirm the event actually ran
    before closing it out, and a Draft/Pending event that never happened
    shouldn't silently flip to Completed.
    """
    event = Event.query.get_or_404(event_id)
    if event.status in (EventStatus.CANCELLED.value, EventStatus.COMPLETED.value):
        flash(f"Event is already {event.status.lower()}.", "error")
        return redirect(url_for("events.view_event", event_id=event.id))

    event.status = EventStatus.COMPLETED.value
    log_action("event.complete", "Event", event.id, f"Marked '{event.name}' completed")
    db.session.commit()
    flash(f"Event '{event.name}' marked Completed.", "success")
    return redirect(url_for("events.view_event", event_id=event.id))


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
    ensure_can_manage_event(event)

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
    log_action(
        "event.cancel", "Event", event.id,
        f"Cancelled '{event.name}'; {len(active_requests)} request(s) cancelled, allocations released",
    )
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
