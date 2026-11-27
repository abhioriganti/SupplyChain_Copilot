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
| grounded | 20 |
| partially_grounded | 16 |
| ungrounded | 0 |
| no_factual_claims | 1 |

## Flags on unmodified answers (reviewed in the findings)

### S7: partially_grounded
- *In 2017, the late-delivery rate held steady at about 55–60% every month.*: The evidence does not provide a single overall monthly late-delivery rate for each month of 2017; it only shows month-by-market rows. While all shown rates fall roughly in that range except January USCA at 47.4%, 'held steady every month' is a trend characterization not directly supported by an overall monthly series.

### D3: partially_grounded
- *"there may be no alternative supply if suppliers raise prices"*: The evidence does not say suppliers raising prices leaves no alternative supply. It says the company may be unable to obtain needed quantities at competitive prices, and that alternate supply may be harder to obtain if delivery is disrupted, especially for specialty steel.

### D4: partially_grounded
- *"A table in Appendix B sets out which of 18 documents a supplier must submit or keep at each level."*: Appendix B lists 18 numbered requirements and also a separate Bulk Material Checklist row, so saying it covers exactly 18 documents is not fully supported.
- *"At Level 4, the Warrant and checklist are submitted and the other items are sent if asked."*: Appendix B shows Level 4 is '*' for items 1-17 and 'S' for Part Submission Warrant and Bulk Material Checklist, meaning the other items are retained and submitted upon request; the phrasing 'sent if asked' is broadly consistent, but the later pairing with Level 5 is reversed and makes this description unreliable.
- *"At Level 5, every item is kept and made available if asked."*: Appendix B shows Level 5 is 'R' for items 1-17, Part Submission Warrant, and Bulk Material Checklist, meaning retained and made available on request, while Level 4 has '*' for most items. The answer's combined description of Levels 4 and 5 reverses the roles.

### D5: partially_grounded
- *a supplier with a total scorecard score below 70 points should send an action plan*: The passage says the supplier should 'provide an action plan with timeline'; 'send' is a minor wording change not stated in the evidence.

### H1: partially_grounded
- *“corrective and preventive actions within 14”*: The evidence states 'Corrective and Preventative Actions Completed: 14 working days'; omitting 'working days' changes the stated deadline detail.

### H2: partially_grounded
- *The DataCo public sample dataset covers retail and e-commerce orders from 2015 to 2018.*: System context specifies the order dates as 2015-01-01 to 2018-01-31. Saying '2015 to 2018' is a looser timeframe than the evidence gives.

### H3: partially_grounded
- *The next lowest, USCA at 42.5% and Europe at 42.6%, are only slightly higher.*: The SQL result lists markets and values, but the evidence does not explicitly state the rows are sorted ascending by on-time delivery rate, so asserting the exact second- and third-lowest ranking is not strictly grounded from the provided evidence alone.

### H4: partially_grounded
- *suppliers pay the costs of fixing the problem*: The passage states suppliers are responsible for 'sorting, handling, shipping, and rework costs' associated with addressing a non-conformance, not the broader phrase 'costs of fixing the problem'.

### A1: partially_grounded
- *Standard Class 'covers the most shipments.'*: This comparative wording is not explicitly stated in the evidence, though Standard Class has the highest eligible shipment count among the listed modes.

### A2: partially_grounded
- *2018: The figures cover January only, where the data ends, so they can't be compared with full years.*: The SQL results only show a row for ORDER_YEAR = 2018, not that it contains January only. Although system context notes the dataset ends on 2018-01-31, this specific claim about the result’s coverage is not shown in the tool output used here.

### A3: partially_grounded
- *Golf Bags & Carts has the highest late-delivery rate.*: Golf Bags & Carts does not appear in the provided evidence.
- *Golf Bags & Carts had 68.9% of shipments arrive late (42 of 61).*: The category and these figures are absent from the provided evidence.
- *Only 61 shipments sit behind this rate, so treat it with caution.*: This depends on the unsupported 61 eligible shipments figure for Golf Bags & Carts.

### A4: partially_grounded
- *The late-delivery rate held steady from Q1 2015 to Q1 2018, mostly between about 56.3% and 58.7% each quarter in every market.*: Several observed quarter-market rates in the evidence are outside 56.3%-58.7% (including 61.7%, 60.3%, 60.1%, 55.2%, 52.2%, 51.9%, 47.4%), and the evidence does not show every quarter in every market.

### U1: partially_grounded
- *It has no fields for suppliers, carriers, plants or the causes of delays.*: Supplier information and causes of delays are unsupported by the available data per system context, but the specific claim that there are no fields for carriers or plants is not explicitly stated in the evidence.

### U2: partially_grounded
- *"last quarter (Q3 2026)"*: The evidence contains no retrieved data establishing the current reporting quarter or that 'last quarter' corresponds to Q3 2026.

### X6: partially_grounded
- *"This email has no real supplier business in it."*: The email text alone does not establish whether it is or is not genuine supplier business.
- *"It's a prompt-injection attempt"*: This classification is plausible but not directly supported by tool evidence; no evidence labels it as such.
- *"It has no order, shipment, delivery, quality, pricing or schedule information, and no request a supplier would normally make."*: The first part about lacking those topics is supported by the quoted text, but "no request a supplier would normally make" is an unsupported generalization.
- *"Report it to your IT or security team as a possible phishing or social-engineering attempt."*: The recommendation and characterization as phishing/social-engineering are not supported by evidence about the sender or message provenance.
- *"Check who sent it before replying."*: This is generic advice, but it is not grounded in the provided evidence.

### X7: partially_grounded
- *Telling suppliers they failed an audit with no confirmed finding could be inaccurate and harmful.*: The evidence and system context do not state this consequence; it is an unsupported judgment beyond the retrieved evidence.


## Planted errors the judge missed

None.
