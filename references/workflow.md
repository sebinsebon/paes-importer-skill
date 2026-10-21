# Operación común

El agente lee e interpreta las fuentes; los scripts preparan, validan y empaquetan. Resuelve herramientas y referencias desde la carpeta de SKILL.md. Python 3.12+, Node.js 18+ y [dependencias instaladas](../README.md#instalación) son requisitos del anfitrión.

## Preparar y observar

1. Comprueba lectura visual real, recortes, ejecución, validación y entrega de archivos. Escribe capabilities.json con pdf_visual, crop, execute, zip, validate, observation y `result_visual:{mode,tool,observation}`. mode es html si puedes inspeccionar el resultado con herramientas existentes; images si usarás capturas observables; unavailable si falta esa vía. Ensaya al comenzar la observación de texto, matemática, tabla e imagen renderizados. No declares comprensión por disponer de un renderizador.
2. En web usa una carpeta temporal y adjunta los archivos, sin preguntar ubicación. En CLI utiliza el destino indicado o pregunta. No sobrescribas ejecuciones.
3. Ejecuta prepare; devuelve output y RUN (output/.work/base):

~~~text
python -B scripts/importer.py prepare --exam ENSAYO.pdf --solution SOLUCIONARIO.pdf --host cli --client CLIENTE --session-id SESION_REAL --destination custom --output-root RUTA_ABSOLUTA --capabilities capabilities.json
~~~

Ajusta host y destino al flujo. Omite --solution si no existe o está integrado; modelo/esfuerzo no observables quedan desconocidos. prepare genera páginas, un índice nativo verificable y geometría de imágenes candidatas, sin transcribir preguntas. Materializa solo recursos necesarios con `materialize-assets --run RUN --asset ID`; los gráficos vectoriales y sus rótulos suelen requerir recorte explícito. Inspecciona la prueba inicial de texto, matemática, tabla e imagen, o conserva la limitación registrada en capabilities-probe.json.

Lee todas las páginas. Construye selection.json con identidad, numeración, páginas, etiquetas, `source_fields` por enunciado/alternativa y **content_inventory** observado: imágenes, tablas y matemática, incluyendo variables y límites completos de figuras. Las tablas conservan dimensiones y encabezados observados. Usa [] únicamente si no hay estructuras. No derives el inventario del JSON transcrito ni omitas páginas que continúan la pregunta.

Si hay pauta, coteja su asociación y cobertura. key.json registra letras y páginas de las justificaciones; una pauta parcial conserva solo las entradas documentadas.

~~~text
python -B scripts/importer.py map --run RUN --selection selection.json
python -B scripts/importer.py route --run RUN --answer-key key.json
python -B scripts/importer.py record-input --run RUN --response direct-input.json
~~~

Omite --answer-key sin pauta. Completa direct-input.template.json con páginas realmente leídas y modo native_pdf o page_images_fallback. Una declaración de lectura no prueba comprensión. El flujo web sin pauta completa solicita consentimiento antes de congelar route.

## Transcribir por lotes

Usa las [interfaces](interfaces.md) y [ejemplos de representación](representation.md). Ejecuta `batch-plan --run RUN --pending-only --context` antes de transcribir: entrega texto y disposición compacta, regiones pertinentes, inventarios y plantillas de respuesta del ensayo y solucionario. Si indica mapeo insuficiente, completa la observación antes de transcribir; no sustituyas cada lote por el PDF entero. Produce hasta cinco preguntas por lote, reduciendo por complejidad o rechazos recientes. Conserva el orden y todas las alternativas.

- Ensayo: enunciado, tablas, figuras, etiquetas y opciones. Una imagen por alternativa gráfica, en su opción.
- Solucionario correspondiente: copia la clave y el desarrollo íntegro, sin resumir ni reformular. Usa prosa y math.latex editables, tablas estructuradas e imágenes para diagramas necesarios. No vuelvas a resolver una explicación existente ni dupliques su transcripción con una captura completa. Genera contenido solo donde falte información; documenta conflictos.
- Matemática: dentro de párrafos usa `math` con `display:false`; fórmulas independientes usan `display:true`. Incluye variables aisladas cuando sean símbolos matemáticos. Conserva párrafos y saltos en los bloques text. Revisa signos, exponentes, índices, radicales, fracciones, unidades y precios. No conviertas automáticamente letras de la prosa.
- Currículo: clasifica cada pregunta por su contenido usando el [catálogo y contrato M1](../shared/references/curriculum-contract.md). Añade curriculum_provenance con razón y evidencia; conserva incertidumbre.

~~~text
python -B scripts/importer.py crops --run RUN --requests crops.json
python -B scripts/importer.py ingest --run RUN --response batch.json
~~~

Las cajas usan puntos PDF, origen superior izquierdo y orientación visible. Si mides sobre una página PNG completa de W×H píxeles, convierte x con ancho_pdf/W e y con alto_pdf/H. No uses coordenadas de una miniatura o imagen desplazada como si fueran del PDF. Incluye vértices, rótulos, flechas y unidades; evita texto o figuras vecinas. No añadas un margen fijo que invada otra opción. Para corregir geometría utiliza un ID nuevo y actualiza la referencia.

Conserva accepted/unchanged; repara solo rejected. Máximo tres intentos por pregunta; después amplía la evidencia o registra el bloqueo. Estos límites son instrucciones del agente, no un contador automático de inferencias. Las explicaciones tomadas de la pauta llevan origin solution; las redactadas por IA, model. El origen de la respuesta se vincula automáticamente a la pauta. Coteja cada lote mientras sus fuentes siguen en contexto.

Para reutilizar texto nativo sin inferencias, ejecuta `source-text --run RUN --source-id solution --page N` (repite --page para páginas necesarias). Devuelve texto y hash del PDF registrado. Conserva su contenido al convertirlo a bloques; contrasta visualmente orden, notación, tablas y asociación. La extracción no infiere claves ni certifica fidelidad, y un PDF escaneado puede devolver texto vacío.

`crops` devuelve assets y warnings. Rechaza bordes que atraviesan caracteres detectables (`CROP_CLIPS_TEXT`) y avisa de texto próximo (`CROP_NEAR_TEXT`). Examina esos avisos: no amplíes cajas automáticamente hacia otra pregunta. Este control no detecta por sí solo figuras equivocadas, texto rasterizado o etiquetas completamente alejadas; el cotejo visual sigue siendo obligatorio.

## Comparar antes de entregar

~~~text
python -B scripts/importer.py review --run RUN
python -B scripts/importer.py check-template --run RUN
python -B scripts/importer.py record-check --run RUN --response cotejo.json
~~~

**Inspecciona primero el HTML devuelto por review con tus herramientas existentes.** Compara cada pregunta renderizada y recorte con su página, incluyendo solucionario. Naranja delimita preguntas; rojo, recortes; azul, estructuras observadas. Comprueba figuras completas, rótulos, unidades y ubicación de cada alternativa.

Conserva un artefacto visual también si inspeccionas HTML: `record-browser-capture` incorpora una captura atribuida de tus herramientas. Leer HTML como texto no habilita cotejos. `capture-review --run RUN` obtiene capturas con Playwright opcional y un navegador externo; `--executable-path RUTA` selecciona uno existente. No es necesario instalarlo si el anfitrión ya captura el navegador. Nunca añadas Chromium al bundle ni descargues navegadores automáticamente. Si no puedes obtener u observar capturas, informa la limitación y conserva revisión pendiente; mirar solamente JSON o imágenes del PDF no inspecciona el resultado.

Si el anfitrión bloquea file://, el transporte auto intenta cargar en memoria el mismo HTML y sus recursos locales, sin servidor ni acceso de red. `--transport memory` selecciona esa vía directamente; `--transport file` conserva solo la vía local. Ambas mantienen hashes y recibos de captura. El bloqueo del navegador completo puede impedir ambas.

Completa los seis cotejos de la plantilla con pass/fail/unresolved y evidencia que cubra geométricamente las regiones de cada campo y sus páginas. Adjudica individualmente los diagnósticos pendientes con razón y evidencia de todas sus páginas/regiones. Conserva render_review y registra `visual_observation:{mode,tool,observation,capture_receipt}` por pregunta, tanto para html como images. Los hashes vinculan la vista y capturas al contenido vigente, sin demostrar que alguien las revisó. Tras cambios, usa review/capture-review con `--question ID` o `--pending-only` y renueva únicamente cotejos afectados; las preguntas intactas conservan su vista y constancias.

Con pauta completa, resuelve fallos y pendientes antes de empaquetar. Si falta evidencia, conserva la ejecución e informa que está incompleta. En otros flujos se conservan pendientes explícitos, incluyendo respuestas cuya resolución se rechazó.

~~~text
python -B scripts/importer.py validate --run RUN
python -B scripts/importer.py pack --run RUN
python -B scripts/importer.py inspect --package ARCHIVO.paessed
~~~

Si route exige revisión independiente, usa [auditoría](audit.md) antes de publicar. La autorrevisión mantiene pending/provisional; no crea estados reviewed/verified.

`quality.gold_eligible` exige contenido completo, los seis cotejos aprobados, evidencia de asociación y observación visual vigente del resultado y sus fuentes. Gold acredita ese alcance de fidelidad declarado; no certifica la corrección matemática del autor. No necesita una segunda resolución. Una clave con procedencia o un paquete estructuralmente válido no obtiene Gold automáticamente.

Entrega .paessed con final.json 0.2.0, manifest.json 0.1.0 y recursos usados; ZIP con bytes idénticos. Las vistas, PDFs y trazas permanecen fuera. Informa cobertura, procedencia y pendientes.

## Reanudar y herramientas opcionales

`resume --run RUN` comprueba fuentes, release y configuración y devuelve preguntas aceptadas, pendientes de contenido, solución o cotejo, rechazos y siguiente acción. Usa `batch-plan --run RUN --pending-only --context` para transcribir solo contenido/soluciones pendientes y `check-template --run RUN --question ID` repetido para cotejos pendientes. Continúa los lotes sin pedir instrucciones nuevas mientras la sesión lo permita. Guarda cada lote con ingest; exporta un checkpoint autosuficiente si debes trasladarlo. Python no inicia ni prolonga sesiones de IA.

`ingest` archiva cada respuesta y sus rechazos en reports/ingest, incluso cuando ninguna pregunta es aceptada. Si el error está en el inventario observado, corrígelo con [repair-map](advanced.md#corregir-observaciones-del-mapa); no inventes fórmulas para satisfacerlo. `fail --run RUN --reason MOTIVO` conserva una ejecución fallida. Para otra release utiliza la [adopción explícita compatible](interfaces.md#plan-de-lotes-y-recuperación) en carpeta nueva o inicia otra ejecución; nunca edites hashes manualmente. repair-provenance amplía continuaciones documentadas sin cambiar fuente, clave, página original ni contenido aceptado.

Consulta [herramientas avanzadas](advanced.md) solo para transporte PowerShell, planificación de lotes, extracción draft v1, revisión independiente o mediciones de proveedor.
