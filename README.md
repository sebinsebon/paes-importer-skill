# PAES Importer Skill

Skill portable para **PAES Matemática M1** desde PDF, con solucionario opcional, a ZIP/.paessed. El agente anfitrión interpreta/resuelve; Python renderiza, recorta, valida, conserva trazabilidad y empaqueta. No requiere otra API de IA ni API key adicional.

Repositorio: https://github.com/sebinsebon/paes-importer-skill

**Para el agente:** comienza por [SKILL.md](SKILL.md) y sigue solo las referencias operativas que necesite ([workflow](references/workflow.md), [interfaces](references/interfaces.md), [audit](references/audit.md) y [compatibilidad](references/hosts.md)). Los informes y tests de mantenimiento del repositorio no son parte de la skill distribuible.

## Prompts listos para usar

**Chat web**

> Usa la skill de https://github.com/sebinsebon/paes-importer-skill. Estoy en un chat web. Adjunto el ensayo y, si corresponde, su solucionario. Comprueba tus capacidades, selecciona el modo adecuado y entrégame el ZIP final.

**CLI / agente de terminal**

> Usa la skill de https://github.com/sebinsebon/paes-importer-skill. Estoy en un agente de terminal. Los PDFs están adjuntos o en las rutas indicadas. Comprueba tus capacidades, selecciona el modo adecuado y genera el ZIP final.

El anfitrión debe obtener el bundle completo y leer SKILL.md con sus referencias. Si no puede acceder a GitHub, adjunta el ZIP de la skill. Un enlace o SKILL.md aislado no instala dependencias ni añade herramientas. Para un repo privado usa acceso disponible o bundle, nunca credenciales en el prompt.

La skill pregunta destino: Documentos (por defecto), Descargas o ruta personalizada. En chat web sin acceso al equipo, entrega ZIP descargable y recomienda dónde guardarlo. Selección interactiva cuando exista; opciones numeradas en otras interfaces.

## Modos

| Entorno | Solucionario | Flujo |
| --- | --- | --- |
| Chat web / CLI | Completo y correspondiente | Importación con cotejo durante producción, sin resolver otra vez ni auditoría independiente completa. |
| Chat web | Ausente / parcial | Consentimiento experimental para resolver pendientes; si rechazas, conserva respuestas/explicaciones missing. |
| CLI | Ausente / parcial | Resuelve lo no cubierto; auditoría con subagentes si existen, o autorrevisión explícita. |

Pauta con letras: explicación breve generada por IA. Con justificación: reutilizar/resumir y registrar origen. Pauta parcial: resolver solo faltantes. Incompatible/ambigua: aclarar o continuar sin utilizarla. Validación estructural y autorrevisión no convierten respuestas en verified.

## Instalación

Requisitos: **Python 3.12+ y Node.js 18+** (`node` disponible en PATH). Validadores JS y sus bibliotecas/licencias ya están incluidos; no necesita npm install. El instalador descarga las dependencias Python fijadas en requirements.txt; para instalación sin red, deben estar disponibles en el entorno o en un repositorio de paquetes configurado por el usuario.

~~~sh
git clone https://github.com/sebinsebon/paes-importer-skill.git
cd paes-importer-skill
python -B scripts/setup.py
~~~

Windows: .venv/Scripts/python.exe -B scripts/importer.py, o ./run.ps1. Linux/macOS: .venv/bin/python -B scripts/importer.py. También sirve un Python con requirements.txt instalado. setup crea .venv y tmp dentro de este checkout; no borra un entorno existente. Si falla pip, conserva el error y reintenta con el Python ya creado.

Los ejemplos con rutas relativas parten de la carpeta que contiene SKILL.md. `python` debe ser el intérprete con las dependencias instaladas: sustituye ese comando por `.venv/Scripts/python.exe` en Windows o `.venv/bin/python` en Linux/macOS si no activaste el entorno. Desde otra carpeta usa las rutas absolutas del intérprete y del script; en PowerShell invoca rutas entre comillas con `&`. Los scripts encuentran sus recursos desde su ubicación, aunque la ruta contenga espacios o acentos.

Para trasladar o compartir la skill, utiliza el clon o el bundle completo. `.venv` pertenece a cada instalación: sus ejecutables y scripts de activación pueden guardar rutas absolutas y debe recrearse en la nueva ubicación con setup.py, conservando primero el entorno anterior fuera de `.venv` si existe. No copies entornos virtuales entre equipos. Los PDFs y las salidas se eligen explícitamente; las ejecuciones guardan sus rutas originales para reanudación y auditoría, por lo que trasladar el código no migra ejecuciones existentes.

El agente puede leer [SKILL.md](SKILL.md) desde esta carpeta. Para descubrimiento en Codex/Claude Code, copia el bundle completo bajo .agents/skills/paes-importer o .claude/skills/paes-importer; prepara dependencias allí o usa otro Python instalado. No es necesario instalar globalmente. [Compatibilidad](references/hosts.md).

## Operación y salida

El agente sigue [workflow](references/workflow.md), localiza preguntas, asocia pauta y produce contenido; prepare no resuelve automáticamente. [Interfaces](references/interfaces.md) de lote, pauta y cotejo. [Auditoría](references/audit.md) cuando corresponda.

~~~text
Documentos/EnsayosPaessedOutput/
  m1-<nombre-observado>/
    <fecha-hora>-<id>/
      m1-<nombre-observado>.zip
      m1-<nombre-observado>.paessed
      final.json
      candidate.json
      assets/
      run.json
      .work/
~~~

Descargas usa igual estructura; ruta personalizada sustituye la raíz EnsayosPaessedOutput, sin agregarla otra vez. Windows respeta carpetas redirigidas y Linux XDG. No sobrescribir ejecuciones. ZIP lleva final.json, manifest.json y PNG usados; no PDF original ni .work.

## Crear el ZIP de la skill para compartir

Con Python y Node.js preparados en esta instalación:

~~~sh
python -B scripts/release.py
python -B scripts/make_bundle.py --output /ruta/absoluta/paes-importer.zip
~~~

El bundle contiene las instrucciones, herramientas y recursos operativos de la skill. No incluye tests, ejemplos sintéticos, informes de desarrollo, configuraciones de CI ni entornos virtuales. Cada anfitrión necesita Python/Node y dependencias disponibles; el ZIP no instala herramientas ni garantiza lectura visual.

## Límites y licencia

Solo M1. Formato histórico paessed-benchmark/0.1.0 compatible con el lector local; no integra PAESSED Web. Las declaraciones de lectura y revisión no autentican comprensión o independencia. Tokens/costo no disponibles son null; no derivar precisión de estados verified.

Pruebas sintéticas no acreditan funcionamiento real de todos los chats/modelos/CLI. [Compatibilidad por entorno](references/hosts.md).

Código MIT. JSZip/KaTeX preservan licencias y atribuciones: [NOTICE](NOTICE.md). No agregar PDFs privados, resultados derivados, recortes de ensayos ni credenciales.
