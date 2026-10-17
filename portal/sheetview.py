"""Student worksheet markup. Pure stdlib.

Used by the hosted portal AND by the tutor's local preview, so the preview is the
same renderer the student gets, not a lookalike.
"""
from html import escape
from pathlib import Path

LETTERS = "ABCD"
_STATIC = Path(__file__).with_name("static")


def _br(s: str) -> str:
    return escape(s).replace("\n", "<br>")


def _marks(n: int) -> str:
    return f"{n} mark" if n == 1 else f"{n} marks"


def sheet_fragment(questions, answers=None, readonly=False) -> str:
    """The questions with answer inputs. `questions` are student-safe dicts."""
    answers = answers or {}
    dis = " disabled" if readonly else ""
    out = ['<ol class="sheet">']
    for i, q in enumerate(questions):
        n = i + 1
        given = str(answers.get(str(i), ""))
        if q["qtype"] == "mcq":
            opts = "".join(
                f'<label class="opt"><input type="radio" name="q{i}" value="{letter}"'
                f'{" checked" if given == letter else ""}{dis}>'
                f'<span class="opt-letter" aria-hidden="true">{letter}</span>'
                f'<span class="opt-text">{escape(text)}</span></label>'
                for letter, text in zip(LETTERS, q["options"]))
            body = (f'<fieldset class="opts"><legend class="sr-only">Answer for question {n}'
                    f'</legend>{opts}</fieldset>')
        elif q["qtype"] == "short":
            body = (f'<input class="ans" type="text" name="q{i}" maxlength="500" '
                    f'autocomplete="off" aria-label="Answer for question {n}" '
                    f'value="{escape(given)}"{dis}>')
        else:
            body = (f'<textarea class="ans" name="q{i}" rows="6" maxlength="2000" '
                    f'aria-label="Answer for question {n}"{dis}>{escape(given)}</textarea>')
        out.append(
            f'<li class="q"><span class="q-no" aria-hidden="true">{n}</span>'
            f'<div class="q-body"><p class="q-text">{_br(q["question"])}</p>'
            f'<p class="q-marks">{_marks(q["marks"])}</p>{body}</div></li>')
    out.append("</ol>")
    return "".join(out)


def preview_page(title: str, questions, subject: str = "") -> str:
    """A standalone page (CSS and JS inlined) for the tutor's local preview.
    Inputs work so the tutor can try the sheet, but nothing is sent anywhere."""
    css = (_STATIC / "portal.css").read_text(encoding="utf-8")
    js = (_STATIC / "portal.js").read_text(encoding="utf-8")
    total = sum(q["marks"] for q in questions)
    sub = f"{escape(subject)} · " if subject else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Preview: {escape(title)}</title><style>{css}</style></head>
<body class="student"><main class="wrap">
<p class="preview-note">Preview. This is what your student sees. Nothing you type here is saved or sent.</p>
<article class="paper">
<header class="paper-head"><h1>{escape(title)}</h1>
<p class="muted">{sub}{len(questions)} questions · {_marks(total)}</p></header>
<form data-sheet onsubmit="return false">
{sheet_fragment(questions)}
<div class="submit-bar"><span class="progress" data-progress></span>
<button class="btn" type="button" disabled>Submit (turned off in preview)</button></div>
</form></article></main><script>{js}</script></body></html>"""
