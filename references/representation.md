# Representación fiel: ejemplos ficticios

El [contrato de contenido](../shared/references/content-contract.md) define los bloques. Mantén separadas prosa y matemática sin perder espacios o puntuación.

## Variables y expresiones

«Si m y n son enteros, calcula m/n» se representa así:

~~~json
[
  {"type":"text","text":"Si "},
  {"type":"math","latex":"m","display":false},
  {"type":"text","text":" y "},
  {"type":"math","latex":"n","display":false},
  {"type":"text","text":" son enteros, calcula "},
  {"type":"math","latex":"\\frac{m}{n}","display":false}
]
~~~

En JSON, cada barra de LaTeX se escapa una vez. El valor decodificado lleva una barra ante frac. Usa display=true para desarrollos separados; false para símbolos dentro de una oración. Las letras de palabras y abreviaturas corrientes siguen siendo prosa. No pierdas índices, exponentes ni unidades.

## Tabla editable

~~~json
{"type":"table","rows":[
  [[{"type":"text","text":"Lado"}],[{"type":"text","text":"Área"}]],
  [[{"type":"math","latex":"a","display":false}],[{"type":"math","latex":"a^2","display":false}]]
]}
~~~

Conserva encabezados, filas, columnas y celdas. Registra shape (o shapes para varias tablas) en el inventario antes de transcribir. Si el contrato no expresa una estructura, por ejemplo celdas combinadas esenciales, registra `representation:"image-with-issue"` y `limitation:{reason,regions}` en esa entrada. Conserva la tabla completa mediante recurso image en el campo e incidencia `TABLE_STRUCTURE_IMAGE_FALLBACK` en la pregunta. Las regiones de limitation cubren las mismas regiones observadas de la tabla. No uses una tabla mínima ficticia para satisfacerla ni apliques esta excepción a matemática editable.

## Opciones gráficas

~~~json
[
  {"label":"A","blocks":[{"type":"image","asset_id":"grafico-a","alt":"Parábola que abre hacia arriba."}]},
  {"label":"B","blocks":[{"type":"image","asset_id":"grafico-b","alt":"Parábola que abre hacia abajo."}]}
]
~~~

Cada recorte incluye su gráfico entero y sus rótulos, sin parte del siguiente. No pongas el mosaico en stem seguido de opciones genéricas.

El recurso debe contener lo observado y permanecer dentro de source_fields de esa alternativa. Un recorte de página completa que mezcla A y B no representa ambas alternativas. Solo reutiliza un recurso compartido cuando la fuente realmente comparte la misma región observada; documenta el mapa con fidelidad.

## Desarrollo con solucionario

Transcribe la explicación y sus ecuaciones como bloques editables, conservando los pasos necesarios para entenderla. Una respuesta correcta por sí sola no demuestra que la transcripción sea fiel. Si el desarrollo necesita un diagrama, incorpora ese diagrama, con la fuente real del solucionario. La captura completa puede quedar como evidencia privada cuando ayude al cotejo.
