# Interfaces de intercambio

Los ejemplos son ficticios. Los scripts no detectan semánticamente preguntas o correspondencia: el anfitrión produce estas entradas a partir de las fuentes reales y documenta la observación.

## selection.json

~~~json
{"title":"Ejemplo ficticio M1","observed_question_count":1,"observation":"Una pregunta ficticia con tabla y dos alternativas","expected_questions":[{"id":"exam-q1","source_id":"exam","number":"1","page":2,"option_labels":["A","B"],"regions":[{"page":2,"bbox":[20,40,500,650]}],"source_fields":{"stem":[{"page":2,"bbox":[40,60,450,260]}],"options/A":[{"page":2,"bbox":[40,300,250,340]}],"options/B":[{"page":2,"bbox":[40,360,250,400]}]},"content_inventory":[{"field":"stem","type":"math","count":1,"symbols":["m","n"],"regions":[{"page":2,"bbox":[40,60,450,100]}]},{"field":"stem","type":"table","count":1,"shape":{"rows":2,"columns":2,"headers":["m","n"]},"regions":[{"page":2,"bbox":[40,120,450,260]}]}]}]}
~~~

IDs seguros y únicos; número como string y página física desde 1. El total observado coincide con el mapa, pero ese control no detecta por sí solo una pregunta omitida del PDF. Las preguntas pertenecen a exam. Registra option_labels en orden y todas las páginas esenciales. `source_fields` contiene `stem` y `options/ETIQUETA`, cada uno con regiones esenciales completas: texto, números, rótulos y unidades. Incluye todas las páginas de un campo que continúa. Estas regiones también delimitan dónde puede permanecer su recorte, sin invadir una alternativa vecina. Las regiones del candidato y la unión de citas deben cubrirlas. `field_regions` permite requisitos adicionales por dimensión de cotejo; no sustituye source_fields.

Si no puedes observar las alternativas o regiones, usa `mapping_pending:true`, contenido unresolved y entrega parcial. No lo uses para aprobar una pregunta completa sin mapa.

`content_inventory` se observa desde el PDF antes de transcribir y queda congelado fuera de final.json. Agrupa field (`stem` u `options/ETIQUETA`) y type (`image`, `table`, `math`), count mínimo positivo y regiones completas. `[]` declara ausencia observada de estructuras. Las tablas editables registran `shape:{rows,columns,headers}`; para varias, `shapes:[...]` en orden. Las figuras requieren un recurso de su campo que contenga lo observado y permanezca dentro de source_fields.

Para matemática, `symbols` enumera variables de una letra. Cada aparición matemática se representa mediante math, también dentro de la prosa. Si una letra aislada es una abreviatura legítima, `text_exceptions:[{symbol,reason,regions}]` documenta la excepción localizada antes de congelar el mapa; no convierte la prosa automáticamente. El inventario detecta omisiones declaradas, sin demostrar comprensión.

Un bloque unresolved explícito conserva el campo pendiente cuando falta evidencia legible. No satisface una entrega completa con pauta; los otros flujos pueden conservarlo en un paquete parcial.

## key.json

~~~json
{"exam_sha256":"HASH_REAL_DEL_EXAMEN", "match":{"status":"matched","reason":"Identidad y numeración contrastadas","evidence":[{"source_id":"solution","page":1,"observation":"Identificación del mismo ensayo"}]},"entries":[{"question_id":"exam-q1","label":"A","source_id":"solution","page":2,"observation":"Fila 1 de la pauta","has_explanation":false}]}
~~~

Con pauta integrada, source_id es exam. Registra únicamente entradas legibles y asociadas; duplicados, preguntas inexistentes, páginas inválidas y asociación no matched se rechazan. Una pauta parcial es válida. has_explanation=true permite procedencia solution para una explicación tomada de esa página. Si la justificación está en otra página, registra esa página en la entrada y describe dónde aparece también la respuesta.

Si la respuesta/desarrollo ocupa varias páginas, añade `pages:[2,3]` a la entrada, incluyendo su `page` principal. Se validan páginas físicas distintas y la vista incluye todas ellas; los cotejos de respuesta/explicación deben cubrir todas las páginas registradas de esa fuente.

Con `has_explanation:true`, añade `content_inventory` observado del desarrollo, con `field:"explanation"`, `source_id` real y las mismas estructuras de tabla, matemática o imagen. Usa `[]` solo para desarrollo observado sin esas estructuras. Este inventario queda vinculado a la pauta congelada.

## batch.json

~~~json
{
  "run_id":"ejemplo-ficticio",
  "questions":[{
    "id":"exam-q1","source_id":"exam","number":"1",
    "regions":[{"page":2,"bbox":[20,40,500,650]}],
    "stem":[
      {"type":"text","text":"Según la tabla, calcula "},
      {"type":"math","latex":"\\frac{m}{n}","display":false},
      {"type":"text","text":"."},
      {"type":"table","rows":[
        [[{"type":"math","latex":"m","display":false}],[{"type":"math","latex":"n","display":false}]],
        [[{"type":"math","latex":"6","display":false}],[{"type":"math","latex":"3","display":false}]]
      ]}
    ],
    "options":[
      {"label":"A","blocks":[{"type":"math","latex":"2","display":false}]},
      {"label":"B","blocks":[{"type":"math","latex":"3","display":false}]}
    ],
    "answer":{"label":"A","status":"provisional","origin":"model","source_ref":null},
    "explanation":{"blocks":[{"type":"math","latex":"\\frac{6}{3}=2","display":true}],"status":"provisional"},
    "fidelity":{"status":"pending","review_ref":null},"issues":[],
    "curriculum":{"eje":"Números","subeje":"Conjunto de los números enteros y racionales","en_temario":"si"}
  }],
  "explanation_provenance":{"exam-q1":{"origin":"model"}},
  "curriculum_provenance":{"exam-q1":{"reason":"La operación central es división de enteros","evidence":[{"source_id":"exam","page":2,"observation":"Cociente de valores enteros de la tabla"}]}}
}
~~~

El ejemplo es una pregunta completa del [contrato](../shared/references/content-contract.md); sustituye run_id, identidad, geometría y contenido por los de la ejecución real. Las figuras se incorporan como en [representación](representation.md#opciones-gráficas), tras crear sus recursos. Cada explicación no vacía requiere procedencia; las redactadas por IA usan model incluso con respuesta de pauta. Fidelidad pending; respuesta/explanation provisional o missing. Las respuestas de pauta se vinculan a su entrada congelada durante ingest.

## crops.json

~~~json
[{"id":"grafico-q1","source_id":"exam","page":2,"bbox":[40,100,300,260],"role":"asset"}]
~~~

Puntos PDF, origen superior izquierdo y orientación visible. Conservar figura completa, unidades y etiquetas; para alternativas visuales, asociar cada una a su etiqueta. Los bloques image referencian el id del recurso. Un crop de auditoría usa role evidence; no se incorpora al paquete por defecto. IDs nuevos; no sobrescribir recursos con distinta geometría.

En una página PNG completa de tamaño W×H, `x_pdf = x_pixel * ancho_pdf / W`, `y_pdf = y_pixel * alto_pdf / H`. Consulta ancho/alto y rotación en catalog.json; no mezcles coordenadas de miniaturas con puntos PDF. Verifica el recorte en `review` antes de dar pass.

## review

`review --run RUN` genera una carpeta nueva bajo `.work/base/reviews/` con HTML local, renderer, KaTeX, páginas de fuente, cajas de pregunta/recorte/inventario y recursos usados. Incluye las páginas de pauta y explicación registradas aunque no haya imágenes del solucionario. Devuelve html y render_review; abre la vista y compara cada pregunta completa.

`render-reviews.json` guarda referencias a vistas; cada fila de check-template incorpora render_review `{path,sha256}`. Conserva ese campo al registrar cotejos. Sus hashes vinculan contenido, solución, imágenes y archivos de la vista. Una edición exige generar una vista nueva y renovar los cotejos afectados. El HTML, las fuentes y las constancias quedan fuera del paquete. Esta operación no acredita que alguien abrió la vista.

Primero inspecciona el HTML renderizado con tus herramientas. Tanto `html` como `images` requieren una constancia de un artefacto visual; leer el archivo HTML como texto no basta. `capture-review --run RUN` usa la dependencia opcional y un navegador externo; `--executable-path RUTA` selecciona un navegador existente. No instala ni descarga navegadores. `--transport memory` sirve los mismos archivos en memoria; `auto` lo intenta si el acceso local está bloqueado. Comprueba imágenes, errores y una prueba observable de texto, matemática, tabla e imagen antes de capturar preguntas. Devuelve `capture_receipt:{path,sha256}`. Si falla, conserva la limitación y las capturas parciales válidas.

`review --question ID` conserva las vistas vigentes de las demás preguntas. `capture-review --question ID --pending-only` reutiliza capturas válidas y reanuda parciales de la misma vista. `--resume-receipt ARCHIVO` admite un JSON con la referencia `{path,sha256}` de una captura previa. Una captura externa de navegador se incorpora mediante `record-browser-capture --run RUN --question ID --image PNG --tool HERRAMIENTA --observation OBSERVACION`. La constancia vincula el archivo, vista y atribución; la observación efectiva sigue siendo responsabilidad del revisor.

## cotejo.json

Usa check-template para hashes de versión. La raíz contiene run_id, independent=false, session_id del productor y questions. Cada fila: id, content_sha256, solution_sha256 y checks con stem/options/assets_math/answer/explanation/consistency. Cada check: status pass/fail/unresolved, reason, field_paths y evidence [{id,sha256,observation,fields}] de imágenes enumeradas en el candidato. Copiar field_paths de la plantilla; cada cita.fields nombra las rutas que esa imagen realmente cubre. La unión de citas debe cubrir exactamente las rutas requeridas: opciones por etiqueta, fórmulas/figuras/tablas por ruta. Un hash de portada o una imagen de otra pregunta no bastan. La fuente de la pauta/solución se comprueba por separado para answer/explanation. No describe revisión independiente.

Cada fila conserva `render_review` y añade `visual_observation:{mode,tool,observation}`. mode es `html`, `images` o `unavailable`. En ambos modos visuales añade `capture_receipt` dentro de visual_observation. La constancia debe corresponder a esa vista y pregunta; generar capturas no acredita su inspección. `unavailable` no permite aprobar el cotejo.

`check-template` prellena referencias y citas, manteniendo los veredictos `unresolved` y observaciones vacías. `source_diagnostics` localiza estructuras nativas no inventariadas, campos de página completa, solapamientos, crops y posibles pérdidas matemáticas o de desarrollo. Para aprobar, cada entrada de `diagnostic_review` requiere su `diagnostic_sha256` vigente, `status:addressed` o `dismissed`, una razón y `evidence` con id, hash y observación de la fuente/página correspondiente. Una señal automática no confirma un defecto ni fidelidad. Corregir el contenido o mapa exige regenerar plantillas y evidencia afectada.

Con pauta completa, validate/pack rechazan cotejos fallidos o pendientes, contenido sin resolver, respuestas/explicaciones faltantes y mapeo/currículo incompletos. Una respuesta provisional con cotejo completo sigue siendo publicable; no exige ni inventa verified. Los otros flujos conservan paquetes parciales explícitos.

## Estados y metadatos

Nuevos finales usan schema_version 0.2.0; se conserva lectura histórica de 0.1.0. run añade host, processing_mode (answer-key/mixed/solve/partial-pending), review_mode (self/independent) y answer_key_sha256. El ledger de ejecución conserva destino real, sugerencia de descarga, procedencia de explicaciones y subconjunto de auditoría.

source_ref de una respuesta de pauta apunta a .work/base/answer-key-map.json#ID. La evidencia y los informes permanecen en el directorio de ejecución; el ZIP autónomo contiene el contenido renderizable y hashes de recursos, no promete llevar toda la auditoría. Para compartir trazabilidad, compartir expresamente los informes necesarios por separado.

El cotejo del productor mantiene estados provisionales/pending. reviewed/verified exige informe independiente, evidencia y decisiones vinculadas. No son equivalentes a una pauta oficial o acierto garantizado. Si hay discrepancia con pauta, conserva su origen y la incidencia; no la sustituuyas silenciosamente.

Gold se informa en `run.quality.gold_eligible`: requiere fidelidad visual completa y evidencia vigente, sin exigir reviewed/verified ni resolución matemática independiente. `origin:answer-key` identifica procedencia, no revisión. Una respuesta con fuente puede seguir siendo provisional y ser elegible para Gold cuando todos los cotejos estén completos. Una revisión independiente de una solución existente verifica su transcripción y asociación; no garantiza que el autor resolviera correctamente.

Si has_explanation es true, ingest exige origin solution para una explicación no vacía. Copia el desarrollo completo, incluyendo matemática, tablas e imágenes; no lo reemplaces por una explicación del modelo. Las conjunciones/preposiciones españolas a/y/e/o/u no son automáticamente variables por compartir letra. Las apariciones ambiguas dentro de prosa requieren cotejo visual; las expresiones y variables matemáticas van en math inline.


## Contrato curricular 0.2.0

Sigue el [contrato curricular normativo](../shared/references/curriculum-contract.md) y su catálogo M1. Cada lote entrega curriculum y curriculum_provenance, como en el ejemplo completo. Clasifica también preguntas pendientes de respuesta; conserva incertidumbre y estados parciales definidos por el contrato.



## Transporte JSON PowerShell

Consulta [esta interfaz opcional](advanced.md#transporte-json-powershell).

## Plan de lotes y recuperación

Consulta [esta interfaz opcional](advanced.md#plan-de-lotes-y-recuperación).

`prepare` guarda `native-source-index.json` con texto, glifos, posiciones y objetos ligados a los hashes de fuentes y extractor. `source-text --run RUN --source-id exam --page 2 --regions REGIONES.json` consulta regiones `{page,bbox}` sin volver a extraer el PDF. Es una ayuda de lectura, pendiente de contraste visual.

`source-text` devuelve texto por defecto. `--layout compact` añade líneas, geometría, estilos tipográficos compartidos y señales pendientes; `--layout full` expone glifos individuales. El índice conserva siempre el detalle completo. Los lotes usan disposición compacta para evitar repetir metadatos tipográficos por carácter sin perder texto seleccionado.

Las imágenes nativas permanecen como geometría en `catalog.asset_candidates` hasta necesitarlas. `materialize-assets --run RUN --asset ID` materializa únicamente candidatas seleccionadas y conserva identidad de fuente/geometría; `--asset` se repite para varias. Para compatibilidad, `prepare --eager-assets` materializa todas. Los recortes nuevos siguen usando `crops`. Las señales de tipografía y elementos repetidos permanecen pendientes; no se suprime automáticamente un logo, encabezado o contenido esencial.

`batch-plan --run RUN --pending-only --context` incluye fuentes, texto nativo, disposición, recursos, inventarios del ensayo y solucionario, valores permitidos y plantillas de respuesta. El presupuesto usa caracteres realmente serializados, incluidas explicaciones; no estima tokens. Una pregunta excesiva queda sola y se señala, sin truncar sus fuentes. Se mantienen cinco preguntas como máximo habitual, reduciendo por complejidad y rechazos recientes: tras uno se limita a dos; tras dos, a una. Una aceptación limpia el historial activo de rechazo de esa pregunta. Completa y guarda cada lote con `ingest`, inspecciona aceptados/rechazados y reintenta únicamente pendientes. Los campos de observación vacíos y los bloques unresolved requieren lectura real.

La procedencia `solution` puede añadir `regions:[{page,bbox}]` cubriendo todas sus páginas congeladas. Permite comparar cobertura del desarrollo original; las diferencias permanecen pendientes para adjudicación visual. Se conserva matemática inline y de bloque sin resolver ni reformular el original.

`export-checkpoint --run RUN --output ARCHIVO_NUEVO.zip` exporta fuentes verificadas, estado y evidencia referenciada. El ZIP se escribe fuera del run y no borra históricos. `adopt-checkpoint --checkpoint ZIP --legacy-bundle RUNTIME_ANTERIOR --output-run CARPETA_NUEVA` verifica ambos runtimes y fuentes, recupera transacciones y conserva contenido aceptado, incluso parcial. Requiere protocolo portable compatible; no migra contratos incompatibles ni sobrescribe carpetas. `repair-provenance --run RUN --response CAMBIOS.json` amplía páginas de continuación de entradas existentes; conserva fuente, página original, clave y contenido, invalidando solo cotejos afectados. Cada cambio incluye question_id, old_pages, add_pages, reason y evidence con source_id/page/evidence_id/sha256/observation por página añadida. No existe límite artificial de tres páginas.

## Lectura ciega 0.2.0

Consulta [esta interfaz opcional](advanced.md#lectura-ciega-020).

## Selección independiente de revisión

Consulta [esta interfaz opcional](advanced.md#selección-independiente-de-revisión).

## Medidas de proveedor

Consulta [esta interfaz opcional](advanced.md#medidas-de-proveedor).

## draft.json v1 del extractor previo

Consulta [esta interfaz opcional](advanced.md#draftjson-v1-del-extractor-previo).
