# Contexto del proyecto — CSHCLI

Resumen del estado real, verificado contra `origin/main` el 14 de octubre
de 2026. Este documento reemplaza a la memoria de sesión para que cualquier
agente pueda orientarse sin releer la conversación. La corrección final del
historial está documentada al final.

## Identidad del repositorio

| Dato | Valor |
| --- | --- |
| Repositorio | `jtpydk5gyh-alt/cshcli`, público, licencia MIT |
| Rama por defecto | `main`, 32 commits, todos con `jtpydk5gyh-alt@users.noreply.github.com` |
| Módulo Python | `cshcli`, comando `cshcli`, script `scripts/cshcli.py` |
| Estado local | `.cshcli/`, ignorado por git |
| PRs mergeadas | 27 (`#11`–`#28`, `#30`–`#38`) |
| Pruebas | 241, todas verdes salvo 2 omitidas por falta de privilegio de symlink |
| CI | verde en Windows y Linux × Python 3.11, 3.12, 3.13; `Personal data guard` obligatorio en `main` |

## Qué es y qué no es

CSHCLI coordina varios agentes de IA sobre un proyecto compartido. Cada
persona usa sus propias credenciales; el coordinador decide quién puede
escribir qué.

**Funciona:** proyectos y roles, invitaciones de un uso, memoria versionada
con compare-and-set, reservas de recursos con fences monótonos, límites de
concurrencia aplicados, manifiesto de contexto acotado, puerta de
publicación serializada, worktrees aislados, generaciones de autorización
revocables, siete proveedores de IA y un guardián contra datos personales.

**No funciona, y está escrito como tal:** no hay sandbox (el worktree es una
frontera de rutas, no un aislamiento de procesos), las reservas son
cooperativas, no hay servicio remoto, y `deploy reserve` solo reserva un
nombre de entorno sin publicar nada.

## Arquitectura

```
CLI  ->  HTTP loopback  ->  Store (SQLite WAL)
                             ├─ identidades, proyectos, membresías
                             ├─ invitaciones
                             ├─ memoria (CAS + metadatos de revisión)
                             ├─ reservas (fence = AUTOINCREMENT)
                             ├─ reservas de ejecución + liquidaciones
                             ├─ authorization_grants (generaciones)
                             ├─ patch_attempts + accepted_patches
                             └─ eventos
```

Cada capa se puede usar sin las otras: `ContextAssembler`, `Policy` e
`IntegrationGate` toman el `Store` por parámetro y llaman a sus métodos
públicos o a un contexto de conexión ya abierto. Ninguna abre una segunda
escritura sobre la misma base, porque eso produce `database is locked`.

## Las invariantes que importan

1. **El coordinador es la única autoridad.** El cliente no decide que una
   reserva caducó por su propio reloj.
2. **Toda decisión de coordinación ocurre dentro de una transacción.**
3. **Lo desconocido nunca se convierte en cero.** Se registra en
   `unknown_usage` y se rechaza cuando la política no lo permite.
4. **Una reserva es un acuerdo cooperativo**, no un bloqueo del sistema de
   ficheros. Solo el runner lo hizo cumplir, y aún no existe.
5. **La memoria no puede cambiar la política.** Una entrada que pida subir
   el techo o permitir costes desconocidos no surte efecto.
6. **Sin datos personales en nada publicable.** Correo noreply, sin rutas de
   usuario, verificado por hook local y por CI.

## Reglas de trabajo aprendidas

- **Rama primero, commit, luego push.** Tres veces en esta sesión un
  `git reset --hard` antes de commitear destruyó trabajo. Una vez llegó a
  `main` con los tests pero sin la implementación y dejó la suite en rojo.
- **Un commit por agente.** Nada de `git add -A` cuando hay más de un
  agente en el árbol. Antes de commitear, `git status --short` y comprobar
  que la lista es la tuya.
- **Un worktree por agente.** Editar en el mismo directorio provocó que dos
  agentes pisaran el trabajo del otro tres veces.
- **Nada de `reset --hard` donde otro agente escribe.** Usa
  `git stash push -u` y un clon limpio.
- **Verificar después del commit**, no antes. Los tests en verde sobre un
  árbol que luego se pierde no prueban nada.

## Herramientas propias

| Script | Para qué |
| --- | --- |
| `scripts/guard_secrets.py` | Detecta correos, rutas de usuario, tokens y claves. Lee el contenido **committeado**, no el disco. Comprueba también que `git config user.email` sea el noreply. |
| `scripts/install_hooks.py` | Instala el hook de commit. **Nunca sobrescribe uno existente** y exige que el guard exista. |
| `scripts/push_rewritten_main.py` | Reescribe la autoría de cualquier commit con la dirección privada, suspende los rulesets, empuja con `--force-with-lease` y los restaura. |

## Lo que quedó a medias

- **`docs/GITHUB_SUPPORT_TICKET.md`** sin commitear, contiene la dirección
  privada. El hook lo bloqueó, correctamente. Decide si se envía a soporte
  tras limpiarlo.
- **Worktree del agente de auditoría** en
  `.codex/worktrees/security-audit/clishare`, con 35 ficheros sin
  commitear sobre una rama que ya no existe en `main`. Su trabajo útil ya
  está fusionado. Procedimiento en `_local/RECOVERY-audit-agent.md`.
- **Sin CI de seguridad**: solo `compileall`, tests y el guard. No hay
  `ruff`, `mypy`, `bandit` ni escaneo de dependencias.

## Hitos del superplan

| Hito | Estado |
| --- | --- |
| 1–5 Piloto local | Completo y verificado |
| 6A Contexto, política, broker | Completo: `context.py`, `policy.py`, `broker.py`, capacidades |
| 6B Worktree aislado | Completo: rutas, symlinks y junctions rechazados |
| 6C Herramientas mediadas y sandbox | Pendiente |
| 7 Servicio remoto y PostgreSQL | Pendiente |
| 8A Puerta de publicación | Completo: fences, generación, propiedad, caducidad, SHA, Git |
| 8B DAG y cola de integración | Pendiente |
| 9 Despliegues con rollback | Pendiente |
| 10 OAuth nativo elegible | Pendiente |
| 11 Presupuestos y observabilidad | Pendiente |

## Qué haría yo ahora

1. **El sandbox de 6C.** Es lo único que impide decir que CSHCLI coordina
   de verdad. Un contenedor Linux no es un lujo: es lo mínimo para impedir
   que un proceso lea la máquina anfitriona o escriba fuera del worktree.
2. **`max_runtime_seconds` por defecto de 900 s** ya está; falta aplicar el
   límite a un proceso real, que es donde se ve si funciona.
3. **Limpiar `docs/GITHUB_SUPPORT_TICKET.md`** o borrarlo. Lleva horas
   dando warnings en cada commit.
4. **Un test de flakiness conocido**: `test_capture_timeout_stops_descendants_while_parent_is_running`
   falla si la máquina está cargada. Pasa aislado. Merece un margen mayor o
   una etiqueta de `slow`.

## Corrección de autoría por squash — verificada y purgada

El aviso "`MiniMax dice haber corregido los squash`" se verificó contra
`origin/main` el 14 de octubre de 2026.

**Estado del historial público.** Los 31 commits alcanzables desde
`refs/remotes/origin/main` tienen como autor únicamente
`jtpydk5gyh-alt@users.noreply.github.com`. La auditoría incluyó:

- `git log origin/main --pretty=format:'%ae' | sort -u` devuelve un único
  correo.
- `git log origin/main --pretty=fuller` no contiene trailers `Co-authored-by`
  con otra dirección.
- No hay registro de la dirección privada ni de sus variantes por dominio
  de relay en ningún campo de autor, committer o trailer.
- El único uso literal de la cadena censurada por el guard en el árbol es
  un fixture de `tests/test_guard.py`, exento por `SELF_EXEMPT`. Su razón
  de ser es que el guard la reconozca.

**Por qué los squash reintroducen la dirección: la cuenta, no el worktree.**
La explicación anterior atribuía el problema al `git config user.email` del
agente. Es incorrecto, y por eso el historial se volvía a ensuciar una y otra
vez.

La causa real está en la cuenta de GitHub. `gh api user/emails` devuelve:

```json
[{"email":"<direccion-relay-privada>","primary":true,"verified":true,"visibility":"public"}]
```

Un único correo, el relay privado, marcado como **principal** y **público**.
Cuando alguien fusiona un PR por squash desde esa cuenta, GitHub no usa la
autoría del commit de la rama: usa el correo principal de la cuenta que
fusiona. Por eso cada squash volvía a estampar la dirección, por mucho que la
reescritura la eliminara un rato antes. El PR `#38` lo demostró de nuevo:
se mergeó limpio y el commit `2710daf` salió con el relay privado.

**Lo que hay que hacer tú, y no se puede hacer desde un token de API.**
Cambiar el correo principal de la cuenta requiere el ámbito `user:email`, que
el token de `gh` de este equipo no tiene: `GET user/emails` responde, pero
`PATCH` y `POST` devuelven 404. En la interfaz web:

1. Ajustes → correos.
2. Añade una dirección que controles y verifícala.
3. Ponla como principal.
4. Borra el relay privado, o al menos pásalo a visibilidad privada.

Hasta que eso ocurra, cada squash reintroduce la dirección y hay que volver
a ejecutar `python scripts/push_rewritten_main.py`. La noreply
`jtpydk5gyh-alt@users.noreply.github.com` no se puede añadir por API: GitHub
rechaza registrarla como correo normal porque ya la usa de forma implícita.

**Lo que sí se hizo desde el repositorio.** El ruleset `main-integrity`
exige ahora el control `Personal data guard` con
`strict_required_status_checks_policy`, así que un PR con un secreto
detectado ya no puede llegar a `main`. El commit `2710daf` se reescribió y
`main` volvió a quedar con la noreply como único correo.

**Un segundo fallo, en el propio guardián.** `committed_text` construía el
spec de git como `f"{revision}:{name}"`. Con la revisión `":"` eso da
`::nombre`, que git rechaza con error 128, y el código caía en silencio a
leer el **worktree**. El guardián llevaba tiempo sin examinar el contenido
que git estaba a punto de registrar: se/editaba el fichero, el índice
conservaba la versión anterior y el hook juzgaba el texto equivocado. Es la
misma forma del fallo, en otro sitio. Corregido en `377e0c8`, con cinco
tests que usan repos git reales. El guardián ahora falla cerrado: si git no
entrega un fichero, se reporta como ilegible en vez de sustituirlo por el
contenido del disco.

**Antes de esta sesión, en el repositorio.** Los objetos alcanzables ya
estaban limpios. El residuo eran las refs `refs/original/refs/heads/main` y
los 84 commits, trees y blobs inalcanzables que conservaban la dirección
privada en disco, aunque no en GitHub. Acciones realizadas:

1. `git update-ref -d refs/original/refs/heads/main` para soltar la backup
   ref.
2. `git reflog expire --expire=now --all` y `git reflog expire
   --expire-unreachable=now --all` para que ningún reflog mantenga
   objetos de la rama reescrita.
3. `git gc --prune=now --quiet` seguido de `git repack -A -d --quiet` y un
   `git gc --prune=now --quiet` final para podarlos.

**Después.** `git fsck --no-reflogs` no imprime nada; no quedan objetos
colgantes. La lista de refs se reduce a:

```
refs/heads/audit/security-and-integrity   noreply only, contenido ya en main
refs/heads/main                           noreply only
refs/remotes/origin/HEAD                  noreply only
refs/remotes/origin/main                  noreply only
```

**Cómo se repite, si vuelve a pasar.** El flujo documentado en
`scripts/push_rewritten_main.py`: levanta ambos rulesets, reescribe el
autor de cualquier commit cuya `AUTHOR_EMAIL` no sea noreply, empuja con
`--force-with-lease` y restaura los rulesets. Antes de un merge que haya
venido de un worktree con `user.email` sospechoso, ejecuta
`python scripts/push_rewritten_main.py` localmente y vuelve a verificar.

**Verificación reproducible.** Para retomar este estado en cualquier
momento:

```
git fetch origin --prune
git log origin/main --pretty=format:'%ae' | sort -u     # una sola línea
git for-each-ref --format='%(refname)' | while read r; do
  git log "$r" --pretty=format:'%ae' | sort -u
done | sort -u                                              # una sola línea
git fsck --no-reflogs                                       # sin salida
```