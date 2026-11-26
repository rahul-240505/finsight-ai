"""Generate a realistic synthetic transaction CSV, plus labels for injected anomalies.

Standard library only; the same seed always gives the same files.

    python3 scripts/generate_synthetic.py --rows 500000 --seed 42 \
        --out data/transactions_500k.csv --labels data/labels_500k.csv

Each account has its own currency, typical spend, favourite categories and merchants, and
active hours. About 0.5% of rows are injected anomalies (labelled in --labels, never in the
main file): very large amounts, night-time spending at unfamiliar merchants, high-risk
merchants, and rapid bursts. The labels let anomaly detection be measured.
"""

import argparse
import csv
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

CATEGORIES = {
    # category: (relative amount, merchants)
    "groceries": (1.0, ["FreshMart", "GreenGrocer", "DailyBasket", "CornerStore", "MegaFoods"]),
    "restaurants": (
        0.9,
        ["Pasta Place", "Sushi Corner", "Burger Hub", "Cafe Aroma", "Curry House"],
    ),
    "transport": (0.5, ["MetroRail", "CityCab", "FuelPoint", "ParkEasy", "BusLink"]),
    "utilities": (2.2, ["PowerGrid Energy", "AquaWater", "FiberNet", "MobileOne"]),
    "shopping": (1.8, ["StyleStore", "TechWorld", "HomeGoods", "BookNook", "SportsZone"]),
    "entertainment": (0.8, ["CinemaMax", "StreamFlix", "GameVault", "ConcertHall"]),
    "travel": (6.0, ["SkyHigh Airlines", "StayWell Hotels", "RailEurope", "CarRental Co"]),
    "health": (1.5, ["CarePharmacy", "City Clinic", "DentalCare", "VisionPlus"]),
}
HIGH_RISK_MERCHANTS = ["QuickCrypto Exchange", "LuckyBet Casino", "Offshore Transfer Ltd"]
CURRENCIES = [("USD", 0.70), ("EUR", 0.15), ("GBP", 0.15)]
START = datetime(2025, 1, 1, tzinfo=UTC)
DAYS = 365
ANOMALY_RATE = 0.005
HEADER = ["transaction_id", "account_id", "timestamp", "amount", "currency", "merchant", "category"]


def make_accounts(rng: random.Random, n: int) -> list[dict]:
    accounts = []
    for i in range(n):
        weights = [rng.random() ** 2 for _ in CATEGORIES]  # a few favourite categories
        accounts.append(
            {
                "id": f"ACC-{i:05d}",
                "currency": rng.choices([c for c, _ in CURRENCIES], [w for _, w in CURRENCIES])[0],
                "scale": math.exp(rng.gauss(math.log(35), 0.5)),  # typical spend differs a lot
                "weights": weights,
                "merchants": {
                    c: rng.sample(m, k=min(3, len(m))) for c, (_, m) in CATEGORIES.items()
                },
                "peak_hour": rng.gauss(14, 2.5),
            }
        )
    return accounts


def normal_tx(rng: random.Random, acc: dict) -> tuple:
    category = rng.choices(list(CATEGORIES), acc["weights"])[0]
    mult = CATEGORIES[category][0]
    amount = acc["scale"] * mult * math.exp(rng.gauss(0, 0.45))
    hour = rng.gauss(acc["peak_hour"], 3)
    while not 6.0 <= hour < 24.0:  # redraw instead of clamping, so no pile-up at 06:00:00
        hour = rng.gauss(acc["peak_hour"], 3)
    when = START + timedelta(days=rng.randrange(DAYS), hours=hour)
    return when, amount, rng.choice(acc["merchants"][category]), category


def anomaly_txs(rng: random.Random, acc: dict) -> tuple[str, list[tuple]]:
    kind = rng.choice(["large_amount", "night_unfamiliar", "high_risk_merchant", "burst"])
    day = START + timedelta(days=rng.randrange(DAYS))
    if kind == "large_amount":
        category = rng.choice(["shopping", "travel"])
        amount = acc["scale"] * rng.uniform(25, 60)
        merchant = rng.choice(acc["merchants"][category])
        return kind, [(day + timedelta(hours=rng.uniform(10, 18)), amount, merchant, category)]
    if kind == "night_unfamiliar":
        category = rng.choice(list(CATEGORIES))
        others = [m for m in CATEGORIES[category][1] if m not in acc["merchants"][category]]
        merchant = rng.choice(others or CATEGORIES[category][1])
        amount = acc["scale"] * rng.uniform(4, 10)
        return kind, [(day + timedelta(hours=rng.uniform(1, 4.5)), amount, merchant, category)]
    if kind == "high_risk_merchant":
        amount = acc["scale"] * rng.uniform(8, 30)
        merchant = rng.choice(HIGH_RISK_MERCHANTS)
        return kind, [(day + timedelta(hours=rng.uniform(0, 24)), amount, merchant, "transfer")]
    start = day + timedelta(hours=rng.uniform(8, 22))  # burst: many charges within minutes
    merchant = rng.choice(CATEGORIES["shopping"][1])
    return kind, [
        (
            start + timedelta(minutes=rng.uniform(0, 10)),
            acc["scale"] * rng.uniform(1.5, 4),
            merchant,
            "shopping",
        )
        for _ in range(rng.randint(4, 7))
    ]


def generate(rows: int, seed: int) -> tuple[list[list[str]], list[list[str]]]:
    rng = random.Random(seed)  # noqa: S311 - reproducible test data, not security
    accounts = make_accounts(rng, max(10, rows // 100))
    records: list[tuple] = []  # (when, account, amount, merchant, category, anomaly_kind)
    while len(records) < rows:
        acc = rng.choice(accounts)
        if rng.random() < ANOMALY_RATE:
            kind, txs = anomaly_txs(rng, acc)
            records += [(w, acc, a, m, c, kind) for w, a, m, c in txs]
        else:
            w, a, m, c = normal_tx(rng, acc)
            records.append((w, acc, a, m, c, ""))
    records = sorted(records[:rows], key=lambda r: r[0])

    out, labels = [], []
    for i, (when, acc, amount, merchant, category, kind) in enumerate(records):
        tx_id = f"TX-{i:08d}"
        out.append(
            [
                tx_id,
                acc["id"],
                when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                f"{max(amount, 0.5):.2f}",
                acc["currency"],
                merchant,
                category,
            ]
        )
        if kind:
            labels.append([tx_id, kind])
    return out, labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=500_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data/transactions.csv"))
    parser.add_argument("--labels", type=Path, default=Path("data/labels.csv"))
    args = parser.parse_args()

    rows, labels = generate(args.rows, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(rows)
    with args.labels.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["transaction_id", "anomaly_type"])
        writer.writerows(labels)
    print(
        f"wrote {len(rows)} rows to {args.out} ({len(labels)} injected anomalies in {args.labels})"
    )


if __name__ == "__main__":
    main()
