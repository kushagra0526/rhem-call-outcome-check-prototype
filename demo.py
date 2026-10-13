"""Six synthetic calls through callcheck -> out/report.html, out/report.json, printed summary.

    python demo.py
"""
import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from callcheck.calls import make_set  # noqa: E402
from callcheck.check import STATUS_WORD, check  # noqa: E402
from callcheck.phrases_dev import BANK  # noqa: E402

SHOW = [("restaurant", "alt_time_accepted"), ("pharmacy", "too_early"), ("restaurant", "callback"),
        ("grocery", "over_budget"), ("pharmacy", "ready_ssn"), ("appointment", "clean")]
e = html.escape
COLOR = {"DONE": "ok", "DONE_CHANGED": "warn", "PENDING": "warn", "NOT_DONE": "bad", "NEEDS_PARENT": "bad"}


def pick():
    calls = make_set(BANK, n_per=6, seed0=0)
    out = []
    for kind, scen in SHOW:
        for c, t in calls:
            if c["kind"] == kind and t["scenario"] == scen and c["report"]["status"] == "complete":
                out.append((c, t))
                break
    return out


def report_text(c):
    f = c["report"].get("fields", {})
    bits = []
    if f.get("date"):
        from datetime import date
        bits.append(date.fromisoformat(f["date"]).strftime("%a %b %d").replace(" 0", " "))
    if f.get("time"):
        h, m = map(int, f["time"].split(":"))
        bits.append(f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}")
    if f.get("party"):
        bits.append(f"for {f['party']}")
    if f.get("price"):
        bits.append(f"${f['price']}")
    return f"Task complete — {c['request'].get('what')} · {c['business']}" + (" · " + " · ".join(bits) if bits else "")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    shown = []
    for c, t in pick():
        r = check(c)
        shown.append((c, r))
        print(f"\n== {c['business']} ({c['kind']}), truth {t['status']}")
        for x in r["lines"]:
            print(f"   {x['i']} {x['who']:<6} {x['text']}")
        print(f"   agent said : {report_text(c)}")
        print(f"   callcheck  : {r['status']} — {r['parent_card']}")
        for f in r["family_card"]:
            print(f"                {f}")
    ev = {}
    for w in ("heldout_v1", "heldout2"):
        p = HERE / f"out/eval_{w}.json" if w != "heldout_v1" else HERE / "out/eval_heldout_v1.json"
        if p.exists():
            ev[w] = json.loads(p.read_text())["metrics"]
    (HERE / "out/report.json").write_text(json.dumps([{"call": c, "result": {k: v for k, v in r.items() if k != "lines"}}
                                                      for c, r in shown], indent=2, default=str))
    (HERE / "out/report.html").write_text(render(shown, ev), encoding="utf-8")
    print("\nwrote out/report.html, out/report.json")


def render(shown, ev):
    blocks = []
    for c, r in shown:
        dec = r["decided_at"]
        flagged = {f["turn"] for f in r["flags"]}
        tr = "".join(
            f'<div class="ln {x["who"]}{" dec" if x["i"] == dec else ""}{" flag" if x["i"] in flagged else ""}">'
            f'<span class="n">{x["i"]}</span><span class="w">{"Rhem" if x["who"] == "agent" else "" if x["who"] == "system" else "Business"}</span>'
            f'<span>{e(x["text"])}</span></div>' for x in r["lines"])
        fam = "".join(f"<li>{e(f)}</li>" for f in r["family_card"][1:])
        blocks.append(f"""<section class="call"><div class="tr"><div class="biz">{e(c['business'])} · {e(c['request'].get('what', ''))}</div>{tr}</div>
<div class="side"><div class="said"><div class="lbl">Agent's card</div><div class="card plain">✓ {e(report_text(c))}</div></div>
<div class="chk"><div class="lbl">After callcheck</div><div class="card"><span class="pill {COLOR[r['status']]}">{STATUS_WORD[r['status']]}</span>
<div class="pc">{e(r['parent_card'])}</div><div class="ev">decided at turn {dec}</div><ul>{fam}</ul></div></div></div></section>""")
    rows = ""
    names = {"heldout_v1": "held-out v1 (first run)", "heldout2": "held-out v2 (first run, the one to quote)"}
    for k, m in ev.items():
        rows += (f"<tr><td>{names[k]}</td><td>{m['calls']}</td><td>{m['truly_not_done']}</td><td class='b'>{m['false_complete_report']}</td>"
                 f"<td>{m['false_complete_keyword']}</td><td class='g'>{m['false_complete_check']}</td><td>{m['missed_done_check']}</td>"
                 f"<td>{m['status_exact']}/{m['calls']}</td><td>{m['flags_caught']}/{m['flags_planted']} · {m['flags_false']} false</td>"
                 f"<td>{m['wrong_claims_caught']}/{m['wrong_claims_planted']}</td></tr>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Call outcome check</title><style>
:root{{--bg:#f6f5f1;--fg:#1f2320;--mut:#666b63;--card:#fff;--line:#e3e1da;--ok:#2f7a4f;--okb:#dcefe2;--warn:#8a6411;--warnb:#f6ecd0;--bad:#b13e2e;--badb:#f7dcd6;--acc:#3b5c8c}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1120px;margin:0 auto;padding:26px 16px 60px}}h1{{font-size:26px;margin:0 0 4px}}.sub{{color:var(--mut)}}
.call{{display:grid;grid-template-columns:1.25fr 1fr;gap:16px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-top:16px}}
@media(max-width:800px){{.call{{grid-template-columns:1fr}}}}.biz{{font-weight:650;margin-bottom:6px}}
.ln{{display:grid;grid-template-columns:22px 70px 1fr;gap:6px;padding:3px 6px;border-radius:6px;font-size:14px}}.ln .n{{color:var(--mut)}}.ln .w{{color:var(--mut);font-size:12.5px;padding-top:1px}}
.ln.agent{{background:#f1f4f9}}.ln.system{{color:var(--mut);font-style:italic}}.ln.dec{{outline:2px solid var(--acc)}}.ln.flag{{background:var(--badb)}}
.lbl{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:2px 0 4px}}.card{{border:1px solid var(--line);border-radius:10px;padding:10px 12px}}
.card.plain{{background:#f3f7f2;color:var(--ok)}}.chk{{margin-top:12px}}.pill{{font-weight:700;font-size:13px;padding:2px 10px;border-radius:99px}}
.pill.ok{{background:var(--okb);color:var(--ok)}}.pill.warn{{background:var(--warnb);color:var(--warn)}}.pill.bad{{background:var(--badb);color:var(--bad)}}
.pc{{margin:8px 0 4px;font-weight:600}}.ev{{color:var(--mut);font-size:13px}}ul{{margin:6px 0 0;padding-left:18px;font-size:13.5px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--card)}}td,th{{border:1px solid var(--line);padding:6px 8px;text-align:left}}td.b{{color:var(--bad);font-weight:700}}td.g{{color:var(--ok);font-weight:700}}
h2{{font-size:18px;margin:30px 0 10px}}</style></head><body><main>
<h1>Did the call actually do it?</h1>
<div class="sub">The agent's "Task complete" card vs. what the business said. Synthetic calls. Unofficial prototype by Kushagra Pratap Singh, not affiliated with Rhem Labs.</div>
{''.join(blocks)}
<h2>Across 88-call sets</h2><div style="overflow-x:auto"><table><tr><th>set</th><th>calls</th><th>not actually done</th><th>told "done" by agent report</th><th>by keyword check</th><th>by callcheck</th><th>real bookings missed</th><th>exact status</th><th>policy flags</th><th>wrong report claims caught</th></tr>{rows}</table></div>
</main></body></html>"""


if __name__ == "__main__":
    main()
