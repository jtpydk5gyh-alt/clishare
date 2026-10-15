# Providers

What CSHCLI can and cannot do about signing in, and why.

## The short version

**No provider is eligible for native login.** `ProviderAuth.capabilities()`
reports `native_login: false` and `reason: "not_reviewed"` for every provider,
and `begin` refuses. That is the finding, not an oversight. Enabling native
login requires recording a review of that provider's own published
documentation; nobody has done one, so the registry in
`src/cshcli/provider_auth.py` ships empty on purpose.

The product keeps working exactly as before: API keys and the official CLIs.

## What the plan requires before enabling anything

1. **Check eligibility and registration first.** The registered client, the
   scopes, the modality and the applicable restrictions have to be documented.
   The plan says it plainly: *a private repository alone does not satisfy
   requirements*. Being published under MIT is not an authorisation.
2. **Anthropic stays on an API key or its official binary** while there is no
   documented authorisation for another modality. CSHCLI never reads or
   exports Claude.ai tokens and implements no OAuth proxy. See the
   [official compliance documentation](https://code.claude.com/docs/en/legal-and-compliance).
3. For OpenAI, the [Sign in with ChatGPT registration](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
   and its [current limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
   are the starting points. Neither has been reviewed here.

## Providers that already work today

| Provider | Modality | Credential |
| --- | --- | --- |
| `openai` | API key, plus the official CLI | `OPENAI_API_KEY` |
| `anthropic` | API key, plus the official CLI | `ANTHROPIC_API_KEY` |
| `google` | API key | `GEMINI_API_KEY` |
| `minimax` | API key, OpenAI-compatible route | `MINIMAX_API_KEY` |
| `codex` | Official CLI authentication | none |
| `claude-code` | Official CLI authentication | none |
| `gemini-cli` | Official CLI authentication | none |

The official CLIs are executed as installed and manage their own
authentication. CSHCLI does not copy OAuth tokens or credential files from
them, and it does not export their secrets.

## What is built behind the closed gate

The machinery exists and is tested, because a gate nobody has ever exercised
is a comment rather than a gate. Once a review happens it will be needed:

- **One-use random state.** 32 bytes, dropped from the pending list the moment
  it is consumed, so a replay finds nothing.
- **PKCE with S256**, generated per attempt, and the verifier travels only to
  the token exchange.
- **Exact redirect matching.** The redirect must be loopback and bare: no
  fragment, no pre-existing `state` or `code` parameter.
- **An expiry of ten minutes** on every pending state.
- **A local secure store**, so the token is never written to the coordinator,
  the repository or the environment. On POSIX it is `0600`; it is not a
  hardware store and does not pretend to be one.
- **The exchange happens locally.** `finish` takes a transport and a test
  asserts that exactly one exchange happens and that nothing is reported to
  the coordinator.

## What is shown before an account is used

The CSHCLI identity and the provider account are separate things, and the
record makes that explicit. Before use, CSHCLI shows the **account name**, the
**billing modality** and the **data destination**. A subscription and an API
key may have different quotas and different billing, and CSHCLI does not
switch billing mode after an error.

## Secrets never appear in output

Nothing in a reported string contains a token. The helper that would render a
sample returns its length and nothing else, matching the personal data guard's
rule: a guard that echoes the secret it found has turned a blocked action into
a leak.

## To enable a provider

1. Read that provider's own documentation for the modality you want.
2. Register a client and record what it is, in writing, not in a code comment.
3. Add a record to `REVIEWED` with `client_id`, `authorize_url`, `scope`,
   `scopes`, `modality`, `restrictions` and `reviewed_on`.
4. Re-run the suite. The `RealRegistryTests` group asserts the registry is
   empty, so it will fail until that test is updated to match the new reality
   deliberately, rather than by accident.

Step 4 matters: the test that says "nothing is eligible" is the one thing
stopping a provider from being enabled by a careless edit.