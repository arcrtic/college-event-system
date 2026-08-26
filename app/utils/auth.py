"""
Authentication and role management utility for the College Event Resource Allocation System.

Supports two primary roles:
- Organizer: create, edit, cancel events, and submit resource requests.
- Admin: manage resources (add/edit/toggle), review, approve, reject, allocate requests, and mark events completed.

Includes built-in demo credentials for easy evaluation:
- Admin: admin / admin123
- Organizer: organizer / org123
"""
from functools import wraps
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

auth_bp = Blueprint("auth", __name__)

DEMO_USERS = {
    "admin": {
        "password": "admin123",
        "name": "Admin User",
        "role": "admin",
    },
    "organizer": {
        "password": "org123",
        "name": "Event Organizer",
        "role": "organizer",
    },
}


def current_user():
    user = session.get("user")
    if user:
        return user
    # Default guest/organizer context
    role = session.get("role", "organizer")
    return {
        "username": "admin" if role == "admin" else "organizer",
        "name": "Admin User" if role == "admin" else "Event Organizer",
        "role": role,
    }


def current_role():
    user = session.get("user")
    if user:
        return user.get("role", "organizer")
    return session.get("role", "organizer")


def is_admin():
    return current_role() == "admin"


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session and "role" not in session:
            flash("Please sign in to access this page.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Decorator for routes that only Admins can access."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin():
            flash("Administrator privileges required to access that page.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.values.get("next") or url_for("dashboard.index")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # Also support 1-click quick demo login buttons
        quick_role = request.form.get("quick_login")
        if quick_role in DEMO_USERS:
            user_data = DEMO_USERS[quick_role]
            session["user"] = {
                "username": quick_role,
                "name": user_data["name"],
                "role": user_data["role"],
            }
            session["role"] = user_data["role"]
            flash(f"Signed in as {user_data['name']} ({user_data['role'].capitalize()}).", "success")
            return redirect(next_url)

        # Standard username/password login
        if username in DEMO_USERS and DEMO_USERS[username]["password"] == password:
            user_data = DEMO_USERS[username]
            session["user"] = {
                "username": username,
                "name": user_data["name"],
                "role": user_data["role"],
            }
            session["role"] = user_data["role"]
            flash(f"Welcome back, {user_data['name']}!", "success")
            return redirect(next_url)

        # Check against ADMIN_PASSCODE as a fallback for admin login
        admin_passcode = current_app.config.get("ADMIN_PASSCODE", "admin123")
        if (username == "admin" or not username) and password == admin_passcode:
            session["user"] = {
                "username": "admin",
                "name": "Admin User",
                "role": "admin",
            }
            session["role"] = "admin"
            flash("Welcome back, Admin User!", "success")
            return redirect(next_url)

        flash("Invalid username or password. Use demo credentials below.", "error")

    return render_template("auth/login.html", next_url=next_url)


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    session.pop("user", None)
    session.pop("role", None)
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/switch-role", methods=["POST"])
def switch_role():
    target_role = request.form.get("role", "organizer")
    if target_role == "admin":
        session["user"] = {
            "username": "admin",
            "name": "Admin User",
            "role": "admin",
        }
        session["role"] = "admin"
        flash("Switched to Admin role.", "success")
    else:
        session["user"] = {
            "username": "organizer",
            "name": "Event Organizer",
            "role": "organizer",
        }
        session["role"] = "organizer"
        flash("Switched to Organizer role.", "success")

    next_url = request.referrer or url_for("dashboard.index")
    return redirect(next_url)


# Legacy route support for switch-to-organizer & admin_login
@auth_bp.route("/switch-to-organizer", methods=["POST"])
def switch_to_organizer():
    session["user"] = {
        "username": "organizer",
        "name": "Event Organizer",
        "role": "organizer",
    }
    session["role"] = "organizer"
    flash("Switched to Organizer view.", "success")
    return redirect(request.referrer or url_for("dashboard.index"))


@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    return redirect(url_for("auth.login", next=request.args.get("next")))
