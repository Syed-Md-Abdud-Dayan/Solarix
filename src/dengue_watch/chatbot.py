"""Dengue Watch chatbot engine.

A deterministic, explainable assistant (no external LLM, works offline) that combines

  1. a safety layer      - detects dengue danger signs / symptom reports and gives urgent guidance first
  2. a knowledge base    - WHO-aligned dengue facts in English and Bangla (knowledge.py)
  3. data tools          - live answers from the trained forecasting models via a `Backend`
  4. conversation memory - city / ward / horizon carry over between turns ("what about Gazipur?")

The engine never touches pandas or the models directly; everything numeric comes through a `Backend`
object (implemented in app.py, stubbed in tests). Every reply is a plain dict that is JSON-serialisable.
"""
from __future__ import annotations

import difflib
import re
from datetime import date, timedelta
from typing import Any, Optional

from . import knowledge as K

MAX_MESSAGE_CHARS = 500

# ------------------------------------------------------------------ text helpers
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_BN_RE = re.compile(r"[ঀ-৿]")

LEVEL_BN = {"Critical": "সংকটজনক", "High": "উচ্চ", "Medium": "মাঝারি", "Low": "নিম্ন"}
CITY_BN = {"Dhaka North": "ঢাকা উত্তর", "Dhaka South": "ঢাকা দক্ষিণ", "Chattogram": "চট্টগ্রাম",
           "Gazipur": "গাজীপুর", "Narayanganj": "নারায়ণগঞ্জ", "All": "সব শহর"}

CITY_ALIASES = {
    "Dhaka North": ["dhaka north", "north dhaka", "dncc", "uttara", "ঢাকা উত্তর", "উত্তর ঢাকা"],
    "Dhaka South": ["dhaka south", "south dhaka", "dscc", "ঢাকা দক্ষিণ", "দক্ষিণ ঢাকা"],
    "Chattogram": ["chattogram", "chittagong", "ctg", "ccc", "চট্টগ্রাম", "চিটাগং"],
    "Gazipur": ["gazipur", "gcc", "গাজীপুর"],
    "Narayanganj": ["narayanganj", "narayangonj", "ncc", "নারায়ণগঞ্জ"],
}
WARD_PREFIX_CITY = {"dncc": "Dhaka North", "dscc": "Dhaka South", "ccc": "Chattogram", "gcc": "Gazipur", "ncc": "Narayanganj"}

MONTHS = {
    "january": 1, "jan": 1, "জানুয়ারি": 1, "february": 2, "feb": 2, "ফেব্রুয়ারি": 2, "march": 3, "mar": 3, "মার্চ": 3,
    "april": 4, "apr": 4, "এপ্রিল": 4, "may": 5, "মে": 5, "june": 6, "jun": 6, "জুন": 6, "july": 7, "jul": 7, "জুলাই": 7,
    "august": 8, "aug": 8, "আগস্ট": 8, "september": 9, "sep": 9, "sept": 9, "সেপ্টেম্বর": 9, "october": 10, "oct": 10, "অক্টোবর": 10,
    "november": 11, "nov": 11, "নভেম্বর": 11, "december": 12, "dec": 12, "ডিসেম্বর": 12,
}
MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}


def norm_text(s: str) -> str:
    s = (s or "").translate(_BN_DIGITS).lower().strip()
    return re.sub(r"\s+", " ", s)


def detect_lang(s: str) -> str:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return "en"
    return "bn" if sum(1 for c in letters if _BN_RE.match(c)) / len(letters) > 0.3 else "en"


def _has(text: str, word: str) -> bool:
    """Whole-word (Latin) or substring (Bangla) match."""
    if _BN_RE.search(word):
        return word in text
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None


_TO_BN = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def _bn_digits(s: str) -> str:
    """Bangla numerals for standalone numbers in prose (IDs like DNCC_Ward_06 and ISO dates stay ASCII)."""
    return re.sub(r"(?<![\w.\-/:])\d[\d,]*(?:\.\d+)?(?![\w\-/:])", lambda m: m.group(0).translate(_TO_BN), s)


def n0(x: float) -> str:
    """Whole numbers for big values, one decimal for small ones (so 0.4 isn't shown as 0)."""
    return fmt(x, 1) if abs(x) < 10 else fmt(x, 0)


def fmt(n: float, d: int = 1) -> str:
    return f"{n:,.{d}f}".rstrip("0").rstrip(".") if d else f"{n:,.0f}"


# ------------------------------------------------------------------ red flags / symptoms
_PERSONAL = re.compile(r"\b(i|i'm|im|my|me|he|she|his|her|him|they|patient|son|daughter|mother|mom|mum|father|dad|baby|child|kid|wife|husband|"
                       r"brother|sister|friend|someone|neighbou?r|is|has|have|having|getting|started|keeps?|can't|cant|cannot)\b|"
                       r"আমার|আমি|তার|সে|ছেলে|মেয়ে|বাবা|মা |রোগী|হচ্ছে|হয়েছে|করছে|হয়|দিচ্ছে|পারছে না|পারছি না")
_INFO_Q = re.compile(r"^(what|why|how|does|do|is|are|can|could|which|when|will|should|tell me|explain|list)\b|\b(signs? of|symptoms? of|causes? of)\b|\?\s*$|কী কী|কি কি|কখন|কী\b|কি\b")
_FEVER = re.compile(r"\b(fever|temperature|febrile|feverish|high temp)\b|জ্বর|জ্বরে|জ্বরটা")
_DENGUE_WORD = re.compile(r"dengue|ডেঙ্গু|ডেংগু")

FLAG_BN = {"abdominal pain": "পেটে ব্যথা", "persistent vomiting": "ক্রমাগত বমি", "bleeding": "রক্তক্ষরণ", "drowsiness / confusion": "ঝিমুনি/বিভ্রান্তি",
           "breathing difficulty": "শ্বাসকষ্ট", "cold clammy skin": "ঠান্ডা ঘামে ভেজা ত্বক", "low urine": "প্রস্রাব কম", "seizure": "খিঁচুনি"}

RED_FLAGS = [
    (r"(severe|bad|intense|a lot of|continuous|constant|terrible)?\s*(stomach|abdominal|belly|tummy)\s*(pain|ache)|pain in (my |the |his |her )?(stomach|belly|abdomen)|পেটে (তীব্র |খুব |অনেক )?ব্যথা|পেট ব্যথা", "abdominal pain"),
    (r"vomit(ing|s|ed)?\b.*(again and again|repeated|persistent|continuous|many times|non.?stop|\b[3-9]\s*(times|x)|cannot|can't|keeps?)|keeps? vomiting|can'?t (keep|hold) (anything|fluids|water|food) down|persistent vomit|বারবার বমি|ক্রমাগত বমি|বমি হচ্ছে|বমি করছে", "persistent vomiting"),
    (r"bleed|blood (in|from|with)|(gum|nose)\s*bleed|nosebleed|black (stool|poop)|tarry stool|vomit(ing)? blood|blood in (stool|vomit|urine)|রক্ত(ক্ষরণ| পড়ছে| পড়া| বমি)|নাক দিয়ে রক্ত|মাড়ি দিয়ে রক্ত|কালো পায়খানা", "bleeding"),
    (r"(very |extremely |too )?(drowsy|lethargic|sleepy|unresponsive|unconscious|faint(ed|ing)?|passed out|confused|disoriented|restless|irritable|can'?t wake|not waking|delirious)|অজ্ঞান|ঝিমাচ্ছে|নেতিয়ে|অস্থির|বিভ্রান্ত", "drowsiness / confusion"),
    (r"(fast|rapid|difficulty|trouble|hard|short(ness)? of) breath|breathing (fast|hard|difficult)|can'?t breathe|শ্বাসকষ্ট|শ্বাস নিতে কষ্ট|দ্রুত শ্বাস", "breathing difficulty"),
    (r"cold (and )?(clammy|sweaty)|clammy|cold (hands|feet)|pale (and )?(cold )?skin|weak pulse|হাত.?পা ঠান্ডা|ঘেমে|ফ্যাকাসে", "cold clammy skin"),
    (r"(very little|no|less|hardly any|not passing|stopped passing) urine|haven'?t (peed|urinated)|not (peeing|urinating)|প্রস্রাব (কম|হচ্ছে না|বন্ধ)", "low urine"),
    (r"seizure|convuls|fit\b|খিঁচুনি", "seizure"),
]
_RED_COMPILED = [(re.compile(p), n) for p, n in RED_FLAGS]


def find_red_flags(text: str) -> list[str]:
    return [n for rx, n in _RED_COMPILED if rx.search(text)]


# ------------------------------------------------------------------ KB matching
_KB_VOCAB = sorted({w for t in K.TOPICS.values() for kw in t["keywords"] for w in re.findall(r"[a-z]{4,}", kw)})


def _spell_fix(text: str) -> str:
    """Correct obvious typos of dengue vocabulary ('dengu', 'symtoms', 'preventon')."""
    out = []
    for w in text.split(" "):
        if re.fullmatch(r"[a-z]{5,}", w) and w not in _KB_VOCAB and not any(v.startswith(w) or w.startswith(v) for v in _KB_VOCAB if len(v) >= 5):
            m = difflib.get_close_matches(w, _KB_VOCAB + ["dengue", "symptoms", "prevention", "forecast", "mosquito", "hospital"], n=1, cutoff=0.9)
            out.append(m[0] if m else w)
        else:
            out.append(w)
    return " ".join(out)


def match_topic(text: str) -> tuple[Optional[str], float]:
    best, best_score = None, 0.0
    for tid, t in K.TOPICS.items():
        score = 0.0
        for kw in t["keywords"]:
            if len(kw) <= 3 and not _BN_RE.search(kw):
                hit = _has(text, kw)
            elif _BN_RE.search(kw):
                hit = kw in text
            else:
                # prefix match so "symptom" hits "symptoms", "vaccin" hits "vaccination"
                hit = re.search(rf"(?<![a-z0-9]){re.escape(kw)}", text) is not None
            if hit:
                score += 1.0 + 0.4 * kw.count(" ") + min(len(kw), 20) / 40
        if score > best_score:
            best, best_score = tid, score
    return best, best_score


# ------------------------------------------------------------------ entities
def extract_entities(raw: str, cities: list[str], today: date) -> dict[str, Any]:
    t = norm_text(raw)
    ent: dict[str, Any] = {}
    found = []
    for city, aliases in CITY_ALIASES.items():
        if city in cities and any(_has(t, a) for a in aliases):
            found.append(city)
    if re.search(r"all cities|all (the )?cities|whole country|every city|nationwide|overall|সব শহর|সারা দেশ", t):
        ent["all_cities"] = True
    if not found and (_has(t, "dhaka") or "ঢাকা" in t):
        ent["dhaka_ambiguous"] = True
    if found:
        ent["cities"] = found
        ent["city"] = found[0]
    # ward id like DNCC_Ward_05, or "ward 5"
    m = re.search(r"\b(dncc|dscc|ccc|gcc|ncc)[\s_-]*ward[\s_-]*0*(\d{1,3})\b", t)
    if m:
        ent["ward_no"] = int(m.group(2)); ent["city"] = WARD_PREFIX_CITY[m.group(1)]; ent["cities"] = [ent["city"]]
        ent["ward_id"] = f"{m.group(1).upper()}_Ward_{int(m.group(2)):02d}"
    else:
        m = re.search(r"(?:ward|ওয়ার্ড)[\s_#-]*(?:no\.?|number|নং|নম্বর)?[\s_#:-]*0*(\d{1,3})\b", t) or re.search(r"\b0*(\d{1,3})\s*(?:no\.?|নং)?\s*(?:ward|ওয়ার্ড)", t)
        if m:
            ent["ward_no"] = int(m.group(1))
    # horizon in weeks
    m = re.search(r"\b(\d{1,2})\s*(?:-)?\s*(?:weeks?|wks?|w\b|সপ্তাহ)", t)
    if m:
        ent["horizon"] = int(m.group(1))
    else:
        m = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*(?:-)?\s*weeks?", t)
        if m:
            ent["horizon"] = NUM_WORDS[m.group(1)]
        elif re.search(r"next week|coming week|upcoming week|এই সপ্তাহ|আগামী সপ্তাহ", t):
            ent["horizon"] = 1
        else:
            m = re.search(r"\b(\d{1,2})\s*months?|(\d{1,2})\s*মাস", t)
            if m:
                ent["horizon"] = min(12, int(m.group(1) or m.group(2)) * 4)
                ent["horizon_from_months"] = True
            elif re.search(r"next month|coming month|upcoming month|আগামী মাস|পরের মাস", t):
                ent["horizon"] = 4
    # explicit month / year
    for name, num in MONTHS.items():
        if name in ("may", "mar", "dec", "sep", "oct", "nov", "jan", "feb", "apr", "jun", "jul", "aug", "sept") and not re.search(rf"(?<![a-z]){name}(?![a-z])", t):
            continue
        if len(name) > 3 and not _BN_RE.search(name) and name not in t:
            continue
        if _BN_RE.search(name) and name not in t:
            continue
        # 'may' is also a verb: require a year or a preposition before it
        if name == "may" and not re.search(r"\b(in|during|for|of|by)\s+may\b|\bmay\s+(20\d\d|month)", t):
            continue
        ent["month"] = num
        break
    my = re.search(r"\b(20\d\d)\b", t)
    if my:
        ent["year"] = int(my.group(1))
    elif re.search(r"next year|আগামী বছর|পরের বছর", t):
        ent["year"] = today.year + 1
    elif re.search(r"this year|এই বছর", t):
        ent["year"] = today.year
    elif re.search(r"last year|previous year|গত বছর", t):
        ent["year"] = today.year - 1
    if re.search(r"next monsoon|coming monsoon|upcoming season|next season|next peak", t):
        ent["next_season"] = True
    # rainfall what-if
    rain = None
    if re.search(r"\b(doubl\w*|twice|2x|২ গুণ|দ্বিগুণ)", t): rain = 2.0
    elif re.search(r"\b(half|50% less|halves|halved|অর্ধেক)", t): rain = 0.5
    elif re.search(r"\b(triple|3x)", t): rain = 2.0
    else:
        m = re.search(r"(\d{1,3})\s*%\s*(more|higher|increase|heavier|extra|wetter|বেশি)", t)
        if m: rain = 1 + int(m.group(1)) / 100
        m = re.search(r"(\d{1,3})\s*%\s*(less|lower|decrease|drier|reduced|কম)", t)
        if m: rain = 1 - int(m.group(1)) / 100
        if rain is None:
            if re.search(r"heavy rain|extreme rain|very wet|flood|above.normal rain|more rain|ভারী বৃষ্টি|বেশি বৃষ্টি|অতিবৃষ্টি", t): rain = 1.5
            elif re.search(r"low rain|little rain|drought|dry (season|spell|year|weather)|less rain|no rain|কম বৃষ্টি|খরা", t): rain = 0.6
    if rain is not None:
        ent["rain_mult"] = round(min(2.0, max(0.4, rain)), 2)
    m = re.search(r"(\d(?:\.\d)?)\s*(?:°|degrees?|deg)?\s*c?\s*(warmer|hotter|higher|more|increase|rise)", t)
    if m and re.search(r"temp|warm|hot|degree|°", t):
        ent["temp_shift"] = min(3.0, float(m.group(1)))
    return ent


# ------------------------------------------------------------------ the engine
class ChatEngine:
    """backend must provide: cities, latest, today(), risk(), future(), actuals(), season(), accuracy(), info()."""

    CONTEXT_KEYS = {"city": str, "ward_id": str, "horizon": int, "intent": str, "lang": str, "rain_mult": float, "year": int, "month": int, "turns": int}

    def __init__(self, backend):
        self.b = backend

    # -- public ---------------------------------------------------------
    def reply(self, message: str, context: Optional[dict] = None, lang: Optional[str] = None) -> dict:
        ctx = self._clean_ctx(context)
        message = (message or "").strip()[:MAX_MESSAGE_CHARS]
        L = lang if lang in ("en", "bn") else (detect_lang(message) if message else ctx.get("lang", "en"))
        if not message:
            return self._pack(L, ctx, "empty", K.SMALLTALK["greet"][L], suggestions=self._chips(L))
        raw_t = norm_text(message)
        t = _spell_fix(raw_t)
        ent = extract_entities(message, list(self.b.cities), self.b.today())
        try:
            out = self._route(t, ent, ctx, L, raw_t)
        except Exception as exc:  # never let a data failure break the conversation
            out = self._pack(L, ctx, "error", self._t(L, "I couldn't get that from the forecasting models just now. Please try again, or ask me a general dengue question.",
                                                       "মডেল থেকে এখন তথ্য আনতে পারিনি। আবার চেষ্টা করুন, অথবা ডেঙ্গু সম্পর্কে সাধারণ প্রশ্ন করুন।"),
                             suggestions=self._chips(L), debug=str(exc)[:200])
        out["context"]["lang"] = L
        out["context"]["turns"] = int(ctx.get("turns", 0)) + 1
        return out

    # -- plumbing -------------------------------------------------------
    def _clean_ctx(self, ctx) -> dict:
        out = {}
        if isinstance(ctx, dict):
            for k, typ in self.CONTEXT_KEYS.items():
                v = ctx.get(k)
                if v is None:
                    continue
                try:
                    out[k] = typ(v)
                except (TypeError, ValueError):
                    pass
        if out.get("city") and out["city"] not in self.b.cities:
            out.pop("city")
        if out.get("lang") not in (None, "en", "bn"):
            out.pop("lang")
        return out

    @staticmethod
    def _t(L, en, bn):
        return bn if L == "bn" else en

    def _city_name(self, L, c):
        return CITY_BN.get(c, c) if L == "bn" else c

    def _lvl(self, L, v):
        return LEVEL_BN.get(v, v) if L == "bn" else v

    def _chips(self, L, keys=None):
        if keys:
            lab = K.FOLLOW_UP_LABELS[L]
            return [{"label": lab[k], "text": lab[k]} for k in keys if k in lab]
        return [{"label": s, "text": s} for s in K.SUGGESTIONS[L][:6]]

    def _pack(self, L, ctx, intent, text="", *, title=None, bullets=None, table=None, severity="info", suggestions=None,
              sources=None, disclaimer=True, notes=None, entities=None, new_ctx=None, debug=None, links=None):
        c = dict(ctx)
        if new_ctx:
            c.update({k: v for k, v in new_ctx.items() if v is not None})
        c["intent"] = intent
        r = {"intent": intent, "severity": severity, "lang": L,
             "reply": {"title": title, "text": text, "bullets": bullets or [], "table": table, "notes": notes or []},
             "suggestions": suggestions if suggestions is not None else self._chips(L),
             "sources": sources or [], "context": c, "entities": entities or {}}
        if disclaimer and intent not in ("greet", "thanks", "bye", "empty", "fallback"):
            r["disclaimer"] = K.DISCLAIMER[L]
        if L == "bn":
            rp = r["reply"]
            rp["text"] = _bn_digits(rp["text"]); rp["title"] = _bn_digits(rp["title"]) if rp["title"] else rp["title"]
            rp["bullets"] = [_bn_digits(x) for x in rp["bullets"]]; rp["notes"] = [_bn_digits(x) for x in rp["notes"]]
        if debug:
            r["debug"] = debug
        return r

    def _topic(self, L, ctx, tid, severity="info", entities=None):
        d = K.TOPICS[tid][L]
        text = ""
        bullets = list(d["body"])
        if tid == "season":
            return self._season(L, ctx, entities)
        return self._pack(L, ctx, f"kb:{tid}", text, title=d["title"], bullets=bullets, severity=severity,
                          suggestions=self._chips(L, d.get("follow_ups")), sources=["WHO dengue guidance", "DGHS Bangladesh"], entities=entities)

    # -- routing --------------------------------------------------------
    def _route(self, t: str, ent: dict, ctx: dict, L: str, raw_t: str = "") -> dict:
        cities = list(self.b.cities)
        # carry over city/horizon from conversation when not stated
        c_city = ent.get("city") or ctx.get("city")
        has_dengue = bool(_DENGUE_WORD.search(t))

        # 1. Safety first: red flags in a personal context -> emergency
        flags = find_red_flags(raw_t or t)
        personal = bool(_PERSONAL.search(t))
        info_q = bool(_INFO_Q.search(raw_t)) and not re.search(r"\b(my|his|her|i|i'm|me|he|she)\b|আমার|আমি|তার", raw_t)
        if flags and not info_q:
            return self._emergency(L, ctx, flags, ent)
        # 2. Symptom report: personal + fever
        if _FEVER.search(t) and personal and not info_q and not re.search(r"forecast|risk|ward|predict|ঝুঁকি|পূর্বাভাস", t):
            return self._symptom_check(L, ctx, t, ent, flags)

        # 3. small talk
        if re.fullmatch(r"(hi|hello|hey|salam|assalamu alaikum|assalamualaikum|good (morning|afternoon|evening)|হ্যালো|হাই|আসসালামু আলাইকুম|সালাম|নমস্কার)[!. ]*", t):
            return self._pack(L, ctx, "greet", K.SMALLTALK["greet"][L])
        if re.search(r"\b(thanks|thank you|thx|ty|appreciate)\b|ধন্যবাদ|শুকরিয়া", t) and len(t) < 40:
            return self._pack(L, ctx, "thanks", K.SMALLTALK["thanks"][L])
        if re.fullmatch(r"(bye|goodbye|see you|good night|বিদায়|আল্লাহ হাফেজ|খোদা হাফেজ)[!. ]*", t):
            return self._pack(L, ctx, "bye", K.SMALLTALK["bye"][L])
        if re.search(r"who are you|what are you|what can you do|help\b|how (do|can) (i|you) use|are you (a )?(bot|ai|human|real)|তুমি কে|আপনি কে|কী করতে পারো|কি করতে পারেন|সাহায্য", t) and not has_dengue:
            return self._help(L, ctx)
        if re.search(r"\b(joke|football|cricket|movie|recipe|stock price|bitcoin|politic\w*|election|prime minister|president|homework|translate|poem|song)\b", t) and not has_dengue:
            return self._pack(L, ctx, "off_topic", K.SMALLTALK["off_topic"][L])

        # 4. data intents
        if re.search(r"accura|reliab|trust|precision|recall|f1|r2|r²|rmse|\bmae\b|metric|error|validat|how good|nirbhul|নির্ভুল|সঠিক|নির্ভরযোগ্য|কতটা ভালো", t):
            return self._accuracy(L, ctx, ent)
        if re.search(r"\b(dataset|data set|data source|where.*data|data (period|coverage|range)|how many wards|which cities|cities (do|are)|coverage|last updated|how recent|up to date|latest data)\b|ডেটা|তথ্যের উৎস|কয়টি ওয়ার্ড", t) and not re.search(r"forecast|risk", t):
            return self._data_info(L, ctx)
        if "rain_mult" in ent and re.search(r"what if|scenario|suppose|if |imagine|যদি|ধরুন", t) or ("temp_shift" in ent and re.search(r"what if|scenario|if |যদি", t)):
            return self._whatif(L, ctx, ent, c_city)
        if ent.get("ward_no") is not None or ent.get("ward_id"):
            return self._ward(L, ctx, ent, c_city)

        compare = len(ent.get("cities", [])) >= 2 or (re.search(r"\bcompare|comparison|versus|\bvs\.?\b|which city|which (area|district)|তুলনা|কোন শহর", t) and re.search(r"cit(y|ies)|areas?|district|risk|forecast|cases|শহর|ঝুঁকি", t))
        top_q = re.search(r"\b(top|highest|worst|most|hotspot|hot spot|priorit\w+|rank\w*|riskiest|dangerous|affected|where should|which wards?|wards? (with|at|that)|critical wards?)\b|শীর্ষ|সবচেয়ে|কোন ওয়ার্ড", t)
        risk_q = re.search(r"\b(risk|forecast|outlook|predict\w*|projection|expected|expect|situation|cases|outbreak|cases|alert|early warning|how bad|will there be|going to be)\b|ঝুঁকি|পূর্বাভাস|সংক্রমণ|প্রাদুর্ভাব|রোগী", t)
        time_q = ent.get("year") or ent.get("month") or ent.get("next_season")
        hist_q = re.search(r"\b(how many (cases|people)|total cases|history|historical|past|worst year|record|happened|actual|reported|last year|previous)\b|গত বছর|মোট রোগী", t)
        peak_q = re.search(r"\b(peak|season|when (is|does|will)|which month|busiest|worst month|time of year)\b|মৌসুম|কোন মাস|কখন", t)
        action_q = re.search(r"what (should|can|do) (we|i|the|officers?|authorities|council)|action|plan|recommend|preparedness|prepare|response|intervention|todo|করণীয়|পরিকল্পনা|প্রস্তুতি", t)

        if compare and (risk_q or top_q or compare):
            if len(ent.get("cities", [])) >= 2 or not ent.get("city"):
                return self._compare(L, ctx, ent)
        if time_q and (risk_q or peak_q or has_dengue or hist_q or ent.get("city")):
            return self._time_forecast(L, ctx, ent, c_city)
        if top_q and (risk_q or c_city or has_dengue or re.search(r"ward|ওয়ার্ড", t)):
            return self._top_wards(L, ctx, ent, c_city)
        if action_q and (c_city or ctx.get("intent", "").startswith(("risk", "top", "ward", "forecast"))):
            return self._actions(L, ctx, ent, c_city)
        if hist_q and not re.search(r"\bwill|next|future|forecast\b", t):
            return self._history(L, ctx, ent, c_city)
        if risk_q and (c_city or "horizon" in ent or ent.get("dhaka_ambiguous")):
            if ent.get("dhaka_ambiguous") and not ent.get("city"):
                return self._compare(L, ctx, {**ent, "cities": [c for c in cities if c.startswith("Dhaka")]})
            return self._city_risk(L, ctx, ent, c_city)
        if peak_q and re.search(r"\bdengue|\bcases|peak|ডেঙ্গু", t) and not re.search(r"\bvaccine\b", t):
            return self._season(L, ctx, ent)

        # 5. knowledge base
        tid, score = match_topic(t)
        if tid and score >= 1.0:
            if tid == "community" and (c_city or action_q) and ctx.get("intent", "").startswith(("risk", "top")):
                return self._actions(L, ctx, ent, c_city)
            return self._topic(L, ctx, tid, entities=ent)

        # 6. bare follow-ups using conversation memory ("what about Gazipur?", "and 8 weeks?", "why?")
        last = ctx.get("intent", "")
        if (ent.get("city") or "horizon" in ent) and last.startswith(("risk", "top", "ward", "forecast", "compare", "actions")):
            if last.startswith("top"):
                return self._top_wards(L, ctx, ent, c_city)
            return self._city_risk(L, ctx, ent, c_city)
        if re.fullmatch(r"(why|how come|explain|more|tell me more|details|আরও|কেন)\??", t) and last:
            if last.startswith(("risk", "top", "ward")):
                return self._drivers(L, ctx, ent, c_city)
            tid = last.split(":", 1)[1] if last.startswith("kb:") else None
            if tid in K.TOPICS and K.TOPICS[tid][L].get("follow_ups"):
                nxt = K.TOPICS[tid][L]["follow_ups"][0]
                return self._topic(L, ctx, nxt, entities=ent)
        if ent.get("dhaka_ambiguous"):
            return self._compare(L, ctx, {**ent, "cities": [c for c in cities if c.startswith("Dhaka")]})
        if ent.get("city"):
            return self._city_risk(L, ctx, ent, c_city)
        if has_dengue:
            return self._topic(L, ctx, "what_is", entities=ent)
        return self._pack(L, ctx, "fallback", K.SMALLTALK["fallback"][L], suggestions=self._chips(L))

    # -- safety ---------------------------------------------------------
    def _emergency(self, L, ctx, flags, ent):
        e = K.EMERGENCY[L]
        seen = self._t(L, "You mentioned: ", "আপনি উল্লেখ করেছেন: ") + ", ".join(FLAG_BN.get(f, f) if L == "bn" else f for f in flags)
        return self._pack(L, ctx, "emergency", seen, title=e["title"], bullets=e["body"] + [K.HOTLINES[L]], severity="emergency",
                          suggestions=self._chips(L, ["warning_signs", "home_care", "hotline"]), sources=["WHO dengue guidance"], entities=ent)

    def _symptom_check(self, L, ctx, t, ent, flags):
        m = re.search(r"(\d+)\s*(?:days?|din|দিন)|(one|two|three|four|five|six|seven)\s*days?", t)
        days = None
        if m:
            days = int(m.group(1)) if m.group(1) else NUM_WORDS[m.group(2)]
        high_risk = bool(re.search(r"pregnan|baby|infant|child|kid|toddler|elderly|old|diabet|heart|kidney|শিশু|গর্ভ|বয়স্ক|ডায়াবেটিস", t))
        b = []
        if days is not None:
            if days <= 5:
                b.append(self._t(L, f"Day {days} of fever: an NS1 antigen test is most useful now (first ~5 days).",
                                 f"জ্বরের {days} দিন: এখন এনএস১ অ্যান্টিজেন পরীক্ষাই সবচেয়ে কার্যকর (প্রথম ~৫ দিন)।"))
            else:
                b.append(self._t(L, f"Day {days} of fever: antibody (IgM/IgG) tests are more useful now, and the critical phase may be near - see a doctor today.",
                                 f"জ্বরের {days} দিন: এখন অ্যান্টিবডি (আইজিএম/আইজিজি) পরীক্ষা বেশি কার্যকর, আর ক্রিটিক্যাল ফেজ কাছাকাছি হতে পারে - আজই ডাক্তার দেখান।"))
        b += [self._t(L, "See a doctor (or a hospital outpatient unit) within 24 hours for assessment and a blood test, sooner if the fever is very high.",
                      "২৪ ঘণ্টার মধ্যে ডাক্তার/হাসপাতালের বহির্বিভাগে মূল্যায়ন ও রক্ত পরীক্ষা করান; জ্বর খুব বেশি হলে আরও আগে।"),
              self._t(L, "Drink plenty of fluids (ORS, water, coconut water) and rest. Paracetamol only as the label/doctor directs; no aspirin or ibuprofen.",
                      "প্রচুর তরল (ওআরএস, পানি, ডাবের পানি) পান করুন ও বিশ্রাম নিন। প্যারাসিটামল শুধু ওষুধের নির্দেশনা/চিকিৎসক অনুযায়ী; অ্যাসপিরিন বা আইবুপ্রোফেন নয়।"),
              self._t(L, "Sleep under a mosquito net so the patient does not infect others.", "মশারির ভেতরে ঘুমান, যাতে অন্যদের সংক্রমিত না করেন।"),
              self._t(L, "Go to hospital IMMEDIATELY for belly pain, repeated vomiting, any bleeding, drowsiness, fast breathing, cold skin or very little urine - especially when the fever settles.",
                      "পেটব্যথা, বারবার বমি, রক্তক্ষরণ, ঝিমুনি, দ্রুত শ্বাস, ঠান্ডা ত্বক বা প্রস্রাব খুব কম হলে - বিশেষ করে জ্বর কমে আসার সময় - সঙ্গে সঙ্গে হাসপাতালে যান।")]
        if high_risk:
            b.insert(0, self._t(L, "Because this involves a higher-risk person (child, pregnancy, older age or chronic illness), please see a doctor TODAY.",
                                "উচ্চ ঝুঁকির ব্যক্তি (শিশু, গর্ভবতী, বয়স্ক বা দীর্ঘমেয়াদি রোগী) হওয়ায় আজই ডাক্তার দেখান।"))
        city = ent.get("city") or ctx.get("city")
        return self._pack(L, ctx, "symptom_check", self._t(L, "I can't diagnose, but fever can be dengue - especially in the monsoon season. Here is what to do:",
                                                           "আমি রোগ নির্ণয় করতে পারি না, তবে জ্বর ডেঙ্গু হতে পারে - বিশেষ করে বর্ষা মৌসুমে। করণীয়:"),
                          title=self._t(L, "Fever: what to do now", "জ্বর: এখন কী করবেন"), bullets=b, severity="caution",
                          suggestions=self._chips(L, ["warning_signs", "testing", "home_care", "hotline"]), sources=["WHO dengue guidance"], new_ctx={"city": city}, entities=ent)

    def _help(self, L, ctx):
        return self._pack(L, ctx, "about", K.SMALLTALK["about_bot"][L], title=self._t(L, "About this assistant", "এই সহকারী সম্পর্কে"),
                          bullets=[self._t(L, "Dengue facts: symptoms, warning signs, prevention, care, testing, vaccines, myths", "ডেঙ্গু তথ্য: লক্ষণ, সতর্কসংকেত, প্রতিরোধ, যত্ন, পরীক্ষা, টিকা, ভুল ধারণা"),
                                   self._t(L, "Risk by city and ward, e.g. 'risk in Dhaka North next 4 weeks'", "শহর ও ওয়ার্ডভিত্তিক ঝুঁকি, যেমন 'ঢাকা উত্তরে আগামী ৪ সপ্তাহের ঝুঁকি'"),
                                   self._t(L, "Future seasons: 'forecast for August 2026', 'dengue next year'", "ভবিষ্যৎ মৌসুম: '২০২৬ সালের আগস্টের পূর্বাভাস'"),
                                   self._t(L, "What-ifs: 'what if rainfall doubles in Gazipur?'", "পরিস্থিতি: 'গাজীপুরে বৃষ্টি দ্বিগুণ হলে কী হবে?'"),
                                   self._t(L, "Model accuracy and data coverage", "মডেলের নির্ভুলতা ও ডেটার পরিধি"),
                                   self._t(L, "You can write in English or Bangla.", "আপনি ইংরেজি বা বাংলায় লিখতে পারেন।")])

    # -- data helpers ---------------------------------------------------
    def _stale(self) -> bool:
        return (self.b.today() - self.b.latest.date()).days > 12 * 7 + 7

    def _stale_note(self, L):
        lat = self.b.latest.date()
        weeks = (self.b.today() - lat).days // 7
        return self._t(L, f"Data note: observed data ends {lat:%d %b %Y} ({weeks} weeks ago), so for later dates I use seasonal long-range forecasts rather than the 12-week models.",
                       f"ডেটা নোট: পর্যবেক্ষিত ডেটা {lat:%d %b %Y} তারিখে শেষ ({weeks} সপ্তাহ আগে), তাই পরের তারিখের জন্য ১২ সপ্তাহের মডেলের বদলে মৌসুমি দীর্ঘমেয়াদি পূর্বাভাস ব্যবহার করি।")

    def _pick_city(self, ent, c_city):
        return c_city or self.b.cities[0]

    def _need_city(self, L, ctx, intent, ent):
        return self._pack(L, ctx, f"{intent}:ask_city", self._t(L, "Which city should I look at?", "কোন শহরের জন্য দেখব?"),
                          suggestions=[{"label": self._city_name(L, c), "text": c} for c in self.b.cities], entities=ent, disclaimer=False)

    def _horizon(self, ent, ctx, default=3):
        h = ent.get("horizon") or ctx.get("horizon") or default
        return max(1, min(12, int(h)))

    # -- city risk ------------------------------------------------------
    def _city_risk(self, L, ctx, ent, c_city):
        city = self._pick_city(ent, c_city)
        h = self._horizon(ent, ctx)
        if self._stale() and not ent.get("as_of"):
            # no data near "now": use the seasonal long-range forecast for the asked window starting today
            start = self.b.today()
            end = start + timedelta(weeks=h)
            return self._future_window(L, ctx, ent, city, start, end, label=self._t(L, f"next {h} weeks", f"আগামী {h} সপ্তাহ"), intent="forecast:city")
        d = self.b.risk(city, h, None, float(ent.get("rain_mult", 1.0)))
        wards = d["wards"]
        top = wards[:3]
        lvl = d["city_risk"]
        text = self._t(L, f"{city} is at {lvl.upper()} dengue risk for the week of {d['target_date']} ({h}-week outlook from {d['origin_date']}). Expected ≈{fmt(d['city_expected_cases'])} cases/week across {len(wards)} wards.",
                       f"{self._city_name(L, city)}-এ {d['target_date']} সপ্তাহের জন্য ডেঙ্গু ঝুঁকি {self._lvl(L, lvl)} ({d['origin_date']} থেকে {h} সপ্তাহের পূর্বাভাস)। {len(wards)}টি ওয়ার্ডে প্রত্যাশিত ≈{fmt(d['city_expected_cases'])} রোগী/সপ্তাহ।")
        cts = d["counts"]
        rows = [[w["ward_id"], self._lvl(L, w["risk"]), fmt(w["predicted_cases"])] for w in top]
        notes = [self._t(L, f"Wards: {cts['Critical']} Critical, {cts['High']} High, {cts['Medium']} Medium, {cts['Low']} Low.",
                         f"ওয়ার্ড: {cts['Critical']} সংকটজনক, {cts['High']} উচ্চ, {cts['Medium']} মাঝারি, {cts['Low']} নিম্ন।")]
        if d.get("backtest"):
            notes.append(self._t(L, "This date is inside the training data, so the numbers are an in-sample back-test and look better than real accuracy.", "এই তারিখ প্রশিক্ষণ ডেটার ভেতরে, তাই সংখ্যাগুলো ইন-স্যাম্পল ব্যাক-টেস্ট - বাস্তব নির্ভুলতার চেয়ে ভালো দেখায়।"))
        if d.get("rain_mult", 1.0) != 1.0:
            notes.append(self._t(L, f"Scenario: rainfall in the last 4 weeks scaled ×{d['rain_mult']}.", f"পরিস্থিতি: গত ৪ সপ্তাহের বৃষ্টি ×{d['rain_mult']} ধরা হয়েছে।"))
        return self._pack(L, ctx, "risk:city", text, title=self._t(L, f"Risk outlook - {city}", f"ঝুঁকির পূর্বাভাস - {self._city_name(L, city)}"),
                          table={"columns": [self._t(L, "Ward", "ওয়ার্ড"), self._t(L, "Risk", "ঝুঁকি"), self._t(L, "Exp. cases/wk", "প্রত্যাশিত রোগী/সপ্তাহ")], "rows": rows},
                          notes=notes, severity="caution" if lvl in ("High", "Critical") else "info",
                          suggestions=self._follow_data(L, city), sources=["Dengue Watch gradient-boosting model"],
                          new_ctx={"city": city, "horizon": h}, entities=ent)

    def _follow_data(self, L, city):
        return [{"label": self._t(L, f"Top wards in {city}", f"{self._city_name(L, city)}-এর শীর্ষ ওয়ার্ড"), "text": self._t(L, f"Top wards in {city}", f"{self._city_name(L, city)}-এর শীর্ষ ওয়ার্ড")},
                {"label": self._t(L, "What should we do?", "আমাদের করণীয় কী?"), "text": self._t(L, f"What should we do in {city}?", f"{self._city_name(L, city)}-এ আমাদের করণীয় কী?")},
                {"label": self._t(L, "If rain doubles", "বৃষ্টি দ্বিগুণ হলে"), "text": self._t(L, f"What if rainfall doubles in {city}?", f"{self._city_name(L, city)}-এ বৃষ্টি দ্বিগুণ হলে কী হবে?")},
                {"label": self._t(L, "Compare cities", "শহর তুলনা"), "text": self._t(L, "Compare cities", "শহর তুলনা করুন")}]

    # -- top wards ------------------------------------------------------
    def _top_wards(self, L, ctx, ent, c_city):
        city = c_city
        if not city:
            return self._need_city(L, ctx, "top", ent)
        h = self._horizon(ent, ctx)
        n = 5
        if self._stale():
            start = self.b.today(); end = start + timedelta(weeks=h)
            return self._future_window(L, ctx, ent, city, start, end, label=self._t(L, f"next {h} weeks", f"আগামী {h} সপ্তাহ"), intent="forecast:top", wards_focus=True)
        d = self.b.risk(city, h, None, float(ent.get("rain_mult", 1.0)))
        top = d["wards"][:n]
        rows = [[w["ward_id"], self._lvl(L, w["risk"]), fmt(w["predicted_cases"]), "; ".join(x["label"] for x in w["drivers"] if x["level"] == "high")[:60] or "-"] for w in top]
        return self._pack(L, ctx, "top:wards", self._t(L, f"Highest-risk wards in {city} for the week of {d['target_date']} ({h}-week outlook):", f"{self._city_name(L, city)}-এ {d['target_date']} সপ্তাহের ({h} সপ্তাহের পূর্বাভাস) সর্বোচ্চ ঝুঁকির ওয়ার্ড:"),
                          title=self._t(L, f"Top wards - {city}", f"শীর্ষ ওয়ার্ড - {self._city_name(L, city)}"),
                          table={"columns": [self._t(L, "Ward", "ওয়ার্ড"), self._t(L, "Risk", "ঝুঁকি"), self._t(L, "Exp. cases/wk", "প্রত্যাশিত রোগী/সপ্তাহ"), self._t(L, "Main drivers", "প্রধান কারণ")], "rows": rows},
                          notes=[d["risk_note"]], suggestions=[{"label": self._t(L, f"Details: {top[0]['ward_id']}", f"বিস্তারিত: {top[0]['ward_id']}"), "text": top[0]["ward_id"]}] + self._follow_data(L, city)[1:3] if top else None,
                          sources=["Dengue Watch gradient-boosting model"], new_ctx={"city": city, "horizon": h, "ward_id": top[0]["ward_id"] if top else None}, entities=ent)

    # -- ward detail ----------------------------------------------------
    def _ward(self, L, ctx, ent, c_city):
        city = c_city
        ward_id = ent.get("ward_id")
        if ward_id:
            city = ent["city"]
        elif not city:
            return self._need_city(L, ctx, "ward", ent)
        h = self._horizon(ent, ctx)
        if self._stale():
            h_data = 12  # still show ward vulnerability profile from the latest observed week
        d = self.b.risk(city, min(h, 12), None, float(ent.get("rain_mult", 1.0)))
        if ward_id is None:
            ward_id = next((w["ward_id"] for w in d["wards"] if w["ward_id"].endswith(f"_{ent['ward_no']:02d}")), None)
        w = next((x for x in d["wards"] if x["ward_id"] == ward_id), None)
        if not w:
            ex = ", ".join(x["ward_id"] for x in d["wards"][:3])
            return self._pack(L, ctx, "ward:notfound", self._t(L, f"I couldn't find that ward in {city}. Wards look like {ex}…", f"{self._city_name(L, city)}-এ ওই ওয়ার্ড পাইনি। ওয়ার্ড আইডি যেমন {ex}…"), new_ctx={"city": city}, entities=ent)
        rank = [x["ward_id"] for x in d["wards"]].index(ward_id) + 1
        b = [f"{x['label']}: {x['detail']}" for x in w["drivers"]]
        b.append(self._t(L, f"Profile: water-logging index {w['water_logging_risk_index']}, sanitation {w['sanitation_score']}, {w['population_density_sqkm']:,} people/km².",
                         f"প্রোফাইল: জলাবদ্ধতা সূচক {w['water_logging_risk_index']}, স্যানিটেশন {w['sanitation_score']}, জনঘনত্ব {w['population_density_sqkm']:,}/বর্গ কিমি।"))
        text = self._t(L, f"{ward_id} ({city}) ranks #{rank} of {len(d['wards'])}: {w['risk'].upper()} risk, ≈{fmt(w['predicted_cases'])} expected cases for the week of {d['target_date']}.",
                       f"{ward_id} ({self._city_name(L, city)}) {len(d['wards'])}টির মধ্যে #{rank}: ঝুঁকি {self._lvl(L, w['risk'])}, {d['target_date']} সপ্তাহে প্রত্যাশিত ≈{fmt(w['predicted_cases'])} রোগী।")
        notes = []
        if self._stale():
            notes.append(self._stale_note(L)+ self._t(L, " This ward view shows the latest observed week.", " এই ওয়ার্ড-দৃশ্যে সর্বশেষ পর্যবেক্ষিত সপ্তাহ দেখানো হয়েছে।"))
        if w.get("actual_cases") is not None:
            notes.append(self._t(L, f"Reported at that week: {w['actual_cases']} cases (in-sample).", f"ওই সপ্তাহে রিপোর্টকৃত: {w['actual_cases']} রোগী (ইন-স্যাম্পল)।"))
        return self._pack(L, ctx, "ward:detail", text, title=ward_id, bullets=b, notes=notes, severity="caution" if w["risk"] in ("High", "Critical") else "info",
                          suggestions=self._follow_data(L, city)[:3], sources=["Dengue Watch gradient-boosting model"], new_ctx={"city": city, "ward_id": ward_id, "horizon": h}, entities=ent)

    def _drivers(self, L, ctx, ent, c_city):
        city = c_city
        if not city:
            return self._need_city(L, ctx, "risk", ent)
        d = self.b.risk(city, self._horizon(ent, ctx), None, 1.0)
        ward = None
        if ctx.get("ward_id"):
            ward = next((w for w in d["wards"] if w["ward_id"] == ctx["ward_id"]), None)
        counts: dict[str, int] = {}
        pool = [ward] if ward else d["wards"]
        for w in pool:
            for x in w["drivers"]:
                if x["level"] == "high":
                    counts[x["label"]] = counts.get(x["label"], 0) + 1
        items = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
        b = [self._t(L, f"{k}: {v} of {len(pool)} ward(s)", f"{k}: {len(pool)}টির মধ্যে {v}টি ওয়ার্ড") for k, v in items] or [self._t(L, "No strong risk driver in this window.", "এই সময়ে কোনো শক্তিশালী ঝুঁকির কারণ নেই।")]
        b.append(K.TOPICS["rain_link"][L]["body"][1])
        return self._pack(L, ctx, "risk:drivers", self._t(L, f"What is driving risk in {city}:", f"{self._city_name(L, city)}-এ ঝুঁকির কারণ:"), bullets=b, new_ctx={"city": city}, entities=ent, suggestions=self._follow_data(L, city)[:3])

    # -- compare --------------------------------------------------------
    def _compare(self, L, ctx, ent):
        cities = ent.get("cities") or list(self.b.cities)
        h = self._horizon(ent, ctx)
        rows, order = [], []
        if self._stale():
            start = self.b.today(); end = start + timedelta(weeks=h)
            for c in cities:
                f = self.b.future(c, start, end, 1.0, 0.0)
                tot = sum(w["expected"] for w in f["weekly"])
                lo = sum(w["p10"] for w in f["weekly"]); hi = sum(w["p90"] for w in f["weekly"])
                order.append((c, tot)); rows.append([c, n0(tot), f"{n0(lo)}-{n0(hi)}", str(len(f["wards"]))])
            cols = [self._t(L, "City", "শহর"), self._t(L, f"Expected cases ({h} wk)", f"প্রত্যাশিত রোগী ({h} সপ্তাহ)"), self._t(L, "Plausible range", "সম্ভাব্য পরিসর"), self._t(L, "Wards", "ওয়ার্ড")]
            notes = [self._stale_note(L)]
        else:
            for c in cities:
                d = self.b.risk(c, h, None, 1.0)
                order.append((c, d["city_expected_cases"]))
                rows.append([c, self._lvl(L, d["city_risk"]), fmt(d["city_expected_cases"]), f"{d['counts']['Critical'] + d['counts']['High']}/{len(d['wards'])}"])
            cols = [self._t(L, "City", "শহর"), self._t(L, "Risk", "ঝুঁকি"), self._t(L, "Exp. cases/wk", "প্রত্যাশিত রোগী/সপ্তাহ"), self._t(L, "High+Critical wards", "উচ্চ+সংকটজনক ওয়ার্ড")]
            notes = []
        order.sort(key=lambda x: -x[1])
        rows.sort(key=lambda r: [c for c, _ in order].index(r[0]))
        text = self._t(L, f"Over the next {h} weeks, {order[0][0]} is expected to have the most dengue activity.", f"আগামী {h} সপ্তাহে {self._city_name(L, order[0][0])}-এ ডেঙ্গুর প্রকোপ সবচেয়ে বেশি হওয়ার সম্ভাবনা।")
        notes.append(self._t(L, "Totals are not adjusted for population or number of wards (Dhaka North/South have 20 wards each, Gazipur/Narayanganj 5).", "মোট সংখ্যা জনসংখ্যা বা ওয়ার্ড-সংখ্যা অনুযায়ী সমন্বয় করা নয় (ঢাকা উত্তর/দক্ষিণে ২০টি করে, গাজীপুর/নারায়ণগঞ্জে ৫টি করে ওয়ার্ড)।"))
        return self._pack(L, ctx, "compare", text, title=self._t(L, "City comparison", "শহরের তুলনা"), table={"columns": cols, "rows": rows}, notes=notes,
                          new_ctx={"horizon": h}, entities=ent, suggestions=[{"label": self._city_name(L, c), "text": c} for c, _ in order[:4]], sources=["Dengue Watch models"])

    # -- future / month / year -----------------------------------------
    def _time_forecast(self, L, ctx, ent, c_city):
        city = "All" if ent.get("all_cities") else (c_city or "All")
        today = self.b.today()
        year, month = ent.get("year"), ent.get("month")
        if ent.get("next_season") and not month:
            year = year or (today.year if today.month <= 7 else today.year + 1)
            month = 8
        if year is None and month is not None:
            year = today.year if month >= today.month else today.year + 1
        if year is None:
            return self._season(L, ctx, ent)
        latest = self.b.latest
        if month:
            start = date(year, month, 1)
            end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
            label = f"{MONTH_NAMES[month]} {year}"
        else:
            start, end = date(year, 1, 1), date(year, 12, 31)
            label = str(year)
        if end <= latest.date():
            return self._history(L, ctx, {**ent, "year": year, "month": month}, c_city)
        if start <= latest.date():
            start = latest.date() + timedelta(days=1)
        if end > date(2030, 12, 31):
            return self._pack(L, ctx, "forecast:range", self._t(L, "The long-range forecast only goes up to 2030, and accuracy falls quickly with distance. Try a nearer date.", "দীর্ঘমেয়াদি পূর্বাভাস ২০৩০ পর্যন্ত, এবং দূরত্বের সাথে নির্ভুলতা কমে। কাছের কোনো তারিখ চেষ্টা করুন।"), entities=ent)
        return self._future_window(L, ctx, ent, city, start, end, label=label, intent="forecast:time")

    def _future_window(self, L, ctx, ent, city, start, end, label, intent, wards_focus=False):
        rain = float(ent.get("rain_mult", 1.0)); temp = float(ent.get("temp_shift", 0.0))
        f = self.b.future(city, start, end, rain, temp)
        wk = f["weekly"]
        if not wk:
            return self._pack(L, ctx, intent, self._t(L, "No forecast weeks fall inside that window.", "ওই সময়ে কোনো পূর্বাভাস সপ্তাহ নেই।"), entities=ent)
        tot = sum(w["expected"] for w in wk); lo = sum(w["p10"] for w in wk); hi = sum(w["p90"] for w in wk)
        peak = max(wk, key=lambda w: w["expected"])
        where = self._city_name(L, city) if city != "All" else self._t(L, "all 5 cities", "৫টি শহর মিলিয়ে")
        text = self._t(L, f"{label} ({where}): ≈{n0(tot)} reported dengue cases expected (plausible weather range ≈{n0(lo)}-{n0(hi)}). Busiest week ≈ {peak['date']} with ≈{n0(peak['expected'])} cases.",
                       f"{label} ({where}): প্রায় {n0(tot)} রোগী প্রত্যাশিত (আবহাওয়াভেদে সম্ভাব্য পরিসর ≈{n0(lo)}-{n0(hi)})। সবচেয়ে ব্যস্ত সপ্তাহ ≈ {peak['date']}, প্রায় {n0(peak['expected'])} রোগী।")
        if tot < 3 * max(1, len(wk)) and peak["expected"] < 8:
            text += self._t(L, " That is the low season - cases usually start rising again in May-June.", " এটি কম সংক্রমণের মৌসুম - সাধারণত মে-জুনে রোগী আবার বাড়তে শুরু করে।")
        rows = []
        for w in f["wards"][:5]:
            rows.append([w["ward_id"], n0(w["expected_total"]), w["peak_week"], self._lvl(L, w["peak_risk"])])
        acc = f.get("accuracy_summary") or {}
        notes = [self._t(L, "Long-range forecasts show a typical season for the plausible weather range - they can't say which specific week an outbreak will hit, and can't foresee new serotypes or control campaigns.",
                         "দীর্ঘমেয়াদি পূর্বাভাস সম্ভাব্য আবহাওয়ায় একটি সাধারণ মৌসুম দেখায় - কোন সপ্তাহে প্রাদুর্ভাব হবে তা বলতে পারে না, নতুন সেরোটাইপ বা নিয়ন্ত্রণ কর্মসূচিও আগাম বোঝে না।")]
        if acc:
            notes.append(self._t(L, f"Held-out check: yearly totals were off by -16% to +26%; city-week R² ≈ {acc['city_week_R2']}.", f"হেল্ড-আউট পরীক্ষা: বার্ষিক মোট -১৬% থেকে +২৬% ভুল ছিল; সিটি-সপ্তাহ R² ≈ {acc['city_week_R2']}।"))
        if rain != 1.0 or temp != 0.0:
            notes.append(self._t(L, f"Scenario: rainfall ×{rain}, temperature {temp:+.1f} °C.", f"পরিস্থিতি: বৃষ্টি ×{rain}, তাপমাত্রা {temp:+.1f} °C।"))
        if self._stale():
            notes.append(self._stale_note(L))
        ttl = (self._t(L, f"Top wards - {where} ({label})", f"শীর্ষ ওয়ার্ড - {where} ({label})") if wards_focus else self._t(L, f"Forecast - {label}", f"পূর্বাভাস - {label}"))
        return self._pack(L, ctx, intent, text, title=ttl,
                          table={"columns": [self._t(L, "Ward", "ওয়ার্ড"), self._t(L, "Expected total", "প্রত্যাশিত মোট"), self._t(L, "Peak week", "শীর্ষ সপ্তাহ"), self._t(L, "Peak risk", "শীর্ষ ঝুঁকি")], "rows": rows} if rows else None,
                          notes=notes, severity="info", suggestions=self._follow_data(L, city if city != "All" else self.b.cities[0])[:4], sources=["Dengue Watch long-range weather-scenario forecast"],
                          new_ctx={"city": city if city != "All" else None, "year": start.year, "month": start.month if (end - start).days < 40 else None}, entities=ent)

    # -- what-if --------------------------------------------------------
    def _whatif(self, L, ctx, ent, c_city):
        city = c_city
        if not city:
            return self._need_city(L, ctx, "whatif", ent)
        h = self._horizon(ent, ctx)
        mult = float(ent.get("rain_mult", 1.0))
        temp = float(ent.get("temp_shift", 0.0))
        notes = []
        today = self.b.today()
        if ent.get("year") or ent.get("month"):
            year = ent.get("year") or (today.year if (ent.get("month") or 1) >= today.month else today.year + 1)
            month = ent.get("month")
            start = date(year, month or 1, 1)
            end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1) if month else date(year, 12, 31)
            label = f"{MONTH_NAMES[month]} {year}" if month else str(year)
            use_future = True
        elif self._stale():
            start = today; end = start + timedelta(weeks=h)
            label = self._t(L, f"the next {h} weeks", f"আগামী {h} সপ্তাহ"); use_future = True
        else:
            use_future = False
        if use_future:
            if start <= self.b.latest.date():
                start = self.b.latest.date() + timedelta(days=1)
            def total(r, t):
                return sum(w["expected"] for w in self.b.future(city, start, end, r, t)["weekly"])
            b0 = total(1.0, 0.0)
            if b0 < 5 and not (ent.get("year") or ent.get("month")):
                # off-season: a rain scenario means nothing, so switch to the coming peak season
                year = today.year if today.month <= 8 else today.year + 1
                start, end, label = date(year, 7, 1), date(year, 9, 30), self._t(L, f"the {year} peak season (Jul-Sep)", f"{year} সালের শীর্ষ মৌসুম (জুলাই-সেপ্টেম্বর)")
                b0 = total(1.0, 0.0)
                notes.append(self._t(L, "It is currently the low season, so I tested the scenario on the coming peak season instead.", "এখন কম সংক্রমণের মৌসুম, তাই পরিস্থিতিটি আসন্ন শীর্ষ মৌসুমে পরীক্ষা করেছি।"))
            b1 = total(mult, temp)
            if self._stale():
                notes.append(self._stale_note(L))
        else:
            label = self._t(L, f"the next {h} weeks", f"আগামী {h} সপ্তাহ")
            b0 = self.b.risk(city, h, None, 1.0)["city_expected_cases"]; b1 = self.b.risk(city, h, None, mult)["city_expected_cases"]
        pct = ((b1 - b0) / b0 * 100) if b0 else 0.0
        sc = self._t(L, f"rainfall ×{mult}", f"বৃষ্টি ×{mult}") + (f", {temp:+.1f} °C" if temp else "")
        text = self._t(L, f"If {sc} in {city}, expected cases for {label} go from ≈{n0(b0)} to ≈{n0(b1)} ({pct:+.0f}%).",
                       f"{self._city_name(L, city)}-এ {sc} হলে {label}-এ প্রত্যাশিত রোগী ≈{n0(b0)} থেকে ≈{n0(b1)} ({pct:+.0f}%)।")
        notes.append(self._t(L, "What-if scenarios show the model's sensitivity to weather - they are not forecasts of what will happen.", "'কী হবে যদি' পরিস্থিতি আবহাওয়ার প্রতি মডেলের সংবেদনশীলতা দেখায় - এগুলো ভবিষ্যদ্বাণী নয়।"))
        return self._pack(L, ctx, "whatif", text, title=self._t(L, "Weather scenario", "আবহাওয়ার পরিস্থিতি"), notes=notes, new_ctx={"city": city, "horizon": h, "rain_mult": mult},
                          suggestions=self._follow_data(L, city)[:3], sources=["Dengue Watch models"], entities=ent)

    # -- history / season ----------------------------------------------
    def _history(self, L, ctx, ent, c_city):
        city = "All" if ent.get("all_cities") else (c_city or "All")
        year, month = ent.get("year"), ent.get("month")
        if year is None:
            s = self.b.season(city)
            yrs = s["yearly"]
            worst = max(yrs, key=yrs.get); best = min(yrs, key=yrs.get)
            rows = [[str(y), fmt(v, 0)] for y, v in sorted(yrs.items())]
            where = self._city_name(L, city) if city != "All" else self._t(L, "all 5 cities", "৫ শহর মিলিয়ে")
            return self._pack(L, ctx, "history:yearly", self._t(L, f"Reported dengue cases per year ({where}). Worst year {worst}: {fmt(yrs[worst], 0)}; lowest {best}: {fmt(yrs[best], 0)}.",
                                                                 f"বছরভিত্তিক রিপোর্টকৃত ডেঙ্গু রোগী ({where})। সবচেয়ে খারাপ বছর {worst}: {fmt(yrs[worst], 0)}; সবচেয়ে কম {best}: {fmt(yrs[best], 0)}।"),
                              title=self._t(L, "Historical cases", "ঐতিহাসিক রোগীসংখ্যা"), table={"columns": [self._t(L, "Year", "বছর"), self._t(L, "Cases", "রোগী")], "rows": rows},
                              notes=[self._t(L, "Cases come from the project's dataset, not live official surveillance.", "সংখ্যাগুলো প্রকল্পের ডেটাসেট থেকে, সরাসরি সরকারি নজরদারি নয়।")],
                              new_ctx={"city": c_city}, entities=ent, sources=["Project dataset 2016-2025"])
        if month:
            start = date(year, month, 1); end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1); label = f"{MONTH_NAMES[month]} {year}"
        else:
            start, end, label = date(year, 1, 1), date(year, 12, 31), str(year)
        if start < date(2016, 1, 1) or start > self.b.latest.date():
            return self._pack(L, ctx, "history:range", self._t(L, f"My dataset covers {self.b.info()['start']} to {self.b.info()['end']}.", f"আমার ডেটাসেট {self.b.info()['start']} থেকে {self.b.info()['end']} পর্যন্ত।"), entities=ent)
        a = self.b.actuals(city, start, end)
        where = self._city_name(L, city) if city != "All" else self._t(L, "all 5 cities", "৫ শহর মিলিয়ে")
        rows = [[w, fmt(v, 0)] for w, v in a["top_wards"]]
        return self._pack(L, ctx, "history:period", self._t(L, f"{label} ({where}): {fmt(a['total'], 0)} reported cases; busiest week {a['peak_week']} with {fmt(a['peak_cases'], 0)}.",
                                                            f"{label} ({where}): মোট {fmt(a['total'], 0)} রোগী; সবচেয়ে ব্যস্ত সপ্তাহ {a['peak_week']}, {fmt(a['peak_cases'], 0)} রোগী।"),
                          title=self._t(L, f"Reported cases - {label}", f"রিপোর্টকৃত রোগী - {label}"), table={"columns": [self._t(L, "Ward", "ওয়ার্ড"), self._t(L, "Cases", "রোগী")], "rows": rows},
                          notes=[self._t(L, "Cases come from the project's dataset, not live official surveillance.", "সংখ্যাগুলো প্রকল্পের ডেটাসেট থেকে, সরাসরি সরকারি নজরদারি নয়।")],
                          new_ctx={"city": c_city}, entities=ent, sources=["Project dataset 2016-2025"])

    def _season(self, L, ctx, ent):
        city = (ent or {}).get("city") or ctx.get("city") or "All"
        s = self.b.season(city)
        sh = s["monthly_share"]
        top3 = sorted(sh, key=sh.get, reverse=True)[:3]
        names = ", ".join(MONTH_NAMES[m] for m in sorted(top3))
        pct = sum(sh[m] for m in top3)
        base = K.TOPICS["season"][L]["body"][0]
        text = self._t(L, f"In the project data, {fmt(pct, 0)}% of cases fall in {names}; the single peak month is {MONTH_NAMES[s['peak_month']]}. Cases are near zero from November to February.",
                       f"প্রকল্পের ডেটায় {names} মাসে মোট রোগীর {fmt(pct, 0)}%; সর্বোচ্চ মাস {MONTH_NAMES[s['peak_month']]}। নভেম্বর থেকে ফেব্রুয়ারি প্রায় শূন্য।")
        rows = [[MONTH_NAMES[m][:3], f"{sh[m]:.1f}%"] for m in range(1, 13)]
        return self._pack(L, ctx, "kb:season", text, title=K.TOPICS["season"][L]["title"], bullets=[base], table={"columns": [self._t(L, "Month", "মাস"), self._t(L, "Share of annual cases", "বার্ষিক রোগীর অংশ")], "rows": rows},
                          suggestions=self._chips(L, ["rain_link", "prevention", "breeding"]), sources=["Project dataset 2016-2025"], new_ctx={"city": ent.get("city") if ent else None}, entities=ent)

    def _actions(self, L, ctx, ent, c_city):
        city = c_city
        if not city:
            return self._need_city(L, ctx, "actions", ent)
        h = self._horizon(ent, ctx)
        if self._stale():
            start = self.b.today(); end = start + timedelta(weeks=h)
            f = self.b.future(city, start, end, 1.0, 0.0)
            peak = max((w["expected"] for w in f["weekly"]), default=0)
            per_ward = peak / max(1, len(f["wards"]))
            lvl = "Critical" if per_ward >= 9 else "High" if per_ward >= 5 else "Medium" if per_ward >= 2 else "Low"
            basis = self._t(L, f"seasonal outlook for the next {h} weeks (≈{n0(peak)} cases at peak week)", f"আগামী {h} সপ্তাহের মৌসুমি পূর্বাভাস (শীর্ষ সপ্তাহে ≈{n0(peak)} রোগী)")
            top_ids = [w["ward_id"] for w in f["wards"][:3]]
        else:
            d = self.b.risk(city, h, None, 1.0)
            lvl = d["city_risk"]; top_ids = [w["ward_id"] for w in d["wards"][:3]]
            basis = self._t(L, f"{h}-week model outlook", f"{h} সপ্তাহের মডেল পূর্বাভাস")
        plan = {
            "Critical": (["Activate the dengue response: daily ward-level larval surveys and larviciding in the top wards", "Alert hospitals to open extra dengue beds, IV-fluid stock and triage desks now",
                          "Clear drains/water-logging and inspect all construction sites this week", "Daily risk messages (Bangla) on warning signs and 'no NSAIDs'"],
                         ["ডেঙ্গু প্রতিরোধ কার্যক্রম চালু করুন: শীর্ষ ওয়ার্ডে প্রতিদিন লার্ভা জরিপ ও লার্ভিসাইডিং", "হাসপাতালকে অতিরিক্ত ডেঙ্গু বেড, আইভি স্যালাইন মজুদ ও ট্রায়াজ ডেস্ক এখনই প্রস্তুত রাখতে জানান",
                          "এ সপ্তাহে ড্রেন/জলাবদ্ধতা পরিষ্কার ও সব নির্মাণস্থল পরিদর্শন করুন", "সতর্কসংকেত ও 'NSAID নয়' নিয়ে প্রতিদিন বাংলায় বার্তা দিন"]),
            "High": (["Weekly breeding-site clean-up in the top wards, with inspections of schools, markets and construction sites", "Pre-position hospital capacity and lab kits for the next 1-3 weeks",
                      "Targeted larviciding where water-logging or sanitation is poor", "Community messages: weekly container checks, repellent, early care-seeking"],
                     ["শীর্ষ ওয়ার্ডে সাপ্তাহিক প্রজননস্থল পরিষ্কার এবং স্কুল, বাজার ও নির্মাণস্থল পরিদর্শন", "আগামী ১-৩ সপ্তাহের জন্য হাসপাতালের সক্ষমতা ও ল্যাব কিট আগাম প্রস্তুত রাখুন",
                      "জলাবদ্ধতা বা স্যানিটেশন খারাপ এমন জায়গায় লক্ষ্যভিত্তিক লার্ভিসাইডিং", "জনসচেতনতা: সাপ্তাহিক পাত্র পরীক্ষা, মশা-নিরোধক, দ্রুত চিকিৎসা নেওয়া"]),
            "Medium": (["Routine weekly inspection and clean-up drives; focus on wards with rising cases", "Check that hospitals and labs can scale up if rain continues", "Begin awareness messaging before the rainy peak"],
                       ["নিয়মিত সাপ্তাহিক পরিদর্শন ও পরিচ্ছন্নতা অভিযান; রোগী বাড়ছে এমন ওয়ার্ডে মনোযোগ দিন", "বৃষ্টি চলতে থাকলে হাসপাতাল ও ল্যাব বাড়তি চাপ সামলাতে পারবে কি না দেখুন", "বর্ষার শীর্ষের আগেই সচেতনতা বার্তা শুরু করুন"]),
            "Low": (["Maintain surveillance and routine household container checks", "Use the quiet period to fix drains, service water tanks and train volunteers", "Keep stock of test kits and fluids ready for the next season"],
                    ["নজরদারি ও বাড়ির পাত্র পরীক্ষা চালু রাখুন", "শান্ত সময়ে ড্রেন মেরামত, পানির ট্যাংক সার্ভিস ও স্বেচ্ছাসেবক প্রশিক্ষণ দিন", "পরবর্তী মৌসুমের জন্য টেস্ট কিট ও স্যালাইন মজুদ রাখুন"]),
        }
        en, bn = plan[lvl]
        bl = list(bn if L == "bn" else en)
        if top_ids:
            bl.insert(0, self._t(L, "Start with: " + ", ".join(top_ids), "শুরু করুন এগুলো দিয়ে: " + ", ".join(top_ids)))
        return self._pack(L, ctx, "actions", self._t(L, f"Suggested response for {city} at {lvl.upper()} level, based on the {basis}:", f"{self._city_name(L, city)}-এর জন্য {self._lvl(L, lvl)} স্তরে প্রস্তাবিত পদক্ষেপ ({basis} অনুযায়ী):"),
                          title=self._t(L, "Action plan", "করণীয় পরিকল্পনা"), bullets=bl, notes=[self._t(L, "Decision support only - follow your city corporation and DGHS directives.", "এটি শুধু সিদ্ধান্ত-সহায়তা - সিটি কর্পোরেশন ও স্বাস্থ্য অধিদপ্তরের নির্দেশনা মানুন।")],
                          new_ctx={"city": city, "horizon": h}, entities=ent, suggestions=self._follow_data(L, city)[:3], sources=["Dengue Watch models", "WHO vector control guidance"])

    def _accuracy(self, L, ctx, ent):
        h = self._horizon(ent, ctx, 3)
        a = self.b.accuracy(h)
        m = a.get("metrics", {})
        b = []
        if m:
            b += [self._t(L, f"Average error ≈ {m.get('MAE')} cases per ward-week; R² = {m.get('R2')} (ward-week) and {m.get('R2_city_week')} (city-week).", f"গড় ত্রুটি ≈ {m.get('MAE')} রোগী/ওয়ার্ড-সপ্তাহ; R² = {m.get('R2')} (ওয়ার্ড-সপ্তাহ), {m.get('R2_city_week')} (সিটি-সপ্তাহ)।"),
                  self._t(L, f"Outbreak detection (≥10 cases in a ward-week): AUC {m.get('AUC_outbreak_ge10')}.", f"প্রাদুর্ভাব শনাক্তকরণ (এক ওয়ার্ড-সপ্তাহে ≥১০ রোগী): AUC {m.get('AUC_outbreak_ge10')}।")]
        c = a.get("classification")
        if c:
            b.append(self._t(L, f"At the default alarm threshold ({c['t']} predicted cases): precision {c['precision']:.2f}, recall {c['recall']:.2f}, F1 {c['f1']:.2f}.", f"ডিফল্ট অ্যালার্ম সীমায় ({c['t']} পূর্বাভাসিত রোগী): precision {c['precision']:.2f}, recall {c['recall']:.2f}, F1 {c['f1']:.2f}।"))
        b.append(self._t(L, "Tested on 2023-2025 data held out from training. Long-range yearly totals were off by -16% to +26%.", "২০২৩-২০২৫ সালের ডেটায় পরীক্ষা, যা প্রশিক্ষণে ব্যবহৃত হয়নি। দীর্ঘমেয়াদি বার্ষিক মোট -১৬% থেকে +২৬% ভুল ছিল।"))
        b.append(self._t(L, "Risk bands are simple thresholds on expected cases, not calibrated probabilities. The model can't see outbreaks that are not in its data.", "ঝুঁকির স্তর প্রত্যাশিত রোগীর সরল সীমা, ক্যালিব্রেটেড সম্ভাবনা নয়। ডেটায় নেই এমন প্রাদুর্ভাব মডেল দেখতে পায় না।"))
        return self._pack(L, ctx, "accuracy", self._t(L, f"Model: {a.get('model')}. Held-out accuracy for the {h}-week-ahead model:", f"মডেল: {a.get('model')}। {h} সপ্তাহ-আগের মডেলের হেল্ড-আউট নির্ভুলতা:"),
                          title=self._t(L, "How accurate is the model?", "মডেল কতটা নির্ভুল?"), bullets=b, entities=ent, new_ctx={"horizon": h}, sources=["artifacts/results.json", "artifacts/classification_metrics.json"], suggestions=self._chips(L, ["season", "rain_link"]))

    def _data_info(self, L, ctx):
        i = self.b.info()
        b = [self._t(L, f"{i['wards']} wards in {len(i['cities'])} cities: {', '.join(i['cities'])}.", f"{len(i['cities'])}টি শহরের {i['wards']}টি ওয়ার্ড: {', '.join(CITY_BN.get(c, c) for c in i['cities'])}।"),
             self._t(L, f"Weekly data from {i['start']} to {i['end']}: cases, weather, ward profile (density, sanitation, water-logging).", f"সাপ্তাহিক ডেটা {i['start']} থেকে {i['end']}: রোগী, আবহাওয়া, ওয়ার্ড প্রোফাইল (ঘনত্ব, স্যানিটেশন, জলাবদ্ধতা)।"),
             self._t(L, "It is a research dataset bundled with this project, not live official surveillance.", "এটি প্রকল্পের সঙ্গে দেওয়া গবেষণা ডেটাসেট, সরাসরি সরকারি নজরদারি নয়।")]
        if self._stale():
            b.append(self._stale_note(L))
        return self._pack(L, ctx, "data_info", self._t(L, "About the data behind the forecasts:", "পূর্বাভাসের পেছনের ডেটা সম্পর্কে:"), bullets=b, sources=["Project dataset"], suggestions=self._chips(L, ["season"]))
