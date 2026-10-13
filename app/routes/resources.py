from datetime import datetime, time
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from app.extensions import db
from app.models import Resource, ResourceType, Allocation
from app.utils.validators import ValidationError, require_text, parse_datetime
from app.utils.booking import booked_quantity, find_alternatives, overlaps
from app.utils.auth import admin_required
from app.utils.audit import log_action

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
    Shows active and inactive resources with filtering by type, status, and search query.
    """
    type_filter = request.args.get("type", "")
    status_filter = request.args.get("status", "")
    search_query = request.args.get("q", "").strip()

    query = Resource.query

    if type_filter:
        query = query.filter(Resource.type == type_filter)

    if status_filter == "active":
        query = query.filter(Resource.is_active.is_(True))
    elif status_filter == "inactive":
        query = query.filter(Resource.is_active.is_(False))

    if search_query:
        query = query.filter(Resource.name.ilike(f"%{search_query}%"))

    resources = query.order_by(Resource.is_active.desc(), Resource.name.asc()).all()
    return render_template(
        "resources/list.html",
        resources=resources,
        types=[t.value for t in ResourceType],
        type_filter=type_filter,
        status_filter=status_filter,
        search_query=search_query,
    )


@resources_bp.route("/new", methods=["GET", "POST"])
@admin_required
def create_resource():
    if request.method == "POST":
        try:
            data = _build_resource_from_form(request.form)
            resource = Resource(**data)
            db.session.add(resource)
            db.session.flush()
            log_action("resource.create", "Resource", resource.id, f"Added {resource.type} '{resource.name}'")
            db.session.commit()
            flash(f"Resource '{resource.name}' added successfully.", "success")
            return redirect(url_for("resources.list_resources"))
        except ValidationError as e:
            flash(e.message, "error")
            return render_template("resources/form.html", resource=None, types=[t.value for t in ResourceType], form_data=request.form)

    return render_template("resources/form.html", resource=None, types=[t.value for t in ResourceType], form_data=None)


@resources_bp.route("/<int:resource_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)

    if request.method == "POST":
        try:
            data = _build_resource_from_form(request.form)
            for key, value in data.items():
                setattr(resource, key, value)
            log_action("resource.update", "Resource", resource.id, f"Edited '{resource.name}'")
            db.session.commit()
            flash(f"Resource '{resource.name}' updated successfully.", "success")
            return redirect(url_for("resources.list_resources"))
        except ValidationError as e:
            flash(e.message, "error")
            return render_template("resources/form.html", resource=resource, types=[t.value for t in ResourceType], form_data=request.form)

    return render_template("resources/form.html", resource=resource, types=[t.value for t in ResourceType], form_data=None)


@resources_bp.route("/<int:resource_id>/toggle", methods=["POST"])
@admin_required
def toggle_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    resource.is_active = not resource.is_active
    state = "activated" if resource.is_active else "deactivated"
    log_action(f"resource.{state}", "Resource", resource.id, f"{state.capitalize()} '{resource.name}'")
    db.session.commit()
    flash(f"Resource '{resource.name}' {state}.", "success")
    return redirect(url_for("resources.list_resources"))


@resources_bp.route("/availability")
def availability():
    """
    Shows live availability of resources for a selected date or exact datetime window,
    along with any active bookings/allocations.
    """
    start_dt = end_dt = None
    rows = []
    error = None

    date_raw = request.args.get("date", "")
    start_raw = request.args.get("start_datetime", "")
    end_raw = request.args.get("end_datetime", "")

    # Priority 1: Start and end datetime provided
    if start_raw and end_raw:
        try:
            start_dt = parse_datetime(start_raw, "Start date/time")
            end_dt = parse_datetime(end_raw, "End date/time")
            if end_dt <= start_dt:
                raise ValidationError("End time must be after start time.")
        except ValidationError as e:
            error = e.message
    # Priority 2: Single date provided (covers the full 24h day)
    elif date_raw:
        try:
            selected_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
            start_dt = datetime.combine(selected_date, time(0, 0, 0))
            end_dt = datetime.combine(selected_date, time(23, 59, 59))
        except ValueError:
            error = "Invalid date format."

    resources = Resource.query.filter_by(is_active=True).order_by(Resource.type, Resource.name).all()

    for resource in resources:
        allocations_list = []
        if start_dt and end_dt and not error:
            booked = booked_quantity(resource.id, start_dt, end_dt)
            free = max(0, resource.total_quantity - booked)
            
            # Fetch active overlapping allocations for details display
            active_allocs = Allocation.query.filter(
                Allocation.resource_id == resource.id,
                Allocation.is_active.is_(True),
            ).all()
            for alloc in active_allocs:
                if overlaps(alloc.start_datetime, alloc.end_datetime, start_dt, end_dt):
                    allocations_list.append(alloc)
        else:
            booked = None
            free = None

        rows.append({
            "resource": resource,
            "booked": booked,
            "free": free,
            "allocations": allocations_list,
        })

    return render_template(
        "resources/availability.html",
        rows=rows,
        date_raw=date_raw,
        start_raw=start_raw,
        end_raw=end_raw,
        error=error,
        start_dt=start_dt,
        end_dt=end_dt,
        checked=bool(start_dt and end_dt and not error),
    )


@resources_bp.route("/available.json")
def available_resources_json():
    """
    JSON API for dynamic dropdown populating:
    Returns suitable, active, and unbooked resources for a given type, time window,
    attendance, and quantity.
    """
    required_type = request.args.get("type", "")
    start_raw = request.args.get("start", "")
    end_raw = request.args.get("end", "")
    attendance_raw = request.args.get("attendance", "")
    qty_raw = request.args.get("qty", "1")

    valid_types = {t.value for t in ResourceType}
    if required_type not in valid_types or not start_raw or not end_raw:
        return jsonify([])

    try:
        start_dt = parse_datetime(start_raw, "Start")
        end_dt = parse_datetime(end_raw, "End")
        if end_dt <= start_dt:
            return jsonify([])
    except ValidationError:
        return jsonify([])

    attendance = None
    if attendance_raw.strip():
        try:
            attendance = int(attendance_raw)
        except ValueError:
            attendance = None

    try:
        qty = max(1, int(qty_raw))
    except (TypeError, ValueError):
        qty = 1

    candidates = find_alternatives(required_type, attendance, start_dt, end_dt, qty, limit=50)
    return jsonify([
        {
            "id": r.id,
            "name": r.name,
            "capacity": r.capacity,
            "total_quantity": r.total_quantity,
        }
        for r in candidates
    ])
