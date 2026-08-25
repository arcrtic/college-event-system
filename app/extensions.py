from flask_sqlalchemy import SQLAlchemy

# Declared here (not in __init__.py) so models.py and routes/*.py can both
# import `db` without importing the app factory itself -> avoids circular imports.
db = SQLAlchemy()
