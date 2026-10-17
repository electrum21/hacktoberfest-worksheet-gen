"""Baseline (plain prompt) vs improved (style guide + structure checks) on short-answer questions."""
import csv, sys, time
import engine
from config import MODEL

TOPICS = {
    "PSLE Math": ["Ratio", "Fractions", "Average", "Percentage"],
    "PSLE Science": ["Water cycle", "Heat energy"],
    "Sec E-Math (O-Level)": ["Quadratic equations and functions", "Trigonometry"],
}
N = 5
MODES = {"baseline": True, "improved": False}


def run(model):
    rows = []
    for mode, is_base in MODES.items():
        for subject, topics in TOPICS.items():
            for topic in topics:
                t0 = time.time()
                try:
                    qs = engine.generate_batch(subject, topic, "short", N, "medium", model=model,
                                               baseline=is_base, retries=0)
                except Exception:
                    rows.append(dict(mode=mode, subject=subject, topic=topic, valid=0, n=0,
                                     consistent=0, dups=0, secs=round(time.time() - t0, 1)))
                    continue
                ws = engine.Worksheet(questions=qs)
                ok = [engine.check(q, model) for q in qs]
                rows.append(dict(mode=mode, subject=subject, topic=topic, valid=1, n=len(qs),
                                 consistent=sum(1 for x in ok if x), dups=engine.duplicate_pairs(ws),
                                 secs=round(time.time() - t0, 1)))
                print(rows[-1], flush=True)
    return rows


def summarise(rows):
    for mode in MODES:
        r = [x for x in rows if x["mode"] == mode]
        tot_q = sum(x["n"] for x in r) or 1
        print(f"\n{mode.upper()}")
        print(f"  valid schema:      {sum(x['valid'] for x in r)}/{len(r)} runs")
        print(f"  self-consistent:   {sum(x['consistent'] for x in r)}/{tot_q} questions "
              f"({100 * sum(x['consistent'] for x in r) / tot_q:.0f}%)")
        print(f"  near-duplicates:   {sum(x['dups'] for x in r)}")
        print(f"  avg secs/run:      {sum(x['secs'] for x in r) / len(r):.1f}")


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else MODEL
    rows = run(model)
    with open("eval_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows)
    summarise(rows)
