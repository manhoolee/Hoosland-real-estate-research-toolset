from __future__ import annotations

import json
from typing import Any

from .capabilities import CapabilityError, CapabilityGateway, TOOL_DEFINITIONS


SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}


class McpProtocol:
    """Session-light Streamable HTTP MCP request dispatcher.

    The HTTP layer owns authentication and the Mcp-Session-Id header. This
    dispatcher intentionally exposes tools only; resources and prompts are not
    advertised.
    """

    def __init__(self, gateway: CapabilityGateway) -> None:
        self.gateway = gateway

    async def dispatch(
        self,
        request: object,
        *,
        conversation_id: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        if isinstance(request, list):
            if not request:
                return self._error(None, -32600, "Invalid Request")
            responses: list[dict[str, Any]] = []
            for item in request:
                response = await self._dispatch_one(item, conversation_id=conversation_id)
                if response is not None:
                    responses.append(response)
            return responses or None
        return await self._dispatch_one(request, conversation_id=conversation_id)

    async def _dispatch_one(
        self,
        request: object,
        *,
        conversation_id: str | None,
    ) -> dict[str, Any] | None:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return self._error(None, -32600, "Invalid Request")
        request_id = request.get("id")
        method = request.get("method")
        if not isinstance(method, str):
            return self._error(request_id, -32600, "Invalid Request")
        params = request.get("params")
        if params is not None and not isinstance(params, dict):
            return self._error(request_id, -32602, "Invalid params")

        # MCP notifications do not receive JSON-RPC responses.
        if request_id is None:
            return None

        if method == "initialize":
            requested = (params or {}).get("protocolVersion")
            protocol_version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else "2025-03-26"
            return self._result(
                request_id,
                {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "real-estate-capability-gateway", "version": "0.1.0"},
                    "instructions": (
                        "Specialist capability tools are deployment-routed. A registered tool whose "
                        "API is absent returns CAPABILITY_NOT_CONFIGURED; never assume it ran."
                    ),
                },
            )
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            return self._result(
                request_id,
                {"tools": [definition.mcp_dict() for definition in TOOL_DEFINITIONS.values()]},
            )
        if method == "tools/call":
            name = (params or {}).get("name")
            arguments = (params or {}).get("arguments", {})
            if not isinstance(name, str):
                return self._error(request_id, -32602, "tools/call requires a string name")
            try:
                value = await self.gateway.execute(
                    name,
                    arguments,
                    conversation_id=conversation_id,
                )
            except CapabilityError as exc:
                error = exc.as_dict()
                return self._result(
                    request_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error [{exc.code}]: {exc.message}",
                            }
                        ],
                        "structuredContent": {"ok": False, "error": error},
                        "isError": True,
                    },
                )
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            return self._result(
                request_id,
                {
                    "content": [{"type": "text", "text": text}],
                    "structuredContent": {"ok": True, "value": value},
                    "isError": False,
                },
            )
        return self._error(request_id, -32601, f"Method not found: {method}")

    @staticmethod
    def _result(request_id: object, result: object) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: object, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
