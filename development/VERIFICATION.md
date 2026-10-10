# Verificación de implementación

> Registro histórico de desarrollo; no forma parte de las instrucciones de uso ni del ZIP distribuible. Las cifras corresponden a la fecha original del informe.

Comprobación local del bundle portable, 2026-10-10. Se utilizan únicamente fuentes ficticias generadas por examples/synthetic.py. No se ejecutan modelos ni se usan PDFs privados o resultados históricos como fixtures.

La suite recorre las rutas con pauta completa/parcial/ausente; consentimiento web; autorrevisión; auditoría de todo el ensayo o solo faltantes; conservación exacta del baseline; evidencia ampliada; lectura completa; procedencia de respuestas/explicaciones; fórmulas/tablas/recortes y alternativas visuales; hashes/ZIP; destinos; reanudación y rechazo de cambios.

El lector real JavaScript y KaTeX se ejecutan en los recorridos de empaquetado. Las pruebas de vínculos dependen del sistema: Windows puede omitir symlink por privilegios, pero comprueba junction; Linux/macOS comprueban symlink y omiten junction Windows.

Entorno local: Windows, Python 3.14.0 y Node 22.22.3. La .venv se recreó después de trasladar el repositorio, con las dependencias fijadas en requirements-dev.txt. El entorno anterior quedó archivado en tmp/venv-before-relocation, excluido de Git y del bundle. Otros equipos deben crear su propio entorno.

test_portability.py comprueba el ZIP distribuible: inventario exacto, extracción sin .git ni .venv, ruta con espacios y acentos, directorio de ejecución distinto, CLI, release y suite completa del importador. También comprueba el rechazo de Node ausente o anterior a 18 durante instalación.

GitHub Actions ejecuta la misma suite en Windows/Linux con Python 3.12/3.14 y Node 22. La matriz remota y macOS no se ejecutaron durante esta auditoría. Las pruebas sintéticas no acreditan compatibilidad real con modelos, CLI o chats ni corrección matemática de ensayos reales.

Resultado local: 46 pruebas, 45 aprobadas y 1 omitida por privilegios de symlink en Windows; junction aprobado. La prueba del bundle ejecutó además las 43 pruebas del importador en la copia extraída. Instalación desde cero con setup.py --dev y pip check correctos. SKILL.md aprobado por quick_validate.py. Release: 46 archivos verificados; el ZIP contiene esos archivos y release.json. git diff --check sin errores. Log local: tmp/verification/portability-tests.log, excluido de la distribución.
