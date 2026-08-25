from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.extensions import db
from app.models import Resource, ResourceType
from app.utils.validators import ValidationError, require_text, parse_datetime
from app.utils.booking import booked_quantity

resources_bp = Blueprint("resources", __name__, url_prefix="/resources")


def _build_resource_from_form(form):
    name = require_text(form.get("name"), "Resource name")

    rtype = form.get("type")
    valid_types = {t.value for t in ResourceType}
    if rtype not in valid_types:
        raise ValidationError("Invalid resource type.")

    capacity_raw = form.get("capacity", "").strip()
    capacity = None
    if capacity_raw:
        try:
            capacity = int(capacity_raw)
        except ValueError:
            raise ValidationError("Capacity must be a whole number.")
        if capacity <= 0:
            raise ValidationError("Capacity must be a positive number.")

    qty_raw = form.get("total_quantity", "1").strip()
    try:
        total_quantity = int(qty_raw) if qty_raw else 1
    except ValueError:
        raise ValidationError("Total quantity must be a whole number.")
    if total_quantity <= 0:
        raise ValidationError("Total quantity must be at least 1.")

    return {"name": name, "type": rtype, "capacity": capacity, "total_quantity": total_quantity}


@resources_bp.route("/")
def list_resources():
    """
    Shows active and inactive resources together (inactive ones are
    visually muted) rather than hiding inactive resources entirely --
    an admin needs to see what's been deactivated in order to reactivate it.
    """
    type_filter = request.args.get("type", "")
    query = Resource.query
    if type_filter:
        query = query.filter(Resource.type == type_filter)

    resources = query.order_by(Resource.is_active.desc(), Resource.name.asc()).all()
    return render_template(
        "resources/list.html",
        resources=resources,
        types=[t.value for t in ResourceType],
        type_filter=type_filter,
    )


@resources_bp.route("/new", methods=["GET", "POST"])
def create_resource():
    if request.method == "POST":
        try:
            data = _build_resource_from_form(request.form)
            resource = Resource(**data)
            db.session.add(resource)
            db.session.commit()
            flash(f"Resource '{resource.name}' added.", "success")
            return redirect(url_for("resources.list_resources"))
        except ValidationError as e:
            flash(e.message, "error")
            return render_template("resources/form.html", resource=None, types=[t.value for t in ResourceType], form_data=request.form)

    return render_template("resources/form.html", resource=None, types=[t.value for t in ResourceType], form_data=None)


@resources_bp.route("/<int:resource_id>/edit", methods=["GET", "POST"])
def edit_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)

    if request.method == "POST":
        try:
            data = _build_resource_from_form(request.form)
            for key, value in data.items():
                setattr(resource, key, value)
            db.session.commit()
            flash(f"Resource '{resource.name}' updated.", "success")
            return redirect(url_for("resources.list_resources"))
        except ValidationError as e:
            flash(e.message, "error")
            return render_template("resources/form.html", resource=resource, types=[t.value for t in ResourceType], form_data=request.form)

    return render_template("resources/form.html", resource=resource, types=[t.value for t in ResourceType], form_data=None)


@resources_bp.route("/<int:resource_id>/toggle", methods=["POST"])
def toggle_resource(resource_id):
    """
    Deactivating a resource (e.g. it broke, or is under maintenance) does
    NOT touch any existing Allocation rows -- a resource already booked
    for an approved event stays booked. Deactivation only prevents it from
    being selected in *new* resource requests (enforced in the booking
    logic step). This mirrors how a real admin would use this toggle.
    """
    resource = Resource.query.get_or_404(resource_id)
    resource.is_active = not resource.is_active
    db.session.commit()
    state = "activated" if resource.is_active else "deactivated"
    flash(f"Resource '{resource.name}' {state}.", "success")
    return redirect(url_for("resources.list_resources"))


@resources_bp.route("/availability")
def availability():
    """
    Section 8 of the assignment explicitly asks for a "Resource
    availability" page distinct from the plain resource list. The list
    page (list_resources) shows what exists and whether it's active; this
    page answers the more useful question an organizer actually has:
    "how many units of each resource are free during a specific window?"

    It reuses booked_quantity() from utils/booking.py -- the exact same
    function the request-creation and allocation flows use for conflict
    checking -- so this page can never disagree with what the booking
    logic will actually decide.
    """
    start_dt = end_dt = None
    rows = []
    error = None

    start_raw = request.args.get("start_datetime", "")
    end_raw = request.args.get("end_datetime", "")

    if start_raw and end_raw:
        try:
            start_dt = parse_datetime(start_raw, "Start date/time")
            end_dt = parse_datetime(end_raw, "End date/time")
            if end_dt <= start_dt:
                raise ValidationError("End time must be after the start time.")
        except ValidationError as e:
            error = e.message

    resources = Resource.query.filter_by(is_active=True).order_by(Resource.type, Resource.name).all()

    for resource in resources:
        if start_dt and end_dt and not error:
            booked = booked_quantity(resource.id, start_dt, end_dt)
            free = resource.total_quantity - booked
        else:
            booked = None
            free = None
        rows.append({"resource": resource, "booked": booked, "free": free})

    return render_template(
        "resources/availability.html",
        rows=rows, start_raw=start_raw, end_raw=end_raw, error=error,
        checked=bool(start_dt and end_dt and not error),
    )
