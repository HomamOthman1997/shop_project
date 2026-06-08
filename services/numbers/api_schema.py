from __future__ import annotations

from typing import Any

from services.numbers.api_payloads import api_discovery_payload


def _schema_ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _json_response(schema: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "description": "JSON response",
        "content": {
            "application/json": {
                "schema": schema or {"type": "object", "additionalProperties": True},
            }
        },
    }


def _error_response(description: str = "Error response") -> dict[str, Any]:
    return _json_response(
        {
            "type": "object",
            "required": ["ok", "error", "code"],
            "properties": {
                "ok": {"type": "boolean", "example": False},
                "error": {"type": "string"},
                "code": {"type": "string"},
            },
            "additionalProperties": True,
            "description": description,
        }
    )


def _bearer_security(scope: str = "") -> list[dict[str, list[str]]]:
    if not scope or scope == "public":
        return []
    return [{"BearerAuth": []}]


def _operation(
    *,
    summary: str,
    action_key: str,
    tags: list[str],
    description: str = "",
    request_body: dict[str, Any] | None = None,
    parameters: list[dict[str, Any]] | None = None,
    success_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action = api_discovery_payload()["actions"][action_key]
    scope = str(action.get("scope") or "")
    operation: dict[str, Any] = {
        "summary": summary,
        "description": description or str(action.get("reason") or ""),
        "tags": tags,
        "operationId": action_key,
        "responses": {
            "200": _json_response(success_schema),
            "400": _error_response("Invalid request."),
            "401": _error_response("Missing or invalid API key."),
            "429": _error_response("Rate limit exceeded."),
        },
    }
    if scope and scope != "public":
        operation["security"] = _bearer_security(scope)
        operation["x-required-scope"] = scope
    if action.get("requires_idempotency_key"):
        operation.setdefault("parameters", []).append(
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": False,
                "schema": {"type": "string"},
                "description": "Recommended idempotency key for safe retries.",
            }
        )
    if parameters:
        operation.setdefault("parameters", []).extend(parameters)
    if request_body:
        operation["requestBody"] = request_body
    return operation


def _path_param(name: str, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": description,
    }


def _query_param(name: str, description: str, *, enum: list[str] | None = None, default: Any = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if enum:
        schema["enum"] = enum
    if default is not None:
        schema["default"] = default
    return {"name": name, "in": "query", "required": False, "schema": schema, "description": description}


def _json_body(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "required": True,
        "content": {"application/json": {"schema": schema}},
    }


def numbers_openapi_schema() -> dict[str, Any]:
    discovery = api_discovery_payload()
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Phantom Numbers API",
            "version": "v1",
            "description": (
                "API-first Numbers platform contract for temporary SMS, rental numbers, "
                "voice call numbers, customer webhooks, account discovery, and order actions."
            ),
        },
        "servers": [{"url": discovery["base_path"], "description": "Numbers API base path"}],
        "security": [{"BearerAuth": []}],
        "tags": [
            {"name": "Catalog"},
            {"name": "Account"},
            {"name": "Quotes"},
            {"name": "Orders"},
            {"name": "Rental"},
            {"name": "Support"},
        ],
        "paths": {
            "/docs": {
                "get": _operation(
                    summary="Human-readable API documentation",
                    action_key="api_docs",
                    tags=["Catalog"],
                    description="Self-hosted HTML documentation generated from the runtime OpenAPI schema and action catalog.",
                    success_schema={"type": "string", "description": "HTML document."},
                )
            },
            "/openapi.json": {
                "get": _operation(
                    summary="OpenAPI schema",
                    action_key="openapi",
                    tags=["Catalog"],
                    description="Generated OpenAPI 3.1 contract for the public Numbers API.",
                )
            },
            "/health": {"get": _operation(summary="Health check", action_key="bootstrap", tags=["Catalog"], success_schema=_schema_ref("HealthResponse"))},
            "/catalog/bootstrap": {
                "get": _operation(
                    summary="Catalog bootstrap and API discovery",
                    action_key="bootstrap",
                    tags=["Catalog"],
                    description="Returns selectors plus api.capabilities and api.actions for external clients.",
                    success_schema=_schema_ref("BootstrapResponse"),
                )
            },
            "/country-suggestions": {
                "get": _operation(
                    summary="Ranked country suggestions",
                    action_key="country_suggestions",
                    tags=["Catalog", "Quotes"],
                    parameters=[
                        _query_param("mode", "Quote mode.", enum=["temp", "rental", "voice"], default="temp"),
                        _query_param("service", "Canonical service key or alias."),
                        _query_param("limit", "Maximum number of rows."),
                    ],
                )
            },
            "/account": {"get": _operation(summary="Account and wallet snapshot", action_key="account", tags=["Account"])},
            "/recharge": {"get": _operation(summary="Recharge options", action_key="recharge", tags=["Account"])},
            "/recharge/requests": {
                "get": _operation(
                    summary="Recent recharge requests",
                    action_key="recharge_requests",
                    tags=["Account"],
                    parameters=[_query_param("limit", "Maximum number of rows.")],
                )
            },
            "/recharge/submit": {
                "post": _operation(
                    summary="Submit recharge proof",
                    action_key="submit_recharge",
                    tags=["Account"],
                    request_body={
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["method_code", "paid_amount", "proof"],
                                    "properties": {
                                        "method_code": {"type": "string"},
                                        "paid_amount": {"type": "string"},
                                        "language": {"type": "string", "enum": ["en", "ar"], "default": "ar"},
                                        "proof": {"type": "string", "format": "binary"},
                                    },
                                }
                            }
                        },
                    },
                )
            },
            "/support": {"get": _operation(summary="Support options", action_key="support", tags=["Support"])},
            "/support/ticket": {
                "post": _operation(
                    summary="Submit support ticket",
                    action_key="submit_ticket",
                    tags=["Support"],
                    request_body={
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["category", "message"],
                                    "properties": {
                                        "category": {"type": "string", "enum": ["numbers", "services", "user_balance"]},
                                        "message": {"type": "string", "minLength": 3, "maxLength": 3500},
                                        "language": {"type": "string", "enum": ["en", "ar"], "default": "ar"},
                                    },
                                }
                            }
                        },
                    },
                )
            },
            "/quotes": {
                "get": _operation(
                    summary="Quote providers",
                    action_key="quotes",
                    tags=["Quotes"],
                    parameters=[
                        _query_param("mode", "Quote mode.", enum=["temp", "rental", "voice"], default="temp"),
                        _query_param("service", "Canonical service key or alias."),
                        _query_param("country", "Country code, or none.", default="none"),
                        _query_param("state", "US state code, or none.", default="none"),
                    ],
                )
            },
            "/orders": {
                "get": _operation(
                    summary="List orders",
                    action_key="orders",
                    tags=["Orders"],
                    parameters=[
                        _query_param("mode", "Order mode filter.", enum=["all", "temp", "voice", "rental"], default="all"),
                        _query_param("limit", "Maximum number of rows."),
                    ],
                    success_schema=_schema_ref("OrderListResponse"),
                ),
                "post": _operation(
                    summary="Create order from quote",
                    action_key="create_order",
                    tags=["Orders"],
                    request_body=_json_body(
                        {
                            "type": "object",
                            "required": ["quote_token"],
                            "properties": {
                                "quote_token": {"type": "string"},
                                "language": {"type": "string", "enum": ["en", "ar"], "default": "en"},
                                "idempotency_key": {"type": "string"},
                            },
                        }
                    ),
                    success_schema=_schema_ref("OrderResponse"),
                ),
            },
            "/orders/{order_id}": {
                "get": _operation(
                    summary="Get one order",
                    action_key="order_detail",
                    tags=["Orders"],
                    parameters=[_path_param("order_id", "Order id.")],
                    success_schema=_schema_ref("OrderResponse"),
                )
            },
            "/orders/{order_id}/refresh": {
                "post": _operation(
                    summary="Refresh order state",
                    action_key="refresh_order",
                    tags=["Orders"],
                    parameters=[_path_param("order_id", "Order id.")],
                    success_schema=_schema_ref("OrderResponse"),
                )
            },
            "/orders/{order_id}/resend": {
                "post": _operation(
                    summary="Request another SMS/code",
                    action_key="resend_order",
                    tags=["Orders"],
                    parameters=[_path_param("order_id", "Order id.")],
                )
            },
            "/orders/{order_id}/replace": {
                "post": _operation(
                    summary="Replace with same provider family",
                    action_key="replace_order",
                    tags=["Orders"],
                    parameters=[_path_param("order_id", "Order id.")],
                )
            },
            "/orders/{order_id}/alternate": {
                "post": _operation(
                    summary="Replace through alternate provider",
                    action_key="alternate_provider",
                    tags=["Orders"],
                    parameters=[_path_param("order_id", "Order id.")],
                )
            },
            "/orders/{order_id}/recording": {
                "get": _operation(
                    summary="Download voice recording",
                    action_key="download_recording",
                    tags=["Orders"],
                    parameters=[_path_param("order_id", "Order id.")],
                    success_schema={"type": "string", "format": "binary"},
                )
            },
            "/orders/{order_id}/rental/sms": {
                "post": _operation(
                    summary="Read rental SMS state",
                    action_key="rental_sms",
                    tags=["Rental"],
                    parameters=[_path_param("order_id", "Order id.")],
                )
            },
            "/orders/{order_id}/rental/finish": {
                "post": _operation(
                    summary="Finish rental",
                    action_key="rental_finish",
                    tags=["Rental"],
                    parameters=[_path_param("order_id", "Order id.")],
                )
            },
            "/orders/{order_id}/rental/renew": {
                "post": _operation(
                    summary="Renew rental",
                    action_key="rental_renew",
                    tags=["Rental"],
                    parameters=[_path_param("order_id", "Order id.")],
                )
            },
            "/orders/{order_id}/rental/wake": {
                "post": _operation(
                    summary="Wake/reactivate rental",
                    action_key="rental_wake",
                    tags=["Rental"],
                    parameters=[_path_param("order_id", "Order id.")],
                )
            },
            "/orders/{order_id}/rental/notes": {
                "post": _operation(
                    summary="Load rental notes/tags",
                    action_key="rental_notes",
                    tags=["Rental"],
                    parameters=[_path_param("order_id", "Order id.")],
                )
            },
        },
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Customer API key.",
                }
            },
            "schemas": {
                "HealthResponse": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "status": {"type": "string"},
                        "service": {"type": "string"},
                        "version": {"type": "string"},
                    },
                },
                "BootstrapResponse": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "version": {"type": "string"},
                        "modes": {"type": "array", "items": {"type": "object"}},
                        "countries": {"type": "array", "items": {"type": "object"}},
                        "states_us": {"type": "array", "items": {"type": "object"}},
                        "services": {"type": "array", "items": {"type": "object"}},
                        "api": {"type": "object", "additionalProperties": True},
                    },
                    "additionalProperties": True,
                },
                "OrderResponse": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "order": _schema_ref("Order"),
                    },
                    "additionalProperties": True,
                },
                "OrderListResponse": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "mode": {"type": "string"},
                        "orders": {"type": "array", "items": _schema_ref("Order")},
                    },
                },
                "Order": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "public_status": {"type": "string"},
                        "mode": {"type": "string", "enum": ["temp", "rental", "voice"]},
                        "service": {"type": "string"},
                        "country": {"type": "string"},
                        "state": {"type": "string"},
                        "provider_id": {"type": "string"},
                        "number": {"type": "string"},
                        "code": {"type": "string"},
                        "api_actions": {"type": "object", "additionalProperties": {"type": "object"}},
                        "customer_state": {"type": "object", "additionalProperties": True},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "x-phantom-api-discovery": discovery,
    }
