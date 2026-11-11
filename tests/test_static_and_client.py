from __future__ import annotations

import importlib.util
import io
import json
import socket
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from conftest import API, MONTH, WEEK, assert_error, login

CLI_TOKEN = "private-cli-token-for-regression-tests"
FILE_MARKER = "versions-file-content-must-stay-private"


@pytest.mark.parametrize("missing_root", [True, False], ids=["missing", "empty"])
def test_static_root_can_arrive_after_startup(project, agent_headers, missing_root):
    frontend = project.root / "frontend"
    for name in ("index.html", "fixture.css"):
        (frontend / name).unlink()
    if missing_root:
        frontend.rmdir()

    with project.client() as client:
        for path in ("/techo/", "/techo/fixture.css"):
            assert client.get(path).status_code == 404
            head = client.head(path)
            assert head.status_code == 404
            assert head.content == b""
        assert client.post("/techo/").status_code == 405
        health = client.get(f"{API}/healthz")
        assert health.status_code == 200
        assert health.json() == {"ok": True}
        assert_error(client.get(f"{API}/me"), 401)
        identity = client.get(f"{API}/me", headers=agent_headers)
        assert identity.status_code == 200
        assert identity.json() == {"author": "agent"}
        assert client.get(f"{API}/month", params={"ym": MONTH}, headers=agent_headers).status_code == 200
        login(client)
        assert client.get(f"{API}/me").json() == {"author": "human"}
        assert_error(client.get(f"{API}/me", headers={"X-Techo-Token": "invalid-token"}), 401)
        assert frontend.is_dir() == (not missing_root)

        # These writes model a separate frontend deployment, only inside the fixture.
        if missing_root:
            assert not frontend.exists()
            frontend.mkdir()
        (frontend / "index.html").write_text("<p>late frontend</p>", encoding="utf-8")
        (frontend / "fixture.css").write_text("body { color: red; }", encoding="utf-8")
        page = client.get("/techo/")
        assert page.status_code == 200
        assert page.text == "<p>late frontend</p>"
        asset = client.get("/techo/fixture.css")
        assert asset.status_code == 200
        assert asset.text == "body { color: red; }"


def test_static_keeps_head_conditional_requests_and_method_handling(client):
    response = client.get("/techo/fixture.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    head = client.head("/techo/fixture.css")
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == response.headers["content-length"]
    assert head.headers["etag"] == response.headers["etag"]
    cached = client.get("/techo/fixture.css", headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304
    assert cached.content == b""
    assert client.post("/techo/fixture.css").status_code == 405


def test_static_blocks_encoded_traversal_and_sibling_prefixes(project, client):
    marker = "outside-static-root-private-content"
    (project.root / "private.txt").write_text(marker, encoding="utf-8")
    sibling = project.root / "frontend-private"
    sibling.mkdir()
    (sibling / "private.txt").write_text(marker, encoding="utf-8")
    for path in (
        "/techo/%2e%2e/private.txt",
        "/techo/%2e%2e%2fprivate.txt",
        "/techo/%2e%2e%5cprivate.txt",
        "/techo/%2e%2e/frontend-private/private.txt",
        "/techo/%2e%2e%2ffrontend-private%2fprivate.txt",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert marker not in response.text


def test_static_does_not_follow_symlinks_outside_root(project, client):
    outside = project.root / "private.txt"
    outside.write_text("private symlink target", encoding="utf-8")
    try:
        (project.root / "frontend" / "linked.txt").symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable")
    assert client.get("/techo/linked.txt").status_code == 404


def test_static_still_rejects_a_root_that_is_a_file(project):
    frontend = project.root / "frontend"
    for name in ("index.html", "fixture.css"):
        (frontend / name).unlink()
    frontend.rmdir()
    frontend.write_text("not a directory", encoding="utf-8")
    with project.client() as client:
        with pytest.raises(RuntimeError, match="not a directory"):
            client.get("/techo/")


@pytest.fixture
def cli(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "tools" / "techo_client.py"
    spec = importlib.util.spec_from_file_location("techo_client_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("TECHO_AGENT_TOKEN", raising=False)
    monkeypatch.delenv("TECHO_BASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        f"TECHO_AGENT_TOKEN={CLI_TOKEN}\nTECHO_BASE_URL=https://example.com/techo\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        module, "build_opener", Mock(side_effect=AssertionError("unexpected network request"))
    )
    return module


@pytest.fixture
def sender(cli, monkeypatch):
    send = Mock(return_value={"ok": True})
    monkeypatch.setattr(cli, "request", send)
    return send


@pytest.mark.parametrize(
    "base_url",
    [
        "https://example.com/techo",
        "https://example.com:8443/techo/",
        "http://127.0.0.1:8875/techo",
        "http://localhost/techo",
        "http://LOCALHOST:8875/techo/",
        "http://[::1]/techo",
        "http://[::1]:8875/techo",
    ],
)
def test_cli_accepts_https_and_exact_local_http(cli, sender, monkeypatch, capsys, base_url):
    monkeypatch.setenv("TECHO_BASE_URL", base_url)
    assert cli.load_config(cli.PROJECT_ROOT / ".env") == (base_url.rstrip("/"), CLI_TOKEN)
    assert cli.main(["month", MONTH]) == 0
    sender.assert_called_once_with(base_url.rstrip("/"), CLI_TOKEN, "GET", "/month", {"ym": MONTH}, None)
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"ok": True}
    assert captured.err == ""


@pytest.mark.parametrize("config_source", ["environment", "file"])
@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.com/techo",
        "http://loopback.example/techo",
        "http://localhost.evil/techo",
        "http://127.0.0.1.evil/techo",
        "http://0.0.0.0/techo",
        "http://127.1/techo",
        "http://127.0.0.2/techo",
        "http://2130706433/techo",
        "http://localhost./techo",
        "http://[::ffff:127.0.0.1]/techo",
        "http://[::1].evil/techo",
        "http://[::1]localhost/techo",
        "http://[::1%25lo]/techo",
        f"http://{CLI_TOKEN}@localhost/techo",
        f"https://user:{CLI_TOKEN}@example.com/techo",
        "http://localhost:0/techo",
        "http://localhost:invalid/techo",
        "https://example.com/techo?token=private",
        "https://example.com/techo#private",
    ],
)
def test_cli_rejects_unsafe_config_before_any_request(
    cli, sender, monkeypatch, capsys, base_url, config_source
):
    if config_source == "environment":
        monkeypatch.setenv("TECHO_BASE_URL", base_url)
    else:
        (cli.PROJECT_ROOT / ".env").write_text(
            f"TECHO_AGENT_TOKEN={CLI_TOKEN}\nTECHO_BASE_URL={base_url}\n", encoding="utf-8"
        )
    resolver = Mock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))])
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    with pytest.raises(cli.ClientError) as failure:
        cli.load_config(cli.PROJECT_ROOT / ".env")
    assert failure.value.payload["error"]["code"] == "configuration_error"
    assert cli.main(["month", MONTH]) == 1
    sender.assert_not_called()
    resolver.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "configuration_error"
    assert CLI_TOKEN not in captured.err
    assert base_url not in captured.err


def test_cli_reorder_requires_a_versions_file(cli, sender, capsys):
    assert cli.main(["reorder", "--period", WEEK, "--ids", "1"]) == 1
    sender.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "usage_error"
    assert CLI_TOKEN not in captured.err


@pytest.mark.parametrize(
    ("ids", "versions"),
    [
        ([3, 1], {"3": "2026-11-09T09:00:00.123456+08:00", "1": "2026-11-09T08:00:00+08:00"}),
        ([], {}),
    ],
)
def test_cli_reorder_submits_supplied_versions_without_fetching(cli, sender, tmp_path, capsys, ids, versions):
    path = tmp_path / "versions.json"
    path.write_text(json.dumps(versions, indent=2), encoding="utf-8-sig")
    args = ["reorder", "--period", WEEK, "--ids", *map(str, ids), "--versions-file", str(path)]
    assert cli.main(args) == 0
    sender.assert_called_once_with(
        "https://example.com/techo",
        CLI_TOKEN,
        "POST",
        "/goals/reorder",
        None,
        {"period": WEEK, "ids": ids, "versions": versions},
    )
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"ok": True}
    assert captured.err == ""


@pytest.mark.parametrize(
    "contents",
    [
        None,
        b"\xff" + FILE_MARKER.encode(),
        f"not JSON {FILE_MARKER} {CLI_TOKEN}".encode(),
        json.dumps([FILE_MARKER, CLI_TOKEN]).encode(),
        json.dumps(f"{FILE_MARKER} {CLI_TOKEN}").encode(),
        b"null",
        b"1",
        b"true",
        b'{"1": NaN}',
    ],
    ids=["missing", "invalid-utf8", "invalid-json", "array", "string", "null", "number", "bool", "nan"],
)
def test_cli_reorder_file_errors_are_safe_and_send_nothing(cli, sender, tmp_path, capsys, contents):
    path = tmp_path / "versions.json"
    if contents is not None:
        path.write_bytes(contents)
    assert cli.main(["reorder", "--period", WEEK, "--ids", "1", "--versions-file", str(path)]) == 1
    sender.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["code"] == "validation_error"
    assert error["field"] == "versions_file"
    assert CLI_TOKEN not in captured.err
    assert FILE_MARKER not in captured.err
    assert str(path) not in captured.err


def test_cli_reorder_handles_an_unreadable_file(cli, sender, tmp_path, monkeypatch, capsys):
    def denied(*args, **kwargs):
        raise PermissionError(FILE_MARKER)

    # Keep config loading real and make just the versions file read fail.
    monkeypatch.setattr(Path, "read_text", denied)
    path = tmp_path / "versions.json"
    assert cli.main(["reorder", "--period", WEEK, "--ids", "--versions-file", str(path)]) == 1
    sender.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "validation_error"
    assert FILE_MARKER not in captured.err
    assert CLI_TOKEN not in captured.err


def test_cli_batch_passes_source_keys_through(cli, sender, tmp_path, capsys):
    body = {
        "items": [{"type": "note", "date": "2026-11-09", "text": "note", "source_key": " chat:123:note "}]
    }
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    assert cli.main(["batch", str(path)]) == 0
    sender.assert_called_once_with("https://example.com/techo", CLI_TOKEN, "POST", "/batch", None, body)
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"ok": True}
    assert captured.err == ""


@pytest.mark.parametrize("error_response", [False, True], ids=["success", "error"])
def test_cli_redacts_tokens_in_server_responses(cli, monkeypatch, capsys, error_response):
    payload = {"message": CLI_TOKEN, "nested": [{CLI_TOKEN: f"https://user:{CLI_TOKEN}@example.com/path"}]}
    if error_response:
        payload = {"error": {"code": "conflict", **payload}}
    response = io.BytesIO(json.dumps(payload).encode())
    opener = Mock()
    if error_response:
        opener.open.side_effect = HTTPError("https://example.com/techo", 409, "Conflict", {}, response)
    else:
        opener.open.return_value = response
    monkeypatch.setattr(cli, "build_opener", Mock(return_value=opener))
    assert cli.main(["month", MONTH]) == int(error_response)
    opener.open.assert_called_once()
    captured = capsys.readouterr()
    output = captured.err if error_response else captured.out
    assert CLI_TOKEN not in output
    assert "https://[redacted]@example.com/path" in output
    assert json.loads(output)
    assert (captured.out if error_response else captured.err) == ""


def test_cli_keeps_redirects_disabled(cli, monkeypatch, capsys):
    target = "https://redirect.example/techo"
    headers = {"Location": target}
    opener = Mock()
    opener.open.side_effect = HTTPError("https://example.com/techo", 302, "Found", headers, io.BytesIO())
    build = Mock(return_value=opener)
    monkeypatch.setattr(cli, "build_opener", build)
    assert cli.main(["month", MONTH]) == 1
    opener.open.assert_called_once()
    build.assert_called_once()
    handler = build.call_args.args[0]
    assert isinstance(handler, cli.NoRedirect)
    request = opener.open.call_args.args[0]
    assert request.get_header("X-techo-token") == CLI_TOKEN
    assert handler.redirect_request(request, None, 302, "Found", headers, target) is None
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["code"] == "http_error"
    assert error["status"] == 302
    assert CLI_TOKEN not in captured.err


@pytest.mark.parametrize(
    ("argv", "path", "query"),
    [
        (["decorations", "day:2026-11-08"], "/decorations", {"page": "day:2026-11-08"}),
        (["strokes", "month:2026-11"], "/strokes", {"page": "month:2026-11"}),
    ],
)
def test_cli_page_commands_are_read_only(cli, sender, capsys, argv, path, query):
    assert cli.main(argv) == 0
    sender.assert_called_once_with("https://example.com/techo", CLI_TOKEN, "GET", path, query, None)
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_cli_photo_add_builds_a_multipart_upload_the_server_accepts(
    cli, sender, tmp_path, capsys, client, agent_headers
):
    from test_photos import image_bytes

    image = tmp_path / "寿司 date.jpg"
    image.write_bytes(image_bytes(size=(320, 240)))
    assert cli.main(["photo-add", "--date", "2026-11-08", "--file", str(image), "--caption", "寿司"]) == 0
    sender.assert_called_once()
    base_url, token, method, path, query, body = sender.call_args.args
    assert (base_url, token, method, path, query) == (
        "https://example.com/techo",
        CLI_TOKEN,
        "POST",
        "/photos",
        None,
    )
    assert isinstance(body, cli.Multipart)
    assert body.content_type.startswith("multipart/form-data; boundary=")
    assert capsys.readouterr().err == ""
    # Feed the exact bytes the CLI would send into the real application.
    response = client.post(
        f"{API}/photos", content=body.data, headers={**agent_headers, "Content-Type": body.content_type}
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert (item["date"], item["caption"], item["width"], item["author"]) == (
        "2026-11-08",
        "寿司",
        320,
        "agent",
    )


def test_cli_photo_add_request_sends_multipart_headers(cli, monkeypatch, tmp_path, capsys):
    image = tmp_path / "a.png"
    image.write_bytes(b"\x89PNG fake")
    opener = Mock()
    opener.open.return_value = io.BytesIO(b'{"id": 1}')
    monkeypatch.setattr(cli, "build_opener", Mock(return_value=opener))
    assert cli.main(["photo-add", "--date", "2026-11-08", "--file", str(image)]) == 0
    request = opener.open.call_args.args[0]
    assert request.full_url == "https://example.com/techo/api/v1/photos"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type").startswith("multipart/form-data; boundary=")
    assert b'name="date"\r\n\r\n2026-11-08\r\n' in request.data
    assert b'name="caption"' not in request.data
    assert json.loads(capsys.readouterr().out) == {"id": 1}


def test_cli_photo_add_rejects_oversized_or_unreadable_files_without_sending(cli, sender, tmp_path, capsys):
    large = tmp_path / "large.jpg"
    large.write_bytes(b"\0" * (2 * 1024 * 1024))
    assert cli.main(["photo-add", "--date", "2026-11-08", "--file", str(large)]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "payload_too_large"
    assert cli.main(["photo-add", "--date", "2026-11-08", "--file", str(tmp_path / "missing.jpg")]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["code"] == "validation_error" and error["field"] == "file"
    sender.assert_not_called()
