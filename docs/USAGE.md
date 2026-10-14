# CLIShare

CLI de IA con credenciales personales y coordinación compartida de proyectos.
La idea: tú creas un proyecto, invitas a otras personas y cada una trabaja con sus
agentes y sus cuentas de IA, compartiendo decisiones y reservando archivos.

**Estado: piloto local 0.1.0.** Ya hay CLI, coordinador HTTP local, SQLite,
proyectos, invitaciones, memoria versionada, reservas y adaptadores de texto IA.
El servicio remoto multiusuario, el runner que controla escrituras, los worktrees
automáticos, la cola de integración y los despliegues reales están en el plan.

El [plan completo](superpowers/plans/2026-10-14-clishare.md), el
[diseño](superpowers/specs/2026-10-14-clishare-design.md) y el
[protocolo HTTP](PROTOCOL.md) describen requisitos, fases, permisos,
invariantes, riesgos y criterios de aceptación. [AGENTS.md](../AGENTS.md) establece
las reglas iniciales de trabajo del repositorio.

## Ejecutar desde el código

Requisito: Python 3.11 o posterior. El piloto no necesita dependencias de ejecución.
Desde la raíz del repositorio:

```powershell
python scripts/clishare.py --help
python scripts/clishare.py serve
```

El coordinador escucha en `http://127.0.0.1:8765` y guarda su base de datos en
`.clishare/coordinator.sqlite3`. Esa carpeta está ignorada por Git. El servidor de
este corte admite exclusivamente loopback; la fase de servicio remoto incluye
HTTPS, identidad verificada, límites de peticiones y administración de miembros.

Para instalar el comando en un entorno virtual:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\clishare --help
```

En Linux/macOS: `.venv/bin/python -m pip install -e .` y `.venv/bin/clishare`.
El empaquetado usa setuptools; el primer comando de instalación puede descargarlo.

## Crear un proyecto e invitar a alguien

Mantén el servidor en la primera terminal. En una segunda terminal PowerShell:

```powershell
$identity = python scripts/clishare.py auth register ana | ConvertFrom-Json
$env:CLISHARE_TOKEN = $identity.token
$project = python scripts/clishare.py project create mi-proyecto | ConvertFrom-Json
$projectId = $project.id
python scripts/clishare.py project list
python scripts/clishare.py project invite $projectId --role member --ttl 3600
```

El token personal de registro se entrega una vez y en la base de datos solo se
guarda su hash. Consérvalo en un almacén local seguro; este corte no tiene
recuperación ni rotación de tokens. La invitación también se devuelve una vez,
caduca y solo puede aceptarse una vez. Compártela con su destinatario por un canal
privado. CLIShare no envía mensajes ni invitaciones por correo automáticamente.

En otra terminal que acceda al mismo coordinador local:

```powershell
$identity = python scripts/clishare.py auth register luis | ConvertFrom-Json
$env:CLISHARE_TOKEN = $identity.token
python scripts/clishare.py project join
python scripts/clishare.py project list
```

`project join` solicita la invitación sin mostrarla. También admite
`--invite-stdin` para automatización. Este ejemplo demuestra dos identidades en
un solo equipo; la colaboración entre equipos necesita la fase de servicio remoto.

| Rol | Leer proyecto, memoria, reservas y eventos | Editar memoria y reservar archivos | Invitar y reservar despliegues |
| --- | --- | --- | --- |
| owner | Sí | Sí | Sí |
| member | Sí | Sí | No |
| viewer | Sí | No | No |

## Memoria y reservas

```powershell
python scripts/clishare.py memory put $projectId architecture --content "Un worktree por tarea" --expected-version 0
python scripts/clishare.py memory list $projectId
python scripts/clishare.py memory put $projectId architecture --content "Un worktree y una rama por tarea" --expected-version 1
python scripts/clishare.py lease acquire $projectId ana-1 file:src/auth.py file:tests/test_auth.py --ttl 120
python scripts/clishare.py lease list $projectId
```

Cada entrada de memoria tiene autor, fecha y versión. `0` crea una entrada; una
actualización debe indicar la última versión leída. `memory list` devuelve
`items` y `next_cursor`; si hay más entradas, usa `--after` con ese cursor.
`--limit` permite de 1 a 10 entradas por página. Un conflicto devuelve error
409 y obliga a releer, evitando sobrescribir el cambio de otra persona. También
puedes usar `memory put ... --file archivo.md --expected-version N` o `--file -`.

Una reserva de `file:src` entra en conflicto con `file:src/auth.py`. Recursos
disjuntos pueden trabajarse en paralelo. Un lote se adquiere completo o se rechaza
completo. Las rutas son relativas, con `/`, sin `..`, rutas absolutas ni nombres
ambiguos de Windows; el coordinador compara mayúsculas de forma conservadora.

La salida incluye `id`, `fence` y `expires_at` para cada recurso. Renueva antes de
que venza y usa los valores de esa reserva:

```powershell
python scripts/clishare.py lease renew $projectId ID_DE_RESERVA FENCE --ttl 120
python scripts/clishare.py lease release $projectId ID_DE_RESERVA FENCE
python scripts/clishare.py events $projectId
```

TTL predeterminado: 120 segundos; rango: 1–3600. La renovación es manual en este
corte. Los fences son crecientes y persistentes: un titular antiguo no puede
renovar o liberar una reserva vencida o reasignada usando un valor obsoleto.

**Límite actual:** una reserva es un acuerdo comprobado por el coordinador.
Todavía no intercepta escrituras de herramientas externas ni conecta el chat
con un agente editor. El runner y la validación de parches del siguiente hito
aplicarán esas reservas a los cambios de código.

## Cuentas de IA y API keys

La identidad de CLIShare y las cuentas de IA son independientes. El coordinador
no recibe claves de proveedores; las llamadas se realizan desde el CLI local.

```powershell
python scripts/clishare.py provider status
python scripts/clishare.py provider login codex
python scripts/clishare.py provider login claude
python scripts/clishare.py provider login gemini
```

Los comandos de login ejecutan el CLI oficial instalado y dejan que este gestione
su autenticación. No copian tokens OAuth ni archivos de credenciales. Se necesita
una versión compatible y el ejecutable en el PATH; en Windows, este adaptador
requiere un ejecutable nativo, porque los wrappers `.cmd/.bat` no conservan todas
las garantías de argumentos. Gemini instalado mediante npm suele usar un wrapper;
en ese caso inicia sesión directamente con su comando oficial y usa su API aquí.

| `chat --provider` | Credencial local | Estado |
| --- | --- | --- |
| `openai` | `OPENAI_API_KEY` | API Responses, modelo explícito |
| `anthropic` | `ANTHROPIC_API_KEY` | API Messages, modelo explícito |
| `google` | `GEMINI_API_KEY` | API generateContent, modelo explícito |
| `codex` | Autenticación del CLI oficial | Texto con sandbox read-only y opciones verificadas |
| `claude-code` | Autenticación del CLI oficial | Texto con herramientas desactivadas y opciones verificadas |
| `gemini-cli` | Autenticación del CLI oficial | Chat bloqueado hasta disponer de aislamiento verificable |

```powershell
$env:CLISHARE_MODEL = "identificador-del-modelo"
python scripts/clishare.py chat --provider openai --model $env:CLISHARE_MODEL "Explica este diseño"
python scripts/clishare.py chat --provider codex "Propón un plan de migración"
python scripts/clishare.py chat --provider claude-code "Revisa esta decisión de arquitectura"
```

El chat actual recibe texto, no adjunta ni recorre el repositorio. Los CLIs de
cuentas ejecutan el chat desde una carpeta temporal vacía. Si faltan los flags
necesarios, el adaptador devuelve un error. Las políticas administradas del CLI
oficial siguen aplicándose; el wrapper no es un sandbox universal.

Las variables API de CLIShare y `CLISHARE_*` se eliminan del entorno de los
subprocesos oficiales. El método de autenticación y la facturación de esos CLIs
siguen dependiendo de su configuración oficial. Una suscripción y una API key
pueden tener cuotas y facturación distintas. CLIShare no cambia automáticamente
de proveedor ni de modalidad de pago tras un error.

OpenAI también documenta una ruta oficial de
[Sign in with ChatGPT](https://developers.openai.com/siwc/quickstart).
Su integración directa se evaluará con un cliente propio y su elegibilidad:
el repositorio privado no concede acceso automáticamente. Claude Code y Gemini CLI
conservan sus propios flujos de login; el roadmap recoge las restricciones de
cada proveedor y las fuentes oficiales.

`.env.example` solo documenta variables: el CLI no carga `.env` automáticamente.
No pongas secretos en prompts, memoria, eventos o archivos versionados. Los errores
de proveedores omiten cuerpos remotos y stderr para no revelar credenciales.

## Coordinar despliegues

```powershell
python scripts/clishare.py deploy reserve $projectId staging --agent ana-release --ttl 120
```

Solo el propietario puede reservar `deploy:staging`; un segundo intento al mismo
entorno falla mientras la reserva siga activa. Se renueva y libera con `lease`.
**Este comando reserva el entorno; no despliega.** El plan incluye cola persistente,
SHA y digest exactos, idempotencia, comprobaciones, publicación, health checks,
reconciliación tras fallos y rollback.

## Verificación

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src tests scripts
python scripts/clishare.py --help
```

Las pruebas usan SQLite real, HTTP local y fixtures de proveedores. Las carreras
sincronizadas hacen competir a once agentes de dos personas por un mismo recurso,
una versión de memoria y una invitación. Comprueban permisos, expiración,
fencing persistente, rutas, lotes atómicos y ausencia de secretos en auditoría.
Las pruebas de proveedores no hacen llamadas de pago ni verifican logins reales.

La [plantilla de GitHub Actions](templates/ci.yml.example) ejecutará la suite
en Windows y Linux con Python 3.11, 3.12 y 3.13 cuando se active como
`.github/workflows/ci.yml`. La credencial usada para la primera subida no permite
publicar workflows; CI queda pendiente de activación con el permiso correspondiente.

## Siguientes entregas

1. Servicio remoto con HTTPS, cuentas verificadas, rotación de tokens y revocación de miembros.
2. Runner por tarea con worktrees, heartbeat, herramientas mediadas y control de rutas/symlinks.
3. Tareas y límites por persona/proveedor, memoria con evidencias y cola de integración sobre SHA.
4. Pipeline de despliegue por entorno con artefactos verificables y rollback.
5. OAuth propio elegible, streaming, métricas de coste, empaquetado y distribución.

El plan desarrolla cada entrega con contratos, pruebas y condiciones de cierre.
