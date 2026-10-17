import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH


@contextmanager
def db():
    c = sqlite3.connect(DB_PATH)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def init():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS students(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            level TEXT DEFAULT '', created TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS worksheets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created TEXT, subject TEXT, topic TEXT, difficulty TEXT,
            model TEXT, data TEXT, student_id INTEGER)""")
        cols = [r[1] for r in c.execute("PRAGMA table_info(worksheets)")]
        if "student_id" not in cols:  # migrate DBs from the first version
            c.execute("ALTER TABLE worksheets ADD COLUMN student_id INTEGER")
        scols = [r[1] for r in c.execute("PRAGMA table_info(students)")]
        if "portal_student_id" not in scols:  # link to the hosted portal's student record
            c.execute("ALTER TABLE students ADD COLUMN portal_student_id INTEGER")
        c.execute("""CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS published(
            id INTEGER PRIMARY KEY AUTOINCREMENT, worksheet_id INTEGER, portal_assignment_id INTEGER UNIQUE,
            student_id INTEGER, title TEXT, status TEXT DEFAULT 'assigned', created TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS results(
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, worksheet_id INTEGER,
            subject TEXT, topic TEXT, correct INTEGER, created TEXT)""")


# ----- students -----

def add_student(name: str, level: str = "") -> int:
    name = name.strip()
    if not name:
        raise ValueError("Name is required")
    try:
        with db() as c:
            return c.execute("INSERT INTO students(name,level,created) VALUES(?,?,?)",
                             (name, level.strip(), _now())).lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"A student called '{name}' already exists")


def list_students():
    with db() as c:
        return c.execute("SELECT id,name,level FROM students ORDER BY name").fetchall()


def delete_student(sid: int):
    with db() as c:
        c.execute("DELETE FROM results WHERE student_id=?", (sid,))
        c.execute("DELETE FROM published WHERE student_id=?", (sid,))
        c.execute("UPDATE worksheets SET student_id=NULL WHERE student_id=?", (sid,))
        c.execute("DELETE FROM students WHERE id=?", (sid,))


# ----- worksheets -----

def save(subject, topic, difficulty, model, ws_json: str, student_id=None) -> int:
    with db() as c:
        return c.execute(
            "INSERT INTO worksheets(created,subject,topic,difficulty,model,data,student_id) "
            "VALUES(?,?,?,?,?,?,?)",
            (_now(), subject, topic, difficulty, model, ws_json, student_id)).lastrowid


def list_all():
    with db() as c:
        return c.execute(
            "SELECT w.id,w.created,w.subject,w.topic,w.difficulty,s.name "
            "FROM worksheets w LEFT JOIN students s ON s.id=w.student_id "
            "ORDER BY w.id DESC").fetchall()


def load(wid: int):
    with db() as c:
        return c.execute(
            "SELECT subject,topic,difficulty,model,data,student_id FROM worksheets WHERE id=?",
            (wid,)).fetchone()


def delete(wid: int):
    with db() as c:
        c.execute("DELETE FROM results WHERE worksheet_id=?", (wid,))
        c.execute("DELETE FROM published WHERE worksheet_id=?", (wid,))
        c.execute("DELETE FROM worksheets WHERE id=?", (wid,))


# ----- results and weak topics -----

def record_results(student_id: int, worksheet_id: int, subject: str, items):
    """items: iterable of (topic, correct: bool). Replaces earlier results for this worksheet."""
    with db() as c:
        c.execute("DELETE FROM results WHERE student_id=? AND worksheet_id=?",
                  (student_id, worksheet_id))
        c.executemany(
            "INSERT INTO results(student_id,worksheet_id,subject,topic,correct,created) "
            "VALUES(?,?,?,?,?,?)",
            [(student_id, worksheet_id, subject, t, int(bool(ok)), _now()) for t, ok in items])


def topic_stats(student_id: int):
    """[(subject, topic, attempts, misses)] sorted by miss rate, worst first."""
    with db() as c:
        return c.execute(
            "SELECT subject, topic, COUNT(*) a, SUM(1-correct) m FROM results "
            "WHERE student_id=? GROUP BY subject, topic "
            "ORDER BY CAST(SUM(1-correct) AS REAL)/COUNT(*) DESC, m DESC", (student_id,)).fetchall()


def weak_topics(student_id: int, subject: str, k: int = 3) -> list[str]:
    return [t for s, t, a, m in topic_stats(student_id) if s == subject and m > 0][:k]


# ----- settings (portal address and token live here, on this machine only) -----

def get_setting(key: str, default: str = "") -> str:
    with db() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def set_setting(key: str, value: str):
    with db() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# ----- portal links and published worksheets -----

def set_portal_student(student_id: int, portal_student_id):
    with db() as c:
        c.execute("UPDATE students SET portal_student_id=? WHERE id=?", (portal_student_id, student_id))


def portal_student_id(student_id: int):
    with db() as c:
        r = c.execute("SELECT portal_student_id FROM students WHERE id=?", (student_id,)).fetchone()
    return r[0] if r else None


def linked_map() -> dict:
    """{local student id: portal student id} for students already linked."""
    with db() as c:
        return {i: p for i, p in c.execute(
            "SELECT id, portal_student_id FROM students WHERE portal_student_id IS NOT NULL")}


def record_published(worksheet_id: int, portal_assignment_id: int, student_id: int, title: str):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO published(worksheet_id,portal_assignment_id,student_id,title,status,created) "
                  "VALUES(?,?,?,?,'assigned',?)", (worksheet_id, portal_assignment_id, student_id, title, _now()))


def get_published(portal_assignment_id: int):
    """(id, worksheet_id, portal_assignment_id, student_id, title, status) or None."""
    with db() as c:
        return c.execute(
            "SELECT id,worksheet_id,portal_assignment_id,student_id,title,status FROM published "
            "WHERE portal_assignment_id=?", (portal_assignment_id,)).fetchone()


def list_published():
    with db() as c:
        return c.execute(
            "SELECT p.portal_assignment_id, p.title, p.status, p.created, s.name FROM published p "
            "LEFT JOIN students s ON s.id=p.student_id ORDER BY p.id DESC").fetchall()


def mark_published(portal_assignment_id: int, status: str = "marked"):
    with db() as c:
        c.execute("UPDATE published SET status=? WHERE portal_assignment_id=?", (status, portal_assignment_id))


def delete_published(portal_assignment_id: int):
    with db() as c:
        c.execute("DELETE FROM published WHERE portal_assignment_id=?", (portal_assignment_id,))


def clear_portal_links():
    """Call when the tutor points the app at a different portal: old ids mean nothing there."""
    with db() as c:
        c.execute("UPDATE students SET portal_student_id=NULL")
        c.execute("DELETE FROM published")
