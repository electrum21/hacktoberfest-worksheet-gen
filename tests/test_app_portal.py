"""Headless UI test of the connected (hybrid) flow: Streamlit app + real portal on localhost.

Covers what README section 5a used to list as unrun: assign from the Generate tab, the Portal
tab's student links, and the Inbox (check, mark, send). The model is mocked; no Ollama needed.
"""
import logging
import os
import pathlib
import re
import tempfile
import threading

import pytest
import requests
from streamlit.testing.v1 import AppTest
from werkzeug.serving import make_server

import engine
import store
from engine import Question, Worksheet
from portal.server import create_app

logging.getLogger("werkzeug").setLevel(logging.ERROR)
APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(scope="module")
def portal():
    tmp = tempfile.TemporaryDirectory()
    app = create_app(os.path.join(tmp.name, "portal.db"), secret_key="k", testing=True)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    s = requests.Session()
    csrf = re.search(r'name="csrf" value="([^"]+)"', s.get(base + "/signup").text).group(1)
    r = s.post(base + "/signup", data=dict(csrf=csrf, name="Ms Tan", email="t@x.co", password="correct horse"))
    token = re.search(r"wsp_[\w-]+", r.text).group(0)
    yield base, token
    server.shutdown()
    tmp.cleanup()


@pytest.fixture
def app(tmp_path, monkeypatch, portal):
    base, token = portal
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "ui.db"))
    store.init()
    store.set_setting("portal_url", base)
    store.set_setting("portal_token", token)

    def fake_generate(subject, topics, qtypes, n, difficulty="medium", model=None, baseline=False, progress=None):
        qs = [Question(question=f"Q{i} about {topics[0]}", qtype="mcq", topic=topics[0], final_answer="A",
                       worked_solution="w", marks=1, options=list("abcd")) for i in range(n)]
        if progress:
            progress(1, 1, "x")
        return Worksheet(questions=qs)

    monkeypatch.setattr(engine, "generate", fake_generate)
    monkeypatch.setattr(engine, "verify", lambda ws, model=None, progress=None: [True] * len(ws.questions))
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def _button(at, part):
    return next(b for b in at.button if part in b.label)


def test_connected_app_loads_and_portal_tab_pings(app):
    assert not app.exception
    assert any("pass through your portal" in c.value for c in app.caption)
    next(t for t in app.text_input if t.label == "Portal address")  # settings form rendered


def test_assign_submit_and_mark_through_the_ui(app, portal):
    base, _ = portal
    next(t for t in app.text_input if t.label == "Student name").set_value("Ahmad")
    _button(app, "Add student").click().run()
    assert not app.exception

    app.sidebar.button[0].click().run()          # generate (mocked)
    assert not app.exception
    app.session_state["assign_picks"] = [store.list_students()[0][0]]  # AppTest can't pick non-string options
    _button(app, "Assign to selected students").click().run()
    assert not app.exception
    assert any("Assigned to 1 student" in s.value for s in app.success)

    # the student's private link is shown in the Portal tab; open it and submit
    link = next(c.value for c in app.code if "/s/" in c.value)
    aid = re.search(r"/s/[^\"']+/(\d+)", requests.get(link).text).group(1)
    requests.post(f"{link}/{aid}", data={"q0": "A", "q1": "B"})

    _button(app, "Check for submissions").click().run()
    assert not app.exception
    assert any("Ahmad" in m.value for m in app.markdown)

    _button(app, "Send marks to student").click().run()
    assert not app.exception
    assert not any(e for e in app.error)
    sid = store.list_students()[0][0]
    assert store.topic_stats(sid)  # per-topic results landed in the local profile
