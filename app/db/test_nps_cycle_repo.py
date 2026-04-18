import pytest
from moto import mock_aws

from app.db.models import SurveyCycle
from app.db import nps_cycle_repo


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
        nps_cycle_repo._create_table()
        yield


def _make_cycle(org_id="org_alpha", cycle_id="cycle_001", **overrides):
    defaults = dict(
        org_id=org_id,
        cycle_id=cycle_id,
        start_date="2024-01-01",
        end_date="2024-03-31",
        status="active",
        reminder_mode="weekly",
        asana_project_gid="proj_123",
        last_reminder_at="",
        distributed_at="",
        asana_form_url="https://form.asana.com/alpha",
        quip_doc_id="quip_abc",
    )
    defaults.update(overrides)
    return SurveyCycle(**defaults)


class TestPutAndGetCycle:
    def test_put_and_get_round_trip(self, ddb_table):
        cycle = _make_cycle()
        nps_cycle_repo.put_cycle(cycle)

        result = nps_cycle_repo.get_cycle("org_alpha", "cycle_001")
        assert result is not None
        assert result.org_id == "org_alpha"
        assert result.cycle_id == "cycle_001"
        assert result.start_date == "2024-01-01"
        assert result.end_date == "2024-03-31"
        assert result.status == "active"
        assert result.reminder_mode == "weekly"
        assert result.asana_project_gid == "proj_123"
        assert result.asana_form_url == "https://form.asana.com/alpha"
        assert result.quip_doc_id == "quip_abc"
        assert result.created_at != ""

    def test_get_nonexistent_returns_none(self, ddb_table):
        result = nps_cycle_repo.get_cycle("org_alpha", "nonexistent")
        assert result is None

    def test_put_sets_created_at_when_empty(self, ddb_table):
        cycle = _make_cycle(created_at="")
        nps_cycle_repo.put_cycle(cycle)
        result = nps_cycle_repo.get_cycle("org_alpha", "cycle_001")
        assert result.created_at != ""

    def test_put_preserves_explicit_created_at(self, ddb_table):
        cycle = _make_cycle(created_at="2024-01-01T00:00:00+00:00")
        nps_cycle_repo.put_cycle(cycle)
        result = nps_cycle_repo.get_cycle("org_alpha", "cycle_001")
        assert result.created_at == "2024-01-01T00:00:00+00:00"


class TestUpdateCycle:
    def test_update_single_field(self, ddb_table):
        nps_cycle_repo.put_cycle(_make_cycle())
        nps_cycle_repo.update_cycle("org_alpha", "cycle_001", status="closed")

        result = nps_cycle_repo.get_cycle("org_alpha", "cycle_001")
        assert result.status == "closed"
        assert result.reminder_mode == "weekly"  # unchanged

    def test_update_multiple_fields(self, ddb_table):
        nps_cycle_repo.put_cycle(_make_cycle())
        nps_cycle_repo.update_cycle(
            "org_alpha", "cycle_001",
            status="closed",
            last_reminder_at="2024-02-15T10:00:00+00:00",
        )

        result = nps_cycle_repo.get_cycle("org_alpha", "cycle_001")
        assert result.status == "closed"
        assert result.last_reminder_at == "2024-02-15T10:00:00+00:00"
        assert result.start_date == "2024-01-01"  # unchanged

    def test_update_no_fields_is_noop(self, ddb_table):
        nps_cycle_repo.put_cycle(_make_cycle())
        nps_cycle_repo.update_cycle("org_alpha", "cycle_001")
        result = nps_cycle_repo.get_cycle("org_alpha", "cycle_001")
        assert result.status == "active"


class TestListCycles:
    def test_list_cycles_for_org(self, ddb_table):
        nps_cycle_repo.put_cycle(_make_cycle(cycle_id="c1"))
        nps_cycle_repo.put_cycle(_make_cycle(cycle_id="c2"))
        nps_cycle_repo.put_cycle(_make_cycle(org_id="org_beta", cycle_id="c3"))

        cycles = nps_cycle_repo.list_cycles("org_alpha")
        cycle_ids = {c.cycle_id for c in cycles}
        assert cycle_ids == {"c1", "c2"}

    def test_list_cycles_empty(self, ddb_table):
        assert nps_cycle_repo.list_cycles("org_alpha") == []


class TestQueryActiveCycles:
    def test_query_active_cycles(self, ddb_table):
        nps_cycle_repo.put_cycle(_make_cycle(org_id="org_a", cycle_id="c1", status="active"))
        nps_cycle_repo.put_cycle(_make_cycle(org_id="org_b", cycle_id="c2", status="active"))
        nps_cycle_repo.put_cycle(_make_cycle(org_id="org_c", cycle_id="c3", status="closed"))

        active = nps_cycle_repo.query_active_cycles()
        active_ids = {(c.org_id, c.cycle_id) for c in active}
        assert active_ids == {("org_a", "c1"), ("org_b", "c2")}

    def test_query_active_cycles_empty(self, ddb_table):
        nps_cycle_repo.put_cycle(_make_cycle(status="closed"))
        assert nps_cycle_repo.query_active_cycles() == []

    def test_query_active_cycles_after_status_update(self, ddb_table):
        nps_cycle_repo.put_cycle(_make_cycle(org_id="org_a", cycle_id="c1", status="active"))
        nps_cycle_repo.update_cycle("org_a", "c1", status="closed")

        active = nps_cycle_repo.query_active_cycles()
        assert len(active) == 0
