import json

import pytest
from moto import mock_aws

from app.db.models import ReminderLog
from app.db import nps_reminder_log_repo


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
        nps_reminder_log_repo._create_table()
        yield


def _make_log(org_id="org_alpha", cycle_id="cycle_001", log_id="log_001", **overrides):
    defaults = dict(
        org_id=org_id,
        cycle_id=cycle_id,
        log_id=log_id,
        sent_at="",
        trigger_type="automated",
        recipient_count=5,
        channels=["email"],
        failures="[]",
    )
    defaults.update(overrides)
    return ReminderLog(**defaults)


class TestPutAndListLogs:
    def test_put_and_list_round_trip(self, ddb_table):
        log = _make_log(trigger_type="manual", recipient_count=10, channels=["email", "slack"])
        nps_reminder_log_repo.put_log(log)

        results = nps_reminder_log_repo.list_logs("org_alpha", "cycle_001")
        assert len(results) == 1
        r = results[0]
        assert r.org_id == "org_alpha"
        assert r.cycle_id == "cycle_001"
        assert r.log_id == "log_001"
        assert r.trigger_type == "manual"
        assert r.recipient_count == 10
        assert r.channels == ["email", "slack"]
        assert r.failures == "[]"
        assert r.sent_at != ""

    def test_put_sets_sent_at_when_empty(self, ddb_table):
        log = _make_log(sent_at="")
        nps_reminder_log_repo.put_log(log)

        results = nps_reminder_log_repo.list_logs("org_alpha", "cycle_001")
        assert results[0].sent_at != ""

    def test_put_preserves_explicit_sent_at(self, ddb_table):
        log = _make_log(sent_at="2024-01-15T10:00:00+00:00")
        nps_reminder_log_repo.put_log(log)

        results = nps_reminder_log_repo.list_logs("org_alpha", "cycle_001")
        assert results[0].sent_at == "2024-01-15T10:00:00+00:00"

    def test_list_multiple_logs(self, ddb_table):
        nps_reminder_log_repo.put_log(_make_log(log_id="l1", trigger_type="automated"))
        nps_reminder_log_repo.put_log(_make_log(log_id="l2", trigger_type="manual"))
        nps_reminder_log_repo.put_log(_make_log(log_id="l3", trigger_type="automated"))

        results = nps_reminder_log_repo.list_logs("org_alpha", "cycle_001")
        assert len(results) == 3
        ids = {r.log_id for r in results}
        assert ids == {"l1", "l2", "l3"}

    def test_list_empty(self, ddb_table):
        assert nps_reminder_log_repo.list_logs("org_alpha", "cycle_001") == []

    def test_failures_stored_as_json_string(self, ddb_table):
        failures = json.dumps([{"email": "a@test.com", "error": "bounce"}])
        log = _make_log(failures=failures)
        nps_reminder_log_repo.put_log(log)

        results = nps_reminder_log_repo.list_logs("org_alpha", "cycle_001")
        parsed = json.loads(results[0].failures)
        assert len(parsed) == 1
        assert parsed[0]["email"] == "a@test.com"


class TestDataIsolation:
    def test_logs_isolated_by_org(self, ddb_table):
        nps_reminder_log_repo.put_log(_make_log(org_id="org_a", log_id="l1"))
        nps_reminder_log_repo.put_log(_make_log(org_id="org_b", log_id="l2"))

        results_a = nps_reminder_log_repo.list_logs("org_a", "cycle_001")
        results_b = nps_reminder_log_repo.list_logs("org_b", "cycle_001")
        assert len(results_a) == 1
        assert results_a[0].log_id == "l1"
        assert len(results_b) == 1
        assert results_b[0].log_id == "l2"

    def test_logs_isolated_by_cycle(self, ddb_table):
        nps_reminder_log_repo.put_log(_make_log(cycle_id="c1", log_id="l1"))
        nps_reminder_log_repo.put_log(_make_log(cycle_id="c2", log_id="l2"))

        results_c1 = nps_reminder_log_repo.list_logs("org_alpha", "c1")
        results_c2 = nps_reminder_log_repo.list_logs("org_alpha", "c2")
        assert len(results_c1) == 1
        assert results_c1[0].log_id == "l1"
        assert len(results_c2) == 1
        assert results_c2[0].log_id == "l2"
