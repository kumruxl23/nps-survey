"""Flask blueprint for NPS Survey Automation routes.

Provides endpoints for org configuration, nominations, survey cycles,
distribution, reminders, ASANA webhook processing, and dashboard data.
All routes delegate to the service layer and return JSON responses.
"""

import functools
import logging
import os

from flask import Blueprint, Response, g, jsonify, redirect, render_template, request, session, url_for

from app.services import (
    nps_asana_dashboard_service,
    nps_cycle_service,
    nps_dashboard_service,
    nps_distribution_service,
    nps_export_service,
    nps_leader_service,
    nps_nomination_service,
    nps_org_config_service,
    nps_phase_service,
    nps_response_service,
    nps_settings_service,
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
        "custom_field_respondent_name_gid",
        "custom_field_respondent_email_gid",
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


def _midway_header_alias() -> str:
    """The Midway alias the ALB asserted, when Midway mode is on."""
    import os as _os
    if _os.environ.get("NPS_MIDWAY_AUTH") != "1":
        return ""
    return request.headers.get("X-Amzn-Oidc-Identity", "").strip().lower()


def _viewer_alias() -> str:
    """Who is using the form: app session first, else the ALB identity."""
    user = session.get("user")
    if user and user.get("username"):
        return str(user["username"]).strip().lower()
    return _midway_header_alias()


def login_or_share_token(f):
    """Allow a session, a valid share token, or an ALB Midway identity.

    Behind the Midway ALB every visitor is authenticated even without an
    app account, so the form accepts the ALB-asserted identity directly.
    Share tokens remain as org-locked capability links. Everything else
    in the app stays session-only.
    """

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            # Provisioned app users get their role-bearing session.
            from app.nps.auth_routes import _try_midway_auth
            _try_midway_auth()
        g.share_org_id = None
        if "user" not in session:
            share_org = nps_share_link_service.resolve_token(request.args.get("token", ""))
            if share_org:
                # Common token: valid but org-agnostic (the viewer's org is
                # resolved from their identity). Legacy per-org tokens stay
                # locked to their org.
                if share_org != nps_share_link_service.COMMON_ORG:
                    g.share_org_id = share_org  # token: locked to this org
            elif not _midway_header_alias():
                if request.is_json or request.headers.get("Accept") == "application/json":
                    return jsonify({"error": "Authentication required"}), 401
                return redirect(url_for("auth.login_page"))
        g.viewer_alias = _viewer_alias()
        return f(*args, **kwargs)

    return wrapper


def _share_org_mismatch(org_id: str):
    """403 response when a share-token caller touches another org, else None."""
    share_org = getattr(g, "share_org_id", None)
    if share_org and org_id != share_org:
        return jsonify({"error": "This link is limited to one org"}), 403
    return None


def _is_privileged_for_org(org_id: str) -> bool:
    """Full visibility: admins/editors, or roster leaders of this org."""
    if session.get("user", {}).get("role") in ("admin", "editor"):
        return True
    viewer = getattr(g, "viewer_alias", "") or ""
    if not viewer:
        return False
    return any(
        leader["alias"] == viewer
        for leader in nps_leader_service.list_leaders(org_id)
    )


def _session_scope_orgs():
    """Org ids the current session may view, or None when unscoped.

    None means 'no scope on the session' (admins, or legacy password
    sessions) — callers fall back to admin-all / home-org resolution.
    """
    user = session.get("user", {}) or {}
    orgs = user.get("nps_orgs")
    return orgs if isinstance(orgs, list) else None


def _viewer_resolved_leader(org_id: str) -> str:
    """The leader the current viewer files under (system-resolved), or ''."""
    viewer = getattr(g, "viewer_alias", "") or ""
    if not viewer:
        return ""
    person = nps_nomination_service.lookup_person(org_id, viewer)
    return ((person or {}).get("leader") or "").strip()


def _nominate_level_denied():
    """403 response when the current nominator is below L5, else None.

    Admins and editors bypass the check (they manage the program). Everyone
    else must be L5+ (PAPI job level) to nominate — an L4 who was granted a
    view role still cannot nominate.
    """
    role = session.get("user", {}).get("role", "")
    if role in ("admin", "editor"):
        return None
    from app.services import nps_access_service, papi_client

    # Can't determine level without PAPI (local dev / tests) — don't block.
    if not papi_client.is_configured():
        return None

    alias = getattr(g, "viewer_alias", "") or ""
    level = None
    try:
        emp = papi_client.get_employee(alias) if alias else None
        level = (emp or {}).get("level")
    except papi_client.PapiError:
        level = None
    if not isinstance(level, int) or level < nps_access_service.MIN_AUTO_LEVEL:
        return jsonify({
            "error": f"Only L{nps_access_service.MIN_AUTO_LEVEL}+ employees can nominate. "
                     f"If you believe this is an error, please contact an admin."
        }), 403
    return None


def _viewer_owns_leader(org_id: str, leader: str) -> bool:
    """Whether the viewer files under this leader (a direct), or is privileged.

    Used for the last-cycle carry-forward list: a nominator may see the
    prior cycle's responded stakeholders under THEIR OWN resolved leader
    (so they can re-nominate them), and admins/editors/roster leaders may
    see any leader's. This does NOT grant access to the current-cycle
    who-nominated-whom list, which stays privileged (see nominate_list) —
    a nomination is gauged at the leader level, so the roster leader and
    admins/editors own that detail, not the directs.
    """
    if _is_privileged_for_org(org_id):
        return True
    resolved = _viewer_resolved_leader(org_id)
    return bool(resolved) and resolved == (leader or "").strip()


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
            alias=data.get("alias", ""),
            name=data.get("name", ""),
            org_id=data.get("org_id", ""),
            notify_alias=data.get("notify_alias", ""),
        )
        return jsonify(leader), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@nps_bp.route("/leaders/set-notify", methods=["POST"])
@role_required("admin", "editor")
def set_leader_notify():
    """Set/clear a leader's reminder redirect (test) alias."""
    try:
        data = request.json or {}
        alias = data.get("alias", "")
        if not alias:
            return jsonify({"error": "alias is required"}), 400
        result = nps_leader_service.set_notify_alias(alias, data.get("notify_alias", ""))
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@nps_bp.route("/leaders/remind", methods=["POST"])
@role_required("admin", "editor")
def remind_leaders():
    """Send email + Slack DM reminders to an org's roster leaders.

    Each reminder is redirected to the leader's test alias (notify_alias)
    when set. Body: {org_id, note?, channels?} where channels is an optional
    subset of ["email", "slack"] (defaults to both).
    """
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        if not org_id:
            return jsonify({"error": "org_id is required"}), 400
        channels = data.get("channels") or ["email", "slack"]
        if not isinstance(channels, list) or not set(channels) <= {"email", "slack"}:
            return jsonify({"error": "channels must be a subset of ['email','slack']"}), 400
        result = nps_leader_service.send_leader_reminders(
            base_url=request.host_url,
            org_id=org_id,
            note=data.get("note", ""),
            channels=tuple(channels),
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error sending leader reminders")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/leaders/notify-open", methods=["POST"])
@role_required("admin", "editor")
def notify_nomination_open():
    """Notify an org's roster leaders that nominations have OPENED.

    Kickoff announcement over email + Slack DM (distinct from the periodic
    reminder). Each notification is redirected to the leader's test alias
    (notify_alias) when set. Body: {org_id, deadline?, note?, channels?}
    where channels is an optional subset of ["email", "slack"] (both by
    default).
    """
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        if not org_id:
            return jsonify({"error": "org_id is required"}), 400
        channels = data.get("channels") or ["email", "slack"]
        if not isinstance(channels, list) or not set(channels) <= {"email", "slack"}:
            return jsonify({"error": "channels must be a subset of ['email','slack']"}), 400
        result = nps_leader_service.send_nomination_open(
            base_url=request.host_url,
            org_id=org_id,
            deadline=data.get("deadline", ""),
            note=data.get("note", ""),
            channels=tuple(channels),
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error sending nomination-open notification")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/leaders/slack-check", methods=["GET"])
@role_required("admin", "editor")
def check_slack_resolution():
    """Diagnose SLAB alias→Slack-ID resolution (read-only, no bot token).

    Query: ?alias=<amazon-alias>. Verifies the SLAB half of the Slack DM
    path works on this host (SLAB only accepts the allowlisted EC2 role, so
    this is meaningful after deploy). Returns {alias, ok, slack_id, error}.
    """
    alias = request.args.get("alias", "")
    if not alias:
        return jsonify({"error": "alias query param is required"}), 400
    return jsonify(nps_leader_service.check_slack_resolution(alias))


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
    """Invalidate the common share link and issue a fresh one.

    Passing an org_id rotates that org's LEGACY per-org token instead
    (kills an old org-locked link that leaked).
    """
    org_id = (request.json or {}).get("org_id", "")
    if org_id:
        token = nps_share_link_service.rotate_token(org_id)
        return jsonify({"org_id": org_id, "share_path": f"/nps/nominate/view?token={token}"})
    token = nps_share_link_service.rotate_common_token()
    return jsonify({"share_path": f"/nps/nominate/view?token={token}"})


@nps_bp.route("/nominate/invite", methods=["POST"])
@role_required("admin", "editor")
def send_nomination_invite():
    """Email one org's leaders that org's form link with a deadline."""
    try:
        data = request.json or {}
        result = nps_leader_service.send_nomination_invite(
            base_url=request.host_url,
            deadline=data.get("deadline", ""),
            note=data.get("note", ""),
            org_id=data.get("org_id", ""),
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error sending nomination invite")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominate/prefill", methods=["GET"])
@login_or_share_token
def nominate_prefill():
    """Best-effort prefill data for an alias (name/designation/leader).

    Looks the alias up in the org's leader roster and nomination history
    (workbook imports included). Returns {found: false} for unknown
    aliases — the form then falls back to manual entry.
    """
    try:
        org_id = request.args.get("org_id", "")
        alias = request.args.get("alias", "")
        if not org_id or not alias:
            return jsonify({"error": "org_id and alias query params are required"}), 400
        mismatch = _share_org_mismatch(org_id)
        if mismatch:
            return mismatch
        person = nps_nomination_service.lookup_person(org_id, alias)
        if not person:
            return jsonify({"found": False})
        return jsonify({"found": True, **person})
    except Exception as exc:
        logger.exception("Error prefetching person data")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominate/context", methods=["GET"])
@login_or_share_token
def nominate_context():
    """Data the nomination form needs: orgs with active cycles + leaders.

    Share-token callers get ONLY their org (locked). Logged-in viewers are
    defaulted to their HOME org (the org where their leader resolves —
    e.g. kumruxl under Sandeep's roster → whs_cpt_in); non-admins are
    LOCKED to it (the org list is filtered server-side, not just hidden
    in the UI). Admins see all active orgs and may switch.
    """
    try:
        share_org = getattr(g, "share_org_id", None)
        orgs = []
        for org in nps_org_config_service.list_active_orgs():
            if share_org and org.org_id != share_org:
                continue
            cycle = nps_cycle_service.get_active_cycle(org.org_id)
            orgs.append({
                "org_id": org.org_id,
                "org_name": org.org_name,
                "leaders": nps_leader_service.list_leaders(org.org_id),
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
        viewer = getattr(g, "viewer_alias", "") or ""
        # Only admins may switch orgs; everyone else is pinned to their
        # home org (when one resolves). Share-token access keeps its own
        # org lock and skips home-org resolution entirely.
        can_switch_org = session.get("user", {}).get("role") == "admin"
        home_org = ""
        if not share_org and viewer:
            home_org = nps_nomination_service.resolve_home_org(
                viewer, [o["org_id"] for o in orgs]
            )
        locked_org = share_org
        if home_org and not can_switch_org:
            # Enforce the lock server-side: a non-admin's context contains
            # ONLY their org, so the client can't reveal other orgs by
            # unhiding the selector.
            orgs = [o for o in orgs if o["org_id"] == home_org]
            locked_org = home_org
        payload = {
            "orgs": orgs,
            "locked_org": locked_org,
            # The viewer's own org — the UI preselects it (admins can
            # still switch away; non-admins are locked above).
            "default_org": home_org,
            "viewer": {
                "alias": viewer,
                "role": session.get("user", {}).get("role", ""),
                "can_switch_org": can_switch_org,
                # Per-org full-visibility flag (admin/editor/roster leader).
                "privileged_orgs": {
                    o["org_id"]: _is_privileged_for_org(o["org_id"]) for o in orgs
                },
            },
        }
        # Admins/editors get the COMMON shareable capability URL — one link
        # for everyone (no login needed); each viewer lands on the org their
        # identity resolves to.
        if session.get("user", {}).get("role") in ("admin", "editor"):
            payload["share_path"] = (
                "/nps/nominate/view?token="
                + nps_share_link_service.get_or_create_common_token()
            )
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
        mismatch = _share_org_mismatch(org_id)
        if mismatch:
            return mismatch
        if not _is_privileged_for_org(org_id):
            # The current-cycle who-nominated-whom list stays privileged:
            # nominations are gauged at the leader level, so only the roster
            # leader and admins/editors see the detail. Directs learn of an
            # existing nomination only via the duplicate-conflict response
            # (submit) or the carry-forward list's "already nominated" flag.
            return jsonify({"error": "Nomination lists are visible to admins and org leaders only"}), 403
        cycle = nps_cycle_service.get_active_cycle(org_id)
        if not cycle:
            return jsonify({"error": f"No active cycle for org '{org_id}'"}), 404
        from app.services.nomination_keys import base_email

        # "__ALL__" → every nomination for the cycle (admins/editors see all
        # leaders at once, since the leader roster may not enumerate everyone).
        if leader == "__ALL__":
            rows = nps_nomination_service.list_nominations(org_id, cycle.cycle_id)
        else:
            rows = nps_nomination_service.list_nominations_for_leader(
                org_id, cycle.cycle_id, leader
            )
        return jsonify([
            {
                "email": base_email(n.email),
                "name": n.name,
                "designation": n.designation,
                "leader": n.leader,
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
        mismatch = _share_org_mismatch(org_id)
        if mismatch:
            return mismatch
        cycle = nps_cycle_service.get_active_cycle(org_id) if org_id else None
        if not cycle:
            return jsonify({"error": "No active survey cycle for this org"}), 400

        # Identity comes from the session/ALB, never from the client body —
        # the nominator cannot be spoofed.
        nominator = getattr(g, "viewer_alias", "") or ""
        if not nominator:
            return jsonify({"error": "Could not establish your identity"}), 401

        # Only L5+ may nominate (admins/editors bypass).
        denied = _nominate_level_denied()
        if denied:
            return denied

        # The leader is ALWAYS system-resolved from the nominator's org
        # records / manager chain — never client-chosen, for anyone. The
        # leader dropdown in the UI is purely a viewing filter.
        person = nps_nomination_service.lookup_person(org_id, nominator)
        leader = (person or {}).get("leader", "")
        if not leader:
            return jsonify({
                "error": "Could not determine your leader for this org — "
                         "ask an org admin to add you or your leader to the roster"
            }), 400

        nomination = nps_nomination_service.nominate_stakeholder(
            org_id=org_id,
            cycle_id=cycle.cycle_id,
            stakeholder_alias=data.get("stakeholder_alias", ""),
            name=data.get("name", ""),
            leader=leader,
            nominated_by=nominator,
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
        mismatch = _share_org_mismatch(org_id)
        if mismatch:
            return mismatch
        cycle = nps_cycle_service.get_active_cycle(org_id) if org_id else None
        if not cycle:
            return jsonify({"error": "No active survey cycle for this org"}), 400

        role = session.get("user", {}).get("role", "")
        nps_nomination_service.remove_leader_nomination(
            org_id=org_id,
            cycle_id=cycle.cycle_id,
            stakeholder_alias=data.get("stakeholder_alias", ""),
            leader=data.get("leader", ""),
            # Identity from session/ALB — not spoofable via the body.
            requested_by=getattr(g, "viewer_alias", "") or "",
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


@nps_bp.route("/nominate/leader-counts", methods=["GET"])
@login_or_share_token
def nominate_leader_counts():
    """Per-leader nomination COUNTS for the active cycle (numbers only).

    Visible to anyone who can open the org's nomination page — it exposes
    no nominee or nominator identities, just a count per leader.
    """
    try:
        org_id = request.args.get("org_id", "")
        if not org_id:
            return jsonify({"error": "org_id query param is required"}), 400
        mismatch = _share_org_mismatch(org_id)
        if mismatch:
            return mismatch
        cycle = nps_cycle_service.get_active_cycle(org_id)
        if not cycle:
            return jsonify({"cycle_id": "", "leaders": []})
        return jsonify({
            "cycle_id": cycle.cycle_id,
            "leaders": nps_nomination_service.count_nominations_by_leader(
                org_id, cycle.cycle_id
            ),
        })
    except Exception as exc:
        logger.exception("Error counting nominations by leader")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominate/previous", methods=["GET"])
@login_or_share_token
def nominate_previous():
    """Prior closed cycle's RESPONDED stakeholders under a leader.

    Same visibility rule as the current-cycle list (own leader / privileged).
    Each row is annotated with whether it's already nominated this cycle so
    the UI can disable "Add" and name the existing nominator.
    """
    try:
        org_id = request.args.get("org_id", "")
        leader = request.args.get("leader", "")
        if not org_id or not leader:
            return jsonify({"error": "org_id and leader query params are required"}), 400
        mismatch = _share_org_mismatch(org_id)
        if mismatch:
            return mismatch
        if not _viewer_owns_leader(org_id, leader):
            return jsonify({"error": "You can only carry forward under your own leader"}), 403
        cycle = nps_cycle_service.get_active_cycle(org_id)
        if not cycle:
            return jsonify({"error": "No active survey cycle for this org"}), 400
        return jsonify(
            nps_nomination_service.list_prior_cycle_responded(
                org_id, cycle.cycle_id, leader
            )
        )
    except Exception as exc:
        logger.exception("Error listing prior-cycle nominations")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/nominate/bulk-submit", methods=["POST"])
@login_or_share_token
def nominate_bulk_submit():
    """Nominate multiple stakeholders at once under the nominator's leader.

    Body: {org_id, stakeholders: [{stakeholder_alias, name, designation}]}.
    Identity and leader are resolved server-side exactly like single submit
    (never client-chosen). Returns a per-row {added, duplicates, errors}.
    """
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        mismatch = _share_org_mismatch(org_id)
        if mismatch:
            return mismatch
        cycle = nps_cycle_service.get_active_cycle(org_id) if org_id else None
        if not cycle:
            return jsonify({"error": "No active survey cycle for this org"}), 400

        nominator = getattr(g, "viewer_alias", "") or ""
        if not nominator:
            return jsonify({"error": "Could not establish your identity"}), 401

        # Only L5+ may nominate (admins/editors bypass).
        denied = _nominate_level_denied()
        if denied:
            return denied

        # Leader is the nominator's own resolved leader — never client-chosen.
        person = nps_nomination_service.lookup_person(org_id, nominator)
        leader = (person or {}).get("leader", "")
        if not leader:
            return jsonify({
                "error": "Could not determine your leader for this org — "
                         "ask an org admin to add you or your leader to the roster"
            }), 400

        stakeholders = data.get("stakeholders", [])
        if not isinstance(stakeholders, list) or not stakeholders:
            return jsonify({"error": "stakeholders must be a non-empty list"}), 400

        result = nps_nomination_service.bulk_nominate_stakeholders(
            org_id=org_id,
            cycle_id=cycle.cycle_id,
            leader=leader,
            nominated_by=nominator,
            stakeholders=stakeholders,
        )
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error bulk-submitting nominations")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Dashboard settings (admin-editable UI content, persisted program-wide)
# ---------------------------------------------------------------------------


@nps_bp.route("/settings", methods=["GET"])
@login_required
def get_settings():
    """Return the persisted dashboard settings blob (or defaults)."""
    try:
        return jsonify(nps_settings_service.get_dashboard_settings())
    except Exception as exc:
        logger.exception("Error loading dashboard settings")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/settings", methods=["POST"])
@role_required("admin")
def save_settings():
    """Overwrite the dashboard settings blob (admins only, last write wins)."""
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Body must be a JSON object"}), 400
        result = nps_settings_service.save_dashboard_settings(data, _viewer_alias())
        # user_access / org_heads may have changed → drop cached access decisions.
        try:
            from app.services import nps_access_service
            nps_access_service.invalidate()
        except Exception:
            logger.exception("access cache invalidate after settings save failed")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error saving dashboard settings")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/admin/export.xlsx", methods=["GET"])
@role_required("admin", "editor")
def export_cycle_xlsx():
    """Download a cycle's responses as an XLSX file.

    Query: cycle_id (required), org_id (optional — omit for all orgs).
    Columns: Org, Leader, Stakeholder, NPS Category, What Was Missing,
    Feedback, Action Taken. Missing fields are left blank.
    """
    cycle_id = request.args.get("cycle_id", "")
    org_id = request.args.get("org_id", "")
    if not cycle_id:
        return jsonify({"error": "cycle_id is required"}), 400
    try:
        data, filename = nps_export_service.build_cycle_export(cycle_id, org_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error building cycle export")
        return jsonify({"error": str(exc)}), 500
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Survey phase schedule routes (admin only)
# ---------------------------------------------------------------------------


@nps_bp.route("/phases", methods=["GET"])
@role_required("admin")
def get_phases():
    """Return the admin-defined phase sequence for an org+cycle."""
    org_id = request.args.get("org_id", "")
    cycle_id = request.args.get("cycle_id", "")
    if not org_id or not cycle_id:
        return jsonify({"error": "org_id and cycle_id are required"}), 400
    try:
        return jsonify(nps_phase_service.get_phase_sequence(org_id, cycle_id))
    except Exception as exc:
        logger.exception("Error loading phase sequence")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/phases", methods=["POST"])
@role_required("admin")
def save_phases():
    """Validate + persist the whole phase sequence (last write wins)."""
    try:
        data = request.get_json(silent=True) or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        phases = data.get("phases")
        if not org_id or not cycle_id:
            return jsonify({"error": "org_id and cycle_id are required"}), 400
        saved = nps_phase_service.save_phase_sequence(
            org_id, cycle_id, phases, _viewer_alias()
        )
        return jsonify(saved)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error saving phase sequence")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/phases/send-now", methods=["POST"])
@role_required("admin")
def send_phase_now():
    """Manually dispatch one phase (for manual-cadence phases)."""
    try:
        data = request.json or {}
        org_id = data.get("org_id", "")
        cycle_id = data.get("cycle_id", "")
        phase_id = data.get("phase_id", "")
        if not all([org_id, cycle_id, phase_id]):
            return jsonify({"error": "org_id, cycle_id, and phase_id are required"}), 400
        if not os.environ.get("NPS_FROM_ADDRESS"):
            return jsonify({"error": "NPS_FROM_ADDRESS not configured"}), 503
        result = nps_phase_service.dispatch_phase_by_id(
            org_id, cycle_id, phase_id, request.host_url, trigger_type="manual"
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error dispatching phase")
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


def _feedback_scope():
    """Who can see which feedback.

    Returns (is_super, my_leader_name):
      - is_super=True  → admins + admin-approved "super leaders"
        (the ``admin_leaders`` settings list): see ALL feedback.
      - otherwise my_leader_name is the leader the viewer maps to (roster);
        a regular leader sees ONLY their own rows. Empty name = sees nothing.
    """
    user = session.get("user", {}) or {}
    role = user.get("role", "")
    if role in ("admin", "editor"):
        return True, ""
    # Midway session carries the resolved scope (super flag + leader name).
    if "nps_super" in user:
        return bool(user.get("nps_super")), (user.get("nps_leader") or "")
    # Legacy (password) session fallback: admin_leaders are super; a roster
    # leader sees only their own rows.
    viewer = (_viewer_alias() or "").strip().lower()
    try:
        super_leaders = [
            str(a).strip().lower()
            for a in (nps_settings_service.get_dashboard_settings().get("admin_leaders") or [])
        ]
    except Exception:
        super_leaders = []
    is_super = bool(viewer) and viewer in super_leaders
    my_leader_name = ""
    if not is_super and viewer:
        ld = nps_leader_service.get_leader(viewer)
        if ld:
            my_leader_name = ld.get("name", "")
    return is_super, my_leader_name


@nps_bp.route("/feedback", methods=["GET"])
@login_required
def list_feedback():
    """Live per-stakeholder feedback (from Asana), gated per-leader.

    Query: org_id, cycle_id (both required). Returns rows with real
    respondent identity (name/email→alias) when the org's respondent
    Name/Email Asana field GIDs are configured. Access follows
    ``_feedback_scope`` — super-viewers see all, a leader sees only theirs.
    """
    org_id = request.args.get("org_id", "")
    cycle_id = request.args.get("cycle_id", "")
    if not org_id or not cycle_id:
        return jsonify({"error": "org_id and cycle_id are required"}), 400
    try:
        rows = nps_asana_dashboard_service.get_feedback(org_id, cycle_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        logger.exception("Asana feedback fetch failed")
        return jsonify({"error": f"Asana fetch failed: {exc}"}), 502
    except Exception as exc:
        logger.exception("Error building feedback")
        return jsonify({"error": str(exc)}), 500

    is_super, my_leader_name = _feedback_scope()
    if not is_super:
        rows = [r for r in rows if (r.get("leader") or "") == my_leader_name] if my_leader_name else []

    for r in rows:
        email = (r.get("respondent_email") or "").strip()
        r["respondent_alias"] = email.split("#", 1)[0].split("@", 1)[0].strip().lower() if email else ""
    return jsonify(rows)


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

    # Access control (feedback is identifiable stakeholder data) — see _feedback_scope.
    is_super, my_leader_name = _feedback_scope()
    if not is_super:
        responses = (
            [r for r in responses if (r.leader or "") == my_leader_name]
            if my_leader_name else []
        )

    if leader_filter:
        responses = [r for r in responses if (r.leader or "") == leader_filter]
    if category_filter:
        responses = [r for r in responses if r.category == category_filter]

    # Stakeholder alias for phonetool avatars: responses are anonymous (name
    # only), but nominations carry the email — join respondent_name -> alias.
    from app.db import nps_nomination_repo
    name_to_alias = {}
    for nom in nps_nomination_repo.list_nominations(org_id, cycle_id):
        nm = (getattr(nom, "name", "") or "").strip().lower()
        email = (getattr(nom, "email", "") or "").strip()
        if nm and email:
            name_to_alias[nm] = email.split("#", 1)[0].split("@", 1)[0].strip().lower()

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
            "respondent_alias": name_to_alias.get(
                (getattr(r, "respondent_name", "") or "").strip().lower(), ""
            ),
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
        # Page render: give the template everything it needs up front —
        # which orgs the viewer may see (admin = all, everyone else = their
        # home org only) and each org's cycles, newest first.
        role = session.get("user", {}).get("role", "")
        viewer = _viewer_alias()
        active = nps_org_config_service.list_active_orgs()
        scope_orgs = _session_scope_orgs()
        home_org = (session.get("user", {}) or {}).get("nps_home_org", "")
        if role == "admin":
            visible = active
        elif scope_orgs is not None:
            # Midway session carries the resolved org scope.
            visible = [o for o in active if o.org_id in scope_orgs]
            if not home_org and visible:
                home_org = visible[0].org_id
        else:
            # Legacy (password) session: fall back to home-org resolution.
            if viewer:
                home_org = nps_nomination_service.resolve_home_org(
                    viewer, [o.org_id for o in active]
                )
            visible = [o for o in active if o.org_id == home_org]
        available_cycles = {}
        for org in visible:
            cycles = sorted(
                nps_cycle_service.list_cycles(org.org_id),
                key=lambda c: c.start_date or "",
                reverse=True,
            )
            available_cycles[org.org_id] = [
                {
                    "cycle_id": c.cycle_id,
                    "cycle_name": c.cycle_name or c.cycle_id,
                    "status": c.status,
                    "start_date": c.start_date,
                    "end_date": c.end_date,
                }
                for c in cycles
            ]
        # Leader name -> alias map (for phonetool avatars in the leader table).
        leader_aliases = {}
        for org in visible:
            for ld in nps_leader_service.list_leaders(org.org_id):
                name = (ld.get("name") or "").strip().lower()
                alias = (ld.get("alias") or "").strip()
                if name and alias:
                    leader_aliases[name] = alias
        # Feedback tab is available to anyone with a feedback scope: admins,
        # super-viewers, or a resolved leader (own rows only).
        su = session.get("user", {}) or {}
        viewer_can_feedback = (
            role in ("admin", "editor")
            or bool(su.get("nps_super"))
            or bool(su.get("nps_leader"))
            or bool(su.get("nps_orgs"))
        )
        return render_template(
            "nps_dashboard.html",
            user_role=role,
            user_home_org=home_org,
            viewer_alias=viewer,
            leader_aliases=leader_aliases,
            viewer_can_feedback=viewer_can_feedback,
            available_orgs=[
                {"org_id": o.org_id, "org_name": o.org_name} for o in visible
            ],
            available_cycles=available_cycles,
        )

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


def _dashboard_org_forbidden(org_id: str):
    """403 when a non-admin asks for an org that isn't their home org.

    Admins may query any org. Everyone else (editors included) is limited
    to the org their identity resolves to — enforced here server-side, not
    just hidden in the UI.
    """
    if session.get("user", {}).get("role") == "admin":
        return None
    scope_orgs = _session_scope_orgs()
    if scope_orgs is not None:
        if org_id and org_id in scope_orgs:
            return None
        return jsonify({"error": "You can only view your own org's dashboard"}), 403
    # Legacy (password) session: fall back to home-org resolution.
    viewer = _viewer_alias()
    home = ""
    if viewer:
        home = nps_nomination_service.resolve_home_org(
            viewer,
            [o.org_id for o in nps_org_config_service.list_active_orgs()],
        )
    if not org_id or org_id != home:
        return jsonify({"error": "You can only view your own org's dashboard"}), 403
    return None


def _live_dashboard_response(fn):
    """Shared plumbing for the live (Asana-backed) dashboard endpoints."""
    org_id = request.args.get("org_id", "")
    cycle_id = request.args.get("cycle_id", "")
    if not org_id or not cycle_id:
        return jsonify({"error": "org_id and cycle_id are required"}), 400
    forbidden = _dashboard_org_forbidden(org_id)
    if forbidden:
        return forbidden
    try:
        return jsonify(fn(org_id, cycle_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:  # Asana API / transport failure
        logger.exception("Asana live dashboard fetch failed")
        return jsonify({"error": f"Asana fetch failed: {exc}"}), 502
    except Exception as exc:
        logger.exception("Error building live dashboard data")
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/dashboard/live", methods=["GET"])
@login_required
def dashboard_live():
    """Live org+cycle headline numbers straight from Asana."""
    return _live_dashboard_response(nps_asana_dashboard_service.get_dashboard_summary)


@nps_bp.route("/dashboard/leaders", methods=["GET"])
@login_required
def dashboard_leaders():
    """Per-leader live breakdown from Asana's Ongoing Survey section."""
    return _live_dashboard_response(nps_asana_dashboard_service.get_leader_breakdown)


@nps_bp.route("/dashboard/distribution", methods=["GET"])
@login_required
def dashboard_distribution():
    """Per-leader promoter/passive/detractor counts (stacked chart data)."""
    return _live_dashboard_response(nps_asana_dashboard_service.get_nps_distribution)


@nps_bp.route("/dashboard/actions", methods=["GET"])
@login_required
def dashboard_actions():
    """Per-leader completed vs incomplete action-task counts."""
    return _live_dashboard_response(nps_asana_dashboard_service.get_action_tracker_status)

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
