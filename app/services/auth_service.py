"""Simple authentication and role-based access control.

Roles:
  - admin: full access (org config, user management, everything)
  - editor: manage nominations, cycles, distribution, reminders
  - viewer: dashboard read-only access

Users are stored in the NpsOrgConfig DynamoDB table with a special
prefix (__user__) to avoid a separate table.
"""

import hashlib
import logging
import os
import secrets

import bcrypt
import boto3

logger = logging.getLogger(__name__)

ROLES = ("admin", "editor", "viewer")


def _get_table():
    table_name = os.environ.get("NPS_ORG_CONFIG_TABLE", "NpsOrgConfig")
    return boto3.resource("dynamodb").Table(table_name)


def _hash_password_bcrypt(password: str) -> str:
    """Hash a password with bcrypt. The salt is embedded in the returned hash."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _legacy_hash_password(password: str, salt: str) -> str:
    """Legacy salted SHA-256 hashing.

    Retained ONLY to verify (and then upgrade) credentials created before
    the bcrypt migration. New passwords are never hashed this way.
    """
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def _is_bcrypt_hash(stored_hash: str) -> bool:
    return stored_hash.startswith(("$2a$", "$2b$", "$2y$"))


def _verify_password(password: str, stored_hash: str, legacy_salt: str) -> bool:
    """Verify a password against a stored hash (bcrypt or legacy SHA-256)."""
    if not stored_hash:
        return False
    if _is_bcrypt_hash(stored_hash):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except ValueError:
            return False
    # Legacy salted SHA-256 path
    return secrets.compare_digest(
        _legacy_hash_password(password, legacy_salt), stored_hash
    )


def create_user(username: str, password: str, role: str, display_name: str = "") -> dict:
    """Create a new user. Raises ValueError if user exists or role invalid."""
    if role not in ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of: {', '.join(ROLES)}")
    if not username or not password:
        raise ValueError("Username and password are required")

    table = _get_table()
    user_key = f"__user__{username}"

    existing = table.get_item(Key={"org_id": user_key}).get("Item")
    if existing:
        raise ValueError(f"User '{username}' already exists")

    hashed = _hash_password_bcrypt(password)

    table.put_item(Item={
        "org_id": user_key,
        "org_name": display_name or username,
        "asana_project_gid": role,
        "asana_form_url": "",  # unused for bcrypt (salt is embedded in the hash)
        "custom_field_nps_score_gid": hashed,
        "custom_field_category_gid": "",
        "custom_field_org_name_gid": "",
        "is_active": True,
    })

    return {"username": username, "role": role, "display_name": display_name or username}


def get_user(username: str) -> dict | None:
    """Fetch an active user record by username WITHOUT a password check.

    Used by the Midway (ALB OIDC) auto-login path, where the network edge
    has already authenticated the person and we only need their app role.
    Returns None for unknown or deactivated users.
    """
    if not username:
        return None
    table = _get_table()
    item = table.get_item(Key={"org_id": f"__user__{username}"}).get("Item")
    if not item or not item.get("is_active", True):
        return None
    return {
        "username": username,
        "role": item.get("asana_project_gid", "viewer"),
        "display_name": item.get("org_name", username),
    }


def authenticate(username: str, password: str) -> dict | None:
    """Verify credentials. Returns user dict or None if invalid."""
    table = _get_table()
    user_key = f"__user__{username}"

    item = table.get_item(Key={"org_id": user_key}).get("Item")
    if not item or not item.get("is_active", True):
        return None

    salt = item.get("asana_form_url", "")
    stored_hash = item.get("custom_field_nps_score_gid", "")

    if not _verify_password(password, stored_hash, salt):
        return None

    # Transparent upgrade: if this account still uses the legacy SHA-256
    # hash, re-hash with bcrypt now that we have the plaintext in hand.
    if not _is_bcrypt_hash(stored_hash):
        try:
            new_hash = _hash_password_bcrypt(password)
            table.update_item(
                Key={"org_id": user_key},
                UpdateExpression="SET custom_field_nps_score_gid = :h, asana_form_url = :s",
                ExpressionAttributeValues={":h": new_hash, ":s": ""},
            )
            logger.info("Upgraded '%s' password hash from SHA-256 to bcrypt", username)
        except Exception:
            logger.warning("Could not upgrade password hash for '%s'", username)

    return {
        "username": username,
        "role": item.get("asana_project_gid", "viewer"),
        "display_name": item.get("org_name", username),
    }


def list_users() -> list[dict]:
    """List all users."""
    table = _get_table()
    response = table.scan()
    users = []
    for item in response.get("Items", []):
        if item["org_id"].startswith("__user__"):
            users.append({
                "username": item["org_id"].replace("__user__", ""),
                "role": item.get("asana_project_gid", "viewer"),
                "display_name": item.get("org_name", ""),
                "is_active": item.get("is_active", True),
            })
    return users


def update_user_role(username: str, role: str) -> None:
    """Update a user's role."""
    if role not in ROLES:
        raise ValueError(f"Invalid role '{role}'")
    table = _get_table()
    table.update_item(
        Key={"org_id": f"__user__{username}"},
        UpdateExpression="SET asana_project_gid = :r",
        ExpressionAttributeValues={":r": role},
    )


def update_password(username: str, new_password: str) -> None:
    """Reset a user's password. Generates a fresh salt and re-hashes."""
    if not new_password:
        raise ValueError("Password cannot be empty")
    table = _get_table()
    user_key = f"__user__{username}"
    existing = table.get_item(Key={"org_id": user_key}).get("Item")
    if not existing:
        raise ValueError(f"User '{username}' not found")

    hashed = _hash_password_bcrypt(new_password)
    table.update_item(
        Key={"org_id": user_key},
        UpdateExpression="SET asana_form_url = :s, custom_field_nps_score_gid = :h",
        ExpressionAttributeValues={":s": "", ":h": hashed},
    )


def delete_user(username: str) -> None:
    """Deactivate a user."""
    table = _get_table()
    table.update_item(
        Key={"org_id": f"__user__{username}"},
        UpdateExpression="SET is_active = :a",
        ExpressionAttributeValues={":a": False},
    )


def ensure_default_admin():
    """Create a default admin user if no users exist.

    The password comes from NPS_ADMIN_PASSWORD. A weak built-in fallback
    ("admin123") is used ONLY for local/dev convenience (run_local.py).
    In any real deployment NPS_ADMIN_PASSWORD MUST be set to a strong
    value via the systemd env override; a loud warning is logged if the
    fallback is used outside local dev.
    """
    users = list_users()
    if not users:
        default_pw = os.environ.get("NPS_ADMIN_PASSWORD")
        if not default_pw:
            default_pw = "admin123"
            # AWS_ACCESS_KEY_ID=local-dev is set by run_local.py; anything
            # else means we're not in the local mocked environment.
            if os.environ.get("AWS_ACCESS_KEY_ID") != "local-dev":
                logger.warning(
                    "NPS_ADMIN_PASSWORD is not set — creating the default admin "
                    "with a WEAK fallback password. Set NPS_ADMIN_PASSWORD to a "
                    "strong value and rotate the admin password immediately."
                )
        try:
            create_user("admin", default_pw, "admin", "Administrator")
            logger.info("Created default admin user (username: admin)")
        except ValueError:
            pass
