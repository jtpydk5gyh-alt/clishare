# Estado verificado de CLIShare

Fecha: 14 de octubre de 2026. Prioridad actual: superplan completo. El plan de
producto está en [el documento principal](superpowers/plans/2026-10-14-clishare.md).

## Base iniciada

| Capacidad | Estado observado |
| --- | --- |
| CLI ejecutable desde fuentes | Ayuda y versión 0.1.0 comprobadas |
| HTTP local y SQLite WAL | Flujo entre dos identidades probado con servidor real |
| Proyectos owner/member/viewer | Lectura y mutaciones según permisos probadas |
| Invitaciones | Caducidad, un solo uso y carreras probadas |
| Memoria | CAS, autoría, persistencia y páginas probadas |
| Reservas file/deploy | Adquisición atómica, prefijos, permisos, expiración y fences probados |
| IA por API y CLI oficial | Contratos probados con fixtures; sin llamadas reales ni gasto |
| Runner editor aislado | Propuesto, todavía no implementado |
| Servicio entre ordenadores | Propuesto, todavía no implementado |
| Integración Git automática | Propuesta, todavía no implementada |
| Publicación y rollback de despliegues | Propuestos; el piloto solo reserva entornos |
| OAuth directo propio | Propuesto y condicionado a mecanismo oficial/elegibilidad |

## Evidencia local

Entorno observado: Windows, Python 3.12.14 del runtime de Codex. El alias `python`
del sistema apunta a WindowsApps y no estaba disponible en esta sesión; para
verificar se utilizó el ejecutable:

```text
C:\Users\67gang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
```

Con `PYTHONPATH=src`, comando `python -m unittest discover -s tests -v`:
**58 pruebas correctas en 19,719 segundos**. Desglose: 27 pruebas del store,
22 de proveedores, 5 de HTTP y 4 de CLI. Las pruebas concurrentes usan once
threads sincronizados; no representan todavía once procesos distribuidos.

También se ejecutaron `python -m compileall -q src tests scripts`,
`python scripts/clishare.py --help` y `python scripts/clishare.py --version`.
El paquete se construyó localmente mediante setuptools, sin dependencias runtime.

No se han verificado cuentas de IA reales, cuotas, facturación, flags contra
binarios oficiales instalados, Linux/macOS reales ni un destino de despliegue.
Los tests de proveedores son fixtures y mocks; los tests de HTTP y SQLite usan
componentes locales reales. CI no está activada: GitHub rechazó publicar el workflow
con la credencial actual por falta del scope `workflow`. Se conserva como
[plantilla](templates/ci.yml.example), pendiente de activación; no hay resultado de CI.

## Reglas y decisiones

Inicialmente no había archivos de proyecto ni AGENTS.md en la carpeta o los
directorios padre inspeccionados. El propietario confirmó después sus reglas:
cero comentarios, ponytail, código mínimo, pruebas antes/después y commits con
su identidad. Están en [AGENTS.md](../AGENTS.md) y en sus instrucciones globales.

Nombre confirmado: `clishare`. La petición inicial fue privado; la decisión
actual es abrirlo como proyecto público bajo MIT de OSI. La apertura y la
documentación se preparan mediante una PR. La memoria personal queda en una ruta
local ignorada por Git; no forma parte de la distribución.

No se ha elegido proveedor de alojamiento o destino de producción. Las pruebas
de estilo confirmaron cero comentarios/docstrings explicativas y 58 pruebas
correctas tras retirarlos. No se alteró la lógica del piloto.
