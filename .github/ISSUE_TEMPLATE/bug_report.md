---
name: Bug report
description: Report a reproducible defect in the local pilot
title: "[bug] "
labels: ["bug", "needs-triage"]
body:
  - type: textarea
    id: context
    attributes:
      label: Context
      description: What were you trying to do, which branch, and which leases were active?
    validations:
      required: true
  - type: textarea
    id: steps
    attributes:
      label: Steps to reproduce
      description: Numbered minimal reproduction starting from a clean checkout.
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected behavior
    validations:
      required: true
  - type: textarea
    id: observed
    attributes:
      label: Observed behavior
    validations:
      required: true
  - type: input
    id: python-version
    attributes:
      label: Python version
      placeholder: Python 3.11.x
    validations:
      required: true
  - type: dropdown
    id: os
    attributes:
      label: Operating system
      options:
        - Windows
        - macOS
        - Linux
        - Other
    validations:
      required: true
  - type: textarea
    id: logs
    attributes:
      label: Logs
      description: Paste logs only. Never paste API keys, coordination tokens, or invitation tokens.
    validations:
      required: false
---