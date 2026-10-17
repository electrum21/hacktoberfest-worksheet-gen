"""Glue between the local database and the hosted portal.

Weak-topic profiles, mark schemes and answer keys never leave this machine: results are written
to the local store, and only a score and comment go back to the portal.
"""
import json

import publish
import store


def link_students(client) -> dict:
    """Make sure every local student has a portal record. Matches by name first, so linking
    twice (or from a second laptop) doesn't create duplicates."""
    remote = {s["name"]: s for s in client.students()}
    linked = created = 0
    for sid, name, level in store.list_students():
        if store.portal_student_id(sid) is not None and any(
                s["id"] == store.portal_student_id(sid) for s in remote.values()):
            continue
        rec = remote.get(name)
        if rec is None:
            rec = client.add_student(name, level)
            created += 1
        else:
            linked += 1
        store.set_portal_student(sid, rec["id"])
    return {"linked": linked, "created": created}


def student_links(client) -> dict:
    """{local student id: private link}"""
    by_portal_id = {s["id"]: s["link"] for s in client.students()}
    return {lid: by_portal_id[pid] for lid, pid in store.linked_map().items() if pid in by_portal_id}


def assign(client, ws, worksheet_id: int, local_student_ids, title: str, subject: str, due=None) -> list[int]:
    """Send a student-safe copy of `ws` to each chosen student. Returns portal assignment ids."""
    if not local_student_ids:
        raise ValueError("Choose at least one student.")
    links = store.linked_map()
    missing = [i for i in local_student_ids if i not in links]
    if missing:
        raise ValueError("Some students aren't linked to the portal yet.")
    questions, key = publish.student_payload(ws)
    created = client.assign(title, subject, due, [links[i] for i in local_student_ids], questions, key)
    local_by_portal = {links[i]: i for i in local_student_ids}
    ids = []
    for row in created:
        store.record_published(worksheet_id, row["id"], local_by_portal[row["student_id"]], title)
        ids.append(row["id"])
    return ids


def inbox(client):
    """Fetch submissions and match them to local worksheets.
    Returns (items, unmatched). `unmatched` are submissions whose worksheet was deleted here."""
    items, unmatched = [], []
    for sub in client.submissions():
        pub = store.get_published(sub["id"])
        loaded = store.load(pub[1]) if pub else None
        if not pub or not loaded:
            unmatched.append(sub)
            continue
        subject, _topic, _diff, _model, data, _sid = loaded
        items.append({**sub, "aid": sub["id"], "worksheet_id": pub[1], "student_id": pub[3],
                      "subject": subject, "questions": json.loads(data)["questions"]})
    return items, unmatched


def finish(client, item: dict, awarded: list[int], comment: str = ""):
    """Send the score to the student, then record per-topic results locally.
    `awarded[i]` is the marks given for question i."""
    qs = item["questions"]
    if len(awarded) != len(qs):
        raise ValueError("Marks don't match the worksheet.")
    for a, q in zip(awarded, qs):
        if not 0 <= a <= q["marks"]:
            raise ValueError("A mark is outside the allowed range.")
    score, total = sum(awarded), sum(q["marks"] for q in qs)
    client.feedback(item["aid"], score, total, comment)          # if this fails, nothing is recorded
    store.record_results(item["student_id"], item["worksheet_id"], item["subject"],
                         [(q.get("topic") or "General", a == q["marks"]) for a, q in zip(awarded, qs)])
    store.mark_published(item["aid"], "marked")
    return score, total
