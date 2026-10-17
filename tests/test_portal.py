"""Portal tests. Plain unittest so they run with `python -m unittest` or pytest.
No Ollama, Streamlit or network needed."""
import json
import os
import re
import sqlite3
import tempfile
import unittest
from unittest import mock

from portal import security, sheetview, validate
from portal.server import create_app


def csrf_from(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


MCQ = {"qtype": "mcq", "question": "What is 2 + 2?", "options": ["3", "4", "5", "6"], "marks": 1}
SHORT = {"qtype": "short", "question": "What is 3 x 3?", "marks": 1}
STRUCT = {"qtype": "structured", "question": "Explain why ice floats.", "marks": 3}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = os.path.join(self.tmp.name, "p.db")
        self.app = create_app(self.db, secret_key="test", testing=True)
        self.web = self.app.test_client()
        self.http = self.app.test_client()  # cookie-less client for API and student calls

    def tearDown(self):
        self.tmp.cleanup()

    def signup(self, email="t@example.com", name="Ms Tan", client=None):
        c = client or self.web
        csrf = csrf_from(c.get("/signup").text)
        r = c.post("/signup", data=dict(csrf=csrf, name=name, email=email, password="correct horse"),
                   follow_redirects=True)
        return re.search(r"wsp_[\w-]+", r.text).group(0)

    def api(self, method, path, token, **kw):
        return getattr(self.http, method)(f"/api/v1{path}", headers={"Authorization": f"Bearer {token}"}, **kw)

    def student(self, token, name="Ahmad"):
        r = self.api("post", "/students", token, json={"name": name, "level": "P6"})
        self.assertEqual(r.status_code, 201, r.text)
        return r.get_json()

    def assign(self, token, student_ids, questions=None, key=None, **extra):
        body = {"title": "Fractions drill", "subject": "PSLE Math", "student_ids": student_ids,
                "questions": questions or [MCQ, SHORT], "mcq_key": key if key is not None else {"0": "B"}}
        body.update(extra)
        return self.api("post", "/assignments", token, json=body)

    def link_path(self, student):
        return "/s/" + student["link"].rsplit("/s/", 1)[1]


class TestTutorAccounts(Base):
    def test_signup_shows_token_once(self):
        token = self.signup()
        self.assertTrue(token.startswith("wsp_"))
        again = self.web.get("/dashboard").text
        self.assertNotIn(token, again)
        self.assertIn("can’t be shown again", again)

    def test_token_is_stored_hashed(self):
        token = self.signup()
        row = sqlite3.connect(self.db).execute("SELECT api_hash, pw_hash FROM tutors").fetchone()
        self.assertNotIn(token, row[0])
        self.assertNotIn("correct horse", row[1])
        self.assertTrue(row[1].startswith("scrypt$"))

    def test_dashboard_requires_login(self):
        r = self.http.get("/dashboard")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_login_wrong_and_right_password(self):
        self.signup()
        c = self.app.test_client()
        csrf = csrf_from(c.get("/login").text)
        bad = c.post("/login", data=dict(csrf=csrf, email="t@example.com", password="nope nope nope"))
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Wrong email or password", bad.text)
        ok = c.post("/login", data=dict(csrf=csrf, email="T@Example.com", password="correct horse"))
        self.assertEqual(ok.status_code, 302)

    def test_csrf_required_on_post(self):
        self.assertEqual(self.http.post("/login", data=dict(email="a@b.co", password="x")).status_code, 400)

    def test_login_rate_limited(self):
        self.signup()
        c = self.app.test_client()
        csrf = csrf_from(c.get("/login").text)
        codes = [c.post("/login", data=dict(csrf=csrf, email="t@example.com", password="wrongwrong")).status_code
                 for _ in range(12)]
        self.assertEqual(codes[-1], 429)

    def test_signup_validation_and_duplicate(self):
        self.signup()
        c = self.app.test_client()
        csrf = csrf_from(c.get("/signup").text)
        short = c.post("/signup", data=dict(csrf=csrf, name="X", email="x@y.co", password="short"))
        self.assertEqual(short.status_code, 400)
        dup = c.post("/signup", data=dict(csrf=csrf, name="X", email="t@example.com", password="long enough pw"))
        self.assertIn("already exists", dup.text)

    def test_invite_code(self):
        with mock.patch.dict(os.environ, {"PORTAL_SIGNUP_CODE": "pilot-2026"}):
            app = create_app(os.path.join(self.tmp.name, "inv.db"), secret_key="k", testing=True)
        c = app.test_client()
        csrf = csrf_from(c.get("/signup").text)
        form = dict(csrf=csrf, name="X", email="x@y.co", password="long enough pw")
        self.assertEqual(c.post("/signup", data={**form, "code": "wrong"}).status_code, 400)
        self.assertEqual(c.post("/signup", data={**form, "code": "pilot-2026"}).status_code, 302)

    def test_rotate_token_invalidates_old(self):
        old = self.signup()
        csrf = csrf_from(self.web.get("/dashboard").text)
        r = self.web.post("/dashboard/token", data=dict(csrf=csrf), follow_redirects=True)
        new = re.search(r"wsp_[\w-]+", r.text).group(0)
        self.assertNotEqual(old, new)
        self.assertEqual(self.api("get", "/ping", old).status_code, 401)
        self.assertEqual(self.api("get", "/ping", new).status_code, 200)

    def test_delete_account_removes_everything(self):
        token = self.signup()
        s = self.student(token)
        self.assign(token, [s["id"]])
        csrf = csrf_from(self.web.get("/dashboard").text)
        self.web.post("/dashboard/delete-account", data=dict(csrf=csrf, confirm="delete"))
        c = sqlite3.connect(self.db)
        for t in ("tutors", "students", "assignments"):
            self.assertEqual(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], 0, t)

    def test_delete_account_needs_confirmation(self):
        self.signup()
        csrf = csrf_from(self.web.get("/dashboard").text)
        self.web.post("/dashboard/delete-account", data=dict(csrf=csrf, confirm="no"))
        self.assertEqual(sqlite3.connect(self.db).execute("SELECT COUNT(*) FROM tutors").fetchone()[0], 1)


class TestApi(Base):
    def test_requires_valid_token(self):
        self.assertEqual(self.http.get("/api/v1/ping").status_code, 401)
        self.assertEqual(self.api("get", "/ping", "wsp_bogus").status_code, 401)
        self.assertEqual(self.api("get", "/ping", self.signup()).status_code, 200)

    def test_students_crud_and_duplicate(self):
        t = self.signup()
        s = self.student(t)
        self.assertIn("/s/", s["link"])
        dup = self.api("post", "/students", t, json={"name": "Ahmad"})
        self.assertEqual(dup.status_code, 409)
        self.assertEqual(len(self.api("get", "/students", t).get_json()["students"]), 1)
        self.assertEqual(self.api("delete", f"/students/{s['id']}", t).status_code, 200)
        self.assertEqual(self.api("get", "/students", t).get_json()["students"], [])

    def test_assignment_rejects_answer_fields(self):
        t = self.signup()
        s = self.student(t)
        for field, value in (("final_answer", "4"), ("worked_solution", "2+2"), ("mark_scheme", ["1m"])):
            bad = {**SHORT, field: value}
            r = self.assign(t, [s["id"]], [MCQ, bad])
            self.assertEqual(r.status_code, 400, field)
            self.assertIn("never be sent", r.get_json()["error"])
        self.assertEqual(sqlite3.connect(self.db).execute("SELECT COUNT(*) FROM assignments").fetchone()[0], 0)

    def test_assignment_validation(self):
        t = self.signup()
        s = self.student(t)
        sid = [s["id"]]
        cases = {
            "mcq with 3 options": dict(questions=[{**MCQ, "options": ["a", "b", "c"]}], key={"0": "A"}),
            "mcq key missing": dict(questions=[MCQ], key={}),
            "key for non-mcq": dict(questions=[MCQ, SHORT], key={"0": "B", "1": "A"}),
            "bad letter": dict(questions=[MCQ], key={"0": "E"}),
            "options on short": dict(questions=[{**SHORT, "options": ["a"]}], key={}),
            "bad qtype": dict(questions=[{**SHORT, "qtype": "essay"}], key={}),
            "zero marks": dict(questions=[{**SHORT, "marks": 0}], key={}),
            "bool marks": dict(questions=[{**SHORT, "marks": True}], key={}),
            "empty questions": dict(questions=[], key={}),
            "too many": dict(questions=[SHORT] * 41, key={}),
            "bad due": dict(questions=[SHORT], key={}, due="next friday"),
        }
        for name, kw in cases.items():
            r = self.assign(t, sid, kw.pop("questions"), kw.pop("key"), **kw)
            self.assertEqual(r.status_code, 400, name)
        self.assertEqual(self.assign(t, [9999]).status_code, 404)
        self.assertEqual(self.assign(t, []).status_code, 400)
        self.assertEqual(self.assign(t, sid, [SHORT], {}, due="2026-11-30").status_code, 201)

    def test_one_assignment_per_student(self):
        t = self.signup()
        a, b = self.student(t, "Ahmad"), self.student(t, "Mei")
        r = self.assign(t, [a["id"], b["id"], a["id"]])
        self.assertEqual(len(r.get_json()["assignments"]), 2)

    def test_tutors_are_isolated(self):
        ta = self.signup("a@x.co", "A", client=self.app.test_client())
        tb = self.signup("b@x.co", "B", client=self.app.test_client())
        sa = self.student(ta)
        aid = self.assign(ta, [sa["id"]]).get_json()["assignments"][0]["id"]
        self.assertEqual(self.assign(tb, [sa["id"]]).status_code, 404)
        self.assertEqual(self.api("delete", f"/students/{sa['id']}", tb).status_code, 404)
        self.assertEqual(self.api("delete", f"/assignments/{aid}", tb).status_code, 404)
        self.assertEqual(self.api("post", f"/assignments/{aid}/feedback", tb,
                                  json={"score": 1, "total": 1}).status_code, 404)
        self.assertEqual(self.api("get", "/students", tb).get_json()["students"], [])

    def test_feedback_rules(self):
        t = self.signup()
        s = self.student(t)
        aid = self.assign(t, [s["id"]]).get_json()["assignments"][0]["id"]
        fb = lambda **kw: self.api("post", f"/assignments/{aid}/feedback", t, json=kw)
        self.assertEqual(fb(score=1, total=2).status_code, 409)  # not submitted yet
        self.http.post(self.link_path(s) + f"/{aid}", data={"q0": "B"})
        self.assertEqual(fb(score=3, total=2).status_code, 400)
        self.assertEqual(fb(score=-1, total=2).status_code, 400)
        self.assertEqual(fb(score=1, total=2, comment="Good effort").status_code, 200)

    def test_non_json_body(self):
        t = self.signup()
        r = self.api("post", "/students", t, data="name=x")
        self.assertEqual(r.status_code, 400)

    def test_api_errors_are_json(self):
        r = self.http.get("/api/v1/nope")
        self.assertEqual(r.status_code, 404)
        self.assertIn("error", r.get_json())


class TestStudentPages(Base):
    def setUp(self):
        super().setUp()
        self.t = self.signup()
        self.s = self.student(self.t)
        self.path = self.link_path(self.s)
        self.aid = self.assign(self.t, [self.s["id"]], [MCQ, SHORT, STRUCT], {"0": "B"}, due="2099-01-01") \
            .get_json()["assignments"][0]["id"]

    def test_sheet_shows_questions_without_any_answer_marked(self):
        html = self.http.get(f"{self.path}/{self.aid}").text
        self.assertIn("What is 2 + 2?", html)
        self.assertIn("Hand in", html)
        self.assertNotIn("checked", html)
        self.assertNotIn("mcq_key", html)

    def test_home_lists_worksheets(self):
        html = self.http.get(self.path).text
        self.assertIn("Hi Ahmad", html)
        self.assertIn("Fractions drill", html)

    def test_submit_marks_mcq_and_locks(self):
        r = self.http.post(f"{self.path}/{self.aid}", data={"q0": "B", "q1": "9", "q2": "Less dense."},
                           follow_redirects=True)
        self.assertIn("Handed in", r.text)
        sub = self.api("get", "/submissions", self.t).get_json()["submissions"][0]
        self.assertEqual((sub["mcq_score"], sub["mcq_total"]), (1, 1))
        self.assertEqual(sub["answers"], {"0": "B", "1": "9", "2": "Less dense."})
        self.assertFalse(sub["late"])
        # a second submit must not overwrite
        self.http.post(f"{self.path}/{self.aid}", data={"q0": "A", "q1": "0"})
        sub = self.api("get", "/submissions", self.t).get_json()["submissions"][0]
        self.assertEqual(sub["answers"]["0"], "B")

    def test_wrong_answer_page_never_reveals_the_key(self):
        self.http.post(f"{self.path}/{self.aid}", data={"q0": "A"})
        html = self.http.get(f"{self.path}/{self.aid}").text
        self.assertEqual(html.count("checked"), 1)
        self.assertRegex(html, r'value="A" checked')
        self.assertNotRegex(html, r'value="B" checked')

    def test_invalid_letter_and_overlong_text_are_sanitised(self):
        self.http.post(f"{self.path}/{self.aid}", data={"q0": "Z", "q1": "x" * 900, "q2": "y" * 5000})
        a = self.api("get", "/submissions", self.t).get_json()["submissions"][0]["answers"]
        self.assertEqual(a["0"], "")
        self.assertEqual((len(a["1"]), len(a["2"])), (500, 2000))

    def test_late_flag(self):
        aid = self.assign(self.t, [self.s["id"]], [SHORT], {}, due="2000-01-01").get_json()["assignments"][0]["id"]
        self.http.post(f"{self.path}/{aid}", data={"q0": "9"})
        subs = {s["id"]: s for s in self.api("get", "/submissions", self.t).get_json()["submissions"]}
        self.assertTrue(subs[aid]["late"])

    def test_marked_view_shows_score_and_comment(self):
        self.http.post(f"{self.path}/{self.aid}", data={"q0": "B"})
        self.api("post", f"/assignments/{self.aid}/feedback", self.t, json={"score": 4, "total": 5, "comment": "Nice work"})
        html = self.http.get(f"{self.path}/{self.aid}").text
        self.assertIn("4 / 5", html)
        self.assertIn("Nice work", html)
        self.assertEqual(self.api("get", "/submissions", self.t).get_json()["submissions"], [])

    def test_bad_links_are_404(self):
        for p in ("/s/short", "/s/" + "x" * 22, "/s/" + "x" * 80):
            self.assertEqual(self.http.get(p).status_code, 404, p)

    def test_other_students_worksheet_is_404(self):
        other = self.student(self.t, "Mei")
        self.assertEqual(self.http.get(f"{self.link_path(other)}/{self.aid}").status_code, 404)
        self.assertEqual(self.http.post(f"{self.link_path(other)}/{self.aid}", data={"q0": "A"}).status_code, 404)

    def test_new_link_replaces_old(self):
        r = self.api("post", f"/students/{self.s['id']}/new-link", self.t).get_json()
        self.assertEqual(self.http.get(self.path).status_code, 404)
        self.assertEqual(self.http.get(self.link_path(r)).status_code, 200)

    def test_content_is_escaped(self):
        s = self.student(self.t, "<b>Hax</b>")
        q = [{**SHORT, "question": "<script>alert(1)</script> & more"}]
        aid = self.assign(self.t, [s["id"]], q, {}).get_json()["assignments"][0]["id"]
        html = self.http.get(f"{self.link_path(s)}/{aid}").text + self.http.get(self.link_path(s)).text
        self.assertNotIn("<script>alert(1)", html)
        self.assertNotIn("<b>Hax</b>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_security_headers(self):
        r = self.http.get(f"{self.path}/{self.aid}")
        self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")
        self.assertNotIn("<script>", r.text.replace('<script src=', ''))  # no inline scripts under this CSP

    def test_deleting_student_removes_their_work(self):
        self.api("delete", f"/students/{self.s['id']}", self.t)
        self.assertEqual(sqlite3.connect(self.db).execute("SELECT COUNT(*) FROM assignments").fetchone()[0], 0)
        self.assertEqual(self.http.get(self.path).status_code, 404)

    def test_empty_state(self):
        t = self.signup("z@x.co", "Z", client=self.app.test_client())
        s = self.student(t, "Empty")
        self.assertIn("Nothing here yet", self.http.get(self.link_path(s)).text)


class TestDashboard(Base):
    def test_status_and_actions(self):
        t = self.signup()
        s = self.student(t)
        aid = self.assign(t, [s["id"]]).get_json()["assignments"][0]["id"]
        self.assertIn("Not submitted", self.web.get("/dashboard").text)
        self.http.post(f"{self.link_path(s)}/{aid}", data={"q0": "B"})
        self.assertIn("Pull it into your laptop app", self.web.get("/dashboard").text)
        csrf = csrf_from(self.web.get("/dashboard").text)
        self.web.post(f"/dashboard/assignments/{aid}/delete", data=dict(csrf=csrf))
        self.assertIn("Nothing assigned yet", self.web.get("/dashboard").text)

    def test_add_student_via_web_and_new_link(self):
        self.signup()
        csrf = csrf_from(self.web.get("/dashboard").text)
        self.web.post("/dashboard/students", data=dict(csrf=csrf, name="Mei", level="Sec 2"))
        html = self.web.get("/dashboard").text
        self.assertIn("Mei", html)
        before = re.search(r'data-copy="([^"]*/s/[^"]+)"', html).group(1)
        sid = sqlite3.connect(self.db).execute("SELECT id FROM students").fetchone()[0]
        self.web.post(f"/dashboard/students/{sid}/new-link", data=dict(csrf=csrf))
        after = re.search(r'data-copy="([^"]*/s/[^"]+)"', self.web.get("/dashboard").text).group(1)
        self.assertNotEqual(before, after)


class TestRetention(Base):
    def test_purge_old_marked_and_abandoned_but_keeps_unmarked_submissions(self):
        t = self.signup()
        s = self.student(t)
        ids = [self.assign(t, [s["id"]]).get_json()["assignments"][0]["id"] for _ in range(4)]
        old = "2000-01-01T00:00:00Z"
        c = sqlite3.connect(self.db)
        c.execute("UPDATE assignments SET created=? ", (old,))
        c.execute("UPDATE assignments SET status='marked', marked_at=? WHERE id=?", (old, ids[0]))
        c.execute("UPDATE assignments SET status='submitted', submitted_at=? WHERE id=?", (old, ids[1]))
        c.execute("UPDATE assignments SET created='2999-01-01T00:00:00Z' WHERE id=?", (ids[3],))
        c.commit()
        self.assertEqual(self.app.purge(180), 2)  # marked-old and assigned-old
        left = {r[0] for r in c.execute("SELECT id FROM assignments")}
        self.assertEqual(left, {ids[1], ids[3]})


class TestUnits(unittest.TestCase):
    def test_password_hashing(self):
        h = security.hash_password("pw12345678")
        self.assertTrue(security.verify_password("pw12345678", h))
        self.assertFalse(security.verify_password("other", h))
        self.assertFalse(security.verify_password("x", "garbage"))
        self.assertFalse(security.verify_password("x", security.DUMMY_HASH))

    def test_rate_limiter(self):
        rl = security.RateLimiter(3, 60)
        for _ in range(3):
            self.assertTrue(rl.ok("ip"))
            rl.record("ip")
        self.assertFalse(rl.ok("ip"))
        self.assertTrue(rl.ok("other"))

    def test_link_tokens_are_unique_and_long(self):
        toks = {security.new_link_token() for _ in range(200)}
        self.assertEqual(len(toks), 200)
        self.assertTrue(all(len(t) >= 20 for t in toks))

    def test_sheet_fragment_escapes_and_renders_types(self):
        html = sheetview.sheet_fragment([
            {**MCQ, "question": "<i>x</i>", "options": ["<a>", "b", "c", "d"]}, SHORT, STRUCT])
        self.assertNotIn("<i>x</i>", html)
        self.assertEqual(html.count('type="radio"'), 4)
        self.assertEqual(html.count("<textarea"), 1)
        self.assertEqual(html.count('type="text"'), 1)

    def test_preview_page_is_self_contained(self):
        page = sheetview.preview_page("T", [MCQ, SHORT], "Math")
        self.assertIn("Nothing you type here is saved", page)
        self.assertIn("<style>", page)
        self.assertNotIn('href="http', page)
        self.assertNotIn('src="http', page)

    def test_feedback_validation(self):
        self.assertEqual(validate.clean_feedback({"score": 2, "total": 3, "comment": " ok "}), (2, 3, "ok"))
        with self.assertRaises(ValueError):
            validate.clean_feedback({"score": 4, "total": 3})
        with self.assertRaises(ValueError):
            validate.clean_feedback({"score": "2", "total": 3})


if __name__ == "__main__":
    unittest.main()
