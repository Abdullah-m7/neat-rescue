# Financial-model findings — supplied cfo.ai exports

**NeatRescue · Team SFAB · Oct 2026–Sep 2027 · USD**

All projections below were taken from the **user-provided 12-page PDF and accompanying XLSX**, rather than calculated from real sales or imported into the technical product logic. The model's assumptions are explicitly hypothetical.

## Core pricing assumptions in the actual exported plan

| Metric | Starter | Team |
|---|---:|---:|
| Subscription / month | $49 | $199 |
| Included verification jobs | 100 | 600 |
| Expected completed jobs / month | 120 | 800 |
| Overage / job above allowance | $0.10 | $0.10 |
| Effective monthly bill (assumption) | $51 | $219 |
| Contribution / customer / month, base assumptions | $39.07 | $144.43 |

**Change from the input brief:** The earlier request proposed $49/25 and $199/150 with $2.50 excess usage. The **exported cfo.ai model itself instead uses 100/600 included jobs and $0.10 overage**. This summary preserves the exported model unchanged and does not quietly substitute the earlier request.

## The model's 12-month projections

| Indicator | Conservative | Base | Growth |
|---|---:|---:|---:|
| Hypothetical revenue | $7,062.13 | $31,649.65 | $83,648.39 |
| Hypothetical gross margin | 32.9% | 60.8% | 66.1% |
| Modeled month-12 customers | 12.0 | 52.0 | 155.2 |
| Hypothetical operating profit (unpaid founder, pre-tax) | $320.46 | $16,344.74 | $50,598.83 |
| Initial unfinanced funding gap | $1,017.15 | $427.43 | $354.86 |

*Source:* Business Plan PDF pages 2 and 5, and Financial Model scenario comparison sheets. Customer counts are expected values of a recurrence, not signed users.

## Cash/runway: crucial caveat

Actual cash today: **$0**. The financial model explicitly states real runway is zero, and all unfinanced modeled scenarios run negative in October 2026. Under the hypothetical `$5,000` bootstrap test, base monthly cash remains positive through the 12-month forecast; in a **no-customer stress** case, the $5,000 covers **10 full months** before running out in month 11. This is hypothetical money, not funding obtained by SFAB.

*Source:* Business Plan PDF page 3 (runway discussion), page 5 (comparison), pages 7–11 (monthly cash).

## Cost guardrails and adversarial risk

The model assumes **$0.05 inference + $0.015 compute + $0.005 logging = $0.07 variable delivery cost per completed verification job**, excluding other overhead and support. At a **$0.10 usage overage price**, the report identifies an **inference ceiling around $0.077/job** after other per-job costs and payment fees. At $0.15 inference, the report warns that an overage verification loses about $0.073 before support/fixed costs.

Sensitivity table: at $0.30 inference and 5% monthly churn, modeled annual operating profit changes to **−$9,290.49**, with a negative **15.7% month-12 gross margin** under the same assumed adoption.

The projected profitability is therefore conditional on **unverified, inexpensive inference assumptions**, unpaid founder effort, and projected customer acquisition. We must **NOT pitch $16k as real profit, or 52 customers as traction**.

*Source:* Business Plan PDF pages 2, 5, 6 and 12; XLSX assumptions and sensitivity sheets.

## Sponsor integration workflow

The business plan is produced by the sponsor service as a **business-side model for the agent's potential commercialization**. NeatRescue does **not** import financial forecasts into its runtime acceptance gate; doing so would conflate synthetic tech verification with commercial performance.

Judges can inspect the two original exports, compare scenario assumptions, and see the proposed safeguards above. Current sponsor evidence is the **actual files provided by the participant**. No verified cfo.ai account URL or API log is claimed.

## Verification and limitations

- XLSX contains 12 worksheets; numerical totals in the scenario summary agree with reported PDF figures.
- Formula-bearing cash cells have **numeric cached values** in original Excel XML; one analysis import layer interpreted negative amounts as date objects. The original files were left **unaltered** and the PDF confirms the monetary amounts. Inspect with Excel numeric currency formats rather than library-converted datetimes.
- Workbook package check revealed no VBA macro project or external-link components. PDF and workbook checksums are in [provenance](CFO_AI_PROVENANCE.md).
- The estimates are not tax, legal or investment advice; no financial audit of a live business has taken place.
