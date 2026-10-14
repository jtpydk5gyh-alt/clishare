# Organización del proyecto

Se revisaron repositorios oficiales el 14 de octubre de 2026:

| Proyecto | Práctica aplicada a CLIShare |
| --- | --- |
| [VS Code](https://github.com/microsoft/vscode) | Identificar qué entrega el repo, documentar límites y enlazar planes |
| [GitHub CLI](https://github.com/cli/cli) | Instalación, ejemplo útil y guía de contribución con pruebas reproducibles |
| [uv](https://github.com/astral-sh/uv) | Definición breve del producto y comandos con resultado observable |
| [FastAPI](https://github.com/fastapi/fastapi) | Separar código, pruebas y documentación; recorrido ejecutar y verificar |

La estructura existente `src/clishare`, `tests` y `docs` es suficiente para este
piloto. README ofrece una entrada corta y USAGE conserva las instrucciones
detalladas. LICENSE, CONTRIBUTING y SECURITY cubren licencia, colaboración y
reportes privados. No se añaden componentes, directorios vacíos ni herramientas
propias de monorepos grandes.

La licencia elegida por el propietario es
[MIT de OSI](https://opensource.org/license/mit), sin modificaciones del texto
de permisos. Se aplica al código y documentación propios; las APIs externas
conservan sus condiciones. Las contribuciones externas conservan su autoría.

Las issues describen trabajo; las PRs presentan cambios para revisión, según
la [guía de GitHub](https://docs.github.com/en/get-started/using-github/communicating-on-github).
Los commits deben formar cambios coherentes y explicar su intención.

GitHub distingue el [registro de contribuciones](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference)
de los [logros del perfil](https://docs.github.com/en/enterprise-cloud%40latest/account-and-profile/reference/profile-reference).
Los logros reconocen eventos e hitos; no se promete un trofeo por un número
arbitrario de commits ni se crean issues o PRs vacías para aumentar contadores.
