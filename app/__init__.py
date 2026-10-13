import os
from flask import Flask, render_template

from config import Config
from app.extensions import db


def create_app(config_class=Config):
    """
    App-factory pattern instead of a single global `app = Flask(__name__)`.
    Reasons this matters for this assignment specifically:
    - Tests can spin up an app with a temp SQLite DB without touching the
      real instance/college_events.db.
    - `db.init_app(app)` (rather than binding at import time) is what lets
      app/extensions.py exist without circular imports.
    """
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)

    # Models must be imported (even though unused directly here) so that
    # SQLAlchemy's metadata knows about them before db.create_all() runs.
    # Without this import, create_all() silently creates zero tables.
    from app import models  # noqa: F401

    # Blueprints are registered here so each feature area (events,
    # resources, requests, approvals) can be built and reasoned about
    # independently, per the step-by-step plan.
    from app.routes.events import events_bp
    from app.routes.resources import resources_bp
    from app.routes.requests import requests_bp
    from app.routes.approvals import approvals_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.admin import admin_bp
    from app.utils.auth import auth_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(approvals_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)

    register_error_handlers(app)

    @app.context_processor
    def inject_role():
        from app.utils.auth import is_admin, current_role, current_user
        from app.models import ResourceRequest, RequestStatus

        admin = is_admin()
        pending_badge = 0
        if admin:
            try:
                pending_badge = ResourceRequest.query.filter_by(
                    status=RequestStatus.PENDING.value
                ).count()
            except Exception:
                db.session.rollback()
        return dict(
            is_admin=admin,
            current_role=current_role(),
            current_user=current_user(),
            pending_badge=pending_badge,
        )

    # NOTE: db.create_all() is deliberately NOT called here synchronously.
    # It used to run at this point, inside app import, which meant a slow
    # or not-yet-ready database (common right after a redeploy) could block
    # worker boot past gunicorn's 30s timeout -> SIGKILL -> app never comes
    # up at all. Schema creation now happens inside the background seed
    # thread below instead, where a slow DB just delays seeding, not the
    # whole app from starting.

    # Auto-seed on startup in a background thread. This replaces running
    # `python seed.py` manually via the Render Shell (not available on the
    # free plan). It's non-blocking so a slow/unready database never delays
    # gunicorn binding the port -- seed_data() itself is idempotent (it
    # skips seeding if data already exists, and creates the schema first
    # if it doesn't exist yet), so this is safe to run on every boot,
    # including redeploys and worker restarts.
    if os.environ.get("AUTO_SEED", "1") == "1":
        import threading

        def _seed_in_background():
            try:
                from seed import seed_data
                seed_data(app)
            except Exception as e:
                print(f"[WARN] Background seeding failed: {e}")

        threading.Thread(target=_seed_in_background, daemon=True).start()

    return app


def register_error_handlers(app):
    """
    Centralized error handling so a raw traceback is never shown to a user
    (an explicit requirement in section 9 of the assignment). Business-logic
    errors are handled at the route level with flash messages; these
    handlers are the safety net for anything unexpected (404s, 500s).
    """

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template("errors/500.html"), 500
