# Contexto del proyecto — CSHCLI

Resumen del estado real, verificado contra `origin/main` el 16 de octubre
de 2026. Este documento reemplaza a la memoria de sesión para que cualquier
agente pueda orientarse sin releer la conversación.

## Checkpoint autoritativo para reanudar

Este bloque prevalece sobre cualquier fotografía histórica contradictoria que
permanezca más abajo. No reinterpretar los estados antiguos como el estado
actual.

- `origin/main` está en `66890f7`, squash del **PR #75**. Es la versión
  **0.9.0** y tiene **69 commits**. El PR pasó **14 checks**.
- La rama local activa es `fix/guard-rechaza-por-nombre`. Solo hay un worktree
  registrado, el principal. No hay agentes trabajando ni otro worktree que
  rescatar.
- Hay siete cambios preparados y todavía **no hay commit, push ni PR** para
  esta rama: `scripts/guard_secrets.py`, `tests/test_guard_names.py`,
  `README.md`, `CHANGELOG.md`, `docs/CONTEXT.md`, `docs/STATUS.md` y
  `docs/USAGE.md`.
- El guard ya rechaza credenciales por nombre antes de intentar leerlas. Cubre
  los nombres y sufijos sensibles que el chat también rechaza, conserva
  `.env.example` y evita el falso positivo `credential_manager.py`.
- `tests/test_guard_names.py` prueba nombres, sufijos, un repositorio Git real,
  un almacén binario y la concordancia entre el guard y el chat.
- La comprobación real rechazó los cuatro nombres sensibles ensayados y dejó
  pasar un archivo ordinario. No se registraron valores de credenciales.
- La última suite completa terminó con **700 pruebas verdes y 26 omitidas con
  motivo en 352.249 s**. Las 20 pruebas que dependen de PostgreSQL también se
  ejecutaron contra PostgreSQL 16.2 real y pasaron.
- `tests/test_workflow.py` todavía contiene tres líneas de comentarios
  explicativos sobre runtimes retirados. Deben eliminarse antes del commit para
  cumplir la regla del propietario de cero comentarios y docstrings
  explicativos. No se deben eliminar las constantes ni debilitar las pruebas.
- Después de esa limpieza hay que ejecutar
  `python -m unittest tests.test_workflow tests.test_guard_names tests.test_guard`,
  la auditoría de comentarios/docstrings y `python scripts/guard_secrets.py` en
  modo staged. Después: commit, push, PR, CI verde y squash a `main`, sin
  force-push.
- Mensaje de commit previsto: `fix(guard): rechazar credenciales por nombre y
  mantener las dos listas alineadas`.

El único bloqueo que requiere una decisión del propietario es la clave privada
de firma. `scripts/release.py`, `minisign` y `CSHCLI_SIGNING_KEY` están
instalados, automatizados y probados con una clave temporal ya eliminada. No se
debe crear una identidad criptográfica permanente en nombre del propietario.

Continúan declaradamente sin verificar: once máquinas reales en lugar de once
procesos, una segunda máquina, una cadena TLS pública y un restore mientras otra
máquina sirve tráfico. Por eso `RemoteStore.verification()` sigue devolviendo
`unverified` y `assert_production_ready()` sigue negándose correctamente.

Decisiones que no deben reabrirse al retomar: el chat permanece de solo lectura;
`cshcli start` conserva el menú de dos ramas; `cshcli` abre el chat; el usuario
no arranca un servidor manualmente; `web/` no se publica; y nunca se exponen ni
se copian claves, credenciales, direcciones privadas o muestras de secretos.

## Última tranche: el chat conoce el proyecto — 0.7.0 y 0.8.0

Dos PRs y dos squashes: **PR #65** → `ce65531` con el índice del proyecto y
`/ver`, y **PR #67** → `0162d76` con `/buscar`. Entre ambos entró el **PR #66**
(`69db85b`), que restauró los formularios de incidencia en formato YAML; no
toca código del paquete y no cambió nada de lo que se describe aquí.

Commits en la primera rama: `aadf1d2` con el código, `5b948de` con la versión y
la documentación, y `2a67ac2` cerrando el contexto.

Qué aporta, en cuatro archivos y cuatro sitios de cableado:

- `src/cshcli/knowledge.py` es nuevo. `index_text` recorre la carpeta actual y
  devuelve los archivos que caben en 4000 caracteres, README y `docs/`, `src/`,
  `tests/` primero, declarando cuántos se quedaron fuera. `note_text` lee un
  archivo y lo devuelve como bloque delimitado, con el contenido recortado para
  que el **mensaje completo** quepa en el presupuesto.
- `run_loop` acepta `note` y `search` opcionales y reconoce `/ver` y
  `/buscar`. Sin lector detrás, `/ver` se rechaza en vez de mandarse al
  proveedor como si fuera una pregunta. Lo mismo con `/buscar`.
- `_chat_loop` compone el contexto con la memoria **y** el índice, y entrega los
  dos. Un error de lectura del disco deja el contexto vacío y el chat arranca
  igual.

**Las decisiones, con su razón:**

1. **El índice es la carpeta desde la que se abrió el CLI**, no el proyecto
   guardado en el coordinador. Quien escribe `cshcli` dentro de su repositorio
   quiere que el agente hable de ese repositorio.
2. **Leer y buscar reutilizan `Workspace`.** El runner ya rechaza rutas
   absolutas, `..`, metadatos de Git, symlinks, junctions y hardlinks; un
   resolvedor nuevo para el chat sería una puerta nueva con el mismo nombre y un
   test menos detrás.
3. **El chat lee y busca; no ejecuta.** Abrir una puerta de ejecución aquí sería
   un sandbox nuevo, y el sandbox sigue sin existir.
4. **Índice y búsqueda comparten un solo recorrido** (`_walk`). Dos copias
   acabarían discrepando sin que nadie lo notara, y el usuario vería un archivo
   en el índice que la búsqueda no encuentra.
5. **Una búsqueda sin resultados no llama al proveedor.** Imprime que no está y
   sigue. La respuesta ya se sabe en local; pagar por oír "no hay nada" no
   ayuda a nadie.

**Lo que no se ha hecho, y sigue siendo una decisión del propietario:** que el
agente pueda **cambiar** un archivo. Eso necesita la puerta de publicación y un
concepto de parche, no una función de lectura. Y nada de esto está probado
contra una API real: que el modelo aproveche el índice y las coincidencias es
suyo, no medido aquí. Lo que sí se comprueba aquí es que una búsqueda vacía no
cuesta, porque eso se decide en local.

**Un efecto secundario que conviene conocer, ya resuelto:** desde 0.7.0 el
índice listaba `docs/GITHUB_SUPPORT_TICKET.md`, un archivo sin trackear con un
dato privado dentro, así que `/ver` podía leerlo y mandarlo al proveedor. **El
propietario decidió borrarlo el 16 de octubre**, y ya no está.

Verificación: `622` pruebas verdes y `8` omitidas con motivo en
`366.718 s`, con `PYTHONPATH=src`. Los 8 omitidos son cinco casos de symlink
que esta máquina no concede, dos de PostgreSQL que no existen aquí y uno de
permisos POSIX que no aplica en Windows; los casos de junction de Windows sí
corren. `compileall`, el guard y la auditoría AST de docstrings (`[]`) pasan.

## Tranche: infraestructura real — 0.9.0

Lo que llevaba semanas declarado como **"no se puede en esta máquina"** ya se
puede. Sin Docker, sin WSL y sin privilegios de administrador.

**La vía: `pip install pgserver`** trae los binarios de PostgreSQL 16.2.
`initdb` levanta un clúster de verdad en `~/cshcli-pg/cluster`, puerto 55432, en
17.9 s. El driver es el extra `remote` que el proyecto ya declaraba. **Ninguno
de los dos es dependencia del producto**: el paquete sigue sin tener ninguna.

## Los cuatro defectos que solo aparecieron al probar de verdad

Esto es lo que justifica el trabajo: los cuatro estaban en el código y **ninguno
podía verse sin una base de datos real**.

1. **`REAL` es `float4` en PostgreSQL.** El esquema declaraba cada marca de
   tiempo como `REAL`, que guarda siete cifras significativas. Un instante Unix
   de este siglo necesita trece: una lease que caducaba en 60 segundos se
   guardaba redondeada a los **128 segundos más cercanos** y seguía viva
   minutos. En SQLite `REAL` es float64, y por eso el piloto no lo vio. Ahora
   todo es `DOUBLE PRECISION`, y hay un test que falla si vuelve un `REAL`.

2. **La migración y su rollback eran el mismo fichero.** `001_remote.sql`
   terminaba en `DROP TABLE`, así que aplicarla creaba el esquema y lo borraba
   acto seguido. El rollback pasó a `001_remote.down.sql`, y `scripts/migrate.py`
   **rechaza cualquier fichero cuyo texto contenga `DROP`**. El defecto se
   convirtió en invarianza.

3. **`sys.path.insert(0, ".../scripts")` rompía los procesos hijo.** En Windows,
   `spawn` hereda el `sys.path`, así que `import cshcli` resolví­a
   `scripts/cshcli.py` y los once procesos de la carrera morían con código 1
   — un fallo a kilómetros de su causa. Ahora se usa `append`, y un test
   comprueba que nadie vuelva a usar `insert`.

4. **`install_hooks.py` fallaba en un worktree enlazado.** Allí `.git` es un
   *fichero*, no un directorio: el instalador reventaba con `FileExistsError` y
   **el hook no se instalaba, es decir el guard dejaba de bloquear commits**.
   Este lo encontró un test del worktree del agente de auditoría que `main` no
   tenía. Resuelto con `git rev-parse --git-common-dir`, y rescatados.

## Lo que quedó probado, con su evidencia

| Qué | Evidencia |
| --- | --- |
| PostgreSQL real | 16.2 en Windows, nueve tablas y la secuencia de fences |
| Concurrencia | once procesos independientes, `file:src` contra `file:src/a.py`, **gana exactamente uno**, y en la base queda una sola lease |
| Restore | `pg_dump`/`pg_restore` sobre base vacía, recuento por tabla, **restaurar sobre base poblada se rechaza**, y el fence nunca retrocede |
| HTTPS | `serve --remote` levanta, `/healthz` responde por TLS con `database: postgresql`; el HTTP plano se rechaza y un cliente que no confía en el certificado se rechaza en el handshake |

## Lo que sigue sin estar verificado, y por qué está bien que lo esté

`RemoteStore.verification()` **sigue diciendo `unverified`** y
`assert_production_ready()` sigue negándose a servir. No es que no se haya
avanzado: el criterio que codifica son once **máquinas**, y esto es una. Que
once procesos ganen uno demuestra que el bloqueo de fila funciona; no que el
servicio sea seguro de exponer.

Tampoco está: una cadena de confianza pública —el certificado es autofirmado y
dura 30 días—, una segunda máquina, ni un restore hecho mientras otra máquina
sirve tráfico.

## Los dos tests que fallaban bajo carga

Un job de Windows 3.11 fallo el 16 de octubre en
`test_server.py::test_authentication_and_browser_requests_are_rejected`, con un
reset de conexion y no con un 403 ausente. El mismo commit paso ese job en el
run de push: era carga, no un defecto del codigo.

Dos arreglos, ambos con la misma regla: **un test que no puede distinguir un
fallo real de ruido de la maquina no vale lo que dice**.

1. `test_capture_timeout_stops_descendants_while_parent_is_running` depended
   de que la maquina arrancara un proceso en 200 ms. Ahora el hijo espera 3 s,
   quince veces el timeout, y el margen ya no depende de la carga. Se anade
   `test_capture_timeout_holds_repeatedly_under_load`, que lo comprueba tres
   veces seguidas.
2. `test_server.py` reintenta **solo** ante un error de conexion, hasta tres
   veces con espera creciente. Nunca reintenta un codigo HTTP: si el 403
   desaparece, el test sigue fallando, que es lo que tiene que comprobar.

**Comprobado de las dos formas que importan:**

- Bajo carga: seis copias en paralelo del test de captura, y cuatro copias de
  doce pruebas, todas en verde.
- Con el codigo roto a proposito: al neutralizar la rama de Windows que mata el
  arbol de procesos, el test falla con *"el hijo sobrevivio al timeout de su
  padre"*. Un test que siempre pasa noHabria detectado nada.

## El guard dejaba pasar credenciales que el chat ya rechazaba

Las dos listas de secretos erans listas distintas, y ya habian divergido. El chat
rechazaba `id_rsa` y el guard lo dejaba pasar si el fichero no tenia un marcador
legible. Comprobado sobre un repositorio de verdad:

```
guard: sin datos personales
```

con dentro un `.netrc` con contrasena, un `.npmrc` con un token, un `id_rsa` sin
clave real y un `wallet.jks` binario. Los cuatro se podian commitear.

El guard miraba **contenido**; el chat miraba **nombre**. Los dos criterios valen
y ninguno sustituye al otro: el guard ve un token en un fichero de nombre
inocuo, y el nombre ve un secreto en un formato que los patrones no reconocen.

Ahora el guard tiene las dos capas. `is_credential_file` rechaza por nombre
antes de leer nada, y `tests/test_guard_names.py` incluye una prueba que exige
**que el guard y el chat reconozcan lo mismo**, para que las dos listas no vuelvan
a separarse.

Un falso positivo que hubo que arreglar de paso: filtrar por la palabra
"credential" marcaba `credential_manager.py` como secreto. Los nombres se
reconocen por forma, no por contenido de la palabra.

## El indice del chat anunciaaba las credenciales

Un `.env` con la clave de API, un `credentials.json`, un `server.key`: todo eso
esta en `.gitignore`, asi que el guard lo impide commitear. Pero el indice del
chat se construye recorriendo la carpeta, y ahi noFilteringaba nada:

```
Archivos del proyecto actual (7):
- .env
- .netrc
- .npmrc
- credentials.json
- normal.py
- server.crt
- server.key
```

Escribir `/ver .env` mandaba la clave de API al proveedor. Y el indice no solo
lo permitia: **lo anunciaba**.

El guard protege el commit; faltaba el otro lado, que es no mandar el secreto
fuera de la maquina. Los dos hacen falta: un fichero que git ignora sigue siendo
un fichero en la carpeta donde alguien acaba de abrir el CLI.

Ahora `is_secret` reconoce `.env*`, `.netrc`, `.npmrc`, `.pypirc`,
`credentials.json`, `service-account*`, `id_rsa`, y los sufijos `.pem`, `.key`,
`.p12`, `.pfx`, `.crt`, `.keystore`, `.asc`. El indice **no los anuncia** y
`/ver` **se niega** con `secret_refused`. `.env.example` sigue leyendose: un
ejemplo no es un secreto.

## El CI corria sobre un runtime retirado

`actions/checkout@v4` y `actions/setup-python@v5` apuntan a **Node 20**, que
llego a su fin en abril de 2026 y que GitHub elimino de los runners durante el
verano de 2026. No rompio nada porque GitHub los ejecutaba igualmente sobre
Node 24, pero cada job imprimia un aviso, y cuando la retirada sea completa el
CI caera sin avisar.

Ahora el workflow usa `actions/checkout@v7` y `actions/setup-python@v7`, que
son las versiones que documenta el propio Marketplace y que ya son Node 24.
`tests/test_workflow.py` falla si alguna accion vuelve a una mayor retirada, si
alguna deja de fijarse a una mayor, y comprueba que la matriz de Python y el
guard siguen intactos.

Comprobado contra las paginas de releases de ambos proyectos, no de memoria.

## El worktree del agente de auditoría — cerrado

`~/.codex/worktrees/security-audit/clishare`, rama `audit/security-and-integrity`,
35 ficheros sin commitear. Revisado fichero a fichero contra `main`.

**Lo que había y su valor:**

| Qué | Decisión |
| --- | --- |
| 2 tests del guard que `main` no tenía | **Rescatados.** El hook instalado bloqueando de verdad un commit con secreto, y el instalador en un worktree enlazado. El segundo destapó un fallo de seguridad |
| 30 patrones de `.gitignore` para credenciales | **Rescatados.** `.netrc`, `.npmrc`, `.pypirc`, `credentials.json`, `service-account*.json`, `*.p12`, `*.pfx`, `*.crt`, `*.keystore` y `*_PRIVATE.md`. Ahora hay un test que falla si alguno vuelve a ser stageable |
| El resto del código | Versiones **anteriores** de ficheros que `main` lleva 20 versiones por delante. Nada rescatable |
| `OPEN_SOURCE_PLAN.md` con la direccion relay privada del propietario | **No se rescata.** Es exactamente el dato que este repositorio existe para no publicar |

**El detalle que decidia la urgencia:** ese worktree contenia la direccion
relay privada del propietario, la que este repositorio existe para no
publicar. `main` ya no la tiene. Mientras el worktree siga en disco, un
`git add` desde alli la volveria a meter.

El guard de datos personales bloqueo este mismo commit al escribir esa
direccion aqui, y con razon: describir el hallazgo no es una excepcion a no
publicarlo.

Cerrado el 16 de octubre.

## Lo único que sigue bloqueado

**La firma de la release, y es una decisión del propietario, no un bloqueo de
infraestructura.**

**El mecanismo está instalado, automatizado y probado. Falta una línea.**

- `minisign` 0.12, **verificado contra la clave pública que publica el propio
  proyecto** antes de ejecutarlo.
- `scripts/release.py` firma solo: encuentra el firmante, firma `SHA256SUMS` y
  comprueba que la firma existe. Comprobado con una clave de descarte que se
  borró después: la firma verificar, sin clave el release se construye y **lo
  dice**, y con `--require-signature` se niega con código 1.
- Sin esos cambios eran tres comandos que alguien podia olvidar.

```powershell
$env:CSHCLI_SIGNING_KEY = "…tu-clave.key"
python scripts/release.py
```

La clave privada es suya y no debe estar nunca en el repositorio ni en una copia
que se sincronice. El procedimiento está en `docs/RELEASES.md`.

## Dónde está el proyecto hoy

**Versión 0.9.0, construida localmente con checksum; no publicada ni firmada.**
61 commits en `origin/main`, todos con noreply. La suite local actual y sus
omisiones justificadas se registran abajo. CI verde en Windows y Linux × Python
3.11, 3.12 y 3.13. Un solo ruleset, `main-integrity`, con `Personal data
guard` como control obligatorio.

**Lo cerrado en este tramo, por orden:**

| Hito | Qué aporta |
| --- | --- |
| 6C | `Runner` que medie cada escritura y no expone ejecución de comandos |
| 7 | `Identity` con sesiones revocables; `RemoteStore`, migración y operaciones. **Sin servidor levantado** |
| 8A | Puerta de publicación: fences, generación, propiedad, caducidad, SHA |
| 8B | `TaskService` con `claim` atómico e `IntegrationQueue` con compare-and-swap |
| 9 | Despliegues con idempotencia y rollback; **cerrado** con las cuatro comprobaciones contra un proceso real |
| 10 | `ProviderAuth` con la puerta de elegibilidad **cerrada a propósito** |
| 11 | `Usage` y `BudgetPolicy` con `Decimal`. **Cerrada en su parte de uso** |

**El siguiente trabajo está escrito y casi todo hecho**: `docs/PLAN-ONLINE.md`
cubre hacer que funcione online, simplificar la primera ejecución, documentar el
comando de instalación y añadir `cshcli update`. Los pasos 1, 2 y 3 están
hechos; **el paso 4, `serve --remote`, necesita una máquina**.

## Identidad del repositorio

| Dato | Valor |
| --- | --- |
| Repositorio | `jtpydk5gyh-alt/cshcli`, público, licencia MIT |
| Versión | `0.9.0`, artefacto local con `dist/SHA256SUMS`; no publicado ni firmado |
| Rama por defecto | `main`, 61 commits en `origin/main`, todos con la noreply de GitHub |
| Módulo Python | `cshcli`, 24 módulos más `__init__` y `__main__`, comando `cshcli`, script `scripts/cshcli.py` |
| Estado local | `.cshcli/`, ignorado por git |
| PRs mergeadas | 67, sin `--admin`: el control obligatorio se respeta |
| Pruebas | 700 verdes; 26 omitidas con motivo: 20 necesitan `CSHCLI_REMOTE_DSN` y **se ejecutaron** contra PostgreSQL 16.2 |
| CI | verde en Windows y Linux × Python 3.11, 3.12, 3.13 |

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
- **Un `reset --hard` sin mirar destruye trabajo, también el propio.**
  `push_rewritten_main.py` incumplía la regla de arriba y se comió un arreglo
  sin commitear. Ya rechaza el árbol sucio antes de resetear.
- **Un control de seguridad no se relaja para que pase el código propio.** El
  guard ve un arroba seguido de algo con punto, y toma por correo cualquier
  decorador con nombre cualificado. Al escribir
  `tests/test_remote_postgres.py` bloqueó el commit; la respuesta fue
  reescribir el test con `self.skipTest()` en `setUp`, no tocar el patrón. Y
  al documentarlo aquí, el párrafo se trippinga a sí mismo, que es la mejor
  prueba de que el control funciona. Merece la pena tenerlo en cuenta antes de
  escribir más tests con decoradores.

## Herramientas propias

| Script | Para qué |
| --- | --- |
| `scripts/guard_secrets.py` | Detecta correos, rutas de usuario, tokens y claves. Lee el contenido **committeado**, no el disco. Comprueba también que `git config user.email` sea el noreply. |
| `scripts/install_hooks.py` | Instala el hook de commit. **Nunca sobrescribe uno existente** y exige que el guard exista. |
| `scripts/push_rewritten_main.py` | Reescribe la autoría de cualquier commit con la dirección privada, suspende los rulesets, empuja con `--force-with-lease` y los restaura. |

## Decisiones del propietario sobre el chat — 16 de octubre

1. **`docs/GITHUB_SUPPORT_TICKET.md` se borra.** No se limpia ni se envía.
   Estaba sin trackear con un dato privado dentro y bloqueando commits; era
   ruido. Borrado de forma recuperable, fuera del índice de git, así que no
   aparece en ningún commit.
2. **El chat sigue solo leyendo.** No se abre la frontera de escritura desde el
   chat. La puerta de publicación y la cola de integración existen y funcionan,
   pero conectarlas al chat es otra cosa: el que escribe pasa a ser un modelo, y
   un modelo no es una persona revisando un diff. Si algún día se abre, la vía
   es `accept_patch` más compare-and-swap, no una escritura directa.
3. **Se para aquí** hasta que el propietario diga. Lo que no dependía de
   infraestructura ni de su decisión está cerrado.

## Lo que quedó a medias

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
| 6C Herramientas mediadas y sandbox | **Completo.** `Runner` con escrituras mediadas, validación de lease inmediata y heartbeat. **No es un contenedor**: sin límites de CPU, memoria, procesos ni red |
| 7 Servicio remoto y PostgreSQL | **Parcial y declarado.** Driver como extra, `RemoteStore` con bloqueo de fila, migración, compose y OPERATIONS.md. El store se niega a servir mientras diga `unverified`. **Falta levantarlo**: no hay servidor, ni Docker, ni WSL, ni PostgreSQL |
| 8A Puerta de publicación | Completo: fences, generación, propiedad, caducidad, SHA, Git |
| 8B DAG y cola de integración | **Completo.** `TaskService` con estados y `claim` atómico, más `IntegrationQueue` con checkout dedicado y avance condicional |
| 9 Despliegues con rollback | **Cerrado.** Las cuatro comprobaciones de aceptación se ejecutan contra un proceso separado y un socket HTTP real. **Sin proveedor configurado**: nada se ha publicado |
| 10 OAuth nativo elegible | **Puerta cerrada.** `ProviderAuth` con PKCE, state de un uso y almacén local, detrás de un registro de revisión **vacío a propósito**. Nadie es elegible |
| 11 Presupuestos y observabilidad | **Parcial.** `Usage.record` con `Decimal`, presupuestos, techo de agentes y correlación sin prompts. La release con checksums está hecha. **Faltan caos, restore y firma** |

## Lo que queda, y qué de ello se puede hacer aquí

| Pendiente | ¿Se puede hacer en esta máquina? |
| --- | --- |
| Paso 1 del plan: `cshcli start` y almacén local de claves | **Sí** |
| Paso 2: documentar el comando de instalación | **Sí** |
| Paso 3: `cshcli update` con checksum | **Sí** |
| Paso 4: `cshcli serve --remote` con HTTPS y PostgreSQL | **No.** Sin servidor |
| 7: levantar el coordinador remoto y probar concurrencia real | **No.** Sin PostgreSQL |
| 11: ensayos de caos y restore probada | **Parcial.** El caos local sí; el restore sobre una base real, no |
| 11: firma de release | **No.** Sin credenciales |

La regla que se viene aplicando: **lo que no se puede comprobar se declara, no
se maquilla.** Cada fila de esta tabla está también en `docs/STATUS.md`, y las
que dependen de infraestructura tienen su motivo escrito.

## Orden de trabajo acordado

Decisiones del propietario, 15 de octubre, en el orden en que se tomaron:

1. El cierre del 9 iba primero, porque era trabajo pequeño y dejaba el
   superplan cerca de terminado. **Hecho**, y encontró un bug real en el manejo
   de timeouts que ningún test contra el objeto en memoria podía ver.
2. Después, la cola del 8B, el 10 y el 11. **Los tres hechos.**
3. Un plan escrito **antes** de tocar código, para online, simplicidad y
   actualización automática. **Escrito** en `docs/PLAN-ONLINE.md`.
4. Versionar después de un cambio grande. **Hecho**: `0.9.0` con checksum y la
   copia instalada verificada, y `0.4.0` tras el menú y el coordinador
   implícito. Publicar y firmar siguen pendientes.

Lo que queda, en orden y con su bloqueo declarado, está en la tabla de arriba.
Lo único que **no** se puede cerrar aquí es el almacenamiento PostgreSQL y el
despliegue HTTPS: no hay Docker, ni WSL, ni PostgreSQL en esta máquina, ni
credenciales para firmar una release.

## Gobernanza: quién puede commitear y fusionar

| Quién | Qué puede hacer |
| --- | --- |
| `jtpydk5gyh-alt` (único colaborador) | Escribir, abrir PR, fusionar, administrar el repositorio |

Los commits no se empujan a `main`: van en una rama y entran por pull request.
Lo que gobierna eso es un único ruleset, `main-integrity`:

| Regla | Efecto |
| --- | --- |
| `pull_request` | Ningún cambio llega a `main` sin PR |
| `required_status_checks` | El PR no fusiona si `Personal data guard` no pasa. `strict`, así que además la rama debe estar al día con `main` |
| `non_fast_forward` | Nadie puede reescribir `main` por la vía normal |
| `deletion` | `main` no se puede borrar |
| `bypass_actors: []` | No hay excepción. Ni el owner se salta el control en el botón de fusionar |

**Sobre "aceptar" el PR: no hay aprobación humana que dar.** El ruleset pide
cero revisores y `require_code_owner_review` está desactivado, así que fusionas
tu propio PR sin que nadie lo apruebe. `CODEOWNERS` te nombra como único
revisor, pero sin esa regla activada es documentación, no una puerta. Hoy no
hay segunda persona mirando el código, y eso es una decisión, no un descuido.

**Lo que sí frena algo aunque tú quieras saltártelo:** el control obligatorio.
Un PR con un secreto detectado no fusiona ni con `--admin` normal. Si aun así
llega algo a `main`, el guard no lo borra: un control fallido en CI no
deshace lo ya publicado. Ahí toca reescribir el historial con
`python scripts/push_rewritten_main.py`, que suspende los rulesets, reescribe
la autoría, empuja con `--force-with-lease` y los restaura.

**Trampa conocida en la atribución.** GitHub atribuye un squash al correo
principal de la cuenta que fusiona, no al autor del commit de la rama. Con un
relay privado como correo principal público, cada squash lo colaba de nuevo.
Está en privado y los dos últimos merges salieron limpios, pero conviene
recordarlo antes de volver a cambiar la configuración de la cuenta.

## Qué haría yo ahora

Con el propietario parado hasta nuevo aviso, lo que queda abierto es de
infraestructura o suyo:

1. **Decidir si el chat puede escribir.** Decidido el 16 de octubre: **no por
   ahora**. Sigue solo leyendo. Si algún día cambia de idea, la vía es
   `accept_patch` más la cola y compare-and-swap, no una escritura directa:
   el que escribe pasaría a ser un modelo, y un modelo no es una persona
   revisando un diff.
2. **El sandbox de 6C.** Sigue siendo lo único que impide decir que CSHCLI
   coordina de verdad. Un contenedor Linux no es un lujo: es lo mínimo para
   impedir que un proceso lea la máquina anfitriona o escriba fuera del
   worktree.
3. **`max_runtime_seconds` por defecto de 900 s** ya está; falta aplicar el
   límite a un proceso real, que es donde se ve si funciona.
4. **Un test de flakiness conocido**: `test_capture_timeout_stops_descendants_while_parent_is_running`
   falla si la máquina está cargada. Pasa aislado. Merece un margen mayor o
   una etiqueta de `slow`.

Lo que **no** está pendiente: el trabajo de producto que no depende de
infraestructura ni de una decisión del propietario está cerrado.

## 6C: qué es un runner y qué no es

El `Runner` expone una superficie deliberadamente pequeña: `read_file`,
`write_file`, `remove`, `rename`. **No existe ningún método que ejecute un
comando, abra un socket o alcance fuera de su worktree.** Esa ausencia es la
garantía, y hay un test que falla si alguien añade uno con nombre plausible.

Tres reglas, comprobadas:

1. **La autorización es un instante, no un permiso.** `write_file` valida el
   lease contra el coordinador *inmediatamente antes* de mover los bytes. Un
   lease validado caduca un segundo después, y por eso la puerta de
   publicación vuelve a comprobar fences, generación y caducidad. El test
   `test_publish_after_a_new_generation_is_refused` valida, revoca la
   generación y exige que la publicación falle igual.
2. **El workspace resuelve la ruta.** Un runner no puede señalarse al host, a
   un checkout vecino ni a través de un symlink, porque nunca entrega una
   ruta a ningún sitio que el workspace no haya resuelto y rechazado antes.
   `Store.validate_lease` añade la comprobación de cobertura: una escritura a
   `file:docs` con un lease sobre `file:src` se rechaza antes de tocar disco.
3. **Un runner parado no escribe.** Perder el heartbeat no es un aviso, termina
   la ejecución.

**Lo que este runner NO es, y hay que decirlo claro.** No es un contenedor. No
limita CPU, memoria ni número de procesos, y no desactiva la red. El plan
sitúa la ejecución arbitraria en un contenedor o VM **Linux** con controles
verificados, y dice que un runner nativo de Windows o macOS no se anunciará
como equivalente hasta verificar sus controles. Hasta que ese contenedor
exista, el runner admite lectura, chat y utilidades de worktree, con esos
límites. Prometer más de lo que los tests demuestran sería exactamente el
defecto que el plan quiere evitar.

`heartbeat_seconds` por defecto 30 s, `lease_ttl` 120 s, ambos validados como
enteros en 1..3600. `True` se rechaza: en Python `True` es un `int`.

## 7: sesiones revocables, y lo que sigue sin poder hacerse

El piloto local emite un token permanente por usuario al registrarse. Con un
coordinador en loopback al que nadie más llega, eso aguanta. En cuanto el
coordinador responde por una red, no: no hay forma de terminar una sesión
sin terminar todas, ni de distinguir a un agente revocado de uno que sencillamente
no volvió.

`Identity` corrige eso. Una sesión es un valor con hash, caducidad y fila que
se puede borrar. El token se compara por HMAC-SHA256 y **nunca se guarda**.
`revoke_agent` incrementa `authorization_generation`, de modo que el trabajo
encolado *antes* de la revocación conserva una autorización que ya no
coincide cuando por fin intenta actuar: conserva el artefacto y no produce
efectos nuevos, que es justo lo que pide el plan para un merge en cola o un
despliegue esperando aprobación.

**Lo que el hito 7 NO puede cerrarse aquí, y no se va a maquillar.** El plan
es explícito: contra un PostgreSQL real, lanzar once procesos independientes
sobre `file:src` y `file:src/a.py` y exigir un único ganador, *sin sustituir
esa prueba por un mock*. También pide HTTPS con la base en red privada, límites
de peticiones, copias automáticas y **una restauración probada sobre una base
vacía** antes de invitar a nadie. No hay PostgreSQL en esta máquina, y la
regla del proyecto es no añadir dependencias de runtime durante el piloto: un
driver de PostgreSQL sería la primera. Se deja escrito como pendiente en vez
de entregar una versión que solo funciona con SQLite y diga que cumple.

### La solución al 7: que el código no pueda sobreprometer

El bloqueo era doble, y los dos tienen arreglo:

**El driver va como extra, no como dependencia.** El propio plan lo dice:
*"Remote service dependencies are declared as extras; the local client keeps
the dependency-free core"*. `[project.optional-dependencies] remote` en
`pyproject.toml` cumple eso. Instalar `cshcli` a secas no arrastra un driver
que el coordinador local no usa, así que tu regla se respeta en vez de
saltarse.

**El propio store se niega a servir tráfico sin pruebas.** Aquí está la idea
que de verdad cierra el hito en pie:
`RemoteStore.verification()` devuelve `unverified` con un motivo, y
`assert_production_ready()` lanza `remote_unverified`. Un test comprueba que
`verification()` **nunca** puede devolver `verified` por su cuenta. Así, la
condición de aceptación del plan —"la versión distribuida no prometa garantías
que no pasan los tests"— está en el código y no solo en un documento que
nadie lee.

**El test de concurrencia existe y se omite diciendo por qué.** Once procesos
independientes compitiendo por `file:src` y `file:src/a.py` contra un
PostgreSQL real, exigiendo un único ganador. El plan prohíbe sustituirlo por un
mock, porque un mock no prueba nada sobre `SELECT ... FOR UPDATE`. Borrarlo
sería justamente lo que el plan prohíbe; se deja, con su motivo en el mensaje
de salto. En esta máquina no hay Docker, Podman, WSL ni PostgreSQL: está
comprobado, no supuesto.

La migración lleva los dos detalles que no son portables y que no conviene
"simplificar": el fence sale de una **secuencia**, nunca de un contador por
fila que un restore podría rebobinar, y la adquisición **bloquea la fila del
proyecto** antes de leer o insertar, porque dos recursos que solapan por
prefijo pueden vivir en filas distintas.

## 8B: el DAG, y por qué `claim` no se puede partir en dos

Cinco agentes ven la misma pila y se la disputan. El fallo que este módulo
existe para evitar es una tarea marcada `running` cuyas leases nunca se
adquirieron, o leases tomadas por una tarea que nunca arrancó porque una
dependencia falló. Los dos son peores que una negativa, porque los dos parecen
progreso.

Por eso `claim` hace la comprobación de dependencias, la de estado y la
adquisición de leases **dentro de una sola transacción de escritura**. No hay
ventana en la que una tarea esté corriendo sin tener lo que necesita, ni
ventana en la que alguien tenga leases sin estar corriendo. Si una lease falla
a mitad del lote, las ya tomadas se expiran en la misma transacción.

Estados: `queued`, `running`, `blocked`, `review`, `merged`, `failed`,
`cancelled`. Una tarea con dependencias nace `blocked` y solo pasa a `queued`
cuando **todas** sus dependencias llegan a `merged`. Que estén en `review` no
basta: una dependencia en revisión todavía puede fallar, así que desbloquear
antes de tiempo sería un deadlock esperando a ocurrir. Una dependencia
cancelada deja a sus dependientes bloqueados para siempre, que es la respuesta
honesta: no hay trabajo que hacer, y fingir lo contrario sería peor.

Un ciclo se rechaza al crear y se vuelve a rechazar al modificar. Comprobarlo
solo al crear dejaría pasar por la puerta de atrás un ciclo colado en una
edición posterior. `Store.acquire_leases` se refactorizó para que su lógica
viva en un `_acquire(connection, ...)` reutilizable; sin eso no había forma de
adquirir leases dentro de la transacción de `claim`.

## 8B: la cola, y por qué la rama solo se mueve si sigue donde estaba

`accept_patch` del 8A registra que un artefacto merece considerarse. **No es
un merge**, y a propósito no reserva un fichero durante las horas que tarda una
revisión humana. Alguien tiene que integrar, y esta es esa parte.

Cuatro reglas, y la razón de cada una:

**Una integración por proyecto a la vez.** Dos parches compuestos a la vez son
la forma exacta de que cada agente vea como ausente el cambio del otro.

**El base se recalcula, no se confía.** Un segundo parche enviado contra el
mismo SHA base que el primero se aplica encima de lo que la rama sirva ahora,
y los checks corren **sobre el resultado compuesto**. Hay un test que lo
comprueba: dos parches con el mismo padre, uno toca `app.py` y otro su test,
los dos terminan fusionados y `observed_base` del segundo es el `merge_sha` del
primero.

**La rama solo se mueve si sigue donde estaba.** La actualización es un
*compare-and-swap* contra el SHA observado **antes** de correr los checks. Las
pruebas largas ocurren antes de esa operación corta; cualquier cosa que moviera
la rama mientras tanto obliga a recalcular. El test simula exactamente eso:
durante el check, alguien apunta la rama a otro commit, y el resultado queda
en `review` con la rama ajena intacta.

**El integrador toma sus propias leases** y nunca reutiliza una fence que el
runner liberó, porque esa fence ya podría habérsele dado a otro.

**El checkout es dedicado.** `_Checkout` crea un worktree propio y lo borra al
terminar. El árbol de trabajo del usuario no se toca nunca, y hay un test que
comprueba que la lista de ficheros y el contenido no cambian tras integrar.
`reset --hard` corre contra el checkout del integrador, nunca contra el tuyo.

Un conflicto o un check que falla dejan la entrada en `review` o `failed`. No
existe ningún camino por el que esto fusione en silencio. Y una revocación
tras la aceptación **suspende** la cola en vez de integrar bajo el permiso
antiguo: `process_next` lanza `integration_suspended` y espera a una persona.

## Versionado: por qué 0.2.0, 0.3.0, 0.4.0 y 0.5.0

Decisión del propietario: **después de un cambio grande se versiona**. Cuatro
veces, con dos razones distintas:

- **`0.1.0` → `0.2.0`**: runner, DAG, cola, despliegues, presupuestos e
  identidad. Un cambio de parche habría untrue: no es una corrección, es una
  capacidad que antes no existía. Y no es `1.0.0` porque el piloto sigue siendo
  local.
- **`0.2.0` → `0.3.0`**: `cshcli start`, el almacén local de claves,
  `cshcli update` con checksum, los ensayos de caos y el ensayo de
  restauración. Otra vez capacidades nuevas, y otra vez el mismo motivo para
  no ser un parche.
- **`0.3.0` → `0.4.0`**: el menú de `start` que ejecuta, el coordinador
  implícito, la sesión local, las rutas HTTP de la cola y el cierre del
  compare-and-swap. Sigue siendo romper una capacidad anterior —`start` ya no
  es un impresor— y añadir una nueva, así que tampoco es un parche.
- **`0.4.0` → `0.5.0`**: el bucle conversacional y el proveedor y modelo en la
  sesión. Un `cshcli` a secas pasó a ser un chat, y `cshcli chat` dejó de
  exigir `--provider`. Romper ese contrato es cambio de comportamiento de un
  comando existente, no una corrección: por eso menor y no parche.

`scripts/release.py` construye, genera `SHA256SUMS` y **verifica la copia
instalada**, no el árbol de trabajo: probar el árbol no probaría el artefacto.
Se niega a construir si las dos versiones declaradas no coinciden o si el árbol
está sucio, y **no firma ni publica**, porque eso necesita una máquina y
credenciales que aquí no existen. Lo dice en cada ejecución.

Lo que un checksum demuestra y lo que no: que el fichero es el que este
repositorio produjo. **No dice quién lo publicó**, que es justo por lo que
firmar figura como pendiente y no como hecho.

El procedimiento completo está en `docs/RELEASES.md`.

## La web no se publica, por decisión del owner

Existe un directorio `web/` en el árbol de trabajo con `dist/` y `.openai/`. **No
se sube a ningún sitio y no se despliega.** Decisión del propietario, registrada
el 15 de octubre de 2026.

Está en `.gitignore` con ese motivo escrito al lado, y **no** en la sección de
cachés o de secretos, porque no es un artefacto de construcción: es algo que se
decidió no publicar. Esa diferencia importa dentro de un mes, cuando alguien se
pregunte por qué esa carpeta está ahí y no la encuentre en ningún sitio.

Esto no es lo mismo que el despliegue del hito 9, que sigue sin destino
configurado. Aquí la regla es más simple y más dura: **la web no sale**. Si
algún día cambia, es una decisión nueva y explícita, no una consecuencia de que
la carpeta ya estuviera.

## 10: una puerta cerrada, que es el resultado

**Ningún proveedor es elegible para login nativo**, y ese es el hallazgo, no un
hueco que alguien rellene después. `capabilities` devuelve `native_login: false`
y `reason: "not_reviewed"` para todos, y `begin` se niega.

El plan lo pide así: hay que revisar la documentación publicada del proveedor
**antes** de habilitar nada, registrando el cliente registrado, los scopes, la
modalidad y las restricciones. Y dice literalmente que *un repositorio privado
por sí solo no cumple los requisitos*. Estar publicado bajo MIT no es una
autorización.

**Lo que sí está construido detrás de la puerta.** La maquinaria existe y está
probada, porque una puerta que nadie ha ejecutado nunca es una puerta, es un
comentario: state aleatorio de un uso, PKCE con S256, redirect exacto de
loopback y sin fragmentos, caducidad de diez minutos, almacén local `0600`, y
el intercambio ocurre en la máquina del usuario con un transporte inyectable
que un test comprueba que se llama una vez y no reporta nada al coordinador.

**Por qué la puerta vacía es más útil que una implementación sin revisar.**
Activar el login nativo para un proveedor exige un registro en `REVIEWED` con
la fecha de revisión, y hay un test que afirma que el registro **está vacío**.
Ese test es lo único que impide que un proveedor se habilite por una
edición descuidada, y falla a propósito cuando alguien añade una revisión de
verdad.

Anthropic se queda en clave de API o su binario oficial mientras no exista una
modalidad documentada. CSHCLI no lee ni exporta tokens de Claude.ai, y no
implementa proxy de OAuth. Los cuatro ficheros que documentan esto están en
`docs/PROVIDERS.md`.

## Paso 1 hecho: `cshcli start` y dónde vive la clave

**El problema real no era la falta de documentación.** Para llegar a algo
útil hacen falta cuatro comandos y `CSHCLI_TOKEN` en el entorno. Eso no es
documentación mal escrita: es una forma mala.

`cshcli start` comprueba qué falta y lo dice, en orden, con el comando exacto
para cada paso: primero el coordinador, luego la identidad, luego el proyecto,
luego la clave. Cuando no queda nada, dice que está listo. No pide de una vez
las cuatro cosas, porque alguien que acaba de instalar no sabe todavía qué
proveedor va a usar, y preguntárselo todo de golpe es la forma de que se vaya.

**La clave dejó de vivir en el entorno.** `$env:OPENAI_API_KEY` es la
respuesta obvia y la equivocada: queda en el historial de la terminal y la
hereda **cada proceso hijo que lanza un agente**. `Keyring` la guarda en
`.cshcli/keys.json`, legible solo por el usuario en POSIX.

La variable de entorno **sigue teniendo prioridad**, y esa es la decisión
deliberada: quien la exportó a propósito no debe ver su clave sustituida en
silencio por una vieja que quedó en disco.

Nada imprime una clave, en ningún sitio. `key show` dice si existe, de dónde
viene y cuánto ocupa; nunca el valor. Hay tests para eso, y uno comprueba que
el valor de un proveedor no aparece al preguntar por otro.

**Un fallo grave que encontró un test:** abrir el keyring **borraba las
claves**, porque el constructor escribía un diccionario vacío sin mirar si el
fichero existía. Un `Keyring` nuevo por cada llamada, y todas las claves al
aire. Es exactamente el fallo que produce una tool que "parece funcionar" en
la primera ejecución y pierde lo hecho en la segunda.

Los comandos que ya existían **no se quitan**. `start` y `key` se suman.

## Paso 3 hecho: `cshcli update` avisa antes de tocar nada

Pediste autoactualización. Instalar código sin avisar es mala idea aunque el
código sea el nuestro, y aquí la razón es concreta y no una moralina:
**instalar desde `main` es instalar código que no está versionado ni
revisado**. Una herramienta que descargara eso en silencio sería peor que no
tener actualizador.

Son dos comandos con un solo nombre:

- **`cshcli update` compara y reporta. No cambia nada en disco.**
- **`cshcli update --apply`** pide que escribas la versión y **verifica el
  checksum de lo descargado antes de tocar lo ya instalado**.

**Por qué el checksum es el punto entero.** La vía de instalación que pediste
es un zip servido desde GitHub. Cualquiera que controle esa ruta puede poner
en ella lo que quiera. Por eso `scripts/release.py` genera `SHA256SUMS`, y por
eso un artefacto que falla la verificación **se borra en vez de dejarse ahí**:
un fichero que parece un paquete es peor que no tener fichero.

**Cuando no hay release publicada, la respuesta es `unknown`, no "al día".**
Decir que estás actualizado cuando no se ha podido comprobar es exactamente el
tipo de mentira que este repositorio lleva evitando en el resto de su
documentación. El informe incluye además que la instalación viene de `main`,
que no está versionada, para que quien lo lea lo sepa antes de decidir.

**No descarga de ninguna rama que no sea `main`**, y no puede convertir un
artefacto sin verificar en algo instalado.

El paso 4, `cshcli serve --remote`, sigue bloqueado sin servidor.

## 11: ensayos de caos locales, y lo que sigue sin poder probarse

El plan pide parar el coordinador, perder la red y matar un runner a mitad de
un despliegue, y recuperar con fences, idempotencia y estado persistido.
Parte necesita una máquina y un proveedor reales, y eso queda declarado como
no verificado. **Lo que sí se puede romper aquí, se rompe de verdad**, contra
un fichero SQLite real y un servidor HTTP real:

- se para el coordinador con una tarea en `running`, y al volver la tarea sigue
  `running`. **No se da por terminada en silencio**, que es lo que haría un
  sistema que pierde la noción de lo que estaba en curso.
- la lease de un agente muerto caduca y un segundo agente entra; el titular
  viejo no puede renovar ni soltar la lease del nuevo.
- un proceso separado lee lo que otro escribió. Frontera real, no simulada.
- un lote abortado no deja nada a medias.
- un despliegue interrumpido y reejecutado no repite el efecto.

**Lo que no se puede probar aquí, y se dice en vez de insinuar:** la
restauración sobre una base real, y el ensayo con un proveedor de verdad. No
hay base que restaurar ni credenciales, y un test que usara un doble en lugar
de una base real estaría probando el doble.

Un detalle que costó tiempo y conviene no repetir: el primer intento de
"transacción sin terminar" **no significaba nada en Windows**, porque el
bloqueo de fichero impide reproducirlo de forma fiable. Se sustituyó por el
ensayo de proceso separado, que sí demuestra algo. Un test que parece cubrir
algo y no cubre nada es peor que no tenerlo.

**El test de captura del proveedor llevaba toda la sesión fallando bajo carga.**
Exigía que el timeout de 200 ms volviera en menos de 800 ms, sin margen para el
arranque de dos intérpretes de Python en una máquina ocupada. El padre del
proceso duerme 5 s, así que un umbral de 2,5 s sigue probando lo que importa —que
no esperó al padre— sin depender de lo rápido que arranque Python. El resto de
la batería pasó siempre en verde, así que era margen, no lógica.

## El plan online, y dónde está

Decidido por el propietario el 15 de octubre. El plan completo, con sus
razones, está en `docs/PLAN-ONLINE.md`. **Los pasos 1, 2 y 3 están hechos**;
el 4 sigue sin implementar, y esa distinción importa más que la lista.

Cuatro decisiones, en orden de ejecución:

1. **`cshcli start` y el almacén local de claves.** Hoy hacen falta cuatro
   pasos y una variable de entorno antes de hacer nada útil. La simplicidad no
   es quitar comandos: es que el camino por defecto no requiera saberlos. La
   clave entra pegada y se guarda con permisos restringidos, porque hoy
   `$env:OPENAI_API_KEY` queda en el historial de la terminal y en el entorno
   de cada proceso hijo.
2. **El comando de instalación documentado**, con sus tres advertencias:
   instala `main` y no una versión, así que no hay reproducibilidad; no
   comprueba checksums ni firmas; y el comando `cshcli` puede no quedar en el
   PATH, mientras que `py -m cshcli` siempre funciona.
3. **`cshcli update`**, que primero **compara y avisa sin tocar nada**, y solo
   con `--apply` instala, pidendo que escribas el nombre de la versión y
   comprobando el checksum antes. Instalar código por sorpresa es mala idea
   aunque el código sea el nuestro: instalar desde `main` es instalar código
   sin versionar ni reviews.
4. **`cshcli serve --remote`**, con HTTPS y PostgreSQL. **Va el último porque
   es el único que puede quedarse esperando infraestructura**, y aquí no hay
   servidor, ni Docker, ni WSL, ni PostgreSQL.

Ese cuarto punto comparte el bloqueo del hito 7, así que su veredicto es el
mismo: se escribe y se revisa, pero **"funciona online" no se declara hasta que
alguien lo haya levantado y dos personas hayan conectado desde máquinas
distintas.** Esa frase tiene que poder leerse en el README el día que sea
cierto, y no antes.

## 11: un coste desconocido no es un coste cero

La regla del plan para este hito es corta y sostiene el resto: usar `decimal`,
registrar moneda, fecha y unidad, y **los desconocidos se quedan en null y
nunca se convierten en cero**.

**El bug que estos tests encontraron en mi propio código.** Filtrar por moneda
en SQL hace que una llamada **sin precio desaparezca del total**, porque no
tiene moneda que casar. El presupuesto parecía más barato de lo que es, que
es justo el fallo contra el que advierte el plan. Ahora los registros sin
moneda se cuentan como desconocidos; los de **otra** moneda sí se excluyen,
porque esos son genuinamente ajenos. Hay dos tests para no volver a
confundir uno con otro.

**Nada se estima.** `authorize_run` acepta una estimación del llamante y la
compara; no la produce. Una estimación inventada por este código sería una
estimación que la política después trataría como si alguien la hubiera
revisado. Sin presupuesto, una ejecución se autoriza: el owner puede no haber
puesto ninguno. Con presupuesto y **sin** estimación, se rechaza con
`estimate_required`, porque un presupuesto que no puede ver el coste de lo que
autoriza es decoración. Y si hay llamadas sin precio conocido, se rechaza con
`usage_incomplete` en vez de sumar la parte conocida como si fuera el total.

`max_agents` se aplica contra las reservas de ejecución activas, que es lo que
significa un techo de agentes: once contra un límite de diez, la undécima se
rechaza con `agent_limit_reached`.

**Correlación sin prompts.** `record` guarda request id, proyecto, tarea,
agente, lease y fence. Un test comprueba que en el evento no aparece `prompt`,
ni `sk-`, ni `Bearer`, ni nombres de variables de proveedor. La exportación de
auditoría dice que **la retención no está configurada**, en vez de fingir un
plazo.

## 9: despliegues, y los dos estados que un binario no sabe expresar

El 9 decide **si** un cambio puede ocurrir, registra **qué** ocurrió, y sabe
**cómo recuperarse** cuando el destino es ambiguo. Tres cosas que merecen
quedar escritas:

**La idempotencia está en la base, no en Python.** `UNIQUE (project_id,
environment, idempotency_key)`. El código compara huellas y devuelve el mismo
despliegue, pero la constraint es la que garantiza que dos peticiones
simultáneas no creen dos. Una comprobación en Python habría sido una carrera.

**Se verifica dos veces, y la segunda es la que importa.** Permiso,
generación de autorización, SHA de comprobaciones, digest y aprobación se
comprueban antes de pasar a `running` **y otra vez inmediatamente antes del
efecto externo**. Una revocación que llegue entre las dos detiene el cambio. Con
una sola comprobación, el instante entre "comprobé" y "cambié" sería una puerta
abierta.

**`reconciling` y `unknown` son estados, no fallos.** Un timeout ambiguo no se
reintenta a ciegas: el worker pregunta al destino qué sirve antes de decidir. Y
si el destino tampoco puede contestar, el entorno queda en `unknown` y **deja de
aceptar promociones** hasta que una persona lo resuelva. Presentar cualquiera
de los dos como un fallo plano permitiría que un reintento ciego sobrescribiera
un despliegue que sí salió. Esa es exactamente la razón de existir del hito.

El rollback va condicionado a tres valores que el llamador leyó antes de
decidir: `expected_active_deployment_id`, `expected_digest` y
`environment_generation`. Cualquier desajuste se rechaza y el estado se queda
igual. Eso es lo que impide que un rollback tardío de A deshaga a B: cuando
llega, B ya está activo, y rechazarse es la respuesta correcta, no un error que
sortear.

**Lo que el 9 NO es.** No hay destino de despliegue: ni staging, ni registro,
ni cuenta de proveedor, ni credencial. El workflow reserva el entorno y se
detiene ahí. La única implementación es `InProcessDestination`, un objeto en
proceso para los tests, y no debe describirse como un objetivo. `deploy
reserve` sigue siendo solo una reserva. Las cuatro comprobaciones que pide la
aceptación del plan —despliegue en staging, fallo de salud inducido, rollback y
reenvío idempotente— quedan sin ejecutar, y `docs/DEPLOYMENTS.md` lo dice en su
primera línea, no al final.

Un detalle sobre el workflow: `cancel-in-progress: false` **no es una garantía
FIFO**. GitHub no promete orden de ejecución dentro de un grupo de
concurrencia y puede reordenar. La cola que decide qué llega a un entorno es la
persistente de CSHCLI en la base, no la de GitHub.

### Cerrado: las cuatro comprobaciones, y el bug que encontró

Las cuatro comprobaciones de aceptación se ejecutan en
`tests/test_deploy_process.py` contra `ProcessDestination`: un destino cuyo
estado escribe **un proceso intérprete aparte** en un directorio, y cuya salud
es una **petición HTTP real** a un servidor en localhost.

| Comprobación | Cómo se induce |
| --- | --- |
| Despliegue en staging | El worker cambia un entorno servido por un proceso que lo sobrevive |
| Fallo de salud | Se **para** el servidor, así que el fallo es una conexión rechazada |
| Rollback | Se lee la fila del entorno y el rollback se condiciona a ella |
| Reenvío idempotente | Se reenvía la misma clave con la misma carga |

Una quinta usa un socket que **acepta la conexión y nunca responde**, que es un
timeout y no un rechazo. Esa encontró un bug real.

**El bug que solo un destino real podía encontrar.** `_start` protecía
`promote` contra `DestinationTimeout`, pero llamaba a `destination.health(...)`
sin protección. Un timeout durante la comprobación de salud se escapaba como
excepción sin manejar en vez de llevar el despliegue a `reconciling`, que es
justo lo que este hito existe para evitar: el entorno puede haber servido el
artefacto y perder la respuesta al volver, y tratarlo como un fallo plano
permite que el siguiente intento sobrescriba un despliegue que sí salió. El
mismo hueco estaba en `_reconcile`.

`InProcessDestination` nunca podía encontrarlo: su `health` devuelve un
diccionario y no lanza nunca. Hacía falta un destino con un socket de verdad
dentro.

**Lo que sigue necesitando una cuenta.** `ProcessDestination` escribe un
directorio y responde en localhost. No es un proveedor de nube y no debe
describirse como tal. Queda sin verificar lo que necesita credenciales: un
proveedor real, secretos por entorno y un entorno compartido por más de una
máquina.

## 11: la restauración, probada de verdad sobre lo que existe

La restauración sobre PostgreSQL no se puede hacer aquí. **La del piloto
SQLite sí**, y se ha ejecutado. Eso convierte el ensayo de PostgreSQL de un
hueco en un guion.

`scripts/restore_drill.py` hace copia, restaura sobre una base **vacía**,
comprueba, y luego lo intenta otra vez para demostrar que un segundo restore
sobre el mismo destino se **rechaza**. Si se permitiera, ese sería el camino
hacia dos autoridades.

La propiedad que más importa se comprueba aparte: **el fence nunca retrocede**.
Una copia que conservara los recuentos de filas pero rebobinara el contador de
fences parecería perfecta y sería peligrosa, porque un agente anterior a la
copia volvería a validar. Hay tests para las dos cosas: una restauración
manipulada que no cuadra se detecta, y un fence rebobinado también.

Las mismas tres comprobaciones —reproducir el estado, conservar el fence,
rechazar un destino poblado— son el guion del ensayo de PostgreSQL. Haberlas
ejecutado una vez aquí significa que la versión de PostgreSQL es un ensayo y no
una suposición.

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
`PATCH` y `POST` devuelven 404. La noreply
`jtpydk5gyh-alt@users.noreply.github.com` tampoco se puede añadir por API,
porque GitHub ya la usa de forma implícita.

**Lo que sí funcionó: poner el relay en privado.** No hace falta cambiar el
correo principal. Con `visibility: private`, GitHub deja de usarlo para
atribuir merges y recurre a la noreply. Comprobado con el PR `#39`:
mergeado por squash **sin** `--admin`, el commit salió con
`291778318+jtpydk5gyh-alt@users.noreply.github.com` y la dirección privada
no volvió a `main`. El PR `#38`, fusionado con el relay todavía público, sí
la había colado.

**Un segundo bloqueo, independiente del anterior.** `main` tenía dos
rulesets que exigían lo mismo, cambios mediante pull request. El segundo,
`main-owner-merge`, con una regla `update` y un bypass de tipo
`RepositoryRole`, rechazaba todos los merges con *"base branch policy
prohibits the merge"*. Los dos se crearon trece segundos después del último
merge, así que el repositorio llevaba rato sin poder fusionar nada por vía
normal. `main-integrity` ya exige pull request, `required_status_checks` con
`Personal data guard`, no.fast-forward y no borrado: `main-owner-merge` era
redundante y solo estorbaba. Se ha eliminado, y el helper ya no lo recrea.

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

## El chat ve el proyecto

La conversación venía de contexto vacío: el chatignoraba la memoria
versionada que el proyecto ya tenía guardada. Ahora la **primera** pregunta
lleva un bloque con las entradas de memoria del proyecto, acotado a 8000
caracteres.

El bloque viaja **dentro de la primera pregunta de usuario**, no como un
mensaje de sistema aparte. Cada proveedor lo escribe de forma distinta —
`instructions`, `system`, `systemInstruction`, `system`— y ninguna de esas
formas se ha comprobado contra una API real. Meter cuatro formas no
verificadas para ahorrar un delimitador habría sido añadir superficie no
verificada a cambio de nada.

Una prueba encontró un bug real durante esto: una entrada con **clave vacía**
pasaba el filtro y producía una línea `- : contenido` malformada. El filtro
comprobaba el contenido pero no la clave.

## El helper de versión, probado y subido

`scripts/bump_version.py` llevaba tiempo sin trackear porque reescribe
archivos de todo el repositorio y no tenía pruebas. Escribirlas lo convirtió en
algo que sí se puede subir.

La prueba que importa no es la del sandbox: es
`test_every_target_still_matches_exactly_once`, que afirma que **cada patrón
sigue dependiendo exactamente una vez en los archivos reales**. Si alguien
reescribe la frase de versión en `README` o `STATUS`, el test falla en la suite
en vez de que el script se niegue a las tres de la mañana. Esa negativa era ya
la propiedad del script; ahora hay algo que la vigila.

Con eso, la regla del propietario —versionar después de un cambio grande— tiene
herramienta, prueba y procedimiento escrito en `docs/RELEASES.md`.

## El bucle recuerda la conversación

El bucle de 0.5.0 mandaba cada línea como una consulta suelta. Ahora acumula los
turnos y los envía con cada nueva línea, con un tope de **20** para que no
crezca sin límite. `/limpiar` vacía la conversación.

`providers.chat` y `_api_chat` aceptan un `history` opcional y arman el cuerpo
según el proveedor: `messages` para Anthropic y MiniMax, `contents` con
`role: model` para Google, y bloques `input` tipados para OpenAI. Una entrada
de historial inservible se descarta en vez de enviarse.

Dos decisiones que las pruebas obligaron a pensar:

- **Un turno fallido no se recuerda.** Si la llamada falla, el par pregunta y
  respuesta no entra al historial, para que la siguiente petición no lleve un
  turno a medias.
- **Sin historial, OpenAI conserva su forma anterior**, `input` como cadena.
  La suite tenía una prueba que lo fijaba y tenía razón: cambiar la forma de
  una petición que ya funcionaba, sin ganar nada, solo agrega riesgo. Ahora la
  lista de bloques tipados se usa únicamente cuando hay conversación.

**No se ha contactado ningún proveedor.** Los cuerpos de petición están cubiertos
por pruebas que capturan lo que se enviaría, no por una llamada real. Eso está
dicho en `README`, `USAGE`, `STATUS` y `CHANGELOG`, no escondido.

## El bucle conversacional

`cshcli` a secas ahora abre un chat. Con la sesión lista imprime un cartel
—nombre, proyecto, proveedor— y lee líneas hasta `/salir`, `/quit` o Ctrl-D.
Sin sesión lista sigue abriendo el menú de primera ejecución. Un error del
proveedor se imprime y el bucle sigue; no termina la sesión.

El obstáculo real no era el bucle: era que para proveedores con clave API,
`--model` es **obligatorio**. Un chat que solodultera el proveedor no tenía con
qué llamar. Por eso el asistente guarda también el proveedor y el modelo en
`.cshcli/session.json`, y `--provider`/`--model` existen ahora en la raíz, no
solo en el subcomando.

Si ya hay una clave guardada, el asistente **elige** ese proveedor en vez de
preguntar cuál. Es la diferencia entre "¿qué proveedor usas?" y nada.

El límite que quedaba: cada línea era una consulta independiente. Cerrado en
0.5.1, con el historial que se describe arriba.

`run_loop` recibe la función de consulta como parámetro, así que el bucle se
prueba entero sin contactar a ningún proveedor.

## La cola exige aceptación previa

El hueco que había quedado abierto después de 0.4.0 está cerrado. La cola de
integración aceptaba **cualquier commit del repositorio**: la puerta
`IntegrationGate` validaba generación de autorización, fences y recursos, pero
nadie exigía haber pasado por ella.

Ahora `IntegrationQueue` consulta `accepted_patches` en dos momentos:

- al **encolar**: sin registro para `(proyecto, commit)` devuelve
  `409 patch_not_accepted`, y con una base distinta de la aceptada,
  `409 patch_base_mismatch`;
- justo antes de **integrar**: si el registro desapareció mientras la entrada
  esperaba, se rechaza y la rama no se mueve.

La consecuencia es que la puerta es la autoridad de publicación y la cola solo
transporta. Eso obliga a que los tests de la cola pasen por
`accept_patch` con sus leases, lo cual es lo que hace que la puerta sea real y
no decorativa: los tests HTTP devuelven 409 sin registro.

No es una regresión de 0.4.0 —la cola local nunca lo hizo—, es un hueco que
existía desde el diseño original y que la exposición HTTP volvió alcanzable.

## Menú de inicio y coordinador implícito

`cshcli start` era un impresor: decía qué comando tocar a continuación y quien
lo usaba tenía que abrir una segunda terminal, ejecutar `serve`, y volver a
correr `start` cuatro veces. El recorrido de una persona nueva eran ocho pasos.

Ahora es un menú de dos opciones y hace el trabajo:

- **1) Sesión** — identidad, proyecto y clave, todo en local.
- **2) Unirme o crear** — con código de invitación entra al proyecto de otra
  persona; sin él crea uno y muestra un código para compartir.

La decisión estructural es que **el coordinador dejó de ser algo que el usuario
arranca**. Si `CSHCLI_URL` no está y nada escucha en 8765, cada comando levanta
su propio coordinador dentro del proceso, en un puerto efímero, y lo cierra al
salir. `.cshcli/session.json` guarda nombre, proyecto y token, así que los
comandos siguientes funcionan sin `--url` y sin `CSHCLI_TOKEN`.

Esto es posible porque el coordinador no tiene estado en memoria que importe:
todo vive en SQLite.

El costo de concurrencia es real y está declarado: antes, con un solo proceso
`serve`, "una integración por proyecto a la vez" se apoyaba en que había un
único coordinador. Ahora hay uno por comando. La corrección la sostiene el
archivo —transacciones, fences y leases viven en la base y SQLite tiene
`busy_timeout` de 30 s—, pero la garantía pasó de ser arquitectónica a depender
del bloqueo de la base. Hay una prueba de dos coordinadores embebidos
compartiendo una misma base, y no se declara más de lo que eso prueba.

El bug más útil de esta tanda salió de las pruebas, no de la revisión: tras
registrarse, el wizard dejaba el cliente sin token y todo lo siguiente devolvía
401. También se corrigió que `run_wizard` tomara `input` como valor por defecto,
lo que lo fijaba en la importación e impedía probarlo, y que el token se
validara **después** de levantar un coordinador: ahora se rechaza antes, sin
arrancar nada.

Los tests de `start` que fijaban el comportamiento anterior fueron reemplazados
por los de `tests/test_wizard.py`, que cubren las dos ramas del menú, la clave
vacía, la opción inválida, la sesión ya lista, la terminal no interactiva y dos
coordinadores embebidos sobre la misma base.

## Cola HTTP local y regla de estilo restaurada

La cola de integración ya está cableada al servidor HTTP local. Las rutas
permiten enviar, listar, leer y procesar entradas bajo el proyecto autenticado.
Las lecturas no exigen una ruta Git; enviar o procesar sí exige una ruta en el
cuerpo o `CSHCLI_REPOSITORY`.

El procesado **falla cerrado**. `CSHCLI_INTEGRATION_CHECK` debe contener un
array JSON de comando, por ejemplo
`["python","-m","unittest","discover","-s","tests"]`. El comando se ejecuta
sin shell dentro del worktree dedicado, con un timeout de 240 segundos. Si no
está configurado, una cola no vacía devuelve `409 checks_not_configured` y la
rama no se mueve. Conflictos,
checks fallidos y un branch que cambia durante los checks siguen sin fusionarse
en silencio.

El error HTTP original tenía dos causas: la ruta contaba cinco segmentos donde
`/v1/projects/{id}/queue` tiene cuatro, y el servidor llamaba a
`IntegrationQueue.submit` y `process_next` con una firma que no existía. El
contrato vuelve a ser uno: repositorio y branch configuran la instancia; las
operaciones reciben solo los identificadores de dominio.

La exposición HTTP también obligó a cerrar dos fugas de ámbito. Leer una
entrada por id ahora exige que pertenezca al proyecto de la URL; un miembro de
otro proyecto recibe `404 queue_not_found`. Y solo el `owner` puede nombrar
`repository` o `branch` en una petición: un `writer` que lo intente recibe
`403 repository_override_forbidden`, de modo que nadie que no sea el operador
puede apuntar el integrador a otra ruta del host.

Se restauró además la regla del propietario de no mantener comentarios ni
docstrings explicativos en código. Una auditoría AST cubre `src/`, `tests/` y
`scripts/`; no quedan docstrings. La búsqueda de comentarios explicativos no
devuelve coincidencias. Las cadenas multilínea de esquemas SQL y del proceso
hijo son datos ejecutables y no se tocaron.

La revisión independiente encontró un defecto real que las pruebas no veían: el
compare-and-swap de la rama ejecutaba `update-ref` con `check=True`, así que
`push_fast_forward` nunca podía devolver `None`. La ruta "la rama se movió
antes de actualizar" era inalcanzable y la carrera escapaba como error interno
en vez de un `review`. Corregido con `check=False` y una prueba que mueve la
rama justo antes de la actualización.

La otra observación del revisor **queda cerrada**: la puerta de aceptación es
ahora obligatoria para la cola, con comprobación al encolar y antes de integrar.

Cierre reproducible de esta tanda: las 13 pruebas HTTP de la cola pasan; la
suite completa pasa con **677 tests en 410.211 s** y 26 omisiones justificadas, de las cuales veinte se ejecutaron aparte contra PostgreSQL 16.2.
`compileall` sobre `src`, `tests` y `scripts` termina sin salida.
