import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr

from app.db.models import OrgConfig

TABLE_NAME = os.environ.get("NPS_ORG_CONFIG_TABLE", "NpsOrgConfig")


def _get_table():
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


def _create_table():
    """Create the NpsOrgConfig DynamoDB table. Used in tests and initial setup."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "org_id", "KeyType": "HASH"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "org_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _item_to_org_config(item: dict) -> OrgConfig:
    """Convert a DynamoDB item dict to an OrgConfig dataclass."""
    return OrgConfig(
        org_id=item["org_id"],
        org_name=item.get("org_name", ""),
        asana_project_gid=item.get("asana_project_gid", ""),
        asana_form_url=item.get("asana_form_url", ""),
        custom_field_nps_score_gid=item.get("custom_field_nps_score_gid", ""),
        custom_field_category_gid=item.get("custom_field_category_gid", ""),
        custom_field_org_name_gid=item.get("custom_field_org_name_gid", ""),
        custom_field_leader_gid=item.get("custom_field_leader_gid", ""),
        quip_doc_id=item.get("quip_doc_id", ""),
        reminder_channels=item.get("reminder_channels", ["email"]),
        slack_bot_token=item.get("slack_bot_token", ""),
        auto_add_unmatched=item.get("auto_add_unmatched", False),
        is_active=item.get("is_active", True),
        created_at=item.get("created_at", ""),
    )


def put_org(org: OrgConfig) -> None:
    """Store an OrgConfig in DynamoDB. Sets created_at if not already set."""
    table = _get_table()
    item = {
        "org_id": org.org_id,
        "org_name": org.org_name,
        "asana_project_gid": org.asana_project_gid,
        "asana_form_url": org.asana_form_url,
        "custom_field_nps_score_gid": org.custom_field_nps_score_gid,
        "custom_field_category_gid": org.custom_field_category_gid,
        "custom_field_org_name_gid": org.custom_field_org_name_gid,
        "custom_field_leader_gid": org.custom_field_leader_gid,
        "quip_doc_id": org.quip_doc_id,
        "reminder_channels": org.reminder_channels,
        "slack_bot_token": org.slack_bot_token,
        "auto_add_unmatched": org.auto_add_unmatched,
        "is_active": org.is_active,
        "created_at": org.created_at or datetime.now(timezone.utc).isoformat(),
    }
    table.put_item(Item=item)


def get_org(org_id: str) -> OrgConfig | None:
    """Retrieve an OrgConfig by org_id. Returns None if not found."""
    table = _get_table()
    response = table.get_item(Key={"org_id": org_id})
    item = response.get("Item")
    if not item:
        return None
    return _item_to_org_config(item)


def update_org(org_id: str, **fields) -> None:
    """Update specific fields on an existing OrgConfig using UpdateExpression."""
    if not fields:
        return
    table = _get_table()

    update_parts = []
    expr_names = {}
    expr_values = {}

    for i, (key, value) in enumerate(fields.items()):
        placeholder_name = f"#f{i}"
        placeholder_value = f":v{i}"
        update_parts.append(f"{placeholder_name} = {placeholder_value}")
        expr_names[placeholder_name] = key
        expr_values[placeholder_value] = value

    update_expression = "SET " + ", ".join(update_parts)

    table.update_item(
        Key={"org_id": org_id},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


def list_active_orgs() -> list[OrgConfig]:
    """Scan for all orgs where is_active is True (excludes system records)."""
    table = _get_table()
    response = table.scan(FilterExpression=Attr("is_active").eq(True))
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.scan(
            FilterExpression=Attr("is_active").eq(True),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    return [_item_to_org_config(item) for item in items if not item["org_id"].startswith("__")]


def list_all_orgs() -> list[OrgConfig]:
    """Scan all org config items (excludes system records)."""
    table = _get_table()
    response = table.scan()
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.scan(
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    return [_item_to_org_config(item) for item in items if not item["org_id"].startswith("__")]
