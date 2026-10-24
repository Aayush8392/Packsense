"""The shipping matcher: HybridMatcher plus matching of long messages by their question pieces (variant "qmax", adopted 2026-10-26 after the pooled padded-message test).

Variants: none (whole message only), last (last question piece), qmax (best score per entry over the question pieces; the shipping variant), allmax (whole message and every piece).
"""
from __future__ import annotations

import segment as sg
import trial_embeddings as te


class SegmentMatcher(te.HybridMatcher):
    variant = "qmax"

    def scores(self, query, skip_wording=None):
        whole = super().scores(query, skip_wording)
        if self.variant == "none" or not sg.is_long(query):
            return whole
        qs = sg.question_pieces(query)
        if not qs:
            return whole
        use = [qs[-1]] if self.variant == "last" else qs
        best: dict[str, float] = dict(whole) if self.variant == "allmax" else {}
        lex_best = dict(self.lex_last) if self.variant == "allmax" else {}
        for p in use:
            for eid, s in super().scores(p, skip_wording):
                if s > best.get(eid, -9.0):
                    best[eid] = s
            for eid, v in self.lex_last.items():
                if v > lex_best.get(eid, -9.0):
                    lex_best[eid] = v
        self.lex_last = lex_best
        return sorted(best.items(), key=lambda x: -x[1])
