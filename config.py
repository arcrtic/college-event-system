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

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f"sqlite:///{os.path.join(basedir, 'instance', 'college_events.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Used by the "prevent double booking" check and other business logic
    # that needs a consistent notion of "now".
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
