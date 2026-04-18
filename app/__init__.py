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

    # Register the NPS blueprint
    from app.nps.routes import nps_bp
    from app.nps.auth_routes import auth_bp

    app.register_blueprint(nps_bp)
    app.register_blueprint(auth_bp)

    if not app.config.get("TESTING"):
        # Create DynamoDB tables if they don't exist (dev/local only)
        _ensure_tables()

        # Create default admin user if none exist
        try:
            from app.services.auth_service import ensure_default_admin
            ensure_default_admin()
        except Exception:
            logger.warning("Could not create default admin user")

        # Initialize the reminder scheduler
        from app.services.nps_scheduler import init_scheduler

        init_scheduler(app)

    return app
