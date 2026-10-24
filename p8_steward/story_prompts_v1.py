"""Item 15, step 4c: the narrator's and the judge's prompts (context amendments A46 and A47). The narrator writes only from the facts code computed; the judge is a second model."""
from __future__ import annotations

import json

import story_check as sc

NARRATOR_SYSTEM = """You write a short factual note about one day of changes to a food database. You are given FACTS as JSON, computed by code. Follow every rule.
1. Use only the facts and patterns given. Every sentence lists the ids it uses in "cites".
2. Numbers: copy digits exactly from the fields value, usual, times_usual, days_in_a_row, fields_with_a_jump, dropped_per_100 and usual_range_per_100. Do not compute any number. Do not write numbers as words (write 8, not eight).
3. Write full sentences that start with a capital letter. Start the first sentence with "On <date_words>"; only the first sentence names the date. When scope is "india", every sentence says India. Name each measure with its "label" exactly as given, word for word.
4. Direction words depend on the fact's "direction": "up" or "down" is a clear change (say higher or lower, or up or down); "up_slight" or "down_slight" is a small change (say "a little higher" or "a little lower"); "usual" means in line with the usual. Say "in line", "steady" or "the same" only for a fact whose direction is "usual". Do not use highest, most, sharp, huge or significant.
5. Never say why anything happened. Never guess (no may, might, probably, likely, appears, suggests). Never give advice (no should, consider, worth).
6. A pattern sentence has type "pattern" and cites the pattern id. It is one sentence that contains the pattern's "wording" exactly as given and also every number listed in the pattern's "must_state" field (for example: "<measure> ... 10.41 ..., against a usual ..., <wording>."). Use the phrase "consistent with" nowhere else.
7. Every fact with direction "up" or "down" that is not listed in a pattern's "cites" needs one sentence of type "unexplained" that cites it and contains the exact words "not explained by any known pattern".
8. Every id in "events" must be cited by at least one sentence.
9. Plain, impersonal English. At most 30 words per sentence and at most 8 sentences. No names of people, brands or products. No markup, links or column names. Do not use I, we, you or our.
10. If "events" is empty, write one or two sentences of type "fact" about the measures whose direction is "usual", or a little higher or lower for the small changes.
Reply with one JSON object only, in this shape: {"sentences":[{"text":"...","type":"fact","cites":["F1"]}]}. The type is "fact", "pattern" or "unexplained"."""

JUDGE_SYSTEM = """You check a short note against the facts it was written from. Each fact has a "direction" computed by code: "up" or "down" is a clear change, "up_slight" or "down_slight" a small change, "usual" means in line with the usual. Trust the direction; do not recompute it.
For each sentence decide whether everything it says is directly supported by the facts it cites. Mark a sentence NOT supported if it states a number or comparison the cited facts do not give, uses a direction the facts do not show (for example "in line" for a fact that is up_slight, or "higher" for a usual fact), says or hints why something happened, guesses, gives advice, or claims more than the pattern wording allows.
Two kinds of sentence are supported by design: a sentence of type "pattern" that uses the pattern's wording and numbers, and a sentence of type "unexplained" saying a change is "not explained by any known pattern", when the cited fact is up or down and no pattern lists it.
Reply with one JSON object only: {"verdicts":[{"n":1,"supported":true,"reason":"at most 15 words"}],"all_supported":true}. Use sentence numbers starting at 1."""


def facts_for_prompt(request: dict) -> str:
    patterns = [{k: v for k, v in p.items() if k != "rule"} for p in request["patterns"]]          # the matching rule is for code and the owner, not for the narrator
    keep = {"day": request["day"], "date_words": request["date_words"], "scope": request["scope"], "facts": request["facts"], "patterns": patterns, "events": request["events"]}
    return json.dumps(keep, ensure_ascii=False)


def narrator_messages(request: dict) -> list[dict]:
    return [{"role": "system", "content": NARRATOR_SYSTEM}, {"role": "user", "content": f"FACTS:\n{facts_for_prompt(request)}"}]


def retry_messages(request: dict, previous: str, problems: list[tuple[str, str]]) -> list[dict]:
    listed = "\n".join(f"- {code}: {msg}" for code, msg in problems[:12])
    return narrator_messages(request) + [{"role": "assistant", "content": previous},
                                         {"role": "user", "content": f"The checker found these problems:\n{listed}\nReturn the full corrected JSON object only."}]


def judge_messages(request: dict, story: dict) -> list[dict]:
    numbered = [{"n": i, "text": s["text"], "cites": s["cites"]} for i, s in enumerate(story["sentences"], start=1)]
    return [{"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": f"FACTS:\n{facts_for_prompt(request)}\n\nNOTE:\n{json.dumps(numbered, ensure_ascii=False)}"}]


def parse_judge(raw: str) -> dict | None:
    import re
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    return sc.parse(text)
