"""Tests for nps_org_config_service using moto for DynamoDB mocking."""

import pytest
from moto import mock_aws

from app.db import nps_org_config_repo
from app.db.models import OrgConfig
from app.services import nps_org_config_service


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def ddb_table():
    with mock_aws():
        nps_org_config_repo._create_table()
        yield


_VALID_ARGS = dict(
    org_id="org_alpha",
    org_name="Alpha Org",
    asana_project_gid="proj_123",
    asana_form_url="https://form.asana.com/alpha",
    custom_field_nps_score_gid="cf_score_1",
    custom_field_category_gid="cf_cat_1",
    custom_field_org_name_gid="cf_org_1",
)


class TestAddOrg:
    def test_add_org_returns_persisted_config(self, ddb_table):
        result = nps_org_config_service.add_org(**_VALID_ARGS)

        assert result.org_id == "org_alpha"
        assert result.org_name == "Alpha Org"
        assert result.asana_project_gid == "proj_123"
        assert result.is_active is True
        assert result.created_at != ""

    def test_add_org_with_quip_doc_id(self, ddb_table):
        result = nps_org_config_service.add_org(**_VALID_ARGS, quip_doc_id="quip_abc")
        assert result.quip_doc_id == "quip_abc"

    def test_add_org_rejects_duplicate_org_id(self, ddb_table):
        nps_org_config_service.add_org(**_VALID_ARGS)

        with pytest.raises(ValueError, match="already exists"):
            nps_org_config_service.add_org(**_VALID_ARGS)

    @pytest.mark.parametrize(
        "missing_field",
        [
            "org_id",
            "org_name",
            "asana_project_gid",
            "asana_form_url",
            "custom_field_nps_score_gid",
            "custom_field_category_gid",
            "custom_field_org_name_gid",
        ],
    )
    def test_add_org_rejects_missing_required_field(self, ddb_table, missing_field):
        args = {**_VALID_ARGS, missing_field: ""}
        with pytest.raises(ValueError, match="Missing required fields"):
            nps_org_config_service.add_org(**args)


class TestUpdateOrg:
    def test_update_single_field(self, ddb_table):
        nps_org_config_service.add_org(**_VALID_ARGS)
        result = nps_org_config_service.update_org("org_alpha", org_name="New Name")

        assert result.org_name == "New Name"
        assert result.asana_project_gid == "proj_123"  # unchanged

    def test_update_multiple_fields(self, ddb_table):
        nps_org_config_service.add_org(**_VALID_ARGS)
        result = nps_org_config_service.update_org(
            "org_alpha",
            org_name="Updated",
            asana_form_url="https://new-url.com",
        )

        assert result.org_name == "Updated"
        assert result.asana_form_url == "https://new-url.com"

    def test_update_nonexistent_org_raises(self, ddb_table):
        with pytest.raises(ValueError, match="not found"):
            nps_org_config_service.update_org("nonexistent", org_name="X")

    def test_update_no_fields_returns_unchanged(self, ddb_table):
        nps_org_config_service.add_org(**_VALID_ARGS)
        result = nps_org_config_service.update_org("org_alpha")
        assert result.org_name == "Alpha Org"


class TestDeactivateOrg:
    def test_deactivate_sets_inactive(self, ddb_table):
        nps_org_config_service.add_org(**_VALID_ARGS)
        nps_org_config_service.deactivate_org("org_alpha")

        org = nps_org_config_service.get_org("org_alpha")
        assert org is not None
        assert org.is_active is False

    def test_deactivate_excludes_from_active_list(self, ddb_table):
        nps_org_config_service.add_org(**_VALID_ARGS)
        nps_org_config_service.deactivate_org("org_alpha")

        active = nps_org_config_service.list_active_orgs()
        assert len(active) == 0

    def test_deactivate_nonexistent_raises(self, ddb_table):
        with pytest.raises(ValueError, match="not found"):
            nps_org_config_service.deactivate_org("nonexistent")


class TestGetOrg:
    def test_get_existing_org(self, ddb_table):
        nps_org_config_service.add_org(**_VALID_ARGS)
        result = nps_org_config_service.get_org("org_alpha")
        assert result is not None
        assert result.org_id == "org_alpha"

    def test_get_nonexistent_returns_none(self, ddb_table):
        assert nps_org_config_service.get_org("nonexistent") is None


class TestListOrgs:
    def test_list_active_orgs(self, ddb_table):
        nps_org_config_service.add_org(**_VALID_ARGS)
        args_b = {**_VALID_ARGS, "org_id": "org_beta", "org_name": "Beta Org"}
        nps_org_config_service.add_org(**args_b)
        nps_org_config_service.deactivate_org("org_beta")

        active = nps_org_config_service.list_active_orgs()
        assert len(active) == 1
        assert active[0].org_id == "org_alpha"

    def test_list_all_orgs_includes_inactive(self, ddb_table):
        nps_org_config_service.add_org(**_VALID_ARGS)
        args_b = {**_VALID_ARGS, "org_id": "org_beta", "org_name": "Beta Org"}
        nps_org_config_service.add_org(**args_b)
        nps_org_config_service.deactivate_org("org_beta")

        all_orgs = nps_org_config_service.list_all_orgs()
        all_ids = {o.org_id for o in all_orgs}
        assert all_ids == {"org_alpha", "org_beta"}

    def test_list_active_empty(self, ddb_table):
        assert nps_org_config_service.list_active_orgs() == []

    def test_list_all_empty(self, ddb_table):
        assert nps_org_config_service.list_all_orgs() == []
