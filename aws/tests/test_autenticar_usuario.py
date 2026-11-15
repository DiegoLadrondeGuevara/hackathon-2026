import json

import boto3
import pytest

from common import auth, ddb
from handlers import autenticar_usuario, autorizar_jwt

PASSWORD = "clave-de-prueba"


@pytest.fixture
def perfiles(aws):
    boto3.client("ssm").put_parameter(
        Name="/red-telecorp/test/jwt/signing_key", Value="clave-de-firma-de-prueba", Type="SecureString"
    )
    table = ddb.table("CustomerProfiles")
    hashed = auth.hash_password(PASSWORD)
    table.put_item(
        Item={
            "pk": "CUSTOMER#70000001",
            "sk": "PROFILE",
            "type": "CUSTOMER",
            "customer_id": "70000001",
            "role": "CUSTOMER",
            "full_name": "Cliente Uno",
            "password_hash": hashed,
        }
    )
    table.put_item(
        Item={
            "pk": "OPERATOR#op001",
            "sk": "PROFILE",
            "type": "OPERATOR",
            "operator_id": "op001",
            "role": "OPERATOR",
            "full_name": "Operador Demo",
            "password_hash": hashed,
        }
    )


def _login(identifier, password=PASSWORD):
    event = {"body": json.dumps({"identifier": identifier, "password": password})}
    resp = autenticar_usuario.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def test_login_de_cliente(perfiles):
    status, body = _login("70000001")
    assert status == 200
    assert body["role"] == "CUSTOMER"
    assert body["name"] == "Cliente Uno"
    assert body["expires_in"] == 900
    claims = auth.verify_token(body["token"])
    assert claims["sub"] == "70000001"
    assert claims["role"] == "CUSTOMER"
    assert claims["exp"] - claims["iat"] == 900


def test_login_de_operador(perfiles):
    status, body = _login("op001")
    assert status == 200
    assert body["role"] == "OPERATOR"
    assert auth.verify_token(body["token"])["sub"] == "op001"


def test_token_del_login_pasa_por_el_autorizador(perfiles):
    _, body = _login("70000001")
    result = autorizar_jwt.handler({"headers": {"authorization": f"Bearer {body['token']}"}}, None)
    assert result == {"isAuthorized": True, "context": {"sub": "70000001", "role": "CUSTOMER"}}


def test_clave_incorrecta_e_inexistente_responden_igual(perfiles):
    incorrecta = _login("70000001", "otra-clave")
    inexistente = _login("99999999")
    assert incorrecta[0] == inexistente[0] == 401
    assert incorrecta[1] == inexistente[1]
    assert incorrecta[1]["error"]["code"] == "UNAUTHORIZED"


def test_perfil_sin_hash_valido_no_entra(perfiles):
    ddb.table("CustomerProfiles").put_item(
        Item={"pk": "CUSTOMER#70000002", "sk": "PROFILE", "role": "CUSTOMER", "password_hash": "roto"}
    )
    assert _login("70000002")[0] == 401


@pytest.mark.parametrize(
    "body",
    [
        None,
        "no es json",
        "[]",
        json.dumps({"identifier": "70000001"}),
        json.dumps({"password": PASSWORD}),
        json.dumps({"identifier": 70000001, "password": PASSWORD}),
        json.dumps({"identifier": "70000001", "password": ""}),
        json.dumps({"identifier": "x" * 65, "password": PASSWORD}),
    ],
)
def test_cuerpo_invalido_da_400(perfiles, body):
    resp = autenticar_usuario.handler({"body": body}, None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"]["code"] == "VALIDATION"
