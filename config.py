import os
from datetime import timedelta
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


class Config:
    """
    Central place for all configuration.
    Reading from environment variables (with safe fallbacks) means the same
    codebase can run locally, in CI, or on a host like Render/Railway without
    code changes -- only the .env file changes.
    """
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    _db_url = os.environ.get(
        'DATABASE_URL',
        f"sqlite:///{os.path.join(basedir, 'instance', 'college_events.db')}"
    )
    # Render/Heroku/Railway-style managed Postgres add-ons hand out URLs
    # starting with "postgres://" or "postgresql://". SQLAlchemy 2.1+
    # defaults to the psycopg3 driver when it sees "postgresql://", but we
    # only have psycopg2-binary installed. Explicitly specifying the
    # "postgresql+psycopg2://" dialect+driver string forces the correct
    # driver regardless of SQLAlchemy version.
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif _db_url.startswith("postgresql://"):
        _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Without this, a Postgres host that's slow to accept connections (e.g.
    # a free-tier instance still spinning up) can make psycopg2 hang for a
    # very long time with no feedback. Fail fast instead so retry loops
    # (see seed.py) actually behave like retries instead of one long hang.
    if _db_url.startswith("postgresql+psycopg2://"):
        SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"connect_timeout": 5}}

    # Password given to the seeded `admin` account the first time it is created
    # (see seed.py). After that, the password lives only as a hash in the DB.
    ADMIN_PASSCODE = os.environ.get('ADMIN_PASSCODE', 'admin123')

    # When "1", the sign-in page shows the demo accounts' credentials. Meant for
    # demos/assignment review only -- leave unset in a real deployment.
    SHOW_DEMO_LOGIN = os.environ.get('SHOW_DEMO_LOGIN', '0') == '1'

    # Allow visitors to self-register (always as organizers, never admins).
    ALLOW_REGISTRATION = os.environ.get('ALLOW_REGISTRATION', '1') == '1'

    # Session cookie hardening. SECURE is opt-in so plain-http local dev works;
    # render.yaml turns it on for the HTTPS production deployment.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Used by the "prevent double booking" check and other business logic
    # that needs a consistent notion of "now".
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
