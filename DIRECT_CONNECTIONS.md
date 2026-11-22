# Conexiones directas Mobile - Desktop

## Estado

Desktop implementa Bluetooth RFCOMM y un publicador Wi-Fi Direct de Windows.
Android-Link versionCode 75 incluye clientes para ambos transportes y lectura
del QR directo; el enlace fisico completo entre equipos aun requiere validacion.
La conexion existente por red y su QR no se sustituyen.

Las conexiones directas se activan manualmente desde `Conexion directa` en
la barra de estado. Cerrar ese dialogo no desactiva los transportes; salir de
Desk los cierra. No se cambian ajustes permanentes del adaptador ni firewall.
Instalar `requirements.txt` en el entorno utilizado para iniciar Desk.

## Bluetooth

- Servicio: `NUMA Deck Mobile`.
- UUID: `da291c95-9964-47c5-b2b9-c6b3d513cb87`.
- RFCOMM con cifrado y autenticacion Bluetooth de Windows.
- Android debe usar un socket RFCOMM seguro y estar emparejado con Windows.
- Mensajes UTF-8 JSON terminados en LF, no frames WebSocket.
- Sobre ese stream se reutiliza el protocolo Mobile v1 existente: `hello`
  con token y `protocol_version: 1`, seguido de acciones con secuencia creciente.
- Respuestas tambien JSON + LF. No enviar acciones antes de `hello_ack`.
- Limite de mensaje: 64 KiB; hasta cuatro streams Bluetooth simultaneos;
  primer mensaje en 15 segundos; limite de frecuencia del receptor actual.

## Wi-Fi Direct

Windows publica un grupo autonomo Wi-Fi Direct con compatibilidad legacy AP,
SSID `NUMA-Deck-*` y clave aleatoria nueva en cada activacion. No es el antiguo
`netsh hostednetwork` ni depende de un router externo. Tambien se aceptan
solicitudes P2P mediante `WiFiDirectConnectionListener`.

El protocolo de aplicacion sigue siendo WebSocket, usando el receptor existente
en el puerto configurado de Desk, por defecto 8765. Android debera conectar
al grupo, obtener su direccion de destino mediante DHCP/gateway o los datos
P2P, y enviar el mismo `hello` autenticado. No asumir 192.168.49.1 ni otra IP fija.
El dialogo muestra todas las direcciones IPv4 activas con su interfaz; escoger
la correspondiente al enlace directo, no la de otra red.

El token autoriza las acciones, aunque Windows acepte la asociacion al grupo.
El firewall puede necesitar autorizacion para el Python de Desk en esa interfaz;
el programa no crea reglas ni modifica perfiles de seguridad automaticamente.
Una politica de Windows, radio desactivada o controlador incompatible produce
estado Error, no una simulacion de conexion disponible.

## Emparejamiento

`Copiar emparejamiento` produce JSON `NUMA-DIRECT` version 1, con transporte,
token y UUID Bluetooth o SSID/clave/puerto Wi-Fi. `QR` permite mostrar el mismo
contenido para escanearlo desde Android. Contiene secretos: no publicarlo
ni incluirlo en logs. Android versionCode 75 reconoce ese formato.

## Validacion

`python -m unittest test_direct_connections` verifica framing, token, secuencias
y rechazo de clientes no autorizados sin activar radios. La publicacion de ambos
servicios y su apagado se probaron en Windows local; no constituye una prueba
de enlace completo Android-Desktop.
