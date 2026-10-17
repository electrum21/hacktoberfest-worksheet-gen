"""Laptop side of hybrid mode: what gets published, and the full loop against a real portal
server running in a background thread. No Ollama, Streamlit or internet needed."""
import json
import logging
import os
import re
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace as NS

import requests
from werkzeug.serving import make_server

import portal_sync
import publish
import store
from portal.server import create_app
from portal_client import PortalClient, PortalError

logging.getLogger("werkzeug").setLevel(logging.ERROR)  # keep test output quiet

SECRET_SOLUTION = "ZZ-WORKED-SOLUTION-7731"
SECRET_SCHEME = "ZZ-MARK-SCHEME-9912"
SECRET_SHORT_ANSWER = "ZZ-SHORT-ANSWER-5540"


def q(**kw):
    base = dict(qtype="short", topic="Fractions", question="Q?", options=[], worked_solution=SECRET_SOLUTION,
                final_answer=SECRET_SHORT_ANSWER, marks=1, mark_scheme=[])
    base.update(kw)
    return NS(**base)


def worksheet():
    return NS(questions=[
        q(qtype="mcq", topic="Fractions", question="Pick one", options=["1", "2", "3", "4"], final_answer="C"),
        q(qtype="short", topic="Decimals", question="Short one", final_answer=SECRET_SHORT_ANSWER),
        q(qtype="structured", topic="Ratio", question="Explain", marks=3, final_answer="x",
          mark_scheme=[SECRET_SCHEME, "1m: method"]),
    ])


def as_json(ws):
    """What store.save keeps: the full worksheet including answers (local only)."""
    return json.dumps({"questions": [vars(x) for x in ws.questions]})


class TestPublishPayload(unittest.TestCase):
    def test_payload_has_no_answers_solutions_or_schemes(self):
        questions, key = publish.student_payload(worksheet())
        blob = json.dumps(questions)
        for secret in (SECRET_SOLUTION, SECRET_SCHEME, SECRET_SHORT_ANSWER):
            self.assertNotIn(secret, blob)
        self.assertEqual(key, {"0": "C"})  # MCQ letters only
        for item in questions:
            self.assertLessEqual(set(item), {"qtype", "question", "options", "marks"})

    def test_malformed_mcq_blocks_publishing(self):
        for bad in (q(qtype="mcq", options=["a", "b", "c", "d"], final_answer="4"),
                    q(qtype="mcq", options=["a", "b"], final_answer="A")):
            with self.assertRaises(ValueError):
                publish.student_payload(NS(questions=[bad]))

    def test_student_preview_matches_portal_renderer_and_hides_answers(self):
        html = publish.student_preview_html(worksheet(), "Maths", "PSLE Math")
        self.assertIn("Pick one", html)
        for secret in (SECRET_SOLUTION, SECRET_SCHEME, SECRET_SHORT_ANSWER):
            self.assertNotIn(secret, html)
        self.assertNotRegex(html, r"<input[^>]*\bchecked\b")  # no option pre-selected


class TestRender(unittest.TestCase):
    def test_student_copy_can_omit_the_key(self):
        import render
        ws = worksheet()
        with_key = render.to_html(ws, "Math", "Fractions", "medium")
        without = render.to_html(ws, "Math", "Fractions", "medium", include_key=False)
        self.assertIn(SECRET_SCHEME, with_key)              # default is unchanged
        for secret in (SECRET_SOLUTION, SECRET_SCHEME, SECRET_SHORT_ANSWER):
            self.assertNotIn(secret, without)
        self.assertNotIn("Answer Key", without)


class TestSecretKey(unittest.TestCase):
    def test_generated_key_is_shared_across_workers_and_private(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            keys = []
            threads = [threading.Thread(target=lambda: keys.append(create_app(db).config["SECRET_KEY"]))
                       for _ in range(6)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(len(set(keys)), 1)
            self.assertGreaterEqual(len(keys[0]), 32)
            if sys.platform != "win32":
                self.assertEqual(oct(os.stat(os.path.join(d, ".portal_secret")).st_mode & 0o777), "0o600")
            self.assertEqual([f for f in os.listdir(d) if f.endswith(".tmp")], [])


class TestClientGuards(unittest.TestCase):
    def test_requires_https_except_localhost(self):
        with self.assertRaises(PortalError):
            PortalClient("http://portal.example.com", "t")
        PortalClient("https://portal.example.com", "t")
        PortalClient("http://127.0.0.1:8000", "t")
        PortalClient("http://localhost:8000", "t")

    def test_rejects_junk_address_and_empty_token(self):
        for url, tok in (("", "t"), ("not a url", "t"), ("ftp://x.com", "t"), ("https://x.com", " ")):
            with self.assertRaises(PortalError):
                PortalClient(url, tok)

    def test_unreachable_portal_gives_a_readable_error(self):
        with self.assertRaises(PortalError) as cm:
            PortalClient("http://127.0.0.1:9", "t", timeout=1).ping()
        self.assertIn("Can't reach the portal", str(cm.exception))


class HybridCase(unittest.TestCase):
    """A real portal on localhost plus a temp local database."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = create_app(os.path.join(cls.tmp.name, "portal.db"), secret_key="k", testing=True)
        cls.server = make_server("127.0.0.1", 0, cls.app, threaded=True)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        # tutor account through the real signup form
        s = requests.Session()
        csrf = re.search(r'name="csrf" value="([^"]+)"', s.get(cls.base + "/signup").text).group(1)
        r = s.post(cls.base + "/signup", data=dict(csrf=csrf, name="Ms Tan", email="t@x.co",
                                                   password="correct horse"))
        cls.token = re.search(r"wsp_[\w-]+", r.text).group(0)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        self.local = tempfile.TemporaryDirectory()
        store.DB_PATH = os.path.join(self.local.name, "local.db")
        store.init()
        self.client = PortalClient(self.base, self.token)
        for s in self.client.students():  # clean slate on the shared portal
            self.client.delete_student(s["id"])

    def tearDown(self):
        self.local.cleanup()

    def save_worksheet(self, ws=None, student_id=None):
        ws = ws or worksheet()
        return ws, store.save("PSLE Math", "Fractions | Decimals | Ratio", "medium", "m", as_json(ws), student_id)

    def page(self, link, aid=None):
        return requests.get(f"{link}/{aid}" if aid else link).text


class TestFullLoop(HybridCase):
    def test_assign_submit_mark_updates_weak_topics_locally(self):
        sid = store.add_student("Ahmad", "P6")
        self.assertEqual(portal_sync.link_students(self.client), {"linked": 0, "created": 1})
        ws, wid = self.save_worksheet()
        aids = portal_sync.assign(self.client, ws, wid, [sid], "Fractions drill", "PSLE Math", "2099-01-01")
        self.assertEqual(len(aids), 1)

        # the student opens their link; nothing secret reaches the portal's page
        link = portal_sync.student_links(self.client)[sid]
        html = self.page(link, aids[0])
        self.assertIn("Pick one", html)
        for secret in (SECRET_SOLUTION, SECRET_SCHEME, SECRET_SHORT_ANSWER):
            self.assertNotIn(secret, html)

        # the student answers: MCQ right, short answer wrong, structured attempted
        requests.post(f"{link}/{aids[0]}", data={"q0": "C", "q1": "wrong", "q2": "some reasoning"})

        items, unmatched = portal_sync.inbox(self.client)
        self.assertEqual((len(items), unmatched), (1, []))
        item = items[0]
        self.assertEqual((item["student_name"], item["mcq_score"], item["mcq_total"]), ("Ahmad", 1, 1))
        self.assertEqual(item["answers"]["1"], "wrong")
        # the local copy still has the answer key for the tutor to mark against
        self.assertEqual(item["questions"][1]["final_answer"], SECRET_SHORT_ANSWER)

        # tutor marks: MCQ 1/1, short 0/1, structured 2/3
        score, total = portal_sync.finish(self.client, item, [1, 0, 2], "Revise decimals")
        self.assertEqual((score, total), (3, 5))

        # the student sees their mark, and the portal no longer lists it as waiting
        marked = self.page(link, aids[0])
        self.assertIn("3 / 5", marked)
        self.assertIn("Revise decimals", marked)
        self.assertEqual(portal_sync.inbox(self.client), ([], []))

        # weak topics were learned locally: Decimals and Ratio missed, Fractions right
        stats = {t: (a, m) for _s, t, a, m in store.topic_stats(sid)}
        self.assertEqual(stats, {"Fractions": (1, 0), "Decimals": (1, 1), "Ratio": (1, 1)})
        self.assertCountEqual(store.weak_topics(sid, "PSLE Math"), ["Decimals", "Ratio"])
        self.assertEqual(store.get_published(aids[0])[5], "marked")

    def test_assign_to_several_students(self):
        ids = [store.add_student(n) for n in ("Ahmad", "Mei", "Ravi")]
        portal_sync.link_students(self.client)
        ws, wid = self.save_worksheet()
        aids = portal_sync.assign(self.client, ws, wid, ids, "Shared sheet", "PSLE Math")
        self.assertEqual(len(set(aids)), 3)
        self.assertEqual(len(store.list_published()), 3)
        links = portal_sync.student_links(self.client)
        self.assertEqual(len(set(links.values())), 3)

    def test_linking_is_idempotent_and_matches_existing_names(self):
        store.add_student("Ahmad")
        self.client.add_student("Mei")  # already on the portal, not yet local
        store.add_student("Mei")
        self.assertEqual(portal_sync.link_students(self.client), {"linked": 1, "created": 1})
        self.assertEqual(portal_sync.link_students(self.client), {"linked": 0, "created": 0})
        self.assertEqual(len(self.client.students()), 2)

    def test_relink_after_student_deleted_on_portal(self):
        sid = store.add_student("Ahmad")
        portal_sync.link_students(self.client)
        self.client.delete_student(store.portal_student_id(sid))
        self.assertEqual(portal_sync.link_students(self.client)["created"], 1)

    def test_unlinked_or_empty_selection_is_refused(self):
        sid = store.add_student("Ahmad")
        ws, wid = self.save_worksheet()
        with self.assertRaises(ValueError):
            portal_sync.assign(self.client, ws, wid, [sid], "t", "s")  # not linked yet
        with self.assertRaises(ValueError):
            portal_sync.assign(self.client, ws, wid, [], "t", "s")

    def test_malformed_mcq_never_reaches_portal(self):
        sid = store.add_student("Ahmad")
        portal_sync.link_students(self.client)
        bad = NS(questions=[q(qtype="mcq", options=["a", "b", "c", "d"], final_answer="4")])
        ws, wid = self.save_worksheet(bad)
        with self.assertRaises(ValueError):
            portal_sync.assign(self.client, bad, wid, [sid], "t", "s")
        self.assertEqual(store.list_published(), [])

    def test_failed_feedback_records_nothing_locally_and_retry_works(self):
        sid = store.add_student("Ahmad")
        portal_sync.link_students(self.client)
        ws, wid = self.save_worksheet()
        aid = portal_sync.assign(self.client, ws, wid, [sid], "t", "PSLE Math")[0]
        link = portal_sync.student_links(self.client)[sid]
        requests.post(f"{link}/{aid}", data={"q0": "C"})
        item = portal_sync.inbox(self.client)[0][0]
        self.client.withdraw(aid)  # portal now 404s on feedback
        with self.assertRaises(PortalError):
            portal_sync.finish(self.client, item, [1, 1, 3])
        self.assertEqual(store.topic_stats(sid), [])
        self.assertEqual(store.get_published(aid)[5], "assigned")

    def test_marks_are_range_checked(self):
        item = {"aid": 1, "questions": [{"marks": 2, "topic": "t"}], "student_id": 1,
                "worksheet_id": 1, "subject": "s"}
        for bad in ([3], [-1], [1, 1]):
            with self.assertRaises(ValueError):
                portal_sync.finish(self.client, item, bad)

    def test_submission_for_deleted_local_worksheet_is_unmatched(self):
        sid = store.add_student("Ahmad")
        portal_sync.link_students(self.client)
        ws, wid = self.save_worksheet()
        aid = portal_sync.assign(self.client, ws, wid, [sid], "t", "PSLE Math")[0]
        requests.post(f"{portal_sync.student_links(self.client)[sid]}/{aid}", data={"q0": "A"})
        store.delete(wid)
        items, unmatched = portal_sync.inbox(self.client)
        self.assertEqual((items, [u["id"] for u in unmatched]), ([], [aid]))
        self.client.withdraw(aid)  # what the Discard button does
        self.assertEqual(portal_sync.inbox(self.client), ([], []))

    def test_withdraw_removes_from_student_view(self):
        sid = store.add_student("Ahmad")
        portal_sync.link_students(self.client)
        ws, wid = self.save_worksheet()
        aid = portal_sync.assign(self.client, ws, wid, [sid], "Oops wrong sheet", "PSLE Math")[0]
        link = portal_sync.student_links(self.client)[sid]
        self.assertIn("Oops wrong sheet", self.page(link))
        self.client.withdraw(aid)
        self.assertNotIn("Oops wrong sheet", self.page(link))

    def test_wrong_token_is_a_clear_error(self):
        with self.assertRaises(PortalError) as cm:
            PortalClient(self.base, "wsp_wrong").ping()
        self.assertEqual(cm.exception.status, 401)


class TestLocalStore(HybridCase):
    def test_settings_roundtrip_and_overwrite(self):
        self.assertEqual(store.get_setting("portal_url", "none"), "none")
        store.set_setting("portal_url", "https://a")
        store.set_setting("portal_url", "https://b")
        self.assertEqual(store.get_setting("portal_url"), "https://b")

    def test_deleting_student_or_worksheet_cleans_published_rows(self):
        a, b = store.add_student("A"), store.add_student("B")
        _ws, wid = self.save_worksheet()
        store.record_published(wid, 101, a, "t")
        store.record_published(wid, 102, b, "t")
        store.delete_student(a)
        self.assertEqual([r[0] for r in store.list_published()], [102])
        store.delete(wid)
        self.assertEqual(store.list_published(), [])

    def test_switching_portals_clears_stale_links(self):
        sid = store.add_student("A")
        store.set_portal_student(sid, 5)
        _ws, wid = self.save_worksheet()
        store.record_published(wid, 9, sid, "t")
        store.clear_portal_links()
        self.assertEqual(store.linked_map(), {})
        self.assertEqual(store.list_published(), [])

    def test_old_databases_migrate(self):
        import sqlite3
        path = os.path.join(self.local.name, "old.db")
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE students(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, "
                  "level TEXT DEFAULT '', created TEXT)")
        c.execute("INSERT INTO students(name) VALUES('Legacy')")
        c.commit()
        c.close()
        store.DB_PATH = path
        store.init()
        self.assertEqual([r[1] for r in store.list_students()], ["Legacy"])
        self.assertIsNone(store.portal_student_id(1))


if __name__ == "__main__":
    unittest.main()
