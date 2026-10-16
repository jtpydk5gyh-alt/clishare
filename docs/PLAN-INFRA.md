# Plan: infraestructura real — PostgreSQL, HTTPS, restore y firma

Decisión del propietario, 16 de octubre de 2026. Todo lo que sigue estaba
declarado como bloqueado por falta de una máquina. Este documento dice cómo se
desbloquea en esta máquina, con lo que ya se ha comprobado y con lo que aún
no.

**La regla no cambia: lo que no se comprueba se declara, no se maquilla.**
Cada punto termina con su evidencia o con la razón por la que no se ha
podido ejecutar.

## 0. Lo que hay en esta máquina, comprobado

| Herramienta | Estado |
| --- | --- |
| Docker | Ausente |
| WSL | `wsl.exe` existe, **sin distribuciones instaladas** |
| PostgreSQL en el PATH | Ausente |
| GPG, OpenSSL, minisign | Ausentes |
| Python | 3.12.10 con `pip` |
| Red | Sí; `pypi.org` responde |

**Cómo se ha resuelto sin Docker ni WSL:** `pip install pgserver` trae los
binarios de **PostgreSQL 16.2** para Windows. `initdb`, `postgres`, `pg_ctl`,
`psql`, `pg_dump`, `pg_restore` y `createdb` están ahí dentro. Arrancan un
clúster real sin instalador y sin privilegios de administrador, y en 17.9 s.

`pip install "psycopg[binary]"` instala el driver que el proyecto ya declaraba
como extra `remote`. **Ninguno de los dos es dependencia del producto**: el
paquete no tiene dependencias de runtime y sigue sin tenerlas.

## 1. PostgreSQL real

`scripts/postgres_local.py` levanta un clúster con puerto fijo bajo un
directorio fuera del repositorio, e imprime el DSN. Los tests lo toman de
`CSHCLI_TEST_DSN`; si no está, **se omiten diciendo por qué**, que es lo que ya
hacían.

Lo que se puede cerrar con esto, y lo que no:

- La migración se aplica contra una base de verdad.
- `RemoteStore` deja de estar en `unverified` por falta de servidor.
- El test de concurrencia de once procesos, que hoy se omite, se ejecuta.

## 2. HTTPS real

`cshcli serve --remote` hoy **valida la configuración y se niega a arrancar**
sin `CSHCLI_TLS_CERT` y sin `CSHCLI_REMOTE_DSN`. Con un certificado autofirmado
y el DSN real, tiene que arrancar, servir y ser consultado por TLS.

**Lo que esto NO es:** una cadena de confianza pública. El certificado es
autofirmado y el cliente tiene que confiar en él explícitamente. Se puede
probar el camino TLS completo hoy; no se puede afirmar que un navegador o una
máquina de otra persona confiarían sin una autoridad certificadora de pago.

## 3. Restore real

`pg_dump` y `pg_restore` contra el clúster de verdad: respaldo, restauración
sobre una base **vacía**, y negativa a restaurar sobre una base poblada. El
drill que hoy solo existe sobre SQLite pasa a ejecutarse contra PostgreSQL.

## 4. Firma de la release

**Bloqueado por una decisión del propietario, no por infraestructura.** El
wheel y `SHA256SUMS` están construidos y con checksum; lo que falta es la
identidad de firma. No hay GPG ni minisign en esta máquina, y se pueden
instalar, pero **la clave es del propietario**: puedo generar una clave nueva y
entregarle la pública y la privada para que las custodie, o usar una que ya
tenga. Generar una identidad criptográfica en nombre de alguien sin que lo
sepa no es una decisión que se tome sola.

## 5. El worktree del agente de auditoría

`~/.codex/worktrees/security-audit/clishare`, rama `audit/security-and-integrity`
con trabajo sin commitear de otro agente. No es infraestructura: es deuda de
higiene. Se revisa, se rescata lo que sirva y se cierra.

## Orden

1. Helper de PostgreSQL y clúster real.
2. `RemoteStore` sirviendo tráfico real, sin `unverified`.
3. El test de once procesos, que deja de omitirse.
4. HTTPS con certificado autofirmado y `serve --remote` levantando.
5. Restore real con `pg_dump`/`pg_restore`.
6. Firma, cuando el propietario decida la clave.
7. Worktree del agente de auditoría.

## Lo que esto no cambia

- **La web no se publica.** Sigue siendo decisión del owner.
- **El sandbox sigue sin existir.** Un contenedor Linux es otra historia.
- **El producto sigue sin dependencias de runtime.** PostgreSQL y el driver
  son infraestructura local y extra opcional, nunca requisitos de instalación.