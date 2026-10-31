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
    text = app_module.app.test_client().get("/notes").get_data(as_text=True)
    assert "申し送り" in text
    assert "&lt;script&gt;" in text
    assert post(client, "/notes", data={"content": "a" * 10001}).status_code == 400
    with app_module.get_db() as db:
        assert db.execute("SELECT content FROM notes").fetchone()[0] == note
    post(client, "/notes", data={"content": ""})
    with app_module.get_db() as db:
        assert db.execute("SELECT content FROM notes").fetchone()[0] == ""


def test_daily_note_is_separate_from_persistent_note(monkeypatch):
    from datetime import date
    client = app_module.app.test_client()
    monkeypatch.setattr(app_module, "today_jst", lambda: date(2026, 10, 28))
    post(client, "/notes", data={"content": "継続するメモ"})
    post(client, "/notes/daily", data={"work_date": "2026-10-28", "content": "今日だけのメモ"})
    assert "今日だけのメモ" in client.get("/notes?date=2026-10-28").get_data(as_text=True)
    other_day = client.get("/notes?date=2026-10-29").get_data(as_text=True)
    assert "継続するメモ" in other_day
    assert "今日だけのメモ" not in other_day
    assert post(client, "/notes/daily", data={"work_date": "2026-10-29", "content": "a" * 10001}).status_code == 400
    with app_module.get_db() as db:
        assert db.execute("SELECT count(*) FROM daily_notes").fetchone()[0] == 1


def test_rename_task_and_edit_today_log_recalculates_group_totals(monkeypatch):
    from datetime import date
    client = app_module.app.test_client()
    monkeypatch.setattr(app_module, "today_jst", lambda: date(2026, 10, 28))
    post(client, "/tasks", data={"name": "定常業務"})
    post(client, "/tasks", data={"name": "別の作業"})
    post(client, "/tasks/1/session", data={"content": "メール確認", "start_time": "11:00", "end_time": "11:20"})
    post(client, "/tasks/1/session", data={"content": "日報作成", "start_time": "15:00", "end_time": "15:10"})
    page = client.get("/").get_data(as_text=True)
    assert "定常業務 の合計" in page and "0時間 30分（30分）" in page
    assert post(client, "/tasks/1/rename", data={"name": "定常作業"}).status_code == 302
    assert post(client, "/sessions/1/edit", data={"task_id": "2", "content": "連絡対応",
                "start_time": "11:00", "end_time": "11:15"}).status_code == 302
    page = client.get("/").get_data(as_text=True)
    assert "定常作業 の合計" in page and "0時間 10分（10分）" in page
    assert "別の作業 の合計" in page and "0時間 15分（15分）" in page
    with app_module.get_db() as db:
        assert db.execute("SELECT task_id, content, duration_minutes FROM task_sessions WHERE id = 1").fetchone()[:] == (2, "連絡対応", 15)
    assert post(client, "/sessions/1/edit", data={"task_id": "2", "start_time": "11:00", "end_time": "11:00"}).status_code == 400
    monkeypatch.setattr(app_module, "today_jst", lambda: date(2026, 10, 29))
    assert post(client, "/sessions/1/edit", data={"task_id": "2", "start_time": "11:00", "end_time": "11:20"}).status_code == 404


def test_edit_past_session_from_history_updates_period_totals(monkeypatch):
    from datetime import date
    client = app_module.app.test_client()
    post(client, "/tasks", data={"name": "定常業務"})
    post(client, "/tasks", data={"name": "報告書"})
    monkeypatch.setattr(app_module, "today_jst", lambda: date(2026, 10, 19))
    post(client, "/tasks/1/session", data={"content": "メール", "start_time": "11:00", "end_time": "11:20"})
    monkeypatch.setattr(app_module, "today_jst", lambda: date(2026, 10, 31))
    history = client.get("/history?date=2026-10-19").get_data(as_text=True)
    assert '/sessions/1/edit' in history and 'value="2026-10-19"' in history
    response = post(client, "/sessions/1/edit", data={"work_date": "2026-10-19", "return_to": "history",
                    "task_id": "2", "content": "月次報告", "start_time": "10:00", "end_time": "11:30"})
    assert response.status_code == 302 and '/history?date=2026-10-19' in response.headers['Location']
    with app_module.get_db() as db:
        row = db.execute("SELECT task_id, work_date, content, duration_minutes FROM task_sessions WHERE id = 1").fetchone()
        week = app_module.weekly_summary(db, date(2026, 10, 19))
        month = app_module.monthly_overtime(db, date(2026, 10, 19))
    assert row[:] == (2, "2026-10-19", "月次報告", 90)
    assert [(item['name'], item['minutes']) for item in week['task_totals']] == [('報告書', 90)]
    assert [(item['name'], item['minutes']) for item in month['task_totals']] == [('報告書', 90)]
    assert post(client, "/sessions/1/edit", data={"work_date": "2026-10-20", "task_id": "2",
                "start_time": "10:00", "end_time": "11:30"}).status_code == 404
    page = client.get('/reports?date=2026-10-19').get_data(as_text=True)
    assert '2026-10 のタスク別時間' in page and '1時間 30分（90分）' in page
    assert '勤怠の開始〜終了から休憩を引いた実働' in page


def test_add_and_delete_past_work_log_from_history(monkeypatch):
    from datetime import date
    client = app_module.app.test_client()
    monkeypatch.setattr(app_module, 'today_jst', lambda: date(2026, 10, 31))
    post(client, '/tasks', data={'name': '定常業務'})
    page = client.get('/history?date=2026-10-19').get_data(as_text=True)
    assert '過去日の作業記録を追加' in page and 'value="2026-10-19"' in page
    response = post(client, '/history/sessions', data={
        'work_date': '2026-10-19', 'task_id': '1', 'content': 'メール確認',
        'start_time': '11:00', 'end_time': '11:20',
    })
    assert response.status_code == 302 and '/history?date=2026-10-19' in response.headers['Location']
    with app_module.get_db() as db:
        row = db.execute('SELECT id, work_date, duration_minutes, content FROM task_sessions').fetchone()
        week = app_module.weekly_summary(db, date(2026, 10, 19))
    assert row['work_date'] == '2026-10-19' and row['duration_minutes'] == 20
    assert week['task_minutes'] == 20 and week['task_totals'][0]['name'] == '定常業務'
    assert 'メール確認' in client.get('/reports?date=2026-10-19').get_data(as_text=True)
    response = post(client, f'/sessions/{row["id"]}/delete', data={'return_to': 'history'})
    assert '/history?date=2026-10-19' in response.headers['Location']
    with app_module.get_db() as db:
        assert db.execute('SELECT count(*) FROM task_sessions').fetchone()[0] == 0


def test_add_past_log_rejects_invalid_or_archived_task(monkeypatch):
    from datetime import date
    client = app_module.app.test_client()
    monkeypatch.setattr(app_module, 'today_jst', lambda: date(2026, 10, 31))
    post(client, '/tasks', data={'name': '旧タスク'})
    post(client, '/tasks/1/delete')
    base = {'work_date': '2026-10-19', 'task_id': '1', 'start_time': '09:00', 'end_time': '10:00'}
    assert post(client, '/history/sessions', data=base).status_code == 400
    post(client, '/tasks', data={'name': '現行タスク'})
    assert post(client, '/history/sessions', data={**base, 'task_id': '2', 'work_date': '2026-11-01'}).status_code == 400
    assert post(client, '/history/sessions', data={**base, 'task_id': '2', 'end_time': '09:00'}).status_code == 400
    with app_module.get_db() as db:
        assert db.execute('SELECT count(*) FROM task_sessions').fetchone()[0] == 0


def test_task_order_can_move_up_and_down_without_changing_history():
    client = app_module.app.test_client()
    for name in ['先頭', '中間', '最後']:
        post(client, '/tasks', data={'name': name})
    post(client, '/tasks/2/session', data={'start_time': '09:00', 'end_time': '09:20'})
    assert post(client, '/tasks/3/move', data={'direction': 'up'}).status_code == 302
    with app_module.get_db() as db:
        names = [row[0] for row in db.execute('SELECT name FROM tasks WHERE deleted_at IS NULL ORDER BY sort_order, id')]
        assert db.execute('SELECT task_id, duration_minutes FROM task_sessions').fetchone()[:] == (2, 20)
    assert names == ['先頭', '最後', '中間']
    assert post(client, '/tasks/3/move', data={'direction': 'down'}).status_code == 302
    assert post(client, '/tasks/1/move', data={'direction': 'up'}).status_code == 400
    page = client.get('/').get_data(as_text=True)
    assert page.index('<h3>先頭</h3>') < page.index('<h3>中間</h3>') < page.index('<h3>最後</h3>')


def test_week_and_month_task_charts_use_separate_date_ranges_and_keep_archived_tasks():
    from datetime import date
    with app_module.get_db() as db:
        db.execute("INSERT INTO tasks(id, name, created_at, sort_order) VALUES (1, '資料', 'test', 1)")
        db.execute("INSERT INTO tasks(id, name, created_at, sort_order, deleted_at) VALUES (2, '会議', 'test', 2, 'test')")
        for task_id, work_date, minutes in [
            (1, '2026-10-25', 30),  # 前週
            (1, '2026-10-26', 60),  # 対象週・月
            (2, '2026-10-27', 30),  # 削除済みタスク
            (1, '2026-11-01', 90),  # 対象週、翌月
        ]:
            db.execute("INSERT INTO task_sessions(task_id, work_date, start_time, end_time, duration_minutes, created_at) "
                       "VALUES (?, ?, '09:00', '10:00', ?, 'test')", (task_id, work_date, minutes))
        db.commit()
        week = app_module.weekly_summary(db, date(2026, 10, 28))
        month = app_module.monthly_overtime(db, date(2026, 10, 28))
    assert [(item['name'], item['minutes']) for item in week['task_totals']] == [('資料', 150), ('会議', 30)]
    assert [(item['name'], item['minutes']) for item in month['task_totals']] == [('資料', 90), ('会議', 30)]
    assert week['task_totals'][0]['percent'] == 83.3
    assert month['task_totals'][0]['percent'] == 75.0


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


def test_delete_task_preserves_history():
    client = app_module.app.test_client()
    post(client, "/tasks", data={"name": "削除テスト"})
    post(client, "/tasks/1/session", data={"start_time": "09:00", "end_time": "10:00"})
    post(client, "/tasks/1/delete")
    with app_module.get_db() as db:
        assert db.execute("SELECT deleted_at FROM tasks").fetchone()[0] is not None
        assert db.execute("SELECT count(*) FROM task_sessions").fetchone()[0] == 1
    text = client.get("/").get_data(as_text=True)
    assert '/tasks/1/session' not in text
    assert '1時間 0分（60分）' in text
    assert '削除テスト' in client.get('/history?task_id=1').get_data(as_text=True)
    post(client, '/tasks/1/session', data={'start_time': '10:00', 'end_time': '11:00'})
    with app_module.get_db() as db:
        assert db.execute("SELECT count(*) FROM task_sessions").fetchone()[0] == 1


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


def test_migrate_original_database_without_losing_data(tmp_path, monkeypatch):
    import shutil
    original = Path(app_module.__file__).parent / 'work_time.empty.db'
    target = tmp_path / 'original.db'
    shutil.copyfile(original, target)
    monkeypatch.setattr(app_module, 'DB_PATH', target)
    with app_module.get_db() as db:
        db.execute("INSERT INTO tasks(name, created_at) VALUES ('旧タスク', '2026-10-18')")
        db.execute("INSERT INTO task_sessions(task_id, work_date, start_time, end_time, duration_minutes, created_at) "
                   "VALUES (1, '2026-10-18', '09:00', '10:00', 60, '2026-10-18')")
        db.execute("INSERT INTO attendance(work_date, start_time, end_time, updated_at) "
                   "VALUES ('2026-10-18', '09:00', '18:00', '2026-10-18')")
        db.execute("INSERT INTO notes VALUES (1, '保存済みメモ')")
    app_module.init_db()
    app_module.init_db()
    with app_module.get_db() as db:
        assert db.execute('SELECT name, deleted_at FROM tasks').fetchone()[:] == ('旧タスク', None)
        assert db.execute('SELECT duration_minutes, content FROM task_sessions').fetchone()[:] == (60, '')
        assert db.execute('SELECT start_time FROM attendance').fetchone()[0] == '09:00'
        assert db.execute('SELECT content FROM notes').fetchone()[0] == '保存済みメモ'
    assert app_module.app.test_client().get('/reports?date=2026-10-18').status_code == 200


def test_history_filters_task_independently_of_content(monkeypatch):
    from datetime import date
    client = app_module.app.test_client()
    post(client, '/tasks', data={'name': '資料作成'})
    post(client, '/tasks', data={'name': '会議'})
    for day, task_id, content in [(19, 1, '月次資料'), (20, 1, '週次資料'), (21, 2, '月次資料')]:
        monkeypatch.setattr(app_module, 'today_jst', lambda day=day: date(2026, 10, day))
        post(client, f'/tasks/{task_id}/session', data={'start_time': '09:00', 'end_time': '11:30', 'content': content})
    text = client.get('/history?task_id=1').get_data(as_text=True)
    assert '月次資料' in text and '週次資料' in text
    assert '2026-10-19' in text and '2026-10-20' in text
    assert '<h3><a href="/history?date=2026-10-21' not in text
    assert '5時間 0分（300分）' in text
    text = client.get('/history?date=2026-10-20&task_id=1').get_data(as_text=True)
    assert '週次資料' in text and '月次資料' not in text
    assert '2時間 30分（150分）' in text
    assert '該当する作業履歴はありません' in client.get('/history?task_id=999').get_data(as_text=True)
    post(client, '/tasks/1/delete')
    assert '週次資料' in client.get('/history?task_id=1').get_data(as_text=True)
    response = post(client, '/sessions/2/delete', data={'return_to': 'history'}, follow_redirects=True)
    assert '週次資料' not in response.get_data(as_text=True)
    assert '月次資料' in client.get('/history?task_id=1').get_data(as_text=True)


def test_week_monday_sunday_year_boundary_and_incomplete():
    from datetime import date
    with app_module.get_db() as db:
        for day in ['2026-12-27', '2026-12-28', '2027-01-03', '2027-01-04']:
            db.execute("INSERT INTO attendance(work_date, start_time, break_start, break_end, end_time, updated_at) "
                       "VALUES (?, '09:00', '12:00', '13:00', '18:00', ?)", (day, day))
        db.execute("INSERT INTO attendance(work_date, start_time, updated_at) VALUES ('2026-12-29', '09:00', 'now')")
        db.commit()
        week = app_module.weekly_summary(db, date(2027, 1, 3))
    assert week['start'] == '2026-12-28' and week['end'] == '2027-01-03'
    assert week['net'] == 960 and week['gross'] == 1080 and week['break'] == 120
    assert week['incomplete'] == 1
    assert len(week['days']) == 7
    assert week['days'][1]['summary']['net'] is None


def test_daily_report_date_persistence_and_deletion(monkeypatch):
    from datetime import date
    client = app_module.app.test_client()
    monkeypatch.setattr(app_module, 'today_jst', lambda: date(2026, 10, 19))
    post(client, '/tasks', data={'name': '開発'})
    post(client, '/tasks/1/session', data={'start_time': '23:30', 'end_time': '00:15', 'content': '<script>内容</script>'})
    post(client, '/attendance', data={'start_time': '22:00', 'end_time': '01:00'})
    post(client, '/reports', data={'work_date': '2026-10-19', 'content': '成果\n<script>追記</script>'})
    monkeypatch.setattr(app_module, 'today_jst', lambda: date(2026, 10, 20))
    app_module.init_db()
    text = client.get('/reports?date=2026-10-19').get_data(as_text=True)
    assert '成果' in text and '&lt;script&gt;追記' in text
    assert '&lt;script&gt;内容' in text and '0時間 45分（45分）' in text
    assert '3時間 0分（180分）' in text
    assert '&lt;script&gt;追記' not in client.get('/reports?date=2026-10-20').get_data(as_text=True)
    post(client, '/reports', data={'work_date': '2026-10-19', 'action': 'delete'})
    with app_module.get_db() as db:
        assert db.execute('SELECT count(*) FROM daily_reports').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM task_sessions').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM attendance').fetchone()[0] == 1


@pytest.mark.parametrize('url', ['/reports?date=invalid', '/reports?date=9999-12-31',
                                '/history?date=2026-02-30', '/history?task_id=oops',
                                '/history?task_id=99999999999999999999999999'])
def test_invalid_history_and_report_parameters(url):
    assert app_module.app.test_client().get(url).status_code == 400


def test_new_forms_validation_and_csrf():
    client = app_module.app.test_client()
    assert client.post('/reports', data={'work_date': '2026-10-19', 'content': 'test'}).status_code == 400
    assert post(client, '/reports', data={'work_date': '2026-10-19', 'content': 'x' * 10001}).status_code == 400
    assert post(client, '/reports', data={'content': 'missing date'}).status_code == 400
    post(client, '/tasks', data={'name': 'test'})
    assert post(client, '/tasks/1/session', data={'start_time': '09:00', 'end_time': '10:00', 'content': 'x' * 2001}).status_code == 400
    with app_module.get_db() as db:
        assert db.execute('SELECT count(*) FROM task_sessions').fetchone()[0] == 0


def test_all_duration_formats():
    assert app_module.format_minutes(150) == '2時間 30分（150分）'
    assert app_module.format_minutes(0) == '0時間 0分（0分）'
    assert app_module.format_minutes(None) == '--'


def test_calendar_month_week_day_and_archived_tasks(monkeypatch):
    from datetime import date
    monkeypatch.setattr(app_module, 'today_jst', lambda: date(2026, 10, 25))
    client = app_module.app.test_client()
    post(client, '/tasks', data={'name': 'カレンダー用タスク'})
    post(client, '/tasks/1/session', data={'start_time': '09:00', 'end_time': '11:30', 'content': '実施済み内容'})
    post(client, '/tasks/1/delete')
    post(client, '/events', data={'work_date': '2026-10-25', 'title': '予定の会議', 'start_time': '13:00', 'end_time': '14:00'})
    month = client.get('/calendar?view=month&date=2026-10-25').get_data(as_text=True)
    assert '予定の会議' in month
    assert 'カレンダー用タスク' not in month and '実施済み内容' not in month
    week = client.get('/calendar?view=week&date=2026-10-25').get_data(as_text=True)
    assert '予定の会議' in week and 'カレンダー用タスク' in week and '実施済み内容' in week
    assert '2時間 30分（150分）' in week
    day = client.get('/calendar?view=day&date=2026-10-25').get_data(as_text=True)
    assert '合計 2時間 30分（150分）' in day
    assert 'カレンダー用タスク' not in client.get('/calendar?view=day&date=2026-10-24').get_data(as_text=True)
    with app_module.get_db() as db:
        assert db.execute('SELECT SUM(duration_minutes) FROM task_sessions').fetchone()[0] == 150
        assert db.execute('SELECT count(*) FROM attendance').fetchone()[0] == 0


def test_calendar_event_create_update_delete_persistence():
    client = app_module.app.test_client()
    post(client, '/events', data={'work_date': '2026-12-31', 'title': '終日予定<script>', 'content': '内容\n次の行'})
    app_module.init_db()
    text = client.get('/calendar?view=day&date=2026-12-31&edit_event=1').get_data(as_text=True)
    assert '終日予定&lt;script&gt;' in text and '終日' in text and '次の行' in text
    assert '予定を更新' in text
    post(client, '/events/1', data={'work_date': '2027-01-01', 'title': '移動後の予定', 'start_time': '10:00', 'end_time': '11:00'})
    assert '移動後の予定' in client.get('/calendar?view=month&date=2027-01-01').get_data(as_text=True)
    assert '終日予定' not in client.get('/calendar?view=day&date=2026-12-31').get_data(as_text=True)
    post(client, '/events/1/delete')
    with app_module.get_db() as db:
        assert db.execute('SELECT count(*) FROM calendar_events').fetchone()[0] == 0
    assert post(client, '/events/999/delete').status_code == 404
    assert post(client, '/events/999', data={'work_date': '2027-01-01', 'title': 'なし'}).status_code == 404


@pytest.mark.parametrize('values', [
    {'work_date': 'bad', 'title': 'test'}, {'title': 'test'},
    {'work_date': '2026-10-25', 'title': ''},
    {'work_date': '2026-10-25', 'title': 'x' * 121},
    {'work_date': '2026-10-25', 'title': 'test', 'content': 'x' * 2001},
    {'work_date': '2026-10-25', 'title': 'test', 'start_time': '09:00'},
    {'work_date': '2026-10-25', 'title': 'test', 'start_time': '9:0', 'end_time': '10:00'},
    {'work_date': '2026-10-25', 'title': 'test', 'start_time': '23:00', 'end_time': '01:00'},
    {'work_date': '2026-10-25', 'title': 'test', 'start_time': '09:00', 'end_time': '09:00'},
])
def test_calendar_event_validation(values):
    client = app_module.app.test_client()
    assert post(client, '/events', data=values).status_code == 400
    with app_module.get_db() as db:
        assert db.execute('SELECT count(*) FROM calendar_events').fetchone()[0] == 0


def test_calendar_csrf_and_query_validation():
    client = app_module.app.test_client()
    assert client.post('/events', data={'work_date': '2026-10-25', 'title': 'なし'}).status_code == 400
    assert client.get('/calendar?view=other').status_code == 400
    assert client.get('/calendar?date=2026-02-30').status_code == 400
    assert client.get('/calendar?edit_event=oops').status_code == 400
    assert client.get('/calendar?edit_event=9999999999999999999999').status_code == 400
    assert client.get('/calendar?edit_event=999').status_code == 404


def test_overtime_separates_weekdays_weekends_and_months():
    from datetime import date
    with app_module.get_db() as db:
        for work_date, start, end, bs, be in [
            ('2026-10-19', '09:00', '19:00', '12:00', '13:00'),  # 実働9h、残業1h
            ('2026-10-20', '09:00', '17:00', '12:00', '13:00'),  # 実働7h、前日の超過1hと相殺
            ('2026-10-21', '09:00', None, None, None),          # 未完了を除外
            ('2026-10-24', '09:00', '12:00', None, None),      # 土曜3h
            ('2026-10-25', '13:00', '15:30', None, None),      # 日曜2.5h
            ('2026-10-31', '22:00', '01:00', None, None),      # 月末土曜、開始日に3h
            ('2026-11-01', '09:00', '11:00', None, None),      # 翌月日曜2h
        ]:
            db.execute('INSERT INTO attendance(work_date,start_time,end_time,break_start,break_end,updated_at) VALUES (?,?,?,?,?,?)',
                       (work_date, start, end, bs, be, 'test'))
        db.commit()
        week = app_module.weekly_summary(db, date(2026, 10, 25))
        month = app_module.monthly_overtime(db, date(2026, 10, 25))
        next_month = app_module.monthly_overtime(db, date(2026, 11, 1))
    assert week['weekday_balance'] == 0 and week['weekday_overtime'] == 0
    assert week['weekend_overtime'] == 330
    assert week['overtime'] == 330 and week['incomplete'] == 1
    assert month['weekday_balance'] == 0 and month['weekday_overtime'] == 0
    assert month['weekend_overtime'] == 510
    assert month['overtime'] == 510 and month['incomplete'] == 1
    assert next_month['weekday_overtime'] == 0 and next_month['weekend_overtime'] == 120
    page = app_module.app.test_client().get('/reports?date=2026-10-25').get_data(as_text=True)
    assert '2026-10 の残業時間' in page and '＋8時間 30分（510分）' in page
    assert page.index('id="monthly-overtime"') > page.index('一週間の業務時間')


def test_overtime_offsets_weekday_shortfall_only_within_each_period():
    from datetime import date
    with app_module.get_db() as db:
        for work_date, start, end in [
            ('2026-10-26', '09:00', '19:00'),  # 月曜、実働9h
            ('2026-10-27', '09:00', '17:00'),  # 火曜、実働7h
            ('2026-10-28', '09:00', '20:00'),  # 水曜、実働10h
            ('2026-11-02', '09:00', '17:00'),  # 翌月、実働7h
            ('2026-11-07', '09:00', '11:00'),  # 土曜、実働2h
        ]:
            db.execute('INSERT INTO attendance(work_date,start_time,end_time,break_start,break_end,updated_at) VALUES (?,?,?,?,?,?)',
                       (work_date, start, end, '12:00' if work_date < '2026-11-07' else None,
                        '13:00' if work_date < '2026-11-07' else None, 'test'))
        db.commit()
        october_week = app_module.weekly_summary(db, date(2026, 10, 28))
        october = app_module.monthly_overtime(db, date(2026, 10, 28))
        november_week = app_module.weekly_summary(db, date(2026, 11, 7))
        november = app_module.monthly_overtime(db, date(2026, 11, 7))
    assert october_week['weekday_balance'] == 120
    assert october_week['weekday_overtime'] == 120
    assert october['weekday_overtime'] == 120
    assert november_week['weekday_balance'] == -60
    assert november_week['weekday_overtime'] == 0
    assert november_week['weekend_overtime'] == 120
    assert november_week['overtime'] == 120
    assert november['weekday_balance'] == -60 and november['overtime'] == 120


def test_calendar_week_crosses_year_and_month_layout():
    client = app_module.app.test_client()
    page = client.get('/calendar?view=week&date=2027-01-01').get_data(as_text=True)
    assert '2026-12-28' in page and '2027-01-03' in page
    for view in ['month', 'week', 'day']:
        assert client.get(f'/calendar?view={view}&date=1900-01-01').status_code == 200
        assert client.get(f'/calendar?view={view}&date=9998-12-31').status_code == 200

