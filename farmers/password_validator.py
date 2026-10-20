"""
Password validator for SmartAssist.

The register page (register.html) mirrors these rules in JavaScript.
If you change anything in this file, update the JS mirror in the same commit,
or the client-side strength meter will disagree with the server.

Rules:
  G1 length 8-128
  G2 common password / blocked word (after de-leet and stemming)
  G3 contains username or email (exact or reversed)
  G4 repeated characters or blocks (aaa, abab)
  G5 sequences and keyboard walks (1234, qwer, asdf)
Scoring: accept only if score >= 5 on the survivors.
"""

import re
import unicodedata

COMMON = {"password", "admin", "qwerty", "letmein", "welcome", "iloveyou",
          "123456", "12345678", "abc123", "monkey", "dragon", "helloworld"}
BLOCKED_WORDS = {"password", "admin", "qwerty", "letmein"}
KEYBOARD_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890", "1qaz2wsx"]
LEET = str.maketrans({"@": "a", "0": "o", "$": "s", "1": "l", "3": "e",
                      "!": "i", "5": "s", "7": "t"})


def normalize(pw: str) -> str:
    return unicodedata.normalize("NFKC", pw).strip()


def stem(pw: str) -> str:
    """Lowercase, strip trailing digits/symbols, then de-leet.
    'Summer2026!' -> 'summer'; 'p@ssword123' -> 'password'."""
    s = re.sub(r"[\d\W_]+$", "", pw.lower())
    return s.translate(LEET)


def has_sequence(pw: str, n: int = 4) -> bool:
    p = pw.lower()
    for i in range(len(p) - n + 1):
        chunk = p[i:i + n]
        codes = [ord(c) for c in chunk]
        diffs = {codes[j + 1] - codes[j] for j in range(n - 1)}
        if diffs in ({1}, {-1}):
            return True
        for row in KEYBOARD_ROWS:
            if chunk in row or chunk[::-1] in row:
                return True
    return False


def has_repeat(pw: str) -> bool:
    if re.search(r"(.)\1{2,}", pw):
        return True
    return bool(re.search(r"(.{2,4})\1+", pw.lower()))


def similar_to_identity(pw: str, identity: str) -> bool:
    """Exact or reversed substring match only. Deliberately NO fuzzy
    matching, so the server agrees exactly with the client meter."""
    if not identity:
        return False
    ident = identity.split("@")[0].lower().translate(LEET)
    p = pw.lower().translate(LEET)
    return len(ident) >= 3 and (ident in p or ident[::-1] in p)


def validate(pw: str, username: str = "", email: str = ""):
    """
    Stage 0: normalize. Stage 1: hard gates (any failure rejects).
    Stage 2: score survivors; accept only if score >= 5.
    Returns dict with accepted, score, band, reasons (user-facing sentences).
    """
    pw = normalize(pw)
    if not pw:
        return {"accepted": False, "score": 0, "band": "Rejected",
                "reasons": ["Please enter a password."]}

    fails = []

    if not 8 <= len(pw) <= 128:
        fails.append("Use 8 to 128 characters.")

    st = stem(pw)
    low = pw.lower().translate(LEET)
    if st in COMMON or low in COMMON or any(w in low for w in BLOCKED_WORDS):
        fails.append("Avoid common passwords or words like password, admin, qwerty.")

    if similar_to_identity(pw, username) or similar_to_identity(pw, email):
        fails.append("Do not include your username or email.")

    if has_repeat(pw):
        fails.append("Avoid repeated characters or blocks like aaa or abab.")

    if has_sequence(pw):
        fails.append("Avoid sequences and keyboard walks like 1234, qwer, asdf.")

    if fails:
        return {"accepted": False, "score": 0, "band": "Rejected", "reasons": fails}

    score = 1
    score += (len(pw) >= 8) + (len(pw) >= 12) + (len(pw) >= 16)
    score += bool(re.search(r"[A-Z]", pw)) + bool(re.search(r"[a-z]", pw))
    score += bool(re.search(r"\d", pw)) + bool(re.search(r"[^A-Za-z0-9\s]", pw))

    band = "Weak" if score <= 4 else "Strong" if score <= 6 else "Excellent"
    return {"accepted": score >= 5, "score": score, "band": band, "reasons": []}