---
name: Feature request
description: Propón una mejora alineada con el superplan
title: "[feature] "
labels: [enhancement, needs-triage]
body:
  - type: textarea
    id: problem
    attributes:
      label: Problema que resuelve
      description: Qué limitación o fricción motiva esta propuesta.
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: Propuesta
      description: Comportamiento deseado, criterios de aceptación y, si aplica, referencias al diseño o al protocolo.
    validations:
      required: true
  - type: textarea
    id: alternative
    attributes:
      label: Alternativa considerada
      description: Otras opciones evaluadas y por qué se descartan.
  - type: dropdown
    id: superplan-task
    attributes:
      label: Tarea del superplan afectada
      options:
        - "(no asignada)"
        - M0
        - M1
        - M2
        - M3
        - M4
        - M5
        - M6
        - M7
    validations:
      required: false
  - type: dropdown
    id: impact
    attributes:
      label: Impacto estimado
      options:
        - low
        - medium
        - high
---
