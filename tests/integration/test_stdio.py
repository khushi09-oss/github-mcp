"""Exercise the installed server over real stdio, without GitHub credentials."""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class StdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_installed_entrypoints_expose_five_tools(self):
        executable = Path(sys.executable).with_name(
            "github-mcp.exe" if os.name == "nt" else "github-mcp"
        )
        for command, args in (
            (sys.executable, ["-m", "github_mcp"]),
            (str(executable), []),
        ):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as cwd:
                parameters = StdioServerParameters(
                    command=command,
                    args=args,
                    cwd=cwd,
                    env={
                        "GITHUB_TOKEN": "",
                        "PYTHONPATH": "",
                        "PYTHONWARNINGS": "error",
                    },
                )
                async with asyncio.timeout(30):
                    async with stdio_client(parameters) as (read, write):
                        async with ClientSession(read, write) as session:
                            initialized = await session.initialize()
                            self.assertEqual(initialized.serverInfo.name, "GitHub MCP")
                            tools = (await session.list_tools()).tools
                            self.assertEqual(
                                {tool.name for tool in tools},
                                {
                                    "get_repo",
                                    "list_user_repos",
                                    "list_repo_contents",
                                    "read_file",
                                    "search_code",
                                },
                            )
                            for tool in tools:
                                self.assertEqual(tool.inputSchema["type"], "object")
                            # Missing arguments fail validation without an API call.
                            result = await session.call_tool("read_file", {})
                            self.assertTrue(result.isError)
