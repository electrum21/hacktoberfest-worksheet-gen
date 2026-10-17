import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS tutors(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  pw_hash TEXT NOT NULL, api_hash TEXT UNIQUE, created TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS students(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tutor_id INTEGER NOT NULL REFERENCES tutors(id) ON DELETE CASCADE,
  name TEXT NOT NULL, level TEXT NOT NULL DEFAULT '',
  link_token TEXT UNIQUE NOT NULL, created TEXT NOT NULL,
  UNIQUE(tutor_id, name));

-- questions: student-safe JSON (no answers). mcq_key: server-only, never sent to students.
CREATE TABLE IF NOT EXISTS assignments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tutor_id INTEGER NOT NULL REFERENCES tutors(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  title TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '', due TEXT,
  questions TEXT NOT NULL, mcq_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'assigned'
    CHECK(status IN ('assigned','submitted','marked')),
  created TEXT NOT NULL,
  submitted_at TEXT, answers TEXT, mcq_score INTEGER, mcq_total INTEGER,
  late INTEGER NOT NULL DEFAULT 0,
  score INTEGER, total INTEGER, comment TEXT, marked_at TEXT);

CREATE INDEX IF NOT EXISTS idx_assign_student ON assignments(student_id, status);
CREATE INDEX IF NOT EXISTS idx_assign_tutor ON assignments(tutor_id, status);
"""


def connect(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init(path: str):
    c = connect(path)
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
