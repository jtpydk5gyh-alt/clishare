# CLIShare

CLI de IA para compartir proyectos, coordinar agentes y conservar decisiones
sin compartir las credenciales personales de cada colaborador.

**Piloto local 0.1.0.** Incluye proyectos, invitaciones, memoria versionada y
reservas de archivos/entornos. Las reservas son cooperativas; el runner aislado,
la colaboración entre equipos y los despliegues reales están en el plan.

[Uso completo](docs/USAGE.md) · [Plan](PLAN.md) · [Protocolo](docs/PROTOCOL.md) ·
[Estado verificado](docs/ESTADO.md) · [Contribuir](CONTRIBUTING.md) ·
[Seguridad](SECURITY.md) · [MIT](LICENSE)

## Empezar

Python 3.11 o posterior. Sin dependencias de ejecución.

```sh
git clone https://github.com/jtpydk5gyh-alt/clishare.git
cd clishare
python scripts/clishare.py serve
```

En otra terminal PowerShell:

```powershell
$identity = python scripts/clishare.py auth register ana | ConvertFrom-Json
$env:CLISHARE_TOKEN = $identity.token
$project = python scripts/clishare.py project create demo | ConvertFrom-Json
python scripts/clishare.py lease acquire $project.id ana-1 file:src --ttl 120
```

El servidor escucha en `127.0.0.1:8765`. La última operación devuelve la reserva
de `file:src` con su identificador, caducidad y generación. Otra identidad
necesita una invitación; una reserva solapada se rechaza mientras siga activa.

## IA personal

```sh
python scripts/clishare.py provider status
python scripts/clishare.py provider login codex
python scripts/clishare.py chat --provider codex "Propón un plan"
```

También admite APIs OpenAI, Anthropic y Google mediante claves de entorno y
modelo explícito. El login requiere el CLI oficial compatible; el chat Gemini
CLI sigue pendiente. Consulta [modalidades y límites](docs/USAGE.md#cuentas-de-ia-y-api-keys).

## Desarrollo

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Código en `src/clishare`, pruebas en `tests` y documentación en `docs`. Los
cambios se proponen mediante pull requests; las issues organizan bugs y mejoras.
La [guía de contribución](CONTRIBUTING.md) explica pruebas y commits.

## Licencia

[MIT](LICENSE), texto de la [Open Source Initiative](https://opensource.org/license/mit).
Copyright © 2026 Trankideal y colaboradores de CLIShare. El código y la
documentación propios se publican bajo MIT; los servicios de IA externos
conservan sus condiciones, cuotas y facturación.
