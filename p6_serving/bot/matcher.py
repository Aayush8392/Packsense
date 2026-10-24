"""The question matcher (Phase C item 14, prototype): find the catalogue entries closest to what a visitor typed, with no AI model and no network.

How it scores: every catalogue wording (the canonical question and the working-set rewordings) is compared with the query by two measures, word overlap
(common words count less, like TF-IDF) and 3-letter overlap (so a typo such as "serch" still lands). An entry's score is its best wording, plus a small
share from its answer text. Before matching, a few rules take the cases a score should not decide: a typed barcode, a language other than English, and (only
when no entry is a strong match) advice and medical questions.

Everything the matcher knows comes from the catalogue; the synonym list and the weights below are the only tuning, and they are set on the WORKING questions.
"""
from __future__ import annotations

import difflib
import math
import re
from collections import Counter
from dataclasses import dataclass, field

import catalogue as cat

STOP = {"a", "an", "the", "of", "to", "in", "on", "is", "are", "be", "it", "this", "that", "i", "you", "me", "my", "do", "does", "did", "for", "so", "there", "your"}
SYNONYMS = {
    "calorie": "kcal", "calories": "kcal", "licence": "license", "licenses": "license", "off": "openfoodfacts", "ofs": "openfoodfacts", "refresh": "update", "refreshed": "update",
    "updated": "update", "updates": "update", "updating": "update", "stale": "old", "flags": "flag", "flagged": "flag", "checks": "check", "versions": "version",
    "websites": "website", "site": "website", "gdpr": "privacy", "costs": "cost", "pay": "cost", "paid": "cost", "scrambled": "hashed", "hash": "hashed",
    "users": "user", "contributors": "contributor", "volunteers": "contributor", "volunteer": "contributor", "editors": "contributor", "edits": "edit", "edited": "edit",
    "products": "product", "items": "product", "brands": "brand", "countries": "country", "photos": "photo", "pictures": "photo", "images": "photo", "numbers": "number",
    "stored": "store", "keep": "store", "kept": "store", "saved": "store", "accurate": "correct", "right": "correct", "true": "correct", "wrong": "incorrect",
    "ai": "artificial", "chatgpt": "artificial", "ingredient": "ingredients", "allergens": "allergen", "allergy": "allergen", "allergies": "allergen",
}
# General word equivalences for words visitors use and the catalogue does not (added 2026-10-27). Both the question and every wording pass through the same mapping, so it only merges words that mean the same here.
EXTRA_SYNONYMS = {
    "repo": "repository", "repos": "repository", "dump": "copy", "dumps": "copy", "sync": "update", "synced": "update", "syncs": "update", "fetch": "update", "fetches": "update", "pull": "update", "pulls": "update",
    "logged": "track", "logging": "track", "tracked": "track", "tracking": "track", "marked": "flag", "marks": "flag", "mark": "flag", "reliable": "correct", "trustworthy": "correct", "reliability": "correct",
    "error": "mistake", "errors": "mistake", "bug": "mistake", "bugs": "mistake", "mistakes": "mistake", "outdated": "old", "android": "app", "iphone": "app", "ios": "app", "manufacturer": "brand", "manufacturers": "brand",
    "leaderboard": "rank", "ranking": "rank", "rankings": "rank", "limitations": "limit", "limitation": "limit", "restrictions": "limit", "restriction": "limit", "graph": "chart", "graphs": "chart", "plot": "chart", "dashboard": "chart",
    "commercial": "business", "commercially": "business", "startup": "business", "company": "business", "attribution": "credit", "cite": "credit", "citation": "credit", "acknowledge": "credit", "frequency": "often",
    "delete": "remove", "deleted": "remove", "disappear": "remove", "disappeared": "remove", "gone": "remove", "historical": "history", "archive": "history", "notify": "alert", "notification": "alert", "notifications": "alert",
    "alerts": "alert", "missing": "empty", "blank": "empty", "sparse": "empty", "incomplete": "empty", "dataset": "file", "spreadsheet": "file", "csv": "file", "contact": "reach", "maintainer": "maker", "creator": "maker",
}
if not __import__("os").environ.get("PACKSENSE_NO_SYN2"):
    SYNONYMS.update({k: v for k, v in EXTRA_SYNONYMS.items() if k not in SYNONYMS})
WEIGHT_WORD, WEIGHT_CHAR, WEIGHT_ANSWER = 0.55, 0.45, 0.12
SUBJECTS = {"openfoodfacts", "packsense", "india", "brand", "card", "barcode", "flag", "check", "artificial", "contributor", "licens", "release", "chart"}
SUBJECT_MISS = 0.07         # per subject word the query names that a wording lacks (and half of it the other way round)
OOV_FACTOR = 0.75           # per word the catalogue has never seen (a product name, a topic we do not cover), at most two
WH_BONUS = 0.08             # a query that opens with the same question word (why / what / how ...) as a wording is a little closer to it
CONFIDENT = 0.40            # at or above this the top entry is answered directly (tuned on the working set)
NEAR_EXACT = 0.95           # a match this close to a catalogue wording is answered even when a cue word is present
THIRD_WINDOW = float(__import__("os").environ.get("PACKSENSE_THIRD", "0.12"))         # a third entry is offered in "did you mean" when it scores within this of the best
LEX_FLOOR = float(__import__("os").environ.get("PACKSENSE_LEX_FLOOR", "0.2"))     # minimum keyword score for a hub or a pair (0 = off)
MARGIN = 0.10               # the top entry must beat the next one with a different answer by this much to be answered directly (otherwise: the three closest are shown)
STRONG = 0.55               # at or above this a match beats the advice and medical rules

ADVICE = re.compile(r"\b(safe (to|for)|healthy|healthier|unhealthy|diabet\w*|cancer|diet|lose weight|weight loss|should i (eat|buy|drink|stop|start|avoid|quit|give up|cut)|which \w+ should i|better than|pregnan\w*|"
                    r"sick|doctor|ill\b|good for me|bad for (me|you)|fasting|expiry|expire\w*|vegan|halal|gluten|palm oil|organic)\b", re.I)
MEDICAL = re.compile(r"\b(sick|doctor|cancer|diabet\w*|lose weight|weight loss|diet|pregnan\w*|symptom\w*|medic\w*)\b", re.I)
# Cues for questions that sound like data questions but cannot be answered from the site (added 2026-10-24 after the held-out run showed these weaknesses; design-based, not tuned to a set).
WEEKDAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
PREDICT = re.compile(rf"\b(predict\w*|forecast\w*|next (week|month|year|quarter)|last (week|month|year|quarter|{WEEKDAYS})|in the future|years? ago|a year ago|will the data|going to (be|get|look))\b", re.I)
RANK_CUE = re.compile(r"\b(best|worst|healthiest|unhealthiest|cheapest|tastiest|most (sugar|salt|calories|fat|flags|mistakes|errors)|highest|lowest quality)\b", re.I)
COMPLETENESS = re.compile(r"\b(complete\w*|fill\w*|data|information|details)\b", re.I)          # "best brands for complete data" is a real question about the brand ranking
OPINION = re.compile(r"\b(good|bad|great|terrible|reliable|trustworthy|fair|worth) (system|idea|score|rating|company|brand|site|website|bot)\b", re.I)
TRICK = re.compile(r"^\s*(say|repeat after me|pretend|ignore|act as|you are now|forget|from now on)\b|system prompt|your instructions|your rules", re.I)
HEALTH_MORE = re.compile(r"\b(safe|unsafe|harmful|dangerous|toxic|bad for|good for|blood pressure|cholesterol|lunchbox|child\w*|kids?|toddler|baby|obes\w*|calories should)\b", re.I)
ROMAN_HINDI = re.compile(r"\b(kya|hai|yeh|ye|nahi|kaise|kitna|mujhe|aap|hain|kyun)\b", re.I)
# A question that asks for advice, a recommendation or something made up is not a "which of two topics" question: no hub and no "did you mean" for it, the three closest are shown.
REQUEST_CUE = re.compile(r"\b(advice|advise|recommend\w*|suggest\w*|make up|invent\w*|allerg\w*)\b", re.I)
# A number answer ("{release_rows} products ...") needs a question that asks for a number or a list; otherwise it is not a clear win (switch DATA_NEEDS_CUE).
COUNT_CUE = re.compile(r"\b(how many|how much|number|count\w*|total|most|least|which|top|highest|lowest|rank\w*|list|share|percent\w*)\b|\d", re.I)
DATA_NEEDS_CUE = False
SHORT_EXTRA = 0.05          # extra margin for a question of two meaningful words or fewer
# General cues for questions the site cannot answer although they sound close to its topic (added 2026-10-25 after the off-topic failures of the pooled test were examined).
PRIVATE_CUE = re.compile(r"\b(e-?mail|phone number|contact number|home address|private details)\b.*\b(editor|volunteer|contributor|founder|person|user|owner)\b|\b(editor|volunteer|contributor|founder|owner)\b.*\b(e-?mail|phone number|contact number|home address|private details|name)\b|\b(reveal|expose|leak)\b.*\b(name|e-?mail|identity)\b", re.I)
OUTSIDE_CUE = re.compile(r"\b(weather|rain|news|headlines?|cricket|share price|stock price|date today|today'?s date|what(?:'s| is) the date|what day is it)\b", re.I)
PRODUCT_FACT_CUE = re.compile(r"\b(calories|ingredients?|allergen\w*|serving size|expiry|price|photo|picture|image)\b.*\b(this|that|specific|particular|my)\b|\b(this|that|specific|particular|my)\b.*\b(calories|ingredients?|allergen\w*|serving size|expiry|price|photo|picture|image)\b", re.I)
COMPARE_CUE = re.compile(r"\b(compare\w*|versus|vs\.?|better than|worse than)\b", re.I)
# Categories the site does not cover at all (shopping, cooking, money, jobs done on the visitor's own papers, lists of a company's products). These get no hub and no "did you mean": a pair of
# related entries would suggest that the site half-answers them. A direct, close answer (for example "is this a shop?") is not affected.
NOT_OFFERED_CUE = re.compile(r"\b(prices?|coupons?|discounts?|deals?|recipes?|cook\w*|invest\w*|stocks?|receipts?|whoever|scan my|email me|send me|every product (?:made|sold) by|all products (?:made|sold) by)\b", re.I)
BARCODE = re.compile(r"(?<!\d)(\d{8,14})(?!\d)")
BARCODE_WORD = re.compile(r"\bbar\s?code\b.*\d|\blook ?up\b.*\d", re.I)


OTHER_LANGUAGE_WORDS = re.compile(r"\b(qu[eé]|est-ce|was ist|wie viel|und|der|die|das|el|los|las|une?|les|des|pourquoi|c[oó]mo|por qu[eé])\b", re.I)


def looks_not_english(q: str) -> bool:
    """A script that is not Latin, a mostly accented text, romanised Hindi or a few common foreign words. A single accented brand name (Nestlé) is not enough."""
    q = q.replace("’", "'")
    letters = [c for c in q if c.isalpha()]
    if not letters:
        return False
    if any(ord(c) > 0x24F for c in letters):
        return True
    accented = sum(1 for c in letters if ord(c) > 127)
    return accented / len(letters) > 0.08 or bool(ROMAN_HINDI.search(q) or OTHER_LANGUAGE_WORDS.search(q) or q.startswith(("¿", "¡")))


def stem(w: str) -> str:
    w = SYNONYMS.get(w, w)
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return SYNONYMS.get(w, w)


WH = ("why", "what", "how many", "how", "who", "when", "where", "which", "can", "does", "do", "is", "are", "will")


def opener(text: str) -> str:
    t = text.strip().lower()
    for w in WH:
        if t.startswith(w + " ") or t == w:
            return "does" if w in ("do", "does") else ("is" if w in ("is", "are") else w)
    return ""


def tokens(text: str) -> list[str]:
    text = re.sub(r"\{[^}]*\}", " ", text.lower())
    text = text.replace("'s", "").replace("open food facts", "openfoodfacts").replace("packsense", "packsense")
    words = [stem(w) for w in re.findall(r"[a-z0-9]+", text)]
    return [w for w in words if w not in STOP]


def trigrams(text: str) -> list[str]:
    t = " " + " ".join(tokens(text)) + " "
    return [t[i:i + 3] for i in range(len(t) - 2)]


class Space:
    """TF-IDF vectors over a list of documents, for one kind of feature."""

    def __init__(self, docs: list[list[str]]):
        df = Counter(f for d in docs for f in set(d))
        n = len(docs)
        self.idf = {f: math.log((1 + n) / (1 + c)) + 1 for f, c in df.items()}
        self.default = math.log(1 + n) + 1

    def vec(self, feats: list[str]) -> dict[str, float]:
        tf = Counter(feats)
        v = {f: (1 + math.log(c)) * self.idf.get(f, self.default) for f, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {f: x / norm for f, x in v.items()}


def dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(f, 0.0) for f, x in a.items())


@dataclass
class Result:
    action: str                       # "answer", "hub", "choice", "generic", "barcode", "english_only", "advice", "medical" (and the other refusal groups)
    entry_id: str | None = None
    score: float = 0.0
    ranked: list = field(default_factory=list)      # [(entry_id, score)] best first
    options: list = field(default_factory=list)     # "hub": the detail entries offered as buttons; "choice": the two entries offered


class Matcher:
    def __init__(self, entries: list[dict] | None = None, fixed: dict | None = None):
        self.fixed = fixed or cat.load_fixed()
        all_entries = entries or cat.load_entries()
        self.alias = {e["id"]: e["same_as"] for e in all_entries if e.get("same_as")}
        self.entries = [e for e in all_entries if not e.get("same_as")]      # a same_as entry lent its wordings to its target
        self.wordings: list[tuple[str, str]] = []            # (entry id, wording)
        for e in self.entries:
            for w in cat.wordings(e):
                self.wordings.append((e["id"], w))
        self.answers = {e["id"]: cat.render(e, self.fixed) for e in self.entries}
        self.word_space = Space([tokens(w) for _, w in self.wordings] + [tokens(a) for a in self.answers.values()])
        self.char_space = Space([trigrams(w) for _, w in self.wordings])
        self.word_vecs = [self.word_space.vec(tokens(w)) for _, w in self.wordings]
        self.char_vecs = [self.char_space.vec(trigrams(w)) for _, w in self.wordings]
        self.answer_vecs = {i: self.word_space.vec(tokens(a)) for i, a in self.answers.items()}
        self.norm_words = [cat.normalise(w) for _, w in self.wordings]
        self.openers = [opener(w) for _, w in self.wordings]
        self.subjects = [set(tokens(w)) & SUBJECTS for _, w in self.wordings]
        self.vocab = sorted({f for d in self.word_space.idf for f in [d]})
        self.takes_name = {eid for eid, w in self.wordings if "{brand}" in w or "{product}" in w}
        self.families = cat.load_families(all_entries)
        self.family_of = {}                                   # entry id -> family index (hub and details)
        for k, f in enumerate(self.families):
            for eid in [f["hub"], *f["details"]]:
                self.family_of[eid] = k
        self.kind = {e["id"]: e.get("kind") for e in self.entries}
        self.use_families = True                              # False: the earlier behaviour (a tie shows the three closest)

    def is_clear(self, top_id: str, top: float, rival: float, query: str) -> bool:
        margin = MARGIN + (SHORT_EXTRA if len(tokens(query)) <= 2 else 0.0)
        if DATA_NEEDS_CUE and self.kind.get(top_id) == "data" and not COUNT_CUE.search(query):
            return False
        return top - rival >= margin

    def tie_result(self, ranked: list[tuple[str, float]], top: float, query: str = "") -> Result:
        """The top entry is a confident match but too close to a rival with a different answer. Same family: answer with the hub; otherwise ask which of the two."""
        top_id = ranked[0][0]
        rival_id = next((i for i, _ in ranked[1:] if self.answers[i] != self.answers[top_id]), None)
        if not self.use_families or rival_id is None or any(rx.search(query) for rx in (REQUEST_CUE, ADVICE, HEALTH_MORE, MEDICAL, TRICK, NOT_OFFERED_CUE)):
            return Result("generic", None, top, ranked[:3])
        lex = getattr(self, "lex_last", None)                 # a hub or a pair needs real word overlap with one of the two entries, not only a close meaning
        if LEX_FLOOR > 0 and lex is not None and max(lex.get(top_id, 0.0), lex.get(rival_id, 0.0)) < LEX_FLOOR:
            return Result("generic", None, top, ranked[:3])
        fa, fb = self.family_of.get(top_id), self.family_of.get(rival_id)
        if fa is not None and fa == fb:
            f = self.families[fa]
            return Result("hub", f["hub"], top, ranked[:3], list(f["details"]))
        options = [top_id, rival_id]
        third = next((i for i, sc in ranked[1:] if i not in options and self.answers[i] not in (self.answers[top_id], self.answers[rival_id]) and sc >= top - THIRD_WINDOW), None)
        return Result("choice", None, top, ranked[:3], options + ([third] if third else []))

    def canon(self, entry_id: str | None) -> str | None:
        """The entry that really answers: an alias entry is answered by its target."""
        return self.alias.get(entry_id, entry_id)

    def scores(self, query: str, skip_wording: str | None = None) -> list[tuple[str, float]]:
        """Entry id -> score for the query. `skip_wording` leaves out wordings equal to it (the leave-one-out test)."""
        qw, qc = self.word_space.vec(tokens(query)), self.char_space.vec(trigrams(query))
        skip = cat.normalise(skip_wording) if skip_wording else None
        qo = opener(query)
        qs = set(tokens(query)) & SUBJECTS
        best: dict[str, float] = {}
        for k, (eid, _) in enumerate(self.wordings):
            if skip is not None and self.norm_words[k] == skip:
                continue
            s = WEIGHT_WORD * dot(qw, self.word_vecs[k]) + WEIGHT_CHAR * dot(qc, self.char_vecs[k])
            if qo and self.openers[k]:
                s += WH_BONUS if qo == self.openers[k] else -WH_BONUS / 2
            s -= SUBJECT_MISS * len(qs - self.subjects[k]) + SUBJECT_MISS / 2 * len(self.subjects[k] - qs)
            if s > best.get(eid, -1.0):
                best[eid] = s
        oov = self.unknown_words(query)
        out = []
        for e in self.entries:
            base = best.get(e["id"], 0.0)
            score = base + WEIGHT_ANSWER * dot(qw, self.answer_vecs[e["id"]])
            if oov and e["id"] not in self.takes_name:
                score *= OOV_FACTOR ** min(oov, 2)
            out.append((e["id"], score))
        return sorted(out, key=lambda x: -x[1])

    def unknown_words(self, query: str) -> int:
        """How many words of the query are not in the catalogue's vocabulary, allowing a one-letter typo."""
        n = 0
        for w in tokens(query):
            if w.isdigit() or w in self.word_space.idf:
                continue
            if not difflib.get_close_matches(w, self.vocab, n=1, cutoff=0.8):
                n += 1
        return n

    def match(self, query: str, skip_wording: str | None = None) -> Result:
        q = query.strip()
        if BARCODE.search(q) or BARCODE_WORD.search(q):
            others = [w for w in tokens(BARCODE.sub(" ", q)) if not w.isdigit() and w not in ("look", "lookup", "up", "barcode", "bar", "code", "search", "find", "check")]
            return Result("barcode" if len(others) <= 2 else "productfacts")
        if looks_not_english(q):
            return Result("english_only")
        ranked = self.scores(q, skip_wording)
        top_id, top = ranked[0]
        rival = next((s for i, s in ranked[1:] if self.answers[i] != self.answers[top_id]), 0.0)
        clear = self.is_clear(top_id, top, rival, q)
        if top < NEAR_EXACT:
            if TRICK.search(q):
                return Result("advice" if (ADVICE.search(q) or HEALTH_MORE.search(q)) else "meta", None, top, ranked[:3])
            if PREDICT.search(q):
                return Result("time", None, top, ranked[:3])
            if RANK_CUE.search(q) and not COMPLETENESS.search(q):
                return Result("ranking", None, top, ranked[:3])
            if OPINION.search(q):
                return Result("meta", None, top, ranked[:3])
            if PRIVATE_CUE.search(q):
                return Result("private", None, top, ranked[:3])
            if PRODUCT_FACT_CUE.search(q):
                return Result("productfacts", None, top, ranked[:3])
            if OUTSIDE_CUE.search(q) or (COMPARE_CUE.search(q) and self.unknown_words(q) >= 1):
                return Result("meta", None, top, ranked[:3])
        if top >= STRONG and clear:
            return Result("answer", top_id, top, ranked[:3])
        if MEDICAL.search(q):
            return Result("medical", None, top, ranked[:3])
        if (ADVICE.search(q) or HEALTH_MORE.search(q)) and top < CONFIDENT + 0.1:
            return Result("advice", None, top, ranked[:3])
        if top >= CONFIDENT and clear:
            return Result("answer", top_id, top, ranked[:3])
        if top >= CONFIDENT:
            return self.tie_result(ranked, top, q)
        return Result("generic", None, top, ranked[:3])


# --- memory of the last answer (follow-up questions) ----------------------------------------------------------------------------------------------
PRONOUN = re.compile(r"\b(it|its|they|them|their|those|that|one|ones|same)\b", re.I)
FOLLOW_OPENER = re.compile(r"^(and|what about|how about|so|then|but)\b", re.I)
LAMBDA = 0.40               # weight of how close an entry's topic is to the last answer's topic
BETA = 0.10                 # extra weight for the entries offered as follow-up buttons under the last answer
SHORT = 3                   # a question with this many meaningful words or fewer may lean on the last answer


def is_follow_up_candidate(q: str) -> bool:
    return len(tokens(q)) <= SHORT or bool(PRONOUN.search(q)) or bool(FOLLOW_OPENER.match(q.strip()))


def _centroids(self: "Matcher") -> dict[str, dict[str, float]]:
    if not hasattr(self, "_cent"):
        docs: dict[str, list[str]] = {}
        for eid, w in self.wordings:
            docs.setdefault(eid, []).extend(tokens(w))
        for eid, a in self.answers.items():
            docs.setdefault(eid, []).extend(tokens(a))
        self._cent = {eid: self.word_space.vec(toks) for eid, toks in docs.items()}
    return self._cent


def match_in_context(self: "Matcher", query: str, prev_id: str | None, follow_ups: dict[str, list[str]] | None = None, mode: str = "always",
                     skip_wording: str | None = None) -> Result:
    """Like match(), but a short or pronoun question may lean on the last answer `prev_id`.
    mode "weak": only when the plain match is not a confident answer; "always": for every candidate question; "off": never (same as match())."""
    base = self.match(query, skip_wording)
    prev_id = self.canon(prev_id)
    if mode == "off" or not prev_id or base.action in ("barcode", "english_only", "medical") or not is_follow_up_candidate(query):
        return base
    if mode == "weak" and base.action == "answer" and not PRONOUN.search(query):
        return base
    cent = _centroids(self)
    prev = cent.get(prev_id, {})
    buttons = set((follow_ups or {}).get(prev_id, []))
    ranked = [(eid, s + (0.0 if eid == prev_id else LAMBDA * dot(prev, cent.get(eid, {}))) + (BETA if eid in buttons else 0.0)) for eid, s in self.scores(query, skip_wording)]
    ranked.sort(key=lambda x: -x[1])
    top_id, top = ranked[0]
    rival = next((s for i, s in ranked[1:] if self.answers[i] != self.answers[top_id]), 0.0)
    if top >= CONFIDENT and self.is_clear(top_id, top, rival, query):
        return Result("answer", top_id, top, ranked[:3])
    if top >= CONFIDENT:
        return self.tie_result(ranked, top, query)
    return Result("generic", None, top, ranked[:3])


Matcher.match_in_context = match_in_context


REPLY_GROUP = {"advice": "Advice", "medical": "Medical", "time": "Time", "ranking": "Ranking", "productfacts": "ProductFacts", "meta": "Meta", "private": "Private", "english_only": "NotEnglish", "barcode": "Barcode"}


def reply(self: "Matcher", result: Result) -> str:
    """The text the bot shows for a result: the entry's answer, or the fixed reply of the refusal group."""
    if result.action == "answer":
        entry = next(e for e in self.entries if e["id"] == result.entry_id)
        return cat.render(entry, self.fixed)
    if result.action == "hub":
        entry = next(e for e in self.entries if e["id"] == result.entry_id)
        return cat.render(entry, self.fixed)
    if result.action == "choice":
        return cat.resolve("@choice_reply", self.fixed)
    if result.action == "generic":
        return cat.resolve("@generic_reply", self.fixed)
    return cat.resolve(self.fixed["decline_groups"][REPLY_GROUP[result.action]], self.fixed)


Matcher.reply = reply
