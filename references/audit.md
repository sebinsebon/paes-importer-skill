# Auditoría CLI independiente

Para independent_question_ids congelados de la ruta. Distinguir preguntas por resolver de preguntas por revisar: la pauta evita resolver de nuevo sin motivo, pero no sustituye revisión de transcripción o figuras. La selección de revisión puede incluir preguntas con pauta usando route --subagents --review-all o --review-question ID repetido; el resto conserva procedencia y alcance de autorrevisión explícitos.

~~~text
python -B scripts/importer.py baseline --run RUN
python -B scripts/importer.py verify prepare --run RUN --session-id SESION_COORDINADOR_REAL
~~~

RUN apunta a la producción base. baseline valida lectura, cobertura, cotejos y paquete; el control queda en .work/base. La verificación queda en .work/verification. No se publica aún el resultado.

Cada lote tiene hasta diez preguntas del subconjunto y páginas fuente necesarias. En 0.2.0 comienza con input.json de source-reading y reading-template.json: solo identidad/regiones y fuente del ensayo, sin transcripción del productor, clave ni explicación. Delegar en agentes con contexto nuevo, sin heredar historial. Entregar únicamente su paquete de lote y estas instrucciones/contrato; no PDF completo, otros lotes ni respuestas externas. Hasta tres agentes simultáneos cuando se pueda. La limitación es de protocolo, no una afirmación de aislamiento de archivos.

Primero cada agente transcribe enunciado y alternativas desde la fuente, registra evidencia y guarda lectura.json a partir de reading-template.json, con contexto nuevo identificado. El coordinador ejecuta:

~~~text
python -B scripts/importer.py verify commit-reading --run VERIFICATION --batch batch-01 --response lectura.json
~~~

Solo tras ese compromiso se revela la propuesta y aparece report-template.json, junto con páginas documentadas de pauta/desarrollo y recursos de explicación. El agente compara su lectura congelada y contrasta respuesta y desarrollo con sus fuentes correspondientes; resolver correctamente desde el ensayo no demuestra que transcribió fielmente el solucionario. Mantiene reading_sha256 y reviewer. Para finales históricos 0.1.0 se conserva el protocolo antiguo, cuyo paquete revela la propuesta desde el inicio; no acreditarlo como lectura ciega. Conserva contenido correcto. Seis checks: stem/options/assets_math/answer/explanation/consistency. Cada juicio pass/error necesita motivo y evidence [{path,sha256,observation}]; answer/explanation requieren evidencia de la fuente registrada cuando proceden de pauta/solucionario. La falta de evidencia queda unresolved. Registra reviewer real, fresh_context=true solo si corresponde, solución independiente, changes con field/before/after/reason/evidence y post_checks. Campos modificables: stem/options/regions/answer/explanation/issues/curriculum. Un cambio curricular necesita razón y evidencia; cambios de contenido requieren renovar o invalidar la clasificación dependiente. No cambia identidad, fuente ni recursos inventados. Aplica [fidelidad estructural](../shared/references/content-contract.md).

Si falta contexto visual, solicitar una ampliación concreta al coordinador. En source-reading conservar la falta de evidencia y no revelar la propuesta prematuramente; add-evidence pertenece a la etapa de comparación posterior:


~~~text
python -B scripts/importer.py verify add-evidence --run VERIFICATION --batch batch-01 --requests evidencia.json
~~~

requests es [{id,question_id,source_id,page,bbox,role,reason}]; source_id identifica ensayo o solucionario registrado y bbox puede omitirse para página completa. Ejecutar antes del informe final; regenera los hashes de comparación preservando reading_sha256, reviewer e historia. Nunca reenviar el PDF completo por comodidad.

~~~text
python -B scripts/importer.py verify check --run VERIFICATION
python -B scripts/importer.py verify decisions --run VERIFICATION
~~~

Completar decisions-template.json como decisions.json. El coordinador identifica una sesión distinta a los verificadores y decide cada cambio con accept true/false, motivo, hash del informe y evidencia citada. Revisa realmente la fuente; no acepta todo automáticamente. Cambios dudosos se rechazan y quedan pendientes. Una discrepancia confirmada que afecte contenido o clave no puede desaparecer como entrega completa; el informe conserva severidad, cobertura y decisión.

~~~text
python -B scripts/importer.py verify consolidate --run VERIFICATION --decisions decisions.json
~~~

Aplica solo cambios aceptados y publica el resultado en la raíz de ejecución. Promueve reviewed/verified únicamente cuando pasan las comprobaciones posteriores, las correcciones fueron aceptadas y la solución independiente coincide. Mantiene baseline exacto, informes y decisiones. La comparación matemática externa no forma parte de esta etapa.

Conserva coordinator-usage.json si hay medidas reales disponibles; null si no existen. scope coordinator_only o verification_including_agents evita doble conteo. La plantilla enumera campos. No volver a consolidar, sobrescribir informes o modificar una producción empaquetada. Una nueva revisión exige nueva ejecución. Reanudar awaiting_reviews consiste en conservar informes previos y completar faltantes después de check; no hay agente autónomo en Python.
