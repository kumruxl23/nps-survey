import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

from app.db.models import ReminderLog

TABLE_NAME = os.environ.get("NPS_REMINDER_LOGS_TABLE", "NpsReminderLogs")


def _get_table():
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


def _create_table():
    """Create the NpsReminderLogs DynamoDB table. Used in tests and initial setup."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "org_id_cycle_id", "KeyType": "HASH"},
            {"AttributeName": "log_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "org_id_cycle_id", "AttributeType": "S"},
            {"AttributeName": "log_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _build_composite_key(org_id: str, cycle_id: str) -> str:
    """Build the composite partition key: {org_id}#{cycle_id}."""
    return f"{org_id}#{cycle_id}"


def _item_to_log(item: dict) -> ReminderLog:
    """Convert a DynamoDB item dict to a ReminderLog dataclass."""
    pk = item["org_id_cycle_id"]
    org_id, cycle_id = pk.split("#", 1)
    return ReminderLog(
        org_id=org_id,
        cycle_id=cycle_id,
        log_id=item["log_id"],
        sent_at=item.get("sent_at", ""),
        trigger_type=item.get("trigger_type", "automated"),
        recipient_count=int(item.get("recipient_count", 0)),
        channels=item.get("channels", []),
        failures=item.get("failures", "[]"),
    )


def put_log(log: ReminderLog) -> None:
    """Store a ReminderLog in DynamoDB. Sets sent_at if not already set."""
    table = _get_table()
    composite_key = _build_composite_key(log.org_id, log.cycle_id)
    item = {
        "org_id_cycle_id": composite_key,
        "log_id": log.log_id,
        "sent_at": log.sent_at or datetime.now(timezone.utc).isoformat(),
        "trigger_type": log.trigger_type,
        "recipient_count": log.recipient_count,
        "channels": log.channels,
        "failures": log.failures,
    }
    table.put_item(Item=item)


def list_logs(org_id: str, cycle_id: str) -> list[ReminderLog]:
    """Query all reminder logs for a given org_id and cycle_id."""
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

    return [_item_to_log(item) for item in items]
