# Contribuir a CLIShare

El proyecto está en fase de piloto local. Lee el [estado](docs/ESTADO.md) y el
[plan](PLAN.md) antes de empezar una funcionalidad. Usa una issue para describir
un bug, discutir una mejora grande o coordinar archivos con otros colaboradores.
Para un cambio pequeño basta una PR.

## Preparar y verificar

Necesitas Git y Python 3.11+. Desde la raíz del checkout:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python scripts/clishare.py --help
```

En Linux/macOS: `PYTHONPATH=src python -m unittest discover -s tests -v`.
Ejecuta las pruebas antes y después del cambio. No necesitan credenciales de IA
ni llamadas de pago. Si falla algo antes, registra el fallo y distingue su causa
de la modificación propuesta.

## Cambios y commits

- Trabaja en una rama y comprueba que nadie esté cambiando los mismos archivos.
- Usa el mínimo código claro y correcto. Reutiliza lo existente y la biblioteca
  estándar; evita dependencias, abstracciones y archivos especulativos.
- No añadas comentarios ni docstrings explicativas al código o a los ejemplos.
  Documenta decisiones en Markdown.
- Mantén las validaciones, permisos y pruebas de concurrencia relevantes.
- Guarda cambios completos en commits pequeños: `fix(memory): reject stale versions`
  o `docs(readme): simplify the first-run example`. Explica el motivo en el cuerpo
  si aporta información; no crees commits vacíos ni divisiones artificiales.
- Conserva tu autoría real. Los agentes del propietario usan su identidad Git
  verificada; las contribuciones externas conservan la identidad de su autor.
- No subas claves, tokens, bases de datos ni `.clishare/private-memory.md`.

## Pull requests

Explica el problema, el cambio y las pruebas ejecutadas. Enlaza la issue si existe;
`Closes #N` puede cerrarla al integrar la PR. Actualiza documentación y protocolo
si cambian interfaces. El propietario revisa e integra las propuestas; abrir una
PR no equivale a fusionarla. Las contribuciones se publican bajo [MIT](LICENSE).

La plantilla de CI está en `docs/templates/ci.yml.example`; su activación sigue
pendiente del permiso de GitHub para publicar workflows.
