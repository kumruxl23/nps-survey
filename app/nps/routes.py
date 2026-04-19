"""Flask blueprint for NPS Survey Automation routes.

Provides endpoints for org configuration, nominations, survey cycles,
distribution, reminders, ASANA webhook processing, and dashboard data.
All routes delegate to the service layer and return JSON responses.
"""

import logging

from flask import Blueprint, jsonify, render_template, request

from app.services import (
    nps_cycle_service,
    nps_dashboard_service,
    nps_distribution_service,
    nps_nomination_service,
    nps_org_config_service,
    nps_response_service,
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
    """List all configured orgs."""
    try:
        orgs = nps_org_config_service.list_all_orgs()
        return jsonify([vars(o) for o in orgs])
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
    """Update an existing org's configuration."""
    try:
        data = request.json or {}
        org_id = data.pop("org_id", None)
        if not org_id:
            return jsonify({"error": "org_id is required"}), 400
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
        result = nps_distribution_service.send_reminder(org_id, cycle_id, trigger_type="manual")
        return jsonify(vars(result))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Error sending reminder")
        return jsonify({"error": str(exc)}), 500


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
def asana_auth():
    """Redirect user to ASANA OAuth2 authorization page."""
    url = asana_client.get_authorize_url()
    from flask import redirect
    return redirect(url)


@nps_bp.route("/auth/callback", methods=["GET"])
def asana_callback():
    """Handle ASANA OAuth2 callback with authorization code."""
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return jsonify({"error": f"ASANA authorization denied: {error}"}), 400

    if not code:
        return jsonify({"error": "No authorization code received"}), 400

    try:
        token_data = asana_client.exchange_code_for_token(code)
        return render_template("nps_auth_success.html")
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500


@nps_bp.route("/auth/status", methods=["GET"])
def asana_auth_status():
    """Check if ASANA is authorized."""
    return jsonify({"authorized": asana_client.is_authorized()})
