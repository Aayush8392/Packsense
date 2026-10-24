"""Load the answer catalogue (p6_serving/bot/catalogue/*.yml): resolve shared texts, merge `same_as` wordings, and render an answer.

An answer written as "@name" is the text under `texts.name` in fixed.yml. A `today` answer always ends with the shared closing line.
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CATALOGUE = HERE / "catalogue"


def load_fixed() -> dict:
    return yaml.safe_load((CATALOGUE / "fixed.yml").read_text(encoding="utf-8"))


def load_entries() -> list[dict]:
    entries: list[dict] = []
    for path in sorted(glob.glob(str(CATALOGUE / "0*.yml"))):
        entries += yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in entries}
    for name in ("paraphrases.yml", "keywords.yml", "more_wordings.yml", "more_wordings_round2.yml"):           # natural and keyword-style extra phrasings, written for each entry
        extra_all = yaml.safe_load((CATALOGUE / name).read_text(encoding="utf-8")) or {}
        for eid, extra in extra_all.items():
            by_id[eid]["alt"] = list(dict.fromkeys(list(by_id[eid].get("alt", [])) + [str(x) for x in extra]))
    for path in ([] if os.environ.get("PACKSENSE_NO_EXPANSION") else [p for p in sorted(glob.glob(str(CATALOGUE / "expansion" / "*.yml"))) if not (os.environ.get("PACKSENSE_NO_GAP") and p.endswith("topics_gap.yml")) and not (os.environ.get("PACKSENSE_NO_SEEN_POOLED") and p.endswith("seen_pooled.yml")) and not (os.environ.get("PACKSENSE_NO_QG") and p.endswith("seen_qwen_groq.yml"))]):           # the systematic wording expansion, one file per group of topics
        for eid, extra in (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).items():
            by_id[eid]["alt"] = list(dict.fromkeys(list(by_id[eid].get("alt", [])) + [str(x) for x in extra]))
    for e in entries:                                        # a question answered by another entry lends that entry its wordings
        if e.get("same_as"):
            target = by_id[e["same_as"]]
            target["alt"] = list(dict.fromkeys(list(target.get("alt", [])) + [e["q"]] + list(e.get("alt", []))))
    return entries


def resolve(text: str, fixed: dict) -> str:
    if text.startswith("@"):
        name = text[1:]
        if name.startswith("decline_groups."):
            return resolve(fixed["decline_groups"][name.split(".", 1)[1]], fixed)
        return fixed["texts"][name]
    return text


def render(entry: dict, fixed: dict) -> str:
    text = resolve(entry["a"], fixed)
    if entry["kind"] == "today" and entry.get("status") != "deferred":
        text = f"{text} {fixed['texts']['closing_line']}"
    return text


def wordings(entry: dict) -> list[str]:
    return [entry["q"]] + list(entry.get("alt", []))


def normalise(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def load_follow_ups(entries: list[dict] | None = None) -> dict[str, list[str]]:
    """Entry id -> the entries offered as follow-up buttons under its answer (aliases resolved to their targets, no repeats, never itself)."""
    entries = entries or load_entries()
    alias = {e["id"]: e["same_as"] for e in entries if e.get("same_as")}
    raw = yaml.safe_load((CATALOGUE / "followups.yml").read_text(encoding="utf-8")) or {}
    out: dict[str, list[str]] = {}
    for eid, ids in raw.items():
        own = alias.get(eid, eid)
        out[eid] = [i for i in dict.fromkeys(alias.get(x, x) for x in ids) if i != own]
    return out


def load_families(entries: list[dict] | None = None) -> list[dict]:
    """Topic families: [{name, hub, details: {entry id: cue}}], with aliases resolved to their targets."""
    entries = entries or load_entries()
    alias = {e["id"]: e["same_as"] for e in entries if e.get("same_as")}
    raw = yaml.safe_load((CATALOGUE / "families.yml").read_text(encoding="utf-8")) or []
    return [{"name": f["name"], "hub": alias.get(f["hub"], f["hub"]), "details": {alias.get(k, k): v for k, v in f["details"].items()}} for f in raw]


# questions that share one answer with another entry (rewordings and cross-topic twins): question id -> entry id
COVERS = {
    "1.1b": "1.1", "1.1c": "1.1", "1.2b": "1.2", "1.4b": "1.4", "1.11b": "1.11", "1.15b": "1.15", "2.1b": "2.1", "2.10b": "2.10", "3.1b": "3.1",
    "3.3b": "3.3", "3.17": "3.16", "4.1b": "4.1", "5.1b": "5.1", "6.1b": "6.1", "6.5b": "6.5", "6.6": "6.5", "6.7b": "6.7", "7.1b": "7.1",
    "7.17": "7.16", "9.1b": "9.1", "9.22": "9.21", "10.7": "10.6", "10.8": "10.6", "10.10": "10.9", "10.16": "10.2", "11.2": "11.1", "11.4": "11.3",
    "12.4": "12.3", "12.6": "12.5", "12.12": "5.13", "12.14": "12.13", "13.3": "13.2", "14.2": "14.1", "15.8": "14.10", "16.4": "16.3",
}
