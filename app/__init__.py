"""Flask application factory for the NPS Survey Automation tool."""

import logging
import os

from flask import Flask

logger = logging.getLogger(__name__)


def _ensure_tables():
    """Create all NPS DynamoDB tables if they don't already exist.

    Catches ResourceInUseException for tables that already exist.
    Intended for development/testing — in production, tables are pre-created.
    """
    from app.db import (
        nps_cycle_repo,
        nps_delivery_failure_repo,
        nps_nomination_repo,
        nps_org_config_repo,
        nps_reminder_log_repo,
        nps_response_repo,
    )

    repos = [
        nps_org_config_repo,
        nps_cycle_repo,
        nps_nomination_repo,
        nps_response_repo,
        nps_reminder_log_repo,
        nps_delivery_failure_repo,
    ]

    for repo in repos:
        try:
            repo._create_table()
        except Exception as exc:
            # ResourceInUseException means the table already exists — safe to ignore
            if "ResourceInUseException" in str(type(exc).__name__) or "ResourceInUseException" in str(exc):
                logger.debug("Table already exists for %s", repo.__name__)
            else:
                logger.warning("Could not create table for %s: %s", repo.__name__, exc)


def _configure_for_proxy(app):
    """Configure the app to run behind the Midway/ALB reverse proxy.

    Enabled by setting ``NPS_BEHIND_PROXY=1``. When the app sits behind an
    internet-facing ALB (with an authenticate-oidc / Midway listener) that
    terminates TLS, we must:

    * trust the ALB's ``X-Forwarded-*`` headers so Flask emits ``https://``
      URLs (avoids mixed-content on redirects/links), and
    * mark session cookies Secure/HttpOnly/SameSite.

    Off by default so local HTTP dev and tests are unaffected.
    """
    from werkzeug.middleware.proxy_fix import ProxyFix

    # One proxy hop (the ALB): trust its forwarded proto/host/for/port.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    app.config.update(
        PREFERRED_URL_SCHEME="https",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )


def _install_allowed_hosts(app):
    """Reject requests whose Host header isn't in the allowlist.

    Set ``NPS_ALLOWED_HOSTS`` to a comma-separated list of hostnames (e.g.
    ``nps.aifa.amazon.dev``) to guard against Host-header spoofing behind
    the ALB. No-op if unset.
    """
    raw = os.environ.get("NPS_ALLOWED_HOSTS", "").strip()
    if not raw:
        return
    allowed = {h.strip().lower() for h in raw.split(",") if h.strip()}

    from flask import request, abort

    @app.before_request
    def _check_host():  # pragma: no cover - exercised via test client below
        host = (request.host or "").split(":", 1)[0].lower()
        if host and host not in allowed:
            abort(400, description="Invalid Host header")


def create_app(config=None):
    """Create and configure the Flask application.

    Args:
        config: Optional dict of configuration overrides (e.g. TESTING=True).

    Returns:
        The configured Flask app instance.
    """
    app = Flask(__name__)

    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-production")

    if config:
        app.config.update(config)

    # Reverse-proxy / Midway-ALB awareness (opt-in via env).
    if os.environ.get("NPS_BEHIND_PROXY", "").lower() in ("1", "true", "yes"):
        _configure_for_proxy(app)
    _install_allowed_hosts(app)

    # Register the NPS blueprint
    from app.nps.routes import nps_bp
    from app.nps.auth_routes import auth_bp

    app.register_blueprint(nps_bp)
    app.register_blueprint(auth_bp)

    if not app.config.get("TESTING"):
        # Create DynamoDB tables only when explicitly opted in (dev/local
        # bootstrap). In production, tables are pre-created and the EC2
        # IAM role is intentionally scoped without dynamodb:CreateTable
        # to keep the principle of least privilege. The defensive call
        # would otherwise log AccessDeniedException on every restart.
        if os.environ.get("NPS_ENSURE_TABLES", "").lower() in ("1", "true", "yes"):
            _ensure_tables()

        # Create default admin user if none exist
        try:
            from app.services.auth_service import ensure_default_admin
            ensure_default_admin()
        except Exception:
            logger.warning("Could not create default admin user")

        # Initialize the reminder scheduler — unless explicitly disabled.
        # Set NPS_DISABLE_SCHEDULER=1 for a read-only real-data demo so we
        # NEVER fire reminder emails against live data/SES.
        if os.environ.get("NPS_DISABLE_SCHEDULER", "").lower() not in ("1", "true", "yes"):
            from app.services.nps_scheduler import init_scheduler

            init_scheduler(app)
        else:
            logger.warning("Reminder scheduler DISABLED (NPS_DISABLE_SCHEDULER set)")

    return app
