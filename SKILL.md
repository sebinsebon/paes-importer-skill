---
name: paes-importer
description: Importa ensayos PAES Matemática M1 PDF, con solucionario opcional, a .paessed 0.2.0 y ZIP idéntico en chat web o CLI, con transcripción estructurada y cotejo visual completo.
license: MIT
metadata:
  requires: Lectura visual, bundle completo, Python 3.12+, Node.js 18+ y entrega de archivos.
---

# Importador PAESSED M1

## Primero: confirmar el entorno

Antes de abrir referencias, flujos o PDFs, comprueba si el usuario ya indicó **Chat Web** o **CLI / agente de terminal** en esta conversación. Si lo indicó, usa esa respuesta sin volver a preguntar. Si no lo indicó o es ambiguo, pregunta: **«¿Dónde estás usando la skill: Chat Web o CLI / agente de terminal?»** Ofrece esas dos opciones y espera su respuesta antes de continuar. Mientras esperas, lee únicamente este SKILL.md; no deduzcas el entorno por las herramientas disponibles.

## Elegir un solo flujo

Localiza el bundle completo, el ensayo y su solucionario, si existe. Comprueba identidad, numeración y cobertura de la pauta mediante lectura real. Si solo hay respuestas, solicita el ensayo. Una pauta ambigua no cuenta como cobertura válida; una parcial conserva sus entradas asociadas.

| Entorno de trabajo | Cobertura válida de la pauta | Leer |
| --- | --- | --- |
| Chat web | Todas las preguntas | [01 Chat con solucionario](flows/01-chat-con-solucionario/WORKFLOW.md) |
| CLI | Todas las preguntas | [02 CLI con solucionario](flows/02-cli-con-solucionario/WORKFLOW.md) |
| CLI | Ausente o parcial | [03 CLI sin solucionario completo](flows/03-cli-sin-solucionario/WORKFLOW.md) |
| Chat web | Ausente o parcial | [04 Chat sin solucionario completo](flows/04-chat-sin-solucionario/WORKFLOW.md) |

Lee solo el flujo elegido y sus referencias necesarias. Un chat web con ejecución de código sigue siendo web.

## Resultado esperado

Conserva enunciados, orden, alternativas, tablas, figuras y matemática del ensayo. Usa el solucionario correspondiente para respuestas y desarrollos: explicaciones como texto y matemática editables; imágenes para diagramas necesarios. La pauta no reduce el cotejo del ensayo.

En prosa `text.text`, conserva negrita con `<b>…</b>` y cursiva con `<i>…</i>`, también en alternativas, celdas y solucionarios. Solo pares completos, sin atributos y dentro del mismo bloque; pueden anidarse. Consulta [representación](references/representation.md#negrita-y-cursiva). Usa `source-text` para consultar `styled_text`, `runs` y `warnings` del texto digital y coteja siempre con la página: son indicios de fuente, no una transcripción de fórmulas o tablas. Si el formato es incierto, conserva todas las palabras y espacios y registra `TEXT_FORMAT_PENDING` en `issues` hasta revisarlo visualmente. En escaneos no inventes formato por OCR, mayúsculas o contexto. Ningún indicio automático permite declarar Gold ni omitir el cotejo.

Transcribe íntegro el desarrollo existente, sin resumir, reformular ni resolverlo de nuevo. Matemática dentro de párrafos: `math` con `display:false`; fórmulas independientes: `display:true`. Conserva párrafos y saltos del original. Usa IA para resolver o explicar solo lo que falte; documenta conflictos con la fuente.

**Gold significa fidelidad visual completa al ensayo y al solucionario disponible**, con asociación correcta, integridad y procedencia. Exige cotejos vigentes de todas las preguntas; una clave por sí sola no basta. No exige segunda resolución matemática ni estados `verified`.

Compara visualmente **cada pregunta, alternativa y recorte** con su fuente antes de entregar. Primero inspecciona el HTML con tus herramientas; si no puedes, usa capturas observables. Si tampoco puedes obtenerlas e inspeccionarlas, informa la limitación y conserva revisión pendiente. Las dependencias de captura son opcionales. Con solucionario completo, repara los pendientes dentro de la ejecución; si falta evidencia, conserva avances e informa que está incompleta. No declares `verified` mediante autorrevisión.

Emite contenido **0.2.0**, con currículo M1 y procedencia, dentro de `.paessed` y ZIP idénticos. En **Chat Web adjunta ambos directamente**, sin preguntar carpeta. En **CLI** usa el destino indicado o pregunta Documentos/Descargas/ruta personalizada. Esquemas y validadores se resuelven dentro del bundle.

Continúa los lotes pendientes mientras la sesión lo permita, guardando cada lote con `ingest`. Usa `resume` y `batch-plan --pending-only` al retomar; conserva lo aceptado. Si la sesión se interrumpe, entrega el estado y la carpeta recuperable. La skill no puede prolongar una sesión ni ejecutar un agente fuera de ella.
