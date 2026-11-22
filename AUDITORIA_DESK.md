# Auditoria De NUMA Deck Presentations

## Alcance Y Método

- Proyecto: NUMA Deck Presentations (Desk).
- Ruta: `C:\00_PROYECTOS\NUMA\NUMA PRESENTATION MD`.
- Fecha: 2026-09-28.
- Tipo: auditoría estática y verificación técnica inicial.
- Alcance: arquitectura, estabilidad, persistencia, backups, presentación, WebSocket Mobile Link, seguridad local, pruebas y observabilidad.
- No se modificó el código de Desk durante esta auditoría.

## Verificaciones Ejecutadas

- `.venv\Scripts\python.exe -m py_compile main.py mobile_link.py preview.py parser.py styles.py editor.py test_all.py` — correcto.
- `.venv\Scripts\python.exe test_all.py` — `ALL TESTS PASSED`.
- Conteo estructural y revisión estática de módulos, funciones, excepciones, timers, sockets, rutas y backups.

## Hallazgos

### AUD-001 — Alto — Mobile Link sin autenticación ni validación completa

- Evidencia: `mobile_link.py:27`, `mobile_link.py:83`, `mobile_link.py:103-116` y `main.py:1062-1084`.
- El receptor escucha en `0.0.0.0:8765`, acepta cualquier cliente que alcance el puerto y entrega sus mensajes al hilo Qt. No se exige un `hello` válido antes de aceptar acciones ni existe token, autorización, límite de mensajes o validación centralizada de versión/secuencia.
- Impacto: cualquier dispositivo de la red local podría intentar avanzar slides, abrir imágenes, alternar el puntero o modificar el tema durante una presentación.
- Recomendación: handshake obligatorio con token de sesión, validación de esquema y versión, control de secuencia, límite de frecuencia, cierre de clientes no autorizados y opción explícita para enlazar solo en loopback o en una interfaz seleccionada.
- Confianza: confirmado por inspección estática.

### AUD-002 — Medio — `recenter_pointer` no ejecuta el recentrado

- Evidencia: `main.py:1082-1083`.
- La acción recibida desde Mobile solo muestra `Puntero Mobile recentrado` en la barra de estado. No llama a `set_mobile_pointer`, no actualiza `_mobile_pointer_pending` y no sincroniza una posición central con Mobile.
- Impacto: el usuario puede pulsar Recentrar y recibir confirmación visual sin que el puntero cambie de posición.
- Recomendación: implementar una operación única de recentrado que actualice el estado Desk, la vista activa y, si corresponde, confirme la posición a Mobile.
- Confianza: confirmado por inspección estática.

### AUD-003 — Medio — Cobertura insuficiente de los flujos críticos

- Evidencia: `test_all.py:1-196`.
- Las pruebas actuales cubren principalmente QSS, parser Markdown, modos slide/scroll/paper, referencias, matemáticas, enlaces e imágenes rotas. No cubren backups, cierre inesperado, recuperación por documento, modo dual, guardado de ambos archivos, navegación del editor, WebSocket real ni ciclo de presentación.
- Impacto: `ALL TESTS PASSED` no certifica los flujos donde se han observado cierres, recuperación incorrecta y problemas de interacción.
- Recomendación: añadir pruebas aisladas para autosave y retención, pruebas de protocolo para Mobile Link, pruebas de modo dual y una matriz manual o automatizada de presentación.
- Confianza: confirmado como hueco de cobertura.

### AUD-004 — Medio — Superficie ampliada de QWebEngine para Markdown local

- Evidencia: `preview.py:150-155`.
- La vista habilita JavaScript, acceso de contenido local a archivos y acceso de contenido local a URLs remotas. Esto es funcionalmente útil para imágenes y contenido enriquecido, pero aumenta la superficie si se abre Markdown no confiable o con HTML embebido.
- Impacto: un documento local puede cargar recursos remotos o ejecutar contenido que no estaba contemplado por el usuario; el riesgo exacto depende del HTML aceptado por el parser y de la configuración de Chromium.
- Recomendación: definir el modelo de confianza de los documentos, sanitizar HTML si se abrirán archivos externos, limitar recursos remotos cuando no sean necesarios y separar la vista de edición de la vista de presentación cuando aplique.
- Confianza: riesgo confirmado; explotación no validada en esta fase.

### AUD-005 — Medio — Concentración elevada de responsabilidades

- Evidencia estructural: `main.py` tiene 8,818 líneas; `create_toolbar` ocupa aproximadamente 358 líneas; `init_ui` aproximadamente 248; `_load_tab` aproximadamente 142; `styles.py` tiene 2,258 líneas y `get_html_template` aproximadamente 1,768.
- La aplicación puede funcionar, pero los cambios en UI, persistencia, presentación y Mobile Link comparten una superficie muy grande y aumentan el riesgo de regresiones cruzadas.
- Recomendación: separar por casos de uso y adaptadores, empezando por autosave/recovery, Mobile Link, presentación y ciclo de pestañas. Mantener interfaces pequeñas antes de extraer clases.
- Confianza: confirmado como deuda de mantenibilidad; no implica por sí solo un fallo funcional.

### AUD-006 — Bajo — Fuente de versión visible inconsistente

- Evidencia: `main.py:325` muestra `Version 1.0.0`, mientras `VERSION_CONTROL_INTERNO.md` registra `0.1.0-dev`.
- Impacto: dificulta correlacionar capturas, logs, reportes y artefactos con el código realmente ejecutado.
- Recomendación: definir una única fuente de versión y usarla en interfaz, logs, changelog y diagnóstico de fallos.
- Confianza: confirmado por inspección estática.

### AUD-007 — Medio — Detención del servidor Mobile con estado potencialmente prematuro

- Evidencia: `mobile_link.py:53-63`.
- `stop()` espera como máximo dos segundos y después limpia las referencias del hilo, loop y servidor aunque el hilo todavía pudiera seguir vivo.
- Impacto: una detención lenta podría dejar un hilo activo, provocar conflicto de puerto o producir un estado inconsistente al iniciar de nuevo el receptor.
- Recomendación: registrar si `join()` terminó, conservar el estado hasta confirmar la terminación y hacer que `start()` rechace una instancia cuyo hilo anterior siga vivo.
- Confianza: riesgo confirmado por diseño; requiere prueba de cierre lento para medir impacto real.

## Cobertura Por Área

| Área | Estado | Evidencia | Riesgo residual |
|---|---|---|---|
| Arquitectura | Amarillo | Alta concentración en `main.py` y `styles.py` | Regresiones al tocar flujos compartidos |
| Datos y archivos | Amarillo | Existe autosave atómico y retención, falta matriz de pruebas | Recuperación dual no certificada automáticamente |
| Seguridad local | Rojo | WebSocket abierto en todas las interfaces sin autenticación | Control remoto no autorizado en la LAN |
| Rendimiento | Amarillo | Coalescencia del puntero y timers existentes | Sin medición de documentos grandes/QWebEngine |
| IPC y concurrencia | Amarillo | WebSocket en hilo separado y señales Qt | Detención, protocolo y límites necesitan pruebas |
| GUI y ciclo de vida | Amarillo | Presentación, dual y QWebEngine integrados | Sin pruebas automatizadas de cierre/presentación |
| Testing | Rojo | `test_all.py` no cubre los flujos críticos | Falsos positivos de estabilidad |
| Logs y operación | Amarillo | Logs de sesión, fallo nativo, Qt y heartbeat | Falta correlación única de versión |

## Prioridad Recomendada

1. Proteger y validar Mobile Link.
2. Corregir y probar `recenter_pointer`.
3. Crear pruebas automatizadas de backups, cierre, recuperación y modo dual.
4. Probar detención/reinicio del servidor Mobile Link.
5. Unificar la versión visible y la versión de diagnóstico.
6. Revisar la política de seguridad de QWebEngine para documentos externos.

## Pendiente De Fase Dinámica

- Prueba con dos clientes Mobile simultáneos.
- Envío de JSON inválido, tipos incorrectos, secuencias repetidas y mensajes de gran tamaño.
- Cierre de Desk durante una escritura de autosave.
- Recuperación de alumno y profesor en modo dual.
- Documento con muchas imágenes y presentación larga.
- Cierre lento y reinicio del receptor WebSocket.
- Inspección visual de los modos sencillo, continuo, papel, presentación y dual.

## Estado Tras La Implementación

- `AUD-001`: mitigado en código. Mobile Link exige token de emparejamiento, handshake, esquema básico, secuencia, tamaño y frecuencia.
- `AUD-002`: corregido. `recenter_pointer` actualiza la posición real del puntero activo.
- `AUD-003`: pendiente únicamente de ejecutar la batería final y la matriz dinámica.
- `AUD-004`: mitigado parcialmente. QWebEngine conserva acceso a archivos locales para imágenes, pero bloquea cargas remotas silenciosas.
- `AUD-005`: mitigado parcialmente. Se extrajeron versionado y diagnósticos; la separación completa de `main.py` permanece como refactorización posterior.
- `AUD-006`: corregido. La versión Desk proviene de `version.py` y se propaga a interfaz, aplicación y operaciones registradas.
- `AUD-007`: mitigado en código. El reinicio conserva referencias si el hilo no termina y registra el estado de detención.

La ejecución de pruebas automatizadas, pruebas dinámicas y nueva auditoría queda reservada para la fase final solicitada.
