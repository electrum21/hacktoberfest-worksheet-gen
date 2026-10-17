# Worksheet Generator for Tutors

> Hacktoberfest Open-Source AI Challenge: Week 2 (theme: **Side Hustle**)
> Tags: `#devchallenge` `#hf26challenge`
> Primary category: **Best Use of Gemma**

A local-first practice worksheet generator for Singapore private tutors, covering PSLE and O-Level. It runs an open-weight model (Gemma) through Ollama, so the whole thing works on a tutor's laptop with no internet, no API key and no per-worksheet cost. Student names and weak topics never leave the machine, unless you choose to connect the optional portal (section 5a), in which case only first names, the worksheets you assign and the students' answers pass through it.

---

## 1. The problem and who would pay

Private tutors spend hours each week writing or hunting for syllabus-style practice questions, writing answer keys and mark schemes, and working out what each student should practise next.

- **Customer:** an independent tutor, or a small tuition centre.
- **Pain:** time spent on worksheets, the risk of a wrong answer key in front of a parent, and no easy way to target a student's weak topics.
- **Willingness to pay:** tutors already charge per hour; saving an hour a week pays for a small monthly fee. (Pricing assumption, to be validated with the first user. See section 8.)
- **Why it is a side hustle:** a narrow, finished tool for one niche, sellable as a one-off licence or a small subscription, with near-zero running cost because inference is local.

## 2. Why open innovation matters here

| Concern | Closed API approach | This project (open weights, local) |
|---|---|---|
| Student privacy | Names, levels and weak topics go to a third-party server | Nothing leaves the laptop |
| Unit economics | Cost per worksheet, scaling with usage | About zero marginal cost, so a flat low price works |
| Offline use | Needs internet | Works anywhere the tutor teaches |
| Niche tuning | Prompting only | Swap models, or fine-tune on syllabus-style questions |
| Vendor lock-in | Pricing and model changes are out of the tutor's hands | Swap the model with one env var (`WS_MODEL`) |

The open model is what makes the business model (flat price, no usage cost) and the privacy promise possible. The student profile feature in particular is only reasonable to offer because the data stays local.

## 3. Features

**Content**
- **8 subjects:** PSLE Math, PSLE Science, PSLE English, Sec E-Math, Sec A-Math, O-Level Physics, Chemistry and Biology, with about 100 syllabus topics in `syllabus.py` (easy to edit or extend).
- **3 question types:** multiple choice (4 options, one correct), short answer, and structured or open-ended questions with a **mark scheme** (marks awarded per point, examiner-style).
- **Exam-paper mode:** pick several topics and types, a difficulty (easy, medium, hard, or mixed 30/50/20), and up to 20 questions. Questions are spread across topics and ordered like a paper (MCQ, then short, then structured), with total marks and a rough suggested time.
- Custom topics for anything not on the list.

**Trust**
- **Blind cross-check.** Each checkable question is re-solved by the model without seeing the key. MCQs and short answers are always checked; structured questions are checked when the final answer is numeric. Disagreements are flagged in the UI, and open-ended questions are labelled "tutor review" instead of being passed off as verified.
- **Structure validation.** MCQs must have exactly 4 distinct options and a letter answer; structured questions must have a mark scheme. Bad output is discarded and regenerated.
- **Duplicate avoidance.** Near-duplicate questions are filtered and counted.
- **Auto-replace and per-question replace.** Flagged questions are regenerated (up to 3 verified tries).

**Students (all local)**
- Keep a roster. Tick the questions a student got wrong after marking.
- The app builds a weak-topic profile per student and subject, and **"Target weak topics"** generates the next worksheet from exactly those topics.

**Output**
- **Word (.docx)** and **printable HTML**, each with a name/date/score header, answer space, MCQ options, and a separate answer key and mark scheme page.
- Local history (SQLite): reopen, re-export or delete past worksheets.

## 4. Architecture

```
Streamlit UI (app.py)
   |
   +-- engine.py ---- Ollama (local) ---- Gemma (open weights)
   |     generate_batch -> structured JSON via pydantic schema, validate, dedupe, retry
   |     plan/generate  -> spread N questions over topics x types, paper order
   |     check/verify   -> blind re-solve, numeric-tolerant matching
   |     auto_fix       -> regenerate flagged questions
   |
   +-- syllabus.py   subjects, topics, style guides
   +-- prompts.py    system prompt, question-type rules, difficulty text
   +-- render.py     HTML and DOCX export (worksheet + answer key + mark scheme)
   +-- store.py      SQLite: worksheets, students, results, weak topics
   +-- publish.py / portal_sync.py / portal_client.py   student-safe payloads, assign, inbox (hybrid mode)
   +-- eval.py       baseline vs improved benchmark -> eval_results.csv
   +-- tests/        96 tests (mocked model, storage, rendering, headless UI, portal, full hybrid loop)

portal/  (optional hosted student portal, Flask + SQLite, no GPU; see 5a)
   +-- server.py     routes: tutor dashboard, student links, token-authenticated API
   +-- wsgi.py       gunicorn entry point      db.py / security.py / validate.py / sheetview.py
   +-- templates/, static/                     no inline script, no third-party requests
```

## 5. Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull gemma3:4b
streamlit run app.py
```

Run the tests (no Ollama needed, the model is mocked). The portal tests need Flask, so install the portal requirements too:

```bash
pip install -r requirements-portal.txt
python -m pytest -q
```

Config via environment variables:

| Var | Default | Purpose |
|---|---|---|
| `WS_MODEL` | `gemma3:4b` | Any Ollama model tag (try a larger Gemma if your hardware allows) |
| `OLLAMA_HOST` | `http://localhost:11434` | Point at another Ollama server if needed |
| `WS_DB` | `worksheets.db` | SQLite file location |
| `WS_PORTAL_URL` | unset | Portal address (optional; can also be saved in the app's Portal tab) |
| `WS_PORTAL_TOKEN` | unset | Portal API token (optional; same as above) |

## 5a. Portal (optional hybrid mode)

Tutors at big centres get a student portal for free. An independent tutor gets one here, without running a server on their laptop and without sending the worksheet-writing itself to the cloud.

**The loop:** generate and cross-check on your laptop → **preview as the student** (or as the tutor, with answers) → assign to one or more students → each student opens a private link on any phone and submits → multiple choice is marked instantly on the portal → you pull the answers into the **Inbox** tab, mark the rest against your own mark scheme, and send back a score and comment → per-topic results land in your local weak-topic profile, ready for "Target weak topics".

| Data | Stays on the laptop | Goes to the portal |
|---|---|---|
| Model, prompts, generation, cross-check | yes | no |
| Answer keys, worked solutions, mark schemes | yes | **never** (the portal rejects any question carrying them) |
| MCQ correct letter (A-D) | yes | yes, server-side only, for instant marking |
| Questions the student must answer | yes | yes (student-safe copy) |
| Student first name and level | yes | yes |
| Student answers | received into Inbox | yes, until marked and purged |
| Weak-topic profiles and results history | yes | no (only a score and comment go back) |

**Run the portal locally to try it:**

```bash
pip install -r requirements-portal.txt
PORTAL_PUBLIC_URL=http://127.0.0.1:8000 python -m portal.server run     # http://127.0.0.1:8000
```

Create a tutor account in the browser, copy the address and token from the dashboard, then paste them into the **Portal** tab of the Streamlit app (or set `WS_PORTAL_URL` and `WS_PORTAL_TOKEN`). Click "Link my students to the portal" to get each student's private link.

**Host it** (needs only Python and a persistent disk, no GPU): `docker build -t tutor-portal .`, mount a volume at `/data`, and set `PORTAL_PUBLIC_URL` to your https address. The laptop app refuses plain `http://` portal addresses except on localhost. Any host that runs a container or gunicorn works.

| Portal env var | Default | Purpose |
|---|---|---|
| `PORTAL_DB` | `portal.db` | SQLite file; put it on a persistent disk |
| `PORTAL_PUBLIC_URL` | (request host) | Address used in student links; an `https://` value turns on Secure cookies |
| `PORTAL_SECRET` | generated, saved next to the DB | Session signing key |
| `PORTAL_SIGNUP_CODE` | unset | If set, signup needs this invite code (recommended for a pilot) |
| `PORTAL_RETENTION_DAYS` | `180` | Deletes marked and never-submitted work after this long (`0` keeps everything) |
| `PORTAL_UTC_OFFSET_HOURS` | `8` | Due dates and displayed times (Singapore) |
| `PORTAL_TRUST_PROXY` | unset | Set to `1` only when behind one reverse proxy, so rate limits see real client IPs |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address for `python -m portal.server run` (the Docker image uses gunicorn on `0.0.0.0:8000`) |

Admin commands: `python -m portal.server purge` and `python -m portal.server reset-password EMAIL`.

**Security design:** students have no accounts, so each private link (128-bit random token) is the credential: send it privately, and use "New link" on the dashboard if it leaks. Passwords use scrypt, API tokens are stored as hashes and shown once, forms carry CSRF tokens, pages send a strict Content-Security-Policy with no inline script and no third-party requests, and every query is scoped to the owning tutor.

**Limits to know about**
- Students are minors. Use first names only, and check your obligations under Singapore's PDPA before running this with real students. This is not legal advice, and nothing here is a compliance certification.
- No email, so no password-reset email. Use the `reset-password` command.
- Rate limiting is per process and in memory. Fine for one small server, not for hostile traffic.
- Student answers are plain text and typed. There is no photo or handwriting upload.
- One tutor account per tutor or centre; no sub-accounts for several tutors sharing a centre.
- The Streamlit side of hybrid mode (assign, Portal tab links, Inbox, marking) is covered by headless tests against a real local portal (`tests/test_app_portal.py`). It has also been exercised end-to-end against a live portal server and a live gemma3:4b model (not mocked): signup, linking a student, assigning a worksheet, a simulated student submitting answers, instant MCQ marking, pulling the Inbox, marking against the real mark scheme, and the weak-topic profile update all worked correctly, and no answer key, worked solution or mark scheme left the laptop. What that run did *not* cover is the visual side: nobody has clicked through the real UI in a browser, so the iframe worksheet preview and the page layout haven't been eyeballed. Do a visual click-through before relying on the layout.

## 6. Evidence: baseline vs improved

```bash
python eval.py gemma3:4b
```

Generates short-answer questions across several topics in two modes and writes `eval_results.csv`:

- **Baseline:** plain prompt ("write N questions about X"), no style guide, no structure checks.
- **Improved:** syllabus style guide, structured output, validation, duplicate avoidance.

Both are scored with the same blind cross-check. Metrics: valid-output rate, self-consistency rate, near-duplicate count, seconds per run.

**Results (fill in after running; do not publish placeholders):**

| Mode | Valid schema | Self-consistent | Near-duplicates | Avg secs/run |
|---|---|---|---|---|
| Baseline | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| Improved | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

**Limitation to state in the post:** self-consistency is not correctness. A model can be consistently wrong. Hand-check a sample (e.g. 10 questions per mode) and report the true correctness rate next to the automated one. Optionally have a tutor rate the sample blind (1-5 for syllabus fit).

## 7. Testing

96 automated tests cover answer matching, MCQ/structured validation, planning, generation retry and filtering, verification modes, auto-fix, duplicate detection, SQLite storage (students, results, weak topics, deletes), HTML escaping, DOCX round-trip, and a headless UI run through every subject and the full student flow (`test_core.py` and `test_app.py`, 27 tests). The model is mocked, so they run in seconds. Portal mode adds `tests/test_portal.py` (accounts, API validation, tutor isolation, answer-key leakage, student flow, retention), `tests/test_hybrid.py` (the full laptop → portal → student → marking loop against a real server on localhost) and `tests/test_app_portal.py` (the Streamlit assign, Portal tab and Inbox flow against a real local portal). Run them without pytest with `python -m unittest tests.test_portal tests.test_hybrid`. The tests do **not** measure real model quality; that is what `eval.py` and a human check are for.

Beyond the mocked suite, a full session has been run against the real model and a real local portal server: generate → blind cross-check → auto-fix → export → save, then the complete hybrid loop (tutor signup, student linking, assign, student submit, instant MCQ marking, Inbox, mark, weak-topic update) over real HTTP. It passed end-to-end and surfaced three real, reproducible issues against the live model — an MCQ option-prefix edge case, missing worked solutions, and a transient generation error discarding an otherwise-good worksheet — all now fixed and covered by regression tests (see section 10).

## 8. First user (bonus points)

No real-user pilot has been completed before submission. The generator has been tested end-to-end by the author using PSLE Math and A-Math subjects, covering all three question types, the export flows and the weak-topic targeting loop. A pilot with an independent tutor is the immediate next step after submission.

## 9. Hacktoberfest checklist

**Submission**
- [ ] Post published on DEV using the challenge submission template (adds `#devchallenge` and `#hf26challenge`)
- [ ] Post states what was built and who would pay for it
- [ ] Demo included (screen recording or screenshots: generate, flag, export, weak-topic targeting)
- [ ] "Why open innovation matters" section (see section 2)
- [ ] First-user story (see section 8), or an honest note that it is not done yet
- [ ] Repo link included
- [ ] Submitted before **October 18, 2026**

**Judging criteria mapping**

| Criterion | How this project addresses it |
|---|---|
| Writing quality (weighted most) | Post built around a real user's reaction and honest eval numbers, including limitations |
| Relevance to prompt/theme | Open-weight model at the core, narrow niche, a real paying customer type |
| Creativity | Blind cross-check as a trust feature; local student profiles that would be risky on a cloud API |
| Technical execution | Schema-validated output, retry and dedupe logic, 96 tests, reproducible eval |
| Partner technology (optional) | See below |

**Partner categories**

| Category | Status | Notes |
|---|---|---|
| Best Use of Gemma | **Targeted** | Gemma runs locally via Ollama; the whole pipeline depends on it |
| Best Use of a .tech Domain | Optional | Only if a live demo is hosted on a claimed .tech domain; link it in the post |
| Best Use of Render / DigitalOcean | Optional | Only if a hosted demo is deployed there; the core product stays local-first |
| Best Use of Tinker | Stretch | Fine-tune on syllabus-style questions and show a measured improvement over the baseline. Only claim it if actually done |
| Best Use of Entire / DevRelay | Optional | Save and embed the agent session in the post |

Do not claim a partner category in the post unless the project genuinely uses that technology.

**Suggested post outline**
1. The problem (a tutor's week) and the first user
2. What I built (30-second demo)
3. Why open weights matter here (privacy, cost, offline, swappable)
4. How it works (the cross-check and the weak-topic loop, in plain language)
5. Results: baseline vs improved, with limitations
6. What the user said, and whether they'd pay
7. What I would build next

## 10. Limitations and roadmap

**Fixed since initial end-to-end testing** (all three were found by actually running the app against the real model, not guessed at — each has a regression test now):
- MCQ options numbered with digits (`1.`, `2)`) instead of letters used to leak the digit prefix into the rendered worksheet. `normalize()`'s option-prefix stripper now matches both.
- `worked_solution` was optional in the schema handed to the model, so Gemma routinely skipped it, especially on short-answer and MCQ questions — the worksheet showed only the final answer with no working. It's now a required field, same as `final_answer`, so every question carries real steps.
- A single topic/question-type batch exhausting its retries (e.g. one bad run of structured questions) used to discard the entire worksheet, including everything already generated. `generate()` now keeps whatever other groups succeeded and only warns about the shortfall.

**Known, open**
- Small models are weaker at multi-step maths and at subtle science wording; use a larger Gemma where hardware allows. Expect more flags on a 4B model: in testing, gemma3:4b's blind cross-check flagged 3-5 of 6 questions on some runs, which auto-fix then resolved.
- Open-ended and text answers cannot be auto-verified. They are labelled for tutor review and carry a mark scheme, but the mark scheme itself is model-written and should be skimmed.
- Answer matching is numeric-tolerant for numbers and exact-normalised for text, so a correct answer phrased differently can be flagged. Treat a flag as "check me", not "wrong".
- No diagrams or figures, so the prompts avoid questions that need them.
- Not yet covered: reading-comprehension passages, mother-tongue languages (Chinese, Malay, Tamil; small-model quality is a real concern), JC H2 subjects.
- Next: comprehension passages with questions, more subjects, fine-tuning on syllabus-style questions, direct PDF export, a parent-friendly progress summary.

## 11. Licence and model terms

The code in this repo is released under the [MIT Licence](LICENSE).

Check the licence terms of the model you run (Gemma has its own [terms of use](https://ai.google.dev/gemma/terms)) before selling anything built on it commercially.
