# Coppice — IAAI-27 Research Artifact Guide

This page is a reviewer-oriented map of the Coppice research artifact. The main README remains the hackathon/project entry point; this document identifies the experiments and evidence used for the IAAI-27 manuscript.

## Paper

**Coppice: Execution-Grounded Search for Cost-Efficient Agentic Code Repair**

Target: IAAI-27, Emerging Applications of AI.

Coppice investigates whether execution-grounded branching search can improve autonomous code-repair reliability while maintaining practical inference economics. It is an experimental/pilot system, not a production-deployed repair service.

## Primary manuscript experiment

The manuscript's primary experiment is the final 10-instance SWE-bench Lite systems experiment using NVIDIA Nemotron 3 Super through Nebius Token Factory and Token Factory Sandboxes:

- 10 selected SWE-bench Lite instances
- 16 proposals per instance / 160 proposals total
- 139 mechanically applicable proposals
- 6 of 10 instances solved under the configured executable test gates
- $0.29 measured model-inference cost for the sweep
- width response, all 10 instances: 11%, 20%, 32%, 46%, 60% at widths 1, 2, 4, 8, 16
- width response, six capability-positive instances: 19%, 33%, 54%, 77%, 100%

The central empirical observation is deliberately bounded: **execution-grounded breadth amplifies an existing stochastic repair capability; it does not create capability where the underlying model has none.** Four of the ten selected instances did not solve in 16 attempts.

This experiment is **not** presented as a SWE-bench Lite leaderboard score. The selected subset, test sampling, and other limitations are documented in the README and findings.

## Independent replication

A fresh-sample run using the Docker executor produced a capability-positive width curve of 19%, 33%, 53%, 76%, 100%, compared with 19%, 33%, 54%, 77%, 100% using Token Factory Sandboxes. The two runs used different model samples and different execution backends.

Earlier development experiments remain in the repository as part of the research record. In particular, earlier nine-instance measurements are **preliminary experiments** and should not be confused with the primary 10-instance manuscript experiment above.

## Paper-to-evidence map

| Manuscript claim / result | Repository evidence |
|---|---|
| Primary 10-instance width response | `results/width-curve-sandboxes.json` |
| Independent Docker replication | `results/width-curve-nebius.json` |
| Width-curve method and interpretation | `docs/findings-04-width-curve.md` |
| Model-tier / structured-output experiment | `docs/findings-05-tier-selection.md` |
| Sandbox-vs-Docker executor measurements | `docs/findings-06-sandboxes-validated.md` |
| Reasoning-output economics | `docs/findings-02-reasoning-cost.md` |
| Diversity-claim audit / research correction | `docs/findings-07-diversity-claim.md` |
| Width analysis implementation | `bench/analyze.py` |
| Width experiment implementation | `bench/width_curve.py` |
| Search implementation | `src/coppice/search.py` |
| Model/provider implementation | `src/coppice/models.py`, `src/coppice/config.py` |
| Executor conformance and fork isolation | `tests/test_executor_conformance.py` |

## Reproduce the primary analysis

With a configured Nebius Token Factory account:

```bash
cp .env.example .env
# Add NEBIUS_API_KEY and NEBIUS_PROJECT_ID to .env or export them in the environment.

COPPICE_MAX_SPEND=6 COPPICE_PROVIDER=nebius \
  python bench/width_curve.py --backend contree --samples 16

python bench/analyze.py results/width-curve-sandboxes.json
```

The committed JSON result artifacts allow inspection of the reported experiment without rerunning paid inference.

## Verification boundary

"Solved" in the manuscript means that a candidate passed the executable gates configured for the experiment. PASS_TO_PASS is sampled at a maximum of 40 tests per branch for efficiency; therefore this should not be interpreted as a guarantee that every repository test passes. The system currently supports single-file patches and the experiment uses a selected 10-instance subset.

## Executor verification

Every executor backend is expected to satisfy the same conformance contract. Fork isolation is particularly important: sibling branches must not observe each other's filesystem writes.

```bash
pytest tests/
```

Without Nebius credentials, the ConTree integration tests are skipped rather than failed. The README documents the expected keyless and configured test counts.

## Credential and service requirements

No service credentials are committed to the repository. `.env.example` contains empty placeholders. Re-running Nebius inference or Token Factory Sandbox experiments requires the corresponding third-party account credentials and may incur service charges.

## Research history

The `docs/findings-*` files are contemporaneous engineering/research notes and intentionally retain unsuccessful approaches, corrections, preliminary measurements, and negative results. They document how the system and claims evolved. Where a historical note differs from the manuscript, the primary experiment and evidence map on this page identify the measurements used in the paper.

## Deployment status

Coppice is currently an experimental research system. The proposed deployment trajectory is human-gated: issue or CI failure → Coppice candidate search → isolated execution and evidence → developer review → pull request → existing CI/CD controls. Production impact and real-user pilot metrics are future evaluation work, not claims of the current artifact.

## License

Apache 2.0. See `LICENSE`.
