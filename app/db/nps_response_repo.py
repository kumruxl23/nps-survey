import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

from app.db.models import NpsResponse

TABLE_NAME = os.environ.get("NPS_RESPONSES_TABLE", "NpsResponses")


def _get_table():
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


def _create_table():
    """Create the NpsResponses DynamoDB table. Used in tests and initial setup."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "org_id_cycle_id", "KeyType": "HASH"},
            {"AttributeName": "response_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "org_id_cycle_id", "AttributeType": "S"},
            {"AttributeName": "response_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _build_composite_key(org_id: str, cycle_id: str) -> str:
    """Build the composite partition key: {org_id}#{cycle_id}."""
    return f"{org_id}#{cycle_id}"


def _item_to_response(item: dict) -> NpsResponse:
    """Convert a DynamoDB item dict to an NpsResponse dataclass."""
    pk = item["org_id_cycle_id"]
    org_id, cycle_id = pk.split("#", 1)
    return NpsResponse(
        org_id=org_id,
        cycle_id=cycle_id,
        response_id=item["response_id"],
        nps_score=int(item["nps_score"]),
        category=item["category"],
        leader=item.get("leader", ""),
        feedback_text=item.get("feedback_text", ""),
        respondent_name=item.get("respondent_name", ""),
        recorded_at=item.get("recorded_at", ""),
        admin_comment=item.get("admin_comment", ""),
    )


def put_response(response: NpsResponse) -> None:
    """Store an NpsResponse in DynamoDB. Sets recorded_at if not already set."""
    table = _get_table()
    composite_key = _build_composite_key(response.org_id, response.cycle_id)
    item = {
        "org_id_cycle_id": composite_key,
        "response_id": response.response_id,
        "nps_score": response.nps_score,
        "category": response.category,
        "leader": response.leader,
        "feedback_text": response.feedback_text,
        "respondent_name": response.respondent_name,
        "recorded_at": response.recorded_at or datetime.now(timezone.utc).isoformat(),
        "admin_comment": response.admin_comment,
    }
    table.put_item(Item=item)


def update_admin_comment(org_id: str, cycle_id: str, response_id: str, comment: str) -> None:
    """Update only the admin_comment field on an existing response."""
    table = _get_table()
    table.update_item(
        Key={
            "org_id_cycle_id": _build_composite_key(org_id, cycle_id),
            "response_id": response_id,
        },
        UpdateExpression="SET admin_comment = :c",
        ExpressionAttributeValues={":c": comment},
    )


def list_responses(org_id: str, cycle_id: str) -> list[NpsResponse]:
    """Query all responses for a given org_id and cycle_id."""
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

    return [_item_to_response(item) for item in items]
