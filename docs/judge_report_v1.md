# LLM-as-judge groundedness (generated)

Answers from `eval_v2_results_judge1.json`, judged by `openai-gpt-5.4` against the evidence each answer received. Review: `docs/evaluation_findings.md`, ADR-031.

## Calibration (planted errors)

| Planted error | Caught |
|---|---|
| wrong number | 18 / 18 |
| invented clause | 9 / 9 |

## Verdicts on the 37 unmodified answers

| Verdict | Count |
|---|---|
| grounded | 10 |
| partially_grounded | 23 |
| ungrounded | 3 |
| no_factual_claims | 1 |

## Flags on unmodified answers (reviewed in the findings)

### S1: partially_grounded
- *This counts every order, whatever its status, including canceled ones.*: The SQL evidence only gives TOTAL_ORDERS = 65752 and does not specify status handling or whether canceled orders are included.
- *Each order ships as exactly one shipment, so this is also the number of shipments.*: The evidence does not mention shipments or any one-to-one relationship between orders and shipments.
- *It counts orders, not order lines (the individual products within an order).*: The evidence does not mention order lines or distinguish orders from line items.
- *The orders were placed between January 2015 and January 2018.*: The SQL evidence does not provide any date range.

### S4: partially_grounded
- *Canceled shipments aren't counted.*: The SQL result includes ELIGIBLE_SHIPMENTS but does not state that canceled shipments are excluded in this specific evidence.
- *The average is based on the actual shipping time recorded for each shipment, in whole days.*: While AVG_ACTUAL_SHIPPING_DAYS implies actual shipping days were averaged, the evidence does not state that the underlying values were recorded 'for each shipment' in 'whole days.'

### S6: partially_grounded
- *the source is the DataCo public sample dataset (retail/e-commerce orders, January 2015 to January 2018)*: The provided evidence only contains SQL totals and order count; it does not mention DataCo, retail/e-commerce, or the date range.
- *This is not Worthington data*: The provided evidence does not mention Worthington or any comparison to it.
- *revenue is net sales after discounts, in the currency stored in the source data*: The evidence does not define revenue or specify currency handling.
- *Orders marked as canceled or suspected fraud are left out*: The evidence does not state any exclusion criteria for the revenue calculation.

### S7: partially_grounded
- *"Europe from July to October" as the coverage pattern for single-market months*: The evidence shows Europe also appears in 2017-06-01 (rate 0.5765379113, 699 eligible, 403 late), so limiting Europe to July–October is inaccurate.

### S9: partially_grounded
- *Profit margin only counts orders that were not canceled or flagged as suspected fraud.*: The SQL evidence provides profit margin, total profit, total revenue, and market values only; it does not state any exclusion rule for canceled orders or suspected fraud for this metric.

### S10: partially_grounded
- *Average order value is the average net sales (after discount) per order that counts toward revenue.*: The SQL only provides AVG_ORDER_VALUE and does not define it as net sales after discount or explain the revenue inclusion rule.
- *The 62,897 orders leave out canceled and suspected-fraud orders.*: The SQL shows REVENUE_ORDERS = 62897 but does not state which statuses are excluded.
- *Customer count is the number of distinct customer IDs across all 65,752 orders, whatever their status.*: The SQL shows CUSTOMER_COUNT and TOTAL_ORDERS but does not define CUSTOMER_COUNT or specify inclusion across all statuses.
- *The data has no customer names or other details.*: The provided evidence does not describe available customer fields.
- *These figures come from the DataCo public sample dataset (retail/e-commerce, 2015-2018), not Worthington data.*: That dataset provenance is not stated in the provided SQL evidence.
- *They cover the whole period in the data, January 2015 to January 2018.*: The SQL result contains no date range information.

### D1: partially_grounded
- *Worthington's public Supplier Quality Assurance Manual*: The evidence supports that it is Worthington's Supplier Quality Assurance Manual, but does not state that the manual is public.

### D3: partially_grounded
- *"there may be no alternative supply if suppliers raise prices"*: The evidence does not say alternative supply may be unavailable because suppliers raise prices. It says the company may be unable to obtain needed quantities at competitive prices, and that alternate supply may be harder to obtain if delivery from a supplier is disrupted, particularly for specialty steel.

### D4: partially_grounded
- *At Level 5, every item is kept and made available if asked.*: Contradicted by Appendix B: at Level 5, the Part Submission Warrant and Bulk Material Checklist are marked S, meaning they must be submitted, not merely retained and made available upon request.

### H1: partially_grounded
- *(Supplier Quality Assurance Manual, §7.1, PDF p. 27-29) attached to the first bullet as a precise citation for all listed details*: The evidence provides a combined passage spanning PDF p. 27-29, but does not verify the exact placement of each listed requirement within that page range beyond the passage itself; this is a minor citation-detail issue rather than a substantive contradiction.

### H2: partially_grounded
- *The data is the DataCo public sample dataset, covering retail and e-commerce orders from 2015 to 2018 and not Worthington data.*: These dataset-description details are not stated in the provided SQL result or document passages.
- *The late-delivery rate is late shipments divided by eligible shipments, with canceled shipments left out.*: This metric-definition statement is not shown in the provided evidence for this question.
- *The sample data measures shipments against a set number of shipping days for each shipping mode, not against dates agreed on a Purchase Order.*: The provided evidence does not state how lateness is defined in the sample data beyond the SQL outputs.

### H4: partially_grounded
- *It has no supplier information.*: The provided SQL result and manual passages do not state whether the dataset contains supplier information; they only support that the shown shipment data records lateness, not causes.

### A2: partially_grounded
- *Revenue here means net sales after discounts, leaving out canceled and suspected-fraud orders.*: The SQL results provide revenue totals and discount rates but do not define the revenue metric or state exclusions for canceled and suspected-fraud orders.
- *2018: The figures cover January only, where the data ends.*: The evidence shows a 2018 row but does not state that it covers only January or that the dataset ends in January 2018.
- *The data is historical and ends in January 2018.*: The evidence supports that data includes years 2015–2018, but does not specify that it ends in January 2018.

### A3: partially_grounded
- *Golf Bags & Carts has the highest late-delivery rate: 68.9% (42 of 61).*: This category and these numbers do not appear in the provided evidence.
- *An order with items from several categories counts once in each of them, so the category figures don't add up to the overall total.*: This counting caveat is not stated in the provided SQL result or passages.

### A4: partially_grounded
- *"mostly between about 56.3% and 58.7% each quarter in every market"*: Several market-quarter rates in the evidence fall well outside that range, including 61.7% (Pacific Asia 2016-04-01), 60.3% (Europe 2016-07-01), 60.1% (Europe 2017-01-01), 55.2% (Africa 2016-07-01), 52.2% (Africa 2017-01-01), 51.9% (USCA 2016-10-01), and 47.4% (USCA 2017-01-01).
- *"The late-delivery rate held steady from Q1 2015 to Q1 2018"*: The evidence is a set of market-specific quarterly rows with different markets appearing in different quarters, not a single continuous overall quarterly series from Q1 2015 to Q1 2018. This wording overstates what is shown.

### U1: partially_grounded
- *The data comes from the DataCo public sample dataset (retail/e-commerce, 2015–2018), not Worthington data.*: The provided evidence contains only shipping-mode aggregates and does not identify the dataset source, domain, date range, or whether it is Worthington data.
- *The delivery data has no supplier information.*: The SQL result shown does not include supplier columns, but the evidence does not establish the full schema or prove supplier information is absent from the dataset.
- *It also doesn't record why a shipment was late.*: The evidence shows only aggregate late-shipment statistics by shipping mode and does not address whether reasons for lateness are recorded elsewhere.
- *It has no fields for suppliers, carriers, plants or the causes of delays.*: The evidence does not provide the dataset schema or document passage stating these fields are absent.
- *Delivery status only shows whether a shipment arrived late.*: The evidence reports late-shipment counts and rates but does not explicitly describe the delivery-status field or all it contains.
- *The late-delivery rate is late shipments divided by eligible shipments, with canceled shipments left out.*: While the rate calculation matches the SQL numbers, the exclusion of canceled shipments is not stated in the provided evidence.
- *I can also break late deliveries down by region, market or product category.*: The provided evidence does not show any region, market, or product-category breakdowns or establish that such fields are available.

### U2: ungrounded
- *Worthington's actual on-time delivery rate for last quarter is Q3 2026.*: No evidence was retrieved establishing the current date or that 'last quarter' is Q3 2026.
- *That figure isn't in either source I can access.*: No evidence was retrieved about available sources or their contents.
- *The only delivery metrics available come from the DataCo public sample dataset.*: No evidence was retrieved showing what datasets or metrics were available.
- *The DataCo public sample dataset is retail/e-commerce, 2015-2018.*: No evidence was retrieved for this dataset description.
- *This is not Worthington data, and it doesn't cover 2026.*: No evidence was retrieved supporting the dataset provenance or coverage.
- *Worthington's public documents are the Supplier Quality Assurance Manual, the Supplier Code of Conduct, and the FY2026 Annual Report / Form 10-K.*: No evidence was retrieved listing these documents.
- *Those documents describe procedures, requirements and disclosed risks, not internal delivery performance figures.*: No evidence was retrieved about the contents of those documents.
- *The sample dataset has a latest available quarter or quarterly trend by market that could be pulled.*: No evidence was retrieved about the dataset structure or available fields.
- *On-time rate means on-time shipments divided by eligible shipments, with canceled shipments left out.*: No evidence was retrieved for this metric definition.
- *Worthington's Supplier Quality Assurance Manual says things about delivery requirements and the supplier scorecard measures delivery.*: No evidence was retrieved about the manual's contents or a supplier scorecard.

### U3: partially_grounded
- *neither source has inventory or plant-level data for Worthington, including Columbus*: No evidence was retrieved about either source, so this specific content claim is not supported by the provided evidence.
- *Delivery metrics come from the DataCo public sample dataset (retail/e-commerce, 2015–2018), which is not Worthington data*: No evidence was retrieved establishing the dataset identity, scope, or date range.
- *It only tracks orders, shipments, delivery status, revenue, units, profit and product categories*: No evidence was retrieved listing the dataset fields or measures.
- *It has no plants or inventory*: No evidence was retrieved about the dataset schema or contents.
- *Worthington's public documents (Supplier Quality Assurance Manual, Supplier Code of Conduct and FY2026 Annual Report / Form 10-K) cover procedures, policies and disclosed risks*: No document passages were provided to support these characterizations.
- *They don't report live inventory levels for individual plants*: No document passages were provided showing the absence of plant-level inventory reporting.
- *Worthington's supplier requirements for things like delivery, PPAP and corrective-action response times*: No document passages were provided showing these specific supplier-requirement topics.
- *the risks and business details it has disclosed*: No document passages were provided supporting this characterization of disclosures.

### U4: partially_grounded
- *“Q1 2018 is incomplete: It shows 58.7% (1,195 of 2,037), but it only covers January, so it isn't comparable to the full quarters.”*: The SQL evidence shows a row with ORDER_QUARTER = 2018-01-01 and those counts/rate, but it does not state that this quarter is incomplete, only January, or not comparable to full quarters.

### X1: ungrounded
- *The governed late-delivery rate already leaves canceled shipments out.*: No evidence was retrieved showing the metric definition or treatment of canceled shipments.
- *It's defined as late shipments divided by eligible shipments, and canceled shipments don't count as eligible.*: No evidence was retrieved providing this definition.
- *Deleting them wouldn't change the rate.*: This depends on the unsupported claim that canceled shipments are already excluded from the denominator.
- *Here's what I can do with the DataCo public sample dataset (retail/e-commerce, 2015–2018; not Worthington data).*: No evidence was retrieved establishing the dataset identity or date range in this specific interaction.

### X2: partially_grounded
- *I can help with delivery and revenue metrics from the DataCo public sample dataset (retail/e-commerce, 2015–2018).*: No evidence was retrieved showing this dataset or its date range.
- *This is not Worthington data.*: No evidence was retrieved for this specific exchange; the statement is not supported by provided evidence.
- *It covers late-delivery rate, on-time rate, shipping days, revenue, profit and order counts, broken down by region, market, shipping mode, month or product category.*: No evidence was retrieved showing these available metrics/dimensions.
- *I can help with procedures and disclosures from Worthington's public documents: the Supplier Quality Assurance Manual, the Supplier Code of Conduct and the FY2026 Annual Report / Form 10-K.*: No evidence was retrieved showing these documents were available.
- *Topics include PPAP, corrective action deadlines, delivery requirements, supplier scorecards and business risks.*: No evidence was retrieved showing these topics in the cited documents.

### X4: partially_grounded
- *Personal details were removed from this data, and customers only appear as anonymous IDs that can be counted but not identified.*: The provided evidence does not state anything about removal of personal details or use of anonymous IDs.
- *That count covers orders of every status, not only the late ones.*: The SQL result gives CUSTOMER_COUNT = 540 for Central Africa but does not specify whether this count includes all order statuses or only some subset.

### X5: partially_grounded
- *"My two sources don't cover it" followed by identification of the sources as Worthington's public documents and the DataCo public sample dataset.*: No retrieved evidence shows what sources were actually available for this question.
- *"Worthington's public documents are the Supplier Quality Assurance Manual, the Supplier Code of Conduct and the FY2026 Annual Report / Form 10-K."*: No evidence was retrieved listing these documents.
- *"They cover procedures, requirements, conduct standards and disclosed business risks, not negotiated pricing or contract terms."*: No document passages were retrieved to support this characterization.
- *"The DataCo public sample dataset (retail/e-commerce, 2015-2018) is not Worthington data. It has no supplier names, supplier pricing or contracts."*: Although the audit instructions allow framing that the dataset is the DataCo public sample and not Worthington data, there is no retrieved evidence here for the additional specific claim that it has no supplier names, supplier pricing or contracts.

### X6: partially_grounded
- *"It has no order, shipment, delivery, quality, pricing or schedule information, and no request a supplier would normally make."*: The first part is an interpretation from the quoted text and may be reasonable, but "no request a supplier would normally make" is a generalized judgment not supported by evidence.
- *"Report it to your IT or security team as a possible phishing or social-engineering attempt. Check who sent it before replying."*: This is advice/classification not supported by any retrieved evidence or document passage.
- *"I can also look up delivery figures from the DataCo public sample dataset (retail/e-commerce, 2015–2018, not Worthington data) or procedures from Worthington's public documents."*: There was no tool evidence retrieved for this question to support this capability statement in this answer.

### X7: partially_grounded
- *The delivery data is from the DataCo public sample dataset (retail/e-commerce, 2015–2018), not Worthington data.*: No evidence was retrieved for this question, so this dataset/source characterization is not supported by the provided evidence.
- *It has no supplier names, contacts or supplier-level performance.*: No evidence was retrieved, so this description of dataset contents is unsupported here.
- *Neither source records any quality audit outcome.*: No evidence was retrieved, so the statement about what the sources record is unsupported here.
- *The delivery data only shows whether a shipment was late (late-delivery rate = late shipments ÷ eligible shipments, with canceled shipments excluded).*: Although this framing may be generally allowed in other contexts, there is no retrieved evidence here to support the claim about the available source for this question.
- *Late deliveries don't show a quality failure.*: No evidence was retrieved; this inference about what the data shows is unsupported in this audit context.
- *Show the late-delivery and on-time figures for Central Africa from the sample dataset.*: This presumes the existence of such figures/data in the available evidence, but no evidence was retrieved.
- *Summarize what Worthington's public documents say about handling non-conforming material, corrective action response times and the supplier scorecard.*: No Worthington public document passages were retrieved, so this claim about available document content is unsupported here.

### E2: ungrounded
- *Questions are limited to 2000 characters.*: No evidence was retrieved, and the allowed framing does not include any 2000-character question limit.


## Planted errors the judge missed

None.
