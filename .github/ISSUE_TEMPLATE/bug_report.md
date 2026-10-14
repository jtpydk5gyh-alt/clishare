---
name: Bug report
description: Reporta un fallo reproducible del piloto local
title: "[bug] "
labels: [bug, needs-triage]
body:
  - type: textarea
    id: context
    attributes:
      label: Contexto
      description: Qué intentabas hacer, entorno, rama y reservas activas.
    validations:
      required: true
  - type: textarea
    id: steps
    attributes:
      label: Pasos para reproducir
      description: Lista numerada y mínima para reproducir el fallo desde un estado limpio.
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Comportamiento esperado
      description: Qué debería haber ocurrido según el diseño y el protocolo.
    validations:
      required: true
  - type: textarea
    id: observed
    attributes:
      label: Comportamiento observado
      description: Qué ocurrió realmente, incluidos mensajes y tracebacks.
    validations:
      required: true
  - type: input
    id: python-version
    attributes:
      label: Versión de Python
      description: Salida exacta de `python --version`.
      placeholder: Python 3.11.x
  - type: dropdown
    id: os
    attributes:
      label: Sistema operativo
      options:
        - Windows
        - macOS
        - Linux
        - Other
  - type: textarea
    id: logs
    attributes:
      label: Logs sin secretos
      description: Pega solo logs; nunca pegues API keys, tokens de coordinación ni invitaciones.
      placeholder: Traceback (most recent call last): ...
---
