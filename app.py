from __future__ import annotations

import sqlite3
import re
import secrets
from contextlib import closing
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "work_time.db"
JST = timezone(timedelta(hours=9))

app = Flask(__name__)
app.config.update(SECRET_KEY=secrets.token_hex(32), SESSION_COOKIE_SAMESITE="Strict")


@app.context_processor
def form_context():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return {"csrf_token": session["csrf_token"], "form_date": today_jst().isoformat()}


@app.before_request
def protect_forms():
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
            abort(400, "フォームが期限切れです。ページを再読み込みしてください。")
        if request.endpoint in {"save_attendance", "add_task_session"}:
            if request.form.get("form_date") != today_jst().isoformat():
                flash("日付が変わりました。時刻を確認して入力し直してください。", "error")
                return redirect(url_for("index"))


def now_jst() -> datetime:
    return datetime.now(JST)


def today_jst() -> date:
    return now_jst().date()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with closing(get_db()) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL CHECK(length(trim(name)) > 0),
                created_at TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                content TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                work_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL CHECK(duration_minutes >= 0),
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_task_sessions_date
            ON task_sessions(work_date);

            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL UNIQUE,
                start_time TEXT,
                break_start TEXT,
                break_end TEXT,
                end_time TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )
        db.commit()


def parse_hhmm(value: str | None) -> int | None:
    if not value:
        return None
    if not re.fullmatch(r"[0-9]{2}:[0-9]{2}", value):
        return None
    try:
        h, m = map(int, value.split(":"))
    except (ValueError, AttributeError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def minutes_between(start: str | None, end: str | None) -> int | None:
    s = parse_hhmm(start)
    e = parse_hhmm(end)
    if s is None or e is None:
        return None
    if e < s:
        # 24時をまたぐ入力にも対応（例 23:30 -> 00:15 = 45分）
        e += 24 * 60
    return e - s


def format_minutes(total: int | None) -> str:
    if total is None:
        return "--"
    hours, mins = divmod(max(total, 0), 60)
    return f"{hours}時間 {mins}分"


def attendance_summary(row: sqlite3.Row | None) -> dict[str, int | None | str]:
    if not row:
        return {"gross": None, "break": None, "net": None, "net_text": "--"}

    gross = minutes_between(row["start_time"], row["end_time"])
    break_minutes = minutes_between(row["break_start"], row["break_end"])
    if row["break_start"] and row["break_end"]:
        break_value = break_minutes or 0
    else:
        break_value = 0

    net = None if gross is None else max(gross - break_value, 0)
    return {
        "gross": gross,
        "break": break_value,
        "net": net,
        "net_text": format_minutes(net),
    }


@app.template_filter("minutes")
def minutes_filter(value: int | None) -> str:
    return format_minutes(value)


@app.route("/")
def index():
    today = today_jst().isoformat()
    with closing(get_db()) as db:
        note = db.execute("SELECT content FROM notes WHERE id = 1").fetchone()
        attendance = db.execute(
            "SELECT * FROM attendance WHERE work_date = ?", (today,)
        ).fetchone()

        tasks = db.execute(
            """
            SELECT
                t.id,
                t.name,
                COALESCE(SUM(CASE WHEN s.work_date = ? THEN s.duration_minutes ELSE 0 END), 0) AS today_minutes
            FROM tasks t
            LEFT JOIN task_sessions s ON s.task_id = t.id
            GROUP BY t.id, t.name, t.sort_order
            ORDER BY t.sort_order ASC, t.id ASC
            """,
            (today,),
        ).fetchall()

        sessions = db.execute(
            """
            SELECT s.id, s.start_time, s.end_time, s.duration_minutes, t.name AS task_name
            FROM task_sessions s
            JOIN tasks t ON t.id = s.task_id
            WHERE s.work_date = ?
            ORDER BY s.start_time DESC, s.id DESC
            """,
            (today,),
        ).fetchall()

        total_task_minutes = db.execute(
            "SELECT COALESCE(SUM(duration_minutes), 0) FROM task_sessions WHERE work_date = ?",
            (today,),
        ).fetchone()[0]

    return render_template(
        "index.html",
        today=today,
        attendance=attendance,
        attendance_summary=attendance_summary(attendance),
        tasks=tasks,
        sessions=sessions,
        total_task_minutes=total_task_minutes,
        note=note["content"] if note else "",
    )


@app.post("/notes")
def save_note():
    content = request.form.get("content", "")
    if len(content) > 10000:
        return "メモは10,000文字以内にしてください。戻って内容を短くしてください。", 400
    with closing(get_db()) as db:
        db.execute(
            "INSERT INTO notes(id, content) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET content = excluded.content", (content,)
        )
        db.commit()
    flash("メモを保存しました。", "success")
    return redirect(url_for("index") + "#notes")


@app.post("/attendance")
def save_attendance():
    today = today_jst().isoformat()
    start_time = request.form.get("start_time") or None
    break_start = request.form.get("break_start") or None
    break_end = request.form.get("break_end") or None
    end_time = request.form.get("end_time") or None

    for label, value in [
        ("開始時間", start_time),
        ("休憩開始", break_start),
        ("休憩終了", break_end),
        ("終了時間", end_time),
    ]:
        if value and parse_hhmm(value) is None:
            flash(f"{label}の形式が正しくありません。", "error")
            return redirect(url_for("index"))

    if bool(break_start) != bool(break_end):
        flash("休憩開始と休憩終了は両方入力してください。", "error")
        return redirect(url_for("index"))

    if break_start and break_end:
        if not start_time or not end_time:
            flash("休憩を保存する場合は勤務の開始・終了も入力してください。", "error")
            return redirect(url_for("index"))
        start = parse_hhmm(start_time)
        gross = minutes_between(start_time, end_time)
        break_offset = (parse_hhmm(break_start) - start) % (24 * 60)
        break_duration = minutes_between(break_start, break_end)
        if break_offset + break_duration > gross:
            flash("休憩は勤務開始から勤務終了までの範囲にしてください。", "error")
            return redirect(url_for("index"))

    with closing(get_db()) as db:
        db.execute(
            """
            INSERT INTO attendance(work_date, start_time, break_start, break_end, end_time, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(work_date) DO UPDATE SET
                start_time = excluded.start_time,
                break_start = excluded.break_start,
                break_end = excluded.break_end,
                end_time = excluded.end_time,
                updated_at = excluded.updated_at
            """,
            (
                today,
                start_time,
                break_start,
                break_end,
                end_time,
                now_jst().isoformat(timespec="seconds"),
            ),
        )
        db.commit()

    flash("本日の業務時間を保存しました。", "success")
    return redirect(url_for("index"))


@app.post("/tasks")
def add_task():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("タスク名を入力してください。", "error")
        return redirect(url_for("index"))
    if len(name) > 120:
        flash("タスク名は120文字以内にしてください。", "error")
        return redirect(url_for("index"))

    with closing(get_db()) as db:
        max_sort = db.execute("SELECT COALESCE(MAX(sort_order), 0) FROM tasks").fetchone()[0]
        db.execute(
            "INSERT INTO tasks(name, created_at, sort_order) VALUES (?, ?, ?)",
            (name, now_jst().isoformat(timespec="seconds"), max_sort + 1),
        )
        db.commit()

    flash("タスクを追加しました。", "success")
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/session")
def add_task_session(task_id: int):
    start_time = request.form.get("start_time") or ""
    end_time = request.form.get("end_time") or ""
    duration = minutes_between(start_time, end_time)

    if duration is None:
        flash("開始時刻と終了時刻を正しく入力してください。", "error")
        return redirect(url_for("index"))
    if duration <= 0:
        flash("作業時間は1分以上にしてください。", "error")
        return redirect(url_for("index"))
    if duration > 24 * 60:
        flash("1回の作業時間は24時間以内にしてください。", "error")
        return redirect(url_for("index"))

    with closing(get_db()) as db:
        task = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            flash("タスクが見つかりません。", "error")
            return redirect(url_for("index"))

        db.execute(
            """
            INSERT INTO task_sessions(task_id, work_date, start_time, end_time, duration_minutes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                today_jst().isoformat(),
                start_time,
                end_time,
                duration,
                now_jst().isoformat(timespec="seconds"),
            ),
        )
        db.commit()

    flash(f"{duration}分の作業を記録しました。", "success")
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/delete")
def delete_task(task_id: int):
    with closing(get_db()) as db:
        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        db.commit()
    flash("タスクを削除しました。", "success")
    return redirect(url_for("index"))


@app.post("/sessions/<int:session_id>/delete")
def delete_session(session_id: int):
    with closing(get_db()) as db:
        db.execute("DELETE FROM task_sessions WHERE id = ?", (session_id,))
        db.commit()
    flash("時間記録を削除しました。", "success")
    return redirect(url_for("index"))


@app.get("/history")
def history():
    with closing(get_db()) as db:
        attendance_rows = db.execute(
            "SELECT * FROM attendance ORDER BY work_date DESC LIMIT 90"
        ).fetchall()
        task_rows = db.execute(
            """
            SELECT s.work_date, t.name, s.start_time, s.end_time, s.duration_minutes
            FROM task_sessions s
            JOIN tasks t ON t.id = s.task_id
            ORDER BY s.work_date DESC, s.start_time DESC
            LIMIT 500
            """
        ).fetchall()

    attendance_items = [
        {"row": row, "summary": attendance_summary(row)} for row in attendance_rows
    ]
    return render_template(
        "history.html", attendance_items=attendance_items, task_rows=task_rows
    )


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)
