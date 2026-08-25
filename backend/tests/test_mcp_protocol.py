from __future__ import annotations

import unittest

from app.capabilities import CapabilityError
from app.mcp_protocol import McpProtocol


class FakeGateway:
    async def execute(
        self,
        name: str,
        arguments: object,
        *,
        conversation_id: str | None = None,
    ) -> object:
        if name == "vision_analyze":
            raise CapabilityError("CAPABILITY_NOT_CONFIGURED", "vision unavailable")
        return {"name": name, "arguments": arguments}


class McpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_and_tools_list(self) -> None:
        protocol = McpProtocol(FakeGateway())  # type: ignore[arg-type]
        initialized = await protocol.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            }
        )
        self.assertEqual("2025-03-26", initialized["result"]["protocolVersion"])  # type: ignore[index]
        listed = await protocol.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {item["name"] for item in listed["result"]["tools"]}  # type: ignore[index]
        self.assertIn("document_extract", names)
        self.assertIn("delegate_text", names)

    async def test_unconfigured_tool_is_an_explicit_mcp_error_result(self) -> None:
        protocol = McpProtocol(FakeGateway())  # type: ignore[arg-type]
        response = await protocol.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "vision_analyze", "arguments": {"prompt": "x"}},
            }
        )
        result = response["result"]  # type: ignore[index]
        self.assertTrue(result["isError"])
        self.assertEqual(
            "CAPABILITY_NOT_CONFIGURED", result["structuredContent"]["error"]["code"]
        )


if __name__ == "__main__":
    unittest.main()
