"""Espejo de contracts/tables.md para crear las tablas en pruebas (moto).
Si cambia el contrato de tablas, se cambia aquí en el mismo commit."""

# tabla -> lista de (nombre_gsi, atributo_pk, atributo_sk)
GSIS = {
    "Reports": [("GSI1-customer", "gsi1pk", "gsi1sk"), ("GSI2-zone", "gsi2pk", "gsi2sk")],
    "Incidents": [("GSI1-zone", "gsi1pk", "gsi1sk"), ("GSI2-queue", "gsi2pk", "gsi2sk")],
    "Telemetry": [("GSI1-zone", "gsi1pk", "gsi1sk"), ("GSI2-open", "gsi2pk", "gsi2sk")],
    "CorrelationMembers": [],
    "NetworkCatalog": [("GSI1-type", "gsi1pk", "gsi1sk"), ("GSI2-zone", "gsi2pk", "gsi2sk")],
    "CustomerProfiles": [],
    "Outbox": [],
}
STREAMS = {"Outbox"}


def create_table_kwargs(logical: str, physical_name: str) -> dict:
    attrs = {"pk", "sk"}
    gsis = []
    for name, pk, sk in GSIS[logical]:
        attrs.update({pk, sk})
        gsis.append(
            {
                "IndexName": name,
                "KeySchema": [{"AttributeName": pk, "KeyType": "HASH"}, {"AttributeName": sk, "KeyType": "RANGE"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        )
    kwargs = {
        "TableName": physical_name,
        "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"} for a in sorted(attrs)],
        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        "BillingMode": "PAY_PER_REQUEST",
    }
    if gsis:
        kwargs["GlobalSecondaryIndexes"] = gsis
    if logical in STREAMS:
        kwargs["StreamSpecification"] = {"StreamEnabled": True, "StreamViewType": "NEW_IMAGE"}
    return kwargs
