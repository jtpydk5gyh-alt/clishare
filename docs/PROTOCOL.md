# Protocolo HTTP de coordinación, versión 1

Fecha: 14 de octubre de 2026. Esta versión describe el piloto local. La URL base la imprime el servidor; normalmente será `http://127.0.0.1:8765`. El servicio solo admite loopback y no debe publicarse mediante un túnel, proxy inverso o bind público. HTTPS y cuentas verificadas pertenecen a una fase posterior.

## Convenciones

- JSON UTF-8. Los cuerpos deben ser objetos, con `Content-Type: application/json`.
- Máximo de cuerpo HTTP: 1 MiB (1 048 576 bytes).
- Salvo `GET /health` y `POST /v1/users`, todas las rutas requieren `Authorization: Bearer <token_personal>`.
- `id` y `project_id` son identificadores opacos. El cliente no debe deducir permisos de ellos.
- Los tiempos son timestamps UTC del servidor expresados en segundos Unix. El cliente no controla la caducidad absoluta.
- Los enteros JSON son estrictos: `true`, `1.0` y `"1"` no sustituyen a `1` en versiones, fences ni TTL.
- La memoria se pagina por clave; las reservas activas se devuelven como lista. Los eventos tienen un límite de resultados; no son una suscripción en tiempo real.
- Las respuestas exitosas contienen `{"data": ...}`; los errores contienen `{"error":{"code":"...","message":"..."}}`.
- No se emiten cabeceras CORS permisivas. Las solicitudes con `Origin` y los `Host` ajenos al servicio local se rechazan para reducir acceso desde páginas web y DNS rebinding.

Los ejemplos usan identificadores descriptivos para mostrar la forma del JSON. El servidor genera los valores reales.

## Salud e identidad local

### `GET /health`

Sin bearer. Respuesta `200`:

```json
{"data":{"status":"ok","mode":"local-pilot"}}
```

### `POST /v1/users`

Sin bearer. Cuerpo:

```json
{"name":"ana"}
```

El nombre debe ser texto no vacío, sin caracteres de control y de hasta 80 caracteres. Los nombres son únicos sin distinguir mayúsculas/minúsculas. Respuesta `201`, con al menos:

```json
{"data":{"id":"user-id","name":"ana","token":"secreto-generado-por-el-servidor"}}
```

El token personal se entrega al crearlo y se guarda con hash en la base de datos. El cliente debe conservarlo localmente sin añadirlo al repositorio. `409 name_taken` indica un nombre ocupado. Esta identidad es local: no verifica correo, cuenta del proveedor ni usuario de GitHub. El piloto no incluye revocación ni recuperación de tokens.

## Proyectos e invitaciones

### `GET /v1/projects`

Bearer requerido. Respuesta `200` con la lista de proyectos a los que pertenece el usuario. Cada entrada incluye `id`, `name` y su `role`. No se listan proyectos ajenos.

### `POST /v1/projects`

Cuerpo `{"name":"mi-proyecto"}`. Nombre de texto no vacío, sin caracteres de control, máximo 120 caracteres. Respuesta `201` con el proyecto creado. El creador adquiere rol `owner`.

### `POST /v1/projects/{project_id}/invites`

Solo `owner`. Cuerpo opcional:

```json
{"role":"member","ttl":3600}
```

`role` admite `member` y `viewer`; por defecto `member`. `ttl` es un entero de 1 a 604800 segundos; por defecto 3600. Respuesta `201` con el token de invitación y su caducidad. No se puede invitar como `owner`. El servicio guarda hash del token y no envía correo ni mensajes al invitado.

### `POST /v1/invites/accept`

El destinatario presenta su bearer personal y este cuerpo:

```json
{"token":"token-de-invitacion"}
```

Respuesta `200`:

```json
{"data":{"project_id":"project-id","role":"member"}}
```

La aceptación y la incorporación son atómicas. Dos clientes que consumen la misma invitación simultáneamente dejan un único ganador. Una invitación consumida devuelve `409 invite_used`; una caducada devuelve `409 invite_expired`; un token desconocido devuelve `404 invite_not_found`. Una aceptación no degrada el rol de un propietario existente.

## Memoria con versión esperada

### `GET /v1/projects/{project_id}/memory`

Todos los miembros pueden leer. Parámetros query: `limit`, entero de 1–10 (por defecto 10), y `after`, última clave de la página anterior. Las claves se ordenan lexicográficamente y el cursor es exclusivo. Respuesta `200` con página:

```json
{"data":{"items":[
  {"key":"architecture","content":"Contexto compartido","version":1,"author_id":"user-id","updated_at":1791943200.0}
],"next_cursor":null}}
```

Cada entrada incluye `key`, `content`, `version`, `author_id` y `updated_at`; el proyecto está determinado por la URL. Si `next_cursor` no es `null`, se obtiene la siguiente página con `?limit=10&after=<cursor-codificado>`. El cliente debe codificar el cursor como valor de query; no concatenarlo sin escapar. La paginación no representa un snapshot global: si se modifican claves entre páginas, el cliente debe releer antes de actuar sobre su contenido.

### `PUT /v1/projects/{project_id}/memory`

Solo `owner` y `member`. Cuerpo:

```json
{
  "key":"architecture",
  "content":"Cada tarea se desarrollará en un worktree propio en la fase runner.",
  "expected_version":0
}
```

`key` es texto no vacío, sin controles, de hasta 200 caracteres. `content` es texto de hasta 256 KiB codificado en UTF-8. `expected_version` es un entero de 0 a 2⁶³−2. `0` crea una clave que no existe; para actualizar se presenta la versión actual. La respuesta `200` devuelve la entrada persistida con versión incrementada y autor. Un desfase devuelve `409 version_conflict` sin sobrescribir.

Secuencia correcta: leer versión → reconciliar el contenido deseado → escribir con esa versión → si llega `409`, releer y decidir. No se debe sustituir automáticamente `expected_version` y reenviar el mismo contenido, porque eso perdería el cambio ajeno.

No hay borrado de memoria ni historial completo de revisiones en v1. La memoria es contenido de colaboradores; no puede conceder permisos o autorizar despliegues.

## Reservas de recursos

### `GET /v1/projects/{project_id}/leases`

Todos los miembros pueden leer. Respuesta `200` con leases activos; las reservas caducadas no bloquean ni aparecen como activas. Cada registro incluye `id`, `project_id`, `user_id`, `agent_id`, `resource`, `fence` y `expires_at`.

### `POST /v1/projects/{project_id}/leases`

`owner` y `member` pueden reservar archivos; únicamente `owner` puede reservar un entorno de despliegue. Cuerpo:

```json
{
  "agent_id":"ana-agente-1",
  "resources":["file:src/api.py","file:tests/test_api.py"],
  "ttl":120
}
```

`agent_id` es una etiqueta de 1–120 caracteres sin controles bajo la identidad autenticada. No reemplaza al bearer ni es identidad autónoma. `ttl` admite enteros de 1 a 3600 segundos; por defecto 120. `resources` es una lista de 1–100 recursos sin duplicados ni solapamientos internos; cada recurso mide hasta 1024 caracteres. La respuesta `201` es una **lista de leases**, uno por recurso; cada fila tiene su propio `id` opaco de texto y `fence` entero. El lote se adquiere en una sola transacción: si un recurso entra en conflicto no se concede ninguno.

```json
{"data":[
  {"id":"lease-a-id","project_id":"project-id","user_id":"user-id","agent_id":"ana-agente-1","resource":"file:src/api.py","fence":41,"expires_at":1791943320.0},
  {"id":"lease-b-id","project_id":"project-id","user_id":"user-id","agent_id":"ana-agente-1","resource":"file:tests/test_api.py","fence":42,"expires_at":1791943320.0}
]}
```

Los valores son ilustrativos: `id` identifica la reserva y `fence` su generación. Un conflicto devuelve `409 lease_conflict` y requiere esperar, reducir recursos o replanificar. La reserva no se concede de forma reentrante por repetir el mismo `agent_id`.

### Recursos admitidos

| Sintaxis | Significado | Conflictos |
| --- | --- | --- |
| `file:src/api.py` | Ruta relativa | Esa ruta, sus padres reservados y sus descendientes |
| `file:src` | Prefijo de directorio | `file:src/api.py`, pero no `file:src2/api.py` |
| `deploy:staging` | Entorno exacto | Otra reserva de `deploy:staging` |

Las rutas de archivo usan `/` y se comparan con `casefold()` conservador. Se rechazan `\`, rutas absolutas/de unidad, segmentos vacíos, `.` o `..`, nombres reservados de Windows, sufijos ambiguos de espacios/puntos, caracteres `:`, `<`, `>`, `"`, `|`, `?`, `*` y caracteres de control. Los entornos usan 1–64 letras ASCII, números, `_` o `-`. Esto evita recursos ambiguos en el protocolo; no resuelve symlinks ni bloquea escrituras del filesystem. `deploy:PROD` y `deploy:prod` son el mismo recurso normalizado; `deploy:prod-eu` es distinto.

### `POST /v1/projects/{project_id}/leases/{lease_id}/renew`

Solo el usuario que adquirió el lease. Cuerpo:

```json
{"fence":41,"ttl":120}
```

`fence` debe ser entero positivo igual al de la reserva. `ttl` tiene el mismo rango y valor por defecto que la adquisición. Respuesta `200` con el registro renovado. La nueva caducidad se calcula desde el reloj del servidor; el fence se conserva. Una reserva caducada devuelve `409 lease_expired` y no revive; un fence incorrecto devuelve `409 fence_mismatch`.

### `DELETE /v1/projects/{project_id}/leases/{lease_id}`

Solo el usuario que adquirió el lease. **Lleva cuerpo JSON**:

```json
{"fence":41}
```

Respuesta `200`: `{"data":{"released":true}}`. Fence incorrecto o reserva caducada devuelve `409`. Otro miembro no puede liberar la reserva, aunque conozca su identificador y fence. Usar un lease desde otro proyecto devuelve `404`.

Los fences aumentan de forma persistente con nuevas adquisiciones y sobreviven a reinicios. El cliente no los calcula. Una integración que quiera impedir escritores antiguos debe verificar el fence en el momento de aplicar el cambio; el servicio de v1 no aplica patches ni ejecuta deploys.

## Eventos

### `GET /v1/projects/{project_id}/events`

Todos los miembros pueden consultar los eventos del proyecto. Respuesta `200` con registros que incluyen proyecto, actor, `kind`, payload y timestamp. Por ejemplo, `memory.updated` indica una mutación aceptada. Los eventos no contienen bearer, tokens de invitación, API keys ni contenido completo de memoria.

El store admite `list_events(user_id, project_id, limit=100)` con límite entero de 1 a 1000. La exposición de filtros, cursores y streaming en HTTP se incorporará como una extensión explícita; v1 no promete reanudar una suscripción desde un cursor.

## Errores y reglas de reintento

| HTTP | Situación | Acción del cliente |
| --- | --- | --- |
| `400` | JSON/campo/tipo/recurso/TTL/fence inválido, Content-Length duplicado o Transfer-Encoding no admitido | Corregir la petición; no reintentar igual |
| `401` | Bearer ausente, inválido o identidad desconocida | Seleccionar credencial local válida |
| `403` | No miembro, rol insuficiente, lease ajeno, Origin/Host rechazado | Cambiar permisos o destino de forma explícita |
| `404` | Ruta, proyecto, invitación o lease inexistente | Releer identificadores; no crear sustitutos implícitos |
| `409` | CAS, recurso ocupado, fence, caducidad o invitación consumida | Releer estado y replanificar |
| `413` | Cuerpo superior a 1 MiB | Reducir el cuerpo antes de reenviar |
| `415` | Cuerpo con Content-Type distinto de application/json | Enviar JSON con la cabecera correcta |
| `500` | Fallo interno no previsto | Conservar contexto, comprobar coordinador y releer antes de repetir mutaciones |

Ejemplo de error:

```json
{"error":{"code":"version_conflict","message":"La versión de memoria ya ha cambiado."}}
```

El texto `message` es explicativo; los clientes deciden con `code` y HTTP. Los detalles internos de SQLite y los secretos no se devuelven. El cliente admite respuestas de hasta 32 MiB y devuelve `response_too_large` si se supera ese límite, sin intentar interpretar JSON truncado. No existe una idempotency key general para POST en el piloto: tras perder una respuesta hay que leer el estado antes de repetir una mutación. En particular, repetir una adquisición puede chocar con el lease concedido por el primer intento.

## Compatibilidad y garantías

El prefijo `/v1` identifica este contrato. Añadir campos de respuesta es compatible; eliminar campos, cambiar semántica de recursos o modificar roles requiere versionado/migración. Los clientes deben ignorar campos adicionales y conservar los identificadores como opacos.

v1 garantiza decisiones transaccionales de coordinación para un coordinador local. **No garantiza exclusión de escritores externos, aislamiento de agentes, integración Git ni despliegues serializados reales.** Esas garantías tienen criterios de aceptación propios en el [diseño](superpowers/specs/2026-10-14-clishare-design.md) y en el [plan](superpowers/plans/2026-10-14-clishare.md).
