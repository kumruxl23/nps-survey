"""Tests for nps_scheduler: should_send_reminder logic and reminder_check_job."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import OrgConfig, SurveyCycle
from app.services.nps_scheduler import (
    init_scheduler,
    reminder_check_job,
    should_send_reminder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cycle(**overrides) -> SurveyCycle:
    """Build a SurveyCycle with sensible defaults for testing."""
    defaults = dict(
        org_id="org_alpha",
        cycle_id="c1",
        start_date="2024-01-01",
        end_date="2024-12-31",
        status="active",
        reminder_mode="daily",
        distributed_at="2024-06-01T00:00:00+00:00",
        last_reminder_at="",
    )
    defaults.update(overrides)
    return SurveyCycle(**defaults)


def _org(**overrides) -> OrgConfig:
    defaults = dict(
        org_id="org_alpha",
        org_name="Alpha",
        asana_project_gid="p1",
        asana_form_url="https://form.asana.com/alpha",
        custom_field_nps_score_gid="cf1",
        custom_field_category_gid="cf2",
        custom_field_org_name_gid="cf3",
    )
    defaults.update(overrides)
    return OrgConfig(**defaults)


# ---------------------------------------------------------------------------
# should_send_reminder tests
# ---------------------------------------------------------------------------

class TestShouldSendReminder:
    """Unit tests for the should_send_reminder pure function."""

    def test_returns_false_when_cycle_closed(self):
        cycle = _cycle(status="closed")
        assert should_send_reminder(cycle) is False

    def test_returns_false_when_mode_manual(self):
        cycle = _cycle(reminder_mode="manual")
        assert should_send_reminder(cycle) is False

    def test_returns_false_when_not_distributed(self):
        cycle = _cycle(distributed_at="")
        assert should_send_reminder(cycle) is False

    def test_returns_false_when_past_end_date(self):
        cycle = _cycle(end_date="2024-01-01")
        now = datetime(2024, 1, 2, tzinfo=timezone.utc)
        assert should_send_reminder(cycle, now=now) is False

    def test_returns_false_on_end_date_is_allowed(self):
        """On the end_date itself, reminders are still allowed."""
        cycle = _cycle(
            end_date="2024-06-02",
            distributed_at="2024-06-01T00:00:00+00:00",
        )
        now = datetime(2024, 6, 2, 1, 0, 0, tzinfo=timezone.utc)
        assert should_send_reminder(cycle, now=now) is True

    # -- First reminder (no last_reminder_at) --

    def test_first_reminder_daily_enough_time_elapsed(self):
        cycle = _cycle(
            reminder_mode="daily",
            distributed_at="2024-06-01T00:00:00+00:00",
            last_reminder_at="",
        )
        now = datetime(2024, 6, 2, 0, 0, 1, tzinfo=timezone.utc)  # >1 day
        assert should_send_reminder(cycle, now=now) is True

    def test_first_reminder_daily_not_enough_time(self):
        cycle = _cycle(
            reminder_mode="daily",
            distributed_at="2024-06-01T12:00:00+00:00",
            last_reminder_at="",
        )
        now = datetime(2024, 6, 2, 11, 59, 59, tzinfo=timezone.utc)  # <1 day
        assert should_send_reminder(cycle, now=now) is False

    def test_first_reminder_alternate_day(self):
        cycle = _cycle(
            reminder_mode="alternate_day",
            distributed_at="2024-06-01T00:00:00+00:00",
            last_reminder_at="",
        )
        now = datetime(2024, 6, 3, 0, 0, 1, tzinfo=timezone.utc)  # >2 days
        assert should_send_reminder(cycle, now=now) is True

    def test_first_reminder_alternate_day_not_enough(self):
        cycle = _cycle(
            reminder_mode="alternate_day",
            distributed_at="2024-06-01T00:00:00+00:00",
            last_reminder_at="",
        )
        now = datetime(2024, 6, 2, 23, 59, 59, tzinfo=timezone.utc)  # <2 days
        assert should_send_reminder(cycle, now=now) is False

    def test_first_reminder_weekly(self):
        cycle = _cycle(
            reminder_mode="weekly",
            distributed_at="2024-06-01T00:00:00+00:00",
            last_reminder_at="",
        )
        now = datetime(2024, 6, 8, 0, 0, 1, tzinfo=timezone.utc)  # >7 days
        assert should_send_reminder(cycle, now=now) is True

    def test_first_reminder_weekly_not_enough(self):
        cycle = _cycle(
            reminder_mode="weekly",
            distributed_at="2024-06-01T00:00:00+00:00",
            last_reminder_at="",
        )
        now = datetime(2024, 6, 7, 23, 59, 59, tzinfo=timezone.utc)  # <7 days
        assert should_send_reminder(cycle, now=now) is False

    # -- Subsequent reminders (has last_reminder_at) --

    def test_subsequent_reminder_daily_enough_time(self):
        cycle = _cycle(
            reminder_mode="daily",
            last_reminder_at="2024-06-05T10:00:00+00:00",
        )
        now = datetime(2024, 6, 6, 10, 0, 1, tzinfo=timezone.utc)
        assert should_send_reminder(cycle, now=now) is True

    def test_subsequent_reminder_daily_not_enough(self):
        cycle = _cycle(
            reminder_mode="daily",
            last_reminder_at="2024-06-05T10:00:00+00:00",
        )
        now = datetime(2024, 6, 6, 9, 59, 59, tzinfo=timezone.utc)
        assert should_send_reminder(cycle, now=now) is False

    def test_subsequent_reminder_weekly_enough_time(self):
        cycle = _cycle(
            reminder_mode="weekly",
            last_reminder_at="2024-06-01T00:00:00+00:00",
        )
        now = datetime(2024, 6, 8, 0, 0, 0, tzinfo=timezone.utc)  # exactly 7 days
        assert should_send_reminder(cycle, now=now) is True

    def test_exact_interval_boundary_returns_true(self):
        """Exactly at the interval boundary (>=) should return True."""
        cycle = _cycle(
            reminder_mode="daily",
            distributed_at="2024-06-01T00:00:00+00:00",
            last_reminder_at="",
        )
        now = datetime(2024, 6, 2, 0, 0, 0, tzinfo=timezone.utc)  # exactly 1 day
        assert should_send_reminder(cycle, now=now) is True


# ---------------------------------------------------------------------------
# reminder_check_job tests
# ---------------------------------------------------------------------------

class TestReminderCheckJob:
    """Tests for the scheduled reminder_check_job using mocks."""

    @patch("app.services.nps_distribution_service.send_reminder")
    @patch("app.services.nps_cycle_service.get_active_cycle")
    @patch("app.services.nps_org_config_service.list_active_orgs")
    def test_sends_reminder_when_due(self, mock_list_orgs, mock_get_cycle, mock_send):
        org = _org()
        cycle = _cycle(reminder_mode="daily")
        mock_list_orgs.return_value = [org]
        mock_get_cycle.return_value = cycle

        with patch(
            "app.services.nps_scheduler.should_send_reminder", return_value=True
        ):
            reminder_check_job()

        mock_send.assert_called_once_with(
            "org_alpha", "c1", trigger_type="automated"
        )

    @patch("app.services.nps_distribution_service.send_reminder")
    @patch("app.services.nps_cycle_service.get_active_cycle")
    @patch("app.services.nps_org_config_service.list_active_orgs")
    def test_skips_when_no_active_cycle(self, mock_list_orgs, mock_get_cycle, mock_send):
        mock_list_orgs.return_value = [_org()]
        mock_get_cycle.return_value = None

        reminder_check_job()

        mock_send.assert_not_called()

    @patch("app.services.nps_distribution_service.send_reminder")
    @patch("app.services.nps_cycle_service.get_active_cycle")
    @patch("app.services.nps_org_config_service.list_active_orgs")
    def test_skips_manual_mode(self, mock_list_orgs, mock_get_cycle, mock_send):
        cycle = _cycle(reminder_mode="manual")
        mock_list_orgs.return_value = [_org()]
        mock_get_cycle.return_value = cycle

        reminder_check_job()

        mock_send.assert_not_called()

    @patch("app.services.nps_distribution_service.send_reminder")
    @patch("app.services.nps_cycle_service.get_active_cycle")
    @patch("app.services.nps_org_config_service.list_active_orgs")
    def test_skips_when_reminder_not_due(self, mock_list_orgs, mock_get_cycle, mock_send):
        cycle = _cycle(reminder_mode="daily")
        mock_list_orgs.return_value = [_org()]
        mock_get_cycle.return_value = cycle

        with patch(
            "app.services.nps_scheduler.should_send_reminder", return_value=False
        ):
            reminder_check_job()

        mock_send.assert_not_called()

    @patch("app.services.nps_distribution_service.send_reminder")
    @patch("app.services.nps_cycle_service.get_active_cycle")
    @patch("app.services.nps_org_config_service.list_active_orgs")
    def test_handles_multiple_orgs(self, mock_list_orgs, mock_get_cycle, mock_send):
        org_a = _org(org_id="org_a")
        org_b = _org(org_id="org_b")
        cycle_a = _cycle(org_id="org_a", cycle_id="ca")
        cycle_b = _cycle(org_id="org_b", cycle_id="cb")

        mock_list_orgs.return_value = [org_a, org_b]
        mock_get_cycle.side_effect = lambda oid: (
            cycle_a if oid == "org_a" else cycle_b
        )

        with patch(
            "app.services.nps_scheduler.should_send_reminder", return_value=True
        ):
            reminder_check_job()

        assert mock_send.call_count == 2

    @patch("app.services.nps_distribution_service.send_reminder")
    @patch("app.services.nps_cycle_service.get_active_cycle")
    @patch("app.services.nps_org_config_service.list_active_orgs")
    def test_continues_on_per_org_error(self, mock_list_orgs, mock_get_cycle, mock_send):
        """If one org raises, the job should continue to the next org."""
        org_a = _org(org_id="org_a")
        org_b = _org(org_id="org_b")
        mock_list_orgs.return_value = [org_a, org_b]

        def side_effect(oid):
            if oid == "org_a":
                raise RuntimeError("boom")
            return _cycle(org_id="org_b", cycle_id="cb")

        mock_get_cycle.side_effect = side_effect

        with patch(
            "app.services.nps_scheduler.should_send_reminder", return_value=True
        ):
            reminder_check_job()

        mock_send.assert_called_once_with(
            "org_b", "cb", trigger_type="automated"
        )

    @patch("app.services.nps_org_config_service.list_active_orgs")
    def test_handles_list_orgs_failure(self, mock_list_orgs):
        """If list_active_orgs fails, the job should not crash."""
        mock_list_orgs.side_effect = RuntimeError("db down")
        # Should not raise
        reminder_check_job()


# ---------------------------------------------------------------------------
# init_scheduler tests
# ---------------------------------------------------------------------------

class TestInitScheduler:
    """Tests for init_scheduler configuration."""

    def test_skips_in_testing_mode(self):
        app = MagicMock()
        app.config = {"TESTING": True}
        result = init_scheduler(app)
        assert result is None

    @patch("app.services.nps_scheduler.os.environ.get", return_value="30")
    def test_reads_interval_from_env(self, mock_env_get):
        app = MagicMock()
        app.config = {}

        with patch("app.services.nps_scheduler.BackgroundScheduler") as MockSched:
            mock_instance = MockSched.return_value
            scheduler = init_scheduler(app)

            mock_instance.add_job.assert_called_once()
            call_kwargs = mock_instance.add_job.call_args
            trigger = call_kwargs.kwargs.get("trigger") or call_kwargs[1].get("trigger")
            assert trigger.interval.total_seconds() == 30 * 60
            mock_instance.start.assert_called_once()
            assert scheduler is mock_instance

    def test_defaults_to_60_minutes(self, monkeypatch):
        monkeypatch.delenv("NPS_SCHEDULER_INTERVAL_MINUTES", raising=False)
        app = MagicMock()
        app.config = {}

        with patch("app.services.nps_scheduler.BackgroundScheduler") as MockSched:
            mock_instance = MockSched.return_value
            init_scheduler(app)

            call_kwargs = mock_instance.add_job.call_args
            trigger = call_kwargs.kwargs.get("trigger") or call_kwargs[1].get("trigger")
            assert trigger.interval.total_seconds() == 60 * 60

    def test_max_instances_is_one(self, monkeypatch):
        monkeypatch.delenv("NPS_SCHEDULER_INTERVAL_MINUTES", raising=False)
        app = MagicMock()
        app.config = {}

        with patch("app.services.nps_scheduler.BackgroundScheduler") as MockSched:
            mock_instance = MockSched.return_value
            init_scheduler(app)

            call_kwargs = mock_instance.add_job.call_args
            assert call_kwargs.kwargs.get("max_instances") == 1
