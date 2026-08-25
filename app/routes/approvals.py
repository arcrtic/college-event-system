from flask import Blueprint, render_template, redirect, url_for, flash

from app.extensions import db
from app.models import ResourceRequest, RequestStatus, Allocation, EventStatus
from app.utils.booking import check_availability

approvals_bp = Blueprint("approvals", __name__, url_prefix="/approvals")


@approvals_bp.route("/")
def list_approvals():
    """
    The admin's queue: requests still needing a decision (Pending) and
    requests that were approved in principle but not yet locked in as
    real allocations (Approved). Split into two sections so the two
    different actions available (Approve/Reject vs. Allocate) are obvious.
    """
    pending = ResourceRequest.query.filter_by(status=RequestStatus.PENDING.value).order_by(ResourceRequest.created_at.asc()).all()
    approved = ResourceRequest.query.filter_by(status=RequestStatus.APPROVED.value).order_by(ResourceRequest.created_at.asc()).all()
    return render_template("approvals/list.html", pending=pending, approved=approved)


@approvals_bp.route("/<int:request_id>/approve", methods=["POST"])
def approve_request(request_id):
    """
    Approve is a sign-off decision, deliberately separate from Allocate.
    It does NOT create Allocation rows or re-check conflicts -- that
    happens at Allocate time, where we re-verify against whatever the
    world looks like *then* (other requests may have been approved and
    allocated in between, so re-checking here would be stale anyway).
    """
    req = ResourceRequest.query.get_or_404(request_id)
    if req.status != RequestStatus.PENDING.value:
        flash("Only pending requests can be approved.", "error")
        return redirect(url_for("approvals.list_approvals"))

    req.status = RequestStatus.APPROVED.value
    db.session.commit()
    flash(f"Request #{req.id} approved. Allocate it to lock in the resources.", "success")
    return redirect(url_for("approvals.list_approvals"))


@approvals_bp.route("/<int:request_id>/reject", methods=["POST"])
def reject_request(request_id):
    req = ResourceRequest.query.get_or_404(request_id)
    if req.status != RequestStatus.PENDING.value:
        flash("Only pending requests can be rejected.", "error")
        return redirect(url_for("approvals.list_approvals"))

    req.status = RequestStatus.REJECTED.value
    db.session.commit()
    flash(f"Request #{req.id} rejected.", "success")
    return redirect(url_for("approvals.list_approvals"))


@approvals_bp.route("/<int:request_id>/allocate", methods=["POST"])
def allocate_request(request_id):
    """
    This is where the assignment's core transactional requirement lives:
    "If an event requests multiple resources and one resource is
    unavailable, none of the requested resources should be allocated."

    We re-run check_availability() for EVERY item first, inside the same
    db.session (no commits yet). Only if every single item passes do we
    add any Allocation rows, and then we commit once at the end. If any
    item fails, we roll back and nothing changes -- the request stays
    'Approved' so the admin can see what happened and decide (reject it,
    or try allocating again later once resources free up).
    """
    req = ResourceRequest.query.get_or_404(request_id)
    if req.status != RequestStatus.APPROVED.value:
        flash("Only approved requests can be allocated.", "error")
        return redirect(url_for("approvals.list_approvals"))

    problems = []
    for item in req.items:
        reasons = check_availability(item.resource, req.start_datetime, req.end_datetime, item.quantity)
        if reasons:
            problems.extend(reasons)

    if problems:
        db.session.rollback()
        for reason in problems:
            flash(reason, "error")
        flash(
            f"Request #{req.id} could not be allocated -- no resources were locked in. "
            f"It remains Approved; you can retry later or reject it.",
            "error",
        )
        return redirect(url_for("requests.view_request", request_id=req.id))

    try:
        for item in req.items:
            db.session.add(Allocation(
                request_item_id=item.id,
                resource_id=item.resource_id,
                event_id=req.event_id,
                quantity=item.quantity,
                start_datetime=req.start_datetime,
                end_datetime=req.end_datetime,
                is_active=True,
            ))
        req.status = RequestStatus.ALLOCATED.value
        if req.event.status != EventStatus.APPROVED.value:
            req.event.status = EventStatus.APPROVED.value
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Something went wrong during allocation. No resources were locked in. Please try again.", "error")
        return redirect(url_for("requests.view_request", request_id=req.id))

    flash(f"Request #{req.id} allocated -- resources are now locked in.", "success")
    return redirect(url_for("requests.view_request", request_id=req.id))


@approvals_bp.route("/<int:request_id>/cancel", methods=["POST"])
def cancel_request(request_id):
    """
    Cancelling an Approved (not yet allocated) or Allocated request.
    For Allocated requests, this is the "cancelled allocations release
    the resource" requirement: we deactivate the Allocation rows rather
    than deleting them (keeps a history of what was once booked), and an
    inactive Allocation is invisible to booked_quantity(), so the units
    become available again immediately.
    """
    req = ResourceRequest.query.get_or_404(request_id)
    if req.status not in (RequestStatus.APPROVED.value, RequestStatus.ALLOCATED.value):
        flash("Only approved or allocated requests can be cancelled.", "error")
        return redirect(url_for("requests.view_request", request_id=req.id))

    # Deactivate all allocations tied to this request's items.
    item_ids = [item.id for item in req.items]
    if item_ids:
        Allocation.query.filter(Allocation.request_item_id.in_(item_ids)).update(
            {"is_active": False}, synchronize_session=False
        )

    req.status = RequestStatus.CANCELLED.value
    db.session.commit()
    flash(f"Request #{req.id} cancelled. Any allocated resources have been released.", "success")
    return redirect(url_for("requests.view_request", request_id=req.id))
