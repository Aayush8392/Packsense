"""Item 15, step 4b: the story checker (context amendments A46 and A47). Code only, no model.

It verifies what code can verify: that every number comes from the facts a sentence cites, that comparative words agree with the direction code computed, that nothing causal,
guessed or advisory is said, that patterns are worded as the owner approved, that every event of the day is covered, and that no name, markup or raw column name appears.
It cannot check meaning (A46); a second model and the owner read the stories for that. Each rule has a code (R1 to R13) so a failure says which one.
"""
from __future__ import annotations

import json
import re

import story_facts as sf

MAX_SENTENCES = 10
MAX_WORDS = 30
TYPES = {"fact", "derived", "pattern", "unexplained"}
UNEXPLAINED_PHRASE = "not explained by any known pattern"


def _words(*ws: str) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in ws) + r")\b", re.I)


UP = _words("up", "rose", "risen", "rise", "rising", "higher", "increase", "increased", "increasing", "jump", "jumped", "spike", "spiked", "surge", "surged", "grew", "grown", "growth", "above", "larger",
            "bigger", "greater", "more", "exceed", "exceeded", "exceeds")
DOWN = _words("down", "fell", "fallen", "fall", "falling", "lower", "decrease", "decreased", "decreasing", "below", "smaller", "fewer", "less", "declined", "decline", "reduced", "shrank")
SUPERLATIVE = _words("most", "least", "highest", "lowest", "largest", "smallest", "biggest", "record", "peak", "ever", "unprecedented", "all-time")
MAGNITUDE = _words("sharp", "sharply", "steep", "steeply", "dramatic", "dramatically", "huge", "massive", "tiny", "enormous", "significant", "significantly", "substantial", "major", "notable",
                   "remarkable", "big", "large", "small", "far", "much", "greatly", "vastly", "way")
BARE_EVENT = re.compile(r"^(?:nutrition changes|ingredients changes|new products|unseen edits)\b[^.]*\b(?:higher|lower) than usual", re.I)
SUPPORT_KINDS = ("new_and_existing", "share_of_changed", "part_of_whole", "rest_contrast", "india_and_rest")
CONNECT = _words("while", "whereas", "which means", "accounts for", "account for", "meaning that", "offset")
STEADY = _words("in line", "steady", "unchanged", "same", "flat", "as usual", "normal")
UNUSUAL = _words("unusual", "unusually", "abnormal", "abnormally", "exceptional", "extreme")
CAUSAL = _words("because", "due to", "caused", "causes", "cause", "causing", "reason", "resulted", "result of", "results in", "led to", "leads to", "driven by", "drives", "explained by",
                "owing to", "thanks to", "therefore", "hence", "consequently", "as a result", "behind", "triggered", "produced by", "stems from")
GUESS = _words("may", "might", "probably", "perhaps", "likely", "possibly", "could", "presumably", "appears", "apparently", "seems", "suggests", "suggesting", "indicates", "indicating",
               "implies", "speculate", "guess", "hypothesis", "maybe", "unclear", "unknown")
ADVICE = _words("should", "recommend", "recommended", "advise", "consider", "need to", "needs to", "must", "ought", "try to", "worth", "investigate", "review", "look into", "keep an eye")
NUMBER_WORDS = _words("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "hundred", "hundreds", "thousand", "thousands", "million", "millions",
                      "dozen", "dozens", "twice", "double", "doubled", "triple", "tripled", "half", "halved", "quarter", "several", "many", "few", "couple", "numerous", "majority", "minority")
VOICE = _words("we", "our", "ours", "us", "i", "my", "you", "your")
CORRECT = re.compile(r"\bcorrect(?:ness|ly)?\b|\bwrong\b|\berror(?:s)?\b|\bmistake(?:s)?\b", re.I)
MARKUP = re.compile(r"[`*#<>\[\]{}]|https?://|www\.")
SNAKE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")
CAPITAL = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]+\b")
ALLOWED_CAPITALS = {"India", "PackSense", "Open", "Food", "Facts", "OFF", "UTC", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December",
                    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _scrub(text: str, request: dict) -> str:
    """The sentence without the fixed phrases code supplied (the plain labels of the facts and the unexplained phrase), so the word rules judge only what the narrator added."""
    out = text
    fixed = {f["label"] for f in request["facts"] + request["patterns"] if "label" in f}
    fixed |= {f["rank_phrase"] for f in request["facts"] if "rank_phrase" in f}
    fixed |= {p["statement"] for p in request["patterns"] if "statement" in p}
    fixed |= {d["statement"] for d in request["derived"]} | {d["conclusion_wording"] for d in request["derived"] if "conclusion_wording" in d}
    for phrase in sorted(fixed, key=len, reverse=True):
        out = re.sub(re.escape(phrase), " ", out, flags=re.I)
    return re.sub(re.escape(UNEXPLAINED_PHRASE), " ", out, flags=re.I)


def _relation_problems(tag: str, text: str, cited: list[dict], request: dict, prev_up: bool = False) -> list[tuple[str, str]]:
    """R18: a connecting phrase may only be written when the numbers behind it show the relation it claims."""
    low = text.lower()
    out: list[tuple[str, str]] = []
    derived = {c["derived"]: c for c in cited if c.get("kind") == "derived"}
    facts = {c["column"]: c for c in cited if c.get("kind") == "fact"}
    if "although" in low and "part_of_whole" not in derived:
        out.append(("R18", f"{tag}: 'although' needs a cited part-of-the-whole fact (two shares that differ)"))
    if "but the mix was different" in low:
        total = facts.get("any_products")
        mix = any(d["derived"] in ("part_of_whole", "rest_contrast", "share_of_changed") for d in request["derived"]) or any(f["column"] == "india_share" and f["direction"] != "usual" for f in request["facts"])
        if not total or total["direction"] != "usual" or not mix:
            out.append(("R18", f"{tag}: 'but the mix was different' needs the total at its usual level and a cited mix change"))
    part_not_all = any(e["kind"] == "part_not_all" for e in derived.get("rest_contrast", {}).get("entries", []))
    if "not all of it" in low and not part_not_all:
        out.append(("R18", f"{tag}: 'not all of it' needs a cited fact showing the rest of the world also above its usual"))
    if "also higher than usual" in low and not (part_not_all or prev_up):
        out.append(("R18", f"{tag}: 'also higher' needs the sentence before it to rest on something that is above its usual, or a cited fact for the rest of the world"))
    if "the rise is in india" in low and not any(e["kind"] == "all_in_india" for e in derived.get("rest_contrast", {}).get("entries", [])):
        out.append(("R18", f"{tag}: 'the rise is in India' needs a cited fact showing the rest of the world at its usual"))
    if "when it usually has" in low and not (facts.get("india_share") and facts["india_share"]["direction"] in ("up", "down")):
        out.append(("R18", f"{tag}: 'when it usually has' needs a cited India share that is clearly off its usual"))
    return out


def words_for_connect(text: str, request: dict) -> str:
    """The sentence without the fixed conclusion wordings code supplied (they may contain 'offset' or similar), for the connective rule."""
    out = text
    for d in request["derived"]:
        for phrase in (d.get("conclusion_wording"), d.get("statement")):
            if phrase:
                out = re.sub(re.escape(phrase), " ", out, flags=re.I)
    return out


PUNCTUATION = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}


def normalise_text(text: str) -> str:
    """Cosmetic clean-up done by code before any check: curly quotes, dashes and non-breaking spaces become their plain forms (the model keeps writing a curly apostrophe)."""
    return "".join(PUNCTUATION.get(c, c) for c in text)


def parse(raw: str) -> dict | None:
    """The narrator's reply as an object, tolerating a code fence around it."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if isinstance(obj, dict) and isinstance(obj.get("sentences"), list):
        for s in obj["sentences"]:
            if isinstance(s, dict) and isinstance(s.get("text"), str):
                s["text"] = normalise_text(s["text"])
    return obj if isinstance(obj, dict) else None


def check(story: dict | None, request: dict, strict: bool = False) -> list[tuple[str, str]]:
    """strict=True is for a model-written story: every clear event must be told and every unexplained change declared. The code-planned story is checked with strict=False."""
    problems: list[tuple[str, str]] = []
    if not story or not isinstance(story.get("sentences"), list) or not story["sentences"]:
        return [("R1", "no usable list of sentences")]
    sentences = story["sentences"]
    if len(sentences) > MAX_SENTENCES:
        problems.append(("R1", f"{len(sentences)} sentences, at most {MAX_SENTENCES}"))
    items = sf.all_items(request)
    cited_all: set[str] = set()
    earlier_cites: set[str] = set()
    earlier_text: list[str] = []
    prev_up = False
    for n, s in enumerate(sentences, start=1):
        text, typ, cites = s.get("text"), s.get("type"), s.get("cites")
        tag = f"sentence {n}"
        if not isinstance(text, str) or typ not in TYPES or not isinstance(cites, list) or not all(isinstance(c, str) for c in cites):
            problems.append(("R1", f"{tag}: needs text, a type of fact, pattern or unexplained, and a list of cited ids"))
            continue
        bad = [c for c in cites if c not in items]
        if not cites or bad:
            problems.append(("R2", f"{tag}: cites {'nothing' if not cites else 'unknown ids ' + ', '.join(bad)}"))
            continue
        cited_all.update(cites)
        cited = [items[c] for c in cites]
        if typ == "derived" and not any(c.get("kind") == "derived" for c in cited):
            problems.append(("R2", f"{tag}: a derived sentence must cite a derived fact"))
        n_derived = sum(1 for c in cited if c.get("kind") == "derived")
        if CONNECT.search(words_for_connect(text, request)) and n_derived != 1:
            problems.append(("R14", f"{tag}: connecting words such as 'while' or 'accounts for' need exactly one cited derived fact (this sentence cites {n_derived}); do not join two derived facts"))
        if request["scope"] == "all" and re.search(r"\bindia\b", text, re.I) and not any(c.get("column") == "india_share" or c.get("derived") in ("india_and_rest", "steady_summary", "part_of_whole", "rest_contrast") for c in cited):
            problems.append(("R15", f"{tag}: India is mentioned but no cited fact is about India"))
        problems.extend(_relation_problems(tag, text, cited, request, prev_up))
        prev_up = any(c.get("direction") in ("up", "up_slight") for c in cited)
        if n > 1 and BARE_EVENT.match(text) and " also " not in text.lower():
            problems.append(("R19", f"{tag}: a bare 'higher than usual' sentence must be joined with 'also' or 'separately', or told in the opening"))
        allowed = sf.known_numbers(request, cites)
        words = _scrub(text, request)
        for tok in NUMBER.findall(text):
            if float(tok.replace(",", "")) not in allowed:
                problems.append(("R3", f"{tag}: the number {tok} is not in the cited facts"))
        for m in NUMBER_WORDS.findall(words):
            problems.append(("R3", f"{tag}: '{m}' is a number or amount written as a word; digits from the facts only"))
        dirs = {c.get("direction") for c in cited}
        dirs |= {d.split("_")[0] for d in dirs if d and d.endswith("_slight")}
        dirs |= {c.get("sign") for c in cited if c.get("sign")}
        for m in UP.findall(words):
            if "up" not in dirs:
                problems.append(("R4", f"{tag}: '{m}' but no cited fact moved up"))
        for m in DOWN.findall(words):
            if "down" not in dirs:
                problems.append(("R4", f"{tag}: '{m}' but no cited fact moved down"))
        if STEADY.search(words) and any(c.get("direction") not in (None, "usual") for c in cited if c.get("kind") in ("fact", "derived")):
            problems.append(("R4", f"{tag}: 'in line' or 'steady' wording, but a cited fact is not at its usual level"))
        for m in SUPERLATIVE.findall(words) + MAGNITUDE.findall(words):
            problems.append(("R4", f"{tag}: '{m}' is a comparison or size word code did not compute"))
        for m in UNUSUAL.findall(words):
            if not dirs & {"up", "down"}:
                problems.append(("R4", f"{tag}: '{m}' but every cited fact is at its usual level"))
        for m in CAUSAL.findall(words):
            problems.append(("R5", f"{tag}: causal wording '{m}'"))
        phrase_ok = False
        if typ == "pattern":
            pats = [c for c in cited if c.get("kind") == "pattern"]
            phrase_ok = bool(pats) and any(p["wording"].lower() in text.lower() for p in pats)
            if not pats:
                problems.append(("R6", f"{tag}: a pattern sentence must cite a pattern that code matched"))
            elif not phrase_ok:
                problems.append(("R6", f"{tag}: a pattern sentence must use the approved wording '{pats[0]['wording']}'"))
            for p in pats:
                found = set(NUMBER.findall(text))
                missing = [x for x in p.get("must_state", []) if x not in found]
                if missing:
                    problems.append(("R13", f"{tag}: the sentence for {p['id']} must state {', '.join(missing)}"))
        guess_text = words
        if phrase_ok:
            for p in [c for c in cited if c.get("kind") == "pattern"]:
                guess_text = re.sub(re.escape(p["wording"]), " ", guess_text, flags=re.I)
        if "consistent with" in guess_text.lower():
            problems.append(("R6", f"{tag}: 'consistent with' is for approved pattern wording only"))
        for m in GUESS.findall(guess_text):
            problems.append(("R6", f"{tag}: guessing wording '{m}'"))
        for m in ADVICE.findall(words):
            problems.append(("R7", f"{tag}: advice wording '{m}'"))
        if typ == "unexplained":
            for f in cited:
                if f.get("kind") == "fact" and f["label"].lower() not in text.lower():
                    problems.append(("R8", f"{tag}: an unexplained sentence must name the measure ('{f['label']}')"))
        for d in cited:
            wording = d.get("conclusion_wording")
            if wording and wording.lower() in text.lower():
                head = NUMBER.findall(d["statement"])[:1]
                if head and head[0] not in NUMBER.findall(" ".join(earlier_text + [text])):
                    problems.append(("R16", f"{tag}: the conclusion of {d['id']} is stated before the finding it rests on; tell that finding with its headline number ({head[0]}) first"))
        earlier_cites.update(cites)
        earlier_text.append(text)
        if typ == "unexplained" and UNEXPLAINED_PHRASE not in text.lower():
            problems.append(("R8", f"{tag}: an unexplained sentence must say '{UNEXPLAINED_PHRASE}'"))
        if typ != "unexplained" and UNEXPLAINED_PHRASE in text.lower():
            problems.append(("R8", f"{tag}: only an unexplained sentence may say '{UNEXPLAINED_PHRASE}'"))
        for tok in SNAKE.findall(text):
            problems.append(("R9", f"{tag}: raw column name '{tok}'; use the plain label"))
        for tok in CAPITAL.findall(text):
            if tok not in ALLOWED_CAPITALS:
                problems.append(("R9", f"{tag}: the name '{tok}' is not allowed"))
        if request["scope"] == "india" and n == 1 and "india" not in text.lower():
            problems.append(("R13", f"{tag}: for the India scope the first sentence must say India"))
        if MARKUP.search(text):
            problems.append(("R10", f"{tag}: markup or a link"))
        if any(ord(c) > 127 for c in text):
            problems.append(("R10", f"{tag}: use plain ASCII characters (a straight apostrophe, no curly quotes or dashes)"))
        if not text.rstrip().endswith("."):
            problems.append(("R11", f"{tag}: a sentence must end with a full stop"))
        if len(text.split()) > MAX_WORDS:
            problems.append(("R11", f"{tag}: {len(text.split())} words, at most {MAX_WORDS}"))
        for m in VOICE.findall(words):
            problems.append(("R11", f"{tag}: personal voice '{m}'"))
        for m in CORRECT.findall(words):
            problems.append(("R11", f"{tag}: '{m}' is a claim about correctness"))
    first = sentences[0].get("text", "") if isinstance(sentences[0], dict) else ""
    if request["date_words"] not in first:
        problems.append(("R13", f"the first sentence must name the day as '{request['date_words']}'"))
    covered_by_pattern = {c for p in request["patterns"] for c in p.get("cites", [])}
    for p in request["patterns"]:
        if p["id"] in cited_all:
            cited_all.update(p.get("cites", []))
    for eid in request["events"]:
        if eid not in cited_all and (strict or eid[0] != "F"):
            problems.append(("R12", f"event {eid} is not covered by any sentence"))
    needs_unexplained = [f["id"] for f in request["facts"] if f["direction"] in ("up", "down") and f["id"] not in covered_by_pattern]
    if strict and needs_unexplained and not any(s.get("type") == "unexplained" for s in sentences if isinstance(s, dict)):
        problems.append(("R12", f"events {', '.join(needs_unexplained)} match no pattern, so one sentence must be of type unexplained"))
    for i, s_ in enumerate(sentences):
        if isinstance(s_, dict) and isinstance(s_.get("text"), str) and s_["text"].lower().rstrip().endswith("the mix was different."):
            nxt = sentences[i + 1] if i + 1 < len(sentences) and isinstance(sentences[i + 1], dict) else {}
            nxt_items = [items[c] for c in nxt.get("cites", []) if isinstance(c, str) and c in items]
            if not any(x.get("derived") in SUPPORT_KINDS or x.get("column") == "india_share" for x in nxt_items):
                problems.append(("R19", f"sentence {i + 1}: 'the mix was different' must be followed by the sentence that shows how"))
    story_text = " ".join(s.get("text", "") for s in sentences if isinstance(s, dict)).lower()
    for d in request["derived"]:
        if d["id"] in request["events"] and d.get("conclusion_wording") and d["conclusion_wording"].lower() not in story_text:
            problems.append(("R17", f"the conclusion of {d['id']} ('{d['conclusion_wording']}') must be stated"))
    if not request["events"]:
        for s in sentences:
            if isinstance(s, dict) and s.get("type") in ("pattern", "unexplained"):
                problems.append(("R12", "a quiet day has no pattern or unexplained sentence"))
    return problems


def render(story: dict, request: dict) -> str:
    """The text shown: the checked sentences, then the caveats written by code, then the label."""
    lines = [s["text"] for s in story["sentences"]] + list(request["caveats"].values()) + [request["footer"]]
    return " ".join(lines)
