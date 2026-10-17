import io, json
import pytest
import engine, store, render
from engine import Question, Worksheet


def q(qtype="short", **kw):
    base = dict(question="What is 2+2 in a hawker centre?", qtype=qtype, topic="T",
                final_answer="4", worked_solution="2+2=4", marks=1)
    base.update(kw)
    return Question(**base)


# ---- answer matching ----
@pytest.mark.parametrize("a,b,expected", [
    ("$42.50", "42.5", True), ("3/4", "0.75", True), ("1,200", "1200", True),
    ("42 cm", "42", True), ("41", "42", False), ("Evaporation.", "evaporation", True),
    ("condensation", "evaporation", False),
])
def test_same_answer(a, b, expected):
    assert engine.same_answer(a, b) is expected


# ---- structure checks ----
def test_normalize_mcq_ok_and_strips_prefixes():
    m = q("mcq", final_answer="b.", options=["A. one", "B) two", "three", "four"], marks=3)
    out = engine.normalize(m)
    assert out.final_answer == "B" and out.options[:2] == ["one", "two"] and out.marks == 1


def test_normalize_mcq_strips_digit_prefixes():
    """Some models number options 1-4 instead of lettering them A-D; the digit prefix
    shouldn't leak into the rendered worksheet."""
    m = q("mcq", final_answer="C", options=["1. one", "2) two", "3. three", "4. four"])
    out = engine.normalize(m)
    assert out.options == ["one", "two", "three", "four"]


@pytest.mark.parametrize("bad", [
    q("mcq", final_answer="B", options=["a", "b", "c"]),                      # 3 options
    q("mcq", final_answer="the second", options=["a", "b", "c", "d"]),        # not a letter
    q("mcq", final_answer="A", options=["x", "x", "y", "z"]),                 # duplicate options
    q("short", final_answer=""),                                               # no answer
])
def test_normalize_rejects(bad):
    assert engine.normalize(bad) is None


def test_normalize_synthesizes_missing_mark_scheme():
    """A structured question with everything but mark_scheme is still usable:
    we fill in a minimal one instead of discarding an otherwise-good question."""
    out = engine.normalize(q("structured", mark_scheme=[]))
    assert out is not None and out.mark_scheme == ["1m: 4"]


# ---- planning ----
def test_plan_covers_all_questions_and_spreads():
    p = engine.plan(["A", "B"], ["mcq", "short"], 5)
    assert sum(c for _, _, c in p) == 5
    assert {t for t, _, _ in p} == {"A", "B"} and {x for _, x, _ in p} == {"mcq", "short"}
    assert engine.plan(["A"], ["short"], 3) == [("A", "short", 3)]


# ---- generate_batch with a fake model ----
def fake_batch(items):
    return json.dumps({"questions": items})


def test_generate_batch_filters_and_retries(monkeypatch):
    bad = {"question": "bad mcq", "options": ["a", "b"], "final_answer": "A", "marks": 1,
           "worked_solution": ""}
    good1 = {"question": "Ali buys 3 pens at $2 each at Bugis. Total?", "final_answer": "$6",
             "worked_solution": "3x2", "marks": 1}
    good2 = {"question": "Mei Ling walks 5 km in 1 hour on the park connector. Speed?",
             "final_answer": "5 km/h", "worked_solution": "5/1", "marks": 1}
    replies = iter([fake_batch([bad, good1]), fake_batch([good2])])
    monkeypatch.setattr(engine, "_chat", lambda *a, **k: next(replies))
    out = engine.generate_batch("PSLE Math", "Rate", "short", 2)
    assert len(out) == 2 and all(x.qtype == "short" and x.topic == "Rate" for x in out)


def test_generate_batch_raises_when_nothing_usable(monkeypatch):
    monkeypatch.setattr(engine, "_chat", lambda *a, **k: "not json")
    with pytest.raises(RuntimeError):
        engine.generate_batch("PSLE Math", "Ratio", "short", 2, retries=1)


def test_generate_orders_like_a_paper(monkeypatch):
    def fake(subject, topic, qtype, n, *a, **k):
        return [q(qtype, question=f"{topic} {qtype} {i}") for i in range(n)]
    monkeypatch.setattr(engine, "generate_batch", fake)
    ws = engine.generate("PSLE Science", ["A", "B"], ["structured", "mcq"], 4)
    assert [x.qtype for x in ws.questions] == ["mcq", "mcq", "structured", "structured"]


# ---- verification ----
def test_check_modes(monkeypatch):
    monkeypatch.setattr(engine, "solve_blind", lambda qq, model=None: "4")
    assert engine.check(q()) is True
    monkeypatch.setattr(engine, "solve_blind", lambda qq, model=None: "5")
    assert engine.check(q()) is False
    # open-ended without a numeric answer is not auto-checkable
    assert engine.check(q("structured", final_answer="Water vapour condenses", mark_scheme=["1m: x"])) is None
    monkeypatch.setattr(engine, "solve_blind", lambda qq, model=None: "B. two")
    assert engine.check(q("mcq", final_answer="B", options=list("wxyz"))) is True


def test_auto_fix_replaces_only_flagged(monkeypatch):
    ws = Worksheet(questions=[q(question="keep me"), q(question="replace me")])
    new = q(question="fresh one")
    monkeypatch.setattr(engine, "regenerate_one", lambda *a, **k: (new, True))
    ws, ok = engine.auto_fix(ws, [True, False], "PSLE Math", "medium")
    assert [x.question for x in ws.questions] == ["keep me", "fresh one"] and ok == [True, True]


def test_duplicate_pairs():
    ws = Worksheet(questions=[q(question="Ali buys 3 pens at $2 each"),
                              q(question="Ali buys 3 pens at $2 each today"),
                              q(question="Describe the water cycle")])
    assert engine.duplicate_pairs(ws) == 1


# ---- storage ----
@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "t.db"))
    store.init()


def test_students_results_and_weak_topics(tmpdb):
    sid = store.add_student("Ahmad", "P6")
    with pytest.raises(ValueError):
        store.add_student("Ahmad")
    wid = store.save("PSLE Math", "Ratio | Fractions", "medium", "m", Worksheet(questions=[q()]).model_dump_json(), sid)
    store.record_results(sid, wid, "PSLE Math", [("Ratio", False), ("Ratio", False), ("Fractions", True), ("Fractions", False)])
    assert store.weak_topics(sid, "PSLE Math") == ["Ratio", "Fractions"]
    assert store.weak_topics(sid, "PSLE Science") == []
    # re-recording replaces rather than duplicates
    store.record_results(sid, wid, "PSLE Math", [("Ratio", True)])
    assert store.weak_topics(sid, "PSLE Math") == []
    assert store.list_all()[0][5] == "Ahmad"
    store.delete_student(sid)
    assert store.list_all()[0][5] is None


# ---- rendering ----
def sample_ws():
    return Worksheet(questions=[
        q("mcq", final_answer="B", options=["one", "two", "three", "four"]),
        q("structured", question="Explain <b>why</b>", mark_scheme=["1m: a", "1m: b"], marks=2),
    ])


def test_html_escapes_and_has_key():
    h = render.to_html(sample_ws(), "PSLE Science", "Water cycle", "mixed", "Tutor X", "Ahmad")
    assert "&lt;b&gt;" in h and "<b>why" not in h
    assert "Answer Key and Mark Scheme" in h and "For: Ahmad" in h and "1m: a" in h


def test_docx_roundtrip():
    from docx import Document
    data = render.to_docx(sample_ws(), "PSLE Science", "Water cycle", "mixed")
    text = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    assert "Answer Key and Mark Scheme" in text and "B. two" in text and "1m: b" in text
