"""Which flagged products go into the steward's review set (roadmap item 22/23): the grouping of nutrition flags and the choice of products.

The review set is the answer-key material for measuring the steward: real products whose newest version still carries an error flag about the nutrition
table, in five groups, with at least a set share from India. This module holds the rules once; the export notebook uses `group_case_sql` to group inside
Databricks and `choose` to pick, and the tests check that the SQL and the Python agree on the same flag names.
"""
from __future__ import annotations

# Each group is a list of alternatives; an alternative is a list of substrings that must ALL occur in the flag name. The first group that matches wins
# when a product carries several flags (the order below is the priority order).
GROUPS: list[tuple[str, list[list[str]]]] = [
    ("A_energy_mismatch", [["energy-value-in-", "does-not-match"]]),
    ("B_salt_vs_sodium", [["salt-does-not-match-sodium"]]),
    ("C_values_too_large", [["over-105"], ["over-3800"]]),
    ("D_sums_too_large", [["greater-than"]]),
]
OTHER = "E_other_nutrition"
ALL_GROUPS = [g for g, _ in GROUPS] + [OTHER]
PREFIX = "en:nutrition-"        # an OFF data-quality tag about the nutrition table


def group_of(flag: str) -> str | None:
    """The group of one flag name, or None when the flag is not about the nutrition table."""
    if not flag.startswith(PREFIX):
        return None
    for name, alternatives in GROUPS:
        if any(all(s in flag for s in alt) for alt in alternatives):
            return name
    return OTHER


def group_case_sql(column: str = "flag") -> str:
    """The same grouping as a SQL CASE expression (Spark and DuckDB both accept it)."""
    def cond(alternatives):
        return " or ".join("(" + " and ".join(f"{column} like '%{s}%'" for s in alt) + ")" for alt in alternatives)
    whens = " ".join(f"when {cond(alts)} then {i + 1}" for i, (_, alts) in enumerate(GROUPS))
    return f"case {whens} else {len(GROUPS) + 1} end"


def group_name(rank: int) -> str:
    return ALL_GROUPS[rank - 1]


def choose(candidates: list[dict], limit_per_group: int, india_per_group: int, exclude: set[str] = frozenset()) -> tuple[list[dict], dict]:
    """Pick products. `candidates` are dicts with code, group, india (0/1) and h (a hash string that fixes the order).

    Per group: up to `india_per_group` Indian products, then non-Indian ones up to `limit_per_group`; when one side runs short the other fills the group.
    Returns (chosen rows, report), where the report says per group how many were taken and how many were India, and which groups came up short.
    """
    chosen, report = [], {"per_group": {}, "short_groups": []}
    for g in ALL_GROUPS:
        pool = sorted((c for c in candidates if c["group"] == g and c["code"] not in exclude), key=lambda c: c["h"])
        india = [c for c in pool if c["india"]][:india_per_group]
        taken = {c["code"] for c in india}
        rest = [c for c in pool if c["code"] not in taken]
        non_india = [c for c in rest if not c["india"]][: max(limit_per_group - len(india), 0)]
        taken |= {c["code"] for c in non_india}
        extra = [c for c in rest if c["code"] not in taken][: max(limit_per_group - len(india) - len(non_india), 0)]   # more India when others are short
        rows = india + non_india + extra
        chosen += rows
        report["per_group"][g] = {"taken": len(rows), "india": sum(1 for c in rows if c["india"]), "available": len(pool)}
        if len(rows) < limit_per_group:
            report["short_groups"].append(g)
    return chosen, report
