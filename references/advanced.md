# Herramientas opcionales

Consultar solo la sección necesaria. La operación habitual está en [workflow](workflow.md).

## Transporte JSON PowerShell

El contenido se escribe mediante un serializador UTF-8 y luego se transporta como bytes, sin interpolarlo en comandos. Usa scripts/write_json.ps1 -InputPath ARCHIVO -OutputPath DESTINO -WorkspaceRoot CARPETA_SELECCIONADA, o run.ps1 -JsonInputPath ARCHIVO -JsonOutputPath DESTINO -WorkspaceRoot CARPETA_SELECCIONADA. WorkspaceRoot debe ser explícito y externo a la skill. Requiere padre existente, rechaza enlaces, raíz del sistema, escape del workspace, JSON inválido y sobrescritura. No modifica el archivo origen.

## Plan de lotes y recuperación

`batch-plan --run RUN --pending-only --context --batch-size 5 --max-characters 24000` devuelve batches, question_index y page_index conservando el candidato. Puede generar o renovar el índice nativo verificable. Parte de selección/inventario y contexto de pauta congelados, incluso cuando el candidato inicial todavía no tiene regiones transcritas. Cada lote conserva IDs, fuentes, páginas, assets, texto/disposición compacta, plantillas y hashes. El límite de caracteres usa el contexto fuente real, sin estimar tokens; una pregunta excesiva queda íntegra y sola. Complejidad y rechazos recientes reducen los límites. Consulta [recuperación portable](interfaces.md#plan-de-lotes-y-recuperación) para exportar/adoptar checkpoints.

`ingest` devuelve accepted, rejected (con motivo) y unchanged por pregunta. Conservar las aceptadas; regenerar únicamente las rechazadas. Un reenvío idéntico conserva estados y razones vigentes. Máximo tres intentos por pregunta dentro del presupuesto disponible; después ampliar evidencia, dejar pending/unresolved explícito o registrar fail. No repetir lotes aprobados para aparentar reparación.

## Corregir observaciones del mapa

Si una observación congelada exige una variable, tabla o figura inexistente, vuelve a mirar su fuente y usa `repair-map --run RUN --response correccion.json`. La entrada contiene `reason` no vacío y `questions` con los registros completos corregidos de selection.json, o `solution_entries` con las entradas completas corregidas de answer-key-map.json.

En preguntas solo pueden cambiar content_inventory, source_fields, regions, field_regions, mapping_pending y justificaciones shared_regions; en soluciones, content_inventory y observation. No permite cambiar identidad, numeración, etiquetas ni clave. Para ampliar páginas de continuación se usa repair-provenance con evidencia. Conserva versiones y solicitud, actualiza hashes mediante el checkpoint existente y retira solo cotejos/vistas afectados. No modifica su contenido ni aprueba la corrección: revisa y renueva sus cotejos. Si cambia la fuente o la identidad, inicia otra ejecución.

## Lectura ciega 0.2.0

La verificación comienza con input.json de stage source-reading y reading-template.json. Completar únicamente id/source_id/number/regions/stem/options/evidence y reviewer identificado. No añadir answer, explanation ni decisiones del productor. `verify commit-reading --run VERIFICATION --batch batch-01 --response lectura.json` congela lectura y hashes antes de generar el paquete de comparison y report-template.json. El informe posterior debe conservar reading_sha256 y el mismo reviewer; la independencia continúa siendo una declaración, no aislamiento autenticado.

## Selección independiente de revisión

`route --run RUN --subagents --review-all` selecciona todas las preguntas para revisión independiente CLI, incluso si tienen pauta. Para un subconjunto usar `--review-question ID` repetido. Ambos modos de selección son excluyentes y requieren capacidades/contexto independientes; el modo web no simula agentes. Sin selección explícita se conserva el subconjunto por resolver existente. Resolver y revisar son decisiones separadas; las claves de pauta permanecen vinculadas y los conflictos se documentan.

## Medidas de proveedor

`record-usage --run RUN --response uso.json` acepta `{run_id, events:[{event_id, usage_source, input_tokens, output_tokens, cached_input_tokens, cost, currency, duration_seconds}]}`. usage_source identifica el recibo real. Cada evento corresponde a una llamada, sin agregados superpuestos; cached_input_tokens registra la parte cacheada cuando el proveedor la expone, sin sumarla de nuevo a input_tokens. Mantener null para medidas no expuestas; currency es obligatorio con costo medido. El mismo event_id idéntico es idempotente; datos distintos se rechazan. No duplicar llamadas de agentes en una suma del coordinador. Los totales incompletos permanecen null, con subtotales conocidos separados. provider_receipts_count cuenta recibos; total_provider_calls desconocido permanece null incluso sin recibos.

El `run.json` de publicación conserva `usage` con alcance `production_only`; `usage_scopes` separa producción y verificación. El agregado mantiene null si falta una medición. La duración acumulada de llamadas no es tiempo de pared. No repitas medidas de verificación en los recibos de producción.

## draft.json v1 del extractor previo

Después de `prepare`, `map` y `route`, una ejecución puede incorporar una extracción v1 existente:

~~~text
python -B scripts/importer.py adapt-draft --run RUN --draft /ruta/draft.json
~~~

El adaptador exige un candidato mapeado todavía intacto y cubrir exactamente la selección congelada completa. Valida el draft y sus recursos, vincula por SHA-256 exacto y número de páginas de fuente, y por número original de pregunta. Comprueba toda la conversión antes de aplicar cambios: asociaciones ambiguas o estructuras sin conversión segura fallan atómicamente y explican el bloqueo. Conserva copia del draft, recursos y evidencia de procedencia en `.work`, fuera del paquete final. Los contextos compartidos representables se incorporan a cada pregunta que los referencia conservando su procedencia. Los gráficos conservan su `source_bbox` y origen superior izquierdo al asociarse con el recorte de fuente; no se invierte el eje vertical ni se inventa geometría.

`complete` y `structural_fidelity.status=verified` son estados del extractor, no aprobación independiente. La conversión no los promueve a `reviewed` o `verified`. Respuestas, explicaciones y currículo no demostrados permanecen pendientes; el anfitrión debe completarlos mediante `ingest`, lectura registrada, cotejos y la auditoría que exija `route`. Conservar el draft interno no sustituye el `.paessed` 0.2.0 final.
