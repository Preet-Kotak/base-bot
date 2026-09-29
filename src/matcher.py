"""
Base matcher — compares two layouts using Hungarian algorithm.
Supports strict mode (exact type match) and fuzzy mode (grouped types).
"""

from scipy.optimize import linear_sum_assignment
import numpy as np

# ─────────────────────────────────────────────
MATCH_DISTANCE_THRESHOLD = 0.05  # max normalized distance to count as a match

# fuzzy mode — only cannon and spear count as same type
FUZZY_GROUPS = {
    "cannon": "cannon_spear",
    "spear":  "cannon_spear",
}
# ─────────────────────────────────────────────


def _get_type(building: dict, fuzzy: bool) -> str:
    """Get building type, remapped if fuzzy mode."""
    t = building["type"]
    if fuzzy:
        return FUZZY_GROUPS.get(t, t)
    return t


def match_layouts(
    layout_a: list[dict],
    layout_b: list[dict],
    fuzzy: bool = False,
) -> dict:
    """
    Compare two building layouts using Hungarian matching.

    Args:
        layout_a: list of {type, x, y} — input base
        layout_b: list of {type, x, y} — DB base
        fuzzy:    if True, use grouped types instead of exact

    Returns:
        {
            "match_pct":          float,   # 0-100
            "matched":            int,
            "total":              int,     # max(len_a, len_b)
            "matched_buildings":  list,    # pairs of matched buildings
            "unmatched_a":        list,    # buildings in A with no match
            "unmatched_b":        list,    # buildings in B with no match
        }
    """
    if not layout_a or not layout_b:
        return {
            "match_pct": 0.0,
            "matched": 0,
            "total": max(len(layout_a), len(layout_b)),
            "matched_buildings": [],
            "unmatched_a": layout_a,
            "unmatched_b": layout_b,
        }

    # group buildings by type
    def group_by_type(layout: list[dict], fuzzy: bool) -> dict[str, list]:
        groups: dict[str, list] = {}
        for b in layout:
            t = _get_type(b, fuzzy)
            groups.setdefault(t, []).append(b)
        return groups

    groups_a = group_by_type(layout_a, fuzzy)
    groups_b = group_by_type(layout_b, fuzzy)

    matched_buildings = []
    unmatched_a       = []
    unmatched_b       = []
    total_matched     = 0

    all_types = set(groups_a.keys()) | set(groups_b.keys())

    for btype in all_types:
        buildings_a = groups_a.get(btype, [])
        buildings_b = groups_b.get(btype, [])

        if not buildings_a:
            unmatched_b.extend(buildings_b)
            continue
        if not buildings_b:
            unmatched_a.extend(buildings_a)
            continue

        # build cost matrix (euclidean distance)
        n = len(buildings_a)
        m = len(buildings_b)
        cost = np.zeros((n, m))
        for i, ba in enumerate(buildings_a):
            for j, bb in enumerate(buildings_b):
                dist = np.sqrt((ba["x"] - bb["x"])**2 + (ba["y"] - bb["y"])**2)
                cost[i, j] = dist

        # Hungarian algorithm
        row_ind, col_ind = linear_sum_assignment(cost)

        matched_a = set()
        matched_b = set()

        for i, j in zip(row_ind, col_ind):
            if cost[i, j] <= MATCH_DISTANCE_THRESHOLD:
                matched_buildings.append({
                    "type":     btype,
                    "a":        buildings_a[i],
                    "b":        buildings_b[j],
                    "distance": round(float(cost[i, j]), 4),
                })
                matched_a.add(i)
                matched_b.add(j)
                total_matched += 1

        unmatched_a.extend(b for k, b in enumerate(buildings_a) if k not in matched_a)
        unmatched_b.extend(b for k, b in enumerate(buildings_b) if k not in matched_b)

    total    = max(len(layout_a), len(layout_b))
    match_pct = round((total_matched / total) * 100, 1) if total > 0 else 0.0

    return {
        "match_pct":         match_pct,
        "matched":           total_matched,
        "total":             total,
        "matched_buildings": matched_buildings,
        "unmatched_a":       unmatched_a,
        "unmatched_b":       unmatched_b,
    }
