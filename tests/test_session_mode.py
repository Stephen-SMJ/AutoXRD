import json

from core.session import SessionStore, _sanitize_cwd


def test_session_store_persists_mode(tmp_path, monkeypatch):
    monkeypatch.setattr("core.session._SESSIONS_ROOT", tmp_path)

    store = SessionStore(
        cwd="/tmp/project",
        model="test-model",
        session_id="session-1",
        mode="coordinator",
    )
    store.append_message({"role": "user", "content": "hello"})

    meta_path = tmp_path / _sanitize_cwd("/tmp/project") / "session-1.meta.json"
    data = json.loads(meta_path.read_text())

    assert data["mode"] == "coordinator"

    sessions = SessionStore.list_sessions("/tmp/project")
    assert len(sessions) == 1
    assert sessions[0].mode == "coordinator"
