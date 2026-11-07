"""
Tests for the OpenAPI schema: tags, the API key security scheme, and public overrides
"""

from main import app

HTTP_METHODS = {"get", "post", "put", "delete", "patch"}
# Public endpoints: the middleware lets them through without an API key, and the
# schema must say so instead of showing a dead "Authorize" button for them.
PUBLIC_PATHS = ["/", "/health", "/health/ready", "/v1/languages"]
EXPECTED_TAGS = ["translation", "conversation", "whatsapp", "account", "health"]


def _operations(schema):
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method in HTTP_METHODS:
                yield method.upper(), path, operation


def test_openapi_declares_the_api_key_scheme():
    schema = app.openapi()

    assert schema["components"]["securitySchemes"]["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    # The middleware requires the key on every non-public route
    assert schema["security"] == [{"ApiKeyAuth": []}]


def test_every_openapi_operation_has_a_tag():
    schema = app.openapi()

    assert [tag["name"] for tag in schema["tags"]] == EXPECTED_TAGS
    known = {tag["name"] for tag in schema["tags"]}
    for method, path, operation in _operations(schema):
        assert operation.get("tags"), f"{method} {path} has no tag"
        assert set(operation["tags"]) <= known, f"{method} {path} uses an unknown tag"


def test_public_endpoints_opt_out_of_the_api_key():
    schema = app.openapi()

    for path in PUBLIC_PATHS:
        assert schema["paths"][path]["get"]["security"] == []


def test_non_public_v1_endpoints_keep_the_api_key_requirement():
    schema = app.openapi()

    v1_paths = [
        path
        for _, path, _ in _operations(schema)
        if path.startswith("/v1/") and path not in PUBLIC_PATHS
    ]
    assert v1_paths  # sanity: the /v1/* surface exists
    for method, path, operation in _operations(schema):
        if path in v1_paths:
            # A route only escapes the global ApiKeyAuth requirement by opting out
            assert operation.get("security") != [], (
                f"{method} {path} must keep requiring the API key"
            )
