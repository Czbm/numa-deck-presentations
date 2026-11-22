# Registro de cambios

Todos los cambios notables de **NUMA Deck Presentations** se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y las versiones siguen [Versionado Semántico](https://semver.org/lang/es/).

## [Sin publicar]

### Corregido
- Las imagenes SVG con dimensiones porcentuales ya no colapsan a cero al aplicar Auto y opciones de imagen; conservan su relacion de aspecto sin alterar el tamano automatico de imagenes raster.
- El boton QR de conexiones directas permite activar el receptor y abre el codigo automaticamente cuando esta disponible, sin completar campos manualmente.
- Las tablas de hoja impresa se reparten por filas entre paginas con encabezados repetidos. Las celdas de texto mayores que una hoja continuan en paginas adicionales sin perder contenido.
- La vista previa localiza y centra la imagen del cursor o su leyenda en la pagina real tras paginar, sin regresar a la primera pagina de la seccion.
- Las opciones de imagen, incluido Sin marco, se aplican tambien cuando la leyenda comparte parrafo con la imagen, conservando su texto y formato.
- Desk actualiza el backup de los documentos modificados al cambiar de pestana y conserva su edicion en memoria al regresar, sin repetir el dialogo de recuperacion. El autosave de documentos sin guion externo utiliza el contenido principal actualizado.
- Desk ya no conserva respaldos de recuperación después de un guardado normal; así se evita ofrecer como recientes copias anteriores y mostrar falsos positivos al reabrir un documento.
- El temporizador de autosave ya no genera respaldos desde pestañas limpias con contenido en memoria desactualizado.
- El overlay de imagen procesa el gesto vertical del Mousepad como zoom, manteniendo el scroll normal cuando no hay imagen abierta.
- El Touchpad de puntero ya no envía eventos de interacción de Mousepad; el Mousepad convencional controla el zoom vertical de imágenes abiertas.
- El Mousepad convencional del Android-Link funciona de forma independiente aunque el puntero principal permanezca visible; ya no depende del botón de mostrar u ocultar puntero.

### Modificado
#### Desk
- Nueva versión activa `v260929.1006`, generada con la hora local y el formato `YYMMDD.HHMM` establecido para NUMA Deck Presentations.
- Desk puede generar un QR autenticado para emparejar NUMA Deck Android-Link sin transcribir el token.

### Añadido
- Desktop: panel `Conexion directa`, receptor Bluetooth RFCOMM autenticado y publicador Wi-Fi Direct de Windows, ambos opcionales e independientes de la red existente.
- QR por transporte para los clientes directos de Android-Link versionCode 75; el enlace fisico entre dispositivos sigue pendiente de validacion.
- Bloque colapsable de configuración de atajos con selector de acciones, captura de teclas mediante `QKeySequenceEdit` y persistencia global en `.numa_deck_shortcuts.json`.
- Acciones configurables para abrir la imagen del slide actual, abrir o cerrar su vista a pantalla completa y aplicar zoom in/zoom out durante cualquier modo de presentación.
- Confirmación visual temporal dentro del bloque de atajos al aplicar o limpiar una combinación.
- El acceso a la configuración de atajos ahora aparece como botón `Atajos` del toolbar, colocado inmediatamente después de `Barra Imagen`, sin ocupar una fila independiente.
- Emparejamiento autenticado para Mobile Link mediante token de sesion incluido en la direccion mostrada por Desk.
- Roadmap de optimización y pruebas de regresión para backups, modo dual y Mobile Link en `ROADMAP_OPTIMIZACION_DESK.md` y `test_regression.py`.
- Registro diagnóstico directo por sesión en `numa_session.log`.
- Receptor WebSocket local para NUMA Deck Android-Link en `mobile_link.py`.
- Traducción de acciones Mobile a navegación, apertura/cierre de imágenes y zoom durante la presentación.
- Overlay visual de puntero Mobile sobre el slide activo, usando coordenadas normalizadas y sin modificar Markdown.
- Etiqueta persistente en la barra inferior con la dirección WebSocket para conectar Mobile.
- Confirmación visible cuando NUMA Deck Android-Link establece conexión.
- Configuración del puntero Mobile desde Android: tamaño, aro/punto, colores neón y rastro.

### Corregido
- El comando `recenter_pointer` de Mobile ahora actualiza realmente el puntero del slide activo y registra la operación.
- La carga de un guion externo ya no vuelve a preguntar por backups del otro documento; la comprobación queda limitada a la fuente que se está cargando.
- Corrección del cierre de imágenes en presentación para evitar pasar `None` como argumento inválido a `QWebEnginePage.runJavaScript`.
- Corregido el registro de acciones Mobile desconocidas que provocaba un `TypeError` por colisión de nombres.
- Aumentado el límite controlado de mensajes de Mobile Link a 300 por segundo para admitir Touchpad y mouse virtual simultáneos sin desconectar sesiones válidas; los excesos siguen cerrándose y ahora dejan el conteo y tipo del último mensaje en el log.
- El diálogo QR se cierra automáticamente al confirmar la conexión y el aviso de conexión establecida desaparece después de 2 segundos.
- Desk ya no muestra una conexión exitosa al abrirse solamente el socket; la confirmación ocurre después de validar el token mediante el mensaje `hello` autenticado.
- El aviso de conexión autenticada incluye ahora el botón `Cerrar` y se cierra automáticamente a los 2 segundos mediante `QMessageBox.exec()` y `accept()`.
- Desk actualiza el puntero Mobile con un temporizador de 8 ms y conserva la coalescencia de posiciones para reducir latencia sin acumular eventos atrasados.
- El autosave ya no crea copias idénticas al original y elimina cualquier copia de recuperación anterior cuando el documento vuelve a quedar limpio; el cierre normal también elimina el par de recuperación.
- La purga de recuperación elimina también copias antiguas que ya coinciden con su original, conservando las que todavía contienen cambios.
- Corregida la colisión del registro de acciones Mobile normales, que podía generar una excepción al usar controles desde Mobile.

### Técnico
- Mobile Link valida handshake, version, payload, secuencia, tamano de mensaje y frecuencia antes de entregar eventos a la GUI.
- La detención de Mobile Link conserva el estado si el hilo no termina, evita reinicios sobre un receptor vivo y registra el ciclo de vida del hilo y los clientes.
- El heartbeat de Desk incluye métricas sin contenido de Mobile Link para localizar saturación, duplicados y clientes activos.
- Las vistas de presentación registran tiempos de preparación y carga, tamaño de Markdown/HTML y resultados de WebEngine sin guardar el contenido del documento.
- La recuperación valida el hash SHA-256 de la copia antes de ofrecerla y la vista local bloquea cargas remotas silenciosas.
- Se extrajo la lógica de archivos de recuperación a `recovery_service.py`, sin dependencia de Qt; la ventana conserva únicamente coordinación y confirmación al usuario.
- Los comandos externos de presentación pasan por `presentation_controller.py`, que centraliza la frontera Mobile -> slides sin exponer widgets al transporte.
- El heartbeat registra el último comando de presentación y su tiempo de despacho para localizar retrasos de navegación.
- Registro ampliado de hooks de teclado, eventos Qt, excepciones de hilos y sesiones de fallo nativo.
- El receptor se ejecuta en un hilo separado y entrega mensajes al hilo Qt mediante señales.
- Se añadió `websockets>=12,<16` a los requisitos del proyecto.
- Color explícito para la dirección de conexión, visible en temas claro y oscuro.
- El puntero se oculta automáticamente al finalizar la presentación.
- El movimiento del puntero se actualiza con `requestAnimationFrame` y la configuración se aplica una sola vez por vista para reducir latencia.
- Desk coalescea los eventos de puntero y renderiza como máximo cada 16 ms para evitar acumulación de posiciones atrasadas.
- El overlay admite rastro de puntos desvanecientes y rastro continuo con canvas.
- Desk acepta la acción `toggle_pointer` para mostrar u ocultar el puntero durante la presentación.
- El puntero Mobile queda por encima del overlay de imagen ampliada y sigue la imagen al cargarla o aplicar zoom.
- Eliminada la apertura de imágenes mediante doble pulsación de avance; el avance vuelve a ejecutarse con una sola pulsación.
- Al ocultar el puntero, Desk acepta clic y scroll de mouse virtual desde Mobile para interactuar con la presentación.
- Desk conserva la coordenada aunque el puntero esté oculto y procesa toque simple, doble toque y scroll sobre el slide.
- Desk recibe desde Mobile los controles de tamaño de texto y alternancia de tema durante la presentación.
