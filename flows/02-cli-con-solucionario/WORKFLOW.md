# CLI con solucionario completo

Aplica cuando todas las preguntas tienen pauta legible y correspondiente. Sigue la [operación común](../../references/workflow.md), usando las [interfaces](../../references/interfaces.md) y el [contrato de contenido](../../shared/references/content-contract.md).

- Usa `prepare --host cli` en el destino indicado; pregunta solo si falta. Observa las capacidades visuales reales: lectura PDF nativa o páginas renderizadas.
- Congela la pauta completa mediante `map` y `route --answer-key key.json`. Si es parcial, vuelve al selector de SKILL.md.
- Transcribe desde el ensayo; toma respuestas y desarrollos del solucionario. Explicaciones editables, con diagramas cuando hagan falta. No repitas la resolución completa si ya está documentada.
- Ejecuta `review` e inspecciona el HTML o, si falta esa vía, las capturas observables de la operación común. Coteja todas las preguntas y recortes antes de `record-check`. Sin ambas vías conserva la revisión pendiente. Una revisión propia no equivale a revisión independiente.
- Repara pendientes antes de `validate`, `pack` e `inspect`. Entrega rutas `.paessed`/ZIP y procedencia. Si falta evidencia, conserva avances y declara la importación incompleta.
