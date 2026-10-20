# Chat web sin solucionario completo

Sigue la [operación común](../../references/workflow.md), las [interfaces](../../references/interfaces.md) y el [contrato de contenido](../../shared/references/content-contract.md).

- Prepara con `--host web` en una carpeta temporal. No preguntes destino local. Conserva la pauta parcial correspondiente.
- Después de `map`, `route` devuelve `needs_consent` si faltan respuestas. Pregunta: «No encontré un solucionario válido para todas las preguntas. ¿Quieres usar el modo experimental para resolver las pendientes? Las respuestas y explicaciones pueden contener errores». Espera la elección **Continuar** o **Dejar respuestas pendientes** y repite con `--experimental yes` o `no`.
- Resuelve solo `solve_question_ids`. Si rechazó, conserva `pending_question_ids` con respuesta y explicación `missing`.
- Transcribe y clasifica también las preguntas pendientes. Usa `review` y coteja todas las preguntas y recortes; registra dudas reales. No simules independencia en la misma conversación.
- Ejecuta `validate`, `pack` e `inspect`; adjunta `.paessed` y ZIP idénticos con sus pendientes visibles. Una entrega parcial válida conserva los estados sin promoverlos a `verified`.
