import pytest
from moto import mock_aws

from app.db.models import DeliveryFailure
from app.db import nps_delivery_failure_repo


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
        nps_delivery_failure_repo._create_table()
        yield


def _make_failure(org_id="org_alpha", cycle_id="cycle_001", failure_id="fail_001", **overrides):
    defaults = dict(
        org_id=org_id,
        cycle_id=cycle_id,
        failure_id=failure_id,
        email="user@example.com",
        error_reason="SMTP timeout",
        event_type="distribution",
        channel="email",
        occurred_at="",
    )
    defaults.update(overrides)
    return DeliveryFailure(**defaults)


class TestPutAndListFailures:
    def test_put_and_list_round_trip(self, ddb_table):
        failure = _make_failure()
        nps_delivery_failure_repo.put_failure(failure)

        results = nps_delivery_failure_repo.list_failures("org_alpha", "cycle_001")
        assert len(results) == 1
        f = results[0]
        assert f.org_id == "org_alpha"
        assert f.cycle_id == "cycle_001"
        assert f.failure_id == "fail_001"
        assert f.email == "user@example.com"
        assert f.error_reason == "SMTP timeout"
        assert f.event_type == "distribution"
        assert f.channel == "email"
        assert f.occurred_at != ""

    def test_put_sets_occurred_at_when_empty(self, ddb_table):
        failure = _make_failure(occurred_at="")
        nps_delivery_failure_repo.put_failure(failure)

        results = nps_delivery_failure_repo.list_failures("org_alpha", "cycle_001")
        assert results[0].occurred_at != ""

    def test_put_preserves_explicit_occurred_at(self, ddb_table):
        failure = _make_failure(occurred_at="2024-01-15T10:00:00+00:00")
        nps_delivery_failure_repo.put_failure(failure)

        results = nps_delivery_failure_repo.list_failures("org_alpha", "cycle_001")
        assert results[0].occurred_at == "2024-01-15T10:00:00+00:00"

    def test_list_multiple_failures(self, ddb_table):
        nps_delivery_failure_repo.put_failure(_make_failure(failure_id="f1", channel="email"))
        nps_delivery_failure_repo.put_failure(_make_failure(failure_id="f2", channel="slack"))
        nps_delivery_failure_repo.put_failure(_make_failure(failure_id="f3", event_type="unmatched_response"))

        results = nps_delivery_failure_repo.list_failures("org_alpha", "cycle_001")
        assert len(results) == 3
        ids = {f.failure_id for f in results}
        assert ids == {"f1", "f2", "f3"}

    def test_list_empty(self, ddb_table):
        assert nps_delivery_failure_repo.list_failures("org_alpha", "cycle_001") == []


class TestDataIsolation:
    def test_failures_isolated_by_org(self, ddb_table):
        nps_delivery_failure_repo.put_failure(_make_failure(org_id="org_a", failure_id="f1"))
        nps_delivery_failure_repo.put_failure(_make_failure(org_id="org_b", failure_id="f2"))

        results_a = nps_delivery_failure_repo.list_failures("org_a", "cycle_001")
        results_b = nps_delivery_failure_repo.list_failures("org_b", "cycle_001")
        assert len(results_a) == 1
        assert results_a[0].failure_id == "f1"
        assert len(results_b) == 1
        assert results_b[0].failure_id == "f2"

    def test_failures_isolated_by_cycle(self, ddb_table):
        nps_delivery_failure_repo.put_failure(_make_failure(cycle_id="c1", failure_id="f1"))
        nps_delivery_failure_repo.put_failure(_make_failure(cycle_id="c2", failure_id="f2"))

        results_c1 = nps_delivery_failure_repo.list_failures("org_alpha", "c1")
        results_c2 = nps_delivery_failure_repo.list_failures("org_alpha", "c2")
        assert len(results_c1) == 1
        assert results_c1[0].failure_id == "f1"
        assert len(results_c2) == 1
        assert results_c2[0].failure_id == "f2"


class TestEventTypesAndChannels:
    def test_stores_distribution_email_failure(self, ddb_table):
        nps_delivery_failure_repo.put_failure(
            _make_failure(event_type="distribution", channel="email")
        )
        results = nps_delivery_failure_repo.list_failures("org_alpha", "cycle_001")
        assert results[0].event_type == "distribution"
        assert results[0].channel == "email"

    def test_stores_reminder_slack_failure(self, ddb_table):
        nps_delivery_failure_repo.put_failure(
            _make_failure(event_type="reminder", channel="slack")
        )
        results = nps_delivery_failure_repo.list_failures("org_alpha", "cycle_001")
        assert results[0].event_type == "reminder"
        assert results[0].channel == "slack"

    def test_stores_unmatched_response_failure(self, ddb_table):
        nps_delivery_failure_repo.put_failure(
            _make_failure(event_type="unmatched_response", channel="email")
        )
        results = nps_delivery_failure_repo.list_failures("org_alpha", "cycle_001")
        assert results[0].event_type == "unmatched_response"
