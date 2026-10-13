"""
Authentication and role management for the College Event Resource Allocation System.

Real, database-backed accounts (see `app.models.User`) with hashed passwords.

Roles
- Organizer: creates/edits/cancels THEIR OWN events, requests resources for them,
  and tracks only their own requests.
- Admin: manages the resource catalogue, approves/rejects/allocates requests,
  can manage any event, and can read the audit log.

Every page except sign-in / registration / static files requires a signed-in
user (see `require_login`). There is no role switching: to act as an admin you
must sign in with an admin account.
"""
import re
from functools import wraps

from flask import (
    Blueprint, abort, current_app, flash, g, jsonify, redirect,
    render_template, request, session, url_for,
)

from app.extensions import db
from app.models import User, UserRole

auth_bp = Blueprint("auth", __name__)

# Endpoints reachable without signing in.
PUBLIC_ENDPOINTS = {"auth.login", "auth.register", "auth.healthz", "static"}

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")


# ---------------------------------------------------------------------------
# Current user helpers
# ---------------------------------------------------------------------------
def current_user():
    """The signed-in `User`, or None. Cached on `g` for the session user_id."""
    user_id = session.get("user_id")
    if not user_id:
        return None

    if getattr(g, "_current_user_id", None) == user_id:
        return getattr(g, "_current_user", None)

    try:
        user = db.session.get(User, user_id)
    except Exception:
        db.session.rollback()
        user = None

    if user is not None and not user.is_active:
        user = None

    g._current_user = user
    g._current_user_id = user_id
    return user


def current_role():
    user = current_user()
    return user.role if user else None


def is_admin():
    user = current_user()
    return bool(user and user.is_admin)


def can_manage_event(event):
    """Admins can manage any event; organizers only the events they own."""
    user = current_user()
    if user is None:
        return False
    return user.is_admin or (event.owner_id is not None and event.owner_id == user.id)


def ensure_can_manage_event(event):
    if not can_manage_event(event):
        abort(403)


def safe_next_url(target):
    """Only allow same-site relative redirects (blocks open-redirect attacks)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("dashboard.index")


# ---------------------------------------------------------------------------
# Decorators / global gate
# ---------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please sign in to access this page.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Only administrators may access. Signed-in organizers get a 403 page."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("Please sign in to access this page.", "error")
            return redirect(url_for("auth.login", next=request.path))
        if not user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@auth_bp.before_app_request
def require_login():
    """Site-wide gate: nothing but the public endpoints works while signed out."""
    if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if current_user() is not None:
        return None

    if request.path.endswith(".json"):
        return jsonify(error="Authentication required"), 401

    flash("Please sign in to continue.", "error")
    next_url = request.path if request.method == "GET" else None
    return redirect(url_for("auth.login", next=next_url) if next_url else url_for("auth.login"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@auth_bp.route("/healthz")
def healthz():
    return "ok", 200


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user() is not None:
        return redirect(url_for("dashboard.index"))

    next_url = safe_next_url(request.values.get("next"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = None
        if username:
            user = User.query.filter(db.func.lower(User.username) == username.lower()).first()

        if user is not None and user.is_active and user.check_password(password):
            session.clear()  # prevents session fixation
            session["user_id"] = user.id
            session.permanent = True
            flash(f"Welcome back, {user.name}!", "success")
            return redirect(next_url)

        flash("Invalid username or password.", "error")

    return render_template(
        "auth/login.html",
        next_url=next_url,
        show_demo=current_app.config.get("SHOW_DEMO_LOGIN", False),
        allow_registration=current_app.config.get("ALLOW_REGISTRATION", True),
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Self-service sign-up. New accounts are ALWAYS organizers, never admins."""
    if not current_app.config.get("ALLOW_REGISTRATION", True):
        abort(404)
    if current_user() is not None:
        return redirect(url_for("dashboard.index"))

    form = request.form
    if request.method == "POST":
        name = form.get("name", "").strip()
        username = form.get("username", "").strip()
        department = form.get("department", "").strip()
        password = form.get("password", "")
        confirm = form.get("confirm_password", "")

        error = None
        if not name:
            error = "Full name is required."
        elif not USERNAME_RE.match(username):
            error = "Username must be 3-30 characters: letters, numbers, dot, dash or underscore."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords do not match."
        elif User.query.filter(db.func.lower(User.username) == username.lower()).first():
            error = "That username is already taken."

        if error:
            flash(error, "error")
        else:
            user = User(
                username=username,
                name=name[:100],
                department=department[:100] or None,
                role=UserRole.ORGANIZER.value,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            session.clear()
            session["user_id"] = user.id
            session.permanent = True
            flash(f"Account created. Welcome, {user.name}!", "success")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
