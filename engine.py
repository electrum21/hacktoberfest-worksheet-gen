import re
from typing import Callable, Optional

import ollama
from pydantic import BaseModel, ValidationError

from config import MODEL, HOST
from prompts import SYSTEM, BASELINE_SYSTEM, user_prompt
from syllabus import TYPE_ORDER

client = ollama.Client(host=HOST)
LETTERS = "ABCD"


# ---------- schemas ----------

class GenQuestion(BaseModel):
    """What we ask the model to produce."""
    question: str
    final_answer: str  # required; no default forces it into the JSON schema's required list
    worked_solution: str  # required for the same reason -- otherwise the model skips it
    options: list[str] = []
    marks: int = 1
    mark_scheme: list[str] = []


class GenBatch(BaseModel):
    questions: list[GenQuestion]


class Question(BaseModel):
    """What we store and render."""
    question: str
    qtype: str = "short"
    topic: str = ""
    options: list[str] = []
    worked_solution: str = ""
    final_answer: str = ""
    marks: int = 1
    mark_scheme: list[str] = []


class Worksheet(BaseModel):
    questions: list[Question]


class Solve(BaseModel):
    final_answer: str


def _chat(messages, schema, temperature, model):
    r = client.chat(model=model, messages=messages, format=schema,
                    options={"temperature": temperature, "num_ctx": 8192})
    return r.message.content


# ---------- structure checks ----------

_LETTER = re.compile(r"^\s*\(?([A-Da-d])\)?[\.\):]?\s*$")
_OPT_PREFIX = re.compile(r"^\s*\(?(?:[A-Da-d]|[1-4])[\)\.]\s+")


def normalize(q: Question) -> Optional[Question]:
    """Return a cleaned question, or None if its structure is unusable."""
    q.question = q.question.strip()
    q.final_answer = q.final_answer.strip()
    q.worked_solution = q.worked_solution.strip()
    q.marks = max(1, min(q.marks, 10))
    if not q.question or not q.final_answer:
        return None
    if q.qtype == "mcq":
        m = _LETTER.match(q.final_answer)
        if len(q.options) != 4 or not m:
            return None
        q.options = [_OPT_PREFIX.sub("", o).strip() for o in q.options]
        if any(not o for o in q.options) or len({o.lower() for o in q.options}) != 4:
            return None
        q.final_answer = m.group(1).upper()
        q.marks = 1
        q.mark_scheme = []
    else:
        q.options = []
        if q.qtype == "structured" and not q.mark_scheme:
            # Model sometimes omits the marking points even though the question and
            # final_answer are fine; synthesize a minimal one instead of discarding
            # an otherwise-usable question.
            q.mark_scheme = [f"{q.marks}m: {q.final_answer}"]
        if q.qtype == "short":
            q.mark_scheme = []
    return q


# ---------- similarity ----------

def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _similar(a: str, b: str, threshold=0.6) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    union = ta | tb
    return bool(union) and len(ta & tb) / len(union) >= threshold


def duplicate_pairs(ws: Worksheet, threshold=0.6) -> int:
    qs = ws.questions
    return sum(_similar(qs[i].question, qs[j].question, threshold)
               for i in range(len(qs)) for j in range(i + 1, len(qs)))


# ---------- generation ----------

def generate_batch(subject, topic, qtype, n, difficulty="medium", avoid=None,
                   model=MODEL, baseline=False, retries=2) -> list[Question]:
    """Generate n questions of one topic and type. May return fewer than n."""
    avoid = list(avoid or [])
    got: list[Question] = []
    last_err = None
    feedback = ""
    max_attempts = (retries + 1) * n if qtype == "structured" else retries + 1
    for attempt in range(max_attempts):
        need = n - len(got)
        if need <= 0:
            break
        request_n = 1 if qtype == "structured" else need
        retry_guidance = ""
        if feedback:
            retry_guidance = (
                "\n\nCorrection required from the previous attempt: "
                f"{feedback} Return a corrected question now; do not repeat the invalid structure."
            )
        msgs = [
            {"role": "system", "content": BASELINE_SYSTEM if baseline else SYSTEM},
            {"role": "user", "content": user_prompt(
                subject, topic, qtype, request_n, difficulty, avoid + [g.question for g in got], baseline)
                + retry_guidance},
        ]
        try:
            temperature = 0.3 if qtype == "structured" else 0.7
            raw = _chat(msgs, GenBatch.model_json_schema(), temperature, model)
            batch = GenBatch.model_validate_json(raw)
        except ValidationError as e:
            last_err = e
            feedback = "the response was not valid JSON matching the required question schema"
            continue
        rejected = 0
        for g in batch.questions:
            q = Question(**g.model_dump(), qtype=qtype, topic=topic)
            if not baseline:
                q = normalize(q)
                if q is None:
                    rejected += 1
                    continue
                if any(_similar(q.question, other) for other in avoid + [x.question for x in got]):
                    rejected += 1
                    continue
            got.append(q)
            if len(got) == n:
                break
        if rejected and len(got) < n:
            if qtype == "structured":
                feedback = (
                    f"{rejected} question(s) were rejected because each structured question "
                    "must have a non-empty `mark_scheme` JSON array"
                )
            elif qtype == "mcq":
                feedback = (
                    f"{rejected} question(s) were rejected because an MCQ needs exactly four "
                    "distinct options and a final answer of only A, B, C, or D"
                )
            else:
                feedback = f"{rejected} question(s) failed the required structure or duplicated an existing question"
    if not got:
        detail = f" Last schema error: {last_err}" if last_err else ""
        raise RuntimeError(
            f"Model returned no usable questions for '{topic}' ({qtype}) after "
            f"{attempt + 1} attempt(s).{detail}"
        )
    return got


def plan(topics: list[str], qtypes: list[str], n: int) -> list[tuple[str, str, int]]:
    """Spread n questions evenly across topics and question types."""
    counts: dict[tuple[str, str], int] = {}
    for i in range(n):
        key = (topics[i % len(topics)], qtypes[(i // len(topics)) % len(qtypes)])
        counts[key] = counts.get(key, 0) + 1
    return [(t, qt, c) for (t, qt), c in counts.items()]


Progress = Optional[Callable[[int, int, str], None]]


def generate(subject, topics, qtypes, n, difficulty="medium", model=MODEL,
             baseline=False, progress: Progress = None) -> Worksheet:
    groups = plan(topics, qtypes, n)
    questions: list[Question] = []
    for k, (topic, qtype, count) in enumerate(groups, 1):
        try:
            questions += generate_batch(subject, topic, qtype, count, difficulty,
                                        avoid=[q.question for q in questions],
                                        model=model, baseline=baseline)
        except RuntimeError:
            # One group exhausting its retries shouldn't discard everything else
            # already generated; the caller already warns when len(questions) < n.
            pass
        if progress:
            progress(k, len(groups), f"{topic} ({qtype})")
    if not questions:
        raise RuntimeError(
            "The model could not produce any usable questions for this worksheet. "
            "Try again, lower the difficulty, or pick a different model."
        )
    order = {t: i for i, t in enumerate(TYPE_ORDER)}
    questions.sort(key=lambda q: order.get(q.qtype, 99))  # stable: paper order
    return Worksheet(questions=questions)


# ---------- verification ----------

NUM = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?(?:/\d+)?")


def _nums(s: str) -> list[float]:
    out = []
    for m in NUM.findall(s):
        m = m.replace(",", "")
        try:
            if "/" in m:
                a, b = m.split("/")
                out.append(float(a) / float(b))
            else:
                out.append(float(m))
        except (ValueError, ZeroDivisionError):
            pass
    return out


def same_answer(a: str, b: str) -> bool:
    na, nb = _nums(a), _nums(b)
    if na and nb:
        return len(na) == len(nb) and all(abs(x - y) <= 0.01 * max(1, abs(y)) for x, y in zip(na, nb))
    clean = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return clean(a) == clean(b)


def is_verifiable(q: Question) -> bool:
    """MCQ and short answers always; structured only when the final answer is numeric."""
    return q.qtype in ("mcq", "short") or bool(_nums(q.final_answer))


def solve_blind(q: Question, model=MODEL) -> str:
    """Solve without seeing the claimed answer."""
    if q.qtype == "mcq":
        opts = "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(q.options))
        prompt = f"Answer this multiple-choice question. Reply with the single letter only.\n\n{q.question}\n{opts}"
    else:
        prompt = f"Solve this carefully. Give only the final answer(s).\n\n{q.question}"
    raw = _chat([{"role": "user", "content": prompt}], Solve.model_json_schema(), 0, model)
    try:
        return Solve.model_validate_json(raw).final_answer
    except ValidationError:
        return ""


def check(q: Question, model=MODEL) -> Optional[bool]:
    """True = blind answer matches, False = disagrees, None = not auto-checkable (tutor review)."""
    if not is_verifiable(q):
        return None
    ans = solve_blind(q, model)
    if not ans:
        return False
    if q.qtype == "mcq":
        return ans.strip().upper()[:1] == q.final_answer[:1].upper()
    return same_answer(ans, q.final_answer)


def verify(ws: Worksheet, model=MODEL, progress: Progress = None) -> list[Optional[bool]]:
    out = []
    for i, q in enumerate(ws.questions, 1):
        out.append(check(q, model))
        if progress:
            progress(i, len(ws.questions), f"question {i}")
    return out


def regenerate_one(ws, idx, subject, difficulty, model=MODEL) -> tuple[Question, Optional[bool]]:
    """Replace question idx with a fresh one of the same topic/type; up to 3 verified attempts."""
    old = ws.questions[idx]
    others = [q.question for i, q in enumerate(ws.questions) if i != idx]
    best = None
    for _ in range(3):
        q = generate_batch(subject, old.topic, old.qtype, 1, difficulty,
                           avoid=others + [old.question], model=model, retries=2)[0]
        ok = check(q, model)
        best = (q, ok)
        if ok is not False:
            break
    return best


def auto_fix(ws, ok, subject, difficulty, model=MODEL):
    """Replace every flagged (False) question once, in place."""
    for i, good in enumerate(ok):
        if good is False:
            try:
                ws.questions[i], ok[i] = regenerate_one(ws, i, subject, difficulty, model)
            except RuntimeError:
                # Keep the original flagged question if generation cannot produce a replacement.
                # The caller can still render it and the tutor can review it manually.
                continue
    return ws, ok
