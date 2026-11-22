# Roadmap de Optimizacion

## Estado actual

- Producto: **NUMA Deck Presentations**.
- Version: `260929.0821` (`[Sin publicar]`, abierta).
- Fecha de inicio: `2026-09-28`.
- Fase activa: **8. Verificacion final**.
- Base confirmada: `py_compile` y `test_all.py` pasan; la auditoria estatica esta en [AUDITORIA_DESK.md](AUDITORIA_DESK.md).

## Objetivo

Reducir cierres inesperados, recuperaciones incorrectas, regresiones en modo dual y latencia de presentacion, conservando la compatibilidad de los documentos y del enlace con **NUMA Deck Android-Link**.

## Fases

### 0. Linea base y observabilidad [x]

- [x] Ejecutar compilacion y pruebas existentes.
- [x] Registrar arquitectura, tamanos, riesgos y pendientes en `AUDITORIA_DESK.md`.
- [x] Mantener version abierta en `[Sin publicar]`.

### 1. Regresion de flujos criticos [/]

- [x] Crear `test_regression.py` separado de la GUI visual.
- [x] Cubrir extraccion de fuentes de alumno/profesor para una pestaña dual.
- [x] Cubrir escritura atomica, comparacion y retencion de backups de tres dias.
- [x] Cubrir protocolo basico de Mobile Link con cliente simulado.
- [x] Verificar que `recenter_pointer` actualiza la posicion del puntero activo.
- [/] Ejecutar pruebas dinamicas de GUI y presentacion real; requieren entorno con ventana y WebEngine.

### 2. Persistencia y recuperacion por alcance [x]

- [x] Separar la revision de alumno y profesor cuando se carga una fuente externa.
- [x] Garantizar que cerrar normalmente deje una copia identica al archivo original.
- [ ] Cubrir recuperacion de alumno/profesor con pruebas de modo dual.
- [x] Registrar en log decision, ruta, hash y resultado de cada recuperacion.

### 3. Mobile Link seguro y validado [x]

- [x] Handshake obligatorio con token de emparejamiento por sesion.
- [x] Validar version, tipo, payload, secuencia y tamano maximo.
- [x] Limitar frecuencia y rechazar clientes no autorizados.
- [x] Evitar autosaves idénticos al original y eliminar copias de recuperación cuando el documento queda limpio.
- [ ] Probar dos clientes, mensajes invalidos y reinicio del receptor.

### 4. Ciclo de vida y concurrencia [x]

- [x] Corregir apagado/reinicio del servidor hasta confirmar la terminacion del hilo.
- [x] Instrumentar inicio, detencion, hilo, clientes y error de cierre del receptor.
- [ ] Probar cierre durante autosave y cierre inesperado simulado.

### 5. Presentacion y controles [/]

- [x] Corregir el recentrado del puntero Mobile.
- [ ] Verificar navegacion, imagen ampliada, scroll y presentacion dual en matriz manual.
- [ ] Confirmar que los eventos afectan slides y no labels ni elementos auxiliares.

### 6. Rendimiento medido [/]

- [/] Añadir métricas de Mobile Link: aceptados, inválidos, duplicados, límite de frecuencia y clientes activos.
- [/] Instrumentar tiempos de preparacion HTML, carga de WebEngine y tamaño de Markdown/HTML por vista.
- [x] Instrumentar tiempo de despacho de comandos de presentación y entrega de puntero.
- [ ] Probar documentos grandes, muchas imagenes y presentaciones largas.
- [ ] Optimizar solo los cuellos medidos: render, coalescencia, memoria o WebEngine.

### 7. Mantenibilidad y versionado [/]

- [/] Separar version, diagnostico, recovery, presentacion y Mobile Link por etapas; version, diagnostico, recovery y la frontera de comandos de presentacion ya tienen componentes propios, la extraccion completa de GUI queda para una refactorizacion posterior.
- [x] Unificar fuente de version para interfaz, logs, changelog y artefactos.
- [ ] Repetir auditoria y actualizar riesgos residuales.
- [x] Actualizar el estado de hallazgos en `AUDITORIA_DESK.md`.

### 8. Verificacion y entrega [/]

- [ ] Ejecutar pruebas automaticas y compilacion.
- [ ] Ejecutar matriz manual de modos sencillo, continuo, papel, presentacion y dual.
- [x] Actualizar `CHANGELOG.md`, `VERSION_CONTROL_INTERNO.md` y conservar copia en el directorio de enlace solicitado.

## Criterio de avance

Una fase solo se marca como completa cuando tiene evidencia reproducible: prueba automatizada, log, medicion o verificacion manual documentada. Los cambios de arquitectura no se realizan antes de cubrir el comportamiento que protegen.
