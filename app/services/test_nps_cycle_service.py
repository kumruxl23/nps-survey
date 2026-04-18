"""Tests for nps_cycle_service using moto for DynamoDB mocking."""

import pytest
from moto import mock_aws

from app.db import nps_org_config_repo, nps_cycle_repo
from app.db.models import SurveyCycle
from app.services import nps_cycle_service, nps_org_config_service


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def ddb_tables():
    with mock_aws():
        nps_org_config_repo._create_table()
        nps_cycle_repo._create_table()
        yield


_ORG_ARGS = dict(
    org_id="org_alpha",
    org_name="Alpha Org",
    asana_project_gid="proj_123",
    asana_form_url="https://form.asana.com/alpha",
    custom_field_nps_score_gid="cf_score_1",
    custom_field_category_gid="cf_cat_1",
    custom_field_org_name_gid="cf_org_1",
)


def _seed_org(org_id="org_alpha", **overrides):
    args = {**_ORG_ARGS, "org_id": org_id, **overrides}
    return nps_org_config_service.add_org(**args)


class TestCreateCycle:
    def test_create_cycle_returns_active_cycle(self, ddb_tables):
        _seed_org()
        cycle = nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")

        assert cycle.org_id == "org_alpha"
        assert cycle.start_date == "2024-01-01"
        assert cycle.end_date == "2024-03-31"
        assert cycle.status == "active"
        assert cycle.reminder_mode == "manual"
        assert cycle.cycle_id != ""

    def test_create_cycle_copies_asana_fields_from_org(self, ddb_tables):
        _seed_org()
        cycle = nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")

        assert cycle.asana_project_gid == "proj_123"
        assert cycle.asana_form_url == "https://form.asana.com/alpha"

    def test_create_cycle_generates_unique_ids(self, ddb_tables):
        _seed_org()
        c1 = nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")
        c2 = nps_cycle_service.create_cycle("org_alpha", "2024-04-01", "2024-06-30")

        assert c1.cycle_id != c2.cycle_id

    def test_create_cycle_rejects_invalid_dates(self, ddb_tables):
        _seed_org()
        with pytest.raises(ValueError, match="end_date must be after start_date"):
            nps_cycle_service.create_cycle("org_alpha", "2024-03-31", "2024-01-01")

    def test_create_cycle_rejects_equal_dates(self, ddb_tables):
        _seed_org()
        with pytest.raises(ValueError, match="end_date must be after start_date"):
            nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-01-01")

    def test_create_cycle_rejects_nonexistent_org(self, ddb_tables):
        with pytest.raises(ValueError, match="not found"):
            nps_cycle_service.create_cycle("nonexistent", "2024-01-01", "2024-03-31")

    def test_create_cycle_rejects_inactive_org(self, ddb_tables):
        _seed_org()
        nps_org_config_service.deactivate_org("org_alpha")

        with pytest.raises(ValueError, match="not active"):
            nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")


class TestCloseCycle:
    def test_close_cycle_sets_status_closed(self, ddb_tables):
        _seed_org()
        cycle = nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")
        nps_cycle_service.close_cycle("org_alpha", cycle.cycle_id)

        result = nps_cycle_repo.get_cycle("org_alpha", cycle.cycle_id)
        assert result.status == "closed"

    def test_close_cycle_nonexistent_raises(self, ddb_tables):
        with pytest.raises(ValueError, match="not found"):
            nps_cycle_service.close_cycle("org_alpha", "nonexistent")


class TestGetActiveCycle:
    def test_get_active_cycle_returns_active(self, ddb_tables):
        _seed_org()
        cycle = nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")

        result = nps_cycle_service.get_active_cycle("org_alpha")
        assert result is not None
        assert result.cycle_id == cycle.cycle_id
        assert result.status == "active"

    def test_get_active_cycle_returns_none_when_all_closed(self, ddb_tables):
        _seed_org()
        cycle = nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")
        nps_cycle_service.close_cycle("org_alpha", cycle.cycle_id)

        assert nps_cycle_service.get_active_cycle("org_alpha") is None

    def test_get_active_cycle_returns_none_for_empty_org(self, ddb_tables):
        assert nps_cycle_service.get_active_cycle("org_alpha") is None


class TestListCycles:
    def test_list_cycles_returns_all_for_org(self, ddb_tables):
        _seed_org()
        nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")
        nps_cycle_service.create_cycle("org_alpha", "2024-04-01", "2024-06-30")

        cycles = nps_cycle_service.list_cycles("org_alpha")
        assert len(cycles) == 2

    def test_list_cycles_empty(self, ddb_tables):
        assert nps_cycle_service.list_cycles("org_alpha") == []

    def test_list_cycles_isolates_by_org(self, ddb_tables):
        _seed_org("org_alpha")
        _seed_org("org_beta", org_name="Beta Org")
        nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")
        nps_cycle_service.create_cycle("org_beta", "2024-01-01", "2024-03-31")

        alpha_cycles = nps_cycle_service.list_cycles("org_alpha")
        assert len(alpha_cycles) == 1
        assert alpha_cycles[0].org_id == "org_alpha"


class TestIsCycleActive:
    def test_active_cycle_returns_true(self, ddb_tables):
        cycle = SurveyCycle(
            org_id="org_alpha",
            cycle_id="c1",
            start_date="2024-01-01",
            end_date="2024-03-31",
            status="active",
            reminder_mode="manual",
        )
        assert nps_cycle_service.is_cycle_active(cycle) is True

    def test_closed_cycle_returns_false(self, ddb_tables):
        cycle = SurveyCycle(
            org_id="org_alpha",
            cycle_id="c1",
            start_date="2024-01-01",
            end_date="2024-03-31",
            status="closed",
            reminder_mode="manual",
        )
        assert nps_cycle_service.is_cycle_active(cycle) is False


class TestUpdateReminderMode:
    def test_update_to_daily(self, ddb_tables):
        _seed_org()
        cycle = nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")
        nps_cycle_service.update_reminder_mode("org_alpha", cycle.cycle_id, "daily")

        result = nps_cycle_repo.get_cycle("org_alpha", cycle.cycle_id)
        assert result.reminder_mode == "daily"

    def test_update_to_alternate_day(self, ddb_tables):
        _seed_org()
        cycle = nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")
        nps_cycle_service.update_reminder_mode("org_alpha", cycle.cycle_id, "alternate_day")

        result = nps_cycle_repo.get_cycle("org_alpha", cycle.cycle_id)
        assert result.reminder_mode == "alternate_day"

    def test_update_to_weekly(self, ddb_tables):
        _seed_org()
        cycle = nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")
        nps_cycle_service.update_reminder_mode("org_alpha", cycle.cycle_id, "weekly")

        result = nps_cycle_repo.get_cycle("org_alpha", cycle.cycle_id)
        assert result.reminder_mode == "weekly"

    def test_update_invalid_mode_raises(self, ddb_tables):
        _seed_org()
        cycle = nps_cycle_service.create_cycle("org_alpha", "2024-01-01", "2024-03-31")

        with pytest.raises(ValueError, match="Invalid reminder mode"):
            nps_cycle_service.update_reminder_mode("org_alpha", cycle.cycle_id, "hourly")

    def test_update_nonexistent_cycle_raises(self, ddb_tables):
        with pytest.raises(ValueError, match="not found"):
            nps_cycle_service.update_reminder_mode("org_alpha", "nonexistent", "daily")
