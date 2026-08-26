import os
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
    # starting with "postgres://", but SQLAlchemy 1.4+ (and Flask-SQLAlchemy
    # 3.x) only accepts the "postgresql://" scheme -- without this rewrite,
    # deploying against their managed Postgres fails immediately at startup.
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Shared passcode required to switch into the Admin role in the app's
    # simple role-separation layer (see app/utils/auth.py). This is NOT a
    # real per-user auth system -- change it via .env before any real use.
    ADMIN_PASSCODE = os.environ.get('ADMIN_PASSCODE', 'admin123')

    # Used by the "prevent double booking" check and other business logic
    # that needs a consistent notion of "now".
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
