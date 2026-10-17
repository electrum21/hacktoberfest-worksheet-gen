"""Headless UI smoke test with the model mocked out."""
import pathlib
import pytest
from streamlit.testing.v1 import AppTest
import engine, store
from engine import Question, Worksheet


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "ui.db"))

    def fake_generate(subject, topics, qtypes, n, difficulty="medium", model=None, baseline=False, progress=None):
        qs = [Question(question=f"Q{i} about {topics[i % len(topics)]}", qtype=qtypes[0],
                       topic=topics[i % len(topics)], final_answer="4", worked_solution="w",
                       marks=1, options=list("abcd") if qtypes[0] == "mcq" else [],
                       mark_scheme=["1m: x"] if qtypes[0] == "structured" else [])
              for i in range(n)]
        if progress:
            progress(1, 1, "x")
        return Worksheet(questions=qs)

    monkeypatch.setattr(engine, "generate", fake_generate)
    monkeypatch.setattr(engine, "verify", lambda ws, model=None, progress=None: [True] + [False] * (len(ws.questions) - 1))
    monkeypatch.setattr(engine, "auto_fix", lambda ws, ok, *a, **k: (ws, [True] * len(ok)))
    at = AppTest.from_file(str(pathlib.Path(__file__).resolve().parent.parent / "app.py"), default_timeout=30)
    at.run()
    return at


def test_loads_clean(app):
    assert not app.exception


def test_generate_flow(app):
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert any("Q0 about" in m.value for m in app.markdown)


def test_every_subject_loads_and_generates(app):
    from syllabus import SUBJECTS
    for name in SUBJECTS:
        app.sidebar.selectbox[1].select(name).run()
        assert not app.exception, name
        app.sidebar.button[0].click().run()
        assert not app.exception, name


def _find_button(at, label_part):
    return next(b for b in at.button if label_part in b.label)


def test_student_flow_end_to_end(app):
    # add a student through the Students tab form
    next(t for t in app.text_input if t.label == "Student name").set_value("Ahmad")
    next(t for t in app.text_input if t.label.startswith("Level")).set_value("P6")
    _find_button(app, "Add student").click().run()
    assert not app.exception
    assert [r[1] for r in store.list_students()] == ["Ahmad"]

    # generate for that student, then save to history
    app.sidebar.selectbox[2].select_index(1).run()
    app.sidebar.button[0].click().run()
    assert not app.exception
    _find_button(app, "Save to history").click().run()
    assert not app.exception and store.list_all()[0][5] == "Ahmad"

    # record results: mark Q1 wrong, rest right
    next(c for c in app.checkbox if c.label.startswith("Q1 wrong")).check()
    _find_button(app, "Save results").click().run()
    assert not app.exception
    sid = store.list_students()[0][0]
    assert store.weak_topics(sid, "PSLE Math") == ["Whole numbers"]
