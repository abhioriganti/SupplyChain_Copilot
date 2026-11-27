# Multi-turn evaluation report (generated)

Run `mt-20261127T013017` against the production agent as the least-privilege runtime user. **0 of 2 conversations** fully passed; **9 of 11 turns** passed. Review: `docs/evaluation_findings.md`.

| Conversation | Pattern | Turn | Question | Result | Failed checks |
|---|---|---|---|---|---|
| M7 | Context falls out of the 3-pair window | 1 | Let's focus on the Pacific Asia market. What is its late-delivery rate? | ✅ pass | - |
| M7 | Context falls out of the 3-pair window | 2 | What are the supplier corrective-action deadlines? | ✅ pass | - |
| M7 | Context falls out of the 3-pair window | 3 | What does the Supplier Code of Conduct say about bribery? | ✅ pass | - |
| M7 | Context falls out of the 3-pair window | 4 | How quickly must a supplier contain a nonconformance after being notified? | ✅ pass | - |
| M7 | Context falls out of the 3-pair window | 5 | Going back to that market: what is its on-time rate by shipping mode? | ❌ fail | facts: missing [['which market', 'specify', 'not specified', "didn't specify", 'did not specify', "haven't specified", 'all markets', 'each market', 'every market', 'clarify', 'not clear which', 'which one']] |
| M7 | Context falls out of the 3-pair window | 6 | Pacific Asia. | ✅ pass | - |
| M8 | Five-turn drill-down (context carried past the window) | 1 | What is the late-delivery rate for the LATAM market? | ✅ pass | - |
| M8 | Five-turn drill-down (context carried past the window) | 2 | Break that down by shipping mode. | ✅ pass | - |
| M8 | Five-turn drill-down (context carried past the window) | 3 | Which of those modes had the most late shipments in absolute terms? | ❌ fail | tools: used []; missing ['delivery_analytics'] |
| M8 | Five-turn drill-down (context carried past the window) | 4 | What does the supplier quality manual require for corrective action? | ✅ pass | - |
| M8 | Five-turn drill-down (context carried past the window) | 5 | Summarise what we found about LATAM in two sentences. | ✅ pass | - |
