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
    async def test_installed_entrypoints_expose_twelve_tools(self):
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
                            prompts = (await session.list_prompts()).prompts
                            self.assertEqual(
                                [p.name for p in prompts], ["prepare_small_change"]
                            )
                            required = {
                                a.name for a in prompts[0].arguments if a.required
                            }
                            self.assertEqual(
                                required, {"owner", "repo", "change_request"}
                            )
                            prepared = await session.get_prompt(
                                "prepare_small_change",
                                {
                                    "owner": "a",
                                    "repo": "b",
                                    "change_request": "reuse token validation",
                                },
                            )
                            self.assertIn(
                                "query_repository_graph",
                                prepared.messages[0].content.text,
                            )
                            tools = (await session.list_tools()).tools
                            self.assertEqual(
                                {tool.name for tool in tools},
                                {
                                    "get_repo",
                                    "list_user_repos",
                                    "list_repo_contents",
                                    "read_file",
                                    "search_code",
                                    "resolve_revision",
                                    "read_file_lines",
                                    "query_repository_graph",
                                    "create_architecture_diagram",
                                    "build_repository_walkthrough",
                                    "inspect_python_dependencies",
                                    "map_python_imports",
                                },
                            )
                            for tool in tools:
                                self.assertEqual(tool.inputSchema["type"], "object")
                            import_tool = next(
                                t for t in tools if t.name == "map_python_imports"
                            )
                            self.assertIsNotNone(import_tool.outputSchema)
                            self.assertTrue(import_tool.annotations.readOnlyHint)
                            invalid_prefix = await session.call_tool(
                                "map_python_imports",
                                {"owner": "a", "repo": "b", "module_prefix": "a..b"},
                            )
                            self.assertEqual(
                                invalid_prefix.structuredContent["error"]["code"],
                                "INVALID_MODULE",
                            )
                            inventory_tool = next(
                                t
                                for t in tools
                                if t.name == "inspect_python_dependencies"
                            )
                            self.assertIsNotNone(inventory_tool.outputSchema)
                            self.assertTrue(inventory_tool.annotations.readOnlyHint)
                            invalid_manifest = await session.call_tool(
                                "inspect_python_dependencies",
                                {
                                    "owner": "a",
                                    "repo": "b",
                                    "manifest_path": "../pyproject.toml",
                                },
                            )
                            self.assertEqual(
                                invalid_manifest.structuredContent["error"]["code"],
                                "INVALID_PATH",
                            )
                            walkthrough = next(
                                t
                                for t in tools
                                if t.name == "build_repository_walkthrough"
                            )
                            self.assertIsNotNone(walkthrough.outputSchema)
                            self.assertTrue(walkthrough.annotations.readOnlyHint)
                            invalid_question = await session.call_tool(
                                "build_repository_walkthrough",
                                {"owner": "a", "repo": "b", "question": ""},
                            )
                            self.assertEqual(
                                invalid_question.structuredContent["error"]["code"],
                                "INVALID_QUESTION",
                            )
                            # Missing arguments fail validation without an API call.
                            result = await session.call_tool("read_file", {})
                            self.assertTrue(result.isError)
                            reader = next(
                                t for t in tools if t.name == "read_file_lines"
                            )
                            self.assertIsNotNone(reader.outputSchema)
                            self.assertTrue(reader.annotations.readOnlyHint)
                            result = await session.call_tool(
                                "read_file_lines",
                                {"owner": "a", "repo": "b", "path": "../secret"},
                            )
                            self.assertTrue(result.isError)
                            self.assertEqual(
                                result.structuredContent["error"]["code"],
                                "INVALID_PATH",
                            )
                            graph_tool = next(
                                t for t in tools if t.name == "query_repository_graph"
                            )
                            self.assertIsNotNone(graph_tool.outputSchema)
                            result = await session.call_tool(
                                "query_repository_graph", {"owner": "../a", "repo": "b"}
                            )
                            self.assertTrue(result.isError)
                            self.assertEqual(
                                result.structuredContent["error"]["code"],
                                "INVALID_REPOSITORY",
                            )
                            diagram_tool = next(
                                t
                                for t in tools
                                if t.name == "create_architecture_diagram"
                            )
                            self.assertIsNotNone(diagram_tool.outputSchema)
                            result = await session.call_tool(
                                "create_architecture_diagram",
                                {"owner": "a", "repo": "b", "max_nodes": 31},
                            )
                            self.assertTrue(result.isError)
                            self.assertEqual(
                                result.structuredContent["error"]["code"],
                                "INVALID_LIMIT",
                            )
