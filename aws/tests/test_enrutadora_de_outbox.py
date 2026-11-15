import json

import boto3
import pytest
from boto3.dynamodb.types import TypeSerializer

from common import ddb, events
from handlers import enrutadora_de_outbox

BUS = "red-telecorp-test-operaciones"


@pytest.fixture
def bus(aws, monkeypatch):
    """Bus con una regla que manda todo lo de `red-telecorp` a una cola, para ver qué se publicó."""
    monkeypatch.setenv("EVENT_BUS_NAME", BUS)
    monkeypatch.setattr(enrutadora_de_outbox, "_client", None)
    client = boto3.client("events")
    client.create_event_bus(Name=BUS)
    sqs = boto3.client("sqs")
    url = sqs.create_queue(QueueName="destino")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    client.put_rule(Name="todo", EventBusName=BUS, EventPattern=json.dumps({"source": ["red-telecorp"]}))
    client.put_targets(Rule="todo", EventBusName=BUS, Targets=[{"Id": "cola", "Arn": arn}])

    def received() -> list:
        out = []
        while True:
            msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])
            if not msgs:
                return out
            for m in msgs:
                out.append(json.loads(m["Body"]))
                sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])

    return received


def _record(event_type="report.created", data=None, event_name="INSERT") -> dict:
    """Registro de stream con la misma forma que escribe `events.outbox_put_op`."""
    item = events.outbox_put_op(event_type, data or {"report_id": "R1"})["Put"]["Item"]
    image = {k: TypeSerializer().serialize(v) for k, v in item.items()}
    return {"eventName": event_name, "dynamodb": {"NewImage": image}}


def test_publica_los_insert_con_el_sobre(bus):
    records = [_record("report.created", {"report_id": "R1"}), _record("incident.updated", {"incident_id": "I1"})]
    assert enrutadora_de_outbox.handler({"Records": records}, None) == {"published": 2}
    got = {m["detail-type"]: m for m in bus()}
    assert set(got) == {"report.created", "incident.updated"}
    msg = got["report.created"]
    assert msg["source"] == "red-telecorp"
    assert msg["detail"]["type"] == "report.created"
    assert msg["detail"]["version"] == 1
    assert msg["detail"]["data"] == {"report_id": "R1"}
    assert msg["detail"]["event_id"] and msg["detail"]["occurred_at"].endswith("Z")


def test_solo_insert(bus):
    records = [_record(event_name="MODIFY"), _record(event_name="REMOVE"), _record()]
    # REMOVE real llega sin NewImage
    records[1]["dynamodb"] = {}
    assert enrutadora_de_outbox.handler({"Records": records}, None) == {"published": 1}
    assert len(bus()) == 1


def test_lote_vacio_no_llama_a_put_events(bus, monkeypatch):
    monkeypatch.setattr(enrutadora_de_outbox, "_events_client", lambda: pytest.fail("no debe llamarse"))
    assert enrutadora_de_outbox.handler({"Records": []}, None) == {"published": 0}
    assert enrutadora_de_outbox.handler({"Records": [_record(event_name="MODIFY")]}, None) == {"published": 0}


def test_registro_incompleto_se_descarta(bus):
    roto = _record()
    del roto["dynamodb"]["NewImage"]["detail"]
    assert enrutadora_de_outbox.handler({"Records": [roto, _record()]}, None) == {"published": 1}
    assert len(bus()) == 1


def test_entradas_fallidas_lanzan_error(bus, monkeypatch):
    class Falla:
        def put_events(self, Entries):  # noqa: N803 - firma de boto3
            return {
                "FailedEntryCount": 1,
                "Entries": [{"EventId": "1"}, {"ErrorCode": "ThrottlingException", "ErrorMessage": "x"}],
            }

    monkeypatch.setattr(enrutadora_de_outbox, "_events_client", lambda: Falla())
    with pytest.raises(RuntimeError) as exc:
        enrutadora_de_outbox.handler({"Records": [_record(), _record()]}, None)
    assert "ThrottlingException" in str(exc.value)


def test_mas_de_diez_registros_se_parten(bus, monkeypatch):
    sizes = []
    real = enrutadora_de_outbox._events_client()

    class Espia:
        def put_events(self, Entries):  # noqa: N803 - firma de boto3
            sizes.append(len(Entries))
            return real.put_events(Entries=Entries)

    monkeypatch.setattr(enrutadora_de_outbox, "_events_client", lambda: Espia())
    assert enrutadora_de_outbox.handler({"Records": [_record() for _ in range(12)]}, None) == {"published": 12}
    assert sizes == [10, 2]
    assert len(bus()) == 12


def test_reintento_del_lote_publica_de_nuevo_con_el_mismo_event_id(bus):
    """Entrega al menos una vez: el duplicado conserva el event_id para que el consumidor lo descarte."""
    record = _record()
    enrutadora_de_outbox.handler({"Records": [record]}, None)
    enrutadora_de_outbox.handler({"Records": [record]}, None)
    ids_ = [m["detail"]["event_id"] for m in bus()]
    assert len(ids_) == 2 and ids_[0] == ids_[1]


def test_forma_real_del_item_de_outbox(bus):
    """El ítem que escribe la transacción tiene los atributos que lee la enrutadora."""
    ddb.transact([events.outbox_put_op("report.created", {"report_id": "R9"})])
    item = ddb.table("Outbox").scan()["Items"][0]
    image = {k: TypeSerializer().serialize(v) for k, v in item.items()}
    enrutadora_de_outbox.handler({"Records": [{"eventName": "INSERT", "dynamodb": {"NewImage": image}}]}, None)
    assert bus()[0]["detail"]["data"] == {"report_id": "R9"}
