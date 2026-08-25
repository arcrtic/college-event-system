from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.extensions import db
from app.models import Event, EventStatus, Resource, ResourceType, ResourceRequest, RequestItem, RequestStatus
from app.utils.validators import ValidationError, parse_datetime, validate_event_window
from app.utils.booking import check_suitability, check_availability, find_alternatives

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
    return render_template("requests/view.html", req=req)


@requests_bp.route("/new/<int:event_id>", methods=["GET", "POST"])
def create_request(event_id):
    event = Event.query.get_or_404(event_id)
    all_resources = Resource.query.order_by(Resource.type, Resource.name).all()
    resource_types = [t.value for t in ResourceType]

    if event.status in (EventStatus.CANCELLED.value, EventStatus.COMPLETED.value):
        flash(f"Cannot request resources for a {event.status.lower()} event.", "error")
        return redirect(url_for("events.view_event", event_id=event.id))

    if request.method == "POST":
        errors = []          # list of plain error strings shown at the top
        item_problems = []   # list of dicts: {label, reasons, alternatives} for detailed per-row feedback

        try:
            start_dt = parse_datetime(request.form.get("start_datetime"), "Start date/time")
            end_dt = parse_datetime(request.form.get("end_datetime"), "End date/time")
            validate_event_window(start_dt, end_dt)
        except ValidationError as e:
            flash(e.message, "error")
            return render_template(
                "requests/form.html", event=event, resources=all_resources,
                resource_types=resource_types, form_data=request.form,
            )

        required_types = request.form.getlist("required_type[]")
        resource_ids = request.form.getlist("resource_id[]")
        quantities = request.form.getlist("quantity[]")

        rows = list(zip(required_types, resource_ids, quantities))
        rows = [r for r in rows if r[1]]  # drop rows where no resource was picked

        if not rows:
            flash("Add at least one resource to the request.", "error")
            return render_template(
                "requests/form.html", event=event, resources=all_resources,
                resource_types=resource_types, form_data=request.form,
            )

        # Validate every row FIRST, collecting all problems, before touching
        # the database. This is what lets us show the organizer everything
        # wrong with their request in one pass instead of a frustrating
        # one-error-at-a-time loop, and guarantees we never partially
        # create a request (all-or-nothing at creation time too).
        validated_items = []
        for required_type, resource_id, qty_raw in rows:
            resource = Resource.query.get(resource_id)
            if resource is None:
                item_problems.append({"label": f"Resource #{resource_id}", "reasons": ["This resource no longer exists."], "alternatives": []})
                continue

            try:
                qty = int(qty_raw)
                if qty <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                item_problems.append({"label": resource.name, "reasons": ["Quantity must be a positive whole number."], "alternatives": []})
                continue

            reasons = check_suitability(resource, required_type, event.expected_attendance)
            reasons += check_availability(resource, start_dt, end_dt, qty)

            if reasons:
                alternatives = find_alternatives(
                    required_type, event.expected_attendance, start_dt, end_dt, qty,
                    exclude_resource_id=resource.id,
                )
                item_problems.append({"label": resource.name, "reasons": reasons, "alternatives": alternatives})
            else:
                validated_items.append((resource, qty))

        if item_problems:
            return render_template(
                "requests/form.html", event=event, resources=all_resources,
                resource_types=resource_types, form_data=request.form,
                item_problems=item_problems,
            )

        # Everything validated -- create the request and its items together.
        try:
            res_request = ResourceRequest(
                event_id=event.id, start_datetime=start_dt, end_datetime=end_dt,
                status=RequestStatus.PENDING.value,
            )
            db.session.add(res_request)
            db.session.flush()  # get res_request.id before adding items

            for resource, qty in validated_items:
                db.session.add(RequestItem(request_id=res_request.id, resource_id=resource.id, quantity=qty))

            # Submitting a request is the organizer signaling "please review
            # this" -- a Draft event moves to Pending automatically so it
            # shows up for admins without an extra manual step.
            if event.status == EventStatus.DRAFT.value:
                event.status = EventStatus.PENDING.value

            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Something went wrong creating the request. Please try again.", "error")
            return render_template(
                "requests/form.html", event=event, resources=all_resources,
                resource_types=resource_types, form_data=request.form,
            )

        flash("Resource request submitted and pending approval.", "success")
        return redirect(url_for("requests.view_request", request_id=res_request.id))

    return render_template(
        "requests/form.html", event=event, resources=all_resources,
        resource_types=resource_types, form_data=None,
    )
