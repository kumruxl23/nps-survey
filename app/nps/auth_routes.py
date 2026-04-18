"""Authentication routes and role-based access decorators."""

import functools
import logging

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.services import auth_service

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/nps/auth", template_folder="../templates")


# ── Decorators ───────────────────────────────────────────────────


def login_required(f):
    """Require any authenticated user."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            if request.is_json or request.headers.get("Accept") == "application/json":
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    """Require the user to have one of the specified roles."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                if request.is_json:
                    return jsonify({"error": "Authentication required"}), 401
                return redirect(url_for("auth.login_page"))
            user_role = session["user"].get("role", "")
            if user_role not in roles:
                return jsonify({"error": "Insufficient permissions"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Routes ───────────────────────────────────────────────────────


@auth_bp.route("/login", methods=["GET"])
def login_page():
    """Render the login page."""
    if "user" in session:
        return redirect("/nps/dashboard")
    return render_template("nps_login.html")


@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticate user."""
    if request.is_json:
        data = request.json
    else:
        data = request.form
    username = data.get("username", "")
    password = data.get("password", "")

    user = auth_service.authenticate(username, password)
    if not user:
        if request.is_json:
            return jsonify({"error": "Invalid username or password"}), 401
        return render_template("nps_login.html", error="Invalid username or password")

    session["user"] = user
    if request.is_json:
        return jsonify(user)
    return redirect("/nps/dashboard")


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Log out the current user."""
    session.pop("user", None)
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/me", methods=["GET"])
def current_user():
    """Return the current logged-in user info."""
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    return jsonify(session["user"])


# ── User management (admin only) ────────────────────────────────


@auth_bp.route("/users", methods=["GET"])
@role_required("admin")
def list_users():
    """List all users."""
    users = auth_service.list_users()
    return jsonify(users)


@auth_bp.route("/users/add", methods=["POST"])
@role_required("admin")
def add_user():
    """Create a new user."""
    try:
        data = request.json or {}
        user = auth_service.create_user(
            username=data.get("username", ""),
            password=data.get("password", ""),
            role=data.get("role", "viewer"),
            display_name=data.get("display_name", ""),
        )
        return jsonify(user), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@auth_bp.route("/users/update-role", methods=["POST"])
@role_required("admin")
def update_role():
    """Update a user's role."""
    try:
        data = request.json or {}
        auth_service.update_user_role(data.get("username", ""), data.get("role", ""))
        return jsonify({"status": "updated"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@auth_bp.route("/users/delete", methods=["POST"])
@role_required("admin")
def delete_user():
    """Deactivate a user."""
    data = request.json or {}
    auth_service.delete_user(data.get("username", ""))
    return jsonify({"status": "deactivated"})
