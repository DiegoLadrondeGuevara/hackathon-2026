"""Acceso a DynamoDB: tablas por nombre lógico, consultas paginadas y operaciones de transacción."""
import boto3

from . import config

_resource = None


def resource():
    global _resource
    if _resource is None:
        _resource = boto3.resource("dynamodb")
    return _resource


def reset():
    """Solo para pruebas: fuerza a crear de nuevo el recurso."""
    global _resource
    _resource = None


def table(logical: str):
    return resource().Table(config.table_name(logical))


def query_all(logical: str, **kwargs) -> list:
    """Query paginada completa. kwargs = argumentos de Table.query (IndexName, KeyConditionExpression, ...)."""
    tbl = table(logical)
    items = []
    while True:
        resp = tbl.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return items
        kwargs["ExclusiveStartKey"] = last


def _expr(op: dict, condition, names, values) -> dict:
    if condition:
        op["ConditionExpression"] = condition
    if names:
        op["ExpressionAttributeNames"] = names
    if values:
        op["ExpressionAttributeValues"] = values
    return op


def put_op(logical, item, condition=None, names=None, values=None) -> dict:
    return {"Put": _expr({"TableName": config.table_name(logical), "Item": item}, condition, names, values)}


def update_op(logical, key, update, condition=None, names=None, values=None) -> dict:
    op = {"TableName": config.table_name(logical), "Key": key, "UpdateExpression": update}
    return {"Update": _expr(op, condition, names, values)}


def delete_op(logical, key, condition=None, names=None, values=None) -> dict:
    return {"Delete": _expr({"TableName": config.table_name(logical), "Key": key}, condition, names, values)}


def check_op(logical, key, condition, names=None, values=None) -> dict:
    op = {"TableName": config.table_name(logical), "Key": key}
    return {"ConditionCheck": _expr(op, condition, names, values)}


def transact(ops: list) -> None:
    """TransactWriteItems (máximo 100 operaciones). Valores Python nativos, sin float."""
    resource().meta.client.transact_write_items(TransactItems=ops)
