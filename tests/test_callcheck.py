import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from callcheck.check import check  # noqa: E402
from callcheck.parse import dates, identifiers, money, party, times  # noqa: E402

TODAY = date(2026, 10, 12)  # Monday


def call(lines, kind="restaurant", req=None, report=None, policy=None):
    req = req or {"date": "2026-10-16", "time": "19:00", "party": 2, "time_tolerance_min": 15, "what": "dinner"}
    tr = [{"who": w, "text": t} for w, t in lines]
    return {"id": "t", "kind": kind, "business": "Willow Bistro", "call_date": TODAY.isoformat(), "request": req,
            "policy": policy or {"share_ok": ["dob", "address", "card_last4"], "fees_need_approval": True},
            "transcript": tr, "report": report or {}}


def test_parse_spoken_times_dates_party():
    assert times("how about quarter to eight?") == [19 * 60 + 45]
    assert times("the earliest is the 20th at 10:30", mode="day") == [10 * 60 + 30]
    assert times("table for 4 at 6:30 pm") == [18 * 60 + 30]       # "for 4" is a party, not 4 PM
    assert dates("Thursday the 16th", TODAY) == [date(2026, 10, 16)]
    assert party("Our only free table seats two") == 2
    assert money("that comes to $86.40 plus a 25 dollars deposit") == [8640, 2500]
    assert identifiers("card ending in 4421") == ["card_last4"]
    assert "ssn" in identifiers("her social is 412-55-0193")


def test_alternative_time_accepted_is_done_changed_and_report_wrong():
    r = check(call([("biz", "Willow Bistro, how can I help?"),
                    ("agent", "A table for two on Friday at 7, please."),
                    ("biz", "We're full at 7, but how about 8:15?"),
                    ("agent", "That works, please book it."),
                    ("biz", "Great, you're all set.")],
                   report={"status": "complete", "fields": {"date": "2026-10-16", "time": "19:00", "party": 2}}))
    assert r["status"] == "DONE_CHANGED" and r["changed"] == ["time"] and r["agreed"]["time"] == "8:15 PM"
    assert {c["claim"]: c["verdict"] for c in r["claims"]}["time: 7:00 PM"] == "WRONG"


def test_callback_reported_complete_is_pending():
    r = check(call([("biz", "Hi"), ("agent", "Table for two Friday at 7?"),
                    ("biz", "Let me check with the manager and we'll call you back."), ("agent", "Thanks."),
                    ("system", "[call ended]")], report={"status": "complete", "fields": {"time": "19:00"}}))
    assert r["status"] == "PENDING" and r["reason"] == "callback"
    assert r["claims"][0]["verdict"] == "WRONG" and r["claims"][1]["verdict"] == "UNSUPPORTED"


def test_pharmacy_too_early_and_dob_is_allowed():
    req = {"what": "lisinopril refill"}
    r = check(call([("biz", "Pharmacy."), ("agent", "Refill lisinopril for Teri."),
                    ("biz", "Date of birth?"), ("agent", "Her date of birth is 3/14/1948."),
                    ("biz", "It's too early to refill, insurance won't cover it until the 20th.")], kind="pharmacy", req=req))
    assert r["status"] == "NOT_DONE" and r["reason"] == "too_early" and r["flags"] == []


def test_overshare_and_budget():
    req = {"what": "groceries", "budget_cents": 6000}
    r = check(call([("biz", "FreshCart."), ("agent", "Groceries for Donna."),
                    ("biz", "Your total comes to $71.20."), ("agent", "Sounds good."),
                    ("biz", "Card?"), ("agent", "The card number is 4111 1111 1111 1111."),
                    ("biz", "Your order is placed.")], kind="grocery", req=req))
    flags = {f["flag"] for f in r["flags"]}
    assert r["status"] == "NEEDS_PARENT" and flags == {"OVERSHARE", "BUDGET"}


def test_delivery_fee_inside_total_is_not_a_separate_fee():
    req = {"what": "groceries", "budget_cents": 10000}
    r = check(call([("biz", "Hi"), ("agent", "Order please."),
                    ("biz", "It's going to be $48.25 including the delivery fee."), ("agent", "Okay, let's do that."),
                    ("biz", "All done, your order is confirmed.")], kind="grocery", req=req))
    assert r["status"] == "DONE" and r["flags"] == []


def test_voicemail_is_not_done():
    r = check(call([("system", "[Voicemail] Please leave a message after the tone."),
                    ("agent", "Hi, calling for Teri."), ("system", "[call ended]")]))
    assert r["status"] == "NOT_DONE" and r["reason"] == "voicemail"
