# Plan: online, sencillo, y que se actualice solo

Decisión del propietario, 15 de octubre de 2026. Este documento es el plan.
Nada de aquí está implementado salvo lo que cada sección dice expresamente.
Se ejecuta en el orden marcado.

## Lo que se pide

1. Que CSHCLI **funcione online**.
2. Que la interfaz sea **mucho más fácil y simple** para la gente.
3. Que **se autoactualice** cuando el repositorio tenga cambios.
4. Que exista el comando
   `py -m pip install "https://github.com/jtpydk5gyh-alt/cshcli/archive/refs/heads/main.zip"`
   y que **ayude a poner la clave de API o a empezar**.

## Las cuatro decisiones, y por qué

### 1. Online: cliente y servidor se separan de verdad

Hoy el coordinador es un proceso en loopback al que nadie más llega. Para que
exista "online" hacen falta dos cosas que hoy no existen: **un sitio donde viva
el coordinador** y **una dirección a la que apunte el cliente**.

| Camino | Qué hace falta | Veredicto |
| --- | --- | --- |
| Túnel al portátil del owner | Un servidor y credenciales | **Rechazado.** Publica la máquina de alguien y no es un producto |
| Hospedar el coordinador | Un servidor o un hosting con coste | **Viable**, es el camino de verdad |
| Que cada persona monte el suyo | Docker y un servidor propio | **Viable**, y es el mismo código del segundo |

El código del servidor **ya existe**: `src/cshcli/remote/`, el esquema en
`migrations/001_remote.sql` y `deploy/compose.yaml`. Lo que falta es poder
**levantarlo y probarlo**, y eso necesita una máquina que aquí no hay.

**Decisión:** se construye un único comando, `cshcli serve --remote`, que
levanta el coordinador sobre PostgreSQL detrás de HTTPS con la base en red
privada, y el cliente deja de exigir loopback cuando la URL lo es de verdad.

**Lo que no se puede prometer todavía.** No hay servidor, ni Docker, ni WSL, ni
PostgreSQL en esta máquina. Todo lo anterior se escribe y se revisa, pero
**"funciona online" no se declara hasta que alguien lo haya levantado en algún
sitio y dos personas hayan conectado desde máquinas distintas.** Esa frase
tiene que poder leerse en el README el día que sea cierto, y no antes.

### 2. Sencillo: un comando, y que sepa qué hacer después

La interfaz actual es correcta y completa, y por eso es difícil: `cshcli auth
register`, `cshcli project create`, `cshcli project invite`, más `CSHCLI_TOKEN`
en el entorno. Cuatro pasos y una variable de entorno antes de hacer nada
útil.

La simplicidad no es quitar comandos. Es que **el camino por defecto no
requiera saberlos**.

**Decisión:**

- `cshcli` sin argumentos **no imprime la ayuda**: comprueba qué falta y hace
  lo siguiente. Si no hay identidad, empieza el alta. Si no hay proyecto, crea
  uno. Si no hay proveedor, ofrece configurarlo.
- `cshcli start` hace, en un guion corto y con preguntas: nombre, proveedor,
  clave. Al final hay un proyecto funcionando y una orden copiada para pegar.
- **Los comandos actuales no desaparecen.** Quien ya sepa usarlos sigue
  pudiendo. Se añaden atajos, no se quitan puertas.
- El texto va en español y en frases cortas. El inglés se queda para lo técnico.

### 3. La clave entra pegándola, no escribiéndola en una terminal

Pediste que el comando de instalación **ayude a poner la clave**. Aquí hay una
razón técnica y no un capricho: hoy la clave va en `$env:OPENAI_API_KEY`, que
queda en el historial de la terminal y en el entorno de cada proceso hijo.

**Decisión:** un almacén local con permisos restringidos, el mismo `SecureStore`
que ya existe para las sesiones nativas. `cshcli start` ofrece "pega tu clave" y
la guarda ahí. Se puede seguir usando la variable de entorno, y cuando está
presente tiene prioridad, porque quien la exporta sabe lo que hace.

**La clave nunca se imprime, ni entra en un log, ni viaja al coordinador.** Hay
un test que lo comprueba, como el que ya existe para el guardián.

### 4. Autoactualización: avisar sí, instalar solo con permiso

Se pide que se autoactualice. Instalar código por sorpresa es una mala idea
aunque el código sea el tuyo, y aquí hay una razón concreta: **instalar desde
`main` es instalar código sin versionar y sin reviews**.

**Decisión:**

- `cshcli update` **compara** la versión instalada con la publicada y dice qué
  hay. No cambia nada.
- `cshcli update --apply` instala, **pide confirmación escribiendo el nombre de
  la versión**, y comprueba el checksum del artefacto antes de tocar la
  instalación actual.
- Si hay cambios sin versión nueva, que es lo normal en `main`, lo dice con
  claridad en vez de fingir que hay una actualización.
- **Nunca** descarga código de una rama que no sea `main` ni de un tag sin
  verificar.

### 5. El comando de instalación, y las tres cosas que hay que mirar

```
py -m pip install "https://github.com/jtpydk5gyh-alt/cshcli/archive/refs/heads/main.zip"
```

Funciona: `pip` acepta una URL de zip. Pero hay tres cosas que conviene saber
antes de documentarlo como la vía recomendada:

1. **Instala `main`, no una versión.** Sin versión no hay reproducibilidad ni
   hay a qué volver si algo sale mal. Se acepta como vía de desarrollo, y por
   eso `cshcli update` avisa cuando lo instalado viene de ahí.
2. **No comprueba nada.** Ni checksums, ni firmas, ni el contenido. Por eso
   `scripts/release.py` genera `SHA256SUMS` y por eso `update --apply` los
   comprueba: sin eso, la actualización automática sería instalar lo que sea
   que el servidor entregue.
3. **El comando `cshcli` puede no quedar en el PATH** tras instalar así,
   según dónde se instale. `py -m cshcli` siempre funciona, y es la forma que
   se documenta como alternativa.

La vía recomendada para uso normal es la versión publicada con su checksum. La
de `main` se documenta como la vía de quien quiere lo último.

## Orden de ejecución

| # | Paso | Por qué en este orden | Estado |
| --- | --- | --- | --- |
| 1 | `cshcli start` y el almacén local de claves | Sin esto, lo demás sigue siendo difícil. Es el que más uso cambia | **Hecho** |
| 2 | El comando de instalación documentado, con sus tres advertencias | Es la puerta de entrada y hoy no está documentado | **Hecho**, en el README |
| 3 | `cshcli update`, primero avisando y luego con `--apply` | Depende del 1 y del 2: sin almacén y sin checksums, actualizar es a ciegas | **Hecho** |
| 4 | `cshcli serve --remote` con HTTPS y PostgreSQL | Es lo más grande y lo único que necesita una máquina. Va último porque es el que puede quedarse esperando infraestructura | Pendiente y bloqueado |

Los pasos 1, 2 y 3 se pueden hacer y verificar aquí. **El 4 no se declara
hecho hasta que alguien lo levante en un servidor y dos personas se conecten
desde máquinas distintas.** Esa frase no se abrevia.

## Lo que esto no cambia

- **La web no se publica.** Sigue siendo decisión del owner, escrita en
  `docs/CONTEXT.md` y en el `.gitignore`.
- **Los comandos existentes no se quitan.** Se añaden atajos.
- **La clave nunca sale de la máquina del usuario.** Ni al coordinador, ni a un
  log, ni a un ticket.
- **Un PR sigue sin mergearse solo.** El control `Personal data guard` es
  obligatorio y `cshcli update` no lo esquiva: si el guard falla, la
  instalación se detiene.