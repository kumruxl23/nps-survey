from dataclasses import dataclass, field
from typing import Literal

ReminderMode = Literal["daily", "alternate_day", "weekly", "manual"]
CycleStatus = Literal["active", "closed"]
NpsCategory = Literal["Promoter", "Passive", "Detractor"]
TriggerType = Literal["automated", "manual"]
ReminderChannel = Literal["email", "slack"]


@dataclass
class OrgConfig:
    org_id: str
    org_name: str
    asana_project_gid: str
    asana_form_url: str
    custom_field_nps_score_gid: str
    custom_field_category_gid: str
    custom_field_org_name_gid: str
    quip_doc_id: str = ""
    reminder_channels: list[ReminderChannel] = field(default_factory=lambda: ["email"])
    slack_bot_token: str = ""
    auto_add_unmatched: bool = False  # auto-add respondents not on nomination list
    is_active: bool = True
    created_at: str = ""


@dataclass
class SurveyCycle:
    org_id: str
    cycle_id: str
    start_date: str
    end_date: str
    status: CycleStatus
    reminder_mode: ReminderMode
    asana_project_gid: str = ""
    last_reminder_at: str = ""
    distributed_at: str = ""
    asana_form_url: str = ""
    quip_doc_id: str = ""
    cycle_name: str = ""  # e.g. "Q2 2025"
    created_at: str = ""


@dataclass
class ImportResult:
    imported_count: int
    skipped_duplicates: int
    total_in_source: int


@dataclass
class Nomination:
    org_id: str
    cycle_id: str
    email: str
    name: str
    leader: str = ""  # leader this stakeholder's response is tagged against
    slack_user_id: str = ""
    responded: bool = False
    responded_at: str = ""
    created_at: str = ""


@dataclass
class NpsResponse:
    org_id: str
    cycle_id: str
    response_id: str
    nps_score: int
    category: NpsCategory
    leader: str = ""  # leader this response is tagged against
    feedback_text: str = ""
    recorded_at: str = ""


@dataclass
class ReminderLog:
    org_id: str
    cycle_id: str
    log_id: str
    sent_at: str
    trigger_type: TriggerType
    recipient_count: int
    channels: list[ReminderChannel] = field(default_factory=list)
    failures: str = "[]"


@dataclass
class NpsSummary:
    org_id: str
    cycle_id: str
    total_nominated: int
    total_responded: int
    promoter_count: int
    passive_count: int
    detractor_count: int
    nps_score: float
    response_rate: float
    cycle_name: str = ""


@dataclass
class DeliveryFailure:
    org_id: str
    cycle_id: str
    failure_id: str
    email: str
    error_reason: str
    event_type: str  # "distribution", "reminder", or "unmatched_response"
    channel: str  # "email" or "slack"
    occurred_at: str = ""


@dataclass
class SlackResult:
    ok: bool
    error: str = ""


@dataclass
class EmailResult:
    ok: bool
    error: str = ""


@dataclass
class DistributionResult:
    sent_count: int
    failed_count: int
    already_distributed: bool = False


@dataclass
class ReminderResult:
    email_sent_count: int = 0
    slack_sent_count: int = 0
    failed_count: int = 0
    channels_used: list[str] = field(default_factory=list)
