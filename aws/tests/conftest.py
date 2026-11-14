import boto3
import pytest
from moto import mock_aws

import schema
from common import config, ddb


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("STAGE", "test")
    monkeypatch.setenv("SSM_PREFIX", "/red-telecorp/test")
    for logical, env_name in config.TABLES.items():
        monkeypatch.setenv(env_name, f"red-telecorp-test-{logical}")
    ddb.reset()
    config.get_secret.cache_clear()
    yield
    ddb.reset()
    config.get_secret.cache_clear()


@pytest.fixture
def aws(aws_env):
    """Entorno AWS simulado con las 7 tablas del contrato ya creadas."""
    with mock_aws():
        ddb.reset()
        client = boto3.client("dynamodb")
        for logical in schema.GSIS:
            client.create_table(**schema.create_table_kwargs(logical, f"red-telecorp-test-{logical}"))
        yield
