# Chat web con solucionario completo

Aplica cuando todas las preguntas tienen pauta legible y correspondiente. Sigue la [operación común](../../references/workflow.md), usando las [interfaces](../../references/interfaces.md) y el [contrato de contenido](../../shared/references/content-contract.md).

- Usa `prepare --host web` en una carpeta temporal escribible. Comprueba lectura visual y entrega descargable. No preguntes destino local.
- Congela la pauta completa mediante `map` y `route --answer-key key.json`. Si es parcial, vuelve al selector de SKILL.md.
- Transcribe desde el ensayo; toma respuestas y desarrollos del solucionario. Explicaciones editables, con diagramas cuando hagan falta. No repitas la resolución completa si ya está documentada.
- Ejecuta `review` e inspecciona la comparación HTML; si no puedes, usa las capturas observables de la operación común. Revisa todas las preguntas y recortes antes de `record-check`. Sin vía visual, informa la limitación y conserva pendientes. Repara antes de `validate` y `pack`.
- Adjunta `.paessed` y ZIP idénticos. Si no puedes completar el cotejo, conserva la ejecución e informa los pendientes; no anuncies una entrega terminada.
