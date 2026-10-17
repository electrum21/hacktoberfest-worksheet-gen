from syllabus import SUBJECTS

SYSTEM = """You write practice worksheets for private tutors in Singapore.
Rules:
- Every question has exactly one unambiguous correct answer or marking scheme.
- worked_solution shows the steps; final_answer is short.
- For numeric answers, final_answer contains only the answer, e.g. "$42.50" or "3/4".
- Vary the structure and context of questions; no near-duplicates.
- Do not refer to diagrams, images or passages you cannot show."""

BASELINE_SYSTEM = "You write practice questions with answers."

TYPE_RULES = {
    "mcq": ("Each question is multiple choice with exactly 4 plausible options in `options` "
            "(no letter prefixes). `final_answer` is ONE letter: A, B, C or D. Exactly one option "
            "is correct. Set marks to 1. Leave mark_scheme empty."),
    "short": ("Each question has a single short final answer. Put the answer in `final_answer` "
              "(required, never empty). Leave `options` and `mark_scheme` empty. marks is 1 or 2."),
    "structured": ("Each question is multi-step or multi-part (use (a), (b) in the question text where "
                   "helpful) worth 2 to 5 marks. `mark_scheme` is required and must be a non-empty "
                   "JSON array of marking points, each starting with its mark, e.g. "
                   "'1m: states that ...', adding up to `marks`. `final_answer` summarises the key "
                   "final result(s)."),
}

DIFFICULTY = {
    "easy": "easy (single concept, direct application)",
    "medium": "medium (typical exam level)",
    "hard": "hard (challenging, multi-concept, like the last questions of a paper)",
    "mixed": "mixed: about 30% easy, 50% medium, 20% hard, ordered easiest to hardest",
}


def user_prompt(subject, topic, qtype, n, difficulty, avoid=None, baseline=False):
    if baseline:
        return f"Write {n} {subject} questions about {topic}."
    p = f"""Style guide: {SUBJECTS[subject]['style']}
Topic: {topic}
Question type: {TYPE_RULES[qtype]}
Difficulty: {DIFFICULTY.get(difficulty, difficulty)}
Write exactly {n} question(s)."""
    if avoid:
        p += "\n\nDo NOT repeat or closely resemble these existing questions:\n" + \
             "\n".join(f"- {q}" for q in avoid[:30])
    return p
