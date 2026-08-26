"""
The core business logic of the whole system lives here, deliberately kept
OUT of the route handlers, so it can be:
  (a) unit-tested without going through Flask's request/response cycle, and
  (b) reused identically at both request-creation time and approval time
      (the assignment requires availability to be re-verified at approval,
      since time has passed and other requests may have been approved in
      the meantime).
"""
from app.models import Resource, Allocation


def overlaps(start_a, end_a, start_b, end_b):
    """
    Two time windows overlap iff each starts before the other ends.
    Using strict '<' (not '<=') is what makes back-to-back bookings OK:
    Auditorium 10:00-14:00 booked, then 14:00-16:00 requested -> allowed,
    because 14:00 is not < 14:00. This matches the assignment's example
    exactly (2:00 PM - 4:00 PM after a 10:00 AM - 2:00 PM booking = Allow).
    """
    return start_a < end_b and start_b < end_a


def booked_quantity(resource_id, start_dt, end_dt, exclude_allocation_id=None):
    """
    Sums how many units of `resource_id` are already allocated during any
    window that overlaps [start_dt, end_dt). Only ACTIVE allocations count
    -- a cancelled allocation releases its units immediately, which is
    exactly the "cancelled allocations release the resource" requirement.
    """
    query = Allocation.query.filter(
        Allocation.resource_id == resource_id,
        Allocation.is_active.is_(True),
    )
    if exclude_allocation_id:
        query = query.filter(Allocation.id != exclude_allocation_id)

    total = 0
    for alloc in query.all():
        if overlaps(alloc.start_datetime, alloc.end_datetime, start_dt, end_dt):
            total += alloc.quantity
    return total


def check_suitability(resource, required_type, expected_attendance):
    """
    Returns a list of human-readable reasons the resource is NOT suitable.
    An empty list means it's suitable. Returning reasons (rather than
    raising on the first failure) lets the UI show everything wrong with a
    pick in one pass, instead of one-error-at-a-time.
    """
    reasons = []
    if not resource.is_active:
        reasons.append(f"'{resource.name}' is inactive.")
    if resource.type != required_type:
        reasons.append(f"'{resource.name}' is a {resource.type}, not a {required_type}.")
    if resource.capacity is not None and expected_attendance is not None:
        if expected_attendance > resource.capacity:
            reasons.append(
                f"'{resource.name}' capacity ({resource.capacity}) is below "
                f"expected attendance ({expected_attendance})."
            )
    return reasons


def check_availability(resource, start_dt, end_dt, requested_qty, exclude_allocation_id=None):
    """
    Returns a list of reasons the resource can't supply `requested_qty`
    units during the window. Empty list = available.
    """
    reasons = []
    if requested_qty > resource.total_quantity:
        reasons.append(
            f"'{resource.name}' only has {resource.total_quantity} unit(s) total; "
            f"{requested_qty} requested."
        )
        return reasons  # no point checking bookings if we already need too many

    already_booked = booked_quantity(resource.id, start_dt, end_dt, exclude_allocation_id)
    remaining = resource.total_quantity - already_booked
    if requested_qty > remaining:
        reasons.append(
            f"'{resource.name}' has only {remaining} of {resource.total_quantity} unit(s) "
            f"free for that time window ({requested_qty} requested)."
        )
    return reasons


def find_alternatives(required_type, expected_attendance, start_dt, end_dt, requested_qty,
                       exclude_resource_id=None, limit=3):
    """
    Suggests other resources that ARE suitable and available, per section 6
    of the assignment. Selection rule (kept simple and explainable):
      1. Same resource type as requested (a Projector can't substitute for
         an Auditorium).
      2. Active.
      3. Capacity >= expected attendance, if the resource has a capacity.
      4. Enough free units for the requested quantity in that exact window.
      5. Among the survivors, prefer the SMALLEST capacity that still fits
         -- i.e. don't suggest a 1000-seat hall for a 50-person workshop
         when a 100-seat room is free. Resources with no capacity concept
         (mics, cameras) are simply not over/under-sized, so they sort by
         name instead.
    """
    candidates = Resource.query.filter(
        Resource.type == required_type,
        Resource.is_active.is_(True),
    )
    if exclude_resource_id:
        candidates = candidates.filter(Resource.id != exclude_resource_id)

    suitable = []
    for resource in candidates.all():
        if resource.capacity is not None and expected_attendance is not None:
            if expected_attendance > resource.capacity:
                continue
        if check_availability(resource, start_dt, end_dt, requested_qty):
            continue  # not enough free units
        suitable.append(resource)

    suitable.sort(key=lambda r: (r.capacity if r.capacity is not None else 0, r.name))
    return suitable[:limit]


def validate_request_rows(rows, expected_attendance, start_dt, end_dt):
    """
    Shared by resource-request creation AND the "resources needed" section
    on event creation, so both entry points enforce identical rules
    instead of two hand-maintained copies of the same checks.

    `rows` is a list of (required_type, resource_id, quantity_raw) tuples,
    already stripped of rows where nothing was picked.

    Returns (validated_items, item_problems):
      - validated_items: [(Resource, qty), ...] ready to save.
      - item_problems: [{label, reasons, alternatives}, ...] for anything
        that failed -- collected across ALL rows in one pass (not just the
        first failure) so the UI can show everything wrong at once, and
        so the caller can enforce all-or-nothing: if item_problems is
        non-empty, nothing should be saved.
    """
    validated_items = []
    item_problems = []

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

        reasons = check_suitability(resource, required_type, expected_attendance)
        reasons += check_availability(resource, start_dt, end_dt, qty)

        if reasons:
            alternatives = find_alternatives(
                required_type, expected_attendance, start_dt, end_dt, qty,
                exclude_resource_id=resource.id,
            )
            item_problems.append({"label": resource.name, "reasons": reasons, "alternatives": alternatives})
        else:
            validated_items.append((resource, qty))

    return validated_items, item_problems
