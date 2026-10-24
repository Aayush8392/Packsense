"""Item 15, step 4c (version 2): the narrator's and the judge's prompts (context amendments A46 and A47). The narrator writes only from the facts code computed; the judge is a second model.
Version 1 of the prompts is kept in story_prompts_v1.py (the first 40-trial run)."""
from __future__ import annotations

import json
import re

import story_check as sc

NARRATOR_SYSTEM = """You write a short note about one day of changes to a food database, for a reader who has not seen the tables. Say what happened and what it means, not a list of measures. You are given FACTS as JSON, all computed by code. Follow every rule.
1. Use only the facts, derived facts and patterns given. Every sentence lists the ids it uses in "cites". The ids in "events" are the findings that must be told, most important first.
2. Numbers: copy digits exactly from the fields of the facts you cite (value, usual, times_usual, days_in_a_row, the numbers inside a statement, fields_with_a_jump, dropped_per_100, usual_range_per_100, carried_share). Do not compute any number. Do not write numbers as words (write 8, not eight).
3. Write full sentences that start with a capital letter. Start the first sentence with "On <date_words>"; only the first sentence names the date. When scope is "india", the first sentence says India. Name each measure with its "label" exactly as given, word for word.
4. Direction words depend on the "direction" of the fact you cite: "up" or "down" is a clear change (higher, lower, up, down); "up_slight" or "down_slight" is a small change ("a little higher", "a little lower"); "usual" means in line with the usual. Say "in line", "steady" or "the same" only for a fact whose direction is "usual". Do not use highest, most, sharp, huge, far or significant; a "rank_phrase" may be copied word for word.
5. Never say why anything happened. Never guess (no may, might, probably, likely, appears, suggests). Never give advice (no should, consider, worth).
6. A derived fact has a ready "statement" computed by code, and sometimes a "conclusion_wording" that code reached from the numbers. Tell its meaning with its numbers, in your own words, and merge facts that belong together. When a derived fact has a conclusion_wording, state that conclusion as its own short sentence beginning "This means that", copying the wording exactly (keep words such as "almost all" as they are written). Only a sentence that cites exactly one derived fact may use "while", "which means", "accounts for" or "offset", and the connection must be the one inside that derived fact (its identity or its conclusion), for example "Outside India, 1,623 products changed while India had 22, which means the increase is outside India." Never join two different derived facts with these words.
7. A pattern sentence has type "pattern" and cites the pattern id. Copy the pattern's "statement" exactly as one sentence (you may put "On <date_words>," in front of it if it is the first sentence). Use the phrase "consistent with" nowhere else.
8. Every fact with direction "up" or "down" (a clear change, not a slight one) that is not listed in a pattern's "cites" needs one sentence of type "unexplained" that cites it and contains the exact words "not explained by any known pattern"; you may cover several facts in one such sentence. Facts that are only "up_slight" or "down_slight" need no sentence: leave them out unless they support a conclusion. Every id in "events" must be cited by at least one sentence.
9. Do not list measures whose direction is "usual" one by one. Mention them once, in one closing sentence, using the steady_summary derived fact. After the events, add at most two other derived facts that help the reader (for example the open-flag bridge); do not retell every derived fact.
10. Keep sentences short and separate: do not join statements with commas; use two sentences instead of one long one. Plain, impersonal English. At most 30 words per sentence and 3 to 6 sentences. No names of people, brands or products. No markup, links or column names. Do not use I, we, you or our. In an all-markets note, say India only when you cite a fact about India.
Reply with one JSON object only, in this shape: {"sentences":[{"text":"...","type":"fact","cites":["F1"]}]}. The type is "fact", "derived", "pattern" or "unexplained"."""

JUDGE_SYSTEM = """You check a short note against the facts it was written from. Each fact has a "direction" computed by code: "up" or "down" is a clear change, "up_slight" or "down_slight" a small change, "usual" means in line with the usual. Trust the direction; do not recompute it. A derived fact has a "statement" and sometimes a "conclusion_wording" that code computed from the numbers; both are true by construction.
For each sentence decide whether everything it says is directly supported by the facts it cites. Mark a sentence NOT supported if it states a number or comparison the cited facts do not give, uses a direction the facts do not show (for example "in line" for a fact that is up_slight, or "higher" for a usual fact), says or hints why something happened, guesses, gives advice, joins facts in a way the derived facts do not show, or claims more than the pattern wording allows. A sentence about India in an all-markets note must cite a fact about India.
Two kinds of sentence are supported by design: a sentence of type "pattern" that uses the pattern's wording and numbers, and a sentence of type "unexplained" saying a change is "not explained by any known pattern", when the cited fact is up or down and no pattern lists it.
Reply with one JSON object only: {"verdicts":[{"n":1,"supported":true,"reason":"at most 15 words"}],"all_supported":true}. Use sentence numbers starting at 1."""


def _clean(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in ("rule", "identity") and not k.startswith("_")}


def facts_for_prompt(request: dict) -> str:
    keep = {"day": request["day"], "date_words": request["date_words"], "scope": request["scope"], "events": request["events"],
            "facts": [_clean(f) for f in request["facts"]], "derived": [_clean(d) for d in request["derived"]], "patterns": [_clean(p) for p in request["patterns"]]}
    return json.dumps(keep, ensure_ascii=False)


def narrator_messages(request: dict) -> list[dict]:
    return [{"role": "system", "content": NARRATOR_SYSTEM}, {"role": "user", "content": f"FACTS:\n{facts_for_prompt(request)}"}]


def retry_messages(request: dict, previous: str, problems: list[tuple[str, str]]) -> list[dict]:
    listed = "\n".join(f"- {code}: {msg}" for code, msg in problems[:12])
    return narrator_messages(request) + [{"role": "assistant", "content": previous},
                                         {"role": "user", "content": f"The checker found these problems:\n{listed}\nReturn the full corrected JSON object only."}]


def judge_messages(request: dict, story: dict) -> list[dict]:
    numbered = [{"n": i, "text": s["text"], "type": s["type"], "cites": s["cites"]} for i, s in enumerate(story["sentences"], start=1)]
    return [{"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": f"FACTS:\n{facts_for_prompt(request)}\n\nNOTE:\n{json.dumps(numbered, ensure_ascii=False)}"}]


def parse_judge(raw: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    return sc.parse(text)
