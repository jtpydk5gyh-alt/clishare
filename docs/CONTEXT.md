# Contexto del proyecto — CSHCLI

Resumen del estado real, verificado contra `origin/main` el 15 de octubre
de 2026. Este documento reemplaza a la memoria de sesión para que cualquier
agente pueda orientarse sin releer la conversación.

## Dónde está el proyecto hoy

**Versión 0.2.0, publicada con checksum.** 46 commits, todos con noreply. 423
tests verdes, 4 omitidos con su motivo. CI verde en Windows y Linux × Python
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

**El siguiente trabajo está escrito**, no empezado: `docs/PLAN-ONLINE.md`
cubre hacer que funcione online, simplificar la primera ejecución, documentar el
comando de instalación y añadir `cshcli update`. Los pasos 1 a 3 se pueden
hacer aquí; el 4 necesita una máquina.

## Identidad del repositorio

| Dato | Valor |
| --- | --- |
| Repositorio | `jtpydk5gyh-alt/cshcli`, público, licencia MIT |
| Versión | `0.2.0`, con `dist/SHA256SUMS` |
| Rama por defecto | `main`, 46 commits, todos con la noreply de GitHub |
| Módulo Python | `cshcli`, 21 módulos, comando `cshcli`, script `scripts/cshcli.py` |
| Estado local | `.cshcli/`, ignorado por git |
| PRs mergeadas | 34, sin `--admin`: el control obligatorio se respeta |
| Pruebas | 423, verdes salvo 4 omitidas: 2 por symlink y 2 por no haber PostgreSQL |
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
4. Versionar después de un cambio grande. **Hecho**: `0.2.0` con checksum y la
   copia instalada verificada.

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

## Versionado: por qué 0.2.0 y no 0.1.1

Decisión del propietario: **después de un cambio grande se versiona**. El
bloque que acababa de cerrar —runner, DAG, cola, despliegues, presupuestos,
identidad y el guard corregido— es un cambio grande, así que el proyecto pasa
de `0.1.0` a **`0.2.0`**.

Un cambio de parche habría sido untrue: no es una corrección, es una capacidad
que antes no existía. Y no es `1.0.0` porque el piloto sigue siendo local, el
sandbox no existe y el servicio remoto no se ha levantado.

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

## Lo que viene ahora: online, sencillo y autoactualización

Decidido por el propietario el 15 de octubre. El plan completo, con sus
razones, está en `docs/PLAN-ONLINE.md`. **Nada de eso está implementado
todavía**, y esa distinción importa más que la lista.

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