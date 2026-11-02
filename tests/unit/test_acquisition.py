"""Acquisition must treat repository paths/content as hostile data."""

import base64
import hashlib
from unittest.mock import Mock

import pytest

from github_mcp import acquisition, snapshots

COMMIT = "a" * 40
TREE = "b" * 40


def blob(raw=b"raise RuntimeError('never execute')\n"):
    sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return dict(
        sha=sha,
        size=len(raw),
        encoding="base64",
        content=base64.b64encode(raw).decode(),
    )


def entry(path="src/main.py", data=None, **changes):
    data = data or blob()
    return (
        dict(path=path, type="blob", mode="100644", size=data["size"], sha=data["sha"])
        | changes
    )


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(acquisition.tempfile, "tempdir", str(tmp_path))
    http = Mock(
        side_effect=[
            {"sha": COMMIT},
            {"sha": COMMIT, "tree": {"sha": TREE}},
            {"sha": TREE, "tree": [entry()], "truncated": False},
            blob(),
        ]
    )
    monkeypatch.setattr(snapshots, "gh", http)
    monkeypatch.setattr(acquisition, "gh", http)
    return http


def test_pinned_private_snapshot_is_removed_after_use(api, tmp_path):
    with acquisition.acquire_snapshot("a", "b", "main") as snapshot:
        root = snapshot.root
        assert root.is_relative_to(tmp_path)
        assert snapshot.commit_sha == COMMIT
        assert snapshot.files == ("src/main.py",)
        assert (root / snapshot.files[0]).read_bytes().startswith(b"raise RuntimeError")
        assert snapshot.omitted == {}
        assert api.call_args_list[1].args[0].endswith(COMMIT)
        assert api.call_args_list[2].args[0].endswith(TREE)
        assert api.call_args_list[3].args[0].endswith(blob()["sha"])
        assert all(c.kwargs["max_bytes"] > 0 for c in api.call_args_list)
    assert not root.exists()


@pytest.mark.parametrize(
    "path",
    [
        "../escape.py",
        "/evil.py",
        "C:/evil.py",
        "a\\b.py",
        "x.py:ads",
        "CON.py",
        "a/../b.py",
        "a//b.py",
        "a./b.py",
        "a\x00.py",
    ],
)
def test_unsafe_tree_paths_fail_before_downloading(api, path, tmp_path):
    api.side_effect = [
        {"sha": COMMIT},
        {"sha": COMMIT, "tree": {"sha": TREE}},
        {"sha": TREE, "tree": [entry(path)], "truncated": False},
    ]
    with pytest.raises(acquisition.SnapshotError, match="UNSAFE_PATH"):
        with acquisition.acquire_snapshot("a", "b"):
            pytest.fail("Must not expose an unsafe snapshot")
    assert api.call_count == 3
    assert list(tmp_path.iterdir()) == []


def test_omissions_do_not_download_unsafe_or_unwanted_files(api):
    entries = [
        entry("link.py", mode="120000"),
        entry("dependency", type="commit", mode="160000"),
        entry("node_modules/vendor.py"),
        entry("secrets.py"),
        entry("README.md"),
        entry("large.py", size=1_000_001),
    ]
    api.side_effect = [
        {"sha": COMMIT},
        {"sha": COMMIT, "tree": {"sha": TREE}},
        {"sha": TREE, "tree": entries, "truncated": False},
    ]
    with acquisition.acquire_snapshot("a", "b") as snapshot:
        assert snapshot.files == ()
        assert sum(snapshot.omitted.values()) == 6
    assert api.call_count == 3


def test_sensitive_directories_are_not_downloaded(api):
    setup_tree(
        api,
        [
            entry(".env/Lib/code.py"),
            entry("secrets/config.py"),
            entry("credentials/config.ts"),
        ],
    )
    with acquisition.acquire_snapshot("a", "b") as snapshot:
        assert snapshot.files == ()
        assert snapshot.omitted == {"sensitive_name": 3}
    assert api.call_count == 3


def test_cleanup_on_consumer_error(api, tmp_path):
    with pytest.raises(RuntimeError, match="consumer"):
        with acquisition.acquire_snapshot("a", "b") as snapshot:
            root = snapshot.root
            raise RuntimeError("consumer")
    assert not root.exists()


def test_revoked_permissions_do_not_reuse_private_data(api, tmp_path):
    with acquisition.acquire_snapshot("a", "b") as first:
        old_root = first.root
    api.side_effect = None
    api.return_value = {"error": "Not found", "error_code": "NOT_FOUND"}
    with pytest.raises(acquisition.SnapshotError, match="NOT_FOUND"):
        with acquisition.acquire_snapshot("a", "b", COMMIT):
            pytest.fail("No cached access")
    assert not old_root.exists()
    assert list(tmp_path.iterdir()) == []


def setup_tree(api, entries, blobs=(), **tree_changes):
    api.side_effect = [
        {"sha": COMMIT},
        {"sha": COMMIT, "tree": {"sha": TREE}},
        {"sha": TREE, "tree": entries, "truncated": False} | tree_changes,
        *blobs,
    ]


@pytest.mark.parametrize(
    "entries",
    [
        [entry("a.py"), entry("A.py")],
        [entry("A/a.py"), entry("a/b.py")],
        [entry("a.py"), entry("a.py/b.py")],
        [entry("COM¹.py")],
    ],
)
def test_portable_collisions_are_rejected(api, entries):
    setup_tree(api, entries)
    with pytest.raises(acquisition.SnapshotError, match="UNSAFE_PATH"):
        with acquisition.acquire_snapshot("a", "b"):
            pytest.fail("Unsafe paths")
    assert api.call_count == 3


@pytest.mark.parametrize(
    "change", [{"truncated": True}, {"tree": None}, {"sha": "c" * 40}]
)
def test_incomplete_or_wrong_tree_is_not_a_snapshot(api, change):
    setup_tree(api, [entry()], **change)
    with pytest.raises(acquisition.SnapshotError):
        with acquisition.acquire_snapshot("a", "b"):
            pytest.fail("Invalid tree")


@pytest.mark.parametrize(
    "change",
    [
        {"content": "!"},
        {"sha": "c" * 40},
        {"content": base64.b64encode(b"x" * blob()["size"]).decode()},
    ],
)
def test_corrupt_blob_aborts_and_cleans_partial_work(api, tmp_path, change):
    setup_tree(api, [entry("a.py"), entry("b.py")], [blob(), blob() | change])
    with pytest.raises(acquisition.SnapshotError, match="INVALID_RESPONSE"):
        with acquisition.acquire_snapshot("a", "b"):
            pytest.fail("Corrupt blob")
    assert list(tmp_path.iterdir()) == []


def test_binary_downloads_still_consume_limits(api, monkeypatch):
    monkeypatch.setattr(acquisition, "MAX_FILES", 1)
    binary = blob(b"\xff")
    setup_tree(api, [entry("a.py", binary), entry("b.py")], [binary])
    with acquisition.acquire_snapshot("a", "b") as snapshot:
        assert snapshot.files == ()
        assert snapshot.omitted == {"non_text": 1, "file_count_limit": 1}
    assert api.call_count == 4


def test_total_download_budget_and_stable_order(api, monkeypatch):
    monkeypatch.setattr(acquisition, "MAX_TOTAL_BYTES", blob()["size"])
    setup_tree(api, [entry("b.py"), entry("a.py")], [blob()])
    with acquisition.acquire_snapshot("a", "b") as snapshot:
        assert snapshot.files == ("a.py",)
        assert snapshot.omitted == {"total_size_limit": 1}
        assert snapshot.total_bytes == blob()["size"]


def test_overlapping_snapshots_have_separate_lifetimes(api):
    original = [
        {"sha": COMMIT},
        {"sha": COMMIT, "tree": {"sha": TREE}},
        {"sha": TREE, "tree": [entry()], "truncated": False},
        blob(),
    ]
    api.side_effect = original + original
    with acquisition.acquire_snapshot("a", "b") as first:
        with acquisition.acquire_snapshot("a", "b", COMMIT) as second:
            assert first.root != second.root
            second_root = second.root
        assert not second_root.exists() and first.root.exists()
    assert not first.root.exists()


def test_storage_error_is_sanitized_and_cleans_up(api, tmp_path, monkeypatch):
    original = acquisition.Path.mkdir

    def fail_source_directory(path, *args, **kwargs):
        if path.name == "src":
            raise OSError("private-storage-location")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(acquisition.Path, "mkdir", fail_source_directory)
    with pytest.raises(acquisition.SnapshotError, match="SNAPSHOT_IO") as error:
        with acquisition.acquire_snapshot("a", "b"):
            pytest.fail("Storage failed")
    assert "private-storage-location" not in error.value.error.message
    assert list(tmp_path.iterdir()) == []


def test_permission_failure_mid_download_destroys_partial_snapshot(api, tmp_path):
    setup_tree(
        api,
        [entry("a.py"), entry("b.py")],
        [blob(), {"error": "Access denied", "error_code": "FORBIDDEN"}],
    )
    with pytest.raises(acquisition.SnapshotError, match="FORBIDDEN"):
        with acquisition.acquire_snapshot("a", "b"):
            pytest.fail("Partial snapshot must not escape")
    assert list(tmp_path.iterdir()) == []


def test_tree_entry_budget_is_enforced_before_download(api, monkeypatch):
    monkeypatch.setattr(acquisition, "MAX_ENTRIES", 1)
    setup_tree(api, [entry("a.py"), entry("b.py")])
    with pytest.raises(acquisition.SnapshotError, match="SNAPSHOT_LIMIT"):
        with acquisition.acquire_snapshot("a", "b"):
            pytest.fail("Tree limit")
    assert api.call_count == 3
