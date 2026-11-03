"""Inspect actual release archives so local files cannot leak through packaging."""

import tarfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath


class DistributionTests(unittest.TestCase):
    def test_archives_contain_only_release_files(self):
        root = Path(__file__).resolve().parents[2]
        wheels = list((root / "dist").glob("*.whl"))
        sources = list((root / "dist").glob("*.tar.gz"))
        self.assertEqual(len(wheels), 1, "Build one wheel before running this check")
        self.assertEqual(len(sources), 1, "Build one sdist before running this check")

        with zipfile.ZipFile(wheels[0]) as archive:
            files = [PurePosixPath(name) for name in archive.namelist()]
            metadata = archive.read("github_mcp-0.1.0.dist-info/METADATA").decode()
            self.assertIn("License-Expression: MIT", metadata)
            self.assertIn("License-File: LICENSE", metadata)
            self.assertEqual(
                archive.read("github_mcp-0.1.0.dist-info/licenses/LICENSE"),
                (root / "LICENSE").read_bytes(),
            )
        self.assertTrue(any(path.name == "server.py" for path in files))
        guide = PurePosixPath("github_mcp/skills/repository-guide/SKILL.md")
        self.assertIn(guide, files)
        with zipfile.ZipFile(wheels[0]) as archive:
            self.assertEqual(
                archive.read(str(guide)), (root / "src" / str(guide)).read_bytes()
            )
        for path in files:
            self.assertTrue(
                path.parts[0] == "github_mcp" or path.parts[0].endswith(".dist-info"),
                f"Unexpected wheel path: {path}",
            )

        with tarfile.open(sources[0]) as archive:
            files = [
                PurePosixPath(*PurePosixPath(member.name).parts[1:])
                for member in archive.getmembers()
                if member.isfile()
            ]
        self.assertIn(PurePosixPath("pyproject.toml"), files)
        self.assertIn(PurePosixPath("src/github_mcp/server.py"), files)
        self.assertIn(
            PurePosixPath("src/github_mcp/skills/repository-guide/SKILL.md"), files
        )
        for path in files:
            self.assertTrue(
                path.parts[:2] == ("src", "github_mcp")
                or path.parts[0] == "tests"
                or str(path)
                in {
                    "pyproject.toml",
                    "uv.lock",
                    "README.md",
                    "CONTRIBUTING.md",
                    ".gitignore",
                    "PKG-INFO",
                    "LICENSE",
                    "docs/RELEASE.md",
                    "benchmarks/evaluate.py",
                    "benchmarks/README.md",
                    "benchmarks/fixtures/small.json",
                },
                f"Unexpected source archive path: {path}",
            )
            self.assertNotIn("__pycache__", path.parts)
