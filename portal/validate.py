"""Strict input validation for what tutors send to the portal.

The key safeguard: a question may only contain the allow-listed student-safe fields.
If a client ever sends final_answer, worked_solution or mark_scheme, the request is
rejected rather than stored, so a bug on the laptop side cannot leak an answer key.
"""
from datetime import date

QTYPES = {"mcq", "short", "structured"}
ALLOWED_Q_KEYS = {"qtype", "question", "options", "marks"}
MAX_QUESTIONS = 40
MAX_STUDENTS_PER_CALL = 50
LETTERS = "ABCD"


def _text(v, field, max_len, required=False) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ValueError(f"{field} must be text")
    v = v.strip()
    if required and not v:
        raise ValueError(f"{field} is required")
    if len(v) > max_len:
        raise ValueError(f"{field} is too long (max {max_len} characters)")
    return v


def _int(v, field, lo, hi) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{field} must be a whole number")
    if not lo <= v <= hi:
        raise ValueError(f"{field} must be between {lo} and {hi}")
    return v


def clean_student(data) -> tuple[str, str]:
    if not isinstance(data, dict):
        raise ValueError("JSON object expected")
    return (_text(data.get("name"), "name", 60, required=True),
            _text(data.get("level"), "level", 30))


def clean_assignment(data) -> dict:
    if not isinstance(data, dict):
        raise ValueError("JSON object expected")
    title = _text(data.get("title"), "title", 120, required=True)
    subject = _text(data.get("subject"), "subject", 80)

    due = data.get("due")
    if due in (None, ""):
        due = None
    else:
        try:
            due = date.fromisoformat(_text(due, "due", 10)).isoformat()
        except ValueError:
            raise ValueError("due must be a date like 2026-11-30")

    ids = data.get("student_ids")
    if not isinstance(ids, list) or not ids:
        raise ValueError("student_ids must be a non-empty list")
    if len(ids) > MAX_STUDENTS_PER_CALL:
        raise ValueError(f"At most {MAX_STUDENTS_PER_CALL} students per call")
    ids = [_int(i, "student_ids entry", 1, 2 ** 31) for i in ids]
    ids = list(dict.fromkeys(ids))  # de-duplicate, keep order

    raw = data.get("questions")
    if not isinstance(raw, list) or not raw:
        raise ValueError("questions must be a non-empty list")
    if len(raw) > MAX_QUESTIONS:
        raise ValueError(f"At most {MAX_QUESTIONS} questions per worksheet")

    questions, mcq_idx = [], set()
    for i, q in enumerate(raw):
        n = i + 1
        if not isinstance(q, dict):
            raise ValueError(f"Question {n} must be an object")
        extra = set(q) - ALLOWED_Q_KEYS
        if extra:
            raise ValueError(f"Question {n} has unsupported field(s): {', '.join(sorted(extra))}. "
                             "Answers and mark schemes must never be sent to the portal.")
        qtype = q.get("qtype")
        if qtype not in QTYPES:
            raise ValueError(f"Question {n}: qtype must be one of {', '.join(sorted(QTYPES))}")
        item = {"qtype": qtype,
                "question": _text(q.get("question"), f"Question {n} text", 4000, required=True),
                "marks": _int(q.get("marks", 1), f"Question {n} marks", 1, 10)}
        opts = q.get("options") or []
        if qtype == "mcq":
            if not isinstance(opts, list) or len(opts) != 4:
                raise ValueError(f"Question {n}: multiple choice needs exactly 4 options")
            item["options"] = [_text(o, f"Question {n} option", 500, required=True) for o in opts]
            mcq_idx.add(str(i))
        elif opts:
            raise ValueError(f"Question {n}: only multiple choice questions have options")
        questions.append(item)

    key = data.get("mcq_key") or {}
    if not isinstance(key, dict):
        raise ValueError("mcq_key must be an object")
    if set(key) != mcq_idx:
        raise ValueError("mcq_key must have exactly one entry for each multiple choice question")
    for k, v in key.items():
        if v not in tuple(LETTERS):
            raise ValueError(f"mcq_key[{k}] must be one of A, B, C, D")

    return {"title": title, "subject": subject, "due": due, "student_ids": ids,
            "questions": questions, "mcq_key": dict(key)}


def clean_feedback(data) -> tuple[int, int, str]:
    if not isinstance(data, dict):
        raise ValueError("JSON object expected")
    total = _int(data.get("total"), "total", 0, 1000)
    score = _int(data.get("score"), "score", 0, total)
    return score, total, _text(data.get("comment"), "comment", 1000)
