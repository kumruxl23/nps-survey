import os
import boto3
import pytest
from moto import mock_aws

from app.db.models import OrgConfig
from app.db import nps_org_config_repo


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


def _make_org(org_id="org_alpha", **overrides):
    defaults = dict(
        org_id=org_id,
        org_name="Alpha Org",
        asana_project_gid="proj_123",
        asana_form_url="https://form.asana.com/alpha",
        custom_field_nps_score_gid="cf_score_1",
        custom_field_category_gid="cf_cat_1",
        custom_field_org_name_gid="cf_org_1",
        quip_doc_id="quip_abc",
        reminder_channels=["email"],
        slack_bot_token="xoxb-test",
        is_active=True,
    )
    defaults.update(overrides)
    return OrgConfig(**defaults)


class TestPutAndGetOrg:
    def test_put_and_get_round_trip(self, ddb_table):
        org = _make_org()
        nps_org_config_repo.put_org(org)

        result = nps_org_config_repo.get_org("org_alpha")
        assert result is not None
        assert result.org_id == "org_alpha"
        assert result.org_name == "Alpha Org"
        assert result.asana_project_gid == "proj_123"
        assert result.asana_form_url == "https://form.asana.com/alpha"
        assert result.custom_field_nps_score_gid == "cf_score_1"
        assert result.custom_field_category_gid == "cf_cat_1"
        assert result.custom_field_org_name_gid == "cf_org_1"
        assert result.quip_doc_id == "quip_abc"
        assert result.reminder_channels == ["email"]
        assert result.slack_bot_token == "xoxb-test"
        assert result.is_active is True
        assert result.created_at != ""

    def test_get_nonexistent_returns_none(self, ddb_table):
        result = nps_org_config_repo.get_org("nonexistent")
        assert result is None

    def test_put_sets_created_at_when_empty(self, ddb_table):
        org = _make_org(created_at="")
        nps_org_config_repo.put_org(org)
        result = nps_org_config_repo.get_org("org_alpha")
        assert result.created_at != ""

    def test_put_preserves_explicit_created_at(self, ddb_table):
        org = _make_org(created_at="2024-01-01T00:00:00+00:00")
        nps_org_config_repo.put_org(org)
        result = nps_org_config_repo.get_org("org_alpha")
        assert result.created_at == "2024-01-01T00:00:00+00:00"


class TestUpdateOrg:
    def test_update_single_field(self, ddb_table):
        nps_org_config_repo.put_org(_make_org())
        nps_org_config_repo.update_org("org_alpha", org_name="Updated Name")

        result = nps_org_config_repo.get_org("org_alpha")
        assert result.org_name == "Updated Name"
        # Other fields unchanged
        assert result.asana_project_gid == "proj_123"

    def test_update_multiple_fields(self, ddb_table):
        nps_org_config_repo.put_org(_make_org())
        nps_org_config_repo.update_org(
            "org_alpha",
            org_name="New Name",
            asana_form_url="https://new-form.asana.com",
        )

        result = nps_org_config_repo.get_org("org_alpha")
        assert result.org_name == "New Name"
        assert result.asana_form_url == "https://new-form.asana.com"
        assert result.quip_doc_id == "quip_abc"  # unchanged

    def test_update_is_active(self, ddb_table):
        nps_org_config_repo.put_org(_make_org())
        nps_org_config_repo.update_org("org_alpha", is_active=False)

        result = nps_org_config_repo.get_org("org_alpha")
        assert result.is_active is False

    def test_update_no_fields_is_noop(self, ddb_table):
        nps_org_config_repo.put_org(_make_org())
        nps_org_config_repo.update_org("org_alpha")
        result = nps_org_config_repo.get_org("org_alpha")
        assert result.org_name == "Alpha Org"


class TestListOrgs:
    def test_list_active_orgs(self, ddb_table):
        nps_org_config_repo.put_org(_make_org("org_a"))
        nps_org_config_repo.put_org(_make_org("org_b"))
        nps_org_config_repo.put_org(_make_org("org_c", is_active=False))

        active = nps_org_config_repo.list_active_orgs()
        active_ids = {o.org_id for o in active}
        assert active_ids == {"org_a", "org_b"}

    def test_list_all_orgs(self, ddb_table):
        nps_org_config_repo.put_org(_make_org("org_a"))
        nps_org_config_repo.put_org(_make_org("org_b", is_active=False))

        all_orgs = nps_org_config_repo.list_all_orgs()
        all_ids = {o.org_id for o in all_orgs}
        assert all_ids == {"org_a", "org_b"}

    def test_list_active_orgs_empty(self, ddb_table):
        assert nps_org_config_repo.list_active_orgs() == []

    def test_list_all_orgs_empty(self, ddb_table):
        assert nps_org_config_repo.list_all_orgs() == []
