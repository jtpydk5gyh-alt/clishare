# Project organisation

Official repositories were reviewed on 14 October 2026:

| Project | Practice applied to CSHCLI |
| --- | --- |
| [VS Code](https://github.com/microsoft/vscode) | State what the repo delivers, document limits, and link plans |
| [GitHub CLI](https://github.com/cli/cli) | Install, useful example, and contribution guide with reproducible tests |
| [uv](https://github.com/astral-sh/uv) | Short product definition and commands with observable output |
| [FastAPI](https://github.com/fastapi/fastapi) | Separate code, tests, and documentation; an "execute and verify" walkthrough |

The existing structure of `src/cshcli`, `tests`, and `docs` is enough for
this pilot. The README provides a short entry point and `docs/USAGE.md`
keeps the detailed instructions. `LICENSE`, `CONTRIBUTING.md`, and
`SECURITY.md` cover licensing, collaboration, and private reports. No extra
components, empty directories, or monorepo-only tooling are added.

The license chosen by the owner is
[OSI MIT](https://opensource.org/license/mit), with no modifications to the
permission text. It applies to the project's own code and documentation;
external APIs keep their terms. External contributions keep their
authorship.

Issues describe work; pull requests present changes for review, in line
with the [GitHub guide](https://docs.github.com/en/get-started/using-github/communicating-on-github).
Commits must form coherent changes and explain their intent.

GitHub distinguishes the
[contributions timeline](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference)
from [profile achievements](https://docs.github.com/en/enterprise-cloud%40latest/account-and-profile/reference/profile-reference).
Achievements recognise events and milestones; there is no promise of a
trophy for an arbitrary number of commits, and no empty issues or PRs are
created to inflate counters.
