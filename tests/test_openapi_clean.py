"""The generated OpenAPI schema (served under /api/docs) has unique operation ids and no warnings, and HEAD still works
on the three HTML pages (uptime checkers use HEAD)."""
import warnings

import pytest

from tests.helpers import make_app


def test_openapi_has_unique_operation_ids_without_warnings(settings):
    client, _pp, _wf = make_app(settings)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        schema = client.get("/openapi.json").json()
    ids = [op["operationId"] for item in schema["paths"].values() for op in item.values()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("path", ["/", "/queue", "/disputes"])
def test_head_still_served_and_hidden_from_schema(settings, path):
    client, _pp, _wf = make_app(settings)
    assert client.head(path).status_code == 200
    assert client.get(path).status_code == 200
    assert "head" not in client.get("/openapi.json").json()["paths"][path]
