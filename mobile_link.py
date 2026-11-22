"""WebSocket receiver for NUMA Deck Android-Link.

The network loop stays outside Qt's GUI thread. Parsed protocol messages are
delivered through Qt signals so Desk can apply presentation actions safely.
"""

import asyncio
import json
import logging
import secrets
import threading
import time
from collections import deque
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, Signal


LOGGER = logging.getLogger("numa.mobile_link")


class MobileLinkServer(QObject):
    """Small local WebSocket server for the Android-Link development protocol."""

    PROTOCOL_VERSION = 1
    MAX_MESSAGE_BYTES = 64 * 1024
    # Touchpad + mouse virtual can emit pointer and scroll events together.
    MAX_MESSAGES_PER_SECOND = 300
    ALLOWED_TYPES = {
        "hello", "pointer", "motion", "pointer_config", "action",
        "mouse_move", "mouse_click", "mouse_scroll",
    }

    connected = Signal(str)
    disconnected = Signal(str)
    message_received = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, parent=None, host="0.0.0.0", port=8765, auth_token=None):
        super().__init__(parent)
        self.host = host
        self.port = int(port)
        self.auth_token = str(auth_token or secrets.token_urlsafe(18))
        self._thread = None
        self._loop = None
        self._server = None
        self._stop_event = threading.Event()
        self._client_count = 0
        self._state_lock = threading.RLock()
        self._client_count_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._stats = {
            "accepted_messages": 0,
            "invalid_messages": 0,
            "unauthorized_clients": 0,
            "oversized_messages": 0,
            "rate_limited_clients": 0,
            "duplicate_sequences": 0,
            "last_sequence": None,
            "last_message_at": None,
            "last_message_type": None,
        }

    @property
    def is_listening(self):
        server = self._server
        return server is not None and server.is_serving()

    @property
    def client_count(self):
        with self._client_count_lock:
            return self._client_count

    def diagnostics_snapshot(self):
        """Return a thread-safe, content-free snapshot for Desk heartbeats."""
        with self._stats_lock:
            snapshot = dict(self._stats)
        snapshot["client_count"] = self.client_count
        return snapshot

    def _record_stat(self, name, **details):
        with self._stats_lock:
            if name in self._stats and isinstance(self._stats[name], int):
                self._stats[name] += 1
            for key in ("last_sequence", "last_message_at", "last_message_type"):
                if key in details:
                    self._stats[key] = details[key]

    def start(self):
        with self._state_lock:
            if self._thread and self._thread.is_alive():
                LOGGER.warning("Inicio Mobile ignorado: el receptor ya esta activo")
                return False
            if self._thread:
                # A finished thread may leave references behind after an
                # import failure or a bind error. They are safe to replace.
                self._thread = None
                self._loop = None
                self._server = None
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._thread_main,
                name="numa-mobile-link",
                daemon=True,
            )
            thread = self._thread
            thread.start()
        LOGGER.info("Inicio solicitado para receptor Mobile | thread=%s", thread.name)
        return True

    def stop(self):
        with self._state_lock:
            thread = self._thread
            loop = self._loop
        if not thread:
            LOGGER.debug("Detencion Mobile ignorada: no hay receptor activo")
            return True
        self._stop_event.set()
        LOGGER.info("Detencion solicitada para receptor Mobile | thread=%s", thread.name)
        if loop and loop.is_running():
            loop.call_soon_threadsafe(self._close_server)
        thread.join(timeout=2.0)
        if thread.is_alive():
            LOGGER.error(
                "Receptor Mobile no termino dentro del limite | thread=%s | clients=%s",
                thread.name,
                self.client_count,
            )
            return False
        with self._state_lock:
            if self._thread is thread:
                self._thread = None
                self._loop = None
                self._server = None
        LOGGER.info("Receptor Mobile detenido limpiamente | clients=%s", self.client_count)
        return True

    def _thread_main(self):
        LOGGER.info("Hilo Mobile iniciado | ident=%s", threading.get_ident())
        try:
            asyncio.run(self._run_server())
        except Exception as error:
            LOGGER.exception("Receptor Mobile no pudo iniciar o finalizar")
            self.error_occurred.emit(f"{type(error).__name__}: {error}")
        finally:
            LOGGER.info("Hilo Mobile finalizado | ident=%s", threading.get_ident())

    async def _run_server(self):
        try:
            import websockets
        except ImportError as error:
            message = "Falta websockets; instala los requisitos de NUMA Deck Presentations"
            LOGGER.error(message)
            self.error_occurred.emit(message)
            return

        self._loop = asyncio.get_running_loop()
        try:
            self._server = await websockets.serve(self._handle_client, self.host, self.port)
            LOGGER.info(
                "Receptor Mobile escuchando | host=%s | port=%s | token_activo=yes",
                self.host,
                self.port,
            )
            await asyncio.to_thread(self._stop_event.wait)
        finally:
            self._close_server()
            if self._server:
                await self._server.wait_closed()
            self._server = None
            LOGGER.info("Receptor Mobile detenido")

    def _close_server(self):
        if self._server:
            self._server.close()

    async def _handle_client(self, websocket):
        remote = str(getattr(websocket, "remote_address", "desconocido"))
        with self._client_count_lock:
            self._client_count += 1
            client_count = self._client_count
        self.connected.emit(remote)
        LOGGER.info("Mobile conectado | remote=%s | clients=%s", remote, client_count)
        authenticated = False
        last_sequence = -1
        message_times = deque()
        try:
            async for raw_message in websocket:
                if isinstance(raw_message, bytes):
                    message_size = len(raw_message)
                elif isinstance(raw_message, str):
                    message_size = len(raw_message.encode("utf-8"))
                else:
                    message_size = 0
                if message_size > self.MAX_MESSAGE_BYTES:
                    self._record_stat("oversized_messages")
                    await self._send_error(websocket, "Mensaje demasiado grande")
                    await self._close_unauthorized(websocket, "message too big")
                    break
                try:
                    message = json.loads(raw_message)
                except (TypeError, json.JSONDecodeError):
                    self._record_stat("invalid_messages")
                    await self._send_error(websocket, "JSON inválido")
                    continue
                valid, reason = self._validate_envelope(message)
                if not valid:
                    self._record_stat("invalid_messages")
                    await self._send_error(websocket, reason)
                    continue

                message_type = message["type"]
                payload = message["payload"]
                sequence = message["sequence"]
                if message_type == "hello":
                    if authenticated:
                        await self._send_error(websocket, "hello duplicado")
                        continue
                    if not self._token_matches(websocket, payload):
                        self._record_stat("unauthorized_clients")
                        await self._send_error(websocket, "Token de emparejamiento inválido")
                        await self._close_unauthorized(websocket, "invalid pairing token")
                        break
                    if payload.get("protocol_version") != self.PROTOCOL_VERSION:
                        self._record_stat("unauthorized_clients")
                        await self._send_error(websocket, "Versión de protocolo incompatible")
                        await self._close_unauthorized(websocket, "unsupported protocol")
                        break
                    authenticated = True
                elif not authenticated:
                    self._record_stat("unauthorized_clients")
                    await self._send_error(websocket, "Se requiere hello para autorizar la conexión")
                    await self._close_unauthorized(websocket, "handshake required")
                    break

                now = time.monotonic()
                message_times.append(now)
                while message_times and now - message_times[0] > 1.0:
                    message_times.popleft()
                if len(message_times) > self.MAX_MESSAGES_PER_SECOND:
                    self._record_stat("rate_limited_clients")
                    LOGGER.warning(
                        "Mobile excedio el limite de frecuencia | remote=%s | messages_last_second=%s | limit=%s | last_type=%s",
                        remote,
                        len(message_times),
                        self.MAX_MESSAGES_PER_SECOND,
                        message_type,
                    )
                    await self._send_error(websocket, "Límite de frecuencia excedido")
                    await self._close_unauthorized(websocket, "rate limit")
                    break
                if sequence <= last_sequence:
                    self._record_stat("duplicate_sequences")
                    LOGGER.debug(
                        "Mobile secuencia repetida o atrasada | remote=%s | sequence=%s | last=%s",
                        remote, sequence, last_sequence,
                    )
                    continue
                last_sequence = sequence
                self._record_stat(
                    "accepted_messages",
                    last_sequence=sequence,
                    last_message_at=time.time(),
                    last_message_type=message_type,
                )
                message["_remote"] = remote
                self.message_received.emit(message)
                if message_type == "hello":
                    await websocket.send(json.dumps({
                        "version": self.PROTOCOL_VERSION,
                        "type": "hello_ack",
                        "sequence": 0,
                        "timestamp": int(time.time() * 1000),
                        "payload": {
                            "desk_name": "NUMA Deck Presentations",
                            "protocol_version": self.PROTOCOL_VERSION,
                            "auth": "pairing_token",
                            "presentation_active": False,
                            "slide_index": 0,
                            "slide_count": 0,
                        },
                    }))
        except Exception as error:
            LOGGER.exception("Error atendiendo Mobile | remote=%s", remote)
            self.error_occurred.emit(f"cliente {remote}: {type(error).__name__}: {error}")
        finally:
            with self._client_count_lock:
                self._client_count = max(0, self._client_count - 1)
                client_count = self._client_count
            self.disconnected.emit(remote)
            LOGGER.info("Mobile desconectado | remote=%s | clients=%s", remote, client_count)

    def _validate_envelope(self, message):
        if not isinstance(message, dict):
            return False, "El mensaje debe ser un objeto JSON"
        if message.get("version") != self.PROTOCOL_VERSION:
            return False, "Versión de protocolo incompatible"
        message_type = message.get("type")
        if message_type not in self.ALLOWED_TYPES:
            return False, "Tipo de mensaje no permitido"
        sequence = message.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            return False, "Secuencia inválida"
        if not isinstance(message.get("timestamp"), (int, float)):
            return False, "Timestamp inválido"
        if not isinstance(message.get("payload"), dict):
            return False, "Payload inválido"
        if message_type == "hello":
            client_name = message["payload"].get("client_name")
            if not isinstance(client_name, str) or not client_name.strip() or len(client_name) > 80:
                return False, "Cliente inválido"
        return True, ""

    def _token_matches(self, websocket, payload):
        path = str(getattr(websocket, "path", "") or "")
        query_token = parse_qs(urlparse(path).query).get("token", [""])[0]
        payload_token = payload.get("token", "")
        return secrets.compare_digest(str(query_token), self.auth_token) or secrets.compare_digest(
            str(payload_token), self.auth_token
        )

    @staticmethod
    async def _send_error(websocket, message):
        await websocket.send(json.dumps({
            "version": MobileLinkServer.PROTOCOL_VERSION,
            "type": "error",
            "payload": {"message": message},
        }))

    @staticmethod
    async def _close_unauthorized(websocket, reason):
        close = getattr(websocket, "close", None)
        if close:
            try:
                await close(code=1008, reason=reason)
            except Exception:
                LOGGER.debug("No se pudo cerrar el cliente Mobile", exc_info=True)
