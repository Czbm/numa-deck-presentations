"""Opt-in Windows direct transports for the existing authenticated Mobile protocol."""

import asyncio
import json
import logging
import secrets
import sys
import threading
from uuid import UUID

from PySide6.QtCore import QObject, Signal


LOGGER = logging.getLogger("numa.direct_connections")
BLUETOOTH_SERVICE_UUID = UUID("da291c95-9964-47c5-b2b9-c6b3d513cb87")


class JsonLineBuffer:
    """RFCOMM is a byte stream: retain partial UTF-8 messages until newline."""

    def __init__(self, limit=64 * 1024):
        self.limit = limit
        self.pending = bytearray()

    def feed(self, data):
        self.pending.extend(data)
        messages = []
        while b"\n" in self.pending:
            line, _, rest = self.pending.partition(b"\n")
            if len(line) > self.limit:
                raise ValueError("Mensaje Bluetooth demasiado grande")
            self.pending = bytearray(rest)
            messages.append(line.decode("utf-8"))
        if len(self.pending) > self.limit:
            raise ValueError("Mensaje Bluetooth demasiado grande")
        return messages


class BluetoothJsonChannel:
    """Adapt RFCOMM JSON-lines to MobileLinkServer's validated client handler."""

    path = ""

    def __init__(self, stream, limit):
        from winrt.windows.storage.streams import DataReader, DataWriter, InputStreamOptions
        self.stream = stream
        self.reader = DataReader(stream.input_stream)
        self.reader.input_stream_options = InputStreamOptions.PARTIAL
        self.writer = DataWriter(stream.output_stream)
        self.buffer = JsonLineBuffer(limit)
        self.messages = []
        self.closed = False
        self.first_message = True
        self.remote_address = "bluetooth:" + str(stream.information.remote_host_name.raw_name)

    def __aiter__(self):
        return self

    async def __anext__(self):
        async def read_message():
            while not self.messages and not self.closed:
                count = await self.reader.load_async(4096)
                if count == 0:
                    raise StopAsyncIteration
                data = bytearray(count)
                self.reader.read_bytes(data)
                self.messages.extend(self.buffer.feed(data))
            if self.closed:
                raise StopAsyncIteration
            return self.messages.pop(0)
        if self.first_message:
            message = await asyncio.wait_for(read_message(), timeout=15)
            self.first_message = False
            return message
        return await read_message()

    async def send(self, message):
        self.writer.write_bytes((message + "\n").encode("utf-8"))
        await self.writer.store_async()

    async def close(self, **kwargs):
        if self.closed:
            return
        self.closed = True
        for resource in (self.reader, self.writer, self.stream):
            try:
                resource.close()
            except Exception:
                LOGGER.debug("Cierre de stream Bluetooth", exc_info=True)


class DirectTransportWorker:
    """Each transport owns its WinRT apartment, async loop and native resources."""

    def __init__(self, owner, mode):
        self.owner = owner
        self.mode = mode
        self.thread = None
        self.loop = None
        self.stop_requested = threading.Event()
        self.resources = []
        self.tasks = set()
        self.event_tokens = []
        self.sockets = set()
        self.devices = []
        self.stop_signal = None
        self.start_task = None
        self.details = {}

    def start(self):
        self.thread = threading.Thread(target=self._thread_main, name="numa-" + self.mode, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_requested.set()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._request_stop)
        if self.thread:
            self.thread.join(timeout=4)
        return not self.thread or not self.thread.is_alive()

    def _request_stop(self):
        if self.stop_signal:
            self.stop_signal.set()
        for task in tuple(self.tasks):
            task.cancel()
        if self.start_task and not self.start_task.done():
            self.start_task.cancel()

    def _thread_main(self):
        initialized = False
        failed = False
        try:
            if sys.platform != "win32":
                raise RuntimeError("Las conexiones directas requieren Windows")
            from winrt.runtime import init_apartment, uninit_apartment, ApartmentType
            init_apartment(ApartmentType.MULTI_THREADED)
            initialized = True
            asyncio.run(self._run())
        except Exception as error:
            failed = True
            LOGGER.exception("No se pudo activar %s", self.mode)
            message = str(error) or ("Windows no respondio durante la activacion" if isinstance(error, TimeoutError) else type(error).__name__)
            self.owner._publish(self.mode, "error", {"error": message})
        finally:
            if initialized:
                uninit_apartment()
            if not failed and self.owner.snapshot(self.mode)[0] != "error":
                self.owner._publish(self.mode, "off", {})

    async def _run(self):
        self.loop = asyncio.get_running_loop()
        self.stop_signal = asyncio.Event()
        try:
            starter = self._start_bluetooth if self.mode == "bluetooth" else self._start_wifi
            self.start_task = asyncio.create_task(starter())
            await asyncio.wait_for(self.start_task, timeout=25)
            if not self.stop_requested.is_set():
                self.owner._publish(self.mode, "ready", self.details)
                await self.stop_signal.wait()
        except asyncio.CancelledError:
            if not self.stop_requested.is_set():
                raise
        finally:
            for obj, remove, token in reversed(self.event_tokens):
                try:
                    getattr(obj, remove)(token)
                except Exception:
                    LOGGER.debug("Retirada de evento WinRT", exc_info=True)
            for obj, method in reversed(self.resources):
                try:
                    getattr(obj, method)()
                except Exception:
                    LOGGER.debug("Cierre de recurso WinRT", exc_info=True)
            for stream in tuple(self.sockets):
                stream.close()
            for task in tuple(self.tasks):
                task.cancel()
            if self.tasks:
                await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
            for device in self.devices:
                device.close()
            self.loop = None

    def _track(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _start_bluetooth(self):
        from winrt.windows.devices.bluetooth.rfcomm import RfcommServiceId, RfcommServiceProvider
        from winrt.windows.networking.sockets import StreamSocketListener, SocketProtectionLevel
        from winrt.windows.storage.streams import DataWriter
        provider = await RfcommServiceProvider.create_async(RfcommServiceId.from_uuid(BLUETOOTH_SERVICE_UUID))
        if provider is None:
            raise RuntimeError("Windows no autoriza el servicio Bluetooth")
        listener = StreamSocketListener()
        self.resources.extend([(listener, "close"), (provider, "stop_advertising")])

        def connected(sender, args):
            stream = args.socket
            try:
                self.loop.call_soon_threadsafe(self._queue_bluetooth, stream)
            except (RuntimeError, AttributeError):
                stream.close()

        token = listener.add_connection_received(connected)
        self.event_tokens.append((listener, "remove_connection_received", token))
        await listener.bind_service_name_with_protection_level_async(
            provider.service_id.as_string(), SocketProtectionLevel.BLUETOOTH_ENCRYPTION_WITH_AUTHENTICATION)
        name = b"NUMA Deck Mobile"
        writer = DataWriter()
        writer.write_byte(0x25)
        writer.write_byte(len(name))
        writer.write_bytes(name)
        provider.sdp_raw_attributes[0x100] = writer.detach_buffer()
        writer.close()
        provider.start_advertising_with_radio_discoverability(listener, True)
        self.details = {"service_uuid": str(BLUETOOTH_SERVICE_UUID), "service_name": name.decode()}

    def _queue_bluetooth(self, stream):
        if self.stop_requested.is_set():
            stream.close()
        else:
            self._track(self._handle_bluetooth(stream))

    async def _handle_bluetooth(self, stream):
        channel = None
        if self.stop_requested.is_set() or len(self.sockets) >= 4:
            stream.close()
            return
        self.sockets.add(stream)
        try:
            channel = BluetoothJsonChannel(stream, self.owner.receiver.MAX_MESSAGE_BYTES)
            await self.owner.receiver._handle_client(channel)
        except Exception:
            LOGGER.exception("Conexion Bluetooth finalizada con error")
        finally:
            if channel:
                await channel.close()
            else:
                stream.close()
            self.sockets.discard(stream)

    async def _start_wifi(self):
        from winrt.windows.devices.wifidirect import (
            WiFiDirectAdvertisementPublisher, WiFiDirectConnectionListener,
            WiFiDirectAdvertisementListenStateDiscoverability,
            WiFiDirectAdvertisementPublisherStatus,
        )
        from winrt.windows.security.credentials import PasswordCredential
        publisher = WiFiDirectAdvertisementPublisher()
        self.resources.append((publisher, "stop"))
        advertisement = publisher.advertisement
        advertisement.is_autonomous_group_owner_enabled = True
        advertisement.listen_state_discoverability = WiFiDirectAdvertisementListenStateDiscoverability.NORMAL
        advertisement.legacy_settings.is_enabled = True
        ssid = "NUMA-Deck-" + secrets.token_hex(3).upper()
        password = secrets.token_urlsafe(12)
        credential = PasswordCredential()
        credential.password = password
        advertisement.legacy_settings.ssid = ssid
        advertisement.legacy_settings.passphrase = credential
        def status_changed(sender, args):
            def update():
                if self.stop_requested.is_set():
                    return
                if args.status in (WiFiDirectAdvertisementPublisherStatus.ABORTED,
                                    WiFiDirectAdvertisementPublisherStatus.STOPPED):
                    if self.owner.snapshot(self.mode)[0] == "ready":
                        error = "Windows detuvo Wi-Fi Direct: " + str(args.error)
                        self.owner._publish(self.mode, "error", {"error": error})
                        self._request_stop()
            if self.loop:
                self.loop.call_soon_threadsafe(update)

        token = publisher.add_status_changed(status_changed)
        self.event_tokens.append((publisher, "remove_status_changed", token))
        listener = WiFiDirectConnectionListener()

        def requested(sender, args):
            request = args.get_connection_request()
            if self.loop:
                self.loop.call_soon_threadsafe(self._queue_wifi, request)
            else:
                request.close()

        token = listener.add_connection_requested(requested)
        self.event_tokens.append((listener, "remove_connection_requested", token))
        publisher.start()
        while publisher.status != WiFiDirectAdvertisementPublisherStatus.STARTED:
            if publisher.status == WiFiDirectAdvertisementPublisherStatus.ABORTED:
                raise RuntimeError("Windows rechazo la publicacion Wi-Fi Direct; revisa el adaptador y sus permisos")
            await asyncio.sleep(0.2)
        self.details = {"ssid": ssid, "password": password, "port": self.owner.receiver.port}

    def _queue_wifi(self, request):
        if self.stop_requested.is_set():
            request.close()
        else:
            self._track(self._accept_wifi(request))

    async def _accept_wifi(self, request):
        from winrt.windows.devices.wifidirect import WiFiDirectDevice
        try:
            device = await asyncio.wait_for(WiFiDirectDevice.from_id_async(request.device_information.id), 20)
            if device:
                self.devices.append(device)
        except Exception as error:
            self.owner._publish("wifi_direct", "ready", dict(self.details, connection_error=str(error)))
        finally:
            request.close()


class DirectConnections(QObject):
    status_changed = Signal(str, str, dict)

    def __init__(self, receiver, parent=None):
        super().__init__(parent)
        self.receiver = receiver
        self.workers = {}
        self.states = {"bluetooth": ("off", {}), "wifi_direct": ("off", {})}
        self.lock = threading.RLock()

    def _publish(self, mode, state, details):
        with self.lock:
            self.states[mode] = (state, dict(details))
        self.status_changed.emit(mode, state, dict(details))

    def snapshot(self, mode):
        with self.lock:
            state, details = self.states[mode]
            return state, dict(details)

    def start(self, mode):
        if mode not in self.states:
            raise ValueError("Transporte desconocido")
        if mode == "wifi_direct" and not self.receiver.is_listening:
            self._publish(mode, "error", {"error": "El receptor de red no esta escuchando; revisa su puerto antes de activar Wi-Fi Direct"})
            return False
        worker = self.workers.get(mode)
        if worker and worker.thread and worker.thread.is_alive():
            return False
        worker = DirectTransportWorker(self, mode)
        self.workers[mode] = worker
        self._publish(mode, "starting", {})
        worker.start()
        return True

    def stop(self, mode):
        worker = self.workers.get(mode)
        if worker and not worker.stop():
            self._publish(mode, "error", {"error": "El transporte sigue cerrando; espera antes de reactivarlo"})
            return False
        self._publish(mode, "off", {})
        return True

    def stop_all(self):
        return all([self.stop(mode) for mode in tuple(self.workers)])

    def pairing_payload(self, mode):
        state, details = self.snapshot(mode)
        if state != "ready":
            raise RuntimeError("El transporte no esta disponible")
        return json.dumps({"format": "NUMA-DIRECT", "version": 1, "transport": mode,
                           "token": self.receiver.auth_token, **details}, ensure_ascii=True)
