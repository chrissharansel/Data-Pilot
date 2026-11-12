"""Creates demo files for trying every DataPilot feature:  python scripts/make_sample_data.py  ->  ./sample_data/

sales.csv       400 orders with planted problems: 3 extreme amounts, duplicate rows, 'north ' spelling variants,
                a rising monthly trend, and a customer_email column (row-level personal data -> triggers the approval gate)
customers.csv   customer ids, 50 of which match sales.csv and 5 of which do not (cross-dataset check)
refund_policy.txt  a short policy document for RAG questions and citations
"""
import random
from pathlib import Path

import numpy as np
import pandas as pd

out = Path(__file__).resolve().parent.parent / "sample_data"
out.mkdir(exist_ok=True)
rng, random_ = np.random.default_rng(7), random.Random(7)

n = 400
dates = pd.to_datetime("2024-01-01") + pd.to_timedelta(np.sort(rng.integers(0, 360, n)), unit="D")
month = dates.month.to_numpy()
amount = (rng.normal(120, 15, n) * (1 + 0.04 * month)).round(2)          # revenue drifts upward through the year
region = rng.choice(["North", "South", "East", "West"], n)
ids = [f"C{rng.integers(1, 61):03d}" for _ in range(n)]
sales = pd.DataFrame({"order_id": range(1001, 1001 + n), "order_date": dates.strftime("%Y-%m-%d"), "customer_id": ids,
                      "region": region, "amount": amount, "quantity": rng.integers(1, 6, n),
                      "customer_email": [f"{i.lower()}@example.com" for i in ids]})
for row, value in [(37, 9800.0), (211, 7450.5), (333, 12000.0)]:        # planted outliers
    sales.loc[row, "amount"] = value
sales.loc[[10, 90, 150], "region"] = ["north ", "NORTH", "south"]       # spelling variants
sales = pd.concat([sales, sales.iloc[[5, 6, 7]]], ignore_index=True)    # duplicates
sales.to_csv(out / "sales.csv", index=False)

cust_ids = [f"C{i:03d}" for i in range(1, 51)] + [f"X{i:03d}" for i in range(1, 6)]
pd.DataFrame({"customer_id": cust_ids, "segment": [random_.choice(["Retail", "Business", "Enterprise"]) for _ in cust_ids],
              "signup_year": [random_.choice([2021, 2022, 2023]) for _ in cust_ids]}).to_csv(out / "customers.csv", index=False)

(out / "refund_policy.txt").write_text("""Refund and Approval Policy (v3)

1. Refunds up to 500 dollars may be approved by any support agent.
2. Refunds above 500 dollars require manager approval within 5 business days.
3. Any single order above 5,000 dollars must be reviewed by the finance team before fulfilment,
   and the review outcome must be recorded in the order notes.
4. Duplicate orders must be cancelled within 48 hours of detection and the customer notified.
5. Customer contact details may only be shared with the finance and compliance teams.
""")
print(f"Wrote {sorted(p.name for p in out.iterdir())} to {out}")
