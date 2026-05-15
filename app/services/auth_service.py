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

import boto3

logger = logging.getLogger(__name__)

ROLES = ("admin", "editor", "viewer")


def _get_table():
    table_name = os.environ.get("NPS_ORG_CONFIG_TABLE", "NpsOrgConfig")
    return boto3.resource("dynamodb").Table(table_name)


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


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

    salt = secrets.token_hex(16)
    hashed = _hash_password(password, salt)

    table.put_item(Item={
        "org_id": user_key,
        "org_name": display_name or username,
        "asana_project_gid": role,
        "asana_form_url": salt,
        "custom_field_nps_score_gid": hashed,
        "custom_field_category_gid": "",
        "custom_field_org_name_gid": "",
        "is_active": True,
    })

    return {"username": username, "role": role, "display_name": display_name or username}


def authenticate(username: str, password: str) -> dict | None:
    """Verify credentials. Returns user dict or None if invalid."""
    table = _get_table()
    user_key = f"__user__{username}"

    item = table.get_item(Key={"org_id": user_key}).get("Item")
    if not item or not item.get("is_active", True):
        return None

    salt = item.get("asana_form_url", "")
    stored_hash = item.get("custom_field_nps_score_gid", "")
    computed = _hash_password(password, salt)

    if computed != stored_hash:
        return None

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

    salt = secrets.token_hex(16)
    hashed = _hash_password(new_password, salt)
    table.update_item(
        Key={"org_id": user_key},
        UpdateExpression="SET asana_form_url = :s, custom_field_nps_score_gid = :h",
        ExpressionAttributeValues={":s": salt, ":h": hashed},
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
    """Create a default admin user if no users exist."""
    users = list_users()
    if not users:
        default_pw = os.environ.get("NPS_ADMIN_PASSWORD", "admin123")
        try:
            create_user("admin", default_pw, "admin", "Administrator")
            logger.info("Created default admin user (username: admin)")
        except ValueError:
            pass
