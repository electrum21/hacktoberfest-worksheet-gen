"""Hosted portal: tutor accounts, student links, the laptop-facing API, and student pages.

Design rules
- Answer keys never reach students. Questions are stored student-safe; only the MCQ key is
  stored (server-side, for instant marking) and it is never rendered or returned to students.
- Students have no accounts. A private link (128-bit token) opens their own worksheets.
- Structured/short-answer marking, mark schemes and weak-topic profiles stay on the laptop.
- Data minimisation: first names, a level, answers. Old data is purged automatically.

Config (environment)
  PORTAL_DB               SQLite path (default portal.db; put it on a persistent disk)
  PORTAL_SECRET           session signing key (default: generated and stored next to the DB)
  PORTAL_PUBLIC_URL       e.g. https://tutor-portal.example.com (used for links; enables Secure cookies)
  PORTAL_SIGNUP_CODE      if set, signup requires this invite code
  PORTAL_RETENTION_DAYS   delete marked/unsubmitted work older than this (default 180, 0 = keep)
  PORTAL_UTC_OFFSET_HOURS used for due dates and display (default 8, Singapore)
  PORTAL_TRUST_PROXY      set to 1 when behind one reverse proxy (so rate limits see real IPs)
"""
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from markupsafe import Markup

from . import db as dbmod, security, sheetview, validate

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WEB_POST_ENDPOINTS = {"signup", "login", "logout", "rotate_token", "add_student_web",
                      "remove_student_web", "rotate_link_web", "remove_assignment_web",
                      "delete_account"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_app(db_path: str | None = None, secret_key: str | None = None,
               testing: bool = False) -> Flask:
    db_path = db_path or os.getenv("PORTAL_DB", "portal.db")
    public_url = os.getenv("PORTAL_PUBLIC_URL", "").rstrip("/")
    signup_code = os.getenv("PORTAL_SIGNUP_CODE", "")
    retention_days = int(os.getenv("PORTAL_RETENTION_DAYS", "180"))
    utc_offset = float(os.getenv("PORTAL_UTC_OFFSET_HOURS", "8"))
    tz = timezone(timedelta(hours=utc_offset))

    dbmod.init(db_path)

    if secret_key is None:
        secret_key = os.getenv("PORTAL_SECRET", "")
    if not secret_key:  # persist a generated key so sessions survive restarts and workers
        path = os.path.join(os.path.dirname(os.path.abspath(db_path)), ".portal_secret")
        if not os.path.exists(path):
            # Write to a private temp file, then publish it atomically. Two workers starting
            # together can then never read a half-written (empty) key.
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w") as f:
                f.write(secrets.token_hex(32))
            os.chmod(tmp, 0o600)
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass
            except OSError:  # filesystem without hard links
                if not os.path.exists(path):
                    os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        with open(path) as f:
            secret_key = f.read().strip()
        if not secret_key:
            raise RuntimeError(f"{path} is empty. Delete it or set PORTAL_SECRET.")

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=secret_key, TESTING=testing,
        MAX_CONTENT_LENGTH=1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=public_url.startswith("https://"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    )
    if os.getenv("PORTAL_TRUST_PROXY") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    auth_limiter = security.RateLimiter(10, 300)      # failed logins / bad API tokens
    student_limiter = security.RateLimiter(240, 60)   # requests to student links
    state = {"last_purge": 0.0}

    # ---------------- db helpers ----------------
    def conn() -> sqlite3.Connection:
        if "db" not in g:
            g.db = dbmod.connect(db_path)
        return g.db

    def one(sql, args=()):
        return conn().execute(sql, args).fetchone()

    def many(sql, args=()):
        return conn().execute(sql, args).fetchall()

    def run(sql, args=()):
        cur = conn().execute(sql, args)
        conn().commit()
        return cur

    @app.teardown_appcontext
    def _close(_exc):
        c = g.pop("db", None)
        if c is not None:
            c.close()

    def purge(days: int = retention_days) -> int:
        """Delete finished or abandoned work older than `days`. Submitted-but-unmarked
        work is kept: the tutor has not collected it yet."""
        if days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        c = dbmod.connect(db_path)
        try:
            n = c.execute(
                "DELETE FROM assignments WHERE (status='marked' AND marked_at < ?) "
                "OR (status='assigned' AND created < ?)", (cutoff, cutoff)).rowcount
            c.commit()
            return n
        finally:
            c.close()

    app.purge = purge  # exposed for the CLI and tests

    def today_local():
        return datetime.now(tz).date()

    # ---------------- request hooks ----------------
    @app.before_request
    def _hooks():
        if retention_days > 0 and time.time() - state["last_purge"] > 3600:
            state["last_purge"] = time.time()
            purge()
        if request.method == "POST" and request.endpoint in WEB_POST_ENDPOINTS:
            sent = request.form.get("csrf", "")
            if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
                abort(400, "Your form expired. Go back, refresh the page and try again.")

    @app.after_request
    def _headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    @app.context_processor
    def _ctx():
        return {"csrf_field": lambda: Markup(
            f'<input type="hidden" name="csrf" value="{csrf_token()}">'),
            "tutor": getattr(g, "tutor", None)}

    @app.template_filter("when")
    def _when(iso):
        if not iso:
            return ""
        d = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return d.astimezone(tz).strftime("%d %b %Y, %H:%M")

    @app.template_filter("day")
    def _day(iso):
        if not iso:
            return ""
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b %Y")

    def base_url() -> str:
        return public_url or request.host_url.rstrip("/")

    def link_for(token: str) -> str:
        return f"{base_url()}/s/{token}"

    # ---------------- errors ----------------
    def wants_json() -> bool:
        return request.path.startswith("/api/")

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(413)
    def _err(e):
        msg = getattr(e, "description", "Something went wrong.")
        if e.code == 404:
            msg = "This page doesn't exist."
        if e.code == 413:
            msg = "That request is too large."
        if wants_json():
            return jsonify(error=msg), e.code
        return render_template("error.html", code=e.code, message=msg), e.code

    def jerr(msg, code=400):
        return jsonify(error=msg), code

    # =====================================================================
    # Tutor web pages
    # =====================================================================
    def login_required(f):
        @wraps(f)
        def w(*a, **k):
            tid = session.get("tutor_id")
            row = one("SELECT * FROM tutors WHERE id=?", (tid,)) if tid else None
            if not row:
                session.pop("tutor_id", None)
                return redirect(url_for("login"))
            g.tutor = row
            return f(*a, **k)
        return w

    @app.get("/")
    def index():
        if session.get("tutor_id"):
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.get("/healthz")
    def healthz():
        one("SELECT 1")
        return "ok"

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            name = request.form.get("name", "").strip()[:80]
            email = request.form.get("email", "").strip().lower()[:200]
            pw = request.form.get("password", "")
            code = request.form.get("code", "")
            problem = None
            if not auth_limiter.ok(request.remote_addr or "?"):
                problem = "Too many attempts. Try again in a few minutes."
            elif signup_code and not hmac.compare_digest(code, signup_code):
                auth_limiter.record(request.remote_addr or "?")
                problem = "That invite code isn't right."
            elif not name:
                problem = "Enter your name or your centre's name."
            elif not EMAIL_RE.match(email):
                problem = "Enter a valid email address."
            elif not 8 <= len(pw) <= 200:
                problem = "Use a password of at least 8 characters."
            elif one("SELECT 1 FROM tutors WHERE email=?", (email,)):
                problem = "An account with that email already exists. Log in instead."
            if problem:
                return render_template("signup.html", problem=problem, name=name, email=email,
                                       needs_code=bool(signup_code)), 400
            token, thash = security.new_api_token()
            tid = run("INSERT INTO tutors(email,name,pw_hash,api_hash,created) VALUES(?,?,?,?,?)",
                      (email, name, security.hash_password(pw), thash, _utc_now())).lastrowid
            session.clear()
            session.permanent = True
            session["tutor_id"] = tid
            session["new_token"] = token
            return redirect(url_for("dashboard"))
        return render_template("signup.html", problem=None, name="", email="",
                               needs_code=bool(signup_code))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            ip = request.remote_addr or "?"
            email = request.form.get("email", "").strip().lower()
            pw = request.form.get("password", "")
            if not auth_limiter.ok(ip):
                return render_template("login.html", problem="Too many attempts. Try again in a few minutes.",
                                       email=email), 429
            row = one("SELECT * FROM tutors WHERE email=?", (email,))
            good = security.verify_password(pw[:200], row["pw_hash"] if row else security.DUMMY_HASH)
            if not (row and good):
                auth_limiter.record(ip)
                return render_template("login.html", problem="Wrong email or password.", email=email), 400
            session.clear()
            session.permanent = True
            session["tutor_id"] = row["id"]
            return redirect(url_for("dashboard"))
        return render_template("login.html", problem=None, email="")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        tid = g.tutor["id"]
        students = many(
            "SELECT s.*, "
            "(SELECT COUNT(*) FROM assignments a WHERE a.student_id=s.id AND a.status!='marked') AS open_count "
            "FROM students s WHERE s.tutor_id=? ORDER BY s.name", (tid,))
        order = "CASE a.status WHEN 'submitted' THEN 0 WHEN 'assigned' THEN 1 ELSE 2 END"
        assignments = many(
            f"SELECT a.id,a.title,a.subject,a.due,a.status,a.late,a.created,a.mcq_score,a.mcq_total,"
            f"a.score,a.total,s.name AS student_name FROM assignments a "
            f"JOIN students s ON s.id=a.student_id WHERE a.tutor_id=? "
            f"ORDER BY {order}, a.id DESC LIMIT 200", (tid,))
        return render_template(
            "dashboard.html", students=students, assignments=assignments,
            new_token=session.pop("new_token", None), base=base_url(),
            has_token=bool(g.tutor["api_hash"]), link_for=link_for)

    @app.post("/dashboard/token")
    @login_required
    def rotate_token():
        token, thash = security.new_api_token()
        run("UPDATE tutors SET api_hash=? WHERE id=?", (thash, g.tutor["id"]))
        session["new_token"] = token
        flash("New token created. The old one no longer works.")
        return redirect(url_for("dashboard"))

    @app.post("/dashboard/students")
    @login_required
    def add_student_web():
        try:
            name, level = validate.clean_student(
                {"name": request.form.get("name"), "level": request.form.get("level")})
            run("INSERT INTO students(tutor_id,name,level,link_token,created) VALUES(?,?,?,?,?)",
                (g.tutor["id"], name, level, security.new_link_token(), _utc_now()))
            flash(f"Added {name}.")
        except ValueError as e:
            flash(str(e), "error")
        except sqlite3.IntegrityError:
            flash("You already have a student with that name.", "error")
        return redirect(url_for("dashboard"))

    @app.post("/dashboard/students/<int:sid>/delete")
    @login_required
    def remove_student_web(sid):
        cur = run("DELETE FROM students WHERE id=? AND tutor_id=?", (sid, g.tutor["id"]))
        flash("Student and their worksheets removed." if cur.rowcount else "Student not found.",
              "info" if cur.rowcount else "error")
        return redirect(url_for("dashboard"))

    @app.post("/dashboard/students/<int:sid>/new-link")
    @login_required
    def rotate_link_web(sid):
        cur = run("UPDATE students SET link_token=? WHERE id=? AND tutor_id=?",
                  (security.new_link_token(), sid, g.tutor["id"]))
        flash("New link created. The old link no longer works." if cur.rowcount else "Student not found.")
        return redirect(url_for("dashboard"))

    @app.post("/dashboard/assignments/<int:aid>/delete")
    @login_required
    def remove_assignment_web(aid):
        run("DELETE FROM assignments WHERE id=? AND tutor_id=?", (aid, g.tutor["id"]))
        flash("Worksheet removed from the portal.")
        return redirect(url_for("dashboard"))

    @app.post("/dashboard/delete-account")
    @login_required
    def delete_account():
        if request.form.get("confirm", "").strip().lower() != "delete":
            flash('Type "delete" to confirm.', "error")
            return redirect(url_for("dashboard"))
        run("DELETE FROM tutors WHERE id=?", (g.tutor["id"],))
        session.clear()
        return render_template("error.html", code=200,
                               message="Your account and all student data have been deleted.")

    # =====================================================================
    # Student pages (no accounts; the link is the credential)
    # =====================================================================
    def student_or_404(link: str):
        if not student_limiter.ok(request.remote_addr or "?"):
            abort(429)
        student_limiter.record(request.remote_addr or "?")
        row = one("SELECT * FROM students WHERE link_token=?", (link,)) if 10 <= len(link) <= 64 else None
        if not row:
            abort(404)
        return row

    @app.errorhandler(429)
    def _429(e):
        if wants_json():
            return jsonify(error="Too many requests."), 429
        return render_template("error.html", code=429, message="Too many requests. Wait a minute and try again."), 429

    def assignment_for(student, aid):
        row = one("SELECT * FROM assignments WHERE id=? AND student_id=?", (aid, student["id"]))
        if not row:
            abort(404)
        return row

    @app.get("/s/<link>")
    def student_home(link):
        s = student_or_404(link)
        rows = many("SELECT id,title,subject,due,status,late,score,total FROM assignments "
                    "WHERE student_id=? ORDER BY CASE status WHEN 'assigned' THEN 0 ELSE 1 END, id DESC",
                    (s["id"],))
        return render_template("student_home.html", student=s, rows=rows,
                               today=today_local().isoformat())

    @app.get("/s/<link>/<int:aid>")
    def student_sheet(link, aid):
        s = student_or_404(link)
        a = assignment_for(s, aid)
        questions = json.loads(a["questions"])
        answers = json.loads(a["answers"]) if a["answers"] else None
        sheet = Markup(sheetview.sheet_fragment(questions, answers, readonly=a["status"] != "assigned"))
        total = sum(q["marks"] for q in questions)
        return render_template("student_sheet.html", student=s, a=a, sheet=sheet,
                               n=len(questions), total=total, today=today_local().isoformat())

    @app.post("/s/<link>/<int:aid>")
    def student_submit(link, aid):
        s = student_or_404(link)
        a = assignment_for(s, aid)
        if a["status"] != "assigned":
            return redirect(url_for("student_sheet", link=link, aid=aid))
        questions = json.loads(a["questions"])
        key = json.loads(a["mcq_key"])
        answers, mcq_score, mcq_total = {}, 0, 0
        for i, q in enumerate(questions):
            val = request.form.get(f"q{i}", "").strip()
            if q["qtype"] == "mcq":
                val = val.upper() if val.upper() in tuple(sheetview.LETTERS) else ""
                mcq_total += q["marks"]
                if val and val == key.get(str(i)):
                    mcq_score += q["marks"]
            else:
                val = val[:500 if q["qtype"] == "short" else 2000]
            answers[str(i)] = val
        late = int(bool(a["due"]) and today_local().isoformat() > a["due"])
        cur = run("UPDATE assignments SET status='submitted', submitted_at=?, answers=?, "
                  "mcq_score=?, mcq_total=?, late=? WHERE id=? AND status='assigned'",
                  (_utc_now(), json.dumps(answers), mcq_score, mcq_total, late, aid))
        if cur.rowcount:
            flash("Submitted. Your tutor will mark it.")
        return redirect(url_for("student_sheet", link=link, aid=aid))

    # =====================================================================
    # API used by the tutor's laptop app (Bearer token)
    # =====================================================================
    def api_auth(f):
        @wraps(f)
        def w(*a, **k):
            ip = request.remote_addr or "?"
            if not auth_limiter.ok(ip):
                return jerr("Too many failed attempts. Try again in a few minutes.", 429)
            header = request.headers.get("Authorization", "")
            token = header[7:].strip() if header.lower().startswith("bearer ") else ""
            row = one("SELECT * FROM tutors WHERE api_hash=?", (security.token_hash(token),)) if token else None
            if not row:
                auth_limiter.record(ip)
                return jerr("Invalid or missing API token.", 401)
            g.tutor = row
            return f(*a, **k)
        return w

    def body():
        data = request.get_json(silent=True)
        if data is None:
            raise ValueError("Send a JSON body with Content-Type: application/json")
        return data

    def student_json(r):
        return {"id": r["id"], "name": r["name"], "level": r["level"], "link": link_for(r["link_token"])}

    @app.get("/api/v1/ping")
    @api_auth
    def api_ping():
        return jsonify(ok=True, name=g.tutor["name"])

    @app.get("/api/v1/students")
    @api_auth
    def api_students():
        rows = many("SELECT * FROM students WHERE tutor_id=? ORDER BY name", (g.tutor["id"],))
        return jsonify(students=[student_json(r) for r in rows])

    @app.post("/api/v1/students")
    @api_auth
    def api_add_student():
        try:
            name, level = validate.clean_student(body())
            sid = run("INSERT INTO students(tutor_id,name,level,link_token,created) VALUES(?,?,?,?,?)",
                      (g.tutor["id"], name, level, security.new_link_token(), _utc_now())).lastrowid
        except ValueError as e:
            return jerr(str(e))
        except sqlite3.IntegrityError:
            return jerr("A student with that name already exists.", 409)
        return jsonify(student_json(one("SELECT * FROM students WHERE id=?", (sid,)))), 201

    def own_student(sid):
        return one("SELECT * FROM students WHERE id=? AND tutor_id=?", (sid, g.tutor["id"]))

    @app.delete("/api/v1/students/<int:sid>")
    @api_auth
    def api_delete_student(sid):
        if not own_student(sid):
            return jerr("Student not found.", 404)
        run("DELETE FROM students WHERE id=?", (sid,))
        return jsonify(ok=True)

    @app.post("/api/v1/students/<int:sid>/new-link")
    @api_auth
    def api_new_link(sid):
        if not own_student(sid):
            return jerr("Student not found.", 404)
        run("UPDATE students SET link_token=? WHERE id=?", (security.new_link_token(), sid))
        return jsonify(student_json(own_student(sid)))

    @app.post("/api/v1/assignments")
    @api_auth
    def api_assign():
        try:
            d = validate.clean_assignment(body())
        except ValueError as e:
            return jerr(str(e))
        marks = ",".join("?" * len(d["student_ids"]))
        found = {r["id"] for r in many(
            f"SELECT id FROM students WHERE tutor_id=? AND id IN ({marks})",
            (g.tutor["id"], *d["student_ids"]))}
        missing = [i for i in d["student_ids"] if i not in found]
        if missing:
            return jerr(f"Unknown student id(s): {missing}", 404)
        out = []
        for sid in d["student_ids"]:
            aid = conn().execute(
                "INSERT INTO assignments(tutor_id,student_id,title,subject,due,questions,mcq_key,created) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (g.tutor["id"], sid, d["title"], d["subject"], d["due"],
                 json.dumps(d["questions"]), json.dumps(d["mcq_key"]), _utc_now())).lastrowid
            out.append({"id": aid, "student_id": sid})
        conn().commit()
        return jsonify(assignments=out), 201

    @app.delete("/api/v1/assignments/<int:aid>")
    @api_auth
    def api_withdraw(aid):
        cur = run("DELETE FROM assignments WHERE id=? AND tutor_id=?", (aid, g.tutor["id"]))
        return (jsonify(ok=True) if cur.rowcount else jerr("Assignment not found.", 404))

    @app.get("/api/v1/submissions")
    @api_auth
    def api_submissions():
        rows = many(
            "SELECT a.*, s.name AS student_name FROM assignments a JOIN students s ON s.id=a.student_id "
            "WHERE a.tutor_id=? AND a.status='submitted' ORDER BY a.submitted_at", (g.tutor["id"],))
        return jsonify(submissions=[{
            "id": r["id"], "student_id": r["student_id"], "student_name": r["student_name"],
            "title": r["title"], "subject": r["subject"], "due": r["due"],
            "submitted_at": r["submitted_at"], "late": bool(r["late"]),
            "answers": json.loads(r["answers"] or "{}"),
            "mcq_score": r["mcq_score"], "mcq_total": r["mcq_total"]} for r in rows])

    @app.post("/api/v1/assignments/<int:aid>/feedback")
    @api_auth
    def api_feedback(aid):
        try:
            score, total, comment = validate.clean_feedback(body())
        except ValueError as e:
            return jerr(str(e))
        row = one("SELECT status FROM assignments WHERE id=? AND tutor_id=?", (aid, g.tutor["id"]))
        if not row:
            return jerr("Assignment not found.", 404)
        if row["status"] == "assigned":
            return jerr("The student hasn't submitted this yet.", 409)
        run("UPDATE assignments SET status='marked', score=?, total=?, comment=?, marked_at=? WHERE id=?",
            (score, total, comment, _utc_now(), aid))
        return jsonify(ok=True)

    return app


# ---------------- command line ----------------
def _cli(argv):
    import getpass
    cmd = argv[1] if len(argv) > 1 else "run"
    app = create_app()
    if cmd == "purge":
        print(f"Deleted {app.purge()} old assignment(s).")
    elif cmd == "reset-password":
        if len(argv) < 3:
            sys.exit("usage: python -m portal.server reset-password EMAIL")
        pw = getpass.getpass("New password (min 8 chars): ")
        if len(pw) < 8:
            sys.exit("Too short.")
        c = dbmod.connect(os.getenv("PORTAL_DB", "portal.db"))
        n = c.execute("UPDATE tutors SET pw_hash=? WHERE email=?",
                      (security.hash_password(pw), argv[2].strip().lower())).rowcount
        c.commit()
        print("Password updated." if n else "No account with that email.")
    elif cmd == "run":
        app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
    else:
        sys.exit("commands: run | purge | reset-password EMAIL")


if __name__ == "__main__":
    _cli(sys.argv)
