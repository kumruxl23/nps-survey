"""Authentication routes and role-based access decorators.

Two auth modes:

1. Password login (default) — the classic username/password form backed
   by bcrypt hashes in DynamoDB. Used for local dev (run_local.py).
2. Midway auto-login (NPS_MIDWAY_AUTH=1) — in production the app sits
   behind an ALB whose HTTPS listener authenticates every request via
   Amazon Federate (Midway) and injects the caller's alias in the
   ``X-Amzn-Oidc-Identity`` header. The instance security group admits
   traffic ONLY from the ALB, so the header cannot be spoofed. The app
   maps alias -> role from its existing user store; the password form is
   disabled entirely. Unknown aliases get an access-request page.
"""

import functools
import logging
import os
import secrets as _secrets

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


def _midway_enabled() -> bool:
    return os.environ.get("NPS_MIDWAY_AUTH") == "1"


def _invalidate_access(alias: str = "") -> None:
    """Drop the cached access decision so a grant change applies promptly."""
    try:
        from app.services import nps_access_service
        nps_access_service.invalidate(alias)
    except Exception:
        logger.exception("access cache invalidate failed for %s", alias)


def _midway_alias() -> str:
    """The Midway alias asserted by the ALB, or empty string."""
    return request.headers.get("X-Amzn-Oidc-Identity", "").strip().lower()


def _try_midway_auth() -> dict | None:
    """Populate the session from the ALB's verified Midway identity.

    No-op unless NPS_MIDWAY_AUTH=1. Access is resolved centrally
    (manual grants first, then live PAPI reporting) so leaders and their
    reports are admitted automatically without a manual user record.
    Returns the user dict on success, or None when the alias has no access.
    """
    if not _midway_enabled():
        return None
    alias = _midway_alias()
    if not alias:
        return None

    from app.services import nps_access_service

    acc = nps_access_service.resolve_access(alias)
    if not acc or not acc.get("role"):
        return None

    rec = auth_service.get_user(alias)
    display_name = (rec or {}).get("display_name") or alias
    user = {
        "username": alias,
        "role": acc["role"],
        "display_name": display_name,
        # Access scope carried on the session for the dashboard + feedback gates.
        "nps_orgs": acc.get("orgs", []),
        "nps_home_org": acc.get("home_org", ""),
        "nps_leader": acc.get("leader_name", ""),
        "nps_super": acc.get("is_super", False),
        "nps_source": acc.get("source", ""),
    }
    session["user"] = user
    logger.info("Midway auto-login: %s (%s via %s)", alias, acc["role"], acc.get("source"))
    return user


# ── Decorators ───────────────────────────────────────────────────


def _establish_session() -> None:
    """Ensure session["user"] reflects CURRENT access.

    In Midway mode we re-resolve from the ALB header on every request (backed
    by a short cache) so grants and removals take effect promptly — a revoked
    user's stale session is cleared here. In password mode we only auto-login
    when there is no session yet.
    """
    if _midway_enabled() and _midway_alias():
        # ALB always injects the identity header → re-resolve every request so
        # a revoked grant clears the stale session immediately.
        if not _try_midway_auth():
            session.pop("user", None)
    elif "user" not in session:
        _try_midway_auth()


def login_required(f):
    """Require any authenticated user."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        _establish_session()
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
            _establish_session()
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
    """Render the login page (password mode) or auto-login (Midway mode)."""
    if "user" in session:
        return redirect("/nps/dashboard")
    if _midway_enabled():
        if _try_midway_auth():
            return redirect("/nps/dashboard")
        # Authenticated with Midway but not provisioned in the app.
        return render_template(
            "nps_login.html", midway_denied=True, alias=_midway_alias()
        ), 403
    return render_template("nps_login.html")


@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticate user (password mode only)."""
    if _midway_enabled():
        return jsonify({"error": "Password login is disabled; access is via Midway"}), 403
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
        username = data.get("username", "").strip().lower()
        password = data.get("password", "")
        if not password and _midway_enabled():
            # Midway mode: the password is never used (form is disabled);
            # store an unguessable random one to satisfy the model.
            password = _secrets.token_urlsafe(32)
        user = auth_service.create_user(
            username=username,
            password=password,
            role=data.get("role", "viewer"),
            display_name=data.get("display_name", ""),
        )
        _invalidate_access(username)
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
        _invalidate_access(data.get("username", ""))
        return jsonify({"status": "updated"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@auth_bp.route("/users/delete", methods=["POST"])
@role_required("admin")
def delete_user():
    """Deactivate a user."""
    data = request.json or {}
    auth_service.delete_user(data.get("username", ""))
    _invalidate_access(data.get("username", ""))
    return jsonify({"status": "deactivated"})
