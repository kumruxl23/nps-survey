import pytest
from moto import mock_aws

from app.db.models import NpsResponse
from app.db import nps_response_repo


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
        nps_response_repo._create_table()
        yield


def _make_response(org_id="org_alpha", cycle_id="cycle_001", response_id="resp_001", **overrides):
    defaults = dict(
        org_id=org_id,
        cycle_id=cycle_id,
        response_id=response_id,
        nps_score=9,
        category="Promoter",
        feedback_text="Great service!",
        recorded_at="",
    )
    defaults.update(overrides)
    return NpsResponse(**defaults)


class TestPutAndListResponses:
    def test_put_and_list_round_trip(self, ddb_table):
        resp = _make_response()
        nps_response_repo.put_response(resp)

        results = nps_response_repo.list_responses("org_alpha", "cycle_001")
        assert len(results) == 1
        r = results[0]
        assert r.org_id == "org_alpha"
        assert r.cycle_id == "cycle_001"
        assert r.response_id == "resp_001"
        assert r.nps_score == 9
        assert r.category == "Promoter"
        assert r.feedback_text == "Great service!"
        assert r.recorded_at != ""

    def test_put_sets_recorded_at_when_empty(self, ddb_table):
        resp = _make_response(recorded_at="")
        nps_response_repo.put_response(resp)

        results = nps_response_repo.list_responses("org_alpha", "cycle_001")
        assert results[0].recorded_at != ""

    def test_put_preserves_explicit_recorded_at(self, ddb_table):
        resp = _make_response(recorded_at="2024-01-15T10:00:00+00:00")
        nps_response_repo.put_response(resp)

        results = nps_response_repo.list_responses("org_alpha", "cycle_001")
        assert results[0].recorded_at == "2024-01-15T10:00:00+00:00"

    def test_list_multiple_responses(self, ddb_table):
        nps_response_repo.put_response(_make_response(response_id="r1", nps_score=10, category="Promoter"))
        nps_response_repo.put_response(_make_response(response_id="r2", nps_score=7, category="Passive"))
        nps_response_repo.put_response(_make_response(response_id="r3", nps_score=3, category="Detractor"))

        results = nps_response_repo.list_responses("org_alpha", "cycle_001")
        assert len(results) == 3
        ids = {r.response_id for r in results}
        assert ids == {"r1", "r2", "r3"}

    def test_list_empty(self, ddb_table):
        assert nps_response_repo.list_responses("org_alpha", "cycle_001") == []


class TestDataIsolation:
    def test_responses_isolated_by_org(self, ddb_table):
        nps_response_repo.put_response(_make_response(org_id="org_a", response_id="r1"))
        nps_response_repo.put_response(_make_response(org_id="org_b", response_id="r2"))

        results_a = nps_response_repo.list_responses("org_a", "cycle_001")
        results_b = nps_response_repo.list_responses("org_b", "cycle_001")
        assert len(results_a) == 1
        assert results_a[0].response_id == "r1"
        assert len(results_b) == 1
        assert results_b[0].response_id == "r2"

    def test_responses_isolated_by_cycle(self, ddb_table):
        nps_response_repo.put_response(_make_response(cycle_id="c1", response_id="r1"))
        nps_response_repo.put_response(_make_response(cycle_id="c2", response_id="r2"))

        results_c1 = nps_response_repo.list_responses("org_alpha", "c1")
        results_c2 = nps_response_repo.list_responses("org_alpha", "c2")
        assert len(results_c1) == 1
        assert results_c1[0].response_id == "r1"
        assert len(results_c2) == 1
        assert results_c2[0].response_id == "r2"


class TestAnonymity:
    def test_no_email_or_name_stored(self, ddb_table):
        """Verify that stored response items contain no email or name fields (Req 6.6)."""
        resp = _make_response()
        nps_response_repo.put_response(resp)

        # Read the raw DynamoDB item to verify no email/name fields
        table = nps_response_repo._get_table()
        raw = table.get_item(
            Key={"org_id_cycle_id": "org_alpha#cycle_001", "response_id": "resp_001"}
        )
        item = raw["Item"]
        assert "email" not in item
        assert "name" not in item
        assert "stakeholder_email" not in item
        assert "stakeholder_name" not in item
