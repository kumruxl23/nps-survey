import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key

from app.db.models import Nomination

TABLE_NAME = os.environ.get("NPS_NOMINATIONS_TABLE", "NpsNominations")


def _get_table():
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


def _create_table():
    """Create the NpsNominations DynamoDB table. Used in tests and initial setup."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "org_id_cycle_id", "KeyType": "HASH"},
            {"AttributeName": "email", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "org_id_cycle_id", "AttributeType": "S"},
            {"AttributeName": "email", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _build_composite_key(org_id: str, cycle_id: str) -> str:
    """Build the composite partition key: {org_id}#{cycle_id}."""
    return f"{org_id}#{cycle_id}"


def _item_to_nomination(item: dict) -> Nomination:
    """Convert a DynamoDB item dict to a Nomination dataclass."""
    # Split composite key back into org_id and cycle_id
    pk = item["org_id_cycle_id"]
    org_id, cycle_id = pk.split("#", 1)
    return Nomination(
        org_id=org_id,
        cycle_id=cycle_id,
        email=item["email"],
        name=item.get("name", ""),
        leader=item.get("leader", ""),
        slack_user_id=item.get("slack_user_id", ""),
        responded=item.get("responded", False),
        responded_at=item.get("responded_at", ""),
        created_at=item.get("created_at", ""),
    )


def put_nomination(nomination: Nomination) -> None:
    """Store a Nomination in DynamoDB. Sets created_at if not already set."""
    table = _get_table()
    composite_key = _build_composite_key(nomination.org_id, nomination.cycle_id)
    item = {
        "org_id_cycle_id": composite_key,
        "email": nomination.email,
        "name": nomination.name,
        "leader": nomination.leader,
        "slack_user_id": nomination.slack_user_id,
        "responded": nomination.responded,
        "responded_at": nomination.responded_at,
        "created_at": nomination.created_at or datetime.now(timezone.utc).isoformat(),
    }
    table.put_item(Item=item)


def get_nomination(org_id: str, cycle_id: str, email: str) -> Nomination | None:
    """Retrieve a Nomination by org_id, cycle_id, and email. Returns None if not found."""
    table = _get_table()
    composite_key = _build_composite_key(org_id, cycle_id)
    response = table.get_item(Key={"org_id_cycle_id": composite_key, "email": email})
    item = response.get("Item")
    if not item:
        return None
    return _item_to_nomination(item)


def list_nominations(org_id: str, cycle_id: str) -> list[Nomination]:
    """Query all nominations for a given org_id and cycle_id."""
    table = _get_table()
    composite_key = _build_composite_key(org_id, cycle_id)
    response = table.query(
        KeyConditionExpression=Key("org_id_cycle_id").eq(composite_key),
    )
    items = response.get("Items", [])

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression=Key("org_id_cycle_id").eq(composite_key),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    return [_item_to_nomination(item) for item in items]


def delete_nomination(org_id: str, cycle_id: str, email: str) -> None:
    """Delete a nomination by org_id, cycle_id, and email."""
    table = _get_table()
    composite_key = _build_composite_key(org_id, cycle_id)
    table.delete_item(Key={"org_id_cycle_id": composite_key, "email": email})


def update_responded(org_id: str, cycle_id: str, email: str) -> None:
    """Mark a nomination as responded with the current timestamp."""
    table = _get_table()
    composite_key = _build_composite_key(org_id, cycle_id)
    now = datetime.now(timezone.utc).isoformat()
    table.update_item(
        Key={"org_id_cycle_id": composite_key, "email": email},
        UpdateExpression="SET #r = :responded, #ra = :responded_at",
        ExpressionAttributeNames={"#r": "responded", "#ra": "responded_at"},
        ExpressionAttributeValues={":responded": True, ":responded_at": now},
    )


def update_nomination(org_id: str, cycle_id: str, email: str, **fields) -> None:
    """Update specific fields on an existing Nomination using UpdateExpression."""
    if not fields:
        return
    table = _get_table()
    composite_key = _build_composite_key(org_id, cycle_id)

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
        Key={"org_id_cycle_id": composite_key, "email": email},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


def query_non_respondents(org_id: str, cycle_id: str) -> list[Nomination]:
    """Query nominations where responded=False for a given org/cycle.

    Queries by org_id_cycle_id and filters for responded=False.
    """
    table = _get_table()
    composite_key = _build_composite_key(org_id, cycle_id)
    response = table.query(
        KeyConditionExpression=Key("org_id_cycle_id").eq(composite_key),
        FilterExpression=Attr("responded").eq(False),
    )
    items = response.get("Items", [])

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression=Key("org_id_cycle_id").eq(composite_key),
            FilterExpression=Attr("responded").eq(False),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    return [_item_to_nomination(item) for item in items]
