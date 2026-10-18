import pytest
from pathlib import Path

import app as app_module


def post(client, url, data=None, **kwargs):
    client.get("/")
    with client.session_transaction() as session:
        token = session["csrf_token"]
    return client.post(url, data={**(data or {}), "csrf_token": token,
                                 "form_date": app_module.today_jst().isoformat()}, **kwargs)


def test_reject_invalid_and_external_break():
    client = app_module.app.test_client()
    for values in [
        {"start_time": "9:0", "end_time": "18:00"},
        {"start_time": "09:00", "end_time": "18:00", "break_start": "19:00", "break_end": "20:00"},
        {"start_time": "09:00", "end_time": "18:00", "break_start": "13:00", "break_end": "12:00"},
    ]:
        post(client, "/attendance", data=values)
    with app_module.get_db() as db:
        assert db.execute("SELECT count(*) FROM attendance").fetchone()[0] == 0


def test_overnight_attendance():
    client = app_module.app.test_client()
    response = post(client, "/attendance", data={"start_time": "22:00", "end_time": "06:00",
                    "break_start": "00:30", "break_end": "01:00"}, follow_redirects=True)
    assert "7時間 30分" in response.get_data(as_text=True)


def test_csrf_required():
    client = app_module.app.test_client()
    assert client.post("/tasks", data={"name": "invalid"}).status_code == 400


def test_note_persists_across_days_and_can_be_cleared(monkeypatch):
    from datetime import date
    client = app_module.app.test_client()
    note = "申し送り\n<script>alert(1)</script>"
    post(client, "/notes", data={"content": note})
    app_module.init_db()
    monkeypatch.setattr(app_module, "today_jst", lambda: date(2026, 10, 20))
    text = app_module.app.test_client().get("/").get_data(as_text=True)
    assert "申し送り" in text
    assert "&lt;script&gt;" in text
    assert post(client, "/notes", data={"content": "a" * 10001}).status_code == 400
    with app_module.get_db() as db:
        assert db.execute("SELECT content FROM notes").fetchone()[0] == note
    post(client, "/notes", data={"content": ""})
    with app_module.get_db() as db:
        assert db.execute("SELECT content FROM notes").fetchone()[0] == ""


def test_day_rollover_and_persistence(monkeypatch):
    from datetime import date
    client = app_module.app.test_client()
    monkeypatch.setattr(app_module, "today_jst", lambda: date(2026, 10, 18))
    post(client, "/tasks", data={"name": "継続タスク"})
    post(client, "/tasks/1/session", data={"start_time": "23:30", "end_time": "00:15"})
    app_module.init_db()
    monkeypatch.setattr(app_module, "today_jst", lambda: date(2026, 10, 19))
    text = client.get("/").get_data(as_text=True)
    assert "継続タスク" in text
    assert "今日 0時間 0分" in text
    assert "45分" in client.get("/history").get_data(as_text=True)
    with client.session_transaction() as session:
        token = session["csrf_token"]
    client.post("/attendance", data={"csrf_token": token, "form_date": "2026-10-18", "start_time": "09:00"})
    with app_module.get_db() as db:
        assert db.execute("SELECT count(*) FROM attendance").fetchone()[0] == 0


def test_delete_cascades():
    client = app_module.app.test_client()
    post(client, "/tasks", data={"name": "削除テスト"})
    post(client, "/tasks/1/session", data={"start_time": "09:00", "end_time": "10:00"})
    post(client, "/tasks/1/delete")
    with app_module.get_db() as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM task_sessions").fetchone()[0] == 0


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "test.db")
    app_module.init_db()
    app_module.app.config.update(TESTING=True, SECRET_KEY="test")


def test_minutes_between():
    assert app_module.minutes_between("09:00", "10:30") == 90
    assert app_module.minutes_between("23:30", "00:15") == 45


def test_task_persists_and_session_records():
    client = app_module.app.test_client()
    response = post(client, "/tasks", data={"name": "テスト作業"}, follow_redirects=True)
    assert response.status_code == 200
    assert "テスト作業" in response.get_data(as_text=True)

    with app_module.get_db() as db:
        task_id = db.execute("SELECT id FROM tasks WHERE name = ?", ("テスト作業",)).fetchone()[0]

    response = post(client, 
        f"/tasks/{task_id}/session",
        data={"start_time": "09:00", "end_time": "10:15"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "75分" in response.get_data(as_text=True)


def test_attendance_net_time():
    client = app_module.app.test_client()
    response = post(client, 
        "/attendance",
        data={
            "start_time": "09:00",
            "break_start": "12:00",
            "break_end": "13:00",
            "end_time": "18:00",
        },
        follow_redirects=True,
    )
    text = response.get_data(as_text=True)
    assert "8時間 0分" in text

