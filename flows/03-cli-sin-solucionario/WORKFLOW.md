# CLI sin solucionario completo

Sigue la [operación común](../../references/workflow.md), las [interfaces](../../references/interfaces.md) y el [contrato de contenido](../../shared/references/content-contract.md). Consulta la [auditoría](../../references/audit.md) solo si seleccionas revisión independiente.

- Prepara con `--host cli`. Conserva la pauta parcial correspondiente y resuelve únicamente `solve_question_ids`; registra la procedencia real de cada respuesta y explicación.
- Declara `--subagents` solo si existen revisores con contexto nuevo y evidencia visual. La revisión independiente predeterminada cubre las preguntas sin pauta; las opciones de selección están en auditoría.
- Transcribe, clasifica currículo y coteja todas las preguntas mediante `review` y `record-check`. Conserva dudas como `unresolved`.
- Si `independent_question_ids` está vacío, usa `validate`, `pack` e `inspect`. De lo contrario, sigue `baseline` y `verify` según auditoría.
- Entrega `.paessed` y ZIP idénticos, cobertura y pendientes explícitos. Puede existir una entrega parcial válida; ninguna revisión acredita certeza matemática automática.
