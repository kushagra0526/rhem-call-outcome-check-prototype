"""Score callcheck against synthetic calls with known outcomes.

    python evaluate.py dev        # dev phrase bank (used while building)
    python evaluate.py heldout    # eval/phrases_heldout.py (v1: first run kept in out/eval_heldout_v1.*)
    python evaluate.py heldout2   # eval/phrases_heldout2.py, committed before callcheck ran on it

Compared with two baselines:
  report   - trust the agent's own report ("complete" -> show it as done)
  keyword  - done if any business line says booked / confirmed / all set / ready
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from callcheck.calls import make_set  # noqa: E402
from callcheck.check import check  # noqa: E402

DONE = ("DONE", "DONE_CHANGED")
KW = re.compile(r"\b(booked|confirmed|all set|ready|placed|scheduled|see you)\b", re.I)


def load(which):
    if which == "dev":
        from callcheck.phrases_dev import BANK
        return make_set(BANK, n_per=4, seed0=0)
    sys.path.insert(0, str(HERE / "eval"))
    if which == "heldout2":
        from phrases_heldout2 import BANK
        return make_set(BANK, n_per=4, seed0=90_000)
    from phrases_heldout import BANK
    return make_set(BANK, n_per=4, seed0=50_000)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    calls = load(which)
    rows, conf = [], Counter()
    m = Counter()
    for call, truth in calls:
        r = check(call)
        conf[(truth["status"], r["status"])] += 1
        t_done = truth["status"] in DONE
        m["calls"] += 1
        m["truly_not_done"] += not t_done
        # a "false complete" = the family is told it's done when it isn't
        m["false_complete_report"] += (call["report"]["status"] == "complete") and not t_done
        m["false_complete_keyword"] += any(KW.search(x["text"]) for x in call["transcript"] if x["who"] == "biz") and not t_done
        m["false_complete_check"] += (r["status"] in DONE) and not t_done
        m["missed_done_check"] += t_done and r["status"] not in DONE
        m["status_exact"] += r["status"] == truth["status"]
        got_flags = {f["flag"] for f in r["flags"]}
        want_flags = set(truth["flags"])
        m["flags_planted"] += len(want_flags)
        m["flags_caught"] += len(want_flags & got_flags)
        m["flags_false"] += len(got_flags - want_flags)
        wrong_truth = set(truth["wrong_claims"])
        wrong_got = {c["claim"].split(":")[0] for c in r["claims"] if c["verdict"] != "OK"}
        m["wrong_claims_planted"] += len(wrong_truth)
        m["wrong_claims_caught"] += len(wrong_truth & wrong_got)
        m["claims_falsely_flagged"] += len(wrong_got - wrong_truth - ({"date", "time", "party", "price"} if not truth["status"] in DONE + ("NEEDS_PARENT",) else set()))
        if r["status"] != truth["status"] or got_flags != want_flags:
            rows.append({"id": call["id"], "truth": truth["status"], "got": r["status"], "reason": r["reason"],
                         "flags_truth": sorted(want_flags), "flags_got": sorted(got_flags),
                         "lines": [f"{x['i']} {x['who']}: {x['text']}  {x['acts']}" for x in r["lines"]]})
    print(f"\n== {which}: {m['calls']} synthetic calls, {m['truly_not_done']} not actually done")
    print(f"   told 'done' when it wasn't:  agent report {m['false_complete_report']}  ·  keyword {m['false_complete_keyword']}  ·  callcheck {m['false_complete_check']}")
    print(f"   real bookings callcheck missed: {m['missed_done_check']}")
    print(f"   exact status: {m['status_exact']}/{m['calls']}")
    print(f"   policy flags caught {m['flags_caught']}/{m['flags_planted']}, false {m['flags_false']}")
    print(f"   wrong report claims caught {m['wrong_claims_caught']}/{m['wrong_claims_planted']}")
    labels = ["DONE", "DONE_CHANGED", "PENDING", "NOT_DONE", "NEEDS_PARENT"]
    print("\n   truth \\ got  " + " ".join(f"{l[:9]:>10}" for l in labels))
    for a in labels:
        print(f"   {a:<12} " + " ".join(f"{conf[(a, b)]:>10}" for b in labels))
    for x in rows:
        print(f"\n   MISS {x['id']}: truth {x['truth']} {x['flags_truth']} got {x['got']} ({x['reason']}) {x['flags_got']}")
        for l in x["lines"]:
            print("      " + l)
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / f"out/eval_{which}.json").write_text(json.dumps(
        {"metrics": dict(m), "confusion": {f"{a}->{b}": v for (a, b), v in conf.items()}, "misses": rows}, indent=2))


if __name__ == "__main__":
    main()
