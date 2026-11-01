"""Exercise HTTP failure paths without credentials, sleeps or network calls."""

import json
import time
from email.utils import formatdate
from unittest.mock import Mock

import pytest
import requests

from github_mcp import server


def response(status=200, data=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps({} if data is None else data).encode()
    result._content_consumed = True
    result.headers.update(headers or {})
    return result


@pytest.fixture
def http(monkeypatch):
    get = Mock(return_value=response(data={"ok": True}))
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setenv("GITHUB_TOKEN", "test-credential")
    monkeypatch.setattr(time, "sleep", Mock())
    return get


def test_timeout_and_redirect_policy(http):
    assert server.gh("/repos/a/b") == {"ok": True}
    assert http.call_args.args[0] == "https://api.github.com/repos/a/b"
    assert http.call_args.kwargs["headers"]["Authorization"] == "Bearer test-credential"
    assert http.call_args.kwargs["timeout"] == (3.05, 10)
    assert http.call_args.kwargs["allow_redirects"] is False


def test_transient_failures_retry_with_a_bound(http):
    http.side_effect = [requests.Timeout("test-credential")] * 3
    result = server.gh("/repos/a/b")
    assert result["error_code"] == "TIMEOUT"
    assert "test-credential" not in str(result)
    assert http.call_count == 3
    assert time.sleep.call_count == 2


def test_server_failure_recovers(http):
    http.side_effect = [response(503), response(data=[])]
    assert server.gh("/users/a/repos") == []
    assert http.call_count == 2


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "AUTHENTICATION"),
        (403, "FORBIDDEN"),
        (404, "NOT_FOUND"),
        (422, "VALIDATION"),
        (302, "REDIRECT"),
    ],
)
def test_permanent_errors_do_not_retry_or_echo_bodies(http, status, code):
    http.return_value = response(status, {"message": "test-credential"})
    result = server.gh("/repos/a/b")
    assert result["error_code"] == code
    assert "test-credential" not in str(result)
    assert http.call_count == 1


@pytest.mark.parametrize("status", [403, 429])
def test_long_rate_limits_return_without_sleeping(http, status):
    http.return_value = response(status, headers={"Retry-After": "120"})
    result = server.gh("/repos/a/b")
    assert result["error_code"] == "RATE_LIMITED"
    assert result["retry_after_seconds"] == 120
    assert http.call_count == 1
    time.sleep.assert_not_called()


def test_short_rate_limit_respects_delay(http):
    http.side_effect = [response(429, headers={"Retry-After": "2"}), response(data=[])]
    assert server.gh("/users/a/repos") == []
    time.sleep.assert_called_once_with(2)


@pytest.mark.parametrize("value", ["invalid", "nan", "inf"])
def test_bad_rate_headers_use_safe_minimum(http, value):
    http.return_value = response(429, headers={"Retry-After": value})
    result = server.gh("/repos/a/b")
    assert result["retry_after_seconds"] == 60
    time.sleep.assert_not_called()


def test_secondary_limit_without_headers_does_not_retry_early(http):
    http.return_value = response(
        403, {"message": "You exceeded a secondary rate limit"}
    )
    assert server.gh("/repos/a/b")["retry_after_seconds"] == 60
    assert http.call_count == 1


@pytest.mark.parametrize("payload", [b"<html>bad gateway</html>", b"null", b'"text"'])
def test_invalid_json_shapes_are_reported(http, payload):
    http.return_value._content = payload
    assert server.gh("/repos/a/b")["error_code"] == "MALFORMED_RESPONSE"


def test_anonymous_requests_omit_authorization(http, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN")
    server.gh("/repos/a/b")
    assert "Authorization" not in http.call_args.kwargs["headers"]


@pytest.mark.parametrize(
    "owner,repo,query",
    [
        ("", "", "FastMCP"),
        ("owner", "", "FastMCP user:owner"),
        ("owner", "repo", "FastMCP repo:owner/repo"),
    ],
)
def test_page_controls_and_search_spacing(monkeypatch, owner, repo, query):
    get = Mock(return_value={"items": [], "total_count": 0})
    monkeypatch.setattr(server, "gh", get)
    server.search_code("FastMCP", owner, repo, page=2, per_page=5)
    assert get.call_args.kwargs["params"] == {
        "q": query,
        "page": 2,
        "per_page": 5,
    }


@pytest.mark.parametrize("page,per_page", [(0, 10), (1, 101), (True, 10)])
def test_bad_pagination_does_not_call_github(monkeypatch, page, per_page):
    get = Mock()
    monkeypatch.setattr(server, "gh", get)
    assert "page" in server.list_user_repos("owner", page=page, per_page=per_page)
    get.assert_not_called()


def test_reset_and_retry_headers_use_the_later_deadline(http):
    http.return_value = response(
        403,
        headers={
            "Retry-After": "1",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(time.time() + 120),
        },
    )
    result = server.gh("/repos/a/b")
    assert 119 <= result["retry_after_seconds"] <= 120
    assert http.call_count == 1


def test_http_date_retry_after_is_respected(http):
    http.return_value = response(
        429,
        headers={
            "Retry-After": formatdate(time.time() + 600, usegmt=True),
        },
    )
    assert 590 <= server.gh("/repos/a/b")["retry_after_seconds"] <= 600
    assert http.call_count == 1
    time.sleep.assert_not_called()


def test_service_retry_after_is_not_ignored(http):
    http.return_value = response(503, headers={"Retry-After": "120"})
    result = server.gh("/repos/a/b")
    assert result["retry_after_seconds"] == 120
    assert http.call_count == 1


@pytest.mark.parametrize(
    "exception,code,count",
    [
        (requests.ConnectionError("test-credential"), "NETWORK_ERROR", 3),
        (requests.exceptions.SSLError("test-credential"), "TLS_ERROR", 1),
        (requests.RequestException("test-credential"), "NETWORK_ERROR", 1),
    ],
)
def test_transport_errors_are_sanitized(http, exception, code, count):
    http.side_effect = exception
    result = server.gh("/repos/a/b")
    assert result["error_code"] == code
    assert "test-credential" not in str(result)
    assert http.call_count == count


def test_repository_page_can_be_continued(monkeypatch):
    get = Mock(
        return_value=[{"full_name": "a/b", "stargazers_count": 0, "forks_count": 0}]
    )
    monkeypatch.setattr(server, "gh", get)
    output = server.list_user_repos("a", page=2, per_page=1)
    assert get.call_args.kwargs["params"]["page"] == 2
    assert "page=3" in output


def test_search_cap_and_incomplete_results(monkeypatch):
    get = Mock(
        return_value={"items": [], "total_count": 20, "incomplete_results": True}
    )
    monkeypatch.setattr(server, "gh", get)
    assert "incomplete" in server.search_code("x")
    assert "1,000" in server.search_code("x", page=101)
    assert get.call_count == 1


@pytest.mark.parametrize(
    "tool,args,data",
    [
        (server.get_repo, ("a", "b"), {}),
        (server.list_user_repos, ("a",), [{}]),
        (server.list_repo_contents, ("a", "b"), [{}]),
        (server.search_code, ("x",), {"items": [None]}),
    ],
)
def test_malformed_records_do_not_crash(monkeypatch, tool, args, data):
    monkeypatch.setattr(server, "gh", Mock(return_value=data))
    assert tool(*args) == "Unexpected response from GitHub"


@pytest.mark.parametrize(
    "data",
    [
        {"type": "file"},
        {"type": "file", "content": "!", "size": 1},
        {"type": "file", "content": "", "size": 2000000, "encoding": "none"},
    ],
)
def test_unavailable_file_content_is_reported(monkeypatch, data):
    monkeypatch.setattr(server, "gh", Mock(return_value=data))
    assert server.read_file("a", "b", "file") == "File content unavailable or invalid"
