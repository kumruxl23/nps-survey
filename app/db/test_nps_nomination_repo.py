import pytest
from moto import mock_aws

from app.db.models import Nomination
from app.db import nps_nomination_repo


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
        nps_nomination_repo._create_table()
        yield


def _make_nomination(org_id="org_alpha", cycle_id="cycle_001", email="alice@example.com", **overrides):
    defaults = dict(
        org_id=org_id,
        cycle_id=cycle_id,
        email=email,
        name="Alice Smith",
        slack_user_id="",
        responded=False,
        responded_at="",
    )
    defaults.update(overrides)
    return Nomination(**defaults)


class TestPutAndGetNomination:
    def test_put_and_get_round_trip(self, ddb_table):
        nom = _make_nomination()
        nps_nomination_repo.put_nomination(nom)

        result = nps_nomination_repo.get_nomination("org_alpha", "cycle_001", "alice@example.com")
        assert result is not None
        assert result.org_id == "org_alpha"
        assert result.cycle_id == "cycle_001"
        assert result.email == "alice@example.com"
        assert result.name == "Alice Smith"
        assert result.responded is False
        assert result.responded_at == ""
        assert result.created_at != ""

    def test_get_nonexistent_returns_none(self, ddb_table):
        result = nps_nomination_repo.get_nomination("org_alpha", "cycle_001", "nobody@example.com")
        assert result is None

    def test_put_sets_created_at_when_empty(self, ddb_table):
        nom = _make_nomination(created_at="")
        nps_nomination_repo.put_nomination(nom)
        result = nps_nomination_repo.get_nomination("org_alpha", "cycle_001", "alice@example.com")
        assert result.created_at != ""

    def test_put_preserves_explicit_created_at(self, ddb_table):
        nom = _make_nomination(created_at="2024-01-01T00:00:00+00:00")
        nps_nomination_repo.put_nomination(nom)
        result = nps_nomination_repo.get_nomination("org_alpha", "cycle_001", "alice@example.com")
        assert result.created_at == "2024-01-01T00:00:00+00:00"


class TestListNominations:
    def test_list_nominations_for_org_cycle(self, ddb_table):
        nps_nomination_repo.put_nomination(_make_nomination(email="a@example.com", name="A"))
        nps_nomination_repo.put_nomination(_make_nomination(email="b@example.com", name="B"))
        nps_nomination_repo.put_nomination(
            _make_nomination(org_id="org_beta", email="c@example.com", name="C")
        )

        noms = nps_nomination_repo.list_nominations("org_alpha", "cycle_001")
        emails = {n.email for n in noms}
        assert emails == {"a@example.com", "b@example.com"}

    def test_list_nominations_empty(self, ddb_table):
        assert nps_nomination_repo.list_nominations("org_alpha", "cycle_001") == []

    def test_list_nominations_different_cycles(self, ddb_table):
        nps_nomination_repo.put_nomination(_make_nomination(cycle_id="c1", email="a@example.com"))
        nps_nomination_repo.put_nomination(_make_nomination(cycle_id="c2", email="b@example.com"))

        noms_c1 = nps_nomination_repo.list_nominations("org_alpha", "c1")
        noms_c2 = nps_nomination_repo.list_nominations("org_alpha", "c2")
        assert len(noms_c1) == 1
        assert noms_c1[0].email == "a@example.com"
        assert len(noms_c2) == 1
        assert noms_c2[0].email == "b@example.com"


class TestDeleteNomination:
    def test_delete_existing(self, ddb_table):
        nps_nomination_repo.put_nomination(_make_nomination())
        nps_nomination_repo.delete_nomination("org_alpha", "cycle_001", "alice@example.com")

        result = nps_nomination_repo.get_nomination("org_alpha", "cycle_001", "alice@example.com")
        assert result is None

    def test_delete_preserves_others(self, ddb_table):
        nps_nomination_repo.put_nomination(_make_nomination(email="a@example.com"))
        nps_nomination_repo.put_nomination(_make_nomination(email="b@example.com"))
        nps_nomination_repo.delete_nomination("org_alpha", "cycle_001", "a@example.com")

        noms = nps_nomination_repo.list_nominations("org_alpha", "cycle_001")
        assert len(noms) == 1
        assert noms[0].email == "b@example.com"

    def test_delete_nonexistent_is_noop(self, ddb_table):
        nps_nomination_repo.delete_nomination("org_alpha", "cycle_001", "nobody@example.com")
        # No error raised


class TestUpdateResponded:
    def test_update_responded_sets_flag_and_timestamp(self, ddb_table):
        nps_nomination_repo.put_nomination(_make_nomination())
        nps_nomination_repo.update_responded("org_alpha", "cycle_001", "alice@example.com")

        result = nps_nomination_repo.get_nomination("org_alpha", "cycle_001", "alice@example.com")
        assert result.responded is True
        assert result.responded_at != ""

    def test_update_responded_preserves_other_fields(self, ddb_table):
        nps_nomination_repo.put_nomination(
            _make_nomination(slack_user_id="U12345")
        )
        nps_nomination_repo.update_responded("org_alpha", "cycle_001", "alice@example.com")

        result = nps_nomination_repo.get_nomination("org_alpha", "cycle_001", "alice@example.com")
        assert result.responded is True
        assert result.name == "Alice Smith"
        assert result.slack_user_id == "U12345"


class TestQueryNonRespondents:
    def test_returns_only_non_respondents(self, ddb_table):
        nps_nomination_repo.put_nomination(_make_nomination(email="a@example.com", responded=False))
        nps_nomination_repo.put_nomination(_make_nomination(email="b@example.com", responded=True))
        nps_nomination_repo.put_nomination(_make_nomination(email="c@example.com", responded=False))

        non_resp = nps_nomination_repo.query_non_respondents("org_alpha", "cycle_001")
        emails = {n.email for n in non_resp}
        assert emails == {"a@example.com", "c@example.com"}

    def test_returns_empty_when_all_responded(self, ddb_table):
        nps_nomination_repo.put_nomination(_make_nomination(email="a@example.com", responded=True))
        nps_nomination_repo.put_nomination(_make_nomination(email="b@example.com", responded=True))

        non_resp = nps_nomination_repo.query_non_respondents("org_alpha", "cycle_001")
        assert non_resp == []

    def test_returns_empty_for_no_nominations(self, ddb_table):
        assert nps_nomination_repo.query_non_respondents("org_alpha", "cycle_001") == []

    def test_after_update_responded_excludes_from_non_respondents(self, ddb_table):
        nps_nomination_repo.put_nomination(_make_nomination(email="a@example.com"))
        nps_nomination_repo.put_nomination(_make_nomination(email="b@example.com"))

        nps_nomination_repo.update_responded("org_alpha", "cycle_001", "a@example.com")

        non_resp = nps_nomination_repo.query_non_respondents("org_alpha", "cycle_001")
        emails = {n.email for n in non_resp}
        assert emails == {"b@example.com"}
