# Auditoría de portabilidad

> Registro histórico de desarrollo; no forma parte de las instrucciones de uso ni del ZIP distribuible. Las cifras corresponden a la fecha original del informe.

Alcance: código, instrucciones, referencias, schemas, viewer, bibliotecas incluidas, instalación, empaquetado, tests y configuración de CI. El bundle es independiente de otros proyectos. Fecha: 2026-10-10.

## Dependencias reales

| Hallazgo | Resolución o requisito |
| --- | --- |
| Python y sus paquetes no se distribuyen dentro de la skill. | Python 3.12+ y requirements.txt; requirements-dev.txt para desarrollo. setup.py crea el entorno dentro de la instalación. |
| setup.py comprobaba la presencia de Node, pero aceptaba versiones inferiores a la mínima declarada. | Comprueba Node.js 18+ antes de crear el entorno. Node se obtiene del PATH del anfitrión. |
| Un entorno .venv contiene referencias al intérprete y a su ubicación original. | Excluido de Git y del bundle. Recrearlo después de trasladar la instalación; no distribuirlo entre equipos. |
| Los ejemplos relativos pueden ejecutarse desde un directorio equivocado o con un Python sin dependencias. | README y workflow explicitan el intérprete y la carpeta de ejecución, y cómo usar rutas absolutas desde otra carpeta. |
| PDFs, archivos de entrada y resultados pertenecen a cada ejecución. | Rutas proporcionadas por el usuario; salida seleccionada mediante Documentos, Descargas o --output-root. Las carpetas conocidas se resuelven en el sistema del usuario. |
| sources.local.json y metadatos de auditoría conservan rutas absolutas de la ejecución. | Son trazabilidad local, fuera del bundle. No se reescriben ni se migran silenciosamente; conservar esas ubicaciones para reanudar. |

Los imports Python usan la ubicación de los scripts; schema y validadores se resuelven desde la raíz de la skill. Los require de JavaScript apuntan a archivos incluidos en viewer/. No se encontraron dependencias de ejecución hacia Test2, V1, V2, PAESSED.CL ni otros repositorios. No hay rutas absolutas del autor en el código distribuido ni enlaces a archivos externos en el árbol versionado.

Los package.json de JSZip y KaTeX conservan metadatos de sus proyectos originales, incluidos scripts y dependencias de construcción. La skill carga directamente las distribuciones minificadas incluidas; no ejecuta esos scripts ni requiere sus árboles de desarrollo. Las licencias y atribuciones se conservan.

## Referencias históricas que se limpiaron

AGENTS.md permitía escribir en Test2/tmp y mencionaba V1/V2. Ahora delimita el checkout y las ubicaciones explícitas del usuario. Se retiraron alusiones a carpetas históricas en workflow, decisiones, compatibilidad y verificación; se conservó la atribución a PAESSED. Los comentarios del motor describen su función actual.

## Compatibilidad conservada

Se mantienen sin modificación el schema completo (incluido su título histórico), el lector y validador del viewer, las bibliotecas, los contratos de contenido/paquete y las referencias de auditoría. Se conservan paessed-benchmark, paessed-package, schema_version 0.1.0, pdf-direct, direct/direct-verified, direct-verification-1.0, paired-experiment y los demás campos existentes. El alias UPSTREAM sigue apuntando a la propia raíz de la skill. Las menciones v1 en mensajes de verificación describen el contrato base, no una carpeta requerida.

No se modifican la selección Chat/CLI, el consentimiento experimental, el cotejo, los estados de revisión, el sistema de auditoría ni el contenido del ZIP/.paessed. release.json se regenera para reflejar los cambios intencionales; las ejecuciones anteriores conservan sus controles de integridad y no se reanudan con hashes sustituidos.

## Comprobación reproducible

Con las dependencias instaladas, ejecutar desde la raíz de la skill:

```sh
python -B scripts/release.py
python -B -m unittest discover -s tests -v
```

test_portability.py genera el bundle con make_bundle.py, comprueba su inventario, lo extrae sin .git ni .venv en una ruta con espacios y acentos y ejecutaba release.py, la CLI y los tests del importador desde una carpeta distinta durante la auditoría original. El nuevo bundle únicamente necesita ejecutar los comandos y recursos operativos; los tests permanecen en GitHub. El subproceso utiliza explícitamente el Python de prueba con las dependencias instaladas y elimina PYTHONPATH. Solo usa PDFs sintéticos. Los resultados y límites de la ejecución local se registran en [VERIFICATION.md](VERIFICATION.md).
