import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

from app.db.models import DeliveryFailure

TABLE_NAME = os.environ.get("NPS_DELIVERY_FAILURES_TABLE", "NpsDeliveryFailures")


def _get_table():
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


def _create_table():
    """Create the NpsDeliveryFailures DynamoDB table. Used in tests and initial setup."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "org_id_cycle_id", "KeyType": "HASH"},
            {"AttributeName": "failure_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "org_id_cycle_id", "AttributeType": "S"},
            {"AttributeName": "failure_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _build_composite_key(org_id: str, cycle_id: str) -> str:
    """Build the composite partition key: {org_id}#{cycle_id}."""
    return f"{org_id}#{cycle_id}"


def _item_to_failure(item: dict) -> DeliveryFailure:
    """Convert a DynamoDB item dict to a DeliveryFailure dataclass."""
    pk = item["org_id_cycle_id"]
    org_id, cycle_id = pk.split("#", 1)
    return DeliveryFailure(
        org_id=org_id,
        cycle_id=cycle_id,
        failure_id=item["failure_id"],
        email=item.get("email", ""),
        error_reason=item.get("error_reason", ""),
        event_type=item.get("event_type", ""),
        channel=item.get("channel", ""),
        occurred_at=item.get("occurred_at", ""),
    )


def put_failure(failure: DeliveryFailure) -> None:
    """Store a DeliveryFailure in DynamoDB. Sets occurred_at if not already set."""
    table = _get_table()
    composite_key = _build_composite_key(failure.org_id, failure.cycle_id)
    item = {
        "org_id_cycle_id": composite_key,
        "failure_id": failure.failure_id,
        "email": failure.email,
        "error_reason": failure.error_reason,
        "event_type": failure.event_type,
        "channel": failure.channel,
        "occurred_at": failure.occurred_at or datetime.now(timezone.utc).isoformat(),
    }
    table.put_item(Item=item)


def list_failures(org_id: str, cycle_id: str) -> list[DeliveryFailure]:
    """Query all delivery failures for a given org_id and cycle_id."""
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

    return [_item_to_failure(item) for item in items]
