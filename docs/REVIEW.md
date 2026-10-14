# Plan and baseline review

Date: 14 October 2026. Scope: the request for a complete CLIShare plan and
the pilot started before prioritising planning.

## Coverage checks

| Requirement | Treatment in the plan |
| --- | --- |
| CLI with AI accounts or API keys | Adapters per modality, official login, eligibility of native OAuth |
| Projects and guests | Identity, roles, invitations, and Git permissions kept separate |
| Shared memory | CAS, provenance, context manifest, and session privacy |
| Five agents and six agents | Full walkthrough, atomic resources, isolation, and integration queue |
| Avoiding stepping on changes | Distinguishes cooperative leases from enforcement in runner and integrator |
| Coordinated deployments | SHA and digest, idempotency, approval, reconciliation, and conditional rollback |
| Repository | Private, account and name confirmed; Git remote configured |
| Owner rules | Confirmed preferences recorded in `AGENTS.md` (local only) and global configuration |

## Findings addressed

The independent review detected a read error on large memory pages in the
pilot. It was fixed with explicit pagination and an explicit response cap,
and was verified through real HTTP. The 58 local tests and the exact
environment are documented in [STATUS.md](STATUS.md).

The plan architecture review asked for concrete Git access per guest, late
writer rejection, queued job revocation, late rollback, offline and
reconnection, context assembly, caps before the first paid runner, and
capabilities per modality and model. These items form design and acceptance
conditions; they are not considered features already implemented.

## Self-evaluation of the deliverable

Scale 1–5. The score evaluates the documentation and its evidence, not the
maturity of the future product.

| Axis | Score | Concrete evidence and limit |
| --- | --- | --- |
| Accuracy | 4 | Protocol cross-checked with code, real local tests, and official sources; AI flags and accounts not verified against real binaries |
| Completeness | 4 | Covers the requirements and the main distributed failure modes; deploy target and OAuth eligibility need a future decision or evidence |
| Clarity | 4 | Separates proposed product, pilot, and verified status; the technical detail requires section-by-section reading |
| Applicability | 4 | Contracts, files, tests, and acceptance per milestone; the sandbox needs a spike before fixing implementation and schedule |
| Conciseness | 4 | The detail answers a superplan; PLAN.md and the document index let you jump to the relevant parts |

Average: 4.0/5. The priority improvements when implementation resumes are
measuring the sandbox, validating collaboration between two machines, and
exercising the first staging target with recovery. Those tests are not
substituted by a rating.
