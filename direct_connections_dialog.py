"""Desktop controls for opt-in Bluetooth and Wi-Fi Direct receivers."""

import io
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget, QMessageBox,
)
from styles import DARK_THEME, LIGHT_THEME


def local_connection_urls(port):
    addresses = []
    for interface in QNetworkInterface.allInterfaces():
        if not interface.flags() & QNetworkInterface.InterfaceFlag.IsUp:
            continue
        for entry in interface.addressEntries():
            ip = entry.ip()
            if ip.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol and not ip.isLoopback():
                addresses.append((interface.humanReadableName(), f"ws://{ip.toString()}:{port}"))
    return addresses


class DirectConnectionsDialog(QDialog):
    def __init__(self, connections, parent=None):
        super().__init__(parent)
        self.connections = connections
        self.controls = {}
        self._pending_qr = set()
        self.setWindowTitle("Conexiones directas Mobile — NUMA Deck")
        self.resize(660, 460)
        is_dark = bool(getattr(parent, "is_dark_mode", False))
        t = DARK_THEME if is_dark else LIGHT_THEME

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        header = QLabel("Conexión directa con tu teléfono", self)
        header.setObjectName("directConnTitle")
        layout.addWidget(header)

        subtitle = QLabel(
            "Usa Bluetooth o Wi-Fi Direct si tu computadora y tu teléfono no comparten la misma red Wi-Fi. "
            "Pulsa «QR» para activar y emparejar en un paso.",
            self,
        )
        subtitle.setObjectName("directConnSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        tabs = QTabWidget(self)
        layout.addWidget(tabs)
        for mode, title in (("bluetooth", "Bluetooth"), ("wifi_direct", "Wi-Fi Direct")):
            page = QWidget()
            form = QFormLayout(page)
            form.setContentsMargins(16, 16, 16, 14)
            form.setSpacing(10)
            status = QLabel()
            status.setWordWrap(True)
            form.addRow("Estado", status)
            fields = {}
            definitions = (("service_name", "Servicio"), ("service_uuid", "UUID")) if mode == "bluetooth" else (
                ("ssid", "Red"), ("password", "Clave Wi-Fi"))
            for key, label in definitions:
                field = QLineEdit()
                field.setReadOnly(True)
                field.setToolTip("Generado automáticamente al activar la conexión")
                form.addRow(label, field)
                fields[key] = field
            token = QLineEdit(connections.receiver.auth_token)
            token.setReadOnly(True)
            token.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("Token Mobile", token)
            if mode == "wifi_direct":
                endpoints = QLabel()
                endpoints.setWordWrap(True)
                form.addRow("Direcciones locales", endpoints)
                fields["endpoints"] = endpoints
            row = QHBoxLayout()
            row.setSpacing(8)
            start = QPushButton("Activar")
            start.setObjectName("softBlueBtn")
            stop = QPushButton("Desactivar")
            copy = QPushButton("Copiar emparejamiento")
            qr = QPushButton("Mostrar QR")
            qr.setObjectName("primaryBtn")
            qr.setToolTip("Activar conexión y mostrar QR de emparejamiento")
            start.clicked.connect(lambda checked=False, m=mode: connections.start(m))
            stop.clicked.connect(lambda checked=False, m=mode: connections.stop(m))
            copy.clicked.connect(lambda checked=False, m=mode: self._copy(m))
            qr.clicked.connect(lambda checked=False, m=mode: self._request_qr(m))
            row.addWidget(start)
            row.addWidget(stop)
            row.addWidget(copy)
            row.addWidget(qr)
            form.addRow(row)
            self.controls[mode] = (status, fields, start, stop, copy, qr)
            tabs.addTab(page, title)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t['background']};
                color: {t['text-primary']};
            }}
            QLabel#directConnTitle {{
                color: {t['text-primary']};
                font-size: 18px;
                font-weight: 800;
            }}
            QLabel#directConnSubtitle {{
                color: {t['text-secondary']};
                font-size: 12px;
            }}
            QTabWidget::pane {{
                border: 1.5px solid {t['border-subtle']};
                border-radius: 12px;
                background-color: {t['surface']};
            }}
            QTabBar::tab {{
                background-color: {t['surface-alt']};
                color: {t['text-secondary']};
                border: 1.5px solid {t['border-subtle']};
                border-bottom: none;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                padding: 7px 16px;
                margin-right: 4px;
                font-weight: 700;
            }}
            QTabBar::tab:selected {{
                background-color: {t['electric-blue']};
                color: #FFFFFF;
                border-color: {t['electric-blue']};
            }}
            QLineEdit {{
                background-color: {t['surface-alt']};
                color: {t['text-primary']};
                border: 1.5px solid {t['border-subtle']};
                border-radius: 8px;
                padding: 5px 10px;
            }}
        """)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.finished.connect(lambda result: self._pending_qr.clear())
        self.finished.connect(lambda result: self.timer.stop())
        self.refresh()

    def _request_qr(self, mode):
        state, _ = self.connections.snapshot(mode)
        if state == "ready":
            self._show_qr(mode)
            return
        self._pending_qr.add(mode)
        if state != "starting":
            self.connections.start(mode)
        self.refresh()

    def _copy(self, mode):
        try:
            payload = self.connections.pairing_payload(mode)
        except RuntimeError:
            self.refresh()
            return
        QApplication.clipboard().setText(payload)

    def refresh(self):
        labels = {"off": "Desactivado", "starting": "Activando...", "ready": "Disponible", "error": "Error"}
        ready_qr = []
        for mode, (status, fields, start, stop, copy, qr) in self.controls.items():
            state, details = self.connections.snapshot(mode)
            status.setText(labels[state] + (": " + details["error"] if details.get("error") else ""))
            if details.get("connection_error"):
                status.setText(status.text() + ": " + details["connection_error"])
            for key, field in fields.items():
                if key != "endpoints":
                    field.setText(str(details.get(key, "")))
            if "endpoints" in fields:
                urls = local_connection_urls(self.connections.receiver.port) if state == "ready" else []
                fields["endpoints"].setText("\n".join(f"{name}: {url}" for name, url in urls) or "Sin direccion IPv4 disponible")
            start.setEnabled(state in ("off", "error"))
            stop.setEnabled(state in ("starting", "ready", "error"))
            copy.setEnabled(state == "ready")
            qr.setEnabled(mode not in self._pending_qr)
            if mode in self._pending_qr:
                if state == "ready":
                    self._pending_qr.remove(mode)
                    ready_qr.append(mode)
                    qr.setEnabled(True)
                elif state in ("off", "error"):
                    self._pending_qr.remove(mode)
                    qr.setEnabled(True)
        for mode in ready_qr:
            self._show_qr(mode)

    def _show_qr(self, mode):
        try:
            import qrcode
            payload = self.connections.pairing_payload(mode)
            data = io.BytesIO()
            qrcode.make(payload).save(data, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(data.getvalue(), "PNG")
        except Exception as error:
            QMessageBox.warning(self, "QR", "No se pudo generar el QR: " + type(error).__name__)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Emparejar " + ("Bluetooth" if mode == "bluetooth" else "Wi-Fi Direct"))
        layout = QVBoxLayout(dialog)
        label = QLabel()
        label.setPixmap(pixmap.scaled(460, 460, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.FastTransformation))
        layout.addWidget(label)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()
