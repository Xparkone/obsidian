import json
import unittest

from integrations.aegis_mcp_server import handle_message


class McpProtocolTest(unittest.TestCase):
    def test_initialize(self):
        response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(response["result"]["serverInfo"]["name"], "aegis-mcp")

    def test_tools_list(self):
        response = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertEqual(names, {"aegis_list_servers", "aegis_execute", "aegis_get_audit"})

    def test_notification_has_no_response(self):
        self.assertIsNone(handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}))


if __name__ == "__main__":
    unittest.main()
