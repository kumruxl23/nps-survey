"""Tests for nps_dashboard_service using moto for DynamoDB."""

import pytest
from moto import mock_aws

from app.db import nps_cycle_repo, nps_nomination_repo, nps_response_repo
from app.db.models import Nomination, NpsResponse, SurveyCycle
from app.services import nps_dashboard_service


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
        nps_cycle_repo._create_table()
        nps_nomination_repo._create_table()
        nps_response_repo._create_table()
        yield


_ORG = "org_alpha"
_CYCLE = "cycle_q1"


def _seed_cycle(org_id=_ORG, cycle_id=_CYCLE, status="active"):
    cycle = SurveyCycle(
        org_id=org_id,
        cycle_id=cycle_id,
        start_date="2025-01-01",
        end_date="2025-03-31",
        status=status,
        reminder_mode="manual",
    )
    nps_cycle_repo.put_cycle(cycle)
    return cycle


def _seed_nomination(email, name="Stakeholder", org_id=_ORG, cycle_id=_CYCLE):
    nom = Nomination(org_id=org_id, cycle_id=cycle_id, email=email, name=name)
    nps_nomination_repo.put_nomination(nom)
    return nom


def _seed_response(nps_score, category, response_id, org_id=_ORG, cycle_id=_CYCLE):
    resp = NpsResponse(
        org_id=org_id,
        cycle_id=cycle_id,
        response_id=response_id,
        nps_score=nps_score,
        category=category,
    )
    nps_response_repo.put_response(resp)
    return resp


# ── compute_nps tests ────────────────────────────────────────────────


class TestComputeNps:
    def test_all_promoters(self, ddb_tables):
        """All responses are promoters -> NPS = 100."""
        _seed_nomination("a@test.com")
        _seed_nomination("b@test.com")
        _seed_response(9, "Promoter", "r1")
        _seed_response(10, "Promoter", "r2")

        summary = nps_dashboard_service.compute_nps(_ORG, _CYCLE)

        assert summary.promoter_count == 2
        assert summary.passive_count == 0
        assert summary.detractor_count == 0
        assert summary.nps_score == 100.0
        assert summary.total_responded == 2
        assert summary.total_nominated == 2
        assert summary.response_rate == 1.0

    def test_all_detractors(self, ddb_tables):
        """All responses are detractors -> NPS = -100."""
        _seed_nomination("a@test.com")
        _seed_nomination("b@test.com")
        _seed_response(3, "Detractor", "r1")
        _seed_response(1, "Detractor", "r2")

        summary = nps_dashboard_service.compute_nps(_ORG, _CYCLE)

        assert summary.promoter_count == 0
        assert summary.detractor_count == 2
        assert summary.nps_score == -100.0

    def test_mixed_responses(self, ddb_tables):
        """Mix of promoters, passives, detractors."""
        for i in range(4):
            _seed_nomination(f"user{i}@test.com")

        _seed_response(10, "Promoter", "r1")   # promoter
        _seed_response(9, "Promoter", "r2")    # promoter
        _seed_response(7, "Passive", "r3")     # passive
        _seed_response(3, "Detractor", "r4")   # detractor

        summary = nps_dashboard_service.compute_nps(_ORG, _CYCLE)

        assert summary.promoter_count == 2
        assert summary.passive_count == 1
        assert summary.detractor_count == 1
        assert summary.total_responded == 4
        # NPS = ((2 - 1) / 4) * 100 = 25.0
        assert summary.nps_score == 25.0
        assert summary.total_nominated == 4
        assert summary.response_rate == 1.0

    def test_no_responses(self, ddb_tables):
        """No responses -> NPS = 0, response_rate = 0."""
        _seed_nomination("a@test.com")

        summary = nps_dashboard_service.compute_nps(_ORG, _CYCLE)

        assert summary.total_responded == 0
        assert summary.nps_score == 0.0
        assert summary.response_rate == 0.0
        assert summary.total_nominated == 1

    def test_no_nominations_no_responses(self, ddb_tables):
        """No nominations and no responses -> all zeros."""
        summary = nps_dashboard_service.compute_nps(_ORG, _CYCLE)

        assert summary.total_nominated == 0
        assert summary.total_responded == 0
        assert summary.nps_score == 0.0
        assert summary.response_rate == 0.0

    def test_partial_response_rate(self, ddb_tables):
        """Only some nominees responded."""
        _seed_nomination("a@test.com")
        _seed_nomination("b@test.com")
        _seed_nomination("c@test.com")
        _seed_nomination("d@test.com")
        _seed_response(9, "Promoter", "r1")
        _seed_response(5, "Detractor", "r2")

        summary = nps_dashboard_service.compute_nps(_ORG, _CYCLE)

        assert summary.total_nominated == 4
        assert summary.total_responded == 2
        assert summary.response_rate == 0.5

    def test_org_isolation(self, ddb_tables):
        """Responses from another org are not included."""
        _seed_nomination("a@test.com", org_id=_ORG)
        _seed_nomination("b@test.com", org_id="org_beta")
        _seed_response(10, "Promoter", "r1", org_id=_ORG)
        _seed_response(1, "Detractor", "r2", org_id="org_beta")

        summary = nps_dashboard_service.compute_nps(_ORG, _CYCLE)

        assert summary.promoter_count == 1
        assert summary.detractor_count == 0
        assert summary.total_responded == 1


# ── compute_nps_all_cycles tests ─────────────────────────────────────


class TestComputeNpsAllCycles:
    def test_multiple_cycles(self, ddb_tables):
        """Returns summaries for all cycles of an org."""
        _seed_cycle(cycle_id="q1")
        _seed_cycle(cycle_id="q2")

        _seed_nomination("a@test.com", cycle_id="q1")
        _seed_response(10, "Promoter", "r1", cycle_id="q1")

        _seed_nomination("b@test.com", cycle_id="q2")
        _seed_response(3, "Detractor", "r2", cycle_id="q2")

        summaries = nps_dashboard_service.compute_nps_all_cycles(_ORG)

        assert len(summaries) == 2
        by_cycle = {s.cycle_id: s for s in summaries}
        assert by_cycle["q1"].nps_score == 100.0
        assert by_cycle["q2"].nps_score == -100.0

    def test_no_cycles(self, ddb_tables):
        """No cycles -> empty list."""
        summaries = nps_dashboard_service.compute_nps_all_cycles(_ORG)
        assert summaries == []

    def test_cycle_with_no_responses(self, ddb_tables):
        """Cycle exists but has no responses."""
        _seed_cycle(cycle_id="q1")
        _seed_nomination("a@test.com", cycle_id="q1")

        summaries = nps_dashboard_service.compute_nps_all_cycles(_ORG)

        assert len(summaries) == 1
        assert summaries[0].nps_score == 0.0
        assert summaries[0].total_nominated == 1
        assert summaries[0].total_responded == 0
