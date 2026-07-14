---
name: review-engineering-phd-thesis
description: Review complete Chinese engineering doctoral dissertation drafts for academic argument quality, contribution traceability, evidence sufficiency, reproducibility, claim boundaries, terminology, and scholarly objects. Use for full-thesis, chapter, abstract, contribution, or submission-readiness reviews across algorithm, system, experimental, theoretical, and interdisciplinary research. Load final-PDF, LaTeX/Git, blind-review, migration, or degree-material profiles only when the user explicitly needs them.
---

# Review Chinese Engineering PhD Thesis

## Objective

Review a complete Chinese engineering dissertation draft by extracting the thesis's own research entities and evidence standards, then testing whether its claims are traceable, supported, reproducible, and bounded. Do not force one discipline's vocabulary, chapter sequence, or preferred prose style onto another.

Automated scans produce **candidates**, not confirmed academic findings. Only assign P0-P3 after checking the active source, current build/PDF, original results, or authoritative source required by the claim.

## Load Rules

For every review, read:

- `shared/core-checklist.md`
- `shared/severity-rules.md`
- `shared/report-template.md`

Then classify each contribution and read only its relevant files:

- algorithm/model: `shared/paradigms/algorithm-model.md`
- system/software-hardware: `shared/paradigms/system-hardware.md`
- experiment/process: `shared/paradigms/experiment-process.md`
- theory/modeling: `shared/paradigms/theory-modeling.md`
- application/interdisciplinary: `shared/paradigms/application-interdisciplinary.md`

Load optional profiles only when the request or deliverable requires them:

- current/final PDF layout or submission package: `profiles/final-pdf.md`
- LaTeX build, active source graph, Git, paths, or provenance: `profiles/latex-build-and-provenance.md`
- anonymous or blind-review copy: `profiles/blind-review.md`
- old-template or old-topic residue: `profiles/migration-audit.md`
- degree application, achievement list, or administrative materials: `profiles/degree-materials.md`

Do not load all paradigm and profile files by default. `shared/checklist.md` and `shared/discipline-adaptation.md` are compatibility pointers, not rule sources.

## Workflow

1. **Set scope and evidence boundary.** Record the actual files/PDF/version inspected and the requested review target. Do not require Git. State unavailable evidence and checks not performed.
2. **Build the contribution map.** For each core contribution, record problem, research entity, evidence, conclusion, boundary, and locations in the abstract, Chapter 1, research chapters, and final chapter. Allow merged, cross-chapter, reordered, and short/long names when the same entity remains traceable.
3. **Select evidence paradigms.** A thesis and even one contribution may use multiple paradigms. Apply each paradigm only to the claims it supports.
4. **Run optional mechanical scans.** For LaTeX, prefer an explicit main file. For PDF, pass expected page size only when the institution specifies one.

```bash
python3 scripts/scan_latex_thesis.py /path/to/thesis --main main.tex
python3 scripts/scan_pdf_text.py /path/to/thesis.pdf
python3 scripts/scan_pdf_text.py /path/to/thesis.pdf --expected-page-size A4
```

5. **Verify candidates.** Check active source context, compile log, rendered page, result table, or external primary source as appropriate. Mark unsupported checks `not_verified`; never infer a final severity from regex output alone.
6. **Review in academic priority order.** Research line and contributions; abstract/first/final chapter consistency; method-evidence-conclusion-boundary closure; reproducibility and comparison validity; terminology/symbols; figures, tables, equations, algorithms, and citations.
7. **Report verified findings first.** Use `shared/report-template.md`. Group repeated manifestations under one root cause. Keep optional stylistic suggestions from obscuring academic risks.
8. **If edits are requested, validate them.** Recheck affected mappings, numbers, references, terms, and rendered pages without reverting unrelated user changes.

## Operating Boundaries

- Verify time-sensitive policies, standards, software versions, statistics, and publication status against current official or original sources. Prefer original or authoritative sources for stable theories and historical facts; newer is not automatically better.
- Do not turn correlation, ablation, sensitivity, attribution, or component removal into causal proof unless the design warrants it.
- Do not call model judges, simulated participants, or ordinary annotators real users or domain experts.
- Do not require fixed chapter headings, identical contribution counts, sentence-level translation alignment, or universal caption punctuation.
- Do not globally replace terms across formulas, proper names, quotations, and bibliography titles without contextual review.
- Near submission, prioritize confirmed P0/P1 and avoid broad low-value rewrites that create new risk.

## Output Contract

Every formal finding must include status, confidence, exact location, evidence, impact, minimum fix, and verification action. Only `confirmed` findings receive P0-P3. If no P0/P1 is confirmed, say so within the stated evidence coverage and list `not_verified` residual risks.
