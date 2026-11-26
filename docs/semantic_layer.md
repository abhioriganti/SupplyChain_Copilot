# Semantic layer: Supply Chain Delivery Performance

**Object:** `SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV` (native Snowflake semantic view)
**DDL:** [`sql/40_semantic/01_supply_chain_delivery_sv.sql`](../sql/40_semantic/01_supply_chain_delivery_sv.sql)
**Glossary:** [business_glossary.md](business_glossary.md) · **Formulas:** [metric_definitions.md](metric_definitions.md) · **Tests:** [semantic_test_report.md](semantic_test_report.md)

## Why it exists

Without a semantic layer, every dashboard, notebook and AI prompt re-derives "late-delivery rate" on its own terms, and they drift. This data shows how far apart the versions get:

| How "late rate" or "revenue" was computed | Result |
|---|---|
| Governed (shipments, canceled excluded) | **57.31%** late rate |
| Canceled shipments left in the denominator | 54.82% |
| Order totals summed after joining to lines (fan-out) | revenue **3.49×** too high |

The semantic view stores each definition **once**, in the warehouse, next to the data. Every consumer reads it: Cortex Analyst, the Cortex Agent (Phase 4), Snowflake Intelligence and plain SQL via `SEMANTIC_VIEW()`.

## Model

```
            regions (ORDER_REGION)  ◄── many-to-one ──  orders (ORDER_ID)  = shipments
                                                            ▲
                                                            │ many-to-one
products (PRODUCT_ID) ◄── many-to-one ── order_lines (ORDER_ITEM_ID)
```

| Logical table | Physical table | Grain | Holds |
|---|---|---|---|
| `orders` | `GOLD.FACT_ORDERS` | order = shipment | delivery metrics, order dimensions |
| `order_lines` | `GOLD.FACT_ORDER_LINES` | order line | revenue, units, profit |
| `products` | `GOLD.DIM_PRODUCTS` | product | product, category, department |
| `regions` | `GOLD.DIM_REGIONS` | region | region, market |

Contents:
- **14 metrics**, 21 dimensions and 6 facts.
- Business synonyms on every important term.
- Comments that carry the business rules.
- `AI_SQL_GENERATION` and `AI_QUESTION_CATEGORIZATION` instructions.
- **3 steward-verified queries**, marked as onboarding questions.

## How it prevents inconsistent calculations

1. **One definition per metric.** `late_delivery_rate` is defined as `late_shipments / eligible_shipments`, built *from the other two governed metrics*, so the numerator and denominator can't drift apart.
2. **Exclusions are part of the metric.** The canceled-shipment rule lives inside `eligible_shipments`, so nobody needs to remember to add a filter.
3. **Analyst picks metrics, it doesn't write formulas.** In every test, the generated SQL was `SELECT … FROM SEMANTIC_VIEW(… METRICS orders.late_delivery_rate …)`, a reference to the governed metric. It never contained a recomputed `SUM(IFF(...))`. See [semantic_test_report.md](semantic_test_report.md).
4. **One meaning per word.** "Region" exists only as `regions.order_region`, even though the order fact also has a region column. Synonyms route "late rate", "delay rate", "percent late" and so on to the same metric.
5. **Verified queries.** "Which regions have the highest late-delivery rate?" matched the steward-verified query `LATE_RATE_BY_REGION`, and Analyst reported `verified_query_used`.

## How it prevents incorrect joins

1. **Relationships are declared**, so join paths aren't guessed: lines→orders, lines→products, orders→regions, all many-to-one.
2. **Each metric belongs to its grain's table.** Delivery metrics sit on `orders` (shipments) and revenue on `order_lines`. Revenue by region traverses lines→orders→regions, many-to-one all the way, so nothing is repeated.
3. **Many-to-many is deduplicated, not inflated.** Orders and products are linked only through lines, so "late rate by category" crosses a many-to-many bridge. Tested result: the semantic view returned exactly `COUNT(DISTINCT order_id)` for **51 of 51 categories**, while a naive SQL join would have inflated **29 of them** (e.g. 24,551 vs 20,386 orders).
4. **Snowflake documents** that a metric grouped by a more granular, non-related dimension is a compile error (`010234`), and undefined names fail at compile time (tested).

## Documented ambiguities

See the glossary's ambiguity table. In summary:
- "on time" includes early
- the late-rate denominator excludes canceled shipments
- average delay is over late shipments only
- revenue is net and excludes canceled and fraud orders
- order metrics grouped by category don't add up to the total
- **monthly trends are confounded by market rotation**, so Analyst is instructed to group by month **and** market, and did so in testing (61 month×market rows)

## Test summary

| Suite | What | Result |
|---|---|---|
| `python -m supplychain_copilot.semantic.validate_view` | Every governed metric via `SEMANTIC_VIEW()` against reconciled Gold, overall + 23 regions + 4 modes + 37 months; category dedup against `COUNT(DISTINCT)`; undefined-name rejection; metric registration | **9 of 9 pass** |
| `python -m supplychain_copilot.semantic.nl_tests --yes` | 9 natural-language questions through Cortex Analyst; generated SQL executed and compared with ground truth (including one negative supplier question) | **9 of 9 pass** |

## Known limitations

- Rates are returned as fractions; the UI formats them as percentages.
- `AI_SQL_GENERATION` is guidance to a model, not an enforced rule. The tests are what verify the behaviour.
- `VERIFIED_AT` was omitted, so it shows as `0`. The steward is a project role, not a person.
- The semantic view hasn't yet been granted to `SCC_APP_ROLE`; that comes in Phase 4 with the agent.
