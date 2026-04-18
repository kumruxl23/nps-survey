"""Tests for nps_response_service using moto for DynamoDB and unittest.mock for asana_client."""

import pytest
from moto import mock_aws
from unittest.mock import patch, MagicMock

from app.db import (
    nps_cycle_repo,
    nps_delivery_failure_repo,
    nps_nomination_repo,
    nps_org_config_repo,
    nps_response_repo,
)
from app.db.models import (
    DeliveryFailure,
    Nomination,
    NpsResponse,
    OrgConfig,
    SurveyCycle,
)
from app.services import nps_response_service


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
        nps_nomination_repo._create_table()
        nps_response_repo._create_table()
        nps_delivery_failure_repo._create_table()
        yield


_ORG = "org_alpha"
_CYCLE = "cycle_q1"
_TASK_GID = "task_12345"


def _seed_org():
    """Create a default OrgConfig in DynamoDB."""
    org = OrgConfig(
        org_id=_ORG,
        org_name="Alpha Org",
        asana_project_gid="proj_123",
        asana_form_url="https://form.asana.com/?k=test",
        custom_field_nps_score_gid="cf_score",
        custom_field_category_gid="cf_cat",
        custom_field_org_name_gid="cf_org",
    )
    nps_org_config_repo.put_org(org)
    return org


def _seed_cycle(status="active"):
    """Create a default SurveyCycle in DynamoDB."""
    cycle = SurveyCycle(
        org_id=_ORG,
        cycle_id=_CYCLE,
        start_date="2025-01-01",
        end_date="2025-03-31",
        status=status,
        reminder_mode="manual",
        asana_project_gid="proj_123",
        asana_form_url="https://form.asana.com/?k=test",
    )
    nps_cycle_repo.put_cycle(cycle)
    return cycle


def _seed_nomination(email="alice@example.com", name="Alice"):
    """Create a nomination in DynamoDB."""
    nom = Nomination(
        org_id=_ORG,
        cycle_id=_CYCLE,
        email=email,
        name=name,
    )
    nps_nomination_repo.put_nomination(nom)
    return nom


def _make_payload(email="alice@example.com", nps_score=9, org_id=_ORG,
                  cycle_id=_CYCLE, task_gid=_TASK_GID):
    return {
        "email": email,
        "nps_score": nps_score,
        "org_id": org_id,
        "cycle_id": cycle_id,
        "task_gid": task_gid,
    }


# ── categorize_score tests ──────────────────────────────────────────


class TestCategorizeScore:
    def test_promoter_score_9(self):
        assert nps_response_service.categorize_score(9) == "Promoter"

    def test_promoter_score_10(self):
        assert nps_response_service.categorize_score(10) == "Promoter"

    def test_passive_score_7(self):
        assert nps_response_service.categorize_score(7) == "Passive"

    def test_passive_score_8(self):
        assert nps_response_service.categorize_score(8) == "Passive"

    def test_detractor_score_0(self):
        assert nps_response_service.categorize_score(0) == "Detractor"

    def test_detractor_score_6(self):
        assert nps_response_service.categorize_score(6) == "Detractor"

    def test_detractor_score_3(self):
        assert nps_response_service.categorize_score(3) == "Detractor"

    def test_invalid_score_negative(self):
        with pytest.raises(ValueError, match="between 0 and 10"):
            nps_response_service.categorize_score(-1)

    def test_invalid_score_above_10(self):
        with pytest.raises(ValueError, match="between 0 and 10"):
            nps_response_service.categorize_score(11)


# ── process_response tests ──────────────────────────────────────────


class TestProcessResponse:
    @patch("app.services.nps_response_service.asana_client")
    def test_successful_response_processing(self, mock_asana, ddb_tables):
        _seed_org()
        _seed_cycle()
        _seed_nomination()
        mock_asana.update_task_custom_fields.return_value = {}

        nps_response_service.process_response(_make_payload(nps_score=9))

        # Nomination marked as responded
        nom = nps_nomination_repo.get_nomination(_ORG, _CYCLE, "alice@example.com")
        assert nom.responded is True
        assert nom.responded_at != ""

        # NpsResponse stored (anonymous — no email/name)
        responses = nps_response_repo.list_responses(_ORG, _CYCLE)
        assert len(responses) == 1
        assert responses[0].nps_score == 9
        assert responses[0].category == "Promoter"
        assert responses[0].org_id == _ORG
        assert responses[0].cycle_id == _CYCLE

        # ASANA custom fields written
        mock_asana.update_task_custom_fields.assert_called_once()
        call_args = mock_asana.update_task_custom_fields.call_args
        assert call_args[0][0] == _TASK_GID
        custom_fields = call_args[0][1]
        assert custom_fields["cf_score"] == 9
        assert custom_fields["cf_cat"] == "Promoter"
        assert custom_fields["cf_org"] == "Alpha Org"

    @patch("app.services.nps_response_service.asana_client")
    def test_detractor_response(self, mock_asana, ddb_tables):
        _seed_org()
        _seed_cycle()
        _seed_nomination()
        mock_asana.update_task_custom_fields.return_value = {}

        nps_response_service.process_response(_make_payload(nps_score=3))

        responses = nps_response_repo.list_responses(_ORG, _CYCLE)
        assert len(responses) == 1
        assert responses[0].category == "Detractor"

    @patch("app.services.nps_response_service.asana_client")
    def test_passive_response(self, mock_asana, ddb_tables):
        _seed_org()
        _seed_cycle()
        _seed_nomination()
        mock_asana.update_task_custom_fields.return_value = {}

        nps_response_service.process_response(_make_payload(nps_score=8))

        responses = nps_response_repo.list_responses(_ORG, _CYCLE)
        assert len(responses) == 1
        assert responses[0].category == "Passive"

    @patch("app.services.nps_response_service.asana_client")
    def test_unmatched_email_logs_failure(self, mock_asana, ddb_tables):
        _seed_org()
        _seed_cycle()
        # No nomination for this email

        nps_response_service.process_response(
            _make_payload(email="unknown@example.com", nps_score=7)
        )

        # No response stored
        responses = nps_response_repo.list_responses(_ORG, _CYCLE)
        assert len(responses) == 0

        # Failure logged with event_type 'unmatched_response'
        failures = nps_delivery_failure_repo.list_failures(_ORG, _CYCLE)
        assert len(failures) == 1
        assert failures[0].event_type == "unmatched_response"
        assert "unknown@example.com" in failures[0].email

        # ASANA not called
        mock_asana.update_task_custom_fields.assert_not_called()

    def test_closed_cycle_rejects_response(self, ddb_tables):
        _seed_org()
        _seed_cycle(status="closed")
        _seed_nomination()

        with pytest.raises(ValueError, match="closed"):
            nps_response_service.process_response(_make_payload())

        # No response stored
        responses = nps_response_repo.list_responses(_ORG, _CYCLE)
        assert len(responses) == 0

    def test_missing_payload_fields_raises(self, ddb_tables):
        with pytest.raises(ValueError, match="must include"):
            nps_response_service.process_response({"email": "a@b.com"})

    def test_invalid_score_raises(self, ddb_tables):
        _seed_org()
        _seed_cycle()
        _seed_nomination()

        with pytest.raises(ValueError, match="between 0 and 10"):
            nps_response_service.process_response(_make_payload(nps_score=15))

    def test_cycle_not_found_raises(self, ddb_tables):
        _seed_org()
        with pytest.raises(ValueError, match="not found"):
            nps_response_service.process_response(
                _make_payload(cycle_id="nonexistent")
            )

    @patch("app.services.nps_response_service.asana_client")
    def test_asana_failure_does_not_block_response_storage(self, mock_asana, ddb_tables):
        _seed_org()
        _seed_cycle()
        _seed_nomination()
        mock_asana.update_task_custom_fields.side_effect = RuntimeError("ASANA API error")

        # Should not raise — ASANA failure is logged but doesn't block
        nps_response_service.process_response(_make_payload(nps_score=10))

        # Response still stored
        responses = nps_response_repo.list_responses(_ORG, _CYCLE)
        assert len(responses) == 1
        assert responses[0].nps_score == 10
        assert responses[0].category == "Promoter"

        # Nomination still marked responded
        nom = nps_nomination_repo.get_nomination(_ORG, _CYCLE, "alice@example.com")
        assert nom.responded is True

    @patch("app.services.nps_response_service.asana_client")
    def test_response_anonymity_no_email_or_name(self, mock_asana, ddb_tables):
        """Verify stored NpsResponse contains no email or name fields."""
        _seed_org()
        _seed_cycle()
        _seed_nomination(email="bob@example.com", name="Bob")
        mock_asana.update_task_custom_fields.return_value = {}

        nps_response_service.process_response(
            _make_payload(email="bob@example.com", nps_score=5)
        )

        responses = nps_response_repo.list_responses(_ORG, _CYCLE)
        assert len(responses) == 1
        resp = responses[0]
        # NpsResponse dataclass should not have email or name
        assert not hasattr(resp, "email")
        assert not hasattr(resp, "name")


# ── get_responses tests ──────────────────────────────────────────────


class TestGetResponses:
    def test_returns_stored_responses(self, ddb_tables):
        resp = NpsResponse(
            org_id=_ORG,
            cycle_id=_CYCLE,
            response_id="resp-1",
            nps_score=9,
            category="Promoter",
        )
        nps_response_repo.put_response(resp)

        results = nps_response_service.get_responses(_ORG, _CYCLE)
        assert len(results) == 1
        assert results[0].response_id == "resp-1"
        assert results[0].nps_score == 9

    def test_returns_empty_for_no_responses(self, ddb_tables):
        results = nps_response_service.get_responses(_ORG, _CYCLE)
        assert results == []

    def test_returns_only_matching_org_cycle(self, ddb_tables):
        resp1 = NpsResponse(
            org_id=_ORG, cycle_id=_CYCLE,
            response_id="resp-1", nps_score=9, category="Promoter",
        )
        resp2 = NpsResponse(
            org_id="other_org", cycle_id=_CYCLE,
            response_id="resp-2", nps_score=5, category="Detractor",
        )
        nps_response_repo.put_response(resp1)
        nps_response_repo.put_response(resp2)

        results = nps_response_service.get_responses(_ORG, _CYCLE)
        assert len(results) == 1
        assert results[0].response_id == "resp-1"
