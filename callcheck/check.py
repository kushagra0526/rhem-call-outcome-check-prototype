"""Decide what a business call actually achieved, and check the agent's report against it.

Each line is tagged with acts. The business's last decisive act wins:
CONFIRM, PENDING, REFUSE, plus the call-level VOICEMAIL / ENDED. Offers and the agent's ACCEPT move
the agreed date/time/party away from the request; a CONFIRM fixes whatever was agreed last.

Statuses
  DONE          confirmed as requested
  DONE_CHANGED  confirmed, but date / time / party differs from the request
  PENDING       someone still has to act (business callback, doctor, the parent confirming)
  NOT_DONE      refused, too early, voicemail, the call ended with nothing
  NEEDS_PARENT  confirmed, but outside the parent's rules (over budget, fee agreed without approval)
Flags (independent of status): OVERSHARE, BUDGET, UNAPPROVED_FEE
"""
import re
from datetime import date

from .parse import dates, fmt_time, identifiers, money, party, times

R = lambda p: re.compile(p, re.I)
CONFIRM = R(r"\b(you'?re (all )?set|you are (all )?set|(it'?s|you'?re|that'?s|she'?s|he'?s|they'?re|order'?s|order is|reservation is|appointment is) (all )?(booked|confirmed|scheduled|placed|in)\b|"
            r"i'?ve (booked|scheduled|got) |have (you|her|him|them) down|got (you|her|him|them) down|put (you|her|him|them) down|"
            r"see (you|her|him|them) (then|on|at)|confirmation (number|code)|will be ready|ready for pick ?up|"
            r"(is|be) on (its|the) way|(can|to|will) pick (it|them) up|(it'?s|that'?s|has) been (filled|processed|sent|submitted)|(we'?ll|we will) (deliver|have it)|booked (you|her|him|them)|all booked|locked in|"
            r"pencil(?:led)? (you|her|him|them) in|it'?s (been )?(filled|processed|sent over|submitted)|we'?ve got (it|that) (in|ready))")
PENDING = {
    "callback": R(r"\b(call (you|her|him|them) back|get back to (you|her|him|them)|(someone|we|i|the manager|the pharmacist) (will|'ll|can) (call|reach out|text|follow up)|"
                  r"follow up (with you|tomorrow|later)|ring (you|her|him) back|hear back)"),
    "doctor": R(r"\b(need[s]? (a |the |her |his )?(doctor|physician|prescriber|provider)|"
                r"(send|fax|sent|faxed) (a |the )?(request|it|that) (to|over to) (dr|the doctor|her doctor|his doctor|the office|the prescriber)|"
                r"no refills? (left|remaining)|out of refills|prior auth|authori[sz]ation from|new (prescription|script))"),
    "confirm_needed": R(r"\b(hold (it|the table|that|the slot) (until|till|for)|if (you|she|he|they) (can )?(call|confirm|come in)|"
                        r"(need|have) (you|her|him|them) to confirm|(has|have|needs?) to confirm|pending (her|his|your) confirmation|tentative)"),
    "waitlist": R(r"\b(wait ?list|waiting list)\b"),
}
NOT_DONE = {
    "too_early": R(r"\b(too (early|soon) (to|for)|can'?t (fill|refill) (it|that) (until|before)|not (due|eligible) (until|before)|"
                   r"insurance (won'?t|will not|doesn'?t) (cover|pay)( it)? (until|before|yet))"),
    "refused": R(r"\b(fully booked|no (availability|openings|tables)|nothing (available|open)|(we'?re|we are) (closed|booked up|out of stock|all out)|"
                 r"can'?t (do|book|take|seat|fit)|(don'?t|do not) (take|accept) (reservations|bookings)|unable to|not able to|we don'?t have anything)"),
}
OFFER = R(r"\b(how about|what about|would .{0,20}work|(we|i) (have|could do|can do|can offer|can fit|could fit)|earliest|next available|"
          r"only (have|thing|opening)|closest (i|we) (have|can)|(i|we) can (squeeze|get) (you|her|him|them) in|there'?s (a|an) (opening|slot))")
ACCEPT = R(r"\b(that works|that'?ll work|sounds good|works for (us|her|him|me)|yes,? please|yes,? that'?s (fine|good)|let'?s do|perfect|go ahead|"
           r"book (it|that)|we'?ll take|(i|we)'?ll take|that'?s fine|okay,? (book|do) (it|that)|please do|fine,? (book|go ahead))")
DECLINE = R(r"\b(no,? thank|that won'?t work|doesn'?t work|can'?t make|no,? that'?s too|we'?ll pass|not that)")
FEE = R(r"\b(fee|deposit|surcharge|service charge|membership|subscription|delivery charge|cancell?ation charge|copay|co-pay|restocking)\b")
TOTAL = R(r"\b(total|comes to|come to|that'?ll be|that will be|it'?s going to be|price is|cost is|grand total)\b")
VOICEMAIL = R(r"\b(leave (a|your) message|after the (tone|beep)|voice ?mail|mailbox (is )?full|not available to take your call)")
ENDED = R(r"\[(call ended|call dropped|line disconnected|hung up)\]")
NEGATED_CONFIRM = R(r"\b(not (yet )?(booked|confirmed)|isn'?t (booked|confirmed)|can'?t confirm|not able to confirm)\b")

STATUS_WORD = {"DONE": "Done", "DONE_CHANGED": "Done, but changed", "PENDING": "Not done yet",
               "NOT_DONE": "Not done", "NEEDS_PARENT": "Needs your OK"}


def _mode(kind):
    return "evening" if kind == "restaurant" else "day"


def tag(turn, kind, today, want=None):
    text, who = turn["text"], turn["who"]
    acts = set()
    if who == "system":
        if VOICEMAIL.search(text):
            acts.add("VOICEMAIL")
        if ENDED.search(text):
            acts.add("ENDED")
        return acts, {}
    fields = {}
    ds, ts = dates(text, today), times(text, _mode(kind))
    # "an opening at 6:30, nothing at 5:30": in a line that names several, the one being offered is
    # not the one that was asked for
    if len(ts) > 1 and want and want.get("time") in ts:
        ts = [x for x in ts if x != want["time"]] or ts
    if len(ds) > 1 and want and want.get("date") in ds:
        ds = [x for x in ds if x != want["date"]] or ds
    if ds:
        fields["date"] = ds[-1]
    if ts:
        fields["time"] = ts[-1]
    if kind == "restaurant":
        p = party(text, restaurant=True)
        if p:
            fields["party"] = p
    amounts = money(text)
    if who == "biz":
        if VOICEMAIL.search(text):
            acts.add("VOICEMAIL")
        if CONFIRM.search(text) and not NEGATED_CONFIRM.search(text):
            acts.add("CONFIRM")
        for k, rx in PENDING.items():
            if rx.search(text):
                acts.add("PENDING:" + k)
        for k, rx in NOT_DONE.items():
            if rx.search(text):
                acts.add("NOT_DONE:" + k)
        if OFFER.search(text) or (fields and "?" in text and not acts):
            acts.add("OFFER")
            acts.discard("NOT_DONE:refused")  # "can't do 6:30, how about 7:30?" is an offer, not a no
        if amounts:
            inside_total = TOTAL.search(text) and re.search(r"\b(including|includes|with|plus tax and)\b[^.]{0,30}" + FEE.pattern[2:], text, re.I)
            if FEE.search(text) and not inside_total:
                acts.add("FEE")
                fields["fee"] = max(amounts)
            if TOTAL.search(text) or not FEE.search(text):
                fields["price"] = max(amounts)
                acts.add("PRICE")
    else:  # agent
        if ACCEPT.search(text):
            acts.add("ACCEPT")
        if DECLINE.search(text):
            acts.add("DECLINE")
        ids = identifiers(text)
        if ids:
            acts.add("SHARE")
            fields["ids"] = ids
    return acts, fields


def check(call):
    req, kind = call["request"], call["kind"]
    today = date.fromisoformat(call["call_date"])
    want = {"date": date.fromisoformat(req["date"]) if req.get("date") else None,
            "time": _hm(req.get("time")), "party": req.get("party")}
    policy = call.get("policy", {})
    tol = req.get("time_tolerance_min", 0)
    agreed = dict(want)
    offered = {}
    decisive = None  # (act, turn index)
    pending_kind = notdone_kind = None
    fee_agreed = price_agreed = None
    last_fee = last_price = None
    flags, evidence, lines = [], {}, []
    for i, turn in enumerate(call["transcript"]):
        acts, f = tag(turn, kind, today, want)
        lines.append({"i": i + 1, "who": turn["who"], "text": turn["text"], "acts": sorted(acts)})
        if turn["who"] == "biz":
            if "OFFER" in acts or "CONFIRM" in acts:
                for k in ("date", "time", "party"):
                    if k in f:
                        offered[k] = (f[k], i + 1)
            if "FEE" in acts:
                last_fee = (f["fee"], i + 1)
            if "PRICE" in acts and "price" in f:
                last_price = (f["price"], i + 1)
            if "CONFIRM" in acts:
                for k, (v, j) in offered.items():
                    agreed[k] = v
                    evidence[k] = j
                decisive = ("CONFIRM", i + 1)
                if last_fee:
                    fee_agreed = fee_agreed or last_fee
                if last_price:
                    price_agreed = last_price
            pk = [a.split(":")[1] for a in acts if a.startswith("PENDING:")]
            nk = [a.split(":")[1] for a in acts if a.startswith("NOT_DONE:")]
            if nk:
                decisive, notdone_kind = ("NOT_DONE", i + 1), nk[0]
            elif pk:
                decisive, pending_kind = ("PENDING", i + 1), pk[0]
            if "VOICEMAIL" in acts and decisive is None:
                decisive, notdone_kind = ("NOT_DONE", i + 1), "voicemail"
        elif turn["who"] == "agent":
            if "ACCEPT" in acts:
                for k, (v, j) in offered.items():
                    agreed[k] = v
                    evidence[k] = j
                if last_fee:
                    fee_agreed = last_fee
                if last_price:
                    price_agreed = last_price
            if "DECLINE" in acts:
                offered = {}
            if "SHARE" in acts:
                bad = [x for x in f["ids"] if x not in policy.get("share_ok", [])]
                if bad:
                    flags.append({"flag": "OVERSHARE", "turn": i + 1, "what": bad})
        else:
            if "VOICEMAIL" in acts and decisive is None:
                decisive, notdone_kind = ("NOT_DONE", i + 1), "voicemail"
            if "ENDED" in acts and decisive is None:
                decisive, notdone_kind = ("NOT_DONE", i + 1), "ended"
    if decisive is None:
        decisive, notdone_kind = ("NOT_DONE", len(lines)), "no outcome"

    changed = []
    status = decisive[0]
    if status == "CONFIRM":
        for k in ("date", "time", "party"):
            if want[k] is None or agreed[k] is None:
                continue
            diff = abs(agreed[k] - want[k]) if k == "time" else (agreed[k] != want[k])
            if (k == "time" and diff > tol) or (k != "time" and diff):
                changed.append(k)
        status = "DONE_CHANGED" if changed else "DONE"
        budget = req.get("budget_cents")
        if budget and price_agreed and price_agreed[0] > budget:
            flags.append({"flag": "BUDGET", "turn": price_agreed[1], "what": [f"${price_agreed[0] / 100:.2f} > ${budget / 100:.2f}"]})
            status = "NEEDS_PARENT"
        if fee_agreed and policy.get("fees_need_approval", True) and fee_agreed[0] > policy.get("fee_ok_cents", 0):
            flags.append({"flag": "UNAPPROVED_FEE", "turn": fee_agreed[1], "what": [f"${fee_agreed[0] / 100:.2f}"]})
            status = "NEEDS_PARENT"
    reason = pending_kind if status == "PENDING" else notdone_kind if status == "NOT_DONE" else None
    claims = check_report(call.get("report", {}), status, agreed, decisive[0] == "CONFIRM", price_agreed)
    res = {"id": call["id"], "kind": kind, "status": status, "reason": reason, "decided_at": decisive[1],
           "changed": changed, "agreed": {k: _show(k, v) for k, v in agreed.items() if v is not None},
           "requested": {k: _show(k, v) for k, v in want.items() if v is not None},
           "evidence": evidence, "flags": flags, "claims": claims, "lines": lines}
    res["parent_card"], res["family_card"] = cards(call, res)
    return res


def check_report(report, status, agreed, confirmed, price):
    if not report:
        return []
    out = []
    says_done = report.get("status") == "complete"
    out.append({"claim": "status: " + report.get("status", "?"),
                "verdict": "OK" if says_done == (status in ("DONE", "DONE_CHANGED")) else "WRONG",
                "truth": status})
    for k, v in report.get("fields", {}).items():
        if k == "price":
            truth = price[0] if price else None
            claim = int(round(float(v) * 100))
            verdict = "UNSUPPORTED" if truth is None else ("OK" if truth == claim else "WRONG")
            out.append({"claim": f"price: ${float(v):.2f}", "verdict": verdict,
                        "truth": None if truth is None else f"${truth / 100:.2f}"})
            continue
        val = date.fromisoformat(v) if k == "date" else _hm(v) if k == "time" else v
        if not confirmed:
            out.append({"claim": f"{k}: {_show(k, val)}", "verdict": "UNSUPPORTED", "truth": "nothing was confirmed"})
        else:
            ok = agreed.get(k) == val
            out.append({"claim": f"{k}: {_show(k, val)}", "verdict": "OK" if ok else "WRONG",
                        "truth": _show(k, agreed.get(k))})
    return out


def cards(call, r):
    what = call["request"].get("what", call["kind"])
    a = r["agreed"]
    when = " · ".join(x for x in (a.get("date"), a.get("time")) if x)
    who = f"for {a['party']}" if a.get("party") else ""
    s = r["status"]
    biz = call.get("business", "the business")
    if s == "DONE":
        parent = f"Done: {what} with {biz}, {when} {who}".strip()
    elif s == "DONE_CHANGED":
        ch = ", ".join(f"{k} {r['requested'].get(k)} → {a.get(k)}" for k in r["changed"])
        parent = f"Booked with a change: {what} with {biz}, {when} {who} ({ch})".strip()
    elif s == "PENDING":
        nxt = {"callback": f"{biz} will call back", "doctor": "the pharmacy is asking the doctor",
               "confirm_needed": "you need to confirm", "waitlist": "you're on the waitlist"}.get(r["reason"], "waiting")
        parent = f"Not done yet: {what}. {nxt[0].upper() + nxt[1:]}."
    elif s == "NOT_DONE":
        why = {"too_early": "too early to refill", "refused": "they couldn't do it", "voicemail": "reached voicemail",
               "ended": "the call ended", "no outcome": "no answer"}.get(r["reason"], r["reason"])
        parent = f"Not done: {what} ({why}). Rhem can try again."
    else:
        parent = f"Needs your OK: {what}. " + "; ".join(f"{f['flag'].replace('_', ' ').lower()} {', '.join(f['what'])}" for f in r["flags"] if f["flag"] != "OVERSHARE")
    family = [f"[{s}] decided at turn {r['decided_at']}: \"{r['lines'][r['decided_at'] - 1]['text']}\""]
    for f in r["flags"]:
        family.append(f"{f['flag']} at turn {f['turn']}: {', '.join(f['what'])}")
    for c in r["claims"]:
        if c["verdict"] != "OK":
            family.append(f"Agent report {c['verdict']}: {c['claim']} (call says {c['truth']})")
    return parent, family


def _hm(s):
    if s is None:
        return None
    if isinstance(s, int):
        return s
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _show(k, v):
    if v is None:
        return None
    if k == "date":
        return v.strftime("%a %b %d").replace(" 0", " ")
    if k == "time":
        return fmt_time(v)
    return v
