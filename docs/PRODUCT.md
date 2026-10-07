# Product requirement

## Buyer and initial scope

Presales/security leaders in IT service firms and B2B SaaS companies. Start with one product line, English XLSX questionnaires and approved internal policies. The commercial hypothesis is that evidence collection, review routing and export save measurable SME time. Buyer willingness to pay remains unvalidated.

## Workflow

Upload questionnaire -> preserve question/cell mapping -> classify questions -> retrieve permission-filtered current evidence -> resolve applicability and conflicts -> draft cited answers -> verify claims -> request missing evidence -> SME review -> approve -> export to original workbook -> audit.

## Requirements

- Import questions without losing workbook sheet/cell identifiers or corrupting formulas, styles and merged cells.
- Preserve product edition, geography, deployment and policy validity metadata.
- Cite exact evidence snippets and versions; never fabricate certifications or capabilities.
- Mark missing, conflicting, expired or unauthorized evidence for review.
- Assign owners using configured responsibility rules, with bounded AI classification.
- Track revisions, reviewer identity, approvals and export history.
- Invalidate pending approvals when underlying evidence changes.
- Treat document text as untrusted data; retrieval cannot authorize tools.
- Export only reviewed responses; show unresolved items explicitly.

## Pilot

Interview five buyers; obtain authorized anonymized questionnaires and documents. Agree a fixed-scope paid pilot before full build: one team/product line, one workbook template, bounded evidence corpus. Establish baseline completion time and reviewer effort first.

## Proposed targets, subject to buyer agreement

- 100% source-cell mapping on supported templates.
- No unauthorized evidence in the defined permission test suite.
- No unapproved final responses in exports.
- At least 50% reduction in median human preparation/review time on agreed comparable questionnaires.
- At least 80% draft acceptance without material factual edits for answerable questions.
- Report citation correctness, abstention, unsupported claims, p95 latency and cost separately.

These are future acceptance targets, not current results. Human review is required for externally shared representations.
