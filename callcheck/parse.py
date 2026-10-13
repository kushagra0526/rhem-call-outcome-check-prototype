"""Pull dates, times, party sizes, money and identifiers out of one spoken line.

Speech-to-text writes numbers both ways ("7:45", "seven forty-five"), people say "Thursday",
"the 16th", "tomorrow", "quarter to eight". Everything resolves against the call date.
"""
import re
from datetime import date, timedelta

WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a couple": 2, "a couple of": 2}
TENS = {"fifteen": 15, "thirty": 30, "forty-five": 45, "forty five": 45, "twenty": 20, "ten": 10,
        "o'clock": 0, "oh five": 5, "fifty": 50}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]
ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
       "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
       "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
       "nineteenth": 19, "twentieth": 20, "twenty-first": 21, "twenty-second": 22, "twenty-third": 23}

NUM_RE = r"(\d{1,2}|" + "|".join(sorted((k for k in WORDNUM if " " not in k), key=len, reverse=True)) + r")"


def _n(tok):
    tok = tok.lower()
    return int(tok) if tok.isdigit() else WORDNUM.get(tok)


def dates(text, today):
    """All dates mentioned, resolved against today (a datetime.date)."""
    t = text.lower()
    out = []
    for m in re.finditer(r"\b(today|tonight|this evening|tomorrow|day after tomorrow)\b", t):
        w = m.group(1)
        out.append((m.start(), today + timedelta(days=2 if w.startswith("day after") else 1 if w == "tomorrow" else 0)))
    for m in re.finditer(r"\b(next |this )?(" + "|".join(WEEKDAYS) + r")\b", t):
        wd = WEEKDAYS.index(m.group(2))
        delta = (wd - today.weekday()) % 7 or 7
        if m.group(1) == "next " and delta < 7:
            delta += 7 if delta <= 2 else 0
        out.append((m.start(), today + timedelta(days=delta)))
    mon = "|".join(MONTHS)
    for m in re.finditer(r"\b(" + mon + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", t):
        out.append((m.start(), date(today.year, MONTHS.index(m.group(1)) + 1, int(m.group(2)))))
    for m in re.finditer(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b|\bthe (" + "|".join(ORD) + r")\b", t):
        d = int(m.group(1)) if m.group(1) else ORD[m.group(2)]
        y, mo = today.year, today.month
        if d < today.day:
            mo += 1
            if mo > 12:
                mo, y = 1, y + 1
        try:
            out.append((m.start(), date(y, mo, d)))
        except ValueError:
            pass
    out.sort()
    # a weekday followed by "the 16th" names one day; keep the explicit number
    res = []
    for pos, d in out:
        if res and pos - res[-1][0] < 22 and res[-1][1] != d:
            res[-1] = (pos, d)
        elif not res or res[-1][1] != d:
            res.append((pos, d))
    return [d for _, d in res]


def times(text, mode="evening"):
    """Times in minutes after midnight. Hour without am/pm: mode "evening" (restaurants) reads
    1-11 as PM; mode "day" (clinics, pharmacies) reads 7-11 as AM and 12-6 as PM."""
    t = text.lower().replace("a.m.", "am").replace("p.m.", "pm")
    out = []
    taken = []

    def add(pos, end, h, m, ampm):
        if h is None or not (0 <= m < 60) or not (1 <= h <= 12):
            return
        if ampm is None:
            ampm = "pm" if h == 12 or (mode == "evening" and h < 12) or (mode == "day" and 1 <= h <= 6) else "am"
        if ampm == "pm":
            h = h + 12 if h < 12 else h
        elif ampm in ("am", "morning") and h == 12:
            h = 0
        out.append((pos, h * 60 + m)); taken.append((pos, end))

    for m in re.finditer(r"\b(noon|midday)\b", t):
        out.append((m.start(), 12 * 60)); taken.append((m.start(), m.end()))
    for m in re.finditer(r"\b(quarter to|quarter past|half past)\s+" + NUM_RE + r"\b(?:\s*(am|pm|in the morning|in the evening|at night))?", t):
        h = _n(m.group(2)); ampm = _ampm(m.group(3))
        if m.group(1) == "quarter to":
            add(m.start(), m.end(), (h - 1) or 12, 45, ampm)
        else:
            add(m.start(), m.end(), h, 15 if m.group(1) == "quarter past" else 30, ampm)
    for m in re.finditer(r"\b(\d{1,2}):(\d{2})\s*(am|pm|in the morning|in the afternoon|in the evening|at night)?", t):
        if any(a <= m.start() < b for a, b in taken):
            continue
        add(m.start(), m.end(), int(m.group(1)), int(m.group(2)), _ampm(m.group(3)))
    words = "|".join(sorted(TENS, key=len, reverse=True))
    for m in re.finditer(r"\b(?:at |by |around |until |after |before |the |do |about |say |is |have |try )" + NUM_RE +
                         r"(?:\s+(" + words + r"))?(?:\s*(am|pm|in the morning|in the afternoon|in the evening|at night|o'clock))?(?![\d:%])", t):
        if any(a <= m.start() + 3 < b for a, b in taken):
            continue
        nxt = t[m.end():m.end() + 9]
        if re.match(r"\s*(people|guests|of us|items|days|weeks|refills|dollars|minutes|hours|pills|tablets|bottles|percent)", nxt):
            continue
        h = _n(m.group(1))
        mins = TENS.get(m.group(2), 0) if m.group(2) else 0
        add(m.start(), m.end(), h, mins, _ampm(m.group(3)))
    for m in re.finditer(r"\b" + NUM_RE + r"\s*(am|pm)\b", t):
        if any(a <= m.start() < b for a, b in taken):
            continue
        add(m.start(), m.end(), _n(m.group(1)), 0, m.group(2))
    out.sort()
    return [v for _, v in out]


def _ampm(s):
    if not s:
        return None
    s = s.strip()
    if s in ("pm", "in the afternoon", "in the evening", "at night"):
        return "pm"
    if s in ("am", "in the morning"):
        return "am"
    return None


def party(text, restaurant=True):
    t = text.lower()
    m = re.search(r"\b(?:table for|party of|for|seat|seats|seating for|reservation for)\s+" + NUM_RE + r"\b(?!\s*(?::|am|pm|o'clock|thirty|fifteen))(?:\s+(?:people|guests|of us|adults))?", t)
    if m and (restaurant or re.search(r"table|party|people|guests|seat|of us|reservation", t)):
        return _n(m.group(1))
    m = re.search(NUM_RE + r"\s+(?:people|guests|of us|adults)\b", t)
    return _n(m.group(1)) if m else None


def money(text):
    """Dollar amounts mentioned, in cents."""
    t = text.lower()
    out = []
    for m in re.finditer(r"\$\s?(\d+(?:,\d{3})*)(?:\.(\d{2}))?", t):
        out.append(int(m.group(1).replace(",", "")) * 100 + int(m.group(2) or 0))
    for m in re.finditer(r"\b(\d+)\s+dollars(?:\s+and\s+(\d+)\s+cents)?", t):
        out.append(int(m.group(1)) * 100 + int(m.group(2) or 0))
    return out


ID_PATTERNS = {
    "ssn": r"\b\d{3}[- ]\d{2}[- ]\d{4}\b|social security",
    "card": r"\b(?:\d{4}[- ]){3}\d{4}\b|\bcard number is\b|\bcard ending\b",
    "cvv": r"\b(?:cvv|security code)\b",
    "medicare": r"\bmedicare (?:number|id) is\b|\b\d[a-z]{2}\d-[a-z]{2}\d-[a-z]{2}\d{2}\b",
    "dob": r"\b(?:date of birth|born on|birthday is|dob)\b|\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b",
    "address": r"\b\d{2,5} [a-z]+ (?:street|st|avenue|ave|road|rd|lane|ln|drive|dr|court|ct)\b",
}


def identifiers(text):
    t = text.lower()
    found = [k for k, p in ID_PATTERNS.items() if re.search(p, t)]
    if "card" in found and re.search(r"card ending in \d{4}\b", t) and not re.search(r"(?:\d{4}[- ]){3}\d{4}", t):
        found = [f for f in found if f != "card"] + ["card_last4"]
    return found


def fmt_time(m):
    if m is None:
        return "-"
    h, mi = divmod(m, 60)
    return f"{(h - 1) % 12 + 1}:{mi:02d} {'AM' if h < 12 else 'PM'}"
