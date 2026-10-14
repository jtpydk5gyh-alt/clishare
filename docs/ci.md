# CI y actualizaciones

La plantilla activa de CI vive en `docs/templates/ci.yml.example`. Se moverá a
`.github/workflows/ci.yml` cuando el permiso `workflow` esté disponible; mientras
tanto ese archivo es la fuente de verdad del pipeline.

Dependabot abre PRs mensuales con un cooldown de 7 días para `pip` y
`github-actions`. Cada PR lleva las etiquetas `dependencies` y, según el
ecosistema, `python` o `ci`. No se asignan revisores ni responsables
automáticamente: el mantenedor verificado revisa y fusiona.

Ante una PR de Dependabot:

1. Revisar el changelog de la versión propuesta.
2. Ejecutar `python -m unittest discover -s tests -v` localmente.
3. Si pasa, fusionar.

No hay promesas de cobertura, plazos de respuesta ni métricas inventadas: el
estado real del pipeline se describe en `docs/ci.md` y en los logs de CI cuando
existan.