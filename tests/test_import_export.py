import json

import pytest

from hitman.core.exporters import export_hitman, export_postman, to_json
from hitman.core.importers import ImportFormatError, parse_import
from hitman.core.models import Auth, Collection, Folder, KeyValue, Request, Variable, count_requests


def _collection():
    return Collection(
        name="Acme Store API", auth=Auth.with_variables("bearer"),
        variables=[Variable("baseUrl", "https://api.dev"), Variable("secret", "x", secret=True)],
        items=[
            Folder(name="Users", items=[
                Request(name="Get user", url="{{baseUrl}}/users/:id?include=orders",
                        params=[KeyValue("include", "orders", "Embed"), KeyValue("fields", "id", enabled=False)],
                        path_vars=[KeyValue("id", "{{userId}}", "User ID")],
                        headers=[KeyValue("Accept", "application/json")]),
            ]),
            Request(name="Create order", method="POST", url="{{baseUrl}}/orders", body_mode="raw",
                    body='{"a": 1}', auth=Auth(type="none")),
            Request(name="Login", method="POST", url="{{baseUrl}}/login", body_mode="urlencoded",
                    form=[KeyValue("user", "bob")]),
        ])


def _strip_ids(items):
    out = []
    for node in items:
        if isinstance(node, Folder):
            out.append(("folder", node.name, _strip_ids(node.items)))
        else:
            data = node.to_dict()
            data.pop("id")
            out.append(("request", data))
    return out


@pytest.mark.parametrize("exporter", [export_hitman, export_postman])
def test_roundtrip_preserves_requests(exporter):
    original = _collection()
    result = parse_import(to_json(exporter(original)))
    assert result.collection.name == original.name
    assert _strip_ids(result.collection.items) == _strip_ids(original.items)
    assert result.collection.auth.type == "bearer"
    assert {v.key for v in result.collection.variables} == {"baseUrl"}  # secrets never exported


def test_detects_curl():
    result = parse_import("curl https://x.dev/ping")
    assert result.kind == "curl" and result.request.url == "https://x.dev/ping"


def test_openapi_yaml_import():
    spec = """
openapi: 3.0.3
info: {title: Petstore}
servers: [{url: "https://{env}.pets.dev/v3", variables: {env: {default: api}}}]
components:
  securitySchemes:
    token: {type: http, scheme: bearer}
  schemas:
    Pet:
      type: object
      properties:
        name: {type: string, example: doggie}
        tags: {type: array, items: {type: string}}
paths:
  /pet/{petId}:
    parameters:
      - {name: petId, in: path, required: true, schema: {type: integer, example: 7}}
    get:
      tags: [pet]
      summary: Find pet by ID
  /pet:
    post:
      tags: [pet]
      summary: Add a new pet
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Pet'}
  /store/inventory:
    get:
      summary: Inventory
      parameters:
        - {name: limit, in: query, required: true, schema: {type: integer, default: 10}}
"""
    result = parse_import(spec)
    col = result.collection
    assert result.kind == "openapi" and col.name == "Petstore"
    assert col.variables[0].value == "https://api.pets.dev/v3"
    assert col.auth.type == "bearer"
    assert count_requests(col.items) == 3 and result.folder_count == 1
    pet = col.items[0]
    get_pet, add_pet = pet.items
    assert get_pet.url == "{{baseUrl}}/pet/:petId" and get_pet.path_vars[0].value == "7"
    assert json.loads(add_pet.body) == {"name": "doggie", "tags": ["string"]}
    inventory = col.items[1]
    assert inventory.url == "{{baseUrl}}/store/inventory?limit=10"


@pytest.mark.parametrize("text, message", [
    ("", "Nothing"),
    ("{not json", "Invalid JSON"),
    ('{"hello": 1}', "Not a collection"),
    ('{"swagger": "2.0"}', "Swagger"),
])
def test_import_errors(text, message):
    with pytest.raises(ImportFormatError, match=message):
        parse_import(text)
