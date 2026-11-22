# Control interno de versiones

## Producto

- Nombre oficial: **NUMA Deck Presentations**.
- Plataforma: Windows.
- Tipo: aplicación de escritorio Python/PySide6.

## Estado de versión

- Versión de desarrollo: `260929.1006`, centralizada en `version.py`.
- Estado: desarrollo activo, sin release pública formal.
- La versión permanece abierta en `[Sin publicar]`; no representa un cierre o distribución pública.

## Registro de esta sesión

- Fecha y hora local de versión: `2026-09-29 10:06`.
- Nueva versión: `260929.1006`.
- Cambio registrado: purga de copias idénticas antiguas y conservación de backups que todavía difieren del original.
- Regla aplicada: sello `YYMMDD.HHMM`, sin reutilizar versiones anteriores.

- Fecha: `2026-09-28`.
- Cambios: receptor WebSocket autenticado de NUMA Deck Android-Link, ciclo de vida de hilo y clientes reforzado, métricas de Mobile Link y render en heartbeat, recovery extraído a `recovery_service.py` con hash de integridad, frontera de comandos extraída a `presentation_controller.py`, política local de recursos WebEngine, versión centralizada en `version.py`, etiqueta de dirección con token de emparejamiento, confirmación visible, traducción de acciones durante presentación, corrección del recentrado del puntero y comprobación de backups limitada al documento que se está cargando.
- Validación: `py_compile`, `test_all.py` y `test_regression.py` completados correctamente.
- Validación QR: generación de payload e imagen QR comprobada; `py_compile`, `test_all.py` y `test_regression.py` completados correctamente el `2026-09-29`.
- Artefacto distribuible: no generado.

## Regla para próximos cambios

- La versión `260929.1006` permanecerá abierta en `[Sin publicar]` hasta que el usuario solicite explícitamente cerrarla.
- En cada cambio posterior se actualizará la versión con la hora local real y se integrará el registro en el changelog existente del mismo día.
- `PATCH`: correcciones y mejoras compatibles dentro de las funciones actuales.
- `MINOR`: nuevo subsistema compartido o cambio visible amplio de flujo.
- `MAJOR`: ruptura de compatibilidad o release estable aprobada.
- Antes de una distribución, se deberá definir una fuente de versión única y actualizar este archivo junto con `CHANGELOG.md`.
