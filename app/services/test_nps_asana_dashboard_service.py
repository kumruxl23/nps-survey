"""Tests for nps_asana_dashboard_service.

DynamoDB (org config, cycles, nominations) is mocked with moto; the Asana
API is mocked with unittest.mock.patch on asana_client functions — no
network access anywhere.
"""

from unittest.mock import patch

import pytest
from moto import mock_aws

from app.db import nps_cycle_repo, nps_nomination_repo, nps_org_config_repo
from app.db.models import Nomination, OrgConfig, SurveyCycle
from app.services import nps_asana_dashboard_service as svc


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


_ORG = "org_alpha"
_CYCLE = "cycle_h1"
_PROJECT = "proj_123"
_SECTION = "sect_ongoing"
_SCORE_GID = "cf_score"
_LEADER_GID = "cf_leader"


@pytest.fixture
def ddb(monkeypatch):
    """Tables + one org and one cycle (due date in the past by default)."""
    with mock_aws():
        nps_org_config_repo._create_table()
        nps_cycle_repo._create_table()
        nps_nomination_repo._create_table()

        nps_org_config_repo.put_org(OrgConfig(
            org_id=_ORG,
            org_name="Alpha Org",
            asana_project_gid=_PROJECT,
            asana_form_url="https://form.asana.com/alpha",
            custom_field_nps_score_gid=_SCORE_GID,
            custom_field_category_gid="cf_cat",
            custom_field_org_name_gid="cf_org",
            custom_field_leader_gid=_LEADER_GID,
        ))
        nps_cycle_repo.put_cycle(SurveyCycle(
            org_id=_ORG,
            cycle_id=_CYCLE,
            start_date="2026-01-01",
            end_date="2026-06-30",
            status="closed",
            reminder_mode="manual",
            action_due_date="2026-07-15",  # already passed
        ))
        yield


def _nominate(n):
    for i in range(n):
        nps_nomination_repo.put_nomination(Nomination(
            org_id=_ORG, cycle_id=_CYCLE, email=f"s{i}@amazon.com", name=f"S {i}",
        ))


def _task(score=None, leader="", created="2026-02-01", completed=False):
    custom_fields = []
    if score is not None:
        custom_fields.append({"gid": _SCORE_GID, "number_value": score, "display_value": str(score)})
    if leader:
        custom_fields.append({"gid": _LEADER_GID, "display_value": leader})
    return {
        "created_at": f"{created}T10:00:00.000Z",
        "completed_at": f"{created}T12:00:00.000Z" if completed else None,
        "custom_fields": custom_fields,
    }


_SECTIONS = [
    {"gid": "sect_old", "name": "H2 2025 (archived)"},
    {"gid": _SECTION, "name": "Ongoing Survey"},
]


def _mock_asana(tasks, sections=_SECTIONS):
    """Patch both asana_client calls the service makes."""
    return (
        patch("app.services.asana_client.list_sections", return_value=sections),
        patch("app.services.asana_client.list_tasks_in_section", return_value=tasks),
    )


class TestFetchAndSectionSelection:
    def test_only_ongoing_section_is_queried(self, ddb):
        p_sections, p_tasks = _mock_asana([_task(score=10, leader="L1")])
        with p_sections, p_tasks as mock_tasks:
            svc.get_dashboard_summary(_ORG, _CYCLE)
        assert mock_tasks.call_args[0][0] == _SECTION  # not sect_old

    def test_missing_ongoing_section_raises(self, ddb):
        p_sections, p_tasks = _mock_asana([], sections=[{"gid": "x", "name": "Other"}])
        with p_sections, p_tasks:
            with pytest.raises(ValueError, match="Ongoing Survey"):
                svc.get_dashboard_summary(_ORG, _CYCLE)

    def test_section_name_match_is_case_insensitive(self, ddb):
        sections = [{"gid": _SECTION, "name": "  ONGOING SURVEY "}]
        p_sections, p_tasks = _mock_asana([_task(score=9)], sections=sections)
        with p_sections, p_tasks:
            assert svc.get_dashboard_summary(_ORG, _CYCLE)["total_responses"] == 1

    def test_tasks_outside_cycle_window_excluded(self, ddb):
        tasks = [
            _task(score=10, created="2026-02-01"),   # in window
            _task(score=10, created="2025-12-31"),   # before start
            _task(score=10, created="2026-07-01"),   # after end
        ]
        p_sections, p_tasks = _mock_asana(tasks)
        with p_sections, p_tasks:
            assert svc.get_dashboard_summary(_ORG, _CYCLE)["total_responses"] == 1

    def test_unknown_org_or_cycle_raises(self, ddb):
        with pytest.raises(ValueError, match="not found"):
            svc.get_dashboard_summary("ghost_org", _CYCLE)
        with pytest.raises(ValueError, match="not found"):
            svc.get_dashboard_summary(_ORG, "ghost_cycle")


class TestDashboardSummary:
    def test_counts_nps_and_response_rate(self, ddb):
        _nominate(10)
        tasks = [
            _task(score=10, completed=True),   # promoter
            _task(score=9, completed=True),    # promoter
            _task(score=8, completed=False),   # passive
            _task(score=7, completed=False),   # passive
            _task(score=3, completed=False),   # detractor
            _task(score=None, completed=False),  # response without a score
        ]
        p_sections, p_tasks = _mock_asana(tasks)
        with p_sections, p_tasks:
            s = svc.get_dashboard_summary(_ORG, _CYCLE)

        assert s["total_nominated"] == 10          # from DynamoDB
        assert s["total_responses"] == 6           # all in-window Asana tasks
        assert s["promoters_count"] == 2
        assert s["passives_count"] == 2
        assert s["detractors_count"] == 1
        # NPS over the 5 SCORED tasks: 2/5*100 - 1/5*100 = 20.0
        assert s["nps_score"] == 20.0
        assert s["response_rate"] == 60.0          # 6 / 10 * 100
        assert s["incomplete_tasks"] == 4
        assert s["overdue_tasks"] == 4             # due date passed

    def test_zero_nominated_gives_zero_rate(self, ddb):
        p_sections, p_tasks = _mock_asana([_task(score=10)])
        with p_sections, p_tasks:
            s = svc.get_dashboard_summary(_ORG, _CYCLE)
        assert s["response_rate"] == 0.0
        assert s["total_nominated"] == 0

    def test_no_scored_tasks_gives_zero_nps(self, ddb):
        p_sections, p_tasks = _mock_asana([_task(score=None)])
        with p_sections, p_tasks:
            assert svc.get_dashboard_summary(_ORG, _CYCLE)["nps_score"] == 0.0

    def test_future_due_date_means_nothing_overdue(self, ddb):
        nps_cycle_repo.update_cycle(_ORG, _CYCLE, action_due_date="2099-01-01")
        p_sections, p_tasks = _mock_asana([_task(score=5, completed=False)])
        with p_sections, p_tasks:
            s = svc.get_dashboard_summary(_ORG, _CYCLE)
        assert s["incomplete_tasks"] == 1
        assert s["overdue_tasks"] == 0

    def test_no_due_date_means_nothing_overdue(self, ddb):
        nps_cycle_repo.update_cycle(_ORG, _CYCLE, action_due_date="")
        p_sections, p_tasks = _mock_asana([_task(score=5, completed=False)])
        with p_sections, p_tasks:
            assert svc.get_dashboard_summary(_ORG, _CYCLE)["overdue_tasks"] == 0

    def test_completed_task_never_overdue(self, ddb):
        p_sections, p_tasks = _mock_asana([_task(score=5, completed=True)])
        with p_sections, p_tasks:
            s = svc.get_dashboard_summary(_ORG, _CYCLE)
        assert s["incomplete_tasks"] == 0
        assert s["overdue_tasks"] == 0


class TestLeaderBreakdown:
    def test_grouped_and_sorted_by_leader(self, ddb):
        tasks = [
            _task(score=10, leader="Beta Lead", completed=True),
            _task(score=6, leader="Alpha Lead", completed=False),
            _task(score=9, leader="Alpha Lead", completed=True),
            _task(score=8, leader="", completed=True),  # -> Unassigned
        ]
        p_sections, p_tasks = _mock_asana(tasks)
        with p_sections, p_tasks:
            rows = svc.get_leader_breakdown(_ORG, _CYCLE)

        assert [r["leader_name"] for r in rows] == ["Alpha Lead", "Beta Lead", "Unassigned"]
        alpha = rows[0]
        assert alpha["responses"] == 2
        assert alpha["promoters"] == 1 and alpha["detractors"] == 1
        assert alpha["nps"] == 0.0            # 50 - 50
        assert alpha["action_complete"] is False  # one task incomplete
        assert alpha["is_overdue"] is True        # due date passed
        beta = rows[1]
        assert beta["nps"] == 100.0
        assert beta["action_complete"] is True
        assert beta["is_overdue"] is False

    def test_empty_when_no_tasks(self, ddb):
        p_sections, p_tasks = _mock_asana([])
        with p_sections, p_tasks:
            assert svc.get_leader_breakdown(_ORG, _CYCLE) == []


class TestNpsDistribution:
    def test_stacked_counts_per_leader(self, ddb):
        tasks = [
            _task(score=10, leader="L1"),
            _task(score=7, leader="L1"),
            _task(score=2, leader="L2"),
        ]
        p_sections, p_tasks = _mock_asana(tasks)
        with p_sections, p_tasks:
            dist = svc.get_nps_distribution(_ORG, _CYCLE)
        assert dist == [
            {"leader_name": "L1", "promoters": 1, "passives": 1, "detractors": 0},
            {"leader_name": "L2", "promoters": 0, "passives": 0, "detractors": 1},
        ]


class TestActionTracker:
    def test_completed_vs_incomplete_per_leader(self, ddb):
        tasks = [
            _task(score=10, leader="L1", completed=True),
            _task(score=8, leader="L1", completed=False),
            _task(score=9, leader="L2", completed=True),
        ]
        p_sections, p_tasks = _mock_asana(tasks)
        with p_sections, p_tasks:
            rows = svc.get_action_tracker_status(_ORG, _CYCLE)
        assert rows == [
            {"leader_name": "L1", "completed": 1, "incomplete": 1},
            {"leader_name": "L2", "completed": 1, "incomplete": 0},
        ]
