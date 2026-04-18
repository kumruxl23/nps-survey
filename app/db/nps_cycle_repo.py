import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

from app.db.models import SurveyCycle

TABLE_NAME = os.environ.get("NPS_SURVEY_CYCLES_TABLE", "NpsSurveyCycles")


def _get_table():
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


def _create_table():
    """Create the NpsSurveyCycles DynamoDB table. Used in tests and initial setup."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "org_id", "KeyType": "HASH"},
            {"AttributeName": "cycle_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "org_id", "AttributeType": "S"},
            {"AttributeName": "cycle_id", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "StatusIndex",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "org_id", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _item_to_survey_cycle(item: dict) -> SurveyCycle:
    """Convert a DynamoDB item dict to a SurveyCycle dataclass."""
    return SurveyCycle(
        org_id=item["org_id"],
        cycle_id=item["cycle_id"],
        start_date=item.get("start_date", ""),
        end_date=item.get("end_date", ""),
        status=item.get("status", "active"),
        reminder_mode=item.get("reminder_mode", "manual"),
        asana_project_gid=item.get("asana_project_gid", ""),
        last_reminder_at=item.get("last_reminder_at", ""),
        distributed_at=item.get("distributed_at", ""),
        asana_form_url=item.get("asana_form_url", ""),
        quip_doc_id=item.get("quip_doc_id", ""),
        cycle_name=item.get("cycle_name", ""),
        created_at=item.get("created_at", ""),
    )


def put_cycle(cycle: SurveyCycle) -> None:
    """Store a SurveyCycle in DynamoDB. Sets created_at if not already set."""
    table = _get_table()
    item = {
        "org_id": cycle.org_id,
        "cycle_id": cycle.cycle_id,
        "start_date": cycle.start_date,
        "end_date": cycle.end_date,
        "status": cycle.status,
        "reminder_mode": cycle.reminder_mode,
        "asana_project_gid": cycle.asana_project_gid,
        "last_reminder_at": cycle.last_reminder_at,
        "distributed_at": cycle.distributed_at,
        "asana_form_url": cycle.asana_form_url,
        "quip_doc_id": cycle.quip_doc_id,
        "cycle_name": cycle.cycle_name,
        "created_at": cycle.created_at or datetime.now(timezone.utc).isoformat(),
    }
    table.put_item(Item=item)


def get_cycle(org_id: str, cycle_id: str) -> SurveyCycle | None:
    """Retrieve a SurveyCycle by org_id + cycle_id. Returns None if not found."""
    table = _get_table()
    response = table.get_item(Key={"org_id": org_id, "cycle_id": cycle_id})
    item = response.get("Item")
    if not item:
        return None
    return _item_to_survey_cycle(item)


def list_cycles(org_id: str) -> list[SurveyCycle]:
    """Query all cycles for a given org_id."""
    table = _get_table()
    response = table.query(KeyConditionExpression=Key("org_id").eq(org_id))
    items = response.get("Items", [])

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression=Key("org_id").eq(org_id),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    return [_item_to_survey_cycle(item) for item in items]


def update_cycle(org_id: str, cycle_id: str, **fields) -> None:
    """Update specific fields on an existing SurveyCycle using UpdateExpression."""
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
        Key={"org_id": org_id, "cycle_id": cycle_id},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


def query_active_cycles() -> list[SurveyCycle]:
    """Query the StatusIndex GSI for all cycles with status='active'."""
    table = _get_table()
    response = table.query(
        IndexName="StatusIndex",
        KeyConditionExpression=Key("status").eq("active"),
    )
    items = response.get("Items", [])

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.query(
            IndexName="StatusIndex",
            KeyConditionExpression=Key("status").eq("active"),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    return [_item_to_survey_cycle(item) for item in items]
