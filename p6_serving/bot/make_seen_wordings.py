"""Turn the questions already seen in the tests into catalogue wordings (2026-10-27).

  catalogue/expansion/seen_qwen_groq.yml   the Qwen and Groq questions both labellers agreed on (an entry listed by both, not a "partly answered" label); long messages contribute their question pieces
  catalogue/expansion/seen_pooled.yml      the first three question sets, as the tests added them (kept out of the pooled tests, which add the training sets themselves)

    python p6_serving/bot/make_seen_wordings.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ["PACKSENSE_NO_SEEN_POOLED"] = "1"
sys.path.insert(0, str(HERE))
import catalogue as cat  # noqa: E402
import cross_validate as cv  # noqa: E402
import final_eval as fe  # noqa: E402
import pooled_cv as pc  # noqa: E402
import segment as sg  # noqa: E402

OUT = HERE / "catalogue" / "expansion"


def dump(path: Path, title: str, data: dict[str, list[str]]) -> None:
    lines = [f"# {title}"]
    for k in sorted(data, key=lambda x: [int(p) if p.isdigit() else p for p in x.replace("b", ".b").split(".")]):
        lines.append(f'"{k}": {json.dumps(data[k], ensure_ascii=False)}')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def qwen_groq(entries: list[dict]) -> dict[str, list[str]]:
    canon = {e["id"]: e.get("same_as", e["id"]) for e in entries}
    existing = {e["id"]: {cat.normalise(w) for w in cat.wordings(e)} for e in entries}
    out: dict[str, list[str]] = {}
    for qfile, f1, f2, prefix in (("fresh_questions_qwen.txt", "labeller/labels_claude_final.txt", "labeller/labels_deepseek_final.txt", "D"),
                                  ("fresh_questions_groq.txt", "labeller/labels_claude_groq.txt", "labeller/labels_deepseek_groq.txt", "G")):
        qs = [ln for ln in (HERE / qfile).read_text(encoding="utf-8").splitlines() if ln.strip()]
        l1, l2 = fe.read_labels(HERE / f1), fe.read_labels(HERE / f2)
        for i, line in enumerate(qs, 1):
            kind, _, t = line.partition("|")
            t = t.strip()
            if kind.strip() != "ON" or "||" in t:
                continue
            (r1, ids1), (r2, ids2) = fe.parse(l1[f"{prefix}{i}"]), fe.parse(l2[f"{prefix}{i}"])
            if r1 != "entry" or r2 != "entry":                       # both labellers must say "these entries answer it" (no partial answers, no declines)
                continue
            order = [x.strip() for x in l1[f"{prefix}{i}"].split(",")]
            common = [x for x in order if x in ids2]
            if not common or common[0] not in canon:
                continue
            target = canon[common[0]]
            texts = sg.question_pieces(t) if sg.is_long(t) else [t]
            for w in texts[:2]:
                if 2 <= len(w.split()) <= 30 and cat.normalise(w) not in existing[target]:
                    out.setdefault(target, []).append(w)
                    existing[target].add(cat.normalise(w))
    return out


def pooled(entries: list[dict]) -> dict[str, list[str]]:
    before = {e["id"]: set(e.get("alt", [])) for e in entries}
    rows = [r for r in pc.load_pool("mine") if r["rule"] != "skip"]
    after = cv.with_extra_wordings(entries, rows)
    out = {}
    for e in after:
        add = [w for w in e.get("alt", []) if w not in before[e["id"]]]
        if add:
            out[e["id"]] = add
    return out


def main() -> None:
    entries = cat.load_entries()
    qg = qwen_groq(entries)
    dump(OUT / "seen_qwen_groq.yml", "Qwen and Groq questions both labellers agreed on, as wordings (2026-10-27). Long messages contribute their question pieces.", qg)
    pl = pooled(entries)
    dump(OUT / "seen_pooled.yml", "The first three question sets as wordings (2026-10-27). Skipped in the pooled tests (PACKSENSE_NO_SEEN_POOLED), which add the training sets themselves.", pl)
    print("qwen+groq wordings:", sum(len(v) for v in qg.values()), "for", len(qg), "entries")
    print("pooled wordings:", sum(len(v) for v in pl.values()), "for", len(pl), "entries")


if __name__ == "__main__":
    main()
