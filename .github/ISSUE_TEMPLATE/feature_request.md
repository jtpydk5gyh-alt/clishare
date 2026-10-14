---
name: Feature request
description: Propose an improvement aligned with the superplan
title: "[feature] "
labels: ["enhancement", "needs-triage"]
body:
  - type: textarea
    id: problem
    attributes:
      label: Problem
      description: What is missing or blocking today, and who hits it?
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: Proposed change
      description: The smallest change that solves the problem.
    validations:
      required: true
  - type: textarea
    id: alternative
    attributes:
      label: Alternatives considered
    validations:
      required: false
  - type: dropdown
    id: milestone
    attributes:
      label: Milestone
      options:
        - "(unassigned)"
        - "M0"
        - "M1"
        - "M2"
        - "M3"
        - "M4"
        - "M5"
        - "M6"
        - "M7"
    validations:
      required: false
  - type: dropdown
    id: impact
    attributes:
      label: Impact
      options:
        - low
        - medium
        - high
    validations:
      required: true
---