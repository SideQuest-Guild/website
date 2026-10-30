"""Guards the API reference against new routes/schemas added without docs.

Every assertion here checks the OpenAPI document the API actually serves (``GET /schema/openapi.json``), not the
Python source, so it catches anything Scalar would show undocumented: a missing summary/description, a response
or parameter left with Litestar's stock text, an orphan tag, or a tag in no ``x-tagGroups`` group (or two).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient


async def _openapi_document(client: AsyncTestClient[Litestar]) -> dict[str, Any]:
    response = await client.get("/schema/openapi.json")
    assert response.status_code == 200
    return response.json()


def _operations(document: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Every ``(path, method, operation)`` triple in the document, skipping hidden (``include_in_schema=False``)
    routes (which never reach ``paths`` in the first place) and the ``/schema/*`` routes that serve the
    document, Scalar, and friends -- infrastructure, not part of the API's own surface."""
    return [
        (path, method, operation)
        for path, path_item in document["paths"].items()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"} and not path.startswith("/schema")
    ]


async def test_every_operation_has_a_summary_and_description(client: AsyncTestClient[Litestar]) -> None:
    document = await _openapi_document(client)
    missing = [
        f"{method.upper()} {path} ({operation.get('operationId')})"
        for path, method, operation in _operations(document)
        if not operation.get("summary", "").strip() or not operation.get("description", "").strip()
    ]
    assert not missing, f"operations missing a summary/description: {missing}"


async def test_every_tag_has_a_description(client: AsyncTestClient[Litestar]) -> None:
    document = await _openapi_document(client)
    tags = document.get("tags", [])
    assert tags, "the document has no tags at all"
    missing = [tag["name"] for tag in tags if not tag.get("description", "").strip()]
    assert not missing, f"tags missing a description: {missing}"


async def test_every_operation_tag_is_in_exactly_one_group(client: AsyncTestClient[Litestar]) -> None:
    document = await _openapi_document(client)
    tag_groups: list[dict[str, Any]] = document.get("x-tagGroups", [])
    assert tag_groups, "the document has no x-tagGroups extension"

    tag_to_groups: dict[str, list[str]] = {}
    for group in tag_groups:
        for tag_name in group["tags"]:
            tag_to_groups.setdefault(tag_name, []).append(group["name"])
    duplicated = {tag: groups for tag, groups in tag_to_groups.items() if len(groups) > 1}
    assert not duplicated, f"tags in more than one group: {duplicated}"

    known_tag_names = {tag["name"] for tag in document.get("tags", [])}
    grouped_tag_names = set(tag_to_groups)
    assert known_tag_names == grouped_tag_names, (
        f"tags with no group: {known_tag_names - grouped_tag_names}; "
        f"grouped names not declared as tags: {grouped_tag_names - known_tag_names}"
    )

    orphaned = [
        f"{method.upper()} {path} ({operation.get('operationId')}): tags={operation.get('tags')}"
        for path, method, operation in _operations(document)
        for tag_name in operation.get("tags", [])
        if tag_name not in grouped_tag_names
    ]
    assert not orphaned, f"operations with a tag outside every group: {orphaned}"

    untagged = [
        f"{method.upper()} {path} ({operation.get('operationId')})"
        for path, method, operation in _operations(document)
        if not operation.get("tags")
    ]
    assert not untagged, f"operations with no tag: {untagged}"


def _is_stock_response_description(status_code: str, description: str) -> bool:
    try:
        stock = HTTPStatus(int(status_code)).description
    except ValueError, KeyError:
        return False
    return description.strip() == stock


async def test_no_response_uses_the_stock_http_phrase(client: AsyncTestClient[Litestar]) -> None:
    document = await _openapi_document(client)
    offenders = []
    for path, method, operation in _operations(document):
        for status_code, response in operation.get("responses", {}).items():
            description = response.get("description", "")
            if not description.strip() or _is_stock_response_description(status_code, description):
                label = f"{method.upper()} {path} ({operation.get('operationId')}) {status_code}"
                offenders.append(f"{label}: {description!r}")
    assert not offenders, f"responses with the stock HTTP phrase (or no description): {offenders}"


async def test_every_parameter_has_a_description(client: AsyncTestClient[Litestar]) -> None:
    document = await _openapi_document(client)
    missing = [
        f"{method.upper()} {path} ({operation.get('operationId')}): {parameter['name']}"
        for path, method, operation in _operations(document)
        for parameter in operation.get("parameters", [])
        if not parameter.get("description", "").strip()
    ]
    assert not missing, f"parameters missing a description: {missing}"


async def test_every_component_schema_has_a_description(client: AsyncTestClient[Litestar]) -> None:
    document = await _openapi_document(client)
    schemas: dict[str, Any] = document.get("components", {}).get("schemas", {})
    assert schemas, "the document has no component schemas at all"
    missing = [name for name, schema in schemas.items() if not schema.get("description", "").strip()]
    assert not missing, f"component schemas missing a description: {missing}"


async def test_document_has_a_plain_intro_and_security_schemes(client: AsyncTestClient[Litestar]) -> None:
    document = await _openapi_document(client)
    assert document["info"]["description"].strip()
    security_schemes = document.get("components", {}).get("securitySchemes", {})
    assert {"SessionAuth", "ApiKeyAuth"}.issubset(security_schemes)
