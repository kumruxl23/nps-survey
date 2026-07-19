"""Flask blueprint for NPS Survey Automation routes.

Provides endpoints for org configuration, nominations, survey cycles,
distribution, reminders, ASANA webhook processing, and dashboard data.
All routes delegate to the service layer and return JSON responses.
"""

import functools
import logging
import os

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from app.services import (
    nps_cycle_service,
    nps_dashboard_service,
    nps_distribution_service,
    nps_leader_service,
    nps_nomination_service,
    nps_org_config_service,
    nps_response_service,
    nps_share_link_service,
)
from app.services import asana_client
from app.services import file_import_service
from app.nps.auth_routes import login_required, role_required

logger = logging.getLogger(__name__)

nps_bp = Blueprint(
    "nps",
    __name__,
    url_prefix="/nps",
    template_folder="../templates",
)


# ---------------------------------------------------------------------------
# Org configuration routes
# ---------------------------------------------------------------------------


@nps_bp.route("/orgs", methods=["GET"])
@login_required
def list_orgs():
    """List all configured orgs.

    The slack_bot_token is intentionally redacted - the UI only needs
    to know whether one is configured, not the value itself.
    """
    try:
        orgs = nps_org_config_service.list_all_orgs()
        out = []
        for o in orgs:
            d = vars(o).copy()
            token = d.pop("slack_bot_token", "") or ""
            d["slack_bot_token_set"] = bool(token)
            out.append(d)
        return jsonify(out)
    except Exception as exc:
        logger.exception("Error listing orgs")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/orgs/add", methods=["POST"])
@role_required("admin")
def add_org():
    """Add a new org configuration."""
    try:
        data = request.json or {}
        org = nps_org_config_service.add_org(
            org_id=data.get("org_id", ""),
            org_name=data.get("org_name", ""),
            asana_project_gid=data.get("asana_project_gid", ""),
            asana_form_url=data.get("asana_form_url", ""),
            custom_field_nps_score_gid=data.get("custom_field_nps_score_gid", ""),
            custom_field_category_gid=data.get("custom_field_category_gid", ""),
            custom_field_org_name_gid=data.get("custom_field_org_name_gid", ""),
            quip_doc_id=data.get("quip_doc_id", ""),
        )
        return jsonify(vars(org)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error adding org")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/orgs/update", methods=["POST"])
@role_required("admin")
def update_org():
    """Update an existing org's configuration.

    Accepts an allowlisted set of fields. ``reminder_channels`` is
    coerced from CSV/list and validated against {'email', 'slack'}.
    ``slack_bot_token`` is stored as-is; clients should send the empty
    string to clear it. Empty string values for other fields will
    overwrite the existing value, so callers should omit a field they
    don't want to change.
    """
    ALLOWED_FIELDS = {
        "org_name",
        "asana_project_gid",
        "asana_form_url",
        "quip_doc_id",
        "custom_field_nps_score_gid",
        "custom_field_category_gid",
        "custom_field_org_name_gid",
        "custom_field_leader_gid",
        "custom_field_feedback_gid",
        "custom_field_what_missing_gid",
        "slack_bot_token",
        "reminder_channels",
        "auto_add_unmatched",
    }
    VALID_CHANNELS = {"email", "slack"}

    try:
        data = request.json or {}
        org_id = data.pop("org_id", None)
        if not org_id:
            return jsonify({"error": "org_id is required"}), 400

        # Drop any field the client tried to sneak in that we don't manage here.
        unknown = set(data.keys()) - ALLOWED_FIELDS
        if unknown:
            return jsonify({"error": f"Unknown fields: {sorted(unknown)}"}), 400

        # Normalize reminder_channels: accept list or CSV string
        if "reminder_channels" in data:
            raw = data["reminder_channels"]
            if isinstance(raw, str):
                raw = [c.strip() for c in raw.split(",") if c.strip()]
            if not isinstance(raw, list) or not raw:
                return jsonify({"error": "reminder_channels must be a non-empty list"}), 400
            channels = [c.lower() for c in raw]
            invalid = [c for c in channels if c not in VALID_CHANNELS]
            if invalid:
                return jsonify({"error": f"Invalid channels: {invalid}. Valid: {sorted(VALID_CHANNELS)}"}), 400
            data["reminder_channels"] = channels

        if "auto_add_unmatched" in data:
            data["auto_add_unmatched"] = bool(data["auto_add_unmatched"])

        org = nps_org_config_service.update_org(org_id, **data)
        return jsonify(vars(org))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error updating org")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/orgs/remove", methods=["POST"])
@role_required("admin")
def remove_org():
    """Deactivate an org configuration."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        if not org_id:
            return jsonify({"error": "org_id is required"}), 400
        nps_org_config_service.deactivate_org(org_id)
        return jsonify({"status": "deactivated", "org_id": org_id})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error removing org")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Nomination routes
# ---------------------------------------------------------------------------


@nps_bp.route("/nominations", methods=["GET"])
@login_required
def list_nominations():
    """View nomination list for a given org/cycle."""
    try:
        org_id = request.args.get("org_id", "")
        cycle_id = request.args.get("cycle_id", "")
        if not org_id or not cycle_id:
            return jsonify({"error": "org_id and cycle_id query params are required"}), 400
        nominations = nps_nomination_service.list_nominations(org_id, cycle_id)
        return jsonify([vars(n) for n in nominations])
    except Exception as exc:
        logger.exception("Error listing nominations")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominations/import-quip", methods=["POST"])
@role_required("admin", "editor")
def import_quip():
    """Import stakeholders from a Quip document (legacy)."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        quip_doc_id = data.get("quip_doc_id", "")
        if not all([org_id, cycle_id, quip_doc_id]):
            return jsonify({"error": "org_id, cycle_id, and quip_doc_id are required"}), 400
        result = nps_nomination_service.import_from_quip(org_id, cycle_id, quip_doc_id)
        return jsonify(vars(result))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error importing from Quip")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominations/upload", methods=["POST"])
@role_required("admin", "editor")
def upload_nominations():
    """Import stakeholders from an uploaded Excel/CSV file.

    Expects multipart form data with:
        - file: The Excel (.xlsx) or CSV file
        - org_id: Organization identifier
        - cycle_id: Survey cycle identifier
    """
    try:
        org_id = request.form.get("org_id", "")
        cycle_id = request.form.get("cycle_id", "")
        if not org_id or not cycle_id:
            return jsonify({"error": "org_id and cycle_id are required"}), 400

        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify({"error": "No file uploaded"}), 400

        file_bytes = uploaded.read()
        result = file_import_service.import_from_excel(
            org_id, cycle_id, file_bytes, uploaded.filename,
        )
        return jsonify(vars(result))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error uploading nominations file")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominations/add", methods=["POST"])
@role_required("admin", "editor")
def add_nomination():
    """Manually add a single stakeholder nomination."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        name = data.get("name", "")
        email = data.get("email", "")
        if not all([org_id, cycle_id, name, email]):
            return jsonify({"error": "org_id, cycle_id, name, and email are required"}), 400
        nomination = nps_nomination_service.add_stakeholder(org_id, cycle_id, name, email)
        return jsonify(vars(nomination)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error adding nomination")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominations/remove", methods=["POST"])
@role_required("admin", "editor")
def remove_nomination():
    """Remove a stakeholder from the nomination list."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        email = data.get("email", "")
        if not all([org_id, cycle_id, email]):
            return jsonify({"error": "org_id, cycle_id, and email are required"}), 400
        nps_nomination_service.remove_stakeholder(org_id, cycle_id, email)
        return jsonify({"status": "removed", "email": email})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error removing nomination")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Leader roster + self-serve nomination form routes
# ---------------------------------------------------------------------------


def login_or_share_token(f):
    """Allow a logged-in session OR a valid nomination-form share token.

    The token comes from the ``token`` query parameter (capability URL),
    so leaders without app accounts can use the form via a shared link.
    Only the nomination form routes use this — everything else stays
    session-only.
    """

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user" in session:
            return f(*args, **kwargs)
        if nps_share_link_service.verify_token(request.args.get("token", "")):
            return f(*args, **kwargs)
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for("auth.login_page"))

    return wrapper


@nps_bp.route("/leaders", methods=["GET"])
@login_required
def list_leaders():
    """List the leader roster used by the nomination form."""
    try:
        return jsonify(nps_leader_service.list_leaders())
    except Exception as exc:
        logger.exception("Error listing leaders")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/leaders/add", methods=["POST"])
@role_required("admin", "editor")
def add_leader():
    """Add a leader to the roster."""
    try:
        data = request.json or {}
        leader = nps_leader_service.add_leader(
            alias=data.get("alias", ""), name=data.get("name", "")
        )
        return jsonify(leader), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@nps_bp.route("/leaders/remove", methods=["POST"])
@role_required("admin", "editor")
def remove_leader():
    """Deactivate a leader on the roster."""
    data = request.json or {}
    alias = data.get("alias", "")
    if not alias:
        return jsonify({"error": "alias is required"}), 400
    nps_leader_service.remove_leader(alias)
    return jsonify({"status": "removed", "alias": alias})


@nps_bp.route("/nominate/view", methods=["GET"])
@login_or_share_token
def nominate_view():
    """Render the self-serve leader nomination form."""
    return render_template("nps_leader_nominate.html")


@nps_bp.route("/nominate/share-link/rotate", methods=["POST"])
@role_required("admin")
def rotate_share_link():
    """Invalidate the current share link and issue a fresh one."""
    token = nps_share_link_service.rotate_token()
    return jsonify({"share_path": f"/nps/nominate/view?token={token}"})


@nps_bp.route("/nominate/invite", methods=["POST"])
@role_required("admin", "editor")
def send_nomination_invite():
    """Email all roster leaders the form link with a nomination deadline."""
    try:
        data = request.json or {}
        result = nps_leader_service.send_nomination_invite(
            base_url=request.host_url,
            deadline=data.get("deadline", ""),
            note=data.get("note", ""),
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error sending nomination invite")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominate/context", methods=["GET"])
@login_or_share_token
def nominate_context():
    """Data the nomination form needs: orgs with active cycles + leaders."""
    try:
        orgs = []
        for org in nps_org_config_service.list_active_orgs():
            cycle = nps_cycle_service.get_active_cycle(org.org_id)
            orgs.append({
                "org_id": org.org_id,
                "org_name": org.org_name,
                "active_cycle": (
                    {
                        "cycle_id": cycle.cycle_id,
                        "cycle_name": cycle.cycle_name or cycle.cycle_id,
                        "end_date": cycle.end_date,
                    }
                    if cycle
                    else None
                ),
            })
        payload = {"orgs": orgs, "leaders": nps_leader_service.list_leaders()}
        # Admins/editors get the shareable capability URL for the form so
        # they can send it to leaders (who have no app accounts).
        if session.get("user", {}).get("role") in ("admin", "editor"):
            token = nps_share_link_service.get_or_create_token()
            payload["share_path"] = f"/nps/nominate/view?token={token}"
        return jsonify(payload)
    except Exception as exc:
        logger.exception("Error building nomination form context")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominate/list", methods=["GET"])
@login_or_share_token
def nominate_list():
    """List active-cycle nominations under one leader (for the form's table)."""
    try:
        org_id = request.args.get("org_id", "")
        leader = request.args.get("leader", "")
        if not org_id or not leader:
            return jsonify({"error": "org_id and leader query params are required"}), 400
        cycle = nps_cycle_service.get_active_cycle(org_id)
        if not cycle:
            return jsonify({"error": f"No active cycle for org '{org_id}'"}), 404
        from app.services.nomination_keys import base_email

        rows = nps_nomination_service.list_nominations_for_leader(
            org_id, cycle.cycle_id, leader
        )
        return jsonify([
            {
                "email": base_email(n.email),
                "name": n.name,
                "designation": n.designation,
                "nominated_by": n.nominated_by,
                "created_at": n.created_at,
            }
            for n in rows
        ])
    except Exception as exc:
        logger.exception("Error listing leader nominations")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominate/submit", methods=["POST"])
@login_or_share_token
def nominate_submit():
    """Submit a stakeholder nomination from the self-serve form.

    Returns 409 with the existing row's details when the stakeholder is
    already nominated under the selected leader (first come, first served).
    """
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle = nps_cycle_service.get_active_cycle(org_id) if org_id else None
        if not cycle:
            return jsonify({"error": "No active survey cycle for this org"}), 400

        nomination = nps_nomination_service.nominate_stakeholder(
            org_id=org_id,
            cycle_id=cycle.cycle_id,
            stakeholder_alias=data.get("stakeholder_alias", ""),
            name=data.get("name", ""),
            leader=data.get("leader", ""),
            nominated_by=data.get("nominated_by", ""),
            designation=data.get("designation", ""),
        )
        return jsonify(vars(nomination)), 201
    except nps_nomination_service.DuplicateNominationError as exc:
        existing = exc.existing
        return jsonify({
            "error": str(exc),
            "duplicate": True,
            "existing": {
                "name": existing.name,
                "leader": existing.leader,
                "nominated_by": existing.nominated_by,
                "created_at": existing.created_at,
            },
        }), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error submitting nomination")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominate/remove", methods=["POST"])
@login_or_share_token
def nominate_remove():
    """Remove a form nomination (admin/editor, the nominator, or the leader)."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle = nps_cycle_service.get_active_cycle(org_id) if org_id else None
        if not cycle:
            return jsonify({"error": "No active survey cycle for this org"}), 400

        role = session.get("user", {}).get("role", "")
        nps_nomination_service.remove_leader_nomination(
            org_id=org_id,
            cycle_id=cycle.cycle_id,
            stakeholder_alias=data.get("stakeholder_alias", ""),
            leader=data.get("leader", ""),
            requested_by=data.get("requested_by", ""),
            is_privileged=role in ("admin", "editor"),
        )
        return jsonify({"status": "removed"})
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error removing nomination")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Cycle routes
# ---------------------------------------------------------------------------


@nps_bp.route("/cycles", methods=["GET"])
@login_required
def list_cycles():
    """List survey cycles for a given org."""
    try:
        org_id = request.args.get("org_id", "")
        if not org_id:
            return jsonify({"error": "org_id query param is required"}), 400
        cycles = nps_cycle_service.list_cycles(org_id)
        return jsonify([vars(c) for c in cycles])
    except Exception as exc:
        logger.exception("Error listing cycles")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/cycles/create", methods=["POST"])
@role_required("admin", "editor")
def create_cycle():
    """Create a new survey cycle."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        start_date = data.get("start_date", "")
        end_date = data.get("end_date", "")
        if not all([org_id, start_date, end_date]):
            return jsonify({"error": "org_id, start_date, and end_date are required"}), 400
        cycle_name = data.get("cycle_name", "")
        cycle = nps_cycle_service.create_cycle(org_id, start_date, end_date, cycle_name=cycle_name)
        return jsonify(vars(cycle)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error creating cycle")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/cycles/close", methods=["POST"])
@role_required("admin", "editor")
def close_cycle():
    """Close a survey cycle."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        if not all([org_id, cycle_id]):
            return jsonify({"error": "org_id and cycle_id are required"}), 400
        nps_cycle_service.close_cycle(org_id, cycle_id)
        return jsonify({"status": "closed", "org_id": org_id, "cycle_id": cycle_id})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error closing cycle")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/cycles/reminder-config", methods=["POST"])
@role_required("admin", "editor")
def update_reminder_config():
    """Update the reminder mode for a cycle."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        mode = data.get("mode", "")
        if not all([org_id, cycle_id, mode]):
            return jsonify({"error": "org_id, cycle_id, and mode are required"}), 400
        nps_cycle_service.update_reminder_mode(org_id, cycle_id, mode)
        return jsonify({"status": "updated", "org_id": org_id, "cycle_id": cycle_id, "mode": mode})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error updating reminder config")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Distribution and reminder routes
# ---------------------------------------------------------------------------


@nps_bp.route("/distribute", methods=["POST"])
@role_required("admin", "editor")
def distribute_survey():
    """Distribute the NPS survey to nominated stakeholders."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        if not all([org_id, cycle_id]):
            return jsonify({"error": "org_id and cycle_id are required"}), 400
        result = nps_distribution_service.distribute_survey(org_id, cycle_id)
        return jsonify(vars(result))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error distributing survey")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/remind", methods=["POST"])
@role_required("admin", "editor")
def send_reminder():
    """Send a manual reminder to non-respondent stakeholders."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        if not all([org_id, cycle_id]):
            return jsonify({"error": "org_id and cycle_id are required"}), 400

        # Guardrail: refuse if the sender is the placeholder default. SES would
        # reject it anyway; this gives a clearer error to the operator.
        from_addr = os.environ.get("NPS_FROM_ADDRESS", "")
        if not from_addr or "example.com" in from_addr.lower():
            return jsonify({
                "error": (
                    "NPS_FROM_ADDRESS is not configured (or is the example.com "
                    "placeholder). Set it to a verified SES sender on the EC2 "
                    "service unit before sending real reminders."
                )
            }), 503

        result = nps_distribution_service.send_reminder(org_id, cycle_id, trigger_type="manual")
        return jsonify(vars(result))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error sending reminder")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/remind/test", methods=["POST"])
@role_required("admin", "editor")
def send_test_reminder():
    """Send a TEST reminder to a fixed recipient (default: kumruxl@).

    For demoing the reminder feature without emailing real stakeholders.
    Optional body: {"org_id": ..., "cycle_id": ..., "recipient": ...}.
    """
    try:
        data = request.json or {}
        org_id = data.get("org_id") or None
        cycle_id = data.get("cycle_id") or None
        recipient = data.get("recipient") or None

        from_addr = os.environ.get("NPS_FROM_ADDRESS", "")
        if not from_addr or "example.com" in from_addr.lower():
            return jsonify({
                "error": (
                    "NPS_FROM_ADDRESS is not configured (or is the example.com "
                    "placeholder). Set it to a verified SES sender before sending "
                    "a test reminder."
                )
            }), 503

        result = nps_distribution_service.send_test_reminder(org_id, cycle_id, recipient)
        return jsonify(result)
    except Exception as exc:
        logger.exception("Error sending test reminder")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/remind/targeted", methods=["POST"])
@role_required("admin", "editor")
def send_targeted_reminder():
    """Send a reminder to a caller-supplied list of stakeholder emails.

    Body JSON:
        org_id (str): required
        cycle_id (str): required
        emails (list[str]): required — emails to remind. Any that aren't
            current non-respondents for this org+cycle are silently dropped.

    Returns:
        ReminderResult-shaped dict on success.
    """
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        emails = data.get("emails") or []
        if not org_id or not cycle_id:
            return jsonify({"error": "org_id and cycle_id are required"}), 400
        if not isinstance(emails, list) or not emails:
            return jsonify({"error": "emails (non-empty list) is required"}), 400

        from_addr = os.environ.get("NPS_FROM_ADDRESS", "")
        if not from_addr or "example.com" in from_addr.lower():
            return jsonify({
                "error": (
                    "NPS_FROM_ADDRESS is not configured (or is the example.com "
                    "placeholder). Set it to a verified SES sender."
                )
            }), 503

        result = nps_distribution_service.send_targeted_reminder(
            org_id, cycle_id, emails, trigger_type="manual",
        )
        return jsonify(vars(result))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error sending targeted reminder")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/pending", methods=["GET"])
@login_required
def list_pending_stakeholders():
    """List non-respondent stakeholders for an org+cycle.

    Query params:
        org_id (str): required
        cycle_id (str): required
        leader (str): optional — filter to one leader's pending stakeholders

    Returns:
        List of {email, name, leader} dicts.
    """
    org_id = request.args.get("org_id", "")
    cycle_id = request.args.get("cycle_id", "")
    leader_filter = request.args.get("leader", "").strip()

    if not org_id or not cycle_id:
        return jsonify({"error": "org_id and cycle_id are required"}), 400

    pending = nps_nomination_service.get_reminder_list(org_id, cycle_id)
    if leader_filter:
        pending = [n for n in pending if (n.leader or "") == leader_filter]

    # Strip multi-leader suffix from the displayed email so the UI shows
    # the deliverable address. The internal sort-key (with suffix) is
    # passed through as `nomination_key` for callers that need to send
    # to that specific leader-relationship.
    from app.services.nomination_keys import base_email

    return jsonify([
        {
            "email": base_email(n.email),
            "nomination_key": n.email,
            "name": n.name,
            "leader": n.leader or "",
        }
        for n in pending
    ])


# ---------------------------------------------------------------------------
# Manual response recording
# ---------------------------------------------------------------------------


@nps_bp.route("/responses/record", methods=["POST"])
@role_required("admin", "editor")
def record_response():
    """Manually record an NPS response for a stakeholder."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        email = data.get("email", "")
        nps_score = data.get("nps_score")
        if not all([org_id, cycle_id, email]) or nps_score is None:
            return jsonify({"error": "org_id, cycle_id, email, and nps_score are required"}), 400
        nps_response_service.process_response({
            "org_id": org_id,
            "cycle_id": cycle_id,
            "email": email,
            "nps_score": int(nps_score),
            "task_gid": "manual_entry",
        })
        return jsonify({"status": "recorded", "email": email, "nps_score": nps_score})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error recording response")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/responses/view", methods=["GET"])
@role_required("admin", "editor")
def responses_view():
    """Render the responses management page."""
    return render_template("nps_responses.html")


@nps_bp.route("/responses", methods=["GET"])
@login_required
def list_responses_for_dashboard():
    """List responses for an org+cycle, optionally filtered by leader.

    Query params:
        org_id (str): required
        cycle_id (str): required
        leader (str): optional — filter to responses tagged against one leader
        category (str): optional — Promoter / Passive / Detractor

    Returns a list of {response_id, leader, nps_score, category, feedback_text,
    recorded_at, admin_comment} dicts. No email/name fields (anonymity by design).
    """
    org_id = request.args.get("org_id", "")
    cycle_id = request.args.get("cycle_id", "")
    leader_filter = (request.args.get("leader") or "").strip()
    category_filter = (request.args.get("category") or "").strip()

    if not org_id or not cycle_id:
        return jsonify({"error": "org_id and cycle_id are required"}), 400

    responses = nps_response_service.get_responses(org_id, cycle_id)
    if leader_filter:
        responses = [r for r in responses if (r.leader or "") == leader_filter]
    if category_filter:
        responses = [r for r in responses if r.category == category_filter]

    # Sort: leader name asc, then recorded_at desc (newest first within a leader)
    responses.sort(key=lambda r: (r.leader or "", -1 * (
        # crude descending sort — convert iso timestamp to a comparable string
        # then negate by inverting in tuple ordering below
        0
    )))
    responses.sort(key=lambda r: ((r.leader or ""), r.recorded_at or ""), reverse=False)
    # The above compounds: primary leader asc, then recorded_at asc as a tiebreaker.
    # Reverse the recorded_at pass on the client side if needed, or do it here:
    responses_sorted: list = []
    by_leader: dict[str, list] = {}
    for r in responses:
        by_leader.setdefault(r.leader or "Unassigned", []).append(r)
    for leader_key in sorted(by_leader.keys()):
        for r in sorted(by_leader[leader_key], key=lambda x: x.recorded_at or "", reverse=True):
            responses_sorted.append(r)

    return jsonify([
        {
            "response_id": r.response_id,
            "leader": r.leader or "",
            "respondent_name": getattr(r, "respondent_name", "") or "",
            "nps_score": r.nps_score,
            "category": r.category,
            "feedback_text": r.feedback_text or "",
            "what_missing_text": getattr(r, "what_missing_text", "") or "",
            "recorded_at": r.recorded_at or "",
            "admin_comment": getattr(r, "admin_comment", "") or "",
        }
        for r in responses_sorted
    ])


@nps_bp.route("/responses/comment", methods=["POST"])
@role_required("admin", "editor")
def update_response_comment():
    """Set or clear the admin_comment on a single response.

    Body JSON:
        org_id (str): required
        cycle_id (str): required
        response_id (str): required
        comment (str): required (use empty string to clear)
    """
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        response_id = data.get("response_id", "")
        comment = data.get("comment", "")
        if not all([org_id, cycle_id, response_id]):
            return jsonify({"error": "org_id, cycle_id, response_id required"}), 400
        # Bound to a sane length so the field doesn't become a free-text dumping ground.
        if len(comment) > 2000:
            return jsonify({"error": "comment is too long (max 2000 chars)"}), 400
        from app.db import nps_response_repo as _resp_repo
        _resp_repo.update_admin_comment(org_id, cycle_id, response_id, comment)
        return jsonify({"status": "ok"})
    except Exception as exc:
        logger.exception("Error updating response admin_comment")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/dashboard/summary", methods=["GET"])
@login_required
def dashboard_summary():
    """Return cross-org NPS summary data."""
    try:
        data = nps_dashboard_service.compute_cross_org_summary()
        return jsonify(data)
    except Exception as exc:
        logger.exception("Error computing cross-org summary")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# ASANA webhook route
# ---------------------------------------------------------------------------


@nps_bp.route("/webhook/asana", methods=["POST"])
def asana_webhook():
    """Handle ASANA webhook events.

    Supports the ASANA handshake protocol: when ASANA sends a POST with
    an ``X-Hook-Secret`` header, respond with 200 and echo the header
    value back. Otherwise, process the webhook payload as a form response.
    """
    # Handshake: ASANA sends X-Hook-Secret to verify the endpoint
    hook_secret = request.headers.get("X-Hook-Secret")
    if hook_secret:
        response = jsonify({"status": "handshake accepted"})
        response.headers["X-Hook-Secret"] = hook_secret
        return response, 200

    # Normal webhook payload processing
    try:
        payload = request.json or {}
        nps_response_service.process_response(payload)
        return jsonify({"status": "processed"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error processing ASANA webhook")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Dashboard route
# ---------------------------------------------------------------------------


@nps_bp.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    """Render the NPS dashboard page, or return JSON data when org_id is provided.

    When accessed without query params, renders the dashboard template.
    When org_id is provided, returns JSON summary data for JS consumption.

    Query params (for JSON mode):
        org_id (required): Organization identifier.
        cycle_id (optional): If provided, return summary for that cycle only.
            If omitted, return summaries for all cycles of the org.
    """
    org_id = request.args.get("org_id", "")
    if not org_id:
        return render_template("nps_dashboard.html")

    try:
        cycle_id = request.args.get("cycle_id", "")
        if cycle_id:
            summary = nps_dashboard_service.compute_nps(org_id, cycle_id)
            return jsonify(vars(summary))
        else:
            summaries = nps_dashboard_service.compute_nps_all_cycles(org_id)
            return jsonify([vars(s) for s in summaries])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error computing dashboard data")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/dashboard/leaders", methods=["GET"])
@login_required
def dashboard_leaders():
    """Return per-leader NPS breakdown for a given org/cycle.

    Query params:
        org_id (required): Organization identifier.
        cycle_id (required): Survey cycle identifier.
    """
    try:
        org_id = request.args.get("org_id", "")
        cycle_id = request.args.get("cycle_id", "")
        if not org_id or not cycle_id:
            return jsonify({"error": "org_id and cycle_id are required"}), 400
        leaders = nps_dashboard_service.compute_nps_by_leader(org_id, cycle_id)
        return jsonify(leaders)
    except Exception as exc:
        logger.exception("Error computing leader dashboard data")
        return jsonify({"error": str(exc)}), 500

# ---------------------------------------------------------------------------
# Template view routes
# ---------------------------------------------------------------------------


@nps_bp.route("/orgs/view", methods=["GET"])
@role_required("admin")
def orgs_view():
    """Render the org configuration management page."""
    return render_template("nps_orgs.html")


@nps_bp.route("/nominations/view", methods=["GET"])
@role_required("admin", "editor")
def nominations_view():
    """Render the nominations management page."""
    return render_template("nps_nominations.html")


@nps_bp.route("/cycles/view", methods=["GET"])
@role_required("admin", "editor")
def cycles_view():
    """Render the survey cycles management page."""
    return render_template("nps_cycles.html")


# ---------------------------------------------------------------------------
# ASANA OAuth routes
# ---------------------------------------------------------------------------


@nps_bp.route("/auth/asana", methods=["GET"])
@role_required("admin")
def asana_auth():
    """Redirect user to ASANA OAuth2 authorization page.

    Only admins can initiate the connection — OAuth tokens are shared
    across the whole tool, so this is a one-time setup action.
    """
    from flask import redirect, session
    state = asana_client.generate_state()
    session["asana_oauth_state"] = state
    return redirect(asana_client.get_authorize_url(state=state))


@nps_bp.route("/auth/callback", methods=["GET"])
def asana_callback():
    """Handle ASANA OAuth2 callback with authorization code.

    Validates the ``state`` parameter against the value stored in the
    admin's session to prevent CSRF. Only an admin who initiated the
    flow will have a matching ``state`` in their session.
    """
    from flask import session

    code = request.args.get("code")
    error = request.args.get("error")
    returned_state = request.args.get("state", "")
    expected_state = session.pop("asana_oauth_state", "")

    if error:
        return jsonify({"error": f"ASANA authorization denied: {error}"}), 400

    if not expected_state or returned_state != expected_state:
        return jsonify({"error": "Invalid OAuth state (possible CSRF)"}), 400

    if not code:
        return jsonify({"error": "No authorization code received"}), 400

    try:
        asana_client.exchange_code_for_token(code)
        return render_template("nps_auth_success.html")
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/auth/status", methods=["GET"])
@login_required
def asana_auth_status():
    """Report Asana authorization state.

    Returns ``{"authorized": bool, "mode": "pat"|"oauth"|"none"}`` so
    the dashboard can distinguish between PAT (no admin action needed)
    and OAuth-not-yet-connected states.
    """
    return jsonify({
        "authorized": asana_client.is_authorized(),
        "mode": asana_client.auth_mode(),
    })
