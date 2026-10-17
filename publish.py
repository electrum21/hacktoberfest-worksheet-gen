"""Build what gets sent to the hosted portal.

The payload is built from an allow-list, field by field. final_answer, worked_solution and
mark_scheme are never copied, and the portal independently rejects any question that carries
them. The only answer data that leaves the laptop is the A-D letter for each multiple choice
question, so the portal can mark those instantly.

No engine/pydantic imports here: works on any object with a `.questions` list.
"""
from portal import sheetview


def student_payload(ws) -> tuple[list[dict], dict[str, str]]:
    """Returns (student-safe questions, {question index: correct letter} for MCQs only)."""
    questions, key = [], {}
    for i, q in enumerate(ws.questions):
        item = {"qtype": q.qtype, "question": q.question, "marks": q.marks}
        if q.qtype == "mcq":
            letter = (q.final_answer or "").strip().upper()[:1]
            if letter not in tuple("ABCD") or len(q.options) != 4:
                raise ValueError(f"Question {i + 1} is a malformed multiple choice question. "
                                 "Replace it before assigning.")
            item["options"] = list(q.options)
            key[str(i)] = letter
        questions.append(item)
    return questions, key


def student_preview_html(ws, title: str, subject: str = "") -> str:
    """The exact student page (same renderer as the portal), with nothing sent anywhere."""
    questions, _ = student_payload(ws)
    return sheetview.preview_page(title, questions, subject)
