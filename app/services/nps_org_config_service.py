"""Service layer for NPS org configuration CRUD operations.

Delegates persistence to app.db.nps_org_config_repo and adds
validation, duplicate-checking, and soft-delete semantics.
"""

from app.db import nps_org_config_repo
from app.db.models import OrgConfig


_REQUIRED_FIELDS = (
    "org_id",
    "org_name",
    "asana_project_gid",
    "asana_form_url",
    "custom_field_nps_score_gid",
    "custom_field_category_gid",
    "custom_field_org_name_gid",
)


def add_org(
    org_id: str,
    org_name: str,
    asana_project_gid: str,
    asana_form_url: str,
    custom_field_nps_score_gid: str,
    custom_field_category_gid: str,
    custom_field_org_name_gid: str,
    quip_doc_id: str = "",
) -> OrgConfig:
    """Add a new org configuration.

    Raises ValueError if required fields are missing/empty or if org_id
    already exists.
    """
    provided = {
        "org_id": org_id,
        "org_name": org_name,
        "asana_project_gid": asana_project_gid,
        "asana_form_url": asana_form_url,
        "custom_field_nps_score_gid": custom_field_nps_score_gid,
        "custom_field_category_gid": custom_field_category_gid,
        "custom_field_org_name_gid": custom_field_org_name_gid,
    }

    missing = [k for k in _REQUIRED_FIELDS if not provided.get(k)]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    existing = nps_org_config_repo.get_org(org_id)
    if existing is not None:
        raise ValueError(f"Org with id '{org_id}' already exists")

    org = OrgConfig(
        org_id=org_id,
        org_name=org_name,
        asana_project_gid=asana_project_gid,
        asana_form_url=asana_form_url,
        custom_field_nps_score_gid=custom_field_nps_score_gid,
        custom_field_category_gid=custom_field_category_gid,
        custom_field_org_name_gid=custom_field_org_name_gid,
        quip_doc_id=quip_doc_id,
    )
    nps_org_config_repo.put_org(org)
    return nps_org_config_repo.get_org(org_id)


def update_org(org_id: str, **fields) -> OrgConfig:
    """Update fields on an existing org configuration.

    Returns the updated OrgConfig. Raises ValueError if org not found.
    """
    existing = nps_org_config_repo.get_org(org_id)
    if existing is None:
        raise ValueError(f"Org with id '{org_id}' not found")

    if fields:
        nps_org_config_repo.update_org(org_id, **fields)

    return nps_org_config_repo.get_org(org_id)


def deactivate_org(org_id: str) -> None:
    """Soft-delete an org by setting is_active=False.

    Raises ValueError if org not found.
    """
    existing = nps_org_config_repo.get_org(org_id)
    if existing is None:
        raise ValueError(f"Org with id '{org_id}' not found")

    nps_org_config_repo.update_org(org_id, is_active=False)


def get_org(org_id: str) -> OrgConfig | None:
    """Retrieve an org configuration by org_id."""
    return nps_org_config_repo.get_org(org_id)


def list_active_orgs() -> list[OrgConfig]:
    """Return all active org configurations."""
    return nps_org_config_repo.list_active_orgs()


def list_all_orgs() -> list[OrgConfig]:
    """Return all org configurations (active and inactive)."""
    return nps_org_config_repo.list_all_orgs()
