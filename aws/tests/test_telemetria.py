"""T10: generadora_de_metricas_y_lotes y clasificadora_de_metricas."""
import json
from decimal import Decimal

import boto3
import pytest
from boto3.dynamodb.conditions import Key

from common import ddb, ids
from handlers import clasificadora_de_metricas as clasificadora
from handlers import generadora_de_metricas_y_lotes as generadora

BUCKET = "red-telecorp-test-metricas"
BASE = "2026-11-14T10:00:00.000Z"
ANTENA, ZONA = "A013", "Z05"
PK = f"ANTENNA#{ANTENA}"


@pytest.fixture
def metricas(aws, monkeypatch):
    """Bucket y cola de métricas simulados; devuelve la URL de la cola."""
    boto3.client("s3").create_bucket(Bucket=BUCKET)
    url = boto3.client("sqs").create_queue(QueueName="red-telecorp-test-ColaMetricas")["QueueUrl"]
    monkeypatch.setenv("METRICS_BUCKET", BUCKET)
    monkeypatch.setenv("QUEUE_METRICAS_URL", url)
    return url


def _antena(antenna_id=ANTENA, zone=ZONA, nominal=95):
    ddb.table("NetworkCatalog").put_item(Item={
        "pk": f"ANTENNA#{antenna_id}", "sk": "META", "type": "ANTENNA", "antenna_id": antenna_id,
        "zone_id": zone, "name": f"Antena {antenna_id}", "nominal_gb": nominal,
        "gsi1pk": "TYPE#ANTENNA", "gsi1sk": antenna_id, "gsi2pk": f"ZONE#{zone}", "gsi2sk": f"ANTENNA#{antenna_id}",
    })


def _ts(minutes: int) -> str:
    return ids.shift_iso(BASE, minutes=minutes)


def _record(key: str, bucket=BUCKET) -> dict:
    return {"messageId": f"m-{key}", "body": json.dumps({"bucket": bucket, "key": key})}


def _lote(key: str, lines: list) -> dict:
    """Sube el archivo (cada línea es un dict o texto crudo) y devuelve el registro SQS."""
    body = "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines) + "\n"
    boto3.client("s3").put_object(Bucket=BUCKET, Key=key, Body=body.encode("utf-8"))
    return _record(key)


def _clasificar(*lecturas, antenna_id=ANTENA) -> None:
    """Un lote por lectura `(minuto, gb)`, como en producción."""
    for minuto, gb in lecturas:
        registro = _lote(f"metrics/x/{antenna_id}-{minuto}.jsonl",
                         [{"antenna_id": antenna_id, "ts": _ts(minuto), "gb_per_min": gb}])
        assert clasificadora.handler({"Records": [registro]}, None) == {"batchItemFailures": []}


def _last(antenna_id=ANTENA) -> dict | None:
    return ddb.table("Telemetry").get_item(Key={"pk": f"ANTENNA#{antenna_id}", "sk": "LAST"}).get("Item")


def _episodios(antenna_id=ANTENA) -> list:
    return ddb.query_all(
        "Telemetry", KeyConditionExpression=Key("pk").eq(f"ANTENNA#{antenna_id}") & Key("sk").begins_with("EPISODE#")
    )


def _outbox(event_type=None) -> list:
    items = sorted(ddb.table("Outbox").scan()["Items"], key=lambda i: i["event_id"])
    return [e for e in (json.loads(i["detail"]) for i in items) if event_type in (None, e["type"])]


def _abiertos(zone=ZONA) -> list:
    return ddb.query_all("Telemetry", IndexName="GSI2-open", KeyConditionExpression=Key("gsi2pk").eq(f"OPEN#{zone}"))


# --- clasificadora_de_metricas ---

def test_lectura_normal_solo_actualiza_last(metricas):
    _antena()
    _clasificar((0, 95))
    last = _last()
    assert last["state"] == "NORMAL" and last["zone_id"] == ZONA and last["last_ts"] == _ts(0)
    assert last["gb_per_min"] == 95 and last["consecutive_normals"] == 0 and "open_episode_id" not in last
    assert _episodios() == [] and _outbox() == []


def test_antena_apagada_abre_episodio_y_emite_anomalia(metricas):
    _antena()
    _clasificar((0, 95), (1, 0))
    (episodio,) = _episodios()
    assert episodio["state"] == "INHABILITADA" and episodio["status"] == "OPEN" and episodio["opened_at"] == _ts(1)
    assert episodio["readings"] == 1 and episodio["min_gb"] == 0 and episodio["max_gb"] == 0
    assert episodio["sk"] == f"EPISODE#{_ts(1)}#{episodio['episode_id']}" and episodio["zone_id"] == ZONA
    assert episodio["gsi1pk"] == f"ZONE#{ZONA}" and episodio["gsi1sk"] == f"{_ts(1)}#{ANTENA}"
    assert [e["episode_id"] for e in _abiertos()] == [episodio["episode_id"]]

    last = _last()
    assert last["state"] == "INHABILITADA" and last["open_episode_id"] == episodio["episode_id"]
    assert last["open_episode_sk"] == episodio["sk"] and last["consecutive_normals"] == 0

    (evento,) = _outbox()
    assert evento["type"] == "telemetry.anomaly" and evento["data"] == {
        "antenna_id": ANTENA, "zone_id": ZONA, "episode_id": episodio["episode_id"], "state": "INHABILITADA",
        "gb_per_min": 0, "reason": "OPENED", "opened_at": _ts(1), "episodes_7d": 1,
    }


@pytest.mark.parametrize("gb,estado", [(0, "INHABILITADA"), (59.9, "CAIDA"), (129.5, "SATURADA")])
def test_umbrales_de_anomalia(metricas, gb, estado):
    _antena()
    _clasificar((0, gb))
    assert _episodios()[0]["state"] == estado and _outbox()[0]["data"]["state"] == estado
    assert isinstance(_last()["gb_per_min"], Decimal)


@pytest.mark.parametrize("gb", [60, 129])
def test_limites_normales_no_abren_episodio(metricas, gb):
    _antena()
    _clasificar((0, gb))
    assert _episodios() == [] and _last()["state"] == "NORMAL"


def test_anomalia_con_episodio_abierto_acumula_y_escala(metricas):
    _antena()
    _clasificar((0, 140), (1, 150), (2, 40))  # SATURADA, SATURADA, CAIDA
    (episodio,) = _episodios()
    assert episodio["state"] == "CAIDA" and episodio["readings"] == 3
    assert episodio["min_gb"] == 40 and episodio["max_gb"] == 150
    abierto, escalado = _outbox("telemetry.anomaly")
    assert abierto["data"]["reason"] == "OPENED" and abierto["data"]["state"] == "SATURADA"
    assert escalado["data"] == {
        "antenna_id": ANTENA, "zone_id": ZONA, "episode_id": episodio["episode_id"], "state": "CAIDA",
        "gb_per_min": 40, "reason": "ESCALATED", "opened_at": _ts(0), "episodes_7d": 1,
    }
    # Mejora sin volver a normal: el episodio conserva el peor estado y no hay más eventos.
    _clasificar((3, 0), (4, 30))
    (episodio,) = _episodios()
    assert episodio["state"] == "INHABILITADA" and episodio["readings"] == 5 and _last()["state"] == "CAIDA"
    assert [e["data"]["reason"] for e in _outbox()] == ["OPENED", "ESCALATED", "ESCALATED"]


def test_cinco_normales_seguidas_cierran_el_episodio(metricas):
    _antena()
    _clasificar((0, 0), (1, 95), (2, 95), (3, 95), (4, 95))
    assert _episodios()[0]["status"] == "OPEN" and _last()["consecutive_normals"] == 4
    assert len(_outbox()) == 1

    _clasificar((5, 95))
    (episodio,) = _episodios()
    assert episodio["status"] == "CLOSED" and episodio["closed_at"] == _ts(5) and episodio["duration_seconds"] == 300
    assert "gsi2pk" not in episodio and "gsi2sk" not in episodio and episodio["gsi1pk"] == f"ZONE#{ZONA}"
    assert _abiertos() == []
    last = _last()
    assert "open_episode_id" not in last and "open_episode_sk" not in last and last["consecutive_normals"] == 0
    (recuperado,) = _outbox("telemetry.recovered")
    assert recuperado["data"] == {
        "antenna_id": ANTENA, "zone_id": ZONA, "episode_id": episodio["episode_id"], "closed_at": _ts(5),
        "duration_seconds": 300,
    }


def test_una_anomalia_reinicia_la_cuenta_de_normales(metricas):
    _antena()
    _clasificar((0, 0), (1, 95), (2, 95), (3, 95), (4, 95), (5, 0), (6, 95), (7, 95), (8, 95), (9, 95))
    (episodio,) = _episodios()
    assert episodio["status"] == "OPEN" and episodio["readings"] == 2 and _last()["consecutive_normals"] == 4
    assert _outbox("telemetry.recovered") == []
    _clasificar((10, 95))
    assert _episodios()[0]["status"] == "CLOSED"


def _episodio_completo(inicio: int) -> None:
    _clasificar((inicio, 0), *[(inicio + n, 95) for n in range(1, 6)])


def test_tres_episodios_en_siete_dias_emiten_recurrencia(metricas):
    _antena()
    dia = 24 * 60
    _episodio_completo(0)
    _episodio_completo(2 * dia)
    assert _outbox("telemetry.recurrent") == []
    _clasificar((6 * dia, 0))
    assert [e["data"]["episodes_7d"] for e in _outbox("telemetry.anomaly")] == [1, 2, 3]
    (recurrente,) = _outbox("telemetry.recurrent")
    assert recurrente["data"] == {
        "antenna_id": ANTENA, "zone_id": ZONA, "episodes_7d": 3, "window_start": _ts(6 * dia - 7 * dia),
    }


def test_episodios_fuera_de_la_ventana_no_cuentan(metricas):
    _antena()
    dia = 24 * 60
    _episodio_completo(0)
    _episodio_completo(2 * dia)
    _clasificar((8 * dia, 0))  # el primero quedó a más de 7 días
    assert [e["data"]["episodes_7d"] for e in _outbox("telemetry.anomaly")] == [1, 2, 2]
    assert _outbox("telemetry.recurrent") == []


def test_mensaje_repetido_y_lecturas_viejas_no_repiten(metricas):
    _antena()
    registro = _lote("metrics/x/a.jsonl", [{"antenna_id": ANTENA, "ts": _ts(1), "gb_per_min": 0}])
    for _ in range(2):
        assert clasificadora.handler({"Records": [registro]}, None) == {"batchItemFailures": []}
    assert len(_episodios()) == 1 and len(_outbox()) == 1 and _episodios()[0]["readings"] == 1
    _clasificar((0, 95))  # anterior a last_ts: se ignora
    assert _last()["last_ts"] == _ts(1) and _last()["state"] == "INHABILITADA"


def test_un_lote_con_varias_antenas_y_lecturas_desordenadas(metricas):
    _antena()
    _antena("A014")
    registro = _lote("metrics/x/b.jsonl", [
        {"antenna_id": ANTENA, "ts": _ts(2), "gb_per_min": 40},
        {"antenna_id": "A014", "ts": _ts(1), "gb_per_min": 95.5},
        {"antenna_id": ANTENA, "ts": _ts(1), "gb_per_min": 140},
    ])
    assert clasificadora.handler({"Records": [registro]}, None) == {"batchItemFailures": []}
    (episodio,) = _episodios()
    assert episodio["opened_at"] == _ts(1) and episodio["state"] == "CAIDA" and episodio["readings"] == 2
    assert _last("A014")["state"] == "NORMAL" and _last("A014")["gb_per_min"] == Decimal("95.5")
    assert _episodios("A014") == []


def test_lineas_invalidas_y_antena_desconocida_se_descartan(metricas):
    _antena()
    registro = _lote("metrics/x/c.jsonl", [
        "no es json", "[]", {"antenna_id": ANTENA, "ts": _ts(1)}, {"antenna_id": ANTENA, "ts": "ayer", "gb_per_min": 1},
        {"antenna_id": ANTENA, "ts": _ts(1), "gb_per_min": -1}, {"antenna_id": ANTENA, "ts": _ts(1), "gb_per_min": "0"},
        {"antenna_id": ANTENA, "ts": _ts(1), "gb_per_min": True}, {"antenna_id": 7, "ts": _ts(1), "gb_per_min": 0},
        '{"antenna_id": "A013", "ts": "2026-11-14T10:01:00.000Z", "gb_per_min": NaN}',
        {"antenna_id": "A999", "ts": _ts(1), "gb_per_min": 0},
        {"antenna_id": ANTENA, "ts": _ts(2), "gb_per_min": 95},
    ])
    assert clasificadora.handler({"Records": [registro]}, None) == {"batchItemFailures": []}
    assert _last()["last_ts"] == _ts(2) and _last("A999") is None
    assert _episodios() == [] and _episodios("A999") == [] and _outbox() == []


@pytest.mark.parametrize("body", [
    "no es json", json.dumps({}), json.dumps({"bucket": BUCKET}), json.dumps({"bucket": BUCKET, "key": 5}),
    json.dumps({"bucket": BUCKET, "key": "otros/a.jsonl"}), json.dumps({"bucket": "otro-bucket", "key": "metrics/a"}),
    json.dumps({"bucket": BUCKET, "key": "metrics/no-existe.jsonl"}),
])
def test_mensaje_invalido_se_descarta_sin_reintento(metricas, body):
    assert clasificadora.handler({"Records": [{"messageId": "m1", "body": body}]}, None) == {"batchItemFailures": []}
    assert _outbox() == []


def test_un_fallo_devuelve_el_registro_a_la_cola(metricas, monkeypatch):
    _antena()
    registro = _lote("metrics/x/d.jsonl", [{"antenna_id": ANTENA, "ts": _ts(1), "gb_per_min": 0}])

    def falla(ops):
        raise RuntimeError("DynamoDB no disponible")

    monkeypatch.setattr(ddb, "transact", falla)
    resp = clasificadora.handler({"Records": [registro]}, None)
    assert resp == {"batchItemFailures": [{"itemIdentifier": registro["messageId"]}]}
    assert _last() is None and _outbox() == []


def test_carrera_en_last_relee_y_no_duplica(metricas, monkeypatch):
    _antena()
    registro = _lote("metrics/x/e.jsonl", [{"antenna_id": ANTENA, "ts": _ts(1), "gb_per_min": 0}])
    real, calls = ddb.transact, []

    def carrera(ops):
        calls.append(1)
        if len(calls) == 1:  # otra ejecución procesa el mismo lote justo antes
            monkeypatch.setattr(ddb, "transact", real)
            clasificadora.handler({"Records": [registro]}, None)
            monkeypatch.setattr(ddb, "transact", carrera)
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    assert clasificadora.handler({"Records": [registro]}, None) == {"batchItemFailures": []}
    assert len(calls) == 1 and len(_episodios()) == 1 and len(_outbox()) == 1


# --- generadora_de_metricas_y_lotes ---

def _escenario(overrides: dict, expires_at: str) -> None:
    ddb.table("NetworkCatalog").put_item(Item={
        "pk": "SCENARIO#ACTIVE", "sk": "META", "type": "SCENARIO", "overrides": overrides, "expires_at": expires_at,
    })


def _archivo(key: str) -> list:
    raw = boto3.client("s3").get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8")
    return [json.loads(line, parse_float=Decimal) for line in raw.splitlines()]


def _mensajes(url: str) -> list:
    msgs = boto3.client("sqs").receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])
    return [{"messageId": m["MessageId"], "body": m["Body"]} for m in msgs]


def test_generadora_escribe_el_lote_y_avisa_por_la_cola(metricas):
    for n in (13, 14, 15):
        _antena(f"A{n:03d}")
    resp = generadora.handler({"time": "2026-11-14T20:01:37Z"}, None)
    key = "metrics/2026-11-14/20-01.jsonl"
    assert resp == {"key": key, "antennas": 3, "overrides": 0}
    filas = _archivo(key)
    assert [f["antenna_id"] for f in filas] == ["A013", "A014", "A015"]
    assert all(f["ts"] == "2026-11-14T20:01:00.000Z" for f in filas)
    assert all(Decimal("80.75") <= f["gb_per_min"] <= Decimal("109.25") for f in filas)
    (mensaje,) = _mensajes(metricas)
    assert json.loads(mensaje["body"]) == {"bucket": BUCKET, "key": key}
    # Reintento del mismo minuto: mismo archivo.
    generadora.handler({"time": "2026-11-14T20:01:37Z"}, None)
    assert _archivo(key) == filas


def test_generadora_sin_hora_en_el_evento_usa_el_minuto_actual(metricas):
    _antena()
    resp = generadora.handler({}, None)
    (fila,) = _archivo(resp["key"])
    assert fila["ts"].endswith(":00.000Z") and fila["ts"] <= ids.now_iso()


def test_generadora_sin_antenas_no_escribe(metricas):
    assert generadora.handler({}, None) == {"key": None, "antennas": 0, "overrides": 0}
    assert _mensajes(metricas) == []


def test_escenario_expirado_se_ignora(metricas):
    _antena()
    _escenario({ANTENA: Decimal("0")}, ids.shift_iso(ids.now_iso(), minutes=-1))
    resp = generadora.handler({"time": "2026-11-14T20:01:00Z"}, None)
    assert resp["overrides"] == 0 and _archivo(resp["key"])[0]["gb_per_min"] > 60


def test_escenario_apaga_una_antena_y_la_clasificadora_abre_el_episodio(metricas):
    _antena()
    _antena("A014")
    _escenario({ANTENA: Decimal("0")}, ids.shift_iso(ids.now_iso(), minutes=15))
    resp = generadora.handler({"time": "2026-11-14T20:01:00Z"}, None)
    assert resp["overrides"] == 1
    assert clasificadora.handler({"Records": _mensajes(metricas)}, None) == {"batchItemFailures": []}
    (episodio,) = _episodios()
    assert episodio["state"] == "INHABILITADA" and episodio["opened_at"] == "2026-11-14T20:01:00.000Z"
    assert _episodios("A014") == [] and _last("A014")["state"] == "NORMAL"
    (evento,) = _outbox()
    assert evento["type"] == "telemetry.anomaly" and evento["data"]["antenna_id"] == ANTENA
