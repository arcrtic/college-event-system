from flask import Blueprint, render_template, request

from app.models import AuditLog
from app.utils.auth import admin_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/audit")
@admin_required
def audit_log():
    """Admin-only trail of who approved, rejected, allocated or cancelled what."""
    action_filter = request.args.get("action", "").strip()
    user_filter = request.args.get("user", "").strip()

    query = AuditLog.query
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
    if user_filter:
        query = query.filter(AuditLog.username == user_filter)

    entries = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(200).all()

    actions = [a for (a,) in AuditLog.query.with_entities(AuditLog.action).distinct().order_by(AuditLog.action)]
    users = [u for (u,) in AuditLog.query.with_entities(AuditLog.username).distinct().order_by(AuditLog.username)]

    return render_template(
        "admin/audit.html",
        entries=entries,
        actions=actions,
        users=users,
        action_filter=action_filter,
        user_filter=user_filter,
    )
