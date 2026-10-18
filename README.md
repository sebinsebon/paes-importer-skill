# PAES Importer Skill

Skill portable para convertir ensayos PDF **PAES Matemática M1**, con solucionario opcional, a contenido **PAESSED 0.2.0** dentro de `.paessed` y ZIP idénticos. El agente interpreta las fuentes; las herramientas renderizan, recortan, validan y empaquetan. No requiere otra API de IA.

Repositorio oficial: https://github.com/sebinsebon/paes-importer-skill

Para utilizarla, entrega al agente el bundle completo y comienza por [SKILL.md](SKILL.md). Indica **Chat Web** o **CLI / agente de terminal** y proporciona ensayo y solucionario correspondiente. Si falta el entorno, la skill lo pregunta antes de cargar referencias y PDFs. La selección conserva cuatro flujos:

| Entorno | Pauta correspondiente | Flujo |
| --- | --- | --- |
| Chat web | Completa | [01 Chat con solucionario](flows/01-chat-con-solucionario/WORKFLOW.md) |
| CLI | Completa | [02 CLI con solucionario](flows/02-cli-con-solucionario/WORKFLOW.md) |
| CLI | Ausente o parcial | [03 CLI sin solucionario completo](flows/03-cli-sin-solucionario/WORKFLOW.md) |
| Chat web | Ausente o parcial | [04 Chat sin solucionario completo](flows/04-chat-sin-solucionario/WORKFLOW.md) |

En Chat Web se adjuntan ambos archivos para descarga; en CLI se usa el destino indicado o se pregunta Documentos/Descargas/ruta personalizada. Una pauta parcial conserva sus respuestas asociadas. La [operación común](references/workflow.md) exige inventario observado, transcripción editable y cotejo de cada pregunta.

## Instalación

Requisitos mínimos: **Python 3.12+**, **Node.js 18+** disponible en PATH y los paquetes fijados en `requirements.txt`. Los validadores JS, renderer y licencias están incluidos; no requieren `npm install`.

~~~sh
git clone https://github.com/sebinsebon/paes-importer-skill.git
cd paes-importer-skill
python -B scripts/setup.py
~~~

`setup.py` crea el entorno fuera de la skill, en el directorio de datos del usuario. Imprime la ruta del intérprete; úsala para los comandos siguientes. `--env-dir RUTA_ABSOLUTA_EXTERNA` permite elegir otro entorno. `--print-python` consulta la ubicación predeterminada sin escribir. También sirve un Python que ya tenga `requirements.txt` instalado. Para instalación sin red se necesitan los paquetes disponibles en el entorno o un repositorio configurado por el usuario.

En Windows, `./run.ps1 --help` resuelve el entorno predeterminado. Para otro intérprete: `./run.ps1 -PythonPath RUTA_PYTHON --help`. Desde otra carpeta utiliza rutas absolutas; en PowerShell invoca rutas entre comillas con `&`. Todos los recursos se resuelven desde la ubicación de la skill.

Los entornos virtuales se recrean al trasladarlos entre equipos. No se incluyen en el bundle. La skill funciona de forma independiente, sin repositorio de desarrollo. Sus ejecuciones, cachés, perfiles y temporales deben permanecer fuera de la instalación. Trasladar el código no migra las rutas y hashes de ejecuciones ya congeladas.

## Inspección visual

Primero utiliza las herramientas del agente para inspeccionar el HTML producido por `review`. Si puede observarlo, no necesita Playwright. Si no puede abrir HTML, puede utilizar la alternativa de capturas descrita en [operación común](references/workflow.md#comparar-antes-de-entregar).

`python -B scripts/setup.py --with-visual` instala únicamente las dependencias Python opcionales de `requirements-visual.txt`. No descarga navegadores. La captura puede usar un navegador existente mediante `--executable-path`; cualquier navegador instalado aparte y su caché permanecen externos. Chromium y Playwright instalado no forman parte del ZIP.

Si tampoco puede obtener e inspeccionar capturas, el agente informa la limitación y deja la revisión visual pendiente. Generar HTML o imágenes no acredita haberlos revisado. Consulta [compatibilidad por anfitrión](references/hosts.md).

## Salida y contrato

~~~text
EnsayosPaessedOutput/
  m1-<nombre-observado>/
    <fecha-hora>-<id>/
      m1-<nombre-observado>.paessed
      m1-<nombre-observado>.zip
      final.json
      candidate.json
      assets/
      run.json
      .work/
~~~

La ruta personalizada sustituye `EnsayosPaessedOutput`. No se sobrescriben ejecuciones. El paquete contiene `final.json` 0.2.0, `manifest.json` 0.1.0 y recursos utilizados. PDFs, vistas e informes de auditoría permanecen fuera; compártelos por separado si necesitas conservar el expediente completo en Chat Web.

El contrato canónico PAESSED 0.2.0 es la referencia normativa. La distribución incluye esquemas y [contratos operativos](shared/references/content-contract.md) sincronizados; no depende de una carpeta `contrato/` externa. La clasificación M1 se rige por el [contrato curricular](shared/references/curriculum-contract.md). Se conserva lectura histórica 0.1.0; `draft.json` v1 es una entrada interna opcional, nunca un final.

`python -B scripts/check_release.py` comprueba los archivos distribuidos sin escribir. La construcción del ZIP y el mantenimiento se realizan fuera de este repositorio operativo; el usuario puede trasladar el bundle completo a otro anfitrión.

## Límites y licencia

Los controles automáticos verifican estructura, geometría declarada, recursos y hashes. Lectura, correspondencia semántica, fidelidad matemática e independencia requieren observación real y conservan limitaciones del modelo. Una suite sintética o el estado `verified` no prueban fidelidad de un ensayo real. La autorrevisión no crea `reviewed` ni `verified`.

Código MIT. Se conservan licencias y atribuciones de JSZip y KaTeX en [NOTICE](NOTICE.md). No incorporar PDFs privados, resultados derivados ni credenciales a la distribución.
