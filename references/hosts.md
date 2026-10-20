# Compatibilidad de anfitriones

SKILL.md enruta a uno de cuatro WORKFLOW.md cuando el anfitrión puede leer el bundle. Instalar una skill no garantiza lectura visual ni otras capacidades. La clasificación web/CLI identifica el lugar de trabajo; las capacidades se observan en la sesión. Un chat web puede disponer de Python, Node y generación de ZIP.

| Anfitrión | Estado de este bundle |
| --- | --- |
| AGY | Corrida real de este bundle pendiente. |
| Codex CLI/app | Adaptación preparada; corrida real pendiente. |
| Claude Code | Adaptación preparada; corrida real pendiente. |
| Chat web con archivos/código | Ruta descargable y consentimiento preparados; prueba real pendiente. |
| Chat solo texto o sin visuales/ZIP | No puede completar este pipeline; debe informar lo faltante. |

No confundir pruebas sintéticas con pruebas reales de productos. Las herramientas dependen de cuenta/sesión; observarlas al comenzar. Leer texto de un PDF no implica comprender sus gráficos.

Además de leer PDF, el anfitrión debe poder observar el resultado renderizado. Prefiere inspección HTML disponible en la sesión. Si falta, usa capturas con el adaptador opcional y un navegador externo existente o preparado aparte. Playwright no pertenece al runtime mínimo y no se distribuyen navegadores. Si ambas vías faltan, registra result_visual.mode unavailable, informa la limitación y conserva cotejos pendientes.

Instalación, salida y herramientas se resuelven desde el bundle operativo: no se busca código en paes-importer-dev ni en un proyecto padre. Los entornos y temporales permanecen externos. Los tests y herramientas de mantenimiento no son requisitos del anfitrión.

Codex: bundle completo bajo .agents/skills/paes-importer o lectura explícita por ruta. Para independencia, agentes sin historial heredado (fork_turns=none donde exista esa API), solo su lote e instrucciones mínimas. Fuentes oficiales: https://learn.chatgpt.com/docs/build-skills y https://learn.chatgpt.com/docs/agent-configuration/subagents.

Claude Code: bundle completo bajo .claude/skills/paes-importer o lectura explícita. Usar un subagente nuevo por lote; evitar forks que hereden historial productor. Fuentes oficiales: https://code.claude.com/docs/en/skills y https://code.claude.com/docs/en/sub-agents.

Chat web: obtener bundle, ejecutar Python/Node en workspace cuando estén disponibles, recortar y entregar enlaces .paessed y ZIP idéntico. Si no dispone de dependencias y no puede prepararlas, informar impedimento. Esperar consentimiento cuando falte pauta. Sin acceso al equipo, el destino local se elige al descargar.

