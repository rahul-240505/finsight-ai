"""Benchmark the main transaction queries with EXPLAIN (ANALYZE, BUFFERS).

Run from backend/ so the app settings and drivers are available:

    PYTHONPATH=. uv run python ../scripts/benchmark_queries.py \
        --owner-email demo@example.com --label before

Each query runs once to warm the cache, then RUNS more times; the median server-side
execution time is reported with the plan's main node, so before/after runs can be compared.
The SQL mirrors what the API runs (app/modules/transactions).
"""

import argparse
import json
import statistics
from pathlib import Path

import psycopg

from app.core.config import get_settings

RUNS = 5
QUERIES = {
    "newest_page": """
        SELECT * FROM transactions WHERE owner_id = %(owner)s
        ORDER BY occurred_at DESC, id DESC LIMIT 51""",
    "keyset_deep_page": """
        SELECT * FROM transactions WHERE owner_id = %(owner)s
          AND (occurred_at, id) < (%(mid_time)s, %(mid_id)s)
        ORDER BY occurred_at DESC, id DESC LIMIT 51""",
    "offset_deep_page": """
        SELECT * FROM transactions WHERE owner_id = %(owner)s
        ORDER BY occurred_at DESC, id DESC LIMIT 51 OFFSET 250000""",
    "account_history": """
        SELECT * FROM transactions WHERE owner_id = %(owner)s AND account_id = %(account)s
        ORDER BY occurred_at DESC, id DESC LIMIT 51""",
    "category_month": """
        SELECT * FROM transactions WHERE owner_id = %(owner)s AND category = 'travel'
          AND occurred_at >= '2025-06-01' AND occurred_at < '2025-07-01'
        ORDER BY occurred_at DESC, id DESC LIMIT 51""",
    "summary_by_currency": """
        SELECT currency, count(*), sum(amount), round(avg(amount), 2), min(amount), max(amount)
        FROM transactions WHERE owner_id = %(owner)s GROUP BY currency""",
}


def main_node(plan: dict) -> str:
    """Walk down single-child nodes to describe the plan briefly, e.g. 'Limit > Sort > Seq Scan'."""
    parts = []
    node = plan
    while node:
        name = node["Node Type"]
        if "Index Name" in node:
            name += f" ({node['Index Name']})"
        parts.append(name)
        children = node.get("Plans", [])
        node = children[0] if len(children) == 1 else None
        if len(children) > 1:
            parts.append("…")
    return " > ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--label", required=True, help="e.g. before / after")
    parser.add_argument("--out", type=Path, default=Path("../data/benchmarks"))
    args = parser.parse_args()

    url = get_settings().database_url.get_secret_value().replace("+psycopg", "")
    results = {}
    with psycopg.connect(url) as conn:
        owner = conn.execute(
            "SELECT id FROM users WHERE email = %s", (args.owner_email,)
        ).fetchone()[0]
        mid = conn.execute(
            "SELECT occurred_at, id, account_id FROM transactions WHERE owner_id = %s "
            "ORDER BY occurred_at DESC, id DESC OFFSET 250000 LIMIT 1",
            (owner,),
        ).fetchone()
        params = {"owner": owner, "mid_time": mid[0], "mid_id": mid[1], "account": mid[2]}
        rows = conn.execute("SELECT count(*) FROM transactions WHERE owner_id = %s", (owner,))
        print(f"rows for owner: {rows.fetchone()[0]}  ·  label: {args.label}  ·  runs: {RUNS}")
        conn.execute("ANALYZE transactions")
        for name, sql in QUERIES.items():
            explain = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql
            conn.execute(explain, params)  # warm-up
            times, plan = [], None
            for _ in range(RUNS):
                plan = conn.execute(explain, params).fetchone()[0][0]
                times.append(plan["Execution Time"])
            results[name] = {
                "median_ms": round(statistics.median(times), 3),
                "runs_ms": [round(t, 3) for t in times],
                "plan": main_node(plan["Plan"]),
                "shared_hit_blocks": plan["Plan"].get("Shared Hit Blocks"),
            }
            print(f"{name:22} {results[name]['median_ms']:>10.3f} ms   {results[name]['plan']}")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.label}.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
