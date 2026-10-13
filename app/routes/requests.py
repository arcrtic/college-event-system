from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.extensions import db
from app.models import Event, EventStatus, ResourceType, ResourceRequest, RequestItem, RequestStatus, Allocation
from app.utils.validators import ValidationError, parse_datetime, validate_event_window
from app.utils.booking import validate_request_rows

requests_bp = Blueprint("requests", __name__, url_prefix="/requests")


@requests_bp.route("/")
def list_requests():
    status_filter = request.args.get("status", "")
    query = ResourceRequest.query
    if status_filter:
        query = query.filter(ResourceRequest.status == status_filter)
    reqs = query.order_by(ResourceRequest.created_at.desc()).all()
    return render_template(
        "requests/list.html",
        requests=reqs,
        statuses=[s.value for s in RequestStatus],
        status_filter=status_filter,
    )


@requests_bp.route("/<int:request_id>")
def view_request(request_id):
    req = ResourceRequest.query.get_or_404(request_id)
    # Fetch active allocations if allocated
    allocations = Allocation.query.filter(
        Allocation.request_item_id.in_([item.id for item in req.items])
    ).all() if req.items else []
    return render_template("requests/view.html", req=req, allocations=allocations)


@requests_bp.route("/new", methods=["GET", "POST"])
@requests_bp.route("/new/<int:event_id>", methods=["GET", "POST"])
def create_request(event_id=None):
    # Available events for requesting resources (Draft, Pending, Approved, or Rejected).
    # Rejected events are included so organizers can resubmit after a rejection.
    available_events = Event.query.filter(
        Event.status.in_([
            EventStatus.DRAFT.value,
            EventStatus.PENDING.value,
            EventStatus.APPROVED.value,
            EventStatus.REJECTED.value,
        ])
    ).order_by(Event.start_datetime.asc()).all()

    selected_event = None
    if event_id:
        selected_event = Event.query.get_or_404(event_id)
    elif request.method == "POST":
        ev_id = request.form.get("event_id")
        if ev_id:
            selected_event = Event.query.get(ev_id)

    resource_types = [t.value for t in ResourceType]

    if selected_event and selected_event.status in (EventStatus.CANCELLED.value, EventStatus.COMPLETED.value):
        flash(f"Cannot request resources for a {selected_event.status.lower()} event.", "error")
        return redirect(url_for("events.view_event", event_id=selected_event.id))

    if request.method == "POST":
        if not selected_event:
            flash("Please select an event for this resource request.", "error")
            return render_template(
                "requests/form.html",
                event=selected_event,
                available_events=available_events,
                resource_types=resource_types,
                form_data=request.form,
            )

        try:
            start_dt = parse_datetime(request.form.get("start_datetime"), "Start date/time")
            end_dt = parse_datetime(request.form.get("end_datetime"), "End date/time")
            validate_event_window(start_dt, end_dt)
        except ValidationError as e:
            flash(e.message, "error")
            return render_template(
                "requests/form.html",
                event=selected_event,
                available_events=available_events,
                resource_types=resource_types,
                form_data=request.form,
            )

        required_types = request.form.getlist("required_type[]")
        resource_ids = request.form.getlist("resource_id[]")
        quantities = request.form.getlist("quantity[]")

        rows = list(zip(required_types, resource_ids, quantities))
        rows = [r for r in rows if r[1]]  # drop rows where no resource was picked

        if not rows:
            flash("Please add at least one resource to the request.", "error")
            return render_template(
                "requests/form.html",
                event=selected_event,
                available_events=available_events,
                resource_types=resource_types,
                form_data=request.form,
            )

        # Validate every row and collect all suitability and availability issues
        validated_items, item_problems = validate_request_rows(
            rows, selected_event.expected_attendance, start_dt, end_dt
        )

        if item_problems:
            return render_template(
                "requests/form.html",
                event=selected_event,
                available_events=available_events,
                resource_types=resource_types,
                form_data=request.form,
                item_problems=item_problems,
            )

        # Atomic creation of request + items
        try:
            res_request = ResourceRequest(
                event_id=selected_event.id,
                start_datetime=start_dt,
                end_datetime=end_dt,
                status=RequestStatus.PENDING.value,
            )
            db.session.add(res_request)
            db.session.flush()

            for resource, qty in validated_items:
                db.session.add(
                    RequestItem(request_id=res_request.id, resource_id=resource.id, quantity=qty)
                )

            # Move Draft or Rejected events to Pending upon request submission.
            # Rejected events re-enter the approval queue when the organizer
            # submits a new request after addressing the admin's concerns.
            if selected_event.status in (EventStatus.DRAFT.value, EventStatus.REJECTED.value):
                selected_event.status = EventStatus.PENDING.value

            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Failed to submit resource request. Please try again.", "error")
            return render_template(
                "requests/form.html",
                event=selected_event,
                available_events=available_events,
                resource_types=resource_types,
                form_data=request.form,
            )

        flash("Resource request submitted successfully and is now pending approval.", "success")
        return redirect(url_for("requests.view_request", request_id=res_request.id))

    return render_template(
        "requests/form.html",
        event=selected_event,
        available_events=available_events,
        resource_types=resource_types,
        form_data=None,
    )
