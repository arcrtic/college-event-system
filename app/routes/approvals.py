from flask import Blueprint, render_template, redirect, url_for, flash, request

from app.extensions import db
from app.models import ResourceRequest, RequestStatus, Allocation, EventStatus
from app.utils.booking import check_availability
from app.utils.auth import admin_required

approvals_bp = Blueprint("approvals", __name__, url_prefix="/approvals")


@approvals_bp.route("/")
@admin_required
def list_approvals():
    """
    Central Admin Approvals Hub:
    1. Pending review (awaiting sign-off)
    2. Approved (awaiting resource allocation / lock-in)
    3. Allocated (actively allocated resources, can be released)
    """
    pending = (
        ResourceRequest.query.filter_by(status=RequestStatus.PENDING.value)
        .order_by(ResourceRequest.created_at.asc())
        .all()
    )
    approved = (
        ResourceRequest.query.filter_by(status=RequestStatus.APPROVED.value)
        .order_by(ResourceRequest.created_at.asc())
        .all()
    )
    allocated = (
        ResourceRequest.query.filter_by(status=RequestStatus.ALLOCATED.value)
        .order_by(ResourceRequest.created_at.desc())
        .limit(15)
        .all()
    )
    return render_template(
        "approvals/list.html",
        pending=pending,
        approved=approved,
        allocated=allocated,
    )


@approvals_bp.route("/<int:request_id>/approve", methods=["POST"])
@admin_required
def approve_request(request_id):
    req = ResourceRequest.query.get_or_404(request_id)
    if req.status != RequestStatus.PENDING.value:
        flash("Only pending requests can be approved.", "error")
        return redirect(request.referrer or url_for("approvals.list_approvals"))

    req.status = RequestStatus.APPROVED.value
    db.session.commit()
    flash(f"Request #{req.id} approved. Proceed to Allocate to lock in resources.", "success")
    return redirect(request.referrer or url_for("approvals.list_approvals"))


@approvals_bp.route("/<int:request_id>/reject", methods=["POST"])
@admin_required
def reject_request(request_id):
    req = ResourceRequest.query.get_or_404(request_id)
    if req.status != RequestStatus.PENDING.value:
        flash("Only pending requests can be rejected.", "error")
        return redirect(request.referrer or url_for("approvals.list_approvals"))

    req.status = RequestStatus.REJECTED.value
    db.session.commit()
    flash(f"Request #{req.id} has been rejected.", "success")
    return redirect(request.referrer or url_for("approvals.list_approvals"))


@approvals_bp.route("/<int:request_id>/allocate", methods=["POST"])
@admin_required
def allocate_request(request_id):
    """
    All-or-Nothing Transactional Allocation:
    Re-verifies real-time availability for EVERY requested item before locking in any resource.
    If ANY single item is unavailable, the entire transaction is aborted with rollback.
    """
    req = ResourceRequest.query.get_or_404(request_id)
    if req.status != RequestStatus.APPROVED.value:
        flash("Only approved requests can be allocated.", "error")
        return redirect(request.referrer or url_for("approvals.list_approvals"))

    # Pre-flight availability check for all items
    problems = []
    for item in req.items:
        reasons = check_availability(item.resource, req.start_datetime, req.end_datetime, item.quantity)
        if reasons:
            problems.extend(reasons)

    if problems:
        db.session.rollback()
        for reason in problems:
            flash(f"Allocation conflict: {reason}", "error")
        flash(
            f"Request #{req.id} could not be allocated due to resource conflicts. "
            f"Zero resources were locked in (All-or-Nothing rule). You may retry later or suggest alternatives.",
            "error",
        )
        return redirect(request.referrer or url_for("requests.view_request", request_id=req.id))

    # All items available -> atomic allocation
    try:
        for item in req.items:
            db.session.add(
                Allocation(
                    request_item_id=item.id,
                    resource_id=item.resource_id,
                    event_id=req.event_id,
                    quantity=item.quantity,
                    start_datetime=req.start_datetime,
                    end_datetime=req.end_datetime,
                    is_active=True,
                )
            )
        req.status = RequestStatus.ALLOCATED.value
        if req.event.status != EventStatus.APPROVED.value:
            req.event.status = EventStatus.APPROVED.value

        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Database error occurred during allocation. Zero resources were locked in.", "error")
        return redirect(request.referrer or url_for("requests.view_request", request_id=req.id))

    flash(f"Request #{req.id} successfully allocated. All resources are now locked in.", "success")
    return redirect(request.referrer or url_for("requests.view_request", request_id=req.id))


@approvals_bp.route("/<int:request_id>/cancel", methods=["POST"])
@admin_required
def cancel_request(request_id):
    """
    Cancelling an Approved or Allocated request:
    Soft-deactivates Allocation rows, immediately freeing resource capacity.
    """
    req = ResourceRequest.query.get_or_404(request_id)
    if req.status not in (RequestStatus.APPROVED.value, RequestStatus.ALLOCATED.value):
        flash("Only approved or allocated requests can be cancelled.", "error")
        return redirect(request.referrer or url_for("requests.view_request", request_id=req.id))

    # Deactivate active allocations
    item_ids = [item.id for item in req.items]
    if item_ids:
        Allocation.query.filter(Allocation.request_item_id.in_(item_ids)).update(
            {"is_active": False}, synchronize_session=False
        )

    req.status = RequestStatus.CANCELLED.value
    db.session.commit()
    flash(f"Request #{req.id} cancelled. Any locked resources have been released.", "success")
    return redirect(request.referrer or url_for("requests.view_request", request_id=req.id))
