---
name: review-engineering-phd-thesis
description: Review completed Chinese engineering doctoral dissertations for submission readiness across computing, electronics, automation, mechanical, civil, materials, energy, environmental, biomedical, and interdisciplinary engineering. Use for full-draft or final-PDF checks involving research framework and contribution mapping, Chinese-English abstract alignment, chapter structure, theory and related work, method-evidence-conclusion closure, terminology, figures/tables/equations/algorithms, captions, floats, cross-references, bibliography, PDF layout, blind review, word counts, or degree materials.
---

# Review Chinese Engineering PhD Thesis

## Objective

Perform an evidence-based review of a Chinese engineering doctoral dissertation after a complete draft exists. Find issues that affect external review, defense, reproducibility, or administrative acceptance without forcing one discipline's vocabulary or chapter template onto another.

The central method is: **extract the dissertation's local standard first, then test internal consistency and discipline-appropriate evidence.** Automated scans identify mechanical risks only; never treat their output as the final academic judgment.

## Required Shared Rules

For a full-thesis, final-submission, or cross-chapter review, read all of these files before judging the dissertation:

- `shared/checklist.md`
- `shared/discipline-adaptation.md`
- `shared/severity-rules.md`
- `shared/report-template.md`

For a narrowly scoped request, read the relevant checklist sections plus severity rules. The files in `shared/` are the single source of truth; do not create a second platform-specific checklist.

## Workflow

1. Lock the target.
   - Confirm the active source folder, Git remote/branch/commit when available, main file, bibliography, latest PDF, and submission mode.
   - If the remote is inaccessible, state exactly which local copy and commit range were actually inspected.
   - Treat source as the editable truth, the latest compiled PDF as layout truth, and primary result tables/data as numerical truth.
   - Preserve unrelated user changes and do not edit reference theses.

2. Build a local-standard sheet.
   - Extract Chinese/English titles, overall problem, research line, challenges, contributions, chapter titles, methods/systems/processes, datasets/specimens, metrics, symbols, abbreviations, and retired terms.
   - Build a mapping across abstracts, Chapter 1, framework figure, research chapters, chapter summaries, final chapter, and degree materials.

3. Classify evidence paradigms.
   - Label each contribution as one or more of: algorithm/model, system/software-hardware, experiment/process, theory/modeling, application/interdisciplinary.
   - Apply the evidence requirements in `shared/discipline-adaptation.md` contribution by contribution.

4. Run mechanical scans when files are available.

```bash
python3 scripts/scan_latex_thesis.py /path/to/thesis --term '旧术语=新术语'
python3 scripts/scan_pdf_text.py /path/to/final.pdf
```

   - Inspect source context and PDF pages before accepting a warning.
   - Do not score thesis quality by warning count.

5. Perform human review in priority order.
   - Submission integrity and anonymity.
   - Framework/contribution mapping and abstract alignment.
   - Method-evidence-conclusion closure and claim boundaries.
   - Terminology, symbols, citations, figures/tables/equations/algorithms.
   - PDF layout, word-count claims, and degree materials.

6. Report findings before optional edits.
   - For review requests, report verified findings ordered P0-P3.
   - Each finding needs location, evidence, impact, fix, and verification.
   - If no P0/P1 is found, say so while listing unverified items and residual risks.

7. Validate any requested edits.
   - Remove or isolate stale build artifacts, then rebuild or re-export when possible.
   - Re-scan retired terms, references, citations, and affected captions.
   - Visually inspect affected final PDF pages.

## Operating Boundaries

- Do not claim novelty, publication status, policy content, or standards compliance without authoritative verification.
- Do not label ablation, correlation, or sensitivity analysis as causal unless the design supports causality.
- Do not label simulation or model-judge evaluation as real-user or domain-expert validation.
- Do not globally replace terms without excluding formulas, proper names, bibliography titles, and quotations.
- Do not report blind-review placeholders as errors until checking the template mode.
- When submission is imminent, prioritize P0/P1 and avoid broad rewrites that introduce new risk.

## Output

Use `shared/report-template.md`. Lead with the submission conclusion and highest-severity findings. Keep advice direct, give exact locations, and provide replacement wording when language changes are needed.
