import re
from datetime import date, timedelta

import streamlit as st
import ollama

import engine, store, render, publish, portal_sync
from config import MODEL, HOST, PORTAL_URL, PORTAL_TOKEN
from portal_client import PortalClient, PortalError
from engine import Worksheet
from syllabus import SUBJECTS, TYPE_LABELS

st.set_page_config(page_title="Worksheet Generator", page_icon="📝", layout="wide")
store.init()

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@st.cache_data(ttl=30)
def installed_models():
    try:
        names = [m.model for m in ollama.Client(host=HOST).list().models]
        return names or [MODEL]
    except Exception:
        return [MODEL]


def badge(ok):
    if ok is True:
        return "✅ Answer cross-checked"
    if ok is False:
        return "⚠️ Blind answer disagreed. Check this one yourself."
    return "📝 Open-ended: tutor review (use the mark scheme)"


def show_html(html, height=560):
    """Embed generated HTML. st.components.v1.html is deprecated (removed after 2026-06-01), so use
    st.iframe where it exists and fall back for older Streamlit versions."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        import streamlit.components.v1 as components
        components.html(html, height=height, scrolling=True)


def get_client():
    """A portal client if the tutor has connected one, else None. Makes no network call."""
    url = store.get_setting("portal_url") or PORTAL_URL
    token = store.get_setting("portal_token") or PORTAL_TOKEN
    if not url or not token:
        return None
    try:
        return PortalClient(url, token)
    except PortalError as e:
        st.warning(str(e))
        return None


st.title("📝 Worksheet Generator for Tutors")
if get_client() is None:
    st.caption("Runs fully on your laptop. No student data leaves this machine.")
else:
    st.caption("Generation, answer keys and weak-topic profiles stay on this laptop. "
               "Only the worksheets you assign, plus students' first names and their answers, "
               "pass through your portal.")

# ================= sidebar =================
with st.sidebar:
    st.header("Worksheet")
    models = installed_models()
    model = st.selectbox("Model", models, index=models.index(MODEL) if MODEL in models else 0)
    subject = st.selectbox("Subject", list(SUBJECTS))
    cfg = SUBJECTS[subject]

    students = store.list_students()
    sopts = {"(no student)": None}
    for sid_, name_, lvl_ in students:
        sopts[f"{name_} ({lvl_})" if lvl_ else name_] = sid_
    student_label = st.selectbox("Student", list(sopts))
    student_id = sopts[student_label]
    student_name = "" if student_id is None else next(n for i, n, _ in students if i == student_id)

    weak = store.weak_topics(student_id, subject) if student_id else []
    use_weak = bool(weak) and st.checkbox(f"Target weak topics: {', '.join(weak)}", value=True)

    topics = st.multiselect("Topics", cfg["topics"], default=cfg["topics"][:1],
                            key=f"topics_{subject}", disabled=use_weak)
    custom = st.text_input("Extra topic (optional)", disabled=use_weak).replace("|", " ").strip()
    qtypes = st.multiselect("Question types", list(TYPE_LABELS), default=cfg["default_types"],
                            format_func=TYPE_LABELS.get, key=f"types_{subject}")
    n = st.slider("Number of questions", 3, 20, 8)
    diff = st.select_slider("Difficulty", ["easy", "medium", "hard", "mixed"], "medium")
    do_verify = st.toggle("Cross-check answers", True,
                          help="Re-solves each checkable question blind and flags disagreements.")
    do_fix = st.toggle("Auto-replace flagged questions", True, disabled=not do_verify)
    tutor = st.text_input("Tutor / centre name (shown on worksheet)", "")

    chosen_topics = weak if use_weak else (topics + ([custom] if custom else []))
    ready = bool(chosen_topics and qtypes)
    if not ready:
        st.warning("Pick at least one topic and one question type.")
    go = st.button("Generate worksheet", type="primary", use_container_width=True, disabled=not ready)

tab_gen, tab_stu, tab_hist, tab_inbox, tab_portal = st.tabs(
    ["Generate", "Students", "History", "Inbox", "Portal"])

# ================= generate =================
if go:
    try:
        prog = st.progress(0.0, text="Writing questions")
        ws = engine.generate(
            subject, chosen_topics, qtypes, n, diff, model=model,
            progress=lambda i, t, lab: prog.progress(0.5 * i / t if do_verify else i / t,
                                                     text=f"Writing: {lab}"))
        ok = [None] * len(ws.questions)
        if do_verify:
            ok = engine.verify(ws, model, progress=lambda i, t, lab: prog.progress(
                0.5 + 0.4 * i / t, text=f"Cross-checking {lab}"))
            if do_fix and False in ok:
                prog.progress(0.95, text=f"Replacing {ok.count(False)} flagged question(s)")
                ws, ok = engine.auto_fix(ws, ok, subject, diff, model)
                if False in ok:
                    st.warning(
                        f"{ok.count(False)} flagged question(s) could not be replaced. "
                        "Review them manually or generate the worksheet again."
                    )
        prog.empty()
        st.session_state["ws"], st.session_state["ok"] = ws, ok
        st.session_state["meta"] = dict(subject=subject, topics=chosen_topics, diff=diff, model=model,
                                        verified=do_verify, student_id=student_id,
                                        student_name=student_name, tutor=tutor, ws_id=None)
        if len(ws.questions) < n:
            st.session_state["warn"] = (f"Only {len(ws.questions)} of {n} questions passed the "
                                        "structure checks. Generate again or use a larger model.")
        else:
            st.session_state.pop("warn", None)
    except Exception as e:
        st.error(f"Generation failed: {e}")
        st.info("Is Ollama running? Try `ollama serve`, and check that the model is pulled.")

with tab_gen:
    if "ws" not in st.session_state:
        st.info("Pick a subject, topics and question types in the sidebar, then hit Generate.")
    else:
        ws: Worksheet = st.session_state["ws"]
        ok = st.session_state["ok"]
        meta = st.session_state["meta"]
        topics_label = " | ".join(meta["topics"])
        if st.session_state.get("warn"):
            st.warning(st.session_state["warn"])

        checked = [x for x in ok if x is not None]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Questions", len(ws.questions))
        c2.metric("Total marks", sum(q.marks for q in ws.questions))
        c3.metric("Cross-checked OK", f"{sum(1 for x in checked if x)}/{len(checked)}" if meta["verified"] else "off")
        c4.metric("Near-duplicates", engine.duplicate_pairs(ws))

        for i, q in enumerate(ws.questions):
            with st.container(border=True):
                st.markdown(f"**Q{i+1}.** {q.question}  \n*[{q.marks} mark(s) · {TYPE_LABELS.get(q.qtype, q.qtype)} · {q.topic}]*")
                if q.qtype == "mcq":
                    for letter, o in zip("ABCD", q.options):
                        st.write(f"{letter}. {o}")
                if meta["verified"]:
                    st.caption(badge(ok[i]))
                with st.expander("Worked solution and mark scheme"):
                    st.write(q.worked_solution)
                    for m in q.mark_scheme:
                        st.write(f"- {m}")
                    st.write(f"**Answer:** {q.final_answer}")
                if st.button("🔄 Replace this question", key=f"regen{i}"):
                    try:
                        with st.spinner("Writing a replacement..."):
                            ws.questions[i], ok[i] = engine.regenerate_one(
                                ws, i, meta["subject"], meta["diff"], meta["model"])
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not replace: {e}")

        args = (ws, meta["subject"], topics_label, meta["diff"], meta["tutor"], meta["student_name"])
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{meta['subject']}-{meta['topics'][0]}")[:60]
        d1, d2, d3 = st.columns(3)
        d1.download_button("⬇️ Word (.docx)", render.to_docx(*args), f"{base}.docx", DOCX_MIME,
                           use_container_width=True)
        d2.download_button("⬇️ Printable HTML", render.to_html(*args), f"{base}.html", "text/html",
                           use_container_width=True)
        if d3.button("💾 Save to history", use_container_width=True):
            meta["ws_id"] = store.save(meta["subject"], topics_label, meta["diff"], meta["model"],
                                       ws.model_dump_json(), meta["student_id"])
            st.success("Saved.")

        # ---- preview, then assign ----
        st.divider()
        st.subheader("Preview and assign")
        sheet_title = f"{meta['subject']}: {topics_label}"
        view = st.radio("Preview as", ["Student", "Tutor (with answers)"], horizontal=True, key="preview_mode")
        try:
            if view == "Student":
                show_html(publish.student_preview_html(ws, sheet_title, meta["subject"]))
            else:
                show_html(render.to_html(ws, meta["subject"], topics_label, meta["diff"],
                                         meta["tutor"], ""))
        except ValueError as e:
            st.error(str(e))

        client = get_client()
        roster = store.list_students()
        if client is None:
            st.info("To send this to students online, connect a portal in the Portal tab. "
                    "Printing and Word export work without one.")
        elif not roster:
            st.caption("Add students in the Students tab first.")
        else:
            names = {i: (f"{n} ({l})" if l else n) for i, n, l in roster}
            with st.form("assign_form"):
                picks = st.multiselect("Assign to", list(names), format_func=names.get, key="assign_picks")
                a_title = st.text_input("Title the student sees", value=sheet_title)
                use_due = st.checkbox("Set a due date", value=True)
                due_day = st.date_input("Due date", value=date.today() + timedelta(days=7))
                if st.form_submit_button("Assign to selected students", type="primary"):
                    try:
                        publish.student_payload(ws)  # fail early on a malformed question
                        if not picks:
                            raise ValueError("Choose at least one student.")
                        portal_sync.link_students(client)
                        if not meta.get("ws_id"):
                            meta["ws_id"] = store.save(meta["subject"], topics_label, meta["diff"],
                                                       meta["model"], ws.model_dump_json(),
                                                       meta["student_id"])
                        portal_sync.assign(client, ws, meta["ws_id"], picks, a_title.strip() or sheet_title,
                                           meta["subject"], str(due_day) if use_due else None)
                        st.success(f"Assigned to {len(picks)} student(s). Their links are in the Portal tab.")
                    except (ValueError, PortalError) as e:
                        st.error(str(e))

        if meta.get("ws_id") and meta.get("student_id"):
            with st.expander(f"Record results for {meta['student_name']} (builds their weak-topic profile)"):
                with st.form("results_form"):
                    wrongs = [st.checkbox(f"Q{i+1} wrong ({q.topic or 'General'})",
                                          key=f"wrong{meta['ws_id']}_{i}")
                              for i, q in enumerate(ws.questions)]
                    if st.form_submit_button("Save results"):
                        store.record_results(meta["student_id"], meta["ws_id"], meta["subject"],
                                             [(q.topic or "General", not w)
                                              for q, w in zip(ws.questions, wrongs)])
                        st.success("Results saved. Weak topics will be offered next time.")
        elif meta.get("student_id") and not meta.get("ws_id"):
            st.caption("Save this worksheet to history to record the student's results.")

# ================= students =================
with tab_stu:
    with st.form("add_student", clear_on_submit=True):
        a, b = st.columns(2)
        new_name = a.text_input("Student name")
        new_level = b.text_input("Level (e.g. P6, Sec 3)")
        if st.form_submit_button("Add student"):
            try:
                store.add_student(new_name, new_level)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    for sid_, name_, lvl_ in store.list_students():
        with st.container(border=True):
            h1, h2 = st.columns([6, 1])
            h1.markdown(f"**{name_}** {('· ' + lvl_) if lvl_ else ''}")
            if h2.button("Delete", key=f"delstu{sid_}"):
                pid_, cl_ = store.portal_student_id(sid_), get_client()
                if pid_ is not None and cl_ is not None:
                    try:  # remove their data from the portal too
                        cl_.delete_student(pid_)
                    except PortalError as e:
                        st.warning(f"Removed locally, but couldn't remove from the portal: {e}")
                store.delete_student(sid_)
                st.rerun()
            stats = store.topic_stats(sid_)
            if not stats:
                st.caption("No results recorded yet.")
            else:
                st.dataframe(
                    [{"Subject": s, "Topic": t, "Attempted": a, "Missed": m,
                      "Miss rate": f"{100 * m / a:.0f}%"} for s, t, a, m in stats],
                    use_container_width=True, hide_index=True)

# ================= history =================
with tab_hist:
    rows = store.list_all()
    if not rows:
        st.write("Nothing saved yet.")
    for wid, created, subj, top, dif, stu in rows:
        a, b, c = st.columns([6, 1, 1])
        a.write(f"**{subj}**: {top} ({dif}){' · ' + stu if stu else ''} · {created}")
        if b.button("Open", key=f"open{wid}"):
            s, t, d, mdl, data, sid_ = store.load(wid)
            loaded = Worksheet.model_validate_json(data)
            sname = next((n for i, n, _ in store.list_students() if i == sid_), "")
            st.session_state.update(
                ws=loaded, ok=[None] * len(loaded.questions),
                meta=dict(subject=s, topics=t.split(" | "), diff=d, model=mdl, verified=False,
                          student_id=sid_, student_name=sname, tutor="", ws_id=wid))
            st.session_state.pop("warn", None)
            st.rerun()
        if c.button("Delete", key=f"del{wid}"):
            store.delete(wid)
            st.rerun()


# ================= inbox =================
with tab_inbox:
    client = get_client()
    if client is None:
        st.info("Connect a portal in the Portal tab to receive students' answers here.")
    else:
        if st.button("Check for submissions", key="inbox_refresh"):
            try:
                st.session_state["inbox"] = portal_sync.inbox(client)
            except PortalError as e:
                st.error(str(e))
        if "inbox" in st.session_state:
            items, unmatched = st.session_state["inbox"]
            if not items and not unmatched:
                st.success("Nothing waiting to be marked.")
            for item in items:
                aid = item["aid"]
                with st.container(border=True):
                    st.markdown(f"**{item['student_name']}** · {item['title']}"
                                f"{'  ·  ⏰ late' if item['late'] else ''}")
                    st.caption(f"Multiple choice marked automatically: {item['mcq_score']}/{item['mcq_total']}. "
                               "You mark the rest below. Suggested marks for short answers are only suggestions.")
                    with st.form(f"mark_{aid}"):
                        awarded = []
                        for i, q in enumerate(item["questions"]):
                            given = item["answers"].get(str(i), "")
                            st.markdown(f"**Q{i+1}.** {q['question']}")
                            st.write(f"Student answered: {given or '(blank)'}")
                            st.caption(f"Expected: {q['final_answer']}"
                                       + ("  |  " + "; ".join(q["mark_scheme"]) if q.get("mark_scheme") else ""))
                            if q["qtype"] == "mcq":
                                default = q["marks"] if given.strip().upper() == q["final_answer"].strip().upper() else 0
                            elif q["qtype"] == "short":
                                default = q["marks"] if given and engine.same_answer(given, q["final_answer"]) else 0
                            else:
                                default = 0
                            awarded.append(st.number_input(f"Q{i+1} marks (out of {q['marks']})", 0, q["marks"],
                                                           default, key=f"m{aid}_{i}"))
                        comment = st.text_input("Comment for the student (optional)", key=f"c{aid}")
                        if st.form_submit_button("Send marks to student", type="primary"):
                            try:
                                got, out_of = portal_sync.finish(client, item, awarded, comment.strip())
                                st.session_state["inbox"] = (
                                    [x for x in items if x["aid"] != aid], unmatched)
                                st.session_state["flash"] = (f"Sent {got}/{out_of} to {item['student_name']}. "
                                                             "Topic results saved to their local profile.")
                                st.rerun()
                            except (ValueError, PortalError) as e:
                                st.error(str(e))
            for sub in unmatched:
                with st.container(border=True):
                    st.warning(f"{sub['student_name']} submitted \"{sub['title']}\", but that worksheet is no longer "
                               "in this app's history, so it can't be marked here.")
                    if st.button("Discard it", key=f"discard{sub['id']}"):
                        try:
                            client.withdraw(sub["id"])
                            st.session_state["inbox"] = (items, [x for x in unmatched if x["id"] != sub["id"]])
                            st.rerun()
                        except PortalError as e:
                            st.error(str(e))
        if st.session_state.get("flash"):
            st.success(st.session_state.pop("flash"))

        with st.expander("Everything you've assigned"):
            pubs = store.list_published()
            if not pubs:
                st.write("Nothing assigned yet.")
            for pid_, title_, status_, created_, sname_ in pubs:
                a, b = st.columns([6, 1])
                a.write(f"**{title_}** · {sname_ or 'removed student'} · "
                        f"{'marked' if status_ == 'marked' else 'not marked yet'} · {created_}")
                if status_ != "marked" and b.button("Withdraw", key=f"wd{pid_}"):
                    try:
                        client.withdraw(pid_)
                        store.delete_published(pid_)
                        st.rerun()
                    except PortalError as e:
                        st.error(str(e))

# ================= portal settings =================
with tab_portal:
    st.write("Connect this app to your portal so you can assign worksheets and collect answers. "
             "Create a portal account, then copy the address and token from its dashboard. "
             "Everything here is optional: printing and Word export work without a portal.")
    saved_url = store.get_setting("portal_url") or PORTAL_URL
    p_url = st.text_input("Portal address", value=saved_url, placeholder="https://your-portal.example.com")
    p_token = st.text_input("API token", value=store.get_setting("portal_token") or PORTAL_TOKEN, type="password")
    if st.button("Save and test connection"):
        try:
            info = PortalClient(p_url, p_token).ping()
            if saved_url and p_url.strip().rstrip("/") != saved_url.rstrip("/"):
                store.clear_portal_links()  # ids from the old portal mean nothing on the new one
            store.set_setting("portal_url", p_url.strip().rstrip("/"))
            store.set_setting("portal_token", p_token.strip())
            st.success(f"Connected as {info['name']}.")
        except PortalError as e:
            st.error(str(e))
    st.caption("The token is stored in this app's local database on this machine.")

    client = get_client()
    if client is not None:
        st.subheader("Student links")
        st.caption("Send each link privately, for example to the parent. Anyone with a link can open that student's worksheets.")
        if st.button("Link my students to the portal"):
            try:
                r = portal_sync.link_students(client)
                st.success(f"Done. {r['created']} added to the portal, {r['linked']} matched by name.")
            except PortalError as e:
                st.error(str(e))
        try:
            links = portal_sync.student_links(client)
            names = {i: n for i, n, _ in store.list_students()}
            for lid, link in links.items():
                st.write(names.get(lid, "?"))
                st.code(link, language=None)
            if not links:
                st.write("No students linked yet.")
        except PortalError as e:
            st.error(str(e))
