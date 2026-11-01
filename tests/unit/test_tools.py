"""Check that packaging preserves useful tool behavior without live GitHub calls."""

import base64
import unittest
from unittest.mock import patch

from github_mcp import server


class ToolTests(unittest.TestCase):
    def test_object_tools_reject_list_responses(self):
        cases = (
            (server.get_repo, ("owner", "repo")),
            (server.read_file, ("owner", "repo", "README.md")),
            (server.search_code, ("example",)),
        )
        with patch.object(server, "gh", return_value=[]):
            for function, args in cases:
                with self.subTest(tool=function.__name__):
                    self.assertEqual(function(*args), "Unexpected response from GitHub")

    def test_user_repositories_reject_object_response(self):
        with patch.object(server, "gh", return_value={"unexpected": True}):
            self.assertEqual(
                server.list_user_repos("owner"), "Unexpected response from GitHub"
            )

    def test_all_tools_return_existing_api_errors(self):
        cases = (
            (server.get_repo, ("owner", "repo")),
            (server.list_user_repos, ("owner",)),
            (server.list_repo_contents, ("owner", "repo")),
            (server.read_file, ("owner", "repo", "README.md")),
            (server.search_code, ("example",)),
        )
        with patch.object(server, "gh", return_value={"error": "Not found"}):
            for function, args in cases:
                with self.subTest(tool=function.__name__):
                    self.assertEqual(function(*args), "Not found")

    def test_read_file_decodes_unicode_and_reports_truncation(self):
        content = "Study buddy: \u2605\n" * 300
        data = {
            "type": "file",
            "content": base64.b64encode(content.encode()).decode(),
            "size": len(content.encode()),
        }
        with patch.object(server, "gh", return_value=data):
            result = server.read_file("owner", "repo", "README.md")
        self.assertEqual(
            result,
            f"File: README.md\n\n{content[:3000]}"
            f"\n\n... (truncated, full file is {data['size']} bytes)",
        )
