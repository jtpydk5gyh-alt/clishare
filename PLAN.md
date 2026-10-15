# CSHCLI plan

The main document is the
[superpowers product and implementation plan](docs/superpowers/plans/2026-10-14-cshcli.md).
It is the reference source for building the product; this file makes it easy
to find from the repository root.

The goal is for you to create a project, invite another person, and have both
of you work with your own AI accounts, coordinating five of your agents with
six of theirs through shared memory, leases, isolation, and controlled
deployments.

| Documento | Para qué |
| --- | --- |
| [Superplan](docs/superpowers/plans/2026-10-14-cshcli.md) | Producto, prioridades, arquitectura, fases, contratos, tests y aceptación |
| [Design](docs/superpowers/specs/2026-10-14-cshcli-design.md) | Decisiones de arquitectura e invariantes de coordinación |
| [Plan online](docs/PLAN-ONLINE.md) | Cómo se operar online, cómo se simplifica la interfaz, cómo se actualiza y cómo se instala |
| [Protocol](docs/PROTOCOL.md) | API exacta del piloto existente |
| [Verified status](docs/STATUS.md) | Qué existe, qué se ha probado y qué sigue propuesto |
| [README](README.md) | Cómo ejecutar el piloto y sus límites actuales |
| [Agent rules](AGENTS.md) | Reglas iniciales del repositorio; no está en el remoto público por decisión del owner |

Current owner priority, as of 15 October 2026: the
[online plan](docs/PLAN-ONLINE.md). The superplan's remaining work is
[status](docs/STATUS.md)'s "Still to do" table, which says for each item
whether it can be done on the machine that writes it. The local base already in
place is preserved as a starting point. Future capabilities in the plan are not
considered delivered until their acceptance tests pass.
