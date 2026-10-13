"""
Lightweight audit trail. Call `log_action(...)` BEFORE the caller's
`db.session.commit()` so the log entry is saved atomically with the change
it describes (and is rolled back with it if the change fails).
"""
from app.extensions import db
from app.models import AuditLog


def log_action(action, entity_type, entity_id=None, details=""):
    from app.utils.auth import current_user

    user = current_user()
    db.session.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else "system",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=(details or "")[:500],
        )
    )
