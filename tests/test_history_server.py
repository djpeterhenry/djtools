import json
import threading
import types
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

import history_server as hs


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Dreaming Of Better Days   [#deep] [#actual_house]", ("Dreaming Of Better Days", False, "")),
        ("Midnight Runner (Extended Mix)   [#tech_house]", ("Midnight Runner", False, "")),
        ("Say My Name (Original Mix)   [#actual_house] [#vocal]", ("Say My Name", True, "Say My Name (Vocal)")),
        ("Song (Club Remix)   [#vocal]", ("Song (Club Remix)", True, "Song (Vocal)")),
        ("Neon Lights (DJ Tool Mix)   [#progressive]", ("Neon Lights (DJ Tool Mix)", False, "")),
        ("Sunset (The Original)   [#afro]", ("Sunset (The Original)", False, "")),
        ("Lost Signal fixed   [#acid]", ("Lost Signal", False, "")),
        ("Warehouse Dub 2   [#disco]", ("Warehouse Dub", False, "")),
        ("No Tags", ("No Tags", False, "")),
    ],
)
def test_process_title(raw, expected):
    assert hs.process_title(raw) == expected


def test_test_history_songs():
    data = hs.get_test_history_songs()
    assert data["name"] == "Test Session"
    assert [s["track_no"] for s in data["songs"]] == [1, 2, 3, 4, 5, 6, 7]
    assert data["songs"][2]["is_vocal"]


class FakeDb:
    def __init__(self, histories, songs):
        self.histories = histories
        self.songs = songs
        self.closed = False

    def get_history(self):
        return self.histories

    def get_history_songs(self, HistoryID):
        return self.songs.get(HistoryID, [])

    def close(self):
        self.closed = True


def song(track_no, title, artist="Artist", year=2020):
    content = types.SimpleNamespace(
        Title=title, Artist=types.SimpleNamespace(Name=artist) if artist else None, ReleaseYear=year
    )
    return types.SimpleNamespace(TrackNo=track_no, Content=content, created_at="2024-06-15 22:00:00")


def test_get_latest_history_songs(monkeypatch):
    db = FakeDb(
        [types.SimpleNamespace(ID=1, Name="HISTORY 2024-06-14"), types.SimpleNamespace(ID=2, Name="HISTORY 2024-06-15")],
        {2: [song(1, "One   [#disco]"), song(2, "Two   [#vocal]", artist=None)]},
    )
    monkeypatch.setattr(hs, "Rekordbox6Database", lambda: db)
    data = hs.get_latest_history_songs()
    assert db.closed
    assert data["name"] == "HISTORY 2024-06-15"
    assert data["songs"][0] == {
        "track_no": 1,
        "title": "One",
        "artist": "Artist",
        "played_at": "2024-06-15 22:00:00",
        "year": 2020,
        "is_vocal": False,
        "vocal_title": "",
    }
    assert data["songs"][1]["artist"] == ""
    assert data["songs"][1]["vocal_title"] == "Two (Vocal)"


@pytest.mark.xfail(strict=True, reason="bug: no history returns [] and the handler calls .get on it")
def test_get_latest_history_songs_empty(monkeypatch):
    monkeypatch.setattr(hs, "Rekordbox6Database", lambda: FakeDb([], {}))
    assert hs.get_latest_history_songs() == {"name": "", "songs": []}


# ------------------------------------------------------------ http routes


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(hs, "_message_state", {"text": "", "set_at": None, "duration": hs.MSG_DISPLAY_SECONDS})
    monkeypatch.setattr(hs, "_suppressed_tail", 0)
    monkeypatch.setattr(hs, "_last_history_count", 0)
    history = {"name": "S", "songs": [{"title": str(i)} for i in range(3)]}
    monkeypatch.setattr(hs, "get_latest_history_songs", lambda: json.loads(json.dumps(history)))

    httpd = HTTPServer(("127.0.0.1", 0), hs.Handler)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    base = "http://127.0.0.1:{}".format(httpd.server_address[1])
    yield types.SimpleNamespace(base=base, history=history)
    httpd.shutdown()
    httpd.server_close()


def request(server, path, body=None):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    method = "GET" if body is None else "POST"
    with urllib.request.urlopen(urllib.request.Request(server.base + path, data=data, method=method)) as resp:
        return resp.status, resp.headers, resp.read()


def get_json(server, path, body=None):
    return json.loads(request(server, path, body)[2])


def test_html_pages(server):
    for path in ["/", "/now", "/now-debug", "/now-debug-test", "/suppress-input", "/message-input"]:
        status, headers, body = request(server, path)
        assert status == 200
        assert headers["Content-Type"] == "text/html"
        assert headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
        assert body.startswith(b"<!DOCTYPE html>")
    assert b"background: transparent" in request(server, "/now")[2]
    assert b'fetch("/api/history-test")' in request(server, "/now-debug-test")[2]


def test_history_test_api(server):
    assert get_json(server, "/api/history-test")["name"] == "Test Session"


def test_suppress_tail(server):
    assert len(get_json(server, "/api/history")["songs"]) == 3
    assert get_json(server, "/api/suppress", b"") == {"count": 1}
    assert get_json(server, "/api/suppress", b"") == {"count": 2}
    assert [s["title"] for s in get_json(server, "/api/history")["songs"]] == ["0"]
    assert get_json(server, "/api/unsuppress", b"") == {"count": 1}
    assert get_json(server, "/api/suppress") == {"count": 1}
    # a new track arriving clears the suppression
    server.history["songs"].append({"title": "3"})
    assert len(get_json(server, "/api/history")["songs"]) == 4
    assert get_json(server, "/api/suppress") == {"count": 0}
    assert get_json(server, "/api/unsuppress", b"") == {"count": 0}


def test_message(server):
    assert get_json(server, "/api/message")["text"] == ""
    assert get_json(server, "/api/message", {"text": " Hello \\ world ", "duration": 5}) == {"ok": True}
    state = get_json(server, "/api/message")
    assert state["text"] == "Hello\nworld"
    assert state["duration"] == 5
    assert state["set_at"]
    get_json(server, "/api/message", {"text": ""})
    state = get_json(server, "/api/message")
    assert state["set_at"] is None
    assert state["duration"] == hs.MSG_DISPLAY_SECONDS


@pytest.mark.parametrize("body", [b"not json", b'{"text": "x", "duration": -1}', b'{"text": 5}', b"[]"])
def test_message_rejects_bad_input(server, body):
    with pytest.raises(urllib.error.HTTPError) as e:
        request(server, "/api/message", body)
    assert e.value.code == 400


def test_unknown_paths(server):
    for path, body in [("/nope", None), ("/nope", b"")]:
        with pytest.raises(urllib.error.HTTPError) as e:
            request(server, path, body)
        assert e.value.code == 404
