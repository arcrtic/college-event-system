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

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(approvals_bp)

    register_error_handlers(app)

    with app.app_context():
        db.create_all()

    return app


def register_error_handlers(app):
    """
    Centralized error handling so a raw traceback is never shown to a user
    (an explicit requirement in section 9 of the assignment). Business-logic
    errors are handled at the route level with flash messages; these
    handlers are the safety net for anything unexpected (404s, 500s).
    """

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template("errors/500.html"), 500
