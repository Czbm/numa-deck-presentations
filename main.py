import sys
import atexit
import faulthandler
import io
import os
import json
import re
import hashlib
import time
import logging
import platform
import ctypes
import socket
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from PySide6.QtCore import (
    Qt, QSize, QTimer, QDir, QUrl, QPoint, QRect, Signal, QEvent, QLockFile, qInstallMessageHandler
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QFileDialog, QMessageBox, QLabel, QFrame,
    QPushButton, QToolBar, QStatusBar, QDialog, QSizePolicy,
    QTreeWidget, QTreeWidgetItem, QComboBox, QTabBar, QInputDialog, QSpinBox,
    QDialogButtonBox, QLayout, QLineEdit, QCheckBox, QStackedLayout, QMenu, QGridLayout,
    QToolButton, QWidgetAction, QKeySequenceEdit
)
from PySide6.QtGui import QAction, QIcon, QKeySequence, QFont, QShortcut, QPixmap, QTextCursor, QTextDocument, QColor

from styles import get_app_stylesheet, LIGHT_THEME, DARK_THEME
from onboarding_dialogs import TemplatePickerDialog, QuickGuideDialog
from editor import MarkdownEditor
from preview import PresentationView
from parser import (
    DOCUMENT_ALIGNMENT_PATTERN,
    _iter_markdown_image_links,
    create_sync_id,
    clear_slide_sync_ids,
    clear_slide_sync_id,
    create_slide_id_marker,
    ensure_slide_ids,
    find_markdown_image_at_position,
    filter_slides_with_file_links,
    find_broken_local_image_links,
    find_broken_internal_slide_links,
    find_broken_slide_id_links,
    get_slide_metadata,
    get_image_display_options,
    replace_internal_slide_link,
    replace_slide_id_link,
    repair_broken_local_image_links,
    set_slide_sync_id,
)
from mobile_link import MobileLinkServer
from direct_connections import DirectConnections
from direct_connections_dialog import DirectConnectionsDialog
from presentation_controller import PresentationController
from recovery_service import RecoveryService
from version import APP_NAME, APP_VERSION


LOGGER = logging.getLogger("numa")
LOG_PATH = None
SESSION_MARKER_PATH = None
FAULT_LOG_HANDLE = None
SESSION_LOG_HANDLE = None


def _write_session_diagnostic(message):
    """Write a direct session record even if the rotating logger is unavailable."""
    if SESSION_LOG_HANDLE is None:
        return
    try:
        SESSION_LOG_HANDLE.write(
            "{0} | pid={1} | {2}\n".format(
                time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), message
            )
        )
        SESSION_LOG_HANDLE.flush()
    except Exception:
        pass


def configure_logging():
    """Create a persistent diagnostic log before the Qt application starts."""
    global LOG_PATH, SESSION_MARKER_PATH, FAULT_LOG_HANDLE, SESSION_LOG_HANDLE
    if LOGGER.handlers:
        return LOG_PATH

    try:
        app_data = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        log_dir = app_data / "NUMA Deck Presentations" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        LOG_PATH = log_dir / "numa.log"
        SESSION_MARKER_PATH = log_dir / "numa.session.json"
        SESSION_LOG_HANDLE = open(
            log_dir / "numa_session.log", "a", encoding="utf-8", buffering=1
        )
        _write_session_diagnostic("configure_logging iniciado")
        handler = RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=4, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        ))
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.DEBUG)
        LOGGER.propagate = False
        _write_session_diagnostic("handler rotativo instalado path={0}".format(LOG_PATH))
        if SESSION_MARKER_PATH.exists():
            try:
                previous = SESSION_MARKER_PATH.read_text(encoding="utf-8")
            except Exception as error:
                previous = f"<no se pudo leer el marcador: {type(error).__name__}>"
            LOGGER.critical("Sesion anterior sin cierre limpio | marker=%s | datos=%s", SESSION_MARKER_PATH, previous)

        SESSION_MARKER_PATH.write_text(
            json.dumps({
                "pid": os.getpid(),
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "python": sys.version,
                "platform": platform.platform(),
                "cwd": os.getcwd(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        FAULT_LOG_HANDLE = open(log_dir / "numa_fault.log", "a", encoding="utf-8")
        faulthandler.enable(file=FAULT_LOG_HANDLE, all_threads=True)
        FAULT_LOG_HANDLE.write(
            "\n--- NUMA FAULT SESSION pid={0} started_at={1} python={2} platform={3} ---\n".format(
                os.getpid(),
                time.strftime("%Y-%m-%d %H:%M:%S"),
                platform.python_version(),
                platform.platform(),
            )
        )
        FAULT_LOG_HANDLE.flush()
        LOGGER.info("Inicio de NUMA | Python=%s | Plataforma=%s", sys.version, platform.platform())
        _write_session_diagnostic("Inicio de NUMA registrado")
    except Exception as error:
        # Logging must never prevent the application from opening.
        _write_session_diagnostic("ERROR configurando logging: {0}: {1}".format(type(error).__name__, error))
        LOG_PATH = None
    return LOG_PATH


def _mark_clean_shutdown():
    """Remove the session marker only after Qt reports a normal shutdown."""
    if SESSION_MARKER_PATH:
        try:
            SESSION_MARKER_PATH.unlink(missing_ok=True)
        except Exception:
            LOGGER.exception("No se pudo eliminar el marcador de cierre limpio")
    if FAULT_LOG_HANDLE:
        try:
            FAULT_LOG_HANDLE.flush()
        except Exception:
            pass


def _flush_fault_log():
    if FAULT_LOG_HANDLE:
        try:
            FAULT_LOG_HANDLE.write(
                "--- NUMA FAULT SESSION END pid={0} ended_at={1} ---\n".format(
                    os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S")
                )
            )
            FAULT_LOG_HANDLE.flush()
            FAULT_LOG_HANDLE.close()
        except Exception:
            pass
    if SESSION_LOG_HANDLE:
        try:
            _write_session_diagnostic("fin del proceso de logging")
            SESSION_LOG_HANDLE.flush()
            SESSION_LOG_HANDLE.close()
        except Exception:
            pass


atexit.register(_flush_fault_log)


def _log_unhandled_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    LOGGER.critical("Excepcion no controlada", exc_info=(exc_type, exc_value, exc_traceback))
    _write_session_diagnostic("Excepcion no controlada: {0}: {1}".format(exc_type.__name__, exc_value))
    for handler in LOGGER.handlers:
        handler.flush()
    try:
        location = f"\n\nRegistro: {LOG_PATH}" if LOG_PATH else ""
        QMessageBox.critical(
            None,
            "Error inesperado",
            "NUMA encontro un error inesperado. Se registro el detalle para diagnostico." + location,
        )
    except Exception:
        pass


def _log_unraisable_exception(unraisable):
    """Record exceptions raised from destructors or other unraisable paths."""
    try:
        _write_session_diagnostic(
            "Excepcion no controlable: {0}: {1}".format(
                getattr(unraisable, "exc_type", type(None)).__name__,
                getattr(unraisable, "exc_value", None),
            )
        )
        LOGGER.critical(
            "Excepcion no controlable | object=%r | message=%s",
            getattr(unraisable, "object", None),
            getattr(unraisable, "err_msg", None),
            exc_info=(
                getattr(unraisable, "exc_type", None),
                getattr(unraisable, "exc_value", None),
                getattr(unraisable, "exc_traceback", None),
            ),
        )
    except Exception:
        pass


def _log_thread_exception(args):
    """Record exceptions that happen outside Qt's main thread."""
    try:
        _write_session_diagnostic(
            "Excepcion en hilo {0}: {1}: {2}".format(
                getattr(args.thread, "name", None), args.exc_type.__name__, args.exc_value
            )
        )
        LOGGER.critical(
            "Excepcion no controlada en hilo | thread=%s ident=%s",
            getattr(args.thread, "name", None),
            getattr(args.thread, "ident", None),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    except Exception:
        pass


def _log_qt_message(mode, context, message):
    """Include Qt and WebEngine diagnostics in NUMA's persistent log."""
    source = getattr(context, "file", None) or "Qt"
    line = getattr(context, "line", 0) or 0
    diagnostic = "Qt [{0}] pid={1} thread={2} {3}:{4} | {5}".format(
        mode, os.getpid(), threading.get_ident(), source, line, message
    )
    _write_session_diagnostic(diagnostic)
    LOGGER.warning(
        "Qt [%s] pid=%s thread=%s %s:%s | %s",
        mode,
        os.getpid(),
        threading.get_ident(),
        source,
        line,
        message,
    )


DEFAULT_MARKDOWN = """# Bienvenidos a NUMA Deck Presentations

Un editor y presentador de diapositivas rápido, moderno y lúdico, diseñado bajo las directrices visuales de **NUMA**.

---

## Características Clave

* **Editor Markdown en Tiempo Real**: Escribe tu contenido y mira la vista previa al instante.
* **Arrastrar y Soltar**: Arrastra cualquier imagen directamente al editor para vincularla.
* **Navegación Flexible**:
    * *Modo Diapositivas*: Diapositivas individuales separadas por `---`.
    * *Modo Continuo*: Lectura vertical tipo documento con scroll fluido.
    * *Modo Hoja Impresa*: Vista paginada lista para exportar o imprimir.
* **Diseño NUMA**: Superficies limpias, jerarquía clara y acentos expresivos en modo claro y oscuro.

---

## Crear Diapositivas

Para separar tu contenido en diapositivas individuales, escribe tres guiones `---` en una línea vacía.

```markdown
# Diapositiva 1
Contenido de la primera diapositiva.

---

# Diapositiva 2
Contenido de la segunda diapositiva.
```

---

## ¡Pruébalo Ahora!

1. Haz clic en **▶ PRESENTAR** en la barra superior (o presiona **F11**) para entrar en pantalla completa.
2. Usa las **Flechas del Teclado** (`←` / `→`) o la **Barra Espaciadora** para navegar por tus diapositivas.
3. Cambia entre **Modo Claro** y **Modo Oscuro** desde el selector de tema en la barra superior.
4. Ajusta el tamaño del texto con **Texto −** y **Texto +** en la vista previa.
"""


# ─────────────────────────────────────────────────────────────
# About Dialog
# ─────────────────────────────────────────────────────────────

class AboutDialog(QDialog):
    """NUMA-styled About dialog."""

    def __init__(self, parent=None, is_dark=False):
        super().__init__(parent)
        self.setWindowTitle("Acerca de NUMA Deck")
        self.resize(420, 280)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.is_dark = is_dark

        bg = "#0E1324" if is_dark else "#F7FAFF"
        surface = "#141B2F" if is_dark else "#FFFFFF"
        text = "#EEF2FF" if is_dark else "#111827"
        border = "#EEF2FF" if is_dark else "#0B0F1A"
        secondary = "#9CA3AF" if is_dark else "#6B7280"

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(28, 28, 28, 28)

        title = QLabel("NUMA Deck Presentations", self)
        title.setFont(QFont("Inter", 20, QFont.Bold))
        title.setStyleSheet(f"color: {text};")
        layout.addWidget(title)

        version = QLabel(f"Version {APP_VERSION}", self)
        version.setFont(QFont("Inter", 11))
        version.setStyleSheet(f"color: {secondary};")
        layout.addWidget(version)

        layout.addSpacing(8)

        desc = QLabel(
            "Editor y presentador de diapositivas Markdown.\n"
            "Disenado con el Sistema de Diseno NUMA.\n\n"
            "Neobrutalism estructural + Material Expressive.\n"
            "Cálido, moderno, lúdico sin ser infantil.",
            self
        )
        desc.setFont(QFont("Inter", 11))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {text};")
        layout.addWidget(desc)

        layout.addStretch()

        close_btn = QPushButton("Cerrar", self)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg};
                border: 3px solid {border};
                border-radius: 14px;
            }}
            QPushButton {{
                background-color: {surface};
                color: {text};
                border: 2px solid {border};
                border-radius: 10px;
                padding: 10px 24px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: #2563FF;
                color: #FFFFFF;
            }}
            QPushButton:pressed {{
                margin-top: 2px;
                margin-left: 2px;
            }}
        """)


class PdfPreviewDialog(QDialog):
    """Preview the PDF export render before printing."""

    def __init__(self, md_text, base_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vista previa antes de exportar PDF")
        self.resize(1180, 760)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.source_md_text = md_text
        self.base_path = base_path
        self.export_md_text = md_text
        self.export_mode = "slides"
        filtered_text, removed_count, kept_count = filter_slides_with_file_links(md_text)
        self.filtered_md_text = filtered_text
        self.file_link_slide_count = removed_count
        self.filtered_slide_count = kept_count

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Revisa que las imagenes y enlaces internos se vean correctamente antes de exportar.", self)
        header.setObjectName("pdfPreviewHeader")
        layout.addWidget(header)

        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("Formato de exportacion:", self))
        self.pdf_format_combo = QComboBox(self)
        self.pdf_format_combo.addItem("Presentacion 16:9 horizontal", "slides")
        self.pdf_format_combo.addItem("Documento carta vertical", "document")
        self.pdf_format_combo.addItem("Hoja impresa (configuracion actual)", "paper")
        format_row.addWidget(self.pdf_format_combo)
        format_row.addStretch(1)
        layout.addLayout(format_row)

        self.skip_file_links_checkbox = QCheckBox(
            f"Omitir slides con enlaces a archivos locales ({removed_count} detectados)",
            self,
        )
        self.skip_file_links_checkbox.setEnabled(removed_count > 0)
        self.skip_file_links_checkbox.setToolTip(
            "Excluye los slides con enlaces clicables a archivos locales. "
            "Las imagenes, enlaces web y enlaces internos se conservan."
        )
        layout.addWidget(self.skip_file_links_checkbox)

        is_dark = getattr(parent, "is_dark_mode", False)
        self.preview = PresentationView(self, is_dark=is_dark)
        if parent and hasattr(parent, "preview"):
            self.preview.presentation_mode = parent.preview.presentation_mode
            self.preview.font_size = parent.preview.font_size
            self.preview.zoom_factor = parent.preview.visible_zoom_factor()
            self.preview.borderless = parent.preview.borderless
            self.preview.clock_visible = parent.preview.clock_visible
            self.preview.clock_mode = parent.preview.clock_mode
            self.preview.clock_show_seconds = parent.preview.clock_show_seconds
            self.preview.clock_size = parent.preview.clock_size
            self.preview.clock_position = parent.preview.clock_position
            self.preview.timer_duration_seconds = parent.preview.timer_duration_seconds
            self.preview.timer_elapsed_seconds = parent.preview.timer_elapsed_seconds
            self.preview.timer_running = parent.preview.timer_running
            self.preview._timer_started_at = parent.preview._timer_started_at
            self.preview.output_width = parent.preview.output_width
            self.preview.output_height = parent.preview.output_height
            self.preview.output_aspect_ratio = parent.preview.output_aspect_ratio
            self.preview.paper_size = parent.preview.paper_size
            self.preview.paper_orientation = parent.preview.paper_orientation
            self.preview.paper_title = parent.preview.paper_title
            self.preview.paper_subtitle = parent.preview.paper_subtitle
            self.preview.paper_header_mode = parent.preview.paper_header_mode
            self.preview.paper_footer_mode = parent.preview.paper_footer_mode
            self.preview.paper_custom_header = parent.preview.paper_custom_header
            self.preview.paper_header_right_mode = parent.preview.paper_header_right_mode
            self.preview.paper_header_right_text = parent.preview.paper_header_right_text
            self.preview.paper_footer_left_mode = parent.preview.paper_footer_left_mode
            self.preview.paper_footer_left_text = parent.preview.paper_footer_left_text
            self.preview.paper_font_scale = parent.preview.paper_font_scale
            if parent.preview.presentation_mode == "paper":
                self.export_mode = "paper"
                self.pdf_format_combo.setCurrentIndex(self.pdf_format_combo.count() - 1)

        self._render_export_preview(md_text)
        layout.addWidget(self.preview, stretch=1)

        buttons = QDialogButtonBox(self)
        self.export_button = buttons.addButton("Exportar PDF", QDialogButtonBox.ButtonRole.AcceptRole)
        self.export_button.setObjectName("primaryBtn")
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.skip_file_links_checkbox.toggled.connect(self._toggle_file_link_slides)
        self.pdf_format_combo.currentIndexChanged.connect(self._change_pdf_format)

        t = DARK_THEME if is_dark else LIGHT_THEME
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t['background']};
                color: {t['text-primary']};
            }}
            QLabel#pdfPreviewHeader {{
                color: {t['text-primary']};
                font-size: 13px;
                font-weight: 700;
            }}
        """)

    def _toggle_file_link_slides(self, skip):
        self.export_md_text = self.filtered_md_text if skip else self.source_md_text
        has_slides = bool(self.export_md_text.strip())
        self.export_button.setEnabled(has_slides)
        if skip and not has_slides:
            self._render_export_preview(
                "# No hay slides para exportar\n\nTodos contienen enlaces a archivos locales.",
            )
            return
        self._render_export_preview(self.export_md_text)

    def _change_pdf_format(self):
        self.export_mode = self.pdf_format_combo.currentData() or "slides"
        self._toggle_file_link_slides(self.skip_file_links_checkbox.isChecked())

    def _render_export_preview(self, markdown_text):
        """Render the paper option exactly as the active in-app paper preview."""
        is_paper_export = self.export_mode == "paper"
        if is_paper_export:
            # The dialog is a visual check. Use the normal paper renderer here
            # so its sheet dimensions and text scale match the workspace; the
            # print-only renderer is used later for the final PDF operation.
            self.preview.presentation_mode = "paper"
        self.preview.set_content(
            markdown_text,
            pdf_export=not is_paper_export,
            base_path=self.base_path,
            pdf_mode=self.export_mode,
        )


class PresentationOutputWindow(QMainWindow):
    """Dedicated fullscreen presentation window for the student/output screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NUMA Presentacion - Salida")
        self._content = QWidget(self)
        self._content_stack = QStackedLayout(self._content)
        self._content_stack.setContentsMargins(0, 0, 0, 0)
        self.preview = PresentationView(self, is_dark=getattr(parent, "is_dark_mode", False))
        self.preview.set_preview_canvas(False)
        self.cast_label = QLabel(self._content)
        self.cast_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cast_label.setStyleSheet("background: #000000;")
        self.cast_label.setScaledContents(False)
        self._content_stack.addWidget(self.preview)
        self._content_stack.addWidget(self.cast_label)
        self.setCentralWidget(self._content)
        self._shortcuts = []
        self.cast_mode = False
        self._cast_frame = QPixmap()

    def set_cast_mode(self, enabled):
        self.cast_mode = bool(enabled)
        self._content_stack.setCurrentWidget(self.cast_label if self.cast_mode else self.preview)

    def update_cast_frame(self, pixmap):
        """Display the exact visual frame emitted by the teacher console."""
        if not self.cast_mode or pixmap is None or pixmap.isNull():
            return
        self._cast_frame = pixmap
        self._render_cast_frame()

    def _render_cast_frame(self):
        if self._cast_frame.isNull() or self.cast_label.size().isEmpty():
            return
        # The source pane occupies only the upper half of the teacher console.
        # A projector must use its whole monitor instead of inheriting that
        # pane's height; scale the visual cast to the output surface.
        self.cast_label.setPixmap(self._cast_frame.scaled(
            self.cast_label.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_cast_frame()


class DualPresentationControlWindow(QMainWindow):
    """Fullscreen teacher console: student above, teacher below."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NUMA Presentacion - Control dual")
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.splitter = QSplitter(Qt.Orientation.Vertical, container)
        self.splitter.setChildrenCollapsible(False)
        self.student_preview = PresentationView(self.splitter, is_dark=getattr(parent, "is_dark_mode", False))
        self.teacher_preview = PresentationView(self.splitter, is_dark=getattr(parent, "is_dark_mode", False))
        self.student_preview.set_preview_canvas(False)
        self.teacher_preview.set_preview_canvas(False)
        self.splitter.addWidget(self.student_preview)
        self.splitter.addWidget(self.teacher_preview)
        self.splitter.setSizes([1, 1])
        layout.addWidget(self.splitter)
        self.setCentralWidget(container)
        self._shortcuts = []


class FlowLayout(QLayout):
    """Compact wrapping layout for toolbar controls."""

    def __init__(self, parent=None, margin=0, spacing=4):
        super().__init__(parent)
        self.item_list = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self.item_list.append(item)

    def count(self):
        return len(self.item_list)

    def itemAt(self, index):
        if 0 <= index < len(self.item_list):
            return self.item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.item_list):
            return self.item_list.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return QSize(900, self.heightForWidth(900))

    def minimumSize(self):
        height = 0
        for item in self.item_list:
            height = max(height, item.minimumSize().height())
        margins = self.contentsMargins()
        return QSize(0, height + margins.top() + margins.bottom())

    def _do_layout(self, rect, test_only=False):
        margins = self.contentsMargins()
        left = rect.x() + margins.left()
        top = rect.y() + margins.top()
        x = left
        y = top
        line_height = 0
        right = rect.right() - margins.right()

        for item in self.item_list:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            space_x = self.spacing()
            space_y = self.spacing()
            item_size = item.sizeHint()
            next_x = x + item_size.width() + space_x
            if x > left and next_x - space_x > right:
                x = left
                y = y + line_height + space_y
                next_x = x + item_size.width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x = next_x
            line_height = max(line_height, item_size.height())

        return y + line_height - rect.y() + margins.bottom()


class FlowToolbar(QWidget):
    """Widget that reports the height required by its wrapping layout."""

    MIN_TOOLBAR_HEIGHT = 30

    def __init__(self, parent=None, max_height=160):
        super().__init__(parent)
        self.max_toolbar_height = max_height

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        layout = self.layout()
        if layout and layout.hasHeightForWidth():
            return layout.heightForWidth(width)
        return super().heightForWidth(width)

    def sizeHint(self):
        height = self.heightForWidth(1200)
        height = max(self.MIN_TOOLBAR_HEIGHT, min(self.max_toolbar_height, height))
        return QSize(1200, height)

    def minimumSizeHint(self):
        return QSize(0, self.MIN_TOOLBAR_HEIGHT)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        target_height = self.heightForWidth(max(1, self.width()))
        target_height = max(self.MIN_TOOLBAR_HEIGHT, min(self.max_toolbar_height, target_height))
        if self.minimumHeight() != target_height or self.maximumHeight() != target_height:
            self.setMinimumHeight(target_height)
            self.setMaximumHeight(target_height)
            self.updateGeometry()


class DocumentTabBar(QTabBar):
    """Tab bar that can open a document from empty-space double clicks."""

    empty_space_double_clicked = Signal()

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        # Keep long Markdown filenames from consuming the whole tab strip.
        return QSize(min(size.width(), 238), size.height())

    def mouseDoubleClickEvent(self, event):
        if self.tabAt(event.pos()) == -1:
            self.empty_space_double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


# ─────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────

class NumaDeckWindow(QMainWindow):
    """
    Main Window of NUMA Deck Presentations application.
    """

    MAX_RECENT = 10  # Max recent files to remember
    SHORTCUT_DEFINITIONS = (
        ("presentar_f11", "Presentar / salir de pantalla completa (F11)", "F11", "toggle_fullscreen_presentation", "global"),
        ("presentar_f5", "Presentar / salir de pantalla completa (F5)", "F5", "toggle_fullscreen_presentation", "global"),
        ("presentacion_salir", "Salir de la presentacion", "Escape", "handle_presentation_escape", "presentation"),
        ("slide_anterior", "Slide anterior", "Left", "presentation_prev_slide", "presentation"),
        ("slide_siguiente", "Slide siguiente", "Right", "presentation_next_slide", "presentation"),
        ("slide_siguiente_espacio", "Slide siguiente (espacio)", "Space", "presentation_next_slide", "presentation"),
        ("slide_anterior_backspace", "Slide anterior (retroceso)", "Backspace", "presentation_prev_slide", "presentation"),
        ("slide_anterior_pageup", "Slide anterior (PageUp)", "PageUp", "presentation_prev_slide", "presentation"),
        ("slide_siguiente_pagedown", "Slide siguiente (PageDown)", "PageDown", "presentation_next_slide", "presentation"),
        ("profesor_anterior", "Slide anterior del profesor", "Q", "teacher_presentation_prev_slide", "presentation"),
        ("profesor_siguiente", "Slide siguiente del profesor", "W", "teacher_presentation_next_slide", "presentation"),
        ("alumno_texto_menos", "Reducir texto del alumno", "F9", "decrease_student_font_size", "presentation"),
        ("alumno_texto_mas", "Aumentar texto del alumno", "F10", "increase_student_font_size", "presentation"),
        ("profesor_texto_menos", "Reducir texto del profesor", "F7", "decrease_teacher_font_size", "presentation"),
        ("profesor_texto_mas", "Aumentar texto del profesor / Sin marco", "F8", "_handle_f8_presentation_shortcut", "presentation"),
        ("imagen_abrir", "Abrir imagen del slide actual", "Ctrl+I", "_open_presentation_image_from_shortcut", "presentation"),
        ("imagen_pantalla_completa", "Abrir o cerrar imagen a pantalla completa", "Alt+I", "_toggle_current_slide_image", "presentation"),
        ("imagen_zoom_mas", "Zoom in de la imagen abierta", "Ctrl+]", "_zoom_in_presentation_image_shortcut", "presentation"),
        ("imagen_zoom_menos", "Zoom out de la imagen abierta", "Ctrl+[", "_zoom_out_presentation_image_shortcut", "presentation"),
        ("zoom_mas", "Aumentar zoom", "Ctrl+=", "zoom_in", "global"),
        ("zoom_menos", "Disminuir zoom", "Ctrl+-", "zoom_out", "global"),
        ("zoom_restablecer", "Restablecer zoom", "Ctrl+0", "zoom_reset", "global"),
        ("barra_markdown", "Mostrar u ocultar barra Markdown", "Ctrl+Shift+M", "toggle_md_toolbar", "global"),
    )
    AUTOSAVE_RETENTION_DAYS = 3
    presentation_alt_tab_requested = Signal()
    presentation_navigation_key_down = Signal(str)
    presentation_navigation_key_up = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setWindowTitle("Sin titulo - NUMA Deck Presentations")
        self.resize(1280, 820)

        # State
        self.current_filepath = None
        self.is_dark_mode = False
        self.theme_preference = "system"
        self.is_fullscreen_presentation = False
        self.is_modified = False
        self.recent_files = []  # List of recently opened file paths
        self.file_preferences = {}
        self.tabs = []
        self.current_tab_index = -1
        self._loading_tab = False
        self._image_repair_checked_paths = set()
        self._continuous_preview_request = None
        self._continuous_preview_sync_scheduled = False
        self.project_root_path = os.path.dirname(os.path.abspath(__file__))
        self.nav_root_path = ""
        self.nav_mode = "slides"
        self.nav_panel_collapsed = False
        self.teacher_mode_enabled = False
        self._restore_editor_focus_pending = False
        self._last_saved_slide_index = 0
        self.teacher_script_path = None
        self.teacher_script_content = ""
        self.presentation_script_path = None
        self.presentation_script_content = ""
        self.teacher_preview_mode = "student"
        self.presentation_output_window = None
        self.teacher_local_presentation_window = None
        self.dual_control_window = None
        self._presentation_saved_preview_mode = None
        self._presentation_student_only_active = False
        self._presentation_next_press_at = 0.0
        self._presentation_prev_press_at = 0.0
        # Wireless presenters commonly emit PageUp/PageDown and have a
        # slightly slower repeat cadence than a keyboard double press.
        self._presentation_double_press_window = 0.80
        self._presentation_power_inhibited = False
        self._presentation_alt_tab_hook = None
        self._presentation_alt_tab_callback = None
        self._presentation_alt_tab_user32 = None
        self._presentation_alt_tab_tab_release = False
        self._presentation_synthetic_key_release = set()
        self._presentation_hook_event_count = 0
        self._presentation_hook_error_count = 0
        self._presentation_hook_last_event = None
        self._presentation_hook_last_error = None
        self._presentation_hold_pressed = set()
        self._presentation_hold_suppress_release = set()
        self._presentation_hold_direction = None
        self._presentation_hold_long_attempted = False
        self._presentation_hold_opened = False
        self._presentation_hold_timer = QTimer(self)
        self._presentation_hold_timer.setSingleShot(True)
        self._presentation_hold_timer.setInterval(650)
        self._presentation_hold_timer.timeout.connect(self._on_presentation_long_press)
        self._presentation_image_zoom_hold_direction = None
        self._presentation_image_zoom_hold_timer = QTimer(self)
        self._presentation_image_zoom_hold_timer.setInterval(140)
        self._presentation_image_zoom_hold_timer.timeout.connect(
            self._repeat_presentation_image_zoom
        )
        self._presentation_clock_override = None
        self._dual_interaction_request_id = 0
        self._dual_projection_state = None
        self._dual_projection_sync_pending = False
        self._dual_projection_sync_timer = QTimer(self)
        self._dual_projection_sync_timer.setInterval(120)
        self._dual_projection_sync_timer.timeout.connect(self._sync_dual_student_projection_state)
        self.dual_student_collapsed = False
        self.dual_teacher_collapsed = False
        self.present_teacher_locally = False
        self.split_editor_enabled = False
        self.editor_role = "student"
        self.teacher_is_modified = False
        self.teacher_marker_visible = True
        self.teacher_marker_text = "PROFESOR"
        self.student_sync_label_visible = False
        self.time_overlay_target = "both"
        self.md_toolbar_visible = False
        self.presentation_toolbar_visible = False
        self.image_toolbar_visible = False
        self.links_toolbar_visible = False
        self.paper_settings_collapsed = False
        self.shortcut_settings_collapsed = True
        self.shortcut_bindings = {}
        self.shortcut_objects = {}
        self.shortcut_action_combo = None
        self.shortcut_sequence_edit = None
        self._outline_current_role = None
        self.mobile_link = MobileLinkServer(self)
        self.direct_connections = DirectConnections(self.mobile_link, self)
        atexit.register(self.direct_connections.stop_all)
        self.mobile_link_qr_dialog = None
        self.mobile_link_success_message = None
        self.presentation_controller = PresentationController(self)
        self.recovery_service = RecoveryService(
            retention_days=self.AUTOSAVE_RETENTION_DAYS
        )
        self._mobile_last_pointer_log_at = 0.0
        self._mobile_pointer_config = {
            "size": 24,
            "shape": "ring",
            "color": "#39FF14",
            "trail": 0,
        }
        self._mobile_pointer_config_version = 0
        self._mobile_pointer_applied_versions = {}
        self._mobile_pointer_visible = True
        self._mobile_pointer_pending = None
        self._mobile_pointer_render_timer = QTimer(self)
        # Match the higher-rate Mobile stream while still coalescing positions.
        self._mobile_pointer_render_timer.setInterval(8)
        self._mobile_pointer_render_timer.timeout.connect(self._render_mobile_pointer)

        self._load_recent_files()
        self._load_file_preferences()
        self._load_app_preferences()
        self._load_shortcut_preferences()
        self.is_dark_mode = self._effective_dark_mode()

        self.init_ui()
        self.create_actions()
        self.create_toolbar()
        self.create_shortcuts()
        self.create_statusbar()
        self._register_operational_events()

        # Connect signals
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.markdown_file_dropped.connect(self._open_dropped_markdown_file)
        self.editor.cursor_position_changed.connect(
            lambda line, col: self._on_cursor_changed(line, col, self.editor)
        )
        self.editor.word_count_changed.connect(self._on_word_count_changed)
        self.editor.scroll_to_slide.connect(self._on_scroll_to_slide)

        self.slide_state_timer = QTimer(self)
        self.slide_state_timer.setInterval(1000)
        self.slide_state_timer.timeout.connect(self._capture_current_slide_preference)
        self.slide_state_timer.start()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(5 * 60 * 1000)
        self.autosave_timer.timeout.connect(self._run_autosave)
        self.autosave_timer.start()
        self._purge_expired_autosaves()

        self.theme_sync_timer = QTimer(self)
        self.theme_sync_timer.setInterval(2000)
        self.theme_sync_timer.timeout.connect(self._sync_automatic_theme)
        self.theme_sync_timer.start()

        self.diagnostic_timer = QTimer(self)
        self.diagnostic_timer.setInterval(30 * 1000)
        self.diagnostic_timer.timeout.connect(self._write_runtime_heartbeat)
        self.diagnostic_timer.start()

        self.external_open_timer = QTimer(self)
        self.external_open_timer.setInterval(400)
        self.external_open_timer.timeout.connect(self._consume_pending_open_files)
        self.external_open_timer.start()

        self.presentation_alt_tab_requested.connect(self._toggle_current_slide_image)
        self.presentation_navigation_key_down.connect(self._on_presentation_navigation_key_down)
        self.presentation_navigation_key_up.connect(self._on_presentation_navigation_key_up)
        self.mobile_link.connected.connect(self._on_mobile_link_connected)
        self.mobile_link.disconnected.connect(self._on_mobile_link_disconnected)
        self.mobile_link.message_received.connect(self._on_mobile_link_message)
        self.mobile_link.error_occurred.connect(self._on_mobile_link_error)

        self.apply_theme()
        restored_session = self._restore_tabs_session()
        if not restored_session:
            self._create_tab(None, DEFAULT_MARKDOWN, modified=False, switch=True)
        self._refresh_word_count()
        if self.nav_mode == "slides":
            self.build_slide_outline()
        self.update_preview()
        self.mobile_link.start()
        self._log_operation(
            "ventana_inicializada",
            restored_session=restored_session,
            tab_count=len(self.tabs),
            log_path=str(LOG_PATH) if LOG_PATH else None,
        )

    # ── UI Setup ──────────────────────────────────────────

    def _log_operation(self, action, **details):
        """Write a compact diagnostic event without recording document content."""
        try:
            active_editor = self._active_markdown_editor()
            current_slide = active_editor.current_slide_index() + 1
        except Exception:
            current_slide = None

        context = {
            "action": action,
            "app_version": APP_VERSION,
            "file": self.current_filepath or "<sin_guardar>",
            "tab": self.current_tab_index + 1 if self.current_tab_index >= 0 else None,
            "editor_role": self.editor_role,
            "slide": current_slide,
            "preview_mode": getattr(getattr(self, "preview", None), "presentation_mode", None),
            "dual_mode": self.teacher_preview_mode,
            "fullscreen": self.is_fullscreen_presentation,
        }
        context.update(details)
        safe_context = {
            key: str(value).replace("\n", "\\n").replace("\r", "")
            if value is not None else None
            for key, value in context.items()
        }
        serialized = json.dumps(safe_context, ensure_ascii=False, sort_keys=True)
        LOGGER.info("OPERACION | %s", serialized)
        _write_session_diagnostic("OPERACION | {0}".format(serialized))

    def _on_mobile_link_connected(self, remote):
        self._log_operation("mobile_link_conectado", remote=remote)
        self.statusBar().showMessage("Mobile conectado; verificando token...", 2500)

    def _confirm_mobile_link_authenticated(self, remote):
        """Confirm Mobile only after Desk has accepted its authenticated hello."""
        self._log_operation("mobile_link_autenticado", remote=remote)
        self.statusBar().showMessage("NUMA Deck Android-Link conectado", 2500)
        if self.mobile_link_qr_dialog is not None:
            self.mobile_link_qr_dialog.close()
            self.mobile_link_qr_dialog = None
            self._log_operation("mobile_link_qr_cerrado_por_autenticacion", remote=remote)
        message_box = QMessageBox(self)
        message_box.setWindowTitle("NUMA Deck Android-Link")
        message_box.setIcon(QMessageBox.Icon.Information)
        message_box.setText("Conexión establecida correctamente con Mobile.")
        message_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        message_box.button(QMessageBox.StandardButton.Ok).setText("Cerrar")
        self.mobile_link_success_message = message_box
        QTimer.singleShot(2000, message_box.accept)
        message_box.exec()
        self.mobile_link_success_message = None

    def _on_mobile_link_disconnected(self, remote):
        self._log_operation("mobile_link_desconectado", remote=remote)
        self.statusBar().showMessage("NUMA Deck Android-Link desconectado", 2500)

    def _on_mobile_link_error(self, message):
        LOGGER.error("Mobile-Link | %s", message)
        self._log_operation("mobile_link_error", message=message)
        lowered = str(message).lower()
        if "10048" in lowered or "address already in use" in lowered or "solo se permite un uso" in lowered:
            friendly = "Control móvil: puerto en uso por otra instancia"
        elif "oserror" in lowered or "errno" in lowered:
            friendly = "Control móvil no disponible en la red local"
        else:
            friendly = f"Control móvil: {message}"
        self.statusBar().showMessage(friendly, 5000)

    def _on_mobile_link_message(self, message):
        """Apply safe Mobile actions on Qt's GUI thread and record input."""
        message_type = message.get("type")
        payload = message.get("payload") or {}
        remote = message.get("_remote")
        if message_type == "hello":
            self._log_operation("mobile_link_hello", remote=remote, client=payload.get("client_name"))
            self._confirm_mobile_link_authenticated(remote)
            return
        if message_type == "pointer":
            try:
                x = max(0.0, min(1.0, float(payload.get("x", 0.0))))
                y = max(0.0, min(1.0, float(payload.get("y", 0.0))))
            except (TypeError, ValueError):
                self._log_operation("mobile_link_pointer_invalido", remote=remote)
                return
            now = time.monotonic()
            if now - self._mobile_last_pointer_log_at >= 0.1:
                self._mobile_last_pointer_log_at = now
                self._log_operation(
                    "mobile_link_pointer",
                    remote=remote,
                    x=round(x, 4),
                    y=round(y, 4),
                    presentation=self.is_fullscreen_presentation,
                )
            self._mobile_pointer_pending = (x, y)
            if self.is_fullscreen_presentation and not self._mobile_pointer_render_timer.isActive():
                self._mobile_pointer_render_timer.start()
            return
        if message_type == "pointer_config":
            try:
                size = max(8, min(96, int(payload.get("size", 24))))
            except (TypeError, ValueError):
                size = 24
            shape = str(payload.get("shape", "ring")).strip().lower()
            if shape not in {"ring", "dot"}:
                shape = "ring"
            color = str(payload.get("color", "#39FF14")).strip()
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                color = "#39FF14"
            try:
                trail = max(0, min(48, int(payload.get("trail", 0))))
            except (TypeError, ValueError):
                trail = 0
            trail_mode = str(payload.get("trail_mode", "dots")).strip().lower()
            if trail_mode not in {"none", "dots", "continuous"}:
                trail_mode = "dots" if trail else "none"
            if trail == 0:
                trail_mode = "none"
            self._mobile_pointer_config = {
                "size": size,
                "shape": shape,
                "color": color,
                "trail": trail,
                "trail_mode": trail_mode,
            }
            if "visible" in payload:
                self._mobile_pointer_visible = bool(payload.get("visible"))
                if not self._mobile_pointer_visible:
                    self._mobile_pointer_pending = None
                    self._mobile_pointer_render_timer.stop()
                if self.is_fullscreen_presentation:
                    target = self._presentation_student_view()
                    pending = self._mobile_pointer_pending or (0.5, 0.5)
                    target.set_mobile_pointer(pending[0], pending[1], self._mobile_pointer_visible)
            self._mobile_pointer_config_version += 1
            if self.is_fullscreen_presentation:
                target = self._presentation_student_view()
                target.set_mobile_pointer_config(**self._mobile_pointer_config)
                self._mobile_pointer_applied_versions[id(target)] = self._mobile_pointer_config_version
            self._log_operation(
                "mobile_link_pointer_config",
                remote=remote,
                pointer_size=size,
                pointer_shape=shape,
                pointer_color=color,
                pointer_trail=trail,
                pointer_trail_mode=trail_mode,
            )
            return
        if message_type == "mouse_move":
            try:
                x = max(0.0, min(1.0, float(payload.get("x", 0.0))))
                y = max(0.0, min(1.0, float(payload.get("y", 0.0))))
            except (TypeError, ValueError):
                self._log_operation("mobile_link_mouse_move_invalido", remote=remote)
                return
            self._log_operation(
                "mobile_link_mouse_move",
                remote=remote,
                x=round(x, 4),
                y=round(y, 4),
            )
            if self.is_fullscreen_presentation:
                self._presentation_student_view().mobile_mouse_move(x, y)
            return
        if message_type == "mouse_click":
            try:
                x = max(0.0, min(1.0, float(payload.get("x", 0.0))))
                y = max(0.0, min(1.0, float(payload.get("y", 0.0))))
            except (TypeError, ValueError):
                self._log_operation("mobile_link_mouse_click_invalido", remote=remote)
                return
            try:
                click_count = max(1, min(2, int(payload.get("click_count", 1))))
            except (TypeError, ValueError):
                click_count = 1
            self._log_operation("mobile_link_mouse_click", remote=remote, x=round(x, 4), y=round(y, 4), click_count=click_count)
            if self.is_fullscreen_presentation:
                self._presentation_student_view().mobile_mouse_click(x, y, click_count)
            return
        if message_type == "mouse_scroll":
            try:
                x = max(0.0, min(1.0, float(payload.get("x", 0.5))))
                y = max(0.0, min(1.0, float(payload.get("y", 0.5))))
                delta_y = max(-1.0, min(1.0, float(payload.get("delta_y", 0.0))))
            except (TypeError, ValueError):
                self._log_operation("mobile_link_mouse_scroll_invalido", remote=remote)
                return
            self._log_operation("mobile_link_mouse_scroll", remote=remote, x=round(x, 4), y=round(y, 4), delta_y=round(delta_y, 4))
            if self.is_fullscreen_presentation:
                self._presentation_student_view().mobile_mouse_scroll(x, y, delta_y)
            return
        if message_type != "action":
            self._log_operation("mobile_link_mensaje_ignorado", remote=remote, message_type=message_type)
            return

        action = str(payload.get("name", "")).strip().lower()
        self._log_operation("mobile_link_action", remote=remote, mobile_action=action)
        if not self.is_fullscreen_presentation:
            self.statusBar().showMessage("Inicia una presentación para usar NUMA Deck Android-Link", 3000)
            return
        if not self.presentation_controller.dispatch_mobile_action(action):
            self._log_operation("mobile_link_action_desconocida", mobile_action=action)

    def _recenter_mobile_pointer(self):
        """Move the Mobile pointer to the center of the active presentation."""
        self._mobile_pointer_pending = (0.5, 0.5)
        target = self._presentation_student_view()
        target.set_mobile_pointer_config(**self._mobile_pointer_config)
        self._mobile_pointer_applied_versions[id(target)] = self._mobile_pointer_config_version
        target.set_mobile_pointer(0.5, 0.5, self._mobile_pointer_visible)
        if self.is_fullscreen_presentation and self._mobile_pointer_visible:
            if not self._mobile_pointer_render_timer.isActive():
                self._mobile_pointer_render_timer.start()
        self._log_operation("mobile_link_pointer_recentrado", x=0.5, y=0.5)
        self.statusBar().showMessage("Puntero Mobile recentrado", 1500)

    def _toggle_mobile_pointer_visibility(self):
        self._mobile_pointer_visible = not self._mobile_pointer_visible
        if not self._mobile_pointer_visible:
            self._mobile_pointer_pending = None
            self._mobile_pointer_render_timer.stop()
        target = self._presentation_student_view()
        target.set_mobile_pointer(0.5, 0.5, self._mobile_pointer_visible)
        self.statusBar().showMessage(
            "Puntero Mobile visible" if self._mobile_pointer_visible else "Puntero Mobile oculto",
            1500,
        )

    def _render_mobile_pointer(self):
        if not self.is_fullscreen_presentation or not self._mobile_pointer_visible:
            self._mobile_pointer_render_timer.stop()
            self._mobile_pointer_pending = None
            return
        if self._mobile_pointer_pending is None:
            self._mobile_pointer_render_timer.stop()
            return
        x, y = self._mobile_pointer_pending
        self._mobile_pointer_pending = None
        target = self._presentation_student_view()
        target_key = id(target)
        if self._mobile_pointer_applied_versions.get(target_key) != self._mobile_pointer_config_version:
            target.set_mobile_pointer_config(**self._mobile_pointer_config)
            self._mobile_pointer_applied_versions[target_key] = self._mobile_pointer_config_version
        target.set_mobile_pointer(x, y, True)

    def _write_runtime_heartbeat(self):
        """Persist the last healthy UI state for silent/native crash diagnosis."""
        try:
            student_index = getattr(self.preview, "_last_known_slide_index", None)
            teacher_index = getattr(self.teacher_preview, "_last_known_slide_index", None)
            self._log_operation(
                "heartbeat",
                pid=os.getpid(),
                split_editor=self.split_editor_enabled,
                student_file=self._student_editor_path() or "<sin_guardar>",
                teacher_file=self.teacher_script_path or "<sin_cargar>",
                student_modified=self.is_modified,
                teacher_modified=self.teacher_is_modified,
                student_slide=(student_index + 1) if isinstance(student_index, int) else None,
                teacher_slide=(teacher_index + 1) if isinstance(teacher_index, int) else None,
                student_preview_visible=self.preview.isVisible(),
                teacher_preview_visible=self.teacher_preview.isVisible(),
                tab_count=len(self.tabs),
                hook_installed=bool(self._presentation_alt_tab_hook),
                hook_event_count=self._presentation_hook_event_count,
                hook_error_count=self._presentation_hook_error_count,
                hook_last_event=self._presentation_hook_last_event,
                hook_last_error=self._presentation_hook_last_error,
                mobile_link=(
                    self.mobile_link.diagnostics_snapshot()
                    if getattr(self, "mobile_link", None)
                    else None
                ),
                student_render=(
                    self.preview.diagnostics_snapshot()
                    if hasattr(self.preview, "diagnostics_snapshot")
                    else None
                ),
                teacher_render=(
                    self.teacher_preview.diagnostics_snapshot()
                    if hasattr(self.teacher_preview, "diagnostics_snapshot")
                    else None
                ),
                presentation_controller=(
                    self.presentation_controller.diagnostics_snapshot()
                    if hasattr(self, "presentation_controller")
                    else None
                ),
            )
        except Exception:
            LOGGER.exception("No se pudo escribir heartbeat de diagnostico")

    def _track_operational_control(self, widget, label):
        """Mark a control so its user clicks can be recorded by eventFilter."""
        if widget is None:
            return
        widget.setProperty("numa_log_control", label)
        widget.installEventFilter(self)

    def _register_operational_events(self):
        """Register user-facing controls once the complete interface exists."""
        controls = [
            (self.recent_btn, "recientes"),
            (self.open_quick_btn, "abrir_directo"),
            (self.save_quick_btn, "guardar_directo"),
            (self.export_pdf_btn, "exportar_pdf"),
            (self.mode_btn, "modo_presentacion"),
            (self.zoom_out_btn, "zoom_menos"),
            (self.zoom_in_btn, "zoom_mas"),
            (self.zoom_reset_btn, "zoom_restablecer"),
            (self.theme_btn, "tema"),
            (self.borderless_btn, "marco"),
            (self.md_toolbar_toggle_btn, "barra_edicion_markdown"),
            (self.clock_mode_combo, "modo_indicador_tiempo"),
            (self.clock_btn, "indicador_tiempo"),
            (self.clock_target_combo, "destino_indicador_tiempo"),
            (self.clock_seconds_btn, "reloj_segundos"),
            (self.timer_minutes_input, "duracion_temporizador"),
            (self.timer_start_btn, "iniciar_pausar_tiempo"),
            (self.timer_reset_btn, "reiniciar_tiempo"),
            (self.clock_size_down_btn, "reloj_menos"),
            (self.clock_size_up_btn, "reloj_mas"),
            (self.clock_position_combo, "posicion_reloj"),
            (self.present_btn, "presentar"),
            (self.nav_toggle_btn, "navegador_colapsar"),
            (self.nav_mode_combo, "modo_navegador"),
            (self.teacher_load_btn, "cargar_guion_profesor"),
            (self.presentation_load_btn, "cargar_presentacion"),
            (self.teacher_sync_btn, "sincronizar_guiones"),
            (self.clear_sync_btn, "borrar_sincronizacion"),
            (self.clear_slide_sync_btn, "desvincular_slide"),
            (self.student_sync_label_btn, "etiqueta_sincronizacion_alumno"),
            (self.split_editor_btn, "editor_dual"),
            (self.teacher_preview_combo, "modo_vista_previa"),
            (self.student_collapse_btn, "colapsar_alumno"),
            (self.student_zoom_out_btn, "zoom_alumno_menos"),
            (self.student_zoom_in_btn, "zoom_alumno_mas"),
            (self.teacher_collapse_btn, "colapsar_profesor"),
            (self.teacher_zoom_out_btn, "zoom_profesor_menos"),
            (self.teacher_zoom_in_btn, "zoom_profesor_mas"),
            (self.present_teacher_btn, "presentar_profesor"),
            (self.present_dual_btn, "presentar_dual"),
            (self.teacher_marker_btn, "marca_profesor"),
            (self.teacher_marker_text_input, "texto_marca_profesor"),
            (self.shortcuts_toolbar_direct_btn, "barra_atajos"),
        ]
        for widget, label in controls:
            self._track_operational_control(widget, label)

        for action, label in (
            (self.new_act, "nuevo"),
            (self.open_act, "abrir"),
            (self.save_act, "guardar"),
            (self.save_teacher_act, "guardar_profesor"),
            (self.save_as_act, "guardar_como"),
            (self.export_pdf_act, "exportar_pdf"),
            (self.about_act, "acerca_de"),
            (self.exit_act, "salir"),
        ):
            action.triggered.connect(
                lambda checked=False, action_label=label: self._log_operation(
                    "accion", control=action_label
                )
            )

    def init_ui(self):
        self.central_widget = QWidget(self)
        self.central_widget.setAcceptDrops(True)
        self.setCentralWidget(self.central_widget)

        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(12, 8, 12, 12)
        main_layout.setSpacing(6)

        # Markdown formatting toolbar spans the full workspace.
        self.editor = MarkdownEditor(self, is_dark=self.is_dark_mode)
        self.editor.image_link_choice_changed = self._remember_image_link_choice
        self.editor.installEventFilter(self)
        self.time_toolbar = FlowToolbar(self, max_height=116)
        self.time_toolbar.setObjectName("timeToolbarContainer")
        self.time_toolbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.time_toolbar_layout = FlowLayout(self.time_toolbar, margin=0, spacing=6)
        self.time_toolbar_layout.setContentsMargins(0, 0, 0, 4)
        self.time_toolbar.setLayout(self.time_toolbar_layout)
        main_layout.addWidget(self.time_toolbar)

        # Paper settings have their own wrapping row. They never compete with
        # the fixed application toolbar when the window becomes narrow.
        self.paper_toolbar = QFrame(self)
        self.paper_toolbar.setObjectName("paperToolbarContainer")
        self.paper_toolbar.installEventFilter(self)
        self.paper_toolbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        paper_block_layout = QVBoxLayout(self.paper_toolbar)
        paper_block_layout.setContentsMargins(0, 0, 0, 4)
        paper_block_layout.setSpacing(4)
        self.paper_settings_toggle_btn = QPushButton("Configuracion de hoja impresa -", self.paper_toolbar)
        self.paper_settings_toggle_btn.setObjectName("softBlueBtn")
        self.paper_settings_toggle_btn.setToolTip("Mostrar u ocultar las opciones de hoja impresa")
        self.paper_settings_toggle_btn.clicked.connect(self.toggle_paper_settings)
        paper_block_layout.addWidget(self.paper_settings_toggle_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        self.paper_settings_content = FlowToolbar(self.paper_toolbar, max_height=320)
        self.paper_settings_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.paper_toolbar_layout = FlowLayout(self.paper_settings_content, margin=0, spacing=6)
        self.paper_toolbar_layout.setContentsMargins(0, 0, 0, 4)
        self.paper_settings_content.setLayout(self.paper_toolbar_layout)
        paper_block_layout.addWidget(self.paper_settings_content)
        self.paper_toolbar.hide()
        # Page options are displayed from the main toolbar as a popup. Keeping
        # this host out of the main layout avoids a permanent third control row.

        self.shortcut_toolbar = self._create_shortcut_settings_block()
        main_layout.addWidget(self.shortcut_toolbar)

        # Preview-specific controls stay independent of the preview width.
        # This keeps their actions available even when that panel is collapsed.
        self.preview_controls_widget = FlowToolbar(self, max_height=116)
        self.preview_controls_widget.setObjectName("previewControls")
        self.preview_controls_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preview_controls_widget.hide()
        # Role, sync and Markdown controls are exposed from compact context
        # menus in the time/context bar below.

        self.presentation_toolbar = self._create_presentation_toolbar()
        self.presentation_toolbar.hide()
        main_layout.addWidget(self.presentation_toolbar)

        self.md_toolbar = self._create_md_toolbar()
        self.md_toolbar.hide()

        self.image_toolbar = self._create_image_toolbar()
        self.image_toolbar.hide()
        main_layout.addWidget(self.image_toolbar)

        # Document tabs span the full workspace above all panels.
        self.tab_bar = self._create_tab_bar()
        main_layout.addWidget(self.tab_bar)

        # Splitter
        self.splitter = QSplitter(Qt.Horizontal, self)
        main_layout.addWidget(self.splitter)

        # Directory navigation panel
        self.nav_container = self._create_navigation_panel()

        # Editor panel
        self.editor_container = QFrame(self)
        self.editor_container.setObjectName("editorContainer")
        editor_layout = QVBoxLayout(self.editor_container)
        editor_layout.setContentsMargins(4, 4, 4, 4)
        editor_layout.setSpacing(4)
        # Keep Markdown formatting attached to the editor it controls.
        editor_layout.addWidget(self.md_toolbar)

        self.editor_splitter = QSplitter(Qt.Vertical, self.editor_container)
        self.editor_splitter.setChildrenCollapsible(False)
        self.editor_splitter.addWidget(self.editor)
        self.teacher_editor = MarkdownEditor(self.editor_container, is_dark=self.is_dark_mode)
        self.teacher_editor.image_link_choice_changed = self._remember_image_link_choice
        self.teacher_editor.markdown_file_dropped.connect(self._open_dropped_markdown_file)
        self.teacher_editor.installEventFilter(self)
        self.teacher_editor.textChanged.connect(self._on_teacher_editor_text_changed)
        self.teacher_editor.cursor_position_changed.connect(
            lambda line, col: self._on_cursor_changed(line, col, self.teacher_editor)
        )
        self.teacher_editor.word_count_changed.connect(self._on_word_count_changed)
        self.teacher_editor.scroll_to_slide.connect(self._on_teacher_editor_scroll_to_slide)
        self.teacher_editor.hide()
        self.editor_splitter.addWidget(self.teacher_editor)
        self.editor_splitter.setSizes([1, 1])
        editor_layout.addWidget(self.editor_splitter, stretch=1)

        # Preview panel
        self.preview_container = QFrame(self)
        self.preview_container.setObjectName("previewContainer")
        self.preview_container.setMinimumWidth(0)
        self.preview_container.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        preview_layout = QVBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        preview_layout.setSpacing(2)

        # Always-visible quick controls: slide navigation and text size.
        self.preview_quick_bar = QWidget(self.preview_container)
        quick_layout = QHBoxLayout(self.preview_quick_bar)
        quick_layout.setContentsMargins(0, 0, 0, 2)
        quick_layout.setSpacing(4)
        self.quick_prev_slide_btn = QPushButton("◀ Anterior", self.preview_quick_bar)
        self.quick_prev_slide_btn.setToolTip("Ir a la diapositiva anterior")
        self.quick_prev_slide_btn.clicked.connect(self._quick_prev_slide)
        self.preview_slide_counter_label = QLabel("Diapositiva 1 / 1", self.preview_quick_bar)
        self.preview_slide_counter_label.setObjectName("previewSlideCounter")
        self.preview_slide_counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.quick_next_slide_btn = QPushButton("Siguiente ▶", self.preview_quick_bar)
        self.quick_next_slide_btn.setToolTip("Pasar a la siguiente diapositiva")
        self.quick_next_slide_btn.clicked.connect(self._quick_next_slide)
        self.quick_font_down_btn = QPushButton("Texto −", self.preview_quick_bar)
        self.quick_font_down_btn.setToolTip("Disminuir tamaño de texto de la diapositiva")
        self.quick_font_down_btn.clicked.connect(self.decrease_font_size)
        self.quick_font_up_btn = QPushButton("Texto +", self.preview_quick_bar)
        self.quick_font_up_btn.setToolTip("Aumentar tamaño de texto de la diapositiva")
        self.quick_font_up_btn.clicked.connect(self.increase_font_size)
        self.quick_prev_slide_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.quick_next_slide_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        quick_layout.addWidget(self.quick_prev_slide_btn)
        quick_layout.addWidget(self.preview_slide_counter_label)
        quick_layout.addWidget(self.quick_next_slide_btn)
        quick_layout.addStretch(1)
        for _b in (self.quick_font_down_btn, self.quick_font_up_btn):
            _b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            quick_layout.addWidget(_b)
        preview_layout.addWidget(self.preview_quick_bar)

        self.teacher_controls_widget = self.preview_controls_widget
        teacher_controls = FlowLayout(self.teacher_controls_widget, margin=0, spacing=4)
        teacher_controls.setContentsMargins(0, 0, 0, 4)
        self.teacher_controls_widget.setLayout(teacher_controls)

        self.md_toolbar_toggle_btn = QPushButton("Ocultar barra MD", self.teacher_controls_widget)
        self.md_toolbar_toggle_btn.setObjectName("softBlueBtn")
        self.md_toolbar_toggle_btn.setToolTip("Ocultar o mostrar los botones de edicion Markdown")
        self.md_toolbar_toggle_btn.clicked.connect(self.toggle_md_toolbar)
        teacher_controls.addWidget(self.md_toolbar_toggle_btn)

        self.teacher_load_btn = QPushButton("Guion Profesor", self.preview_container)
        self.teacher_load_btn.setToolTip("Cargar guion Markdown del profesor para vista dual")
        self.teacher_load_btn.clicked.connect(self.load_teacher_script)
        teacher_controls.addWidget(self.teacher_load_btn)

        self.presentation_load_btn = QPushButton("Presentacion", self.preview_container)
        self.presentation_load_btn.setToolTip("Elegir el Markdown que se mostrara al alumnado en modo dual")
        self.presentation_load_btn.clicked.connect(self.load_student_presentation)
        teacher_controls.addWidget(self.presentation_load_btn)

        self.teacher_sync_btn = QPushButton("Vincular slide", self.preview_container)
        self.teacher_sync_btn.setObjectName("accentBtn")
        self.teacher_sync_btn.setToolTip("Vincular el slide actual del alumno con el del profesor")
        self.teacher_sync_btn.clicked.connect(self.sync_teacher_preview_manual)
        teacher_controls.addWidget(self.teacher_sync_btn)

        self.clear_sync_btn = QPushButton("Desvincular documento", self.preview_container)
        self.clear_sync_btn.setObjectName("softMangoBtn")
        self.clear_sync_btn.setToolTip("Eliminar todos los vinculos de sincronizacion entre alumno y profesor")
        self.clear_sync_btn.clicked.connect(self.clear_dual_sync)
        teacher_controls.addWidget(self.clear_sync_btn)

        self.clear_slide_sync_btn = QPushButton("Desvincular slide", self.preview_container)
        self.clear_slide_sync_btn.setObjectName("softMangoBtn")
        self.clear_slide_sync_btn.setToolTip("Eliminar solo el vinculo del slide actual entre alumno y profesor")
        self.clear_slide_sync_btn.clicked.connect(self.clear_current_slide_sync)
        teacher_controls.addWidget(self.clear_slide_sync_btn)

        self.student_sync_label_btn = QPushButton("Vinculo Profesor", self.preview_container)
        self.student_sync_label_btn.setObjectName("softBlueBtn")
        self.student_sync_label_btn.setToolTip("Mostrar el slide sincronizado del profesor en la vista del alumno")
        self.student_sync_label_btn.setCheckable(True)
        self.student_sync_label_btn.clicked.connect(self.toggle_student_sync_label)
        teacher_controls.addWidget(self.student_sync_label_btn)

        self.split_editor_btn = QPushButton("Editor Dual", self.preview_container)
        self.split_editor_btn.setToolTip("Dividir el panel de edicion para alumno y profesor")
        self.split_editor_btn.clicked.connect(self.toggle_split_editor)
        teacher_controls.addWidget(self.split_editor_btn)

        self.teacher_preview_combo = QComboBox(self.preview_container)
        self.teacher_preview_combo.setToolTip("Cambiar vista previa entre alumno, dual o profesor")
        self.teacher_preview_combo.addItem("Alumno", "student")
        self.teacher_preview_combo.addItem("Dual", "dual")
        self.teacher_preview_combo.addItem("Profesor", "teacher")
        self.teacher_preview_combo.currentIndexChanged.connect(self.change_teacher_preview_mode)
        teacher_controls.addWidget(self.teacher_preview_combo)

        self.student_collapse_btn = QPushButton("Alumno -", self.preview_container)
        self.student_collapse_btn.setToolTip("Colapsar o restaurar la vista del alumno")
        self.student_collapse_btn.clicked.connect(self.toggle_student_preview_collapsed)
        teacher_controls.addWidget(self.student_collapse_btn)

        self.student_zoom_out_btn = QPushButton("A-", self.preview_container)
        self.student_zoom_out_btn.setToolTip("Disminuir zoom de la vista del alumno")
        self.student_zoom_out_btn.clicked.connect(lambda: self.adjust_dual_preview_zoom("student", -0.1))
        teacher_controls.addWidget(self.student_zoom_out_btn)

        self.student_zoom_in_btn = QPushButton("A+", self.preview_container)
        self.student_zoom_in_btn.setToolTip("Aumentar zoom de la vista del alumno")
        self.student_zoom_in_btn.clicked.connect(lambda: self.adjust_dual_preview_zoom("student", 0.1))
        teacher_controls.addWidget(self.student_zoom_in_btn)

        self.teacher_collapse_btn = QPushButton("Profesor -", self.preview_container)
        self.teacher_collapse_btn.setToolTip("Colapsar o restaurar la vista del profesor")
        self.teacher_collapse_btn.clicked.connect(self.toggle_teacher_preview_collapsed)
        teacher_controls.addWidget(self.teacher_collapse_btn)

        self.teacher_zoom_out_btn = QPushButton("P-", self.preview_container)
        self.teacher_zoom_out_btn.setToolTip("Disminuir zoom de la vista del profesor")
        self.teacher_zoom_out_btn.clicked.connect(lambda: self.adjust_dual_preview_zoom("teacher", -0.1))
        teacher_controls.addWidget(self.teacher_zoom_out_btn)

        self.teacher_zoom_in_btn = QPushButton("P+", self.preview_container)
        self.teacher_zoom_in_btn.setToolTip("Aumentar zoom de la vista del profesor")
        self.teacher_zoom_in_btn.clicked.connect(lambda: self.adjust_dual_preview_zoom("teacher", 0.1))
        teacher_controls.addWidget(self.teacher_zoom_in_btn)

        self.teacher_marker_btn = QPushButton("Marca Profesor", self.preview_container)
        self.teacher_marker_btn.setToolTip("Mostrar u ocultar la marca visual roja del profesor")
        self.teacher_marker_btn.setCheckable(True)
        self.teacher_marker_btn.setChecked(True)
        self.teacher_marker_btn.clicked.connect(self.toggle_teacher_marker)
        teacher_controls.addWidget(self.teacher_marker_btn)

        self.teacher_marker_text_input = QLineEdit("PROFESOR", self.preview_container)
        self.teacher_marker_text_input.setToolTip("Texto de la marca visual del profesor")
        self.teacher_marker_text_input.setMaximumWidth(120)
        self.teacher_marker_text_input.editingFinished.connect(self.change_teacher_marker_text)
        teacher_controls.addWidget(self.teacher_marker_text_input)

        # Build this toolbar after its synchronization controls exist.
        self.links_toolbar = self._create_links_toolbar()
        self.links_toolbar.hide()
        main_layout.insertWidget(main_layout.indexOf(self.tab_bar), self.links_toolbar)

        self.preview = PresentationView(self, is_dark=self.is_dark_mode)
        self.preview.markdown_file_dropped.connect(self._open_dropped_markdown_file)
        self.preview.clicked.connect(lambda: self.activate_editor_for("student"))
        self.preview.student_sync_label_activated.connect(self.open_teacher_slide_from_student_label)
        self.preview.zoom_changed.connect(lambda factor: self._on_preview_zoom_changed("student", factor))
        self.preview.slide_navigated_by_key.connect(self._center_editor_on_slide)
        self.preview.paper_page_changed.connect(self._on_preview_paper_page_changed)
        self.preview.web_view.loadFinished.connect(self._restore_editor_focus_after_preview_load)
        self.preview.web_view.loadFinished.connect(
            lambda ok: self._center_active_cursor_after_preview_load(self.preview, ok)
        )
        preview_layout.addWidget(self.preview, stretch=1)

        self.teacher_preview = PresentationView(self, is_dark=self.is_dark_mode)
        self.teacher_preview.markdown_file_dropped.connect(self._open_dropped_markdown_file)
        self.teacher_preview.clicked.connect(lambda: self.activate_editor_for("teacher"))
        self.teacher_preview.zoom_changed.connect(lambda factor: self._on_preview_zoom_changed("teacher", factor))
        self.teacher_preview.web_view.loadFinished.connect(
            lambda ok: self._center_active_cursor_after_preview_load(self.teacher_preview, ok)
        )
        self.teacher_preview.setVisible(False)
        preview_layout.addWidget(self.teacher_preview, stretch=1)

        # Add panels to splitter
        self.splitter.addWidget(self.nav_container)
        self.splitter.addWidget(self.editor_container)
        self.splitter.addWidget(self.preview_container)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(2, True)
        self.splitter.setHandleWidth(6)
        self.splitter.setSizes([220, 560, 500])
        self._saved_nav_width = 220
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 1)

    def _create_navigation_panel(self):
        """Create a collapsible directory browser for Markdown files."""
        container = QFrame(self)
        container.setObjectName("navContainer")

        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.nav_toggle_btn = QPushButton("◂ Plegar panel")
        self.nav_toggle_btn.setObjectName("navToggle")
        self.nav_toggle_btn.setToolTip("Plegar el panel lateral")
        self.nav_toggle_btn.setFixedHeight(28)
        self.nav_toggle_btn.clicked.connect(self.toggle_navigation_panel)
        layout.addWidget(self.nav_toggle_btn)

        self.nav_body = QWidget(container)
        nav_body_layout = QVBoxLayout(self.nav_body)
        nav_body_layout.setContentsMargins(0, 0, 0, 0)
        nav_body_layout.setSpacing(4)

        self.nav_mode_combo = QComboBox(self.nav_body)
        self.nav_mode_combo.setObjectName("navModeCombo")
        self.nav_mode_combo.setToolTip("Cambiar entre índice de diapositivas y explorador de archivos")
        self.nav_mode_combo.addItem("Diapositivas", "slides")
        self.nav_mode_combo.addItem("Archivos", "files")
        self.nav_mode_combo.currentIndexChanged.connect(self.change_navigation_mode)
        nav_body_layout.addWidget(self.nav_mode_combo)

        nav_controls = QHBoxLayout()
        nav_controls.setContentsMargins(0, 0, 0, 0)
        nav_controls.setSpacing(4)

        def nav_btn(text, tooltip, callback):
            b = QPushButton(text)
            b.setObjectName("navSmallBtn")
            b.setToolTip(tooltip)
            b.setFixedHeight(26)
            b.setVisible(False)
            b.clicked.connect(callback)
            self._track_operational_control(b, f"navegador_{text}")
            return b

        nav_controls.addWidget(nav_btn("Equipo", "Mostrar unidades y ubicaciones principales", self.show_computer_root))
        nav_controls.addWidget(nav_btn("C:", "Ir al disco C", lambda: self.set_navigation_root("C:/")))
        nav_controls.addWidget(nav_btn("Proyecto", "Ir a la carpeta del proyecto NUMA", lambda: self.set_navigation_root(self.project_root_path)))
        nav_controls.addWidget(nav_btn("Subir", "Subir un nivel", self.navigate_up))
        nav_body_layout.addLayout(nav_controls)
        self.nav_file_controls = nav_controls

        self.nav_path_label = QLabel("Índice de diapositivas")
        self.nav_path_label.setObjectName("navPathLabel")
        self.nav_path_label.setWordWrap(True)
        nav_body_layout.addWidget(self.nav_path_label)

        self.file_tree = QTreeWidget(self.nav_body)
        self.file_tree.setObjectName("fileTree")
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setAnimated(True)
        self.file_tree.setIndentation(14)
        self.file_tree.itemClicked.connect(self._select_tree_item)
        self.file_tree.itemDoubleClicked.connect(self._activate_tree_item)
        self.file_tree.itemExpanded.connect(self._populate_tree_item)
        self.file_tree.itemActivated.connect(self._activate_tree_item)
        nav_body_layout.addWidget(self.file_tree, stretch=1)

        self.nav_new_slide_btn = QPushButton("+ Nueva diapositiva", self.nav_body)
        self.nav_new_slide_btn.setObjectName("softBlueBtn")
        self.nav_new_slide_btn.setToolTip("Insertar un separador de nueva diapositiva (---)")
        self.nav_new_slide_btn.clicked.connect(self._md_insert_slide_separator)
        nav_body_layout.addWidget(self.nav_new_slide_btn)

        layout.addWidget(self.nav_body, stretch=1)
        return container

    def _create_tab_bar(self):
        """Create the document tab bar."""
        tab_bar = DocumentTabBar(self)
        tab_bar.setObjectName("documentTabs")
        tab_bar.setMovable(True)
        tab_bar.setTabsClosable(True)
        tab_bar.setExpanding(False)
        tab_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tab_bar.currentChanged.connect(self._switch_to_tab)
        tab_bar.tabCloseRequested.connect(self._close_tab)
        tab_bar.tabMoved.connect(self._on_tab_moved)
        tab_bar.empty_space_double_clicked.connect(self.file_open)
        return tab_bar

    def _tab_title(self, tab):
        name = os.path.basename(tab["path"]) if tab.get("path") else "Sin título"
        modified = "*" if tab.get("modified") else ""
        dual_marker = "D | " if self._tab_is_dual(tab) else ""
        if len(name) <= 24:
            return f"{modified}{dual_marker}{name}"
        # Preserve both ends: the beginning usually identifies the chapter,
        # while the end preserves version and extension information.
        return f"{modified}{dual_marker}{name[:10]}...{name[-9:]}"

    def _tab_is_dual(self, tab):
        return bool(tab.get("teacher_preview_mode") == "dual")

    def _update_tab_visual(self, index, tab=None):
        if not (hasattr(self, "tab_bar") and 0 <= index < self.tab_bar.count()):
            return
        if tab is None and 0 <= index < len(self.tabs):
            tab = self.tabs[index]
        tab = tab or {}
        self.tab_bar.setTabText(index, self._tab_title(tab))
        dual = self._tab_is_dual(tab)
        if dual:
            color = QColor("#10B981" if not self.is_dark_mode else "#34D399")
            self.tab_bar.setTabToolTip(index, f"Modo dual: {tab.get('path') or 'Documento nuevo sin guardar'}")
        else:
            color = QColor("#111827" if not self.is_dark_mode else "#EEF2FF")
            self.tab_bar.setTabToolTip(index, tab.get("path") or "Documento nuevo sin guardar")
        self.tab_bar.setTabTextColor(index, color)

    def _sync_current_tab_from_editor(self):
        if 0 <= self.current_tab_index < len(self.tabs):
            tab = self.tabs[self.current_tab_index]
            # setPlainText() emits transient cursor/scroll events at position
            # zero while a tab is loading.  Never let those replace the saved
            # position captured just before the tab switch.
            if not self._loading_tab:
                self._capture_tab_navigation_state(tab)
            tab["path"] = self.current_filepath
            if self.editor_role == "student" or self.split_editor_enabled:
                if self._uses_external_student_presentation():
                    self.presentation_script_content = self.editor.toPlainText()
                else:
                    tab["content"] = self.editor.toPlainText()
            tab["modified"] = self.is_modified
            tab["presentation_script_path"] = self.presentation_script_path
            tab["presentation_script_content"] = self.presentation_script_content
            tab["teacher_script_path"] = self.teacher_script_path
            tab["teacher_script_content"] = self.teacher_script_content
            tab["teacher_preview_mode"] = self.teacher_preview_mode
            tab["dual_student_collapsed"] = self.dual_student_collapsed
            tab["dual_teacher_collapsed"] = self.dual_teacher_collapsed
            tab["student_preview_zoom"] = self._preview_zoom_for_persistence(self.preview)
            tab["teacher_preview_zoom"] = self._preview_zoom_for_persistence(self.teacher_preview)
            tab["font_size"] = int(self.preview.font_size)
            tab["present_teacher_locally"] = self.present_teacher_locally
            tab["split_editor_enabled"] = self.split_editor_enabled
            tab["editor_role"] = self.editor_role
            tab["teacher_modified"] = self.teacher_is_modified
            tab["teacher_marker_visible"] = self.teacher_marker_visible
            tab["teacher_marker_text"] = self.teacher_marker_text
            tab["student_sync_label_visible"] = self.student_sync_label_visible
            tab["presentation_mode"] = self.preview.presentation_mode
            tab["paper_size"] = self.preview.paper_size
            tab["paper_orientation"] = self.preview.paper_orientation
            tab["paper_header_mode"] = self.preview.paper_header_mode
            tab["paper_footer_mode"] = self.preview.paper_footer_mode
            tab["paper_custom_header"] = self.preview.paper_custom_header
            tab["paper_header_right_mode"] = self.preview.paper_header_right_mode
            tab["paper_header_right_text"] = self.preview.paper_header_right_text
            tab["paper_footer_left_mode"] = self.preview.paper_footer_left_mode
            tab["paper_footer_left_text"] = self.preview.paper_footer_left_text
            tab["paper_font_scale"] = self.preview.paper_font_scale
            tab["borderless"] = bool(self.preview.borderless)
            tab["clock_visible"] = bool(self.clock_btn.isChecked())
            tab["time_overlay_target"] = self.time_overlay_target
            tab["clock_mode"] = self.preview.clock_mode
            tab["clock_show_seconds"] = bool(self.preview.clock_show_seconds)
            tab["clock_size"] = int(self.preview.clock_size)
            tab["clock_position"] = self.preview.clock_position
            tab["timer_duration_minutes"] = max(1, self.preview.timer_duration_seconds // 60)
            tab["visual_state_saved"] = True
            self._update_tab_visual(self.current_tab_index, tab)

    def _preview_zoom_for_persistence(self, preview):
        """Return the factor that is actually visible for this preview mode."""
        try:
            model_zoom = max(0.01, float(preview.zoom_factor))
        except (TypeError, ValueError):
            model_zoom = 1.0

        # Slide mode uses NUMA's CSS scaling. Continuous and paper views use
        # QWebEngine page zoom, which can differ from the model factor.
        if self._loading_tab or preview.presentation_mode == "slide":
            return model_zoom
        try:
            browser_zoom = max(0.01, float(preview.web_view.zoomFactor()))
        except (AttributeError, TypeError, ValueError):
            return model_zoom
        return browser_zoom

    # ── Crash recovery autosave ──────────────────────────

    @staticmethod
    def _autosave_root():
        root = RecoveryService.autosave_root()
        root.mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def _autosave_paths_for_document(cls, path):
        service = RecoveryService(root=cls._autosave_root())
        return service.paths_for_document(path)

    def _purge_expired_autosaves(self):
        """Keep recovery copies for three days, then remove only expired data."""
        service = getattr(self, "recovery_service", RecoveryService(retention_days=self.AUTOSAVE_RETENTION_DAYS))
        removed = service.purge_expired()
        if removed:
            self._log_operation("autosaves_expirados_purgados", files=removed)

    def _document_sources_for_tab(self, tab=None, modified_only=False):
        """Return every editable source represented by one tab."""
        tab = tab if isinstance(tab, dict) else {}
        sources = []
        student_path = tab.get("presentation_script_path") or tab.get("path")
        student_content = (tab.get("presentation_script_content", "")
                           if tab.get("presentation_script_path") else tab.get("content", ""))
        if student_path and (not modified_only or tab.get("modified")):
            sources.append((student_path, student_content or ""))
        teacher_path = tab.get("teacher_script_path")
        if teacher_path and (not modified_only or tab.get("teacher_modified")):
            sources.append((teacher_path, tab.get("teacher_script_content", "") or ""))
        return sources

    def _current_document_sources(self):
        """Capture current student and teacher text without writing originals."""
        if not (0 <= self.current_tab_index < len(self.tabs)):
            return []

        self._sync_current_tab_from_editor()
        sources = []
        student_path = self._student_editor_path() or self.current_filepath
        if student_path:
            # Always use the live source. In dual mode the tab snapshot can
            # lag behind the student editor after a preview/editor switch.
            sources.append((student_path, self._student_markdown_text()))
        if self.teacher_script_path:
            sources.append((self.teacher_script_path, self.teacher_script_content))
        return sources

    def _write_recovery_copy(self, path, content):
        """Write an atomic recovery copy and its comparison metadata."""
        service = getattr(self, "recovery_service", RecoveryService(retention_days=self.AUTOSAVE_RETENTION_DAYS))
        written = service.write_recovery_copy(path, content, clean_snapshot=True)
        if not written:
            self._log_operation("autosave_error", path=path, error="write_failed")
        return written

    def _write_autosave(self, path, content):
        service = getattr(self, "recovery_service", RecoveryService(retention_days=self.AUTOSAVE_RETENTION_DAYS))
        written = service.write_autosave(path, content)
        if not written and path:
            LOGGER.debug("Autosave omitido o no escrito para %s", path)
        return written

    def _refresh_clean_backups_for_sources(self, sources):
        """Remove recovery copies when documents close normally."""
        service = getattr(self, "recovery_service", RecoveryService(retention_days=self.AUTOSAVE_RETENTION_DAYS))
        removed = service.refresh_clean_backups(sources)
        if removed:
            self._log_operation("backups_limpios_eliminados", files=removed)
        return removed

    def _remove_autosave(self, path):
        backup_path, meta_path = self._autosave_paths_for_document(path)
        for candidate in (backup_path, meta_path):
            if candidate:
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    LOGGER.exception("No se pudo eliminar autosave %s", candidate)

    def _run_autosave(self):
        if self._loading_tab:
            return
        self._purge_expired_autosaves()
        self._sync_current_tab_from_editor()
        sources_by_path = {}
        for tab in self.tabs:
            for path, content in self._document_sources_for_tab(tab, modified_only=True):
                if path:
                    sources_by_path[os.path.normcase(os.path.abspath(path))] = (path, content)
        if self.is_modified or self.teacher_is_modified:
            for path, content in self._current_document_sources():
                if path:
                    sources_by_path[os.path.normcase(os.path.abspath(path))] = (path, content)
        written = 0
        written_paths = []
        for path, content in sources_by_path.values():
            if self._write_autosave(path, content):
                written += 1
                written_paths.append(path)
        if written:
            self._show_autosave_notice(written_paths)
            self.statusBar().showMessage(f"Autosave creado ({written} archivo(s))", 2200)
            self._log_operation("autosave_creado", files=written)

    def _check_tab_autosaves(self, tab, check_student=True, check_teacher=True):
        """Offer recovery only for the sources requested from one tab.

        Opening or activating a tab checks both sources represented by that
        tab. Loading one external source later must pass a narrower scope so
        an unrelated student/teacher backup cannot prompt the user.
        """
        if not isinstance(tab, dict):
            return

        student_path = tab.get("presentation_script_path") or tab.get("path")
        if check_student and student_path:
            student_key = "presentation_script_content" if tab.get("presentation_script_path") else "content"
            recovered, was_recovered = self._read_with_autosave_offer(
                student_path,
                "el documento del alumno",
                fallback_text=tab.get(student_key, "") or "",
            )
            if was_recovered:
                tab[student_key] = recovered
                tab["modified"] = True

        teacher_path = tab.get("teacher_script_path")
        teacher_mode_active = (
            tab.get("teacher_preview_mode") in {"dual", "teacher"}
            or bool(tab.get("split_editor_enabled"))
            or tab.get("editor_role") == "teacher"
        )
        if check_teacher and teacher_path and teacher_mode_active:
            recovered, was_recovered = self._read_with_autosave_offer(
                teacher_path,
                "el guion del profesor",
                fallback_text=tab.get("teacher_script_content", "") or "",
            )
            if was_recovered:
                tab["teacher_script_content"] = recovered
                tab["teacher_modified"] = True

    def _read_with_autosave_offer(self, path, role_label="documento", fallback_text=None):
        """Read a source, offering a newer crash-recovery copy when present."""
        normalized = os.path.abspath(path)
        service = getattr(self, "recovery_service", RecoveryService(retention_days=self.AUTOSAVE_RETENTION_DAYS))
        try:
            candidate = service.inspect(normalized)
        except Exception as exc:
            LOGGER.exception("No se pudo revisar autosave para %s", normalized)
            self._log_operation("autosave_revision_error", path=normalized, error=type(exc).__name__)
            if fallback_text is not None:
                return fallback_text, False
            return Path(normalized).read_text(encoding="utf-8"), False
        if not candidate:
            if fallback_text is not None:
                return fallback_text, False
            return Path(normalized).read_text(encoding="utf-8"), False
        if not candidate.get("valid", False):
            self._log_operation(
                "autosave_integridad_invalida",
                path=normalized,
                expected_hash=candidate.get("expected_hash"),
                actual_hash=candidate.get("backup_hash"),
            )
            if fallback_text is not None:
                return fallback_text, False
            return Path(normalized).read_text(encoding="utf-8"), False
        backup_text = candidate["backup_text"]
        original_text = candidate["original_text"]
        if not (candidate["backup_is_newer"] and candidate["differs"]):
            if fallback_text is not None:
                return fallback_text, False
            return original_text, False
        metadata = candidate["metadata"]
        created = metadata.get("created_at")
        created_text = time.strftime("%Y-%m-%d %H:%M", time.localtime(created)) if created else "reciente"
        answer = QMessageBox.question(
            self,
            "Backup reciente encontrado",
            f"Se encontró un backup reciente del {role_label} ({created_text}).\n\n"
            f"Archivo correspondiente:\n{normalized}\n\n"
            "El archivo original no contiene esos cambios. ¿Deseas abrir la copia de recuperación?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        operation = "autosave_recuperado" if answer == QMessageBox.Yes else "autosave_rechazado"
        self._log_operation(
            operation,
            path=normalized,
            backup_hash=candidate["backup_hash"],
            original_hash=candidate["original_hash"],
            role=role_label,
        )
        if answer == QMessageBox.Yes:
            return backup_text, True
        if fallback_text is not None:
            return fallback_text, False
        return original_text, False

    def _clear_autosaves_for_open_documents(self):
        # Kept as a compatibility hook for the shutdown flow. A clean close
        # refreshes each backup from disk, then retention removes only old data.
        sources = []
        for tab in self.tabs:
            sources.extend(self._document_sources_for_tab(tab))
        sources.extend(self._current_document_sources())
        self._refresh_clean_backups_for_sources(sources)
        self._purge_expired_autosaves()

    @staticmethod
    def _editor_view_state(editor):
        cursor = editor.textCursor()
        return {
            "position": cursor.position(),
            "anchor": cursor.anchor(),
            "vertical": editor.verticalScrollBar().value(),
            "horizontal": editor.horizontalScrollBar().value(),
        }

    @staticmethod
    def _restore_editor_view_state(editor, state):
        if not isinstance(state, dict):
            return
        try:
            maximum = max(0, len(editor.toPlainText()))
            position = min(max(0, int(state.get("position", 0))), maximum)
            anchor = min(max(0, int(state.get("anchor", position))), maximum)
            cursor = editor.textCursor()
            cursor.setPosition(anchor)
            cursor.setPosition(position, QTextCursor.MoveMode.KeepAnchor)
            editor.setTextCursor(cursor)
            editor.verticalScrollBar().setValue(max(0, int(state.get("vertical", 0))))
            editor.horizontalScrollBar().setValue(max(0, int(state.get("horizontal", 0))))
        except (TypeError, ValueError):
            return

    def _capture_tab_navigation_state(self, tab):
        """Keep each tab's editor and preview positions independent."""
        if self.split_editor_enabled:
            tab["student_editor_state"] = self._editor_view_state(self.editor)
            tab["teacher_editor_state"] = self._editor_view_state(self.teacher_editor)
        elif self.editor_role == "teacher":
            tab["teacher_editor_state"] = self._editor_view_state(self.editor)
        else:
            tab["student_editor_state"] = self._editor_view_state(self.editor)

        tab["student_slide_index"] = max(0, int(getattr(self.preview, "_last_known_slide_index", 0)))
        tab["teacher_slide_index"] = max(0, int(getattr(self.teacher_preview, "_last_known_slide_index", 0)))

    def _create_tab(self, path=None, content="", modified=False, switch=True, check_autosave=True):
        tab = {
            "path": path,
            "content": content,
            "modified": modified,
            "presentation_script_path": None,
            "presentation_script_content": "",
            "teacher_script_path": None,
            "teacher_script_content": "",
            "teacher_preview_mode": "student",
            "dual_student_collapsed": False,
            "dual_teacher_collapsed": False,
            "student_preview_zoom": 1.0,
            "teacher_preview_zoom": 1.0,
            "present_teacher_locally": False,
            "split_editor_enabled": False,
            "editor_role": "student",
            "teacher_modified": False,
            "teacher_marker_visible": True,
            "teacher_marker_text": "PROFESOR",
            "student_sync_label_visible": False,
            "presentation_mode": "slide",
            "paper_size": "letter",
            "paper_orientation": "portrait",
            "paper_header_mode": "auto_title",
            "paper_footer_mode": "page_of_total",
            "paper_custom_header": "",
            "paper_header_right_mode": "none",
            "paper_header_right_text": "",
            "paper_footer_left_mode": "none",
            "paper_footer_left_text": "",
            "paper_font_scale": 1.0,
            "borderless": False,
            "clock_visible": False,
            "time_overlay_target": "both",
            "clock_mode": "clock",
            "clock_show_seconds": False,
            "clock_size": 22,
            "clock_position": "top-right",
            "timer_duration_minutes": 5,
            "student_editor_state": {},
            "teacher_editor_state": {},
            "student_slide_index": 0,
            "teacher_slide_index": 0,
        }
        self.tabs.append(tab)
        index = len(self.tabs) - 1
        self.tab_bar.addTab(self._tab_title(tab))
        self._update_tab_visual(index, tab)
        if switch:
            # Activating a newly opened tab must not emit an intermediate tab
            # change that calls _load_tab() with the default backup check.
            # The controlled load immediately below is the only check allowed
            # for this opening operation.
            self.tab_bar.blockSignals(True)
            try:
                self.tab_bar.setCurrentIndex(index)
            finally:
                self.tab_bar.blockSignals(False)
            self._load_tab(index, check_autosave=check_autosave)
        return index

    def _load_tab(self, index, check_autosave=True):
        if not (0 <= index < len(self.tabs)):
            return

        tab = self.tabs[index]
        if check_autosave and not tab.get("_loaded_in_session", False):
            self._check_tab_autosaves(tab)
        tab["_loaded_in_session"] = True
        self._loading_tab = True
        self.current_tab_index = index
        self.current_filepath = tab.get("path")
        self.presentation_script_path = tab.get("presentation_script_path")
        self.presentation_script_content = tab.get("presentation_script_content", "")
        self.teacher_script_path = tab.get("teacher_script_path")
        self.teacher_script_content = tab.get("teacher_script_content", "")
        self.teacher_preview_mode = tab.get("teacher_preview_mode", "student")
        self._update_tab_visual(index, tab)
        self.dual_student_collapsed = bool(tab.get("dual_student_collapsed", False))
        self.dual_teacher_collapsed = bool(tab.get("dual_teacher_collapsed", False))
        self.present_teacher_locally = bool(tab.get("present_teacher_locally", False))
        self.split_editor_enabled = bool(tab.get("split_editor_enabled", False))
        self.editor_role = tab.get("editor_role", "student")
        self.teacher_is_modified = bool(tab.get("teacher_modified", False))
        self.teacher_marker_visible = bool(tab.get("teacher_marker_visible", True))
        self.teacher_marker_text = (tab.get("teacher_marker_text", "PROFESOR") or "PROFESOR").strip() or "PROFESOR"
        self.student_sync_label_visible = bool(tab.get("student_sync_label_visible", False))
        clock_mode = tab.get("clock_mode", "clock")
        if clock_mode not in {"clock", "stopwatch", "timer"}:
            clock_mode = "clock"
        clock_visible = bool(tab.get("clock_visible", False))
        self.time_overlay_target = self._normalise_time_overlay_target(
            tab.get("time_overlay_target", "both")
        )
        self.preview.clock_visible = clock_visible
        self.preview.clock_mode = clock_mode
        self.preview.clock_show_seconds = bool(tab.get("clock_show_seconds", False))
        self.preview.clock_size = int(tab.get("clock_size", 22) or 22)
        self.preview.clock_position = tab.get("clock_position", "top-right")
        self.preview.timer_duration_seconds = max(1, int(tab.get("timer_duration_minutes", 5) or 5)) * 60
        self.preview.timer_elapsed_seconds = 0.0
        self.preview.timer_running = False
        self.preview._timer_started_at = None
        self.clock_btn.setChecked(clock_visible)
        self.clock_target_combo.blockSignals(True)
        self.clock_target_combo.setCurrentIndex(
            max(0, self.clock_target_combo.findData(self.time_overlay_target))
        )
        self.clock_target_combo.blockSignals(False)
        self._sync_time_overlay_to_previews()
        self.clock_mode_combo.blockSignals(True)
        self.clock_mode_combo.setCurrentIndex(max(0, self.clock_mode_combo.findData(clock_mode)))
        self.clock_mode_combo.blockSignals(False)
        self.clock_seconds_btn.setChecked(self.preview.clock_show_seconds)
        self.timer_minutes_input.blockSignals(True)
        self.timer_minutes_input.setValue(max(1, self.preview.timer_duration_seconds // 60))
        self.timer_minutes_input.blockSignals(False)
        self._update_time_overlay_controls()
        paper_size = tab.get("paper_size", "letter")
        if paper_size not in {"letter", "legal", "a4", "a3"}:
            paper_size = "letter"
        paper_orientation = tab.get("paper_orientation", "portrait")
        if paper_orientation not in {"portrait", "landscape"}:
            paper_orientation = "portrait"
        self._set_paper_options(paper_size, paper_orientation, refresh=False, persist=False)
        self._set_paper_running_matter(
            tab.get("paper_header_mode", "auto_title"),
            tab.get("paper_footer_mode", "page_of_total"),
            tab.get("paper_custom_header", ""),
            refresh=False,
            persist=False,
        )
        self._set_paper_secondary_matter(
            tab.get("paper_header_right_mode", "none"),
            tab.get("paper_header_right_text", ""),
            tab.get("paper_footer_left_mode", "none"),
            tab.get("paper_footer_left_text", ""),
            refresh=False,
            persist=False,
        )
        self._set_paper_font_scale(
            int(float(tab.get("paper_font_scale", 1.0) or 1.0) * 100),
            refresh=False,
            persist=False,
        )
        presentation_mode = tab.get("presentation_mode", "slide")
        if presentation_mode not in {"slide", "scroll", "paper"}:
            presentation_mode = "slide"
        self._set_presentation_mode(presentation_mode, refresh=False, persist=False)
        self.preview.zoom_factor = float(tab.get("student_preview_zoom", self.preview.zoom_factor) or 1.0)
        self.teacher_preview.zoom_factor = float(tab.get("teacher_preview_zoom", self.teacher_preview.zoom_factor) or 1.0)
        self.zoom_label.setText(f"{int(self.preview.zoom_factor * 100)}%")
        self.teacher_preview_combo.blockSignals(True)
        self.teacher_preview_combo.setCurrentIndex(max(0, self.teacher_preview_combo.findData(self.teacher_preview_mode)))
        self.teacher_preview_combo.blockSignals(False)
        self._update_teacher_marker_controls()
        self.student_sync_label_btn.setChecked(self.student_sync_label_visible)
        self._update_teacher_presentation_button()
        self.editor.set_document_path(self._student_editor_path())
        self.editor.setPlainText(self._student_editor_text())
        self.teacher_editor.set_document_path(self.teacher_script_path)
        self.teacher_editor.setPlainText(self.teacher_script_content)
        self._apply_split_editor_state()
        self._ensure_slide_ids_in_editor(mark_modified=False)
        self._repair_broken_slide_links(prompt=True)
        if tab.get("visual_state_saved"):
            # A restored session is newer than the shared preferences file.
            # This avoids an old global value reverting the mode or frame
            # after a normal close and reopen.
            try:
                font_size = max(10, min(int(tab.get("font_size", 24)), 72))
            except (TypeError, ValueError):
                font_size = 24
            self.preview.font_size = font_size
            self.teacher_preview.set_font_size(font_size)
            self._set_borderless_state(bool(tab.get("borderless", False)), persist=False)
        elif self.current_filepath:
            self._apply_file_preferences(self.current_filepath)
        self.is_modified = bool(tab.get("modified", False))
        self._loading_tab = False
        if self.editor_role == "teacher" and self.teacher_script_content and not self.split_editor_enabled:
            self._set_editor_text_quietly(self.teacher_script_content, self.teacher_script_path)
        if self.split_editor_enabled:
            self._restore_editor_view_state(self.editor, tab.get("student_editor_state"))
            self._restore_editor_view_state(self.teacher_editor, tab.get("teacher_editor_state"))
        elif self.editor_role == "teacher":
            self._restore_editor_view_state(self.editor, tab.get("teacher_editor_state"))
        else:
            self._restore_editor_view_state(self.editor, tab.get("student_editor_state"))
        self._update_title()
        student_slide = max(0, int(tab.get("student_slide_index", self._last_saved_slide_index if self.current_filepath else 0)))
        teacher_slide = max(0, int(tab.get("teacher_slide_index", 0)))
        self.preview.restore_slide_after_next_load(student_slide)
        self.teacher_preview.restore_slide_after_next_load(teacher_slide)
        self.update_preview(
            target_slide=student_slide,
            sync_teacher=False,
            teacher_target_slide=teacher_slide,
        )
        if self.nav_mode == "slides":
            self.build_slide_outline()
        if (self.teacher_preview_mode == "dual" or bool(self.teacher_script_path)) and not self.teacher_mode_enabled:
            self.toggle_teacher_mode(True)
        self._refresh_word_count()
        if self.current_filepath:
            checked_path = self.current_filepath
            QTimer.singleShot(0, lambda path=checked_path: self._offer_broken_image_repair(path))

    def _switch_to_tab(self, index):
        if self._loading_tab or index == self.current_tab_index:
            return
        if not (0 <= index < len(self.tabs)):
            return
        self._log_operation("cambiar_pestana", target_tab=index + 1)
        self._sync_current_tab_from_editor()
        if 0 <= self.current_tab_index < len(self.tabs):
            outgoing = self.tabs[self.current_tab_index]
            for path, content in self._document_sources_for_tab(outgoing, modified_only=True):
                self._write_autosave(path, content)
        self._load_tab(index)

    def _on_tab_moved(self, from_index, to_index):
        if not (0 <= from_index < len(self.tabs) and 0 <= to_index < len(self.tabs)):
            return
        self._log_operation("reordenar_pestana", origen=from_index + 1, destino=to_index + 1)
        tab = self.tabs.pop(from_index)
        self.tabs.insert(to_index, tab)
        self.current_tab_index = self.tab_bar.currentIndex()

    def _close_tab(self, index):
        if not (0 <= index < len(self.tabs)):
            return
        if index == self.current_tab_index:
            # Visual preferences are independent from unsaved Markdown text.
            # Store them before the close confirmation so a discarded edit does
            # not discard the user's working view.
            self._remember_current_file_preferences(include_visual=True)

        if index == self.current_tab_index:
            self._sync_current_tab_from_editor()

        tab = self.tabs[index]
        if tab.get("modified") or tab.get("teacher_modified"):
            name = os.path.basename(tab["path"]) if tab.get("path") else "Sin titulo"
            reply = QMessageBox.question(
                self,
                "Cerrar pestana",
                f"Hay cambios sin guardar en {name}. ¿Deseas guardar antes de cerrar?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.Save:
                current_before = self.current_tab_index
                self._load_tab(index)
                if not self.file_save():
                    self._load_tab(current_before)
                    return
                self._sync_current_tab_from_editor()

        # A normal tab close leaves a backup identical to the file on disk.
        # Unsaved edits were either saved above or intentionally discarded.
        self._refresh_clean_backups_for_sources(self._document_sources_for_tab(tab))

        del self.tabs[index]
        self.tab_bar.removeTab(index)

        if not self.tabs:
            self.current_tab_index = -1
            self._create_tab(None, "", modified=False, switch=True)
            return

        next_index = min(index, len(self.tabs) - 1)
        self.current_tab_index = -1
        self.tab_bar.setCurrentIndex(next_index)
        self._load_tab(next_index)

    def create_actions(self):
        self.new_act = QAction("Nuevo", self)
        self.new_act.setShortcut(QKeySequence.New)
        self.new_act.setStatusTip("Crear un nuevo documento")
        self.new_act.triggered.connect(self.file_new)

        self.new_template_act = QAction("Nuevo desde plantilla...", self)
        self.new_template_act.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.new_template_act.setStatusTip("Crear una nueva presentación desde una plantilla lista")
        self.new_template_act.triggered.connect(self.show_template_picker)

        self.quick_guide_act = QAction("Guía rápida de Markdown...", self)
        self.quick_guide_act.setShortcut(QKeySequence("F1"))
        self.quick_guide_act.setStatusTip("Ver bloques de Markdown con inserción rápida y atajos")
        self.quick_guide_act.triggered.connect(self.show_quick_guide)

        self.open_act = QAction("Abrir", self)
        self.open_act.setShortcut(QKeySequence.Open)
        self.open_act.setStatusTip("Abrir un documento Markdown")
        self.open_act.triggered.connect(self.file_open)

        self.save_act = QAction("Guardar", self)
        self.save_act.setShortcut(QKeySequence.Save)
        self.save_act.setStatusTip("Guardar el documento actual")
        self.save_act.triggered.connect(self.file_save)

        self.save_teacher_act = QAction("Guardar Profesor", self)
        self.save_teacher_act.setStatusTip("Guardar solamente el guion del profesor")
        self.save_teacher_act.triggered.connect(self.file_save_teacher)

        self.save_as_act = QAction("Guardar Como", self)
        self.save_as_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_act.setStatusTip("Guardar como nuevo archivo")
        self.save_as_act.triggered.connect(self.file_save_as)

        self.export_pdf_act = QAction("Exportar PDF", self)
        self.export_pdf_act.setShortcut(QKeySequence("Ctrl+E"))
        self.export_pdf_act.setStatusTip("Exportar presentacion como PDF")
        self.export_pdf_act.triggered.connect(self.export_pdf)

        self.find_act = QAction("Buscar...", self)
        self.find_act.setShortcut(QKeySequence.Find)
        self.find_act.setStatusTip("Buscar texto en el editor activo")
        self.find_act.triggered.connect(self.show_find_replace_dialog)

        self.replace_act = QAction("Buscar y reemplazar...", self)
        self.replace_act.setShortcut(QKeySequence("Ctrl+H"))
        self.replace_act.setStatusTip("Buscar y reemplazar texto en el editor activo")
        self.replace_act.triggered.connect(lambda: self.show_find_replace_dialog(show_replace=True))

        self.about_act = QAction("Acerca de", self)
        self.about_act.triggered.connect(self.show_about)

        self.exit_act = QAction("Salir", self)
        self.exit_act.setShortcut(QKeySequence("Ctrl+Q"))
        self.exit_act.triggered.connect(self.close)

    def create_toolbar(self):
        self.toolbar = QToolBar("Herramientas", self)
        self.toolbar.setIconSize(QSize(20, 20))
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.addToolBar(self.toolbar)

        # File actions share one compact project menu.
        self.file_menu_btn = QToolButton(self)
        self.file_menu_btn.setText("Archivo")
        self.file_menu_btn.setToolTip("Crear, abrir, guardar y administrar archivos")
        self.file_menu = QMenu(self.file_menu_btn)
        self.file_menu.addAction(self.new_act)
        self.file_menu.addAction(self.new_template_act)
        self.file_menu.addAction(self.open_act)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.save_act)
        self.file_menu.addAction(self.save_teacher_act)
        self.file_menu.addAction(self.save_as_act)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.quick_guide_act)
        self.file_menu.addAction(self.about_act)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_act)
        self.file_menu_btn.setMenu(self.file_menu)
        self.file_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(self.file_menu_btn)
        self.open_quick_btn = QToolButton(self)
        self.open_quick_btn.setObjectName("quickOpenBtn")
        self.open_quick_btn.setText("Abrir")
        self.open_quick_btn.setToolTip("Abrir un archivo Markdown (Ctrl+O)")
        self.open_quick_btn.clicked.connect(self.file_open)
        self.toolbar.addWidget(self.open_quick_btn)
        self.save_quick_btn = QToolButton(self)
        self.save_quick_btn.setObjectName("quickSaveBtn")
        self.save_quick_btn.setText("Guardar")
        self.save_quick_btn.setToolTip("Guardar el documento activo (Ctrl+S)")
        self.save_quick_btn.clicked.connect(self.file_save)
        self.toolbar.addWidget(self.save_quick_btn)
        self.save_teacher_act.setVisible(False)
        self.toolbar.addSeparator()

        self.view_menu_btn = QToolButton(self)
        self.view_menu_btn.setText("Vista")
        self.view_menu_btn.setToolTip("Configurar paneles y barras visibles")
        self.view_menu = QMenu(self.view_menu_btn)
        show_menu = self.view_menu.addMenu("Mostrar")
        self.view_markdown_toolbar_action = show_menu.addAction("Barra de Markdown")
        self.view_markdown_toolbar_action.setCheckable(True)
        self.view_markdown_toolbar_action.setChecked(self.md_toolbar_visible)
        self.view_markdown_toolbar_action.toggled.connect(self._toggle_markdown_toolbar_visibility)
        self.view_presentation_toolbar_action = show_menu.addAction("Barra de Presentar")
        self.view_presentation_toolbar_action.setCheckable(True)
        self.view_presentation_toolbar_action.setChecked(self.presentation_toolbar_visible)
        self.view_presentation_toolbar_action.toggled.connect(self._toggle_presentation_toolbar_visibility)
        self.view_image_toolbar_action = show_menu.addAction("Barra de Imagen")
        self.view_image_toolbar_action.setCheckable(True)
        self.view_image_toolbar_action.setChecked(self.image_toolbar_visible)
        self.view_image_toolbar_action.toggled.connect(self._toggle_image_toolbar_visibility)
        self.view_links_toolbar_action = show_menu.addAction("Barra de Vinculos")
        self.view_links_toolbar_action.setCheckable(True)
        self.view_links_toolbar_action.setChecked(self.links_toolbar_visible)
        self.view_links_toolbar_action.toggled.connect(self._toggle_links_toolbar_visibility)
        show_menu.addSeparator()
        show_menu.addAction("Panel de Slides", self.toggle_navigation_panel)
        self.view_menu_btn.setMenu(self.view_menu)
        self.view_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(self.view_menu_btn)
        self.toolbar.addSeparator()

        # Recent files
        self.recent_btn = QPushButton("Recientes", self)
        self.recent_btn.setToolTip("Abrir archivo reciente")
        self.recent_btn.clicked.connect(self.show_recent_files)
        self.toolbar.addWidget(self.recent_btn)

        self.toolbar.addSeparator()

        # Export
        self.export_pdf_btn = QPushButton("Exportar PDF", self)
        self.export_pdf_btn.setObjectName("softMintBtn")
        self.export_pdf_btn.setToolTip("Exportar presentacion como PDF (Ctrl+E)")
        self.export_pdf_btn.clicked.connect(self.export_pdf)
        self.toolbar.addWidget(self.export_pdf_btn)

        self.toolbar.addSeparator()

        # Mode
        self.mode_btn = QPushButton("Modo: Diapositivas", self)
        self.mode_btn.setObjectName("softBlueBtn")
        self.mode_btn.setToolTip("Elegir modo de visualizacion")
        self.mode_menu = QMenu(self.mode_btn)
        for label, mode in (
            ("Diapositivas", "slide"),
            ("Continuo", "scroll"),
            ("Hoja impresa", "paper"),
        ):
            action = self.mode_menu.addAction(label)
            action.setData(mode)
            action.triggered.connect(lambda checked=False, value=mode: self.set_presentation_mode(value))
        self.mode_btn.setMenu(self.mode_menu)
        self.toolbar.addWidget(self.mode_btn)

        self.page_settings_btn = QToolButton(self)
        self.page_settings_btn.setText("Configurar pagina")
        self.page_settings_btn.setToolTip("Configurar hoja impresa")
        self.page_settings_btn.clicked.connect(self.show_paper_settings_popup)
        self.page_settings_btn.hide()
        self.page_settings_action = self.toolbar.addWidget(self.page_settings_btn)

        self.paper_size_combo = QComboBox(self)
        self.paper_size_combo.setToolTip("Tamano de hoja para el modo Hoja impresa")
        self.paper_size_combo.addItem("Carta", "letter")
        self.paper_size_combo.addItem("Oficio", "legal")
        self.paper_size_combo.addItem("A4", "a4")
        self.paper_size_combo.addItem("A3", "a3")
        self.paper_size_combo.currentIndexChanged.connect(self._paper_options_changed)

        self.paper_orientation_combo = QComboBox(self)
        self.paper_orientation_combo.setToolTip("Orientacion de hoja para el modo Hoja impresa")
        self.paper_orientation_combo.addItem("Vertical", "portrait")
        self.paper_orientation_combo.addItem("Horizontal", "landscape")
        self.paper_orientation_combo.currentIndexChanged.connect(self._paper_options_changed)

        self.toolbar.addSeparator()

        # Zoom
        self.zoom_out_btn = QPushButton("−", self)
        self.zoom_out_btn.setFixedWidth(34)
        self.zoom_out_btn.setToolTip("Disminuir zoom (Ctrl+- / Numpad -)")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.toolbar.addWidget(self.zoom_out_btn)

        self.zoom_label = QPushButton("100%", self)
        self.zoom_label.setObjectName("zoomPctBtn")
        self.zoom_label.setFixedWidth(58)
        self.zoom_label.setToolTip("Restablecer zoom al 100% (Ctrl+0)")
        self.zoom_label.clicked.connect(self.zoom_reset)
        self.toolbar.addWidget(self.zoom_label)

        self.exact_zoom_input = QSpinBox(self)
        self.exact_zoom_input.setRange(1, 10000)
        self.exact_zoom_input.setSingleStep(5)
        self.exact_zoom_input.setSuffix("%")
        self.exact_zoom_input.setFixedWidth(78)
        self.exact_zoom_input.setToolTip("Definir el zoom exacto de la hoja impresa")
        self.exact_zoom_input.valueChanged.connect(self.set_exact_preview_zoom)

        self.paper_header_combo = QComboBox(self)
        self.paper_header_combo.setToolTip("Estilo de encabezado sugerido para cada hoja")
        self.paper_header_combo.addItem("Encabezado: titulo", "auto_title")
        self.paper_header_combo.addItem("Encabezado: subtitulo", "subtitle")
        self.paper_header_combo.addItem("Encabezado: titulo y subtitulo", "auto_hierarchy")
        self.paper_header_combo.addItem("Encabezado personalizado", "custom")
        self.paper_header_combo.addItem("Sin encabezado", "none")
        self.paper_header_combo.currentIndexChanged.connect(self._paper_running_matter_changed)

        self.paper_footer_combo = QComboBox(self)
        self.paper_footer_combo.setToolTip("Estilo de pie de pagina")
        self.paper_footer_combo.addItem("Pie: pagina de total", "page_of_total")
        self.paper_footer_combo.addItem("Pie: solo pagina", "page")
        self.paper_footer_combo.addItem("Pie: titulo y subtitulo", "auto_hierarchy")
        self.paper_footer_combo.addItem("Sin pie", "none")
        self.paper_footer_combo.currentIndexChanged.connect(self._paper_running_matter_changed)

        self.paper_custom_header_input = QLineEdit(self)
        self.paper_custom_header_input.setPlaceholderText("Encabezado personalizado")
        self.paper_custom_header_input.setMinimumWidth(220)
        self.paper_custom_header_input.editingFinished.connect(self._paper_running_matter_changed)

        self.paper_header_right_combo = QComboBox(self)
        self.paper_header_right_combo.setToolTip("Bloque derecho del encabezado")
        self.paper_footer_left_combo = QComboBox(self)
        self.paper_footer_left_combo.setToolTip("Bloque izquierdo del pie de pagina")
        for combo in (self.paper_header_right_combo, self.paper_footer_left_combo):
            combo.addItem("Solo titulo", "title")
            combo.addItem("Solo subtitulo", "subtitle")
            combo.addItem("Titulo y subtitulo", "auto_hierarchy")
            combo.addItem("Texto personalizado", "custom")
            combo.addItem("Sin bloque", "none")
            combo.currentIndexChanged.connect(self._paper_secondary_matter_changed)

        self.paper_header_right_input = QLineEdit(self)
        self.paper_header_right_input.setPlaceholderText("Texto de encabezado derecho")
        self.paper_header_right_input.setMinimumWidth(220)
        self.paper_header_right_input.editingFinished.connect(self._paper_secondary_matter_changed)
        self.paper_footer_left_input = QLineEdit(self)
        self.paper_footer_left_input.setPlaceholderText("Texto de pie izquierdo")
        self.paper_footer_left_input.setMinimumWidth(220)
        self.paper_footer_left_input.editingFinished.connect(self._paper_secondary_matter_changed)

        self.paper_font_scale_input = QSpinBox(self)
        self.paper_font_scale_input.setRange(50, 200)
        self.paper_font_scale_input.setSingleStep(5)
        self.paper_font_scale_input.setValue(100)
        self.paper_font_scale_input.setSuffix("% texto")
        self.paper_font_scale_input.setToolTip("Reducir o ampliar la tipografia para ajustar contenido por hoja")
        self.paper_font_scale_input.valueChanged.connect(self._set_paper_font_scale)

        paper_label = QLabel("Hoja:", self.paper_toolbar)
        paper_label.setObjectName("timeToolbarLabel")
        self.paper_toolbar_layout.addWidget(paper_label)
        self.paper_toolbar_layout.addWidget(self.paper_size_combo)
        self.paper_toolbar_layout.addWidget(self.paper_orientation_combo)
        zoom_label = QLabel("Zoom exacto:", self.paper_toolbar)
        zoom_label.setObjectName("timeToolbarLabel")
        self.paper_toolbar_layout.addWidget(zoom_label)
        self.paper_toolbar_layout.addWidget(self.exact_zoom_input)
        self.paper_toolbar_layout.addWidget(self.paper_header_combo)
        self.paper_toolbar_layout.addWidget(self.paper_footer_combo)
        self.paper_toolbar_layout.addWidget(self.paper_custom_header_input)
        self.paper_toolbar_layout.addWidget(self.paper_header_right_combo)
        self.paper_toolbar_layout.addWidget(self.paper_header_right_input)
        self.paper_toolbar_layout.addWidget(self.paper_footer_left_combo)
        self.paper_toolbar_layout.addWidget(self.paper_footer_left_input)
        self.paper_toolbar_layout.addWidget(self.paper_font_scale_input)

        self.zoom_in_btn = QPushButton("+", self)
        self.zoom_in_btn.setFixedWidth(34)
        self.zoom_in_btn.setToolTip("Aumentar zoom (Ctrl+= / Numpad +)")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.toolbar.addWidget(self.zoom_in_btn)

        self.zoom_reset_btn = QPushButton("Reset", self)
        self.zoom_reset_btn.setToolTip("Restablecer zoom al 100% (Ctrl+0)")
        self.zoom_reset_btn.clicked.connect(self.zoom_reset)
        self.zoom_reset_btn.hide()

        self.toolbar.addSeparator()

        # Theme settings are global: automatic follows the Windows color mode.
        self.theme_btn = QToolButton(self)
        self.theme_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.theme_btn.setToolTip("Elegir tema automático, claro u oscuro")
        theme_menu = QMenu(self.theme_btn)
        self.theme_auto_act = theme_menu.addAction("Automático (Windows)")
        self.theme_light_act = theme_menu.addAction("Modo Claro")
        self.theme_dark_act = theme_menu.addAction("Modo Oscuro")
        for action in (self.theme_auto_act, self.theme_light_act, self.theme_dark_act):
            action.setCheckable(True)
        self.theme_auto_act.triggered.connect(lambda: self._set_theme_preference("system"))
        self.theme_light_act.triggered.connect(lambda: self._set_theme_preference("light"))
        self.theme_dark_act.triggered.connect(lambda: self._set_theme_preference("dark"))
        self.theme_btn.setMenu(theme_menu)
        self.toolbar.addWidget(self.theme_btn)

        self.toolbar.addSeparator()

        # Borderless toggle
        self.borderless_btn = QPushButton("Sin Marco", self)
        self.borderless_btn.setToolTip("Alternar marco en diapositivas (F8)")
        self.borderless_btn.setCheckable(True)
        self.borderless_btn.clicked.connect(self.toggle_borderless)
        self.toolbar.addWidget(self.borderless_btn)

        # Push primary presentation CTA to the right for unmistakable hierarchy.
        toolbar_spacer = QWidget(self)
        toolbar_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(toolbar_spacer)

        self.toolbar_present_btn = QPushButton("▶ PRESENTAR", self)
        self.toolbar_present_btn.setObjectName("primaryBtn")
        self.toolbar_present_btn.setToolTip("Iniciar presentación en pantalla completa (F11)")
        self.toolbar_present_btn.clicked.connect(self.toggle_fullscreen_presentation)
        self.toolbar.addWidget(self.toolbar_present_btn)

        self.presentation_toolbar_action = None

        self.clock_mode_combo = QComboBox(self)
        self.clock_mode_combo.setToolTip("Elegir reloj, cronometro o temporizador")
        self.clock_mode_combo.addItem("Reloj", "clock")
        self.clock_mode_combo.addItem("Cronometro", "stopwatch")
        self.clock_mode_combo.addItem("Temporizador", "timer")
        self.clock_mode_combo.currentIndexChanged.connect(self.change_clock_mode)
        self.time_toolbar_layout.addWidget(self.clock_mode_combo)

        self.clock_btn = QPushButton("Mostrar", self)
        self.clock_btn.setToolTip("Mostrar u ocultar el indicador de tiempo en presentacion")
        self.clock_btn.setCheckable(True)
        self.clock_btn.setObjectName("softMangoBtn")
        self.clock_btn.clicked.connect(self.toggle_clock)
        self.time_toolbar_layout.addWidget(self.clock_btn)

        self.clock_target_combo = QComboBox(self)
        self.clock_target_combo.setToolTip("Elegir en que presentacion se muestra el indicador de tiempo")
        self.clock_target_combo.addItem("Alumno", "student")
        self.clock_target_combo.addItem("Profesor", "teacher")
        self.clock_target_combo.addItem("Ambas", "both")
        self.clock_target_combo.setCurrentIndex(2)
        self.clock_target_combo.currentIndexChanged.connect(self.change_time_overlay_target)
        self.time_toolbar_layout.addWidget(self.clock_target_combo)

        self.clock_seconds_btn = QPushButton("Seg", self)
        self.clock_seconds_btn.setToolTip("Mostrar segundos en el reloj")
        self.clock_seconds_btn.setCheckable(True)
        self.clock_seconds_btn.clicked.connect(self.toggle_clock_seconds)
        self.clock_seconds_action = None
        self.time_toolbar_layout.addWidget(self.clock_seconds_btn)

        self.timer_minutes_input = QSpinBox(self)
        self.timer_minutes_input.setRange(1, 24 * 60)
        self.timer_minutes_input.setValue(5)
        self.timer_minutes_input.setSuffix(" min")
        self.timer_minutes_input.setToolTip("Duracion inicial del temporizador")
        self.timer_minutes_input.valueChanged.connect(self.change_timer_duration)
        self.timer_minutes_action = None
        self.time_toolbar_layout.addWidget(self.timer_minutes_input)

        self.timer_start_btn = QPushButton("Iniciar", self)
        self.timer_start_btn.setToolTip("Iniciar o pausar el cronometro o temporizador")
        self.timer_start_btn.clicked.connect(self.toggle_timer_running)
        self.timer_start_action = None
        self.time_toolbar_layout.addWidget(self.timer_start_btn)

        self.timer_reset_btn = QPushButton("Reiniciar", self)
        self.timer_reset_btn.setToolTip("Reiniciar el cronometro o temporizador")
        self.timer_reset_btn.clicked.connect(self.reset_timer)
        self.timer_reset_action = None
        self.time_toolbar_layout.addWidget(self.timer_reset_btn)

        self.clock_size_down_btn = QPushButton("Hora -", self)
        self.clock_size_down_btn.setToolTip("Reducir tamano del reloj")
        self.clock_size_down_btn.clicked.connect(self.decrease_clock_size)
        self.time_toolbar_layout.addWidget(self.clock_size_down_btn)

        self.clock_size_up_btn = QPushButton("Hora +", self)
        self.clock_size_up_btn.setToolTip("Aumentar tamano del reloj")
        self.clock_size_up_btn.clicked.connect(self.increase_clock_size)
        self.time_toolbar_layout.addWidget(self.clock_size_up_btn)

        self.clock_position_combo = QComboBox(self)
        self.clock_position_combo.setToolTip("Ubicacion del reloj")
        self.clock_position_combo.addItem("Sup Izq", "top-left")
        self.clock_position_combo.addItem("Sup Der", "top-right")
        self.clock_position_combo.addItem("Inf Izq", "bottom-left")
        self.clock_position_combo.addItem("Inf Der", "bottom-right")
        self.clock_position_combo.setCurrentIndex(1)
        self.clock_position_combo.currentIndexChanged.connect(self.change_clock_position)
        self.time_toolbar_layout.addWidget(self.clock_position_combo)
        self.time_toolbar.updateGeometry()
        self._update_time_overlay_controls()

        # Presentation actions remain together beside the time controls.
        self.presentation_actions_block = QFrame(self.time_toolbar)
        self.presentation_actions_block.setObjectName("presentationActionsBlock")
        presentation_actions_layout = QHBoxLayout(self.presentation_actions_block)
        presentation_actions_layout.setContentsMargins(6, 3, 6, 3)
        presentation_actions_layout.setSpacing(5)

        self.present_btn = QPushButton("PRESENTAR", self.presentation_actions_block)
        self.present_btn.setObjectName("accentBtn")
        self.present_btn.setToolTip("Pantalla completa (F11)")
        self.present_btn.clicked.connect(self.toggle_fullscreen_presentation)
        presentation_actions_layout.addWidget(self.present_btn)

        self.present_teacher_btn = QPushButton("Presentar Profesor", self.presentation_actions_block)
        self.present_teacher_btn.setObjectName("softBlueBtn")
        self.present_teacher_btn.setToolTip("Abrir o cerrar el guion del profesor en modo presentacion")
        self.present_teacher_btn.clicked.connect(self.toggle_teacher_local_presentation)
        presentation_actions_layout.addWidget(self.present_teacher_btn)

        self.present_dual_btn = QPushButton("Presentar Dual", self.presentation_actions_block)
        self.present_dual_btn.setObjectName("softBlueBtn")
        self.present_dual_btn.setToolTip("Control dual: alumno arriba, profesor abajo y alumno en segunda pantalla")
        self.present_dual_btn.clicked.connect(self.toggle_dual_control_presentation)
        presentation_actions_layout.addWidget(self.present_dual_btn)
        self.time_toolbar_layout.addWidget(self.presentation_actions_block)
        self._create_compact_context_controls()
        self.time_toolbar.updateGeometry()

    def _create_shortcut_settings_block(self):
        """Create the collapsible global shortcut editor."""
        container = QFrame(self)
        container.setObjectName("shortcutSettingsContainer")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        block_layout = QVBoxLayout(container)
        block_layout.setContentsMargins(0, 0, 0, 4)
        block_layout.setSpacing(4)

        content = QWidget(container)
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(4, 0, 4, 0)
        content_layout.setSpacing(6)

        label = QLabel("Accion", content)
        content_layout.addWidget(label)
        self.shortcut_action_combo = QComboBox(content)
        self.shortcut_action_combo.setMinimumWidth(290)
        self.shortcut_action_combo.setToolTip("Seleccionar la accion que recibira el atajo")
        for action_id, description, default, callback, scope in self.SHORTCUT_DEFINITIONS:
            self.shortcut_action_combo.addItem(description, action_id)
        self.shortcut_action_combo.currentIndexChanged.connect(self._load_selected_shortcut)
        content_layout.addWidget(self.shortcut_action_combo, stretch=1)

        self.shortcut_sequence_edit = QKeySequenceEdit(content)
        self.shortcut_sequence_edit.setMaximumSequenceLength(1)
        self.shortcut_sequence_edit.setToolTip("Presiona una tecla o combinacion para asignarla")
        self.shortcut_sequence_edit.editingFinished.connect(self._save_selected_shortcut)
        content_layout.addWidget(self.shortcut_sequence_edit)

        apply_button = QPushButton("Aplicar", content)
        apply_button.setObjectName("accentBtn")
        apply_button.setToolTip("Guardar el atajo seleccionado")
        apply_button.clicked.connect(self._save_selected_shortcut)
        content_layout.addWidget(apply_button)

        clear_button = QPushButton("Limpiar", content)
        clear_button.setToolTip("Quitar el atajo de la accion seleccionada")
        clear_button.clicked.connect(self._clear_selected_shortcut)
        content_layout.addWidget(clear_button)

        self.shortcut_settings_content = content
        block_layout.addWidget(content)

        self.shortcut_feedback_label = QLabel("", container)
        self.shortcut_feedback_label.setObjectName("shortcutFeedback")
        self.shortcut_feedback_label.setVisible(False)
        block_layout.addWidget(self.shortcut_feedback_label)
        self.shortcut_feedback_timer = QTimer(container)
        self.shortcut_feedback_timer.setSingleShot(True)
        self.shortcut_feedback_timer.timeout.connect(self.shortcut_feedback_label.hide)

        content.setVisible(True)
        container.setVisible(False)
        self._load_selected_shortcut()
        return container

    def _toggle_shortcut_toolbar_visibility(self, checked=None):
        if isinstance(checked, bool):
            visible = checked
            self.shortcut_settings_collapsed = not visible
        else:
            visible = self.shortcut_settings_collapsed
            self.shortcut_settings_collapsed = not visible
            visible = not self.shortcut_settings_collapsed
        self.shortcut_toolbar.setVisible(visible)
        if hasattr(self, "shortcuts_toolbar_direct_btn"):
            self.shortcuts_toolbar_direct_btn.blockSignals(True)
            self.shortcuts_toolbar_direct_btn.setChecked(visible)
            self.shortcuts_toolbar_direct_btn.blockSignals(False)
        self.shortcut_toolbar.updateGeometry()
        self.statusBar().showMessage(
            "Configuracion de atajos visible" if visible else "Configuracion de atajos oculta",
            1500,
        )

    def toggle_shortcut_settings(self):
        """Compatibility entry point for opening or closing the shortcut block."""
        self._toggle_shortcut_toolbar_visibility()

    def _load_selected_shortcut(self):
        if self.shortcut_sequence_edit is None or self.shortcut_action_combo is None:
            return
        action_id = self.shortcut_action_combo.currentData()
        self.shortcut_sequence_edit.blockSignals(True)
        self.shortcut_sequence_edit.setKeySequence(
            QKeySequence(self.shortcut_bindings.get(action_id, ""))
        )
        self.shortcut_sequence_edit.blockSignals(False)

    def _save_selected_shortcut(self):
        if self.shortcut_sequence_edit is None or self.shortcut_action_combo is None:
            return
        action_id = self.shortcut_action_combo.currentData()
        if not action_id:
            return
        sequence = self.shortcut_sequence_edit.keySequence()
        sequence_text = sequence.toString(QKeySequence.SequenceFormat.PortableText)
        for other_id, other_sequence in self.shortcut_bindings.items():
            if other_id != action_id and other_sequence and other_sequence == sequence_text:
                self.shortcut_sequence_edit.blockSignals(True)
                self._load_selected_shortcut()
                self.shortcut_sequence_edit.blockSignals(False)
                QMessageBox.warning(
                    self,
                    "Atajo duplicado",
                    "Ese atajo ya esta asignado a otra accion. Elige otra tecla o combinacion.",
                )
                return
        self.shortcut_bindings[action_id] = sequence_text
        shortcut = self.shortcut_objects.get(action_id)
        if shortcut is not None:
            shortcut.setKey(sequence)
        self._update_presentation_window_shortcut(action_id, sequence)
        self._save_shortcut_preferences()
        self._show_shortcut_feedback(
            f"Atajo aplicado: {self.shortcut_action_combo.currentText()} -> "
            f"{sequence_text or 'sin asignar'}"
        )
        self.statusBar().showMessage(
            f"Atajo guardado: {sequence_text or 'sin asignar'}", 1800
        )

    def _show_shortcut_feedback(self, message):
        self.shortcut_feedback_label.setText(message)
        self.shortcut_feedback_label.setVisible(True)
        self.shortcut_feedback_timer.start(3500)

    def _clear_selected_shortcut(self):
        if self.shortcut_sequence_edit is None:
            return
        self.shortcut_sequence_edit.clear()
        self._save_selected_shortcut()

    def _compact_context_menu_button(self, text, tooltip, menu):
        button = QToolButton(self.time_toolbar)
        button.setText(text)
        button.setToolTip(tooltip)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.time_toolbar_layout.addWidget(button)
        return button

    def _create_compact_context_controls(self):
        """Expose contextual workflows without permanently consuming rows."""
        self.compact_header_enabled = True
        for widget in (
            self.clock_mode_combo, self.clock_btn, self.clock_target_combo,
            self.clock_seconds_btn, self.timer_minutes_input,
            self.timer_start_btn, self.timer_reset_btn,
            self.clock_size_down_btn, self.clock_size_up_btn,
            self.clock_position_combo, self.presentation_actions_block,
        ):
            widget.hide()

        self.slides_panel_btn = QToolButton(self.time_toolbar)
        self.slides_panel_btn.setText("Slides")
        self.slides_panel_btn.setToolTip("Mostrar u ocultar el panel lateral de diapositivas y archivos")
        self.slides_panel_btn.setCheckable(True)
        self.slides_panel_btn.setChecked(not self.nav_panel_collapsed)
        self.slides_panel_btn.clicked.connect(self.toggle_navigation_panel)
        self.time_toolbar_layout.addWidget(self.slides_panel_btn)

        time_menu = QMenu(self)
        modes_menu = time_menu.addMenu("Tipo")
        for label, value in (("Reloj", "clock"), ("Cronometro", "stopwatch"), ("Temporizador", "timer")):
            action = modes_menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, mode=value: self.clock_mode_combo.setCurrentIndex(
                    max(0, self.clock_mode_combo.findData(mode))
                )
            )
        time_menu.addAction("Mostrar u ocultar", self.clock_btn.click)
        audience_menu = time_menu.addMenu("Mostrar en")
        for label, value in (("Alumno", "student"), ("Profesor", "teacher"), ("Ambas", "both")):
            action = audience_menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, target=value: self.clock_target_combo.setCurrentIndex(
                    max(0, self.clock_target_combo.findData(target))
                )
            )
        time_menu.addSeparator()
        time_menu.addAction("Segundos", self.clock_seconds_btn.click)
        time_menu.addAction("Iniciar / Pausar", self.timer_start_btn.click)
        time_menu.addAction("Reiniciar", self.timer_reset_btn.click)
        time_menu.addAction("Reducir tamano", self.clock_size_down_btn.click)
        time_menu.addAction("Aumentar tamano", self.clock_size_up_btn.click)
        self.time_menu_btn = self._compact_context_menu_button("Tiempo", "Reloj, cronometro y temporizador", time_menu)

        presentation_menu = QMenu(self)
        presentation_menu.addAction("Presentar", self.present_btn.click)
        presentation_menu.addAction("Presentar profesor", self.present_teacher_btn.click)
        presentation_menu.addAction("Presentar dual", self.present_dual_btn.click)
        self.presentation_menu_btn = self._compact_context_menu_button("Presentar", "Opciones de presentacion", presentation_menu)

        role_menu = QMenu(self)
        role_menu.addAction("Cargar guion profesor", self.teacher_load_btn.click)
        role_menu.addAction("Elegir presentacion alumno", self.presentation_load_btn.click)
        role_menu.addAction("Alternar editor dual", self.split_editor_btn.click)
        views_menu = role_menu.addMenu("Vista previa")
        for label, value in (("Alumno", "student"), ("Dual", "dual"), ("Profesor", "teacher")):
            action = views_menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, view=value: self.teacher_preview_combo.setCurrentIndex(
                    max(0, self.teacher_preview_combo.findData(view))
                )
            )
        role_menu.addAction("Colapsar alumno", self.student_collapse_btn.click)
        role_menu.addAction("Colapsar profesor", self.teacher_collapse_btn.click)
        self.role_menu_btn = self._compact_context_menu_button("Rol y vistas", "Alumno, profesor y vista dual", role_menu)

        sync_menu = QMenu(self)
        sync_menu.addAction("Vincular slide", self.teacher_sync_btn.click)
        sync_menu.addAction("Desvincular slide", self.clear_slide_sync_btn.click)
        sync_menu.addAction("Desvincular documento", self.clear_sync_btn.click)
        sync_menu.addAction("Mostrar vinculo profesor", self.student_sync_label_btn.click)
        self.sync_menu_btn = self._compact_context_menu_button("Vínculos", "Sincronización alumno-profesor", sync_menu)

        markdown_menu = QMenu(self)
        markdown_menu.addAction(self.find_act)
        markdown_menu.addAction(self.replace_act)
        markdown_menu.addSeparator()
        history_menu = markdown_menu.addMenu("Historial")
        history_menu.addAction("Deshacer", lambda: self._active_markdown_editor().undo())
        history_menu.addAction("Rehacer", lambda: self._active_markdown_editor().redo())
        format_menu = markdown_menu.addMenu("Formato")
        format_menu.addAction("Negrita", lambda: self._md_wrap("**", "**"))
        format_menu.addAction("Cursiva", lambda: self._md_wrap("*", "*"))
        format_menu.addAction("Tachado", lambda: self._md_wrap("~~", "~~"))
        alignment_menu = format_menu.addMenu("Alineacion")
        alignment_menu.addAction("Alinear a la izquierda", lambda: self._md_align("left"))
        alignment_menu.addAction("Centrar", lambda: self._md_align("center"))
        alignment_menu.addAction("Alinear a la derecha", lambda: self._md_align("right"))
        alignment_menu.addAction("Justificar", lambda: self._md_align("justify"))
        alignment_menu.addSeparator()
        alignment_menu.addAction("Justificar todo el documento", self._md_justify_document)
        headings_menu = markdown_menu.addMenu("Encabezados")
        for level in range(1, 6):
            headings_menu.addAction(f"H{level}", lambda checked=False, value=level: self._md_prefix("#" * value + " "))
        lists_menu = markdown_menu.addMenu("Listas")
        lists_menu.addAction("Vinetas", lambda: self._md_prefix("- "))
        lists_menu.addAction("Numerada", lambda: self._md_prefix("1. "))
        lists_menu.addAction("Tareas", lambda: self._md_prefix("- [ ] "))
        insert_menu = markdown_menu.addMenu("Insertar")
        insert_menu.addAction("Enlace", self._md_insert_link)
        insert_menu.addAction("Enlace a slide", self._md_insert_slide_link)
        insert_menu.addAction("Archivo", self._md_insert_file_link)
        insert_menu.addAction("Imagen", self._md_insert_image)
        insert_menu.addAction("Configurar imagen", self._configure_image_display)
        insert_menu.addAction("Bloque de codigo", self._md_insert_codeblock)
        insert_menu.addAction("Cita", lambda: self._md_prefix("> "))
        insert_menu.addAction("Separador de slide", self._md_insert_slide_separator)
        self.md_menu_btn = self._compact_context_menu_button("Markdown", "Herramientas de edicion Markdown", markdown_menu)

        self.md_toolbar_direct_btn = QToolButton(self.time_toolbar)
        self.md_toolbar_direct_btn.setText("Formato MD")
        self.md_toolbar_direct_btn.setToolTip("Mostrar u ocultar la barra de formato Markdown (Ctrl+Shift+M)")
        self.md_toolbar_direct_btn.setCheckable(True)
        self.md_toolbar_direct_btn.setChecked(self.md_toolbar_visible)
        self.md_toolbar_direct_btn.clicked.connect(self._toggle_markdown_toolbar_visibility)
        self.time_toolbar_layout.addWidget(self.md_toolbar_direct_btn)

        self.presentation_toolbar_direct_btn = QToolButton(self.time_toolbar)
        self.presentation_toolbar_direct_btn.setText("Barra Presentar")
        self.presentation_toolbar_direct_btn.setToolTip("Mostrar u ocultar la barra de controles de presentacion")
        self.presentation_toolbar_direct_btn.setCheckable(True)
        self.presentation_toolbar_direct_btn.setChecked(self.presentation_toolbar_visible)
        self.presentation_toolbar_direct_btn.clicked.connect(self._toggle_presentation_toolbar_visibility)
        self.presentation_toolbar_direct_btn.hide()

        self.links_toolbar_direct_btn = QToolButton(self.time_toolbar)
        self.links_toolbar_direct_btn.setText("Barra Vínculos")
        self.links_toolbar_direct_btn.setToolTip("Mostrar u ocultar las herramientas de vínculos")
        self.links_toolbar_direct_btn.setCheckable(True)
        self.links_toolbar_direct_btn.setChecked(self.links_toolbar_visible)
        self.links_toolbar_direct_btn.clicked.connect(self._toggle_links_toolbar_visibility)
        self.time_toolbar_layout.addWidget(self.links_toolbar_direct_btn)

        self.image_toolbar_direct_btn = QToolButton(self.time_toolbar)
        self.image_toolbar_direct_btn.setText("Imagen")
        self.image_toolbar_direct_btn.setToolTip("Mostrar u ocultar las herramientas de imagen")
        self.image_toolbar_direct_btn.setCheckable(True)
        self.image_toolbar_direct_btn.setChecked(self.image_toolbar_visible)
        self.image_toolbar_direct_btn.clicked.connect(self._toggle_image_toolbar_visibility)
        self.time_toolbar_layout.addWidget(self.image_toolbar_direct_btn)

        self.shortcuts_toolbar_direct_btn = QToolButton(self.time_toolbar)
        self.shortcuts_toolbar_direct_btn.setText("Atajos")
        self.shortcuts_toolbar_direct_btn.setToolTip("Mostrar u ocultar la configuración de atajos")
        self.shortcuts_toolbar_direct_btn.setCheckable(True)
        self.shortcuts_toolbar_direct_btn.setChecked(not self.shortcut_settings_collapsed)
        self.shortcuts_toolbar_direct_btn.clicked.connect(self._toggle_shortcut_toolbar_visibility)
        self.time_toolbar_layout.addWidget(self.shortcuts_toolbar_direct_btn)

        self.teacher_mode_btn = QToolButton(self.time_toolbar)
        self.teacher_mode_btn.setText("Modo Docente")
        self.teacher_mode_btn.setToolTip("Activar herramientas avanzadas de guion de profesor y sincronización dual")
        self.teacher_mode_btn.setCheckable(True)
        self.teacher_mode_btn.setChecked(self.teacher_mode_enabled)
        self.teacher_mode_btn.clicked.connect(self.toggle_teacher_mode)
        self.time_toolbar_layout.addWidget(self.teacher_mode_btn)

        self.templates_quick_btn = QToolButton(self.time_toolbar)
        self.templates_quick_btn.setText("+ Plantilla")
        self.templates_quick_btn.setToolTip("Crear una nueva presentación desde una plantilla (Ctrl+Shift+N)")
        self.templates_quick_btn.clicked.connect(self.show_template_picker)
        self.time_toolbar_layout.addWidget(self.templates_quick_btn)

        self.quick_guide_btn = QToolButton(self.time_toolbar)
        self.quick_guide_btn.setText("? Guía")
        self.quick_guide_btn.setToolTip("Abrir guía rápida de Markdown y atajos (F1)")
        self.quick_guide_btn.clicked.connect(self.show_quick_guide)
        self.time_toolbar_layout.addWidget(self.quick_guide_btn)

        self._apply_teacher_mode_visibility()

    def show_template_picker(self):
        """Open the NUMA template picker and create a new tab with the chosen template."""
        dialog = TemplatePickerDialog(
            default_markdown=DEFAULT_MARKDOWN,
            is_dark=self.is_dark_mode,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_content is not None:
            self._sync_current_tab_from_editor()
            self._create_tab(None, dialog.selected_content, modified=False, switch=True)
            self.statusBar().showMessage("Nueva presentación creada desde plantilla", 2500)

    def show_quick_guide(self):
        """Open the quick Markdown & shortcuts guide with 1-click insertion."""
        dialog = QuickGuideDialog(
            on_insert=self._insert_guide_snippet,
            is_dark=self.is_dark_mode,
            parent=self,
        )
        dialog.exec()

    def _insert_guide_snippet(self, snippet):
        editor = self._active_markdown_editor()
        cursor = editor.textCursor()
        cursor.insertText(snippet)
        editor.setFocus()
        self.statusBar().showMessage("Bloque Markdown insertado en el editor", 2000)

    def toggle_teacher_mode(self, checked=None):
        """Progressive disclosure toggle for dual teacher/student workflows."""
        if isinstance(checked, bool):
            self.teacher_mode_enabled = checked
        else:
            self.teacher_mode_enabled = not self.teacher_mode_enabled
        if hasattr(self, "teacher_mode_btn"):
            self.teacher_mode_btn.blockSignals(True)
            self.teacher_mode_btn.setChecked(self.teacher_mode_enabled)
            self.teacher_mode_btn.blockSignals(False)
        self._apply_teacher_mode_visibility()
        if self.nav_mode == "slides":
            self.build_slide_outline()
        self.statusBar().showMessage(
            "Modo Docente activado (herramientas de profesor visibles)"
            if self.teacher_mode_enabled
            else "Modo estándar activado (interfaz simplificada)",
            2200,
        )

    def _apply_teacher_mode_visibility(self):
        enabled = bool(getattr(self, "teacher_mode_enabled", False))
        for attr in ("role_menu_btn", "sync_menu_btn", "links_toolbar_direct_btn"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setVisible(enabled)
        if not enabled and hasattr(self, "links_toolbar") and self.links_toolbar.isVisible():
            self.links_toolbar.hide()
        if hasattr(self, "time_toolbar"):
            self.time_toolbar.updateGeometry()

    def _create_links_toolbar(self):
        """Create the collapsible toolbar for teacher/student links."""
        container = FlowToolbar()
        container.setObjectName("linksToolbarContainer")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = FlowLayout(container, margin=0, spacing=5)
        layout.setContentsMargins(6, 2, 6, 2)
        container.setLayout(layout)

        sync_button = QPushButton("Vincular slide", container)
        sync_button.setObjectName("accentBtn")
        sync_button.setToolTip("Vincular el slide actual del alumno con el del profesor")
        sync_button.clicked.connect(self.teacher_sync_btn.click)
        layout.addWidget(sync_button)

        clear_button = QPushButton("Desvincular documento", container)
        clear_button.setObjectName("softMangoBtn")
        clear_button.clicked.connect(self.clear_sync_btn.click)
        layout.addWidget(clear_button)

        clear_slide_button = QPushButton("Desvincular slide", container)
        clear_slide_button.setObjectName("softMangoBtn")
        clear_slide_button.setToolTip("Eliminar solo el vinculo del slide actual")
        clear_slide_button.clicked.connect(self.clear_slide_sync_btn.click)
        layout.addWidget(clear_slide_button)

        label_button = QPushButton("Mostrar vinculo profesor", container)
        label_button.setObjectName("softBlueBtn")
        label_button.setCheckable(True)
        label_button.clicked.connect(self.student_sync_label_btn.click)
        layout.addWidget(label_button)
        self.links_toolbar_sync_button = sync_button
        self.links_toolbar_clear_button = clear_button
        self.links_toolbar_clear_slide_button = clear_slide_button
        self.links_toolbar_label_button = label_button
        return container

    def _create_image_toolbar(self):
        """Create the opt-in toolbar for the selected Markdown image."""
        container = FlowToolbar()
        container.setObjectName("imageToolbarContainer")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = FlowLayout(container, margin=0, spacing=4)
        layout.setContentsMargins(0, 0, 0, 4)
        container.setLayout(layout)

        configure = QPushButton("Configurar imagen", container)
        configure.setToolTip("Abrir la configuracion completa de la imagen")
        configure.clicked.connect(self._configure_image_display)
        layout.addWidget(configure)

        for label, value in (("Auto", "auto"), ("25%", "25%"), ("40%", "40%"),
                             ("60%", "60%"), ("80%", "80%"), ("100%", "100%")):
            button = QPushButton(label, container)
            button.setToolTip(f"Ancho de imagen: {label}")
            button.clicked.connect(lambda checked=False, item=value: self._update_image_display_option(width=item))
            layout.addWidget(button)

        for label, value in (("Izq", "left"), ("Centro", "center"), ("Der", "right")):
            button = QPushButton(label, container)
            button.setToolTip(f"Alinear imagen: {label}")
            button.clicked.connect(lambda checked=False, item=value: self._update_image_display_option(align=item))
            layout.addWidget(button)

        for label, value in (("0 grados", "0"), ("90 grados", "90"),
                             ("180 grados", "180"), ("270 grados", "270")):
            button = QPushButton(label, container)
            button.setToolTip(f"Orientacion: {label}")
            button.clicked.connect(lambda checked=False, item=value: self._update_image_display_option(orientation=item))
            layout.addWidget(button)

        color_button = QPushButton("Color", container)
        color_button.clicked.connect(lambda: self._update_image_display_option(color="color"))
        layout.addWidget(color_button)
        gray_button = QPushButton("Escala de grises", container)
        gray_button.clicked.connect(lambda: self._update_image_display_option(color="grayscale"))
        layout.addWidget(gray_button)
        for label, value in (("Sin marco", "none"), ("Marco", "plain"), ("Marco con sombra", "shadow")):
            button = QPushButton(label, container)
            button.setToolTip(f"Marco de imagen: {label.lower()}")
            button.clicked.connect(lambda checked=False, item=value: self._update_image_display_option(frame=item))
            layout.addWidget(button)
        return container

    def _create_md_toolbar(self):
        """Create a compact always-visible markdown formatting toolbar."""
        container = FlowToolbar()
        container.setObjectName("mdToolbarContainer")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        body_layout = FlowLayout(container, margin=0, spacing=4)
        body_layout.setContentsMargins(0, 0, 0, 4)
        container.setLayout(body_layout)

        def btn(text, tooltip, callback):
            b = QPushButton(text)
            b.setToolTip(tooltip)
            b.clicked.connect(callback)
            b.setFixedHeight(26)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._track_operational_control(b, f"markdown_{text}")
            return b

        def sep():
            s = QLabel("|")
            s.setObjectName("mdToolbarSep")
            s.setFixedHeight(26)
            return s

        def menu_btn(text, tooltip, items):
            b = QPushButton(text)
            b.setToolTip(tooltip)
            b.setFixedHeight(26)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            menu = QMenu(b)
            for item in items:
                if item is None:
                    menu.addSeparator()
                else:
                    label, cb = item
                    menu.addAction(label, cb)
            b.setMenu(menu)
            self._track_operational_control(b, f"markdown_{text}")
            return b

        def add_controls(widgets):
            for w in widgets:
                if isinstance(w, str) and w == "|":
                    body_layout.addWidget(sep())
                else:
                    body_layout.addWidget(w)

        add_controls([
            btn("↩", "Deshacer (Ctrl+Z)", lambda: self._active_markdown_editor().undo()),
            btn("↪", "Rehacer (Ctrl+Y)", lambda: self._active_markdown_editor().redo()),
            "|",
            btn("B", "Negrita (Ctrl+B)", lambda: self._md_wrap("**", "**")),
            btn("I", "Cursiva (Ctrl+I)", lambda: self._md_wrap("*", "*")),
            btn("S", "Tachado", lambda: self._md_wrap("~~", "~~")),
            menu_btn("Título", "Insertar encabezado (H1–H5)", [
                ("Título 1 (H1)", lambda: self._md_prefix("# ")),
                ("Título 2 (H2)", lambda: self._md_prefix("## ")),
                ("Título 3 (H3)", lambda: self._md_prefix("### ")),
                ("Título 4 (H4)", lambda: self._md_prefix("#### ")),
                ("Título 5 (H5)", lambda: self._md_prefix("##### ")),
            ]),
            menu_btn("Lista", "Insertar lista", [
                ("Viñetas (- )", lambda: self._md_prefix("- ")),
                ("Numerada (1. )", lambda: self._md_prefix("1. ")),
                ("Tareas (- [ ])", lambda: self._md_prefix("- [ ] ")),
            ]),
            menu_btn("Alineación", "Alinear texto o párrafo", [
                ("Izquierda", lambda: self._md_align("left")),
                ("Centrar", lambda: self._md_align("center")),
                ("Derecha", lambda: self._md_align("right")),
                ("Justificar", lambda: self._md_align("justify")),
                None,
                ("Justificar todo el documento", self._md_justify_document),
            ]),
            "|",
            menu_btn("Enlace", "Insertar enlace web, a diapositiva o archivo", [
                ("Enlace web", self._md_insert_link),
                ("Enlace a diapositiva", self._md_insert_slide_link),
                ("Enlace a archivo local", self._md_insert_file_link),
            ]),
            btn("Imagen", "Insertar imagen", self._md_insert_image),
            btn("Ajustar img", "Configurar tamaño y posición de la imagen actual", self._configure_image_display),
            menu_btn("Código", "Insertar código o cita", [
                ("Código en línea (`code`)", lambda: self._md_wrap("`", "`")),
                ("Bloque de código (```)", self._md_insert_codeblock),
                ("Bloque C# (```cs)", self._md_insert_csharp_codeblock),
                None,
                ("Cita (> )", lambda: self._md_prefix("> ")),
                ("Subrayado (++)", lambda: self._md_wrap("++", "++")),
                ("Superíndice (^)", lambda: self._md_wrap("^", "^")),
                ("Subíndice (~)", lambda: self._md_wrap("~", "~")),
                ("Línea horizontal", lambda: self._md_insert_text("\n---\n")),
            ]),
            "|",
            btn("+ Slide", "Insertar separador de nueva diapositiva (---)", self._md_insert_slide_separator),
        ])

        return container

    def _create_presentation_toolbar(self):
        """Optional direct presentation controls, mirroring the compact menu."""
        container = FlowToolbar(self, max_height=120)
        container.setObjectName("presentationToolbarContainer")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._update_presentation_toolbar_theme(container)
        layout = FlowLayout(container, margin=0, spacing=5)
        layout.setContentsMargins(6, 2, 6, 2)
        container.setLayout(layout)

        for text, tooltip, callback, object_name in (
            ("PRESENTAR", "Pantalla completa (F11)", self.toggle_fullscreen_presentation, "accentBtn"),
            ("Presentar Profesor", "Abrir o cerrar la presentacion del profesor", self.toggle_teacher_local_presentation, "softBlueBtn"),
            ("Presentar Dual", "Abrir control dual y salida para alumnado", self.toggle_dual_control_presentation, "softBlueBtn"),
        ):
            button = QPushButton(text, container)
            button.setToolTip(tooltip)
            button.setObjectName(object_name)
            button.clicked.connect(callback)
            layout.addWidget(button)
        return container

    def show_find_replace_dialog(self, show_replace=False):
        """Open a reusable find/replace dialog for the active Markdown editor."""
        if not hasattr(self, "_find_replace_dialog"):
            dialog = QDialog(self)
            dialog.setWindowTitle("Buscar y reemplazar")
            dialog.setModal(False)
            layout = QGridLayout(dialog)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setHorizontalSpacing(8)
            layout.setVerticalSpacing(8)

            find_input = QLineEdit(dialog)
            find_input.setPlaceholderText("Texto a buscar")
            replace_input = QLineEdit(dialog)
            replace_input.setPlaceholderText("Reemplazar con")
            case_check = QCheckBox("Distinguir mayusculas", dialog)
            status = QLabel("", dialog)
            status.setWordWrap(True)

            previous_btn = QPushButton("Anterior", dialog)
            next_btn = QPushButton("Siguiente", dialog)
            replace_btn = QPushButton("Reemplazar", dialog)
            replace_all_btn = QPushButton("Reemplazar todo", dialog)
            close_btn = QPushButton("Cerrar", dialog)

            layout.addWidget(QLabel("Buscar:"), 0, 0)
            layout.addWidget(find_input, 0, 1, 1, 4)
            layout.addWidget(QLabel("Reemplazar:"), 1, 0)
            layout.addWidget(replace_input, 1, 1, 1, 4)
            layout.addWidget(case_check, 2, 1, 1, 3)
            layout.addWidget(previous_btn, 3, 0)
            layout.addWidget(next_btn, 3, 1)
            layout.addWidget(replace_btn, 3, 2)
            layout.addWidget(replace_all_btn, 3, 3)
            layout.addWidget(close_btn, 3, 4)
            layout.addWidget(status, 4, 0, 1, 5)

            previous_btn.clicked.connect(lambda: self._find_editor_text(backward=True))
            next_btn.clicked.connect(self._find_editor_text)
            replace_btn.clicked.connect(self._replace_editor_text)
            replace_all_btn.clicked.connect(self._replace_all_editor_text)
            close_btn.clicked.connect(dialog.close)
            find_input.returnPressed.connect(self._find_editor_text)

            self._find_replace_dialog = dialog
            self._find_replace_widgets = {
                "find": find_input,
                "replace": replace_input,
                "case": case_check,
                "replace_label": layout.itemAtPosition(1, 0).widget(),
                "replace_btn": replace_btn,
                "replace_all_btn": replace_all_btn,
                "status": status,
            }

        widgets = self._find_replace_widgets
        for key in ("replace", "replace_label", "replace_btn", "replace_all_btn"):
            widgets[key].setVisible(show_replace)
        self._find_replace_dialog.setWindowTitle(
            "Buscar y reemplazar" if show_replace else "Buscar texto"
        )
        self._find_replace_dialog.show()
        self._find_replace_dialog.raise_()
        self._find_replace_dialog.activateWindow()
        widgets["find"].setFocus()
        widgets["find"].selectAll()

    def _find_editor_text(self, backward=False):
        widgets = getattr(self, "_find_replace_widgets", None)
        if not widgets:
            return False
        needle = widgets["find"].text()
        if not needle:
            widgets["status"].setText("Escribe el texto que deseas buscar.")
            return False
        editor = self._active_markdown_editor()
        flags = QTextDocument.FindFlag.FindCaseSensitively if widgets["case"].isChecked() else QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        found = editor.find(needle, flags)
        if not found:
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
            editor.setTextCursor(cursor)
            found = editor.find(needle, flags)
        widgets["status"].setText(
            "Coincidencia encontrada." if found else "No se encontraron coincidencias."
        )
        if found:
            editor.setFocus()
        return found

    def _replace_editor_text(self):
        widgets = getattr(self, "_find_replace_widgets", None)
        if not widgets:
            return
        editor = self._active_markdown_editor()
        cursor = editor.textCursor()
        if not cursor.hasSelection() and not self._find_editor_text():
            return
        cursor = editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(widgets["replace"].text())
            widgets["status"].setText("Coincidencia reemplazada.")
        self._find_editor_text()

    def _replace_all_editor_text(self):
        widgets = getattr(self, "_find_replace_widgets", None)
        if not widgets:
            return
        needle = widgets["find"].text()
        if not needle:
            widgets["status"].setText("Escribe el texto que deseas buscar.")
            return
        editor = self._active_markdown_editor()
        flags = QTextDocument.FindFlag.FindCaseSensitively if widgets["case"].isChecked() else QTextDocument.FindFlag(0)
        cursor = QTextCursor(editor.document())
        cursor.beginEditBlock()
        replacements = 0
        while True:
            match = editor.document().find(needle, cursor, flags)
            if match.isNull():
                break
            match.insertText(widgets["replace"].text())
            cursor = match
            replacements += 1
        cursor.endEditBlock()
        widgets["status"].setText(f"Se reemplazaron {replacements} coincidencias.")
        if replacements:
            editor.setFocus()
            self._log_operation("reemplazar_texto", count=replacements)

    def _toggle_links_toolbar_visibility(self, checked=None):
        self.links_toolbar_visible = (
            bool(checked) if checked is not None else not self.links_toolbar_visible
        )
        self.links_toolbar.setVisible(
            self.links_toolbar_visible and not self.is_fullscreen_presentation
        )
        if hasattr(self, "view_links_toolbar_action"):
            self.view_links_toolbar_action.blockSignals(True)
            self.view_links_toolbar_action.setChecked(self.links_toolbar_visible)
            self.view_links_toolbar_action.blockSignals(False)
        if hasattr(self, "links_toolbar_direct_btn"):
            self.links_toolbar_direct_btn.blockSignals(True)
            self.links_toolbar_direct_btn.setChecked(self.links_toolbar_visible)
            self.links_toolbar_direct_btn.blockSignals(False)
        self._log_operation("alternar_barra_vinculos", visible=self.links_toolbar_visible)

    def _toggle_image_toolbar_visibility(self, checked=None):
        self.image_toolbar_visible = (
            bool(checked) if checked is not None else not self.image_toolbar_visible
        )
        self.image_toolbar.setVisible(
            self.image_toolbar_visible and not self.is_fullscreen_presentation
        )
        if hasattr(self, "view_image_toolbar_action"):
            self.view_image_toolbar_action.blockSignals(True)
            self.view_image_toolbar_action.setChecked(self.image_toolbar_visible)
            self.view_image_toolbar_action.blockSignals(False)
        if hasattr(self, "image_toolbar_direct_btn"):
            self.image_toolbar_direct_btn.blockSignals(True)
            self.image_toolbar_direct_btn.setChecked(self.image_toolbar_visible)
            self.image_toolbar_direct_btn.blockSignals(False)
        self._log_operation("alternar_barra_edicion_imagen", visible=self.image_toolbar_visible)

    def _update_image_display_option(self, **updates):
        """Update one display property on the image at the editor cursor."""
        editor = self._active_markdown_editor()
        source = editor.toPlainText()
        cursor = editor.textCursor()
        positions = [cursor.position()]
        if cursor.hasSelection():
            positions.extend((cursor.selectionStart(), cursor.selectionEnd()))
        image = next(
            (find_markdown_image_at_position(source, position) for position in positions
             if find_markdown_image_at_position(source, position)),
            None,
        )
        if not image:
            self.statusBar().showMessage("Coloca el cursor sobre una imagen Markdown.", 3000)
            editor.setFocus()
            return
        options, directive_range = get_image_display_options(source, image["start"])
        options.update(updates)
        directive = (
            "<!-- numa-image: "
            f"width={options['width']}, align={options['align']}, "
            f"spacing={options['spacing']}, orientation={options['orientation']}, "
            f"color={options['color']}, frame={options['frame']} -->"
        )
        start, end = directive_range or (image["start"], image["start"])
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(f"{directive}\n")
        cursor.endEditBlock()
        editor.setTextCursor(cursor)
        editor.setFocus()
        self._last_active_markdown_editor = editor
        self._log_operation("editar_imagen", **updates)
        self.statusBar().showMessage("Configuracion de imagen aplicada.", 1800)

    def _toggle_markdown_toolbar_visibility(self, checked=None):
        self.md_toolbar_visible = bool(checked) if checked is not None else not self.md_toolbar_visible
        self.md_toolbar.setVisible(self.md_toolbar_visible and not self.is_fullscreen_presentation)
        if hasattr(self, "view_markdown_toolbar_action"):
            self.view_markdown_toolbar_action.blockSignals(True)
            self.view_markdown_toolbar_action.setChecked(self.md_toolbar_visible)
            self.view_markdown_toolbar_action.blockSignals(False)
        if hasattr(self, "md_toolbar_direct_btn"):
            self.md_toolbar_direct_btn.blockSignals(True)
            self.md_toolbar_direct_btn.setChecked(self.md_toolbar_visible)
            self.md_toolbar_direct_btn.blockSignals(False)
        self._log_operation("alternar_barra_edicion_markdown", visible=self.md_toolbar_visible)

    def _toggle_presentation_toolbar_visibility(self, checked=None):
        self.presentation_toolbar_visible = (
            bool(checked) if checked is not None else not self.presentation_toolbar_visible
        )
        self.presentation_toolbar.setVisible(
            self.presentation_toolbar_visible and not self.is_fullscreen_presentation
        )
        if getattr(self, "presentation_toolbar_action", None):
            self.presentation_toolbar_action.setVisible(
                self.presentation_toolbar_visible and not self.is_fullscreen_presentation
            )
        if hasattr(self, "view_presentation_toolbar_action"):
            self.view_presentation_toolbar_action.blockSignals(True)
            self.view_presentation_toolbar_action.setChecked(self.presentation_toolbar_visible)
            self.view_presentation_toolbar_action.blockSignals(False)
        if hasattr(self, "presentation_toolbar_direct_btn"):
            self.presentation_toolbar_direct_btn.blockSignals(True)
            self.presentation_toolbar_direct_btn.setChecked(self.presentation_toolbar_visible)
            self.presentation_toolbar_direct_btn.blockSignals(False)
        self._log_operation("alternar_barra_presentacion", visible=self.presentation_toolbar_visible)

    def toggle_md_toolbar(self):
        """Open the compact Markdown menu without adding another toolbar row."""
        if hasattr(self, "md_menu_btn"):
            self.md_menu_btn.showMenu()
            self._log_operation("abrir_menu_edicion_markdown")
            return
        self.md_toolbar_visible = not self.md_toolbar.isVisible()
        self.md_toolbar.setVisible(self.md_toolbar_visible)

    def toggle_navigation_panel(self):
        """Collapse or expand the left navigation panel, always keeping a visible rail."""
        if not self.nav_panel_collapsed:
            sizes = self.splitter.sizes()
            if sizes and sizes[0] >= 120:
                self._saved_nav_width = sizes[0]

        self.nav_panel_collapsed = not self.nav_panel_collapsed
        self.nav_body.setVisible(not self.nav_panel_collapsed)
        is_files = self.nav_mode == "files"

        if self.nav_panel_collapsed:
            self.nav_toggle_btn.setText("▸")
            self.nav_toggle_btn.setProperty("collapsed", True)
            self.nav_toggle_btn.setToolTip("Desplegar panel de diapositivas y archivos")
            self.nav_toggle_btn.setFixedHeight(44)
            self.nav_container.setMinimumWidth(36)
            self.nav_container.setMaximumWidth(36)
            sizes = self.splitter.sizes()
            if len(sizes) >= 3:
                extra = max(0, sizes[0] - 36)
                self.splitter.setSizes([36, sizes[1] + extra, sizes[2]])
        else:
            self.nav_toggle_btn.setText("◂ Plegar panel")
            self.nav_toggle_btn.setProperty("collapsed", False)
            self.nav_toggle_btn.setToolTip("Plegar el panel lateral")
            self.nav_toggle_btn.setFixedHeight(28)
            self.nav_container.setMaximumWidth(16777215)
            self.nav_container.setMinimumWidth(180)
            target_w = max(180, getattr(self, "_saved_nav_width", 220))
            sizes = self.splitter.sizes()
            if len(sizes) >= 3:
                delta = max(0, target_w - sizes[0])
                self.splitter.setSizes([target_w, max(240, sizes[1] - delta), sizes[2]])
        self.nav_toggle_btn.style().unpolish(self.nav_toggle_btn)
        self.nav_toggle_btn.style().polish(self.nav_toggle_btn)

        if hasattr(self, "slides_panel_btn"):
            self.slides_panel_btn.blockSignals(True)
            self.slides_panel_btn.setChecked(not self.nav_panel_collapsed)
            self.slides_panel_btn.blockSignals(False)

        state = "colapsado (pulsa ▸ o «Slides» para desplegar)" if self.nav_panel_collapsed else "visible"
        self.statusBar().showMessage(f"Panel lateral {state}", 2000)

    def change_navigation_mode(self):
        """Switch the left panel between files and slide outline."""
        self.nav_mode = self.nav_mode_combo.currentData() or "slides"
        is_files = self.nav_mode == "files"
        for i in range(self.nav_file_controls.count()):
            widget = self.nav_file_controls.itemAt(i).widget()
            if widget:
                widget.setVisible(is_files)
        if hasattr(self, "nav_new_slide_btn"):
            self.nav_new_slide_btn.setVisible(not is_files)
        self.nav_toggle_btn.setText("▸" if self.nav_panel_collapsed else "◂ Plegar panel")
        if is_files:
            self.show_computer_root()
        else:
            self.build_slide_outline()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "paper_toolbar", None) and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._fit_paper_settings_block)
        control_label = obj.property("numa_log_control") if obj is not None else None
        if (
            control_label
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._log_operation("clic", control=control_label)

        if obj in (getattr(self, "editor", None), getattr(self, "teacher_editor", None)):
            if self._loading_tab:
                return super().eventFilter(obj, event)
            if event.type() in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress):
                self._last_active_markdown_editor = obj
                is_teacher_editor = obj is getattr(self, "teacher_editor", None)
                # In simple mode the shared editor can display the teacher script.
                role = "teacher" if is_teacher_editor or (
                    obj is getattr(self, "editor", None)
                    and self.editor_role == "teacher"
                    and not self.split_editor_enabled
                ) else "student"
                if event.type() == QEvent.Type.FocusIn:
                    self._log_operation("foco_editor", editor=role)
                if role != self.editor_role:
                    self.editor_role = role
                    self._sync_current_tab_from_editor()
                    if self.nav_mode == "slides":
                        self.build_slide_outline()
                elif self.nav_mode == "slides":
                    slide_index = obj.current_slide_index() if hasattr(obj, "current_slide_index") else 0
                    if getattr(self, "_outline_current_role", None) != role:
                        self.build_slide_outline()
                    else:
                        self._highlight_outline_slide(slide_index)
        return super().eventFilter(obj, event)

    @staticmethod
    def _markdown_paths_from_mime_data(mime_data):
        """Return local Markdown paths from an external drag operation."""
        if not mime_data or not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            path = url.toLocalFile()
            if path and path.lower().endswith((".md", ".markdown")):
                paths.append(path)
        return paths

    def dragEnterEvent(self, event):
        if self._markdown_paths_from_mime_data(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._markdown_paths_from_mime_data(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = self._markdown_paths_from_mime_data(event.mimeData())
        if paths:
            event.acceptProposedAction()
            for path in paths:
                self._open_dropped_markdown_file(path)
            return
        super().dropEvent(event)

    def _consume_pending_open_files(self):
        """Open Markdown files requested by a secondary launch (e.g. Explorer double-click)."""
        queue_path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NUMA Deck Presentations" / "pending_open_files.json"
        if not queue_path.is_file():
            return
        try:
            raw = queue_path.read_text(encoding="utf-8")
            queue_path.unlink(missing_ok=True)
            paths = json.loads(raw)
        except Exception:
            LOGGER.exception("No se pudo procesar la cola de archivos externos")
            return
        if not isinstance(paths, list):
            return
        opened_any = False
        for path in paths:
            if isinstance(path, str) and os.path.isfile(path):
                self._open_file(path)
                opened_any = True
        if opened_any:
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            self.activateWindow()

    def _open_dropped_markdown_file(self, file_path):
        """Open a Markdown file received through any drag-and-drop surface."""
        if not file_path or not os.path.isfile(file_path):
            self.statusBar().showMessage("El archivo Markdown soltado no existe.", 3000)
            return
        if not file_path.lower().endswith((".md", ".markdown")):
            return
        self._log_operation("archivo_soltado", path=os.path.abspath(file_path))
        self._open_file(file_path)

    def _slide_count(self):
        text = self._presentation_markdown_text()
        if not text.strip():
            return 1
        return max(1, sum(1 for line in text.splitlines() if line.strip() == "---") + 1)

    def _outline_editor_role(self):
        active_editor = self._active_markdown_editor()
        if self.split_editor_enabled and active_editor is self.teacher_editor:
            return "teacher"
        if self.editor_role == "teacher" and not self.split_editor_enabled:
            return "teacher"
        return "student"

    def _outline_source(self):
        role = self._outline_editor_role()
        if role == "teacher":
            editor = self.teacher_editor if self.split_editor_enabled else self.editor
            text = self.teacher_editor.toPlainText() if self.split_editor_enabled else self.teacher_script_content
            return role, editor, text
        return "student", self.editor, self._student_markdown_text()

    def _outline_title(self, text, fallback):
        clean = text.strip().lstrip("#").strip()
        clean = clean.replace("**", "").replace("__", "").replace("`", "")
        return clean or fallback

    def _make_slide_outline_item(self, title, slide_index, line_index, level=1):
        item = QTreeWidgetItem([title])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "type": "slide",
            "slide_index": slide_index,
            "line_index": line_index,
            "level": level,
        })
        return item

    def build_slide_outline(self):
        """Build an outline tree from slides and headings in the open document."""
        self.file_tree.clear()
        role, editor, text = self._outline_source()
        self._outline_current_role = role
        if getattr(self, "teacher_mode_enabled", False):
            label = "Diapositivas del profesor" if role == "teacher" else "Diapositivas del alumno"
        else:
            label = "Índice de diapositivas"
        self.nav_path_label.setText(label)
        lines = text.splitlines()

        slide_index = 0
        current_slide_item = None
        heading_stack = {}
        slide_has_heading = False

        def ensure_slide_item(line_index):
            nonlocal current_slide_item, slide_has_heading
            if current_slide_item is None:
                current_slide_item = self._make_slide_outline_item(
                    f"{slide_index + 1}. Sin título",
                    slide_index,
                    line_index,
                    1,
                )
                self.file_tree.addTopLevelItem(current_slide_item)
                slide_has_heading = False
            return current_slide_item

        for line_index, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "---":
                slide_index += 1
                current_slide_item = None
                heading_stack = {}
                slide_has_heading = False
                continue

            match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if not match:
                continue

            level = len(match.group(1))
            title = self._outline_title(match.group(2), f"Slide {slide_index + 1}")
            label = f"{slide_index + 1} {title}" if not slide_has_heading else title
            item = self._make_slide_outline_item(label, slide_index, line_index, level)

            if not slide_has_heading:
                current_slide_item = item
                self.file_tree.addTopLevelItem(item)
                slide_has_heading = True
            else:
                parent = None
                for parent_level in range(level - 1, 0, -1):
                    parent = heading_stack.get(parent_level)
                    if parent:
                        break
                (parent or ensure_slide_item(line_index)).addChild(item)

            heading_stack[level] = item
            for deeper in list(heading_stack):
                if deeper > level:
                    heading_stack.pop(deeper, None)

        if self.file_tree.topLevelItemCount() == 0:
            self.file_tree.addTopLevelItem(self._make_slide_outline_item("1 Sin titulo", 0, 0, 1))

        self.file_tree.expandAll()
        self._highlight_outline_slide(editor.current_slide_index())

    def _highlight_outline_slide(self, slide_index):
        if self.nav_mode != "slides":
            return

        target = None

        def visit(item):
            nonlocal target
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and data.get("type") == "slide" and int(data.get("slide_index", -1)) == int(slide_index):
                current = target.data(0, Qt.ItemDataRole.UserRole) if target else None
                if target is None or int(data.get("level", 99)) < int(current.get("level", 99)):
                    target = item
            for i in range(item.childCount()):
                visit(item.child(i))

        for i in range(self.file_tree.topLevelItemCount()):
            visit(self.file_tree.topLevelItem(i))

        if target:
            self.file_tree.blockSignals(True)
            self.file_tree.setCurrentItem(target)
            self.file_tree.scrollToItem(target)
            self.file_tree.blockSignals(False)

    def _goto_outline_item(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(data, dict) or data.get("type") != "slide":
            return

        line_index = max(0, int(data.get("line_index", 0)))
        slide_index = max(0, int(data.get("slide_index", 0)))
        role, editor, _ = self._outline_source()
        block = editor.document().findBlockByNumber(line_index)
        if block.isValid():
            cursor = QTextCursor(block)
            editor.setTextCursor(cursor)
            editor.centerCursor()
            self._last_active_markdown_editor = editor
            editor.setFocus()
            self.editor_role = role
        if role == "teacher":
            self.teacher_preview.goto_slide(slide_index)
        else:
            self.preview.goto_slide(slide_index)
            self._remember_current_file_preferences(slide_index=slide_index)
            self._update_preview_slide_label(slide_index)
        self._highlight_outline_slide(slide_index)

    def _make_tree_item(self, label, path, is_dir):
        """Create one navigation item with its filesystem path attached."""
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, is_dir)
        if is_dir:
            item.addChild(QTreeWidgetItem(["Cargando..."]))
        return item

    def _has_visible_children(self, path):
        """Return True when a folder likely contains entries worth expanding."""
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    if entry.is_dir(follow_symlinks=False) or entry.name.lower().endswith((".md", ".markdown")):
                        return True
        except OSError:
            return False
        return False

    def _populate_tree_item(self, item):
        """Load a folder's child directories and Markdown files."""
        path = item.data(0, Qt.ItemDataRole.UserRole)
        is_dir = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not is_dir or not path:
            return

        if item.childCount() != 1 or item.child(0).data(0, Qt.ItemDataRole.UserRole) is not None:
            return

        item.takeChildren()
        try:
            folders = []
            markdown_files = []
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        if entry.name.startswith("."):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            folders.append(entry)
                        elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith((".md", ".markdown")):
                            markdown_files.append(entry)
                    except OSError:
                        continue

            for entry in sorted(folders, key=lambda e: e.name.lower()):
                child = self._make_tree_item(entry.name, entry.path, True)
                if not self._has_visible_children(entry.path):
                    child.takeChildren()
                item.addChild(child)

            for entry in sorted(markdown_files, key=lambda e: e.name.lower()):
                item.addChild(self._make_tree_item(entry.name, entry.path, False))

            if item.childCount() == 0:
                item.addChild(QTreeWidgetItem(["(Carpeta vacia)"]))
        except OSError as e:
            item.addChild(QTreeWidgetItem([f"(No accesible: {e.strerror})"]))

    def _select_tree_item(self, item, column=0):
        """Show the selected path without changing folder state."""
        if self.nav_mode == "slides":
            self._goto_outline_item(item)
            return
        path = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self.nav_path_label.setText(path or "Equipo")

    def show_computer_root(self):
        """Show available filesystem drives."""
        self.nav_root_path = ""
        self.file_tree.clear()
        for drive in QDir.drives():
            path = drive.absoluteFilePath()
            label = f"{path.rstrip('/')}\\"
            self.file_tree.addTopLevelItem(self._make_tree_item(label, path, True))
        self.nav_path_label.setText("Equipo")
        self.statusBar().showMessage("Navegador: Equipo", 1500)

    def set_navigation_root(self, path):
        """Move the navigation tree to a specific folder or drive."""
        normalized = os.path.abspath(path)
        if not os.path.exists(normalized):
            QMessageBox.warning(self, "Ruta no encontrada", f"No existe:\n{normalized}")
            return

        self.nav_root_path = normalized
        self.file_tree.clear()
        root = self._make_tree_item(os.path.basename(os.path.normpath(normalized)) or normalized, normalized, True)
        self.file_tree.addTopLevelItem(root)
        self._populate_tree_item(root)
        root.setExpanded(True)
        self.nav_path_label.setText(normalized)
        self.statusBar().showMessage(f"Navegador: {normalized}", 1500)

    def navigate_up(self):
        """Move navigation one directory above the current root."""
        if not self.nav_root_path:
            return

        parent = os.path.dirname(os.path.normpath(self.nav_root_path))
        if parent and parent != os.path.normpath(self.nav_root_path):
            self.set_navigation_root(parent)
        else:
            self.show_computer_root()

    def _activate_tree_item(self, item, column=0):
        """Expand folders or open Markdown files from the navigation tree."""
        if self.nav_mode == "slides":
            self._goto_outline_item(item)
            return
        if not item:
            return

        file_path = item.data(0, Qt.ItemDataRole.UserRole)
        is_dir = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not file_path:
            return

        if is_dir:
            self.nav_path_label.setText(file_path)
            if item.isExpanded():
                item.setExpanded(False)
            else:
                self._populate_tree_item(item)
                item.setExpanded(True)
            return

        if not file_path.lower().endswith((".md", ".markdown")):
            self.statusBar().showMessage("Selecciona un archivo Markdown (.md)", 2000)
            return

        self._open_file(file_path)

    def _update_presentation_toolbar_theme(self, container=None):
        """Update presentation toolbar colors based on current theme."""
        target = container or getattr(self, "presentation_toolbar", None)
        if not target:
            return
        if getattr(self, "is_dark_mode", False):
            target.setStyleSheet("""
                QWidget#presentationToolbarContainer {
                    background: #242017;
                    border: 1px solid #7C5010;
                    border-radius: 6px;
                }
            """)
        else:
            target.setStyleSheet("""
                QWidget#presentationToolbarContainer {
                    background: #FFF8E8;
                    border: 1px solid #F2B44B;
                    border-radius: 6px;
                }
            """)

    def _update_md_toolbar_theme(self):
        """Update MD toolbar colors based on current theme."""
        if not hasattr(self, 'md_toolbar'):
            return
        if self.is_dark_mode:
            bg = "#141B2F"
            border = "#2A3555"
            sep_color = "#334155"
            text = "#EEF2FF"
            btn_bg = "#1A2340"
            hover_bg = "#2563FF"
        else:
            bg = "#F1F5F9"
            border = "#CBD5E1"
            sep_color = "#CBD5E1"
            text = "#111827"
            btn_bg = "#FFFFFF"
            hover_bg = "#2563FF"

        self.md_toolbar.setStyleSheet(f"""
            QWidget#mdToolbarContainer {{
                border: 1px solid {border};
                border-radius: 10px;
                padding: 4px 6px;
                background: {bg};
            }}
            QPushButton {{
                border: 1.5px solid {border};
                border-radius: 6px;
                padding: 3px 8px;
                font-size: 11px;
                font-weight: 600;
                min-width: 22px;
                background: {btn_bg};
                color: {text};
            }}
            QPushButton:hover {{
                background: {hover_bg};
                color: #FFFFFF;
                border-color: {hover_bg};
            }}
            QPushButton:pressed {{
                background: #0A84FF;
                color: #FFFFFF;
            }}
            QLabel#mdToolbarSep {{
                color: {sep_color};
                font-size: 14px;
                padding: 0 2px;
                background: transparent;
            }}
        """)

    def _update_navigation_theme(self):
        """Update directory navigation colors based on current theme."""
        if not hasattr(self, 'nav_container'):
            return

        if self.is_dark_mode:
            bg = "#141B2F"
            surface = "#1A2340"
            border = "#2A3555"
            text = "#EEF2FF"
            muted = "#9CA3AF"
            selected = "#2563FF"
        else:
            bg = "#F8FAFC"
            surface = "#FFFFFF"
            border = "#CBD5E1"
            text = "#111827"
            muted = "#4B5563"
            selected = "#2563FF"

        self.nav_container.setStyleSheet(f"""
            QFrame#navContainer {{
                border: 1.5px solid {border};
                border-radius: 14px;
                background: {bg};
            }}
            QPushButton#navToggle {{
                border: 1.5px solid {border};
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 700;
                text-align: left;
                background: {surface};
                color: {text};
            }}
            QPushButton#navToggle[collapsed="true"] {{
                text-align: center;
                padding: 0px;
                font-size: 16px;
                border-color: {selected};
                color: {selected};
            }}
            QPushButton#navToggle:hover {{
                background: {selected};
                color: #FFFFFF;
                border-color: {selected};
            }}
            QPushButton#navSmallBtn {{
                border: 1.5px solid {border};
                border-radius: 8px;
                padding: 3px 6px;
                font-size: 10px;
                font-weight: 700;
                background: {surface};
                color: {text};
            }}
            QPushButton#navSmallBtn:hover {{
                background: {selected};
                color: #FFFFFF;
                border-color: {selected};
            }}
            QComboBox#navModeCombo {{
                border: 1.5px solid {border};
                border-radius: 8px;
                padding: 4px 26px 4px 8px;
                font-size: 11px;
                font-weight: 700;
                background: {surface};
                color: {text};
                selection-background-color: {selected};
                selection-color: #FFFFFF;
            }}
            QComboBox#navModeCombo QAbstractItemView {{
                border: 1.5px solid {border};
                border-radius: 8px;
                background: {surface};
                color: {text};
                selection-background-color: {selected};
                selection-color: #FFFFFF;
                outline: none;
                padding: 4px;
            }}
            QComboBox#navModeCombo QAbstractItemView::item {{
                min-height: 22px;
                padding: 5px 8px;
                background: {surface};
                color: {text};
            }}
            QComboBox#navModeCombo QAbstractItemView::item:hover,
            QComboBox#navModeCombo QAbstractItemView::item:selected {{
                background: {selected};
                color: #FFFFFF;
            }}
            QLabel#navPathLabel {{
                color: {muted};
                font-size: 10px;
                padding: 2px 4px;
                background: transparent;
            }}
            QTreeView#fileTree {{
                border: 1px solid {border};
                border-radius: 10px;
                background: {surface};
                color: {text};
                padding: 4px;
                font-size: 12px;
                outline: none;
            }}
            QTreeView#fileTree::item {{
                min-height: 24px;
                padding: 2px 4px;
                border-radius: 6px;
            }}
            QTreeView#fileTree::item:selected {{
                background: {selected};
                color: #FFFFFF;
            }}
            QTreeView#fileTree::item:hover {{
                background: rgba(37, 99, 255, 0.18);
            }}
        """)

    def _update_tab_theme(self):
        """Update document tab colors based on current theme."""
        if not hasattr(self, 'tab_bar'):
            return

        if self.is_dark_mode:
            bg = "#0E1324"
            surface = "#141B2F"
            border = "#2A3555"
            text = "#EEF2FF"
        else:
            bg = "#F7FAFF"
            surface = "#FFFFFF"
            border = "#CBD5E1"
            text = "#111827"

        self.tab_bar.setStyleSheet(f"""
            QTabBar {{
                background: {bg};
            }}
            QTabBar::tab {{
                background: {surface};
                color: {text};
                border: 1.5px solid {border};
                border-bottom: 1.5px solid {border};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 6px 24px 6px 10px;
                margin-right: 4px;
                font-size: 11px;
                font-weight: 700;
            }}
            QTabBar::tab:selected {{
                background: #2563FF;
                color: #FFFFFF;
                border-color: #2563FF;
            }}
        """)

    def _md_wrap(self, before, after):
        """Wrap selected text or insert markers."""
        editor = self._active_markdown_editor()
        cursor = editor.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            cursor.insertText(f"{before}{text}{after}")
        else:
            cursor.insertText(f"{before}{after}")
            # Move cursor between markers
            cursor.movePosition(cursor.MoveOperation.Left, cursor.MoveMode.MoveAnchor, len(after))
            editor.setTextCursor(cursor)
        editor.setFocus()

    def _md_prefix(self, prefix):
        """Insert prefix at beginning of line."""
        editor = self._active_markdown_editor()
        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.StartOfBlock, cursor.MoveMode.MoveAnchor)
        cursor.insertText(prefix)
        editor.setFocus()

    def _md_align(self, alignment):
        """Apply a persistent text alignment to the selected Markdown blocks."""
        if alignment not in {"left", "center", "right", "justify"}:
            return

        editor = self._active_markdown_editor()
        cursor = editor.textCursor()
        source = editor.toPlainText()
        selection_start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        selection_end = cursor.selectionEnd() if cursor.hasSelection() else cursor.position()
        alignment_block = re.compile(
            r'<div class="numa-align-(?:left|center|right|justify)">\s*(.*?)\s*</div>',
            re.DOTALL,
        )

        # When the caret is already inside an aligned block, replace that
        # wrapper instead of nesting a second div around a fragment of it.
        for match in alignment_block.finditer(source):
            if match.start() <= selection_start and selection_end <= match.end():
                cursor.setPosition(match.start())
                cursor.setPosition(match.end(), QTextCursor.MoveMode.KeepAnchor)
                content = match.group(1).strip()
                cursor.beginEditBlock()
                cursor.insertText(f'<div class="numa-align-{alignment}">\n\n{content}\n\n</div>')
                cursor.endEditBlock()
                editor.setTextCursor(cursor)
                editor.setFocus()
                return

        if cursor.hasSelection():
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            cursor.setPosition(start)
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        else:
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)

        content = cursor.selectedText().replace("\u2029", "\n").strip()
        if not content or re.fullmatch(r"</?div(?:\s+[^>]*)?>", content, re.IGNORECASE):
            self.statusBar().showMessage(
                "Coloca el cursor en un parrafo o selecciona el texto que deseas alinear.",
                3000,
            )
            editor.setFocus()
            return

        cursor.beginEditBlock()
        cursor.insertText(f'<div class="numa-align-{alignment}">\n\n{content}\n\n</div>')
        cursor.endEditBlock()
        editor.setTextCursor(cursor)
        editor.setFocus()

    def _md_justify_document(self):
        """Persist a document-wide justification directive for all preview modes."""
        editor = self._active_markdown_editor()
        source = editor.toPlainText()
        directive = "<!-- numa-document-align: justify -->"
        updated = DOCUMENT_ALIGNMENT_PATTERN.sub(directive, source, count=1)
        if updated == source:
            updated = f"{directive}\n\n{source.lstrip()}"

        cursor = editor.textCursor()
        old_position = cursor.position()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(updated)
        cursor.endEditBlock()
        cursor.setPosition(min(len(updated), old_position + (len(updated) - len(source))))
        editor.setTextCursor(cursor)
        editor.setFocus()
        self.statusBar().showMessage("Documento justificado en todas las vistas.", 2500)

    def _md_insert_text(self, text):
        """Insert raw text at cursor."""
        editor = self._active_markdown_editor()
        editor.textCursor().insertText(text)
        editor.setFocus()

    def _md_insert_slide_separator(self):
        """Insert a slide separator followed by a stable invisible slide ID."""
        marker = create_slide_id_marker()
        self._md_insert_text(f"\n\n---\n{marker}\n\n")

    def _md_insert_link(self):
        """Insert markdown link placeholder."""
        editor = self._active_markdown_editor()
        cursor = editor.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            cursor.insertText(f"[{text}](url)")
        else:
            cursor.insertText("[texto del enlace](url)")
        editor.setFocus()

    def _md_insert_slide_link(self):
        """Insert a Markdown link to another slide using a stable slide key."""
        editor = self._active_markdown_editor()
        self._ensure_slide_ids_in_editor(editor=editor, mark_modified=False)
        cursor = editor.textCursor()
        selected_text = cursor.selectedText().strip()

        if selected_text:
            link_text = selected_text
        else:
            link_text, ok = QInputDialog.getText(
                self,
                "Texto del enlace",
                "Texto visible en la presentación:"
            )
            if not ok or not link_text.strip():
                editor.setFocus()
                return
            link_text = link_text.strip()

        slides = get_slide_metadata(editor.toPlainText())
        items = [f"{slide['number']} - {slide['title']}" for slide in slides]
        current_index = 0
        if hasattr(editor, "current_slide_index"):
            current_index = min(max(0, editor.current_slide_index()), max(0, len(items) - 1))

        selected_slide, ok = QInputDialog.getItem(
            self,
            "Slide destino",
            "Selecciona el slide al que llevará el enlace:",
            items,
            current_index,
            False
        )
        if not ok or not selected_slide:
            editor.setFocus()
            return

        slide = slides[items.index(selected_slide)]
        target = slide.get("id") or slide.get("key")
        scheme = "slide-id" if slide.get("id") else "slide-key"
        cursor.insertText(f"[{link_text}]({scheme}:{target})")
        editor.setFocus()

    def _ensure_slide_ids_in_editor(self, editor=None, mark_modified=False):
        """Add invisible slide IDs to the current editor text when missing."""
        editor = editor or self._active_markdown_editor()
        text = editor.toPlainText()
        updated, changed = ensure_slide_ids(text)
        if not changed:
            return False

        cursor = editor.textCursor()
        position = cursor.position()
        editor.blockSignals(True)
        editor.setPlainText(updated)
        cursor = editor.textCursor()
        cursor.setPosition(min(position, len(updated)))
        editor.setTextCursor(cursor)
        editor.blockSignals(False)

        if editor is getattr(self, "teacher_editor", None) or (
            editor is self.editor and self.editor_role == "teacher" and not self.split_editor_enabled
        ):
            self.teacher_script_content = updated
            self.teacher_is_modified = bool(mark_modified or self.teacher_is_modified)
        self.is_modified = bool(mark_modified or self.is_modified)
        self._sync_current_tab_from_editor()
        self._update_title()
        if self.nav_mode == "slides":
            self.build_slide_outline()
        return True

    def _repair_broken_slide_links(self, prompt=False, editor=None):
        """Offer to reconnect slide-id links whose target slide no longer exists."""
        editor = editor or self._active_markdown_editor()
        text = editor.toPlainText()
        broken_links = find_broken_internal_slide_links(text)
        if not broken_links:
            return False
        if prompt:
            reply = QMessageBox.question(
                self,
                "Enlaces internos rotos",
                "Hay enlaces a slides que ya no existen. ¿Quieres reasignarlos ahora?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return False

        changed = False
        for broken in broken_links:
            scheme = broken["scheme"]
            old_target = broken["target"]
            slides = [slide for slide in get_slide_metadata(editor.toPlainText()) if slide.get("id")]
            if not slides:
                break
            items = [f"{slide['number']} - {slide['title']}" for slide in slides]
            selected_slide, ok = QInputDialog.getItem(
                self,
                "Reasignar enlace interno",
                f"El destino {old_target} ya no existe. Selecciona el nuevo slide:",
                items,
                0,
                False
            )
            if not ok or not selected_slide:
                continue

            slide = slides[items.index(selected_slide)]
            updated = replace_internal_slide_link(editor.toPlainText(), scheme, old_target, slide["id"])
            editor.setPlainText(updated)
            changed = True

        if changed:
            if editor is getattr(self, "teacher_editor", None) or (
                editor is self.editor and self.editor_role == "teacher" and not self.split_editor_enabled
            ):
                self.teacher_script_content = editor.toPlainText()
                self.teacher_is_modified = True
            self.is_modified = True
            self._sync_current_tab_from_editor()
            self._update_title()
            self.update_preview()
        return changed

    def _md_insert_file_link(self):
        """Insert a Markdown link to a local file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo local",
            "",
            "Todos los archivos (*)"
        )
        if not file_path:
            self._active_markdown_editor().setFocus()
            return

        editor = self._active_markdown_editor()
        cursor = editor.textCursor()
        link_text = cursor.selectedText() if cursor.hasSelection() else os.path.basename(file_path)
        file_url = QUrl.fromLocalFile(file_path).toString()
        cursor.insertText(f"[{link_text}](<{file_url}>)")
        editor.setFocus()

    def _md_insert_image(self):
        """Insert markdown image placeholder."""
        editor = self._active_markdown_editor()
        cursor = editor.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            cursor.insertText(f"![{text}](ruta/imagen.png)")
        else:
            cursor.insertText("![descripcion](ruta/imagen.png)")
        editor.setFocus()

    def _configure_image_display(self):
        """Configure the displayed size and placement of the image at the cursor."""
        active_editor = self._active_markdown_editor()
        candidates = [active_editor, self.editor, getattr(self, "teacher_editor", None)]
        editor = None
        image = None
        unique_candidates = []
        seen_editors = set()
        for candidate in candidates:
            if candidate is None or id(candidate) in seen_editors:
                continue
            seen_editors.add(id(candidate))
            unique_candidates.append(candidate)

        def image_at_cursor(candidate, cursor):
            text = candidate.toPlainText()
            positions = [cursor.position()]
            if cursor.hasSelection():
                positions.extend((cursor.selectionStart(), cursor.selectionEnd()))
            for position in positions:
                located = find_markdown_image_at_position(text, position)
                if located:
                    return located
            return None

        # Toolbar clicks move focus away from the text editor. Prefer a
        # selected image in either editor before falling back to saved focus.
        for candidate in unique_candidates:
            candidate_cursor = candidate.textCursor()
            if not candidate_cursor.hasSelection():
                continue
            candidate_image = image_at_cursor(candidate, candidate_cursor)
            if candidate_image and (
                candidate_cursor.selectionStart() <= candidate_image["end"]
                and candidate_image["start"] <= candidate_cursor.selectionEnd()
            ):
                editor, image = candidate, candidate_image
                break

        if editor is None:
            for candidate in unique_candidates:
                candidate_image = image_at_cursor(candidate, candidate.textCursor())
                if candidate_image:
                    editor, image = candidate, candidate_image
                    break

        if not image:
            self.statusBar().showMessage(
                "Coloca el cursor en la linea de la imagen que deseas configurar.",
                3500,
            )
            active_editor.setFocus()
            return

        cursor = editor.textCursor()
        source = editor.toPlainText()
        options, directive_range = get_image_display_options(source, image["start"])
        dialog = QDialog(self)
        dialog.setWindowTitle("Configurar imagen")
        dialog.setModal(True)
        dialog.setMinimumWidth(360)
        layout = QGridLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        width_combo = QComboBox(dialog)
        for label, value in (
            ("Automatico", "auto"),
            ("25%", "25%"),
            ("40%", "40%"),
            ("60%", "60%"),
            ("80%", "80%"),
            ("100%", "100%"),
        ):
            width_combo.addItem(label, value)

        alignment_combo = QComboBox(dialog)
        for label, value in (
            ("Izquierda", "left"),
            ("Centro", "center"),
            ("Derecha", "right"),
        ):
            alignment_combo.addItem(label, value)

        spacing_combo = QComboBox(dialog)
        for label, value in (
            ("Compacto", "compact"),
            ("Normal", "normal"),
            ("Amplio", "wide"),
        ):
            spacing_combo.addItem(label, value)

        orientation_combo = QComboBox(dialog)
        for label, value in (("0 grados", "0"), ("90 grados", "90"),
                             ("180 grados", "180"), ("270 grados", "270")):
            orientation_combo.addItem(label, value)
        color_combo = QComboBox(dialog)
        color_combo.addItem("Color", "color")
        color_combo.addItem("Escala de grises", "grayscale")

        for combo, value in (
            (width_combo, options["width"]),
            (alignment_combo, options["align"]),
            (spacing_combo, options["spacing"]),
            (orientation_combo, options["orientation"]),
            (color_combo, options["color"]),
        ):
            index = combo.findData(value)
            combo.setCurrentIndex(max(0, index))

        layout.addWidget(QLabel("Ancho en la hoja:"), 0, 0)
        layout.addWidget(width_combo, 0, 1)
        layout.addWidget(QLabel("Alineacion:"), 1, 0)
        layout.addWidget(alignment_combo, 1, 1)
        layout.addWidget(QLabel("Espaciado vertical:"), 2, 0)
        layout.addWidget(spacing_combo, 2, 1)
        layout.addWidget(QLabel("Orientacion:"), 3, 0)
        layout.addWidget(orientation_combo, 3, 1)
        layout.addWidget(QLabel("Color:"), 4, 0)
        layout.addWidget(color_combo, 4, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons, 5, 0, 1, 2)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            editor.setFocus()
            return

        directive = (
            "<!-- numa-image: "
            f"width={width_combo.currentData()}, "
            f"align={alignment_combo.currentData()}, "
            f"spacing={spacing_combo.currentData()}, "
            f"orientation={orientation_combo.currentData()}, "
            f"color={color_combo.currentData()}, "
            f"frame={options.get('frame', 'none')} -->"
        )
        start, end = directive_range or (image["start"], image["start"])
        if directive_range:
            end = image["start"]

        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(f"{directive}\n")
        cursor.endEditBlock()
        editor.setTextCursor(cursor)
        editor.setFocus()
        self._last_active_markdown_editor = editor
        self._log_operation(
            "configurar_imagen",
            width=width_combo.currentData(),
            align=alignment_combo.currentData(),
            spacing=spacing_combo.currentData(),
        )
        self.statusBar().showMessage("Configuracion de imagen aplicada.", 2500)

    def _md_insert_codeblock(self):
        """Insert fenced code block."""
        editor = self._active_markdown_editor()
        cursor = editor.textCursor()
        cursor.insertText("```\n\n```")
        cursor.movePosition(cursor.MoveOperation.Up, cursor.MoveMode.MoveAnchor)
        editor.setTextCursor(cursor)
        editor.setFocus()

    def _md_insert_csharp_codeblock(self):
        """Insert a C# fenced code block."""
        editor = self._active_markdown_editor()
        cursor = editor.textCursor()
        cursor.insertText("```csharp\n\n```")
        cursor.movePosition(cursor.MoveOperation.Up, cursor.MoveMode.MoveAnchor)
        editor.setTextCursor(cursor)
        editor.setFocus()

    def create_shortcuts(self):
        self.shortcut_objects = {}
        for action_id, description, default, callback_name, scope in self.SHORTCUT_DEFINITIONS:
            shortcut = QShortcut(QKeySequence(self.shortcut_bindings.get(action_id, default)), self)
            shortcut.setProperty("shortcut_id", action_id)
            shortcut.activated.connect(getattr(self, callback_name))
            shortcut.setEnabled(scope == "global")
            self.shortcut_objects[action_id] = shortcut

        # Preserve the attribute names used by presentation lifecycle code.
        self.shortcut_esc = self.shortcut_objects["presentacion_salir"]
        self.shortcut_left = self.shortcut_objects["slide_anterior"]
        self.shortcut_right = self.shortcut_objects["slide_siguiente"]
        self.shortcut_space = self.shortcut_objects["slide_siguiente_espacio"]
        self.shortcut_backspace = self.shortcut_objects["slide_anterior_backspace"]
        self.shortcut_page_up = self.shortcut_objects["slide_anterior_pageup"]
        self.shortcut_page_down = self.shortcut_objects["slide_siguiente_pagedown"]
        self.shortcut_teacher_prev = self.shortcut_objects["profesor_anterior"]
        self.shortcut_teacher_next = self.shortcut_objects["profesor_siguiente"]
        self.shortcut_f9 = self.shortcut_objects["alumno_texto_menos"]
        self.shortcut_f10 = self.shortcut_objects["alumno_texto_mas"]
        self.shortcut_f7 = self.shortcut_objects["profesor_texto_menos"]
        self.shortcut_f8 = self.shortcut_objects["profesor_texto_mas"]

        # Hardware zoom keys remain available in addition to the configurable
        # Ctrl bindings because Qt exposes them as standard key sequences.
        self.shortcut_zoom_in_standard = QShortcut(QKeySequence("ZoomIn"), self)
        self.shortcut_zoom_in_standard.activated.connect(self.zoom_in)
        self.shortcut_zoom_out_standard = QShortcut(QKeySequence("ZoomOut"), self)
        self.shortcut_zoom_out_standard.activated.connect(self.zoom_out)

    def _enable_presentation_shortcuts(self):
        for action_id, description, default, callback_name, scope in self.SHORTCUT_DEFINITIONS:
            if scope == "presentation":
                self.shortcut_objects[action_id].setEnabled(True)

    def _disable_presentation_shortcuts(self):
        for action_id, description, default, callback_name, scope in self.SHORTCUT_DEFINITIONS:
            if scope == "presentation":
                self.shortcut_objects[action_id].setEnabled(False)

    def _presentation_target_screen(self):
        screens = QApplication.screens()
        current = self.screen()
        for screen in screens:
            if screen != current:
                return screen
        return None

    def _sync_output_window_style(self):
        if not self.presentation_output_window:
            return
        output = self.presentation_output_window.preview
        output.presentation_mode = self.preview.presentation_mode
        output.font_size = self.preview.font_size
        output.zoom_factor = self.preview.zoom_factor
        output.borderless = self.preview.borderless
        output.clock_visible = self.preview.clock_visible
        output.clock_mode = self.preview.clock_mode
        output.clock_show_seconds = self.preview.clock_show_seconds
        output.clock_size = self.preview.clock_size
        output.clock_position = self.preview.clock_position
        output.timer_duration_seconds = self.preview.timer_duration_seconds
        output.timer_elapsed_seconds = self.preview.timer_elapsed_seconds
        output.timer_running = self.preview.timer_running
        output._timer_started_at = self.preview._timer_started_at
        output.set_output_aspect_ratio(self.preview.output_width, self.preview.output_height)
        output.set_teacher_marker(False, "PROFESOR")

    def _sync_output_window_to_slide(self, slide_index):
        if self.dual_control_window:
            # Editor and regular-preview navigation must never take control
            # of an active dual presentation. The dual console is its own
            # source of truth and the projector mirrors only that source.
            return
        # The normal output window follows preview changes only in the regular
        # presentation mode. In Presentar Dual, the dedicated console owns
        # both its student presentation and the passive projector mirror.
        if self.presentation_output_window and not self.dual_control_window:
            self.presentation_output_window.preview.goto_slide(slide_index)

    def _mirror_dual_student_interaction(self):
        """Mirror direct HTML interactions from teacher control to projector."""
        self._sync_dual_student_projection_state()

    def _sync_dual_student_projection_state(self):
        """Keep the projector as a read-only mirror of the student control pane."""
        control = self.dual_control_window
        output = self.presentation_output_window
        if not control or not output:
            self._dual_projection_sync_timer.stop()
            self._dual_projection_sync_pending = False
            return
        if output.cast_mode:
            # The secondary display is a visual cast, not a second HTML
            # presentation. It therefore cannot diverge from the control pane.
            output.update_cast_frame(control.student_preview.grab())
            return
        if self._dual_projection_sync_pending:
            return
        self._dual_projection_sync_pending = True

        def apply_to_projector(state):
            self._dual_projection_sync_pending = False
            if self.dual_control_window and self.presentation_output_window:
                self._apply_dual_student_state_to_projector(state)

        control.student_preview.get_interactive_state(apply_to_projector)

    def _apply_dual_student_state_to_projector(self, state):
        if not isinstance(state, dict):
            return
        # Avoid injecting identical state into Chromium every timer cycle.
        state_key = json.dumps(state, sort_keys=True, ensure_ascii=True)
        if state_key == self._dual_projection_state:
            return

        def remember_if_applied(applied):
            # The output WebView can still be loading when dual presentation
            # opens. Keep retrying until its image overlay API is available.
            if applied:
                self._dual_projection_state = state_key

        self.presentation_output_window.preview.apply_interactive_state(
            state,
            callback=remember_if_applied,
        )

    def _sync_teacher_local_presentation_to_slide(self, student_slide_index):
        teacher_slide = self._matching_teacher_slide_index(student_slide_index)
        if self.teacher_local_presentation_window:
            self.teacher_local_presentation_window.preview.goto_slide(teacher_slide)
        if self.dual_control_window:
            self.dual_control_window.teacher_preview.goto_slide(teacher_slide)

    def _presentation_student_view(self):
        if self.dual_control_window:
            return self.dual_control_window.student_preview
        if self.teacher_local_presentation_window and not self.is_fullscreen_presentation:
            return self.teacher_local_presentation_window.preview
        return self.presentation_output_window.preview if self.presentation_output_window else self.preview

    def _presentation_teacher_view(self):
        if self.dual_control_window:
            return self.dual_control_window.teacher_preview
        if self.teacher_local_presentation_window:
            return self.teacher_local_presentation_window.preview
        if self.teacher_preview.isVisible():
            return self.teacher_preview
        return None

    def _sync_teacher_local_window_style(self):
        teacher_views = []
        if self.teacher_local_presentation_window:
            teacher_views.append(self.teacher_local_presentation_window.preview)
        if self.dual_control_window:
            teacher_views.append(self.dual_control_window.teacher_preview)
        for teacher in teacher_views:
            self._apply_teacher_presentation_style(teacher)

    def _apply_teacher_presentation_style(self, teacher):
        teacher.presentation_mode = self.preview.presentation_mode
        teacher.font_size = self.teacher_preview.font_size
        teacher.zoom_factor = self.teacher_preview.zoom_factor
        teacher.borderless = self.preview.borderless
        teacher.clock_visible = self.teacher_preview.clock_visible
        teacher.clock_mode = self.preview.clock_mode
        teacher.clock_show_seconds = self.preview.clock_show_seconds
        teacher.clock_size = self.preview.clock_size
        teacher.clock_position = self.preview.clock_position
        teacher.timer_duration_seconds = self.preview.timer_duration_seconds
        teacher.timer_elapsed_seconds = self.preview.timer_elapsed_seconds
        teacher.timer_running = self.preview.timer_running
        teacher._timer_started_at = self.preview._timer_started_at
        teacher.set_output_aspect_ratio(self.preview.output_width, self.preview.output_height)
        teacher.set_teacher_marker(self.teacher_marker_visible, self.teacher_marker_text)

    def _sync_dual_control_window_style(self):
        if not self.dual_control_window:
            return
        student = self.dual_control_window.student_preview
        student.presentation_mode = self.preview.presentation_mode
        student.font_size = self.preview.font_size
        student.zoom_factor = self.preview.zoom_factor
        student.borderless = self.preview.borderless
        student.clock_visible = self.preview.clock_visible
        student.clock_mode = self.preview.clock_mode
        student.clock_show_seconds = self.preview.clock_show_seconds
        student.clock_size = self.preview.clock_size
        student.clock_position = self.preview.clock_position
        student.timer_duration_seconds = self.preview.timer_duration_seconds
        student.timer_elapsed_seconds = self.preview.timer_elapsed_seconds
        student.timer_running = self.preview.timer_running
        student._timer_started_at = self.preview._timer_started_at
        student.set_output_aspect_ratio(self.preview.output_width, self.preview.output_height)
        student.set_teacher_marker(False, "PROFESOR")
        student.set_student_sync_label(
            self.student_sync_label_visible,
            self._student_sync_label_map(),
        )
        self._apply_teacher_presentation_style(self.dual_control_window.teacher_preview)

    def _shortcut_sequence(self, action_id):
        return QKeySequence(self.shortcut_bindings.get(action_id, ""))

    def _create_presentation_window_shortcut(self, window, action_id, callback):
        shortcut = QShortcut(self._shortcut_sequence(action_id), window)
        shortcut.setProperty("shortcut_id", action_id)
        shortcut.activated.connect(callback)
        return shortcut

    def _update_presentation_window_shortcut(self, action_id, sequence):
        for window in (
            self.presentation_output_window,
            self.teacher_local_presentation_window,
            self.dual_control_window,
        ):
            for shortcut in getattr(window, "_shortcuts", ()) if window else ():
                if shortcut.property("shortcut_id") == action_id:
                    shortcut.setKey(sequence)

    def _bind_student_output_shortcuts(self, window):
        window._shortcuts = [
            self._create_presentation_window_shortcut(window, "slide_anterior", self.presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "slide_siguiente", self.presentation_next_slide),
            self._create_presentation_window_shortcut(window, "slide_siguiente_espacio", self.presentation_next_slide),
            self._create_presentation_window_shortcut(window, "slide_anterior_backspace", self.presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "presentacion_salir", self.handle_presentation_escape),
            self._create_presentation_window_shortcut(window, "profesor_anterior", self.teacher_presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "profesor_siguiente", self.teacher_presentation_next_slide),
            self._create_presentation_window_shortcut(window, "alumno_texto_menos", self.decrease_student_font_size),
            self._create_presentation_window_shortcut(window, "alumno_texto_mas", self.increase_student_font_size),
            self._create_presentation_window_shortcut(window, "profesor_texto_menos", self.decrease_teacher_font_size),
            self._create_presentation_window_shortcut(window, "profesor_texto_mas", self.increase_teacher_font_size),
            self._create_presentation_window_shortcut(window, "imagen_abrir", self._open_presentation_image_from_shortcut),
            self._create_presentation_window_shortcut(window, "imagen_pantalla_completa", self._toggle_current_slide_image),
            self._create_presentation_window_shortcut(window, "imagen_zoom_mas", self._zoom_in_presentation_image_shortcut),
            self._create_presentation_window_shortcut(window, "imagen_zoom_menos", self._zoom_out_presentation_image_shortcut),
            self._create_presentation_window_shortcut(window, "slide_anterior_pageup", self.presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "slide_siguiente_pagedown", self.presentation_next_slide),
        ]

    def _bind_teacher_output_shortcuts(self, window):
        window._shortcuts = [
            self._create_presentation_window_shortcut(window, "profesor_anterior", self.teacher_presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "profesor_siguiente", self.teacher_presentation_next_slide),
            self._create_presentation_window_shortcut(window, "presentacion_salir", self.handle_presentation_escape),
            self._create_presentation_window_shortcut(window, "slide_anterior", self.presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "slide_siguiente", self.presentation_next_slide),
            self._create_presentation_window_shortcut(window, "alumno_texto_menos", self.decrease_student_font_size),
            self._create_presentation_window_shortcut(window, "alumno_texto_mas", self.increase_student_font_size),
            self._create_presentation_window_shortcut(window, "profesor_texto_menos", self.decrease_teacher_font_size),
            self._create_presentation_window_shortcut(window, "profesor_texto_mas", self.increase_teacher_font_size),
            self._create_presentation_window_shortcut(window, "imagen_abrir", self._open_presentation_image_from_shortcut),
            self._create_presentation_window_shortcut(window, "imagen_pantalla_completa", self._toggle_current_slide_image),
            self._create_presentation_window_shortcut(window, "imagen_zoom_mas", self._zoom_in_presentation_image_shortcut),
            self._create_presentation_window_shortcut(window, "imagen_zoom_menos", self._zoom_out_presentation_image_shortcut),
            self._create_presentation_window_shortcut(window, "slide_anterior_pageup", self.presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "slide_siguiente_pagedown", self.presentation_next_slide),
        ]

    def _bind_dual_control_shortcuts(self, window):
        """Keep all presentation navigation available from the teacher screen."""
        window._shortcuts = [
            self._create_presentation_window_shortcut(window, "slide_anterior", self.presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "slide_siguiente", self.presentation_next_slide),
            self._create_presentation_window_shortcut(window, "slide_siguiente_espacio", self.presentation_next_slide),
            self._create_presentation_window_shortcut(window, "slide_anterior_backspace", self.presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "profesor_anterior", self.teacher_presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "profesor_siguiente", self.teacher_presentation_next_slide),
            self._create_presentation_window_shortcut(window, "alumno_texto_menos", self.decrease_student_font_size),
            self._create_presentation_window_shortcut(window, "alumno_texto_mas", self.increase_student_font_size),
            self._create_presentation_window_shortcut(window, "profesor_texto_menos", self.decrease_teacher_font_size),
            self._create_presentation_window_shortcut(window, "profesor_texto_mas", self.increase_teacher_font_size),
            self._create_presentation_window_shortcut(window, "imagen_abrir", self._open_presentation_image_from_shortcut),
            self._create_presentation_window_shortcut(window, "imagen_pantalla_completa", self._toggle_current_slide_image),
            self._create_presentation_window_shortcut(window, "imagen_zoom_mas", self._zoom_in_presentation_image_shortcut),
            self._create_presentation_window_shortcut(window, "imagen_zoom_menos", self._zoom_out_presentation_image_shortcut),
            self._create_presentation_window_shortcut(window, "presentacion_salir", self.handle_presentation_escape),
            self._create_presentation_window_shortcut(window, "slide_anterior_pageup", self.presentation_prev_slide),
            self._create_presentation_window_shortcut(window, "slide_siguiente_pagedown", self.presentation_next_slide),
        ]

    def _is_presentation_double_press(self, direction):
        now = time.monotonic()
        attribute = f"_presentation_{direction}_press_at"
        previous = getattr(self, attribute, 0.0)
        double = 0.0 < now - previous <= self._presentation_double_press_window
        setattr(self, attribute, 0.0 if double else now)
        return double

    def _perform_presentation_next_slide(self):
        self._log_operation("navegar_presentacion", direction="next", target="student")
        target = self._presentation_student_view()
        if self._dual_presentation_sync_active():
            target.get_current_slide(self._prepare_dual_presentation_next_slide)
            return
        target.next_slide()
        target.get_current_slide(self._after_presentation_navigation)

    def _center_editor_on_slide(self, slide_index):
        """Scroll the Markdown editor so the slide's first text line is centered."""
        try:
            lines = self.editor.toPlainText().split("\n")
            start = self._rendered_slide_start_line(lines, max(0, int(slide_index)))
            if start is None:
                return
            block = self.editor.document().findBlockByNumber(start)
            if not block.isValid():
                return
            cursor = QTextCursor(block)
            # Move the cursor without re-triggering preview navigation.
            self.editor.blockSignals(True)
            try:
                self.editor.setTextCursor(cursor)
            finally:
                self.editor.blockSignals(False)
            self.editor.centerCursor()
        except Exception:
            logging.exception("No se pudo centrar el editor en el slide")

    def _center_editor_on_paper_page(self, page_info):
        """Move and center the Markdown editor on the source line of the shown printed page."""
        if not isinstance(page_info, dict):
            return
        try:
            lines = self.editor.toPlainText().split("\n")
            if not lines:
                return
            total_pages = max(1, int(page_info.get("total", 1) or 1))
            page_index = max(0, min(int(page_info.get("page", 0) or 0), total_pages - 1))
            slide_index = int(page_info.get("slideIndex", -1))
            snippets = page_info.get("snippets") or []

            def _normalize_md(text):
                cleaned = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text or "")
                cleaned = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cleaned)
                cleaned = re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s+)+", "", cleaned)
                cleaned = re.sub(r"[*_`~]+", "", cleaned)
                cleaned = re.sub(r"\s+", " ", cleaned).strip().casefold()
                return cleaned

            slide_start = None
            slide_end = len(lines)
            if slide_index >= 0:
                slide_start = self._rendered_slide_start_line(lines, slide_index)
                next_start = self._rendered_slide_start_line(lines, slide_index + 1)
                if next_start is not None and (slide_start is None or next_start > slide_start):
                    slide_end = next_start

            def _find_matching_line(start_idx, end_idx):
                for snippet in snippets:
                    needle = _normalize_md(snippet)
                    if len(needle) < 6:
                        continue
                    probe = needle[:60]
                    short_probe = needle[:28]
                    for line_idx in range(max(0, start_idx), min(len(lines), end_idx)):
                        norm_line = _normalize_md(lines[line_idx])
                        if not norm_line:
                            continue
                        if probe in norm_line or (len(norm_line) >= 10 and norm_line in needle):
                            return line_idx
                    for line_idx in range(max(0, start_idx), min(len(lines), end_idx)):
                        norm_line = _normalize_md(lines[line_idx])
                        if norm_line and short_probe in norm_line:
                            return line_idx
                return None

            target_line = None
            if slide_start is not None:
                target_line = _find_matching_line(slide_start, slide_end)
            if target_line is None:
                target_line = _find_matching_line(0, len(lines))
            if target_line is None and slide_start is not None:
                target_line = slide_start
            if target_line is None:
                ratio = page_index / max(1, total_pages - 1)
                target_line = int(round(ratio * max(0, len(lines) - 1)))

            block = self.editor.document().findBlockByNumber(target_line)
            if not block.isValid():
                return
            cursor = QTextCursor(block)
            self.editor.blockSignals(True)
            try:
                self.editor.setTextCursor(cursor)
            finally:
                self.editor.blockSignals(False)
            self.editor.centerCursor()
            if hasattr(self, "cursor_label"):
                self.cursor_label.setText(f"Ln {target_line + 1}, Col 1")
            if slide_index >= 0 and self.nav_mode == "slides":
                self._highlight_outline_slide(slide_index)
        except Exception:
            logging.exception("No se pudo centrar el editor en la hoja impresa")

    def _quick_next_slide(self):
        if getattr(self.preview, "presentation_mode", "slide") == "paper":
            self.preview.step_paper_page(1, self._center_editor_on_paper_page)
            return
        self.preview.next_slide()
        self.preview.get_current_slide(self._after_presentation_navigation)

    def _quick_prev_slide(self):
        if getattr(self.preview, "presentation_mode", "slide") == "paper":
            self.preview.step_paper_page(-1, self._center_editor_on_paper_page)
            return
        self.preview.prev_slide()
        self.preview.get_current_slide(self._after_presentation_navigation)

    def presentation_next_slide(self):
        target = self._presentation_student_view()
        target.close_image_zoom_if_open(
            lambda was_open: self._presentation_next_slide_after_image_guard(was_open, target)
        )

    def _presentation_next_slide_after_image_guard(self, image_was_open, target):
        if image_was_open:
            self._presentation_hold_opened = False
            self._presentation_hold_long_attempted = False
            self._log_operation("cerrar_imagen_presentacion_pulsacion")
            return
        self._perform_presentation_next_slide()

    def _perform_presentation_prev_slide(self):
        self._log_operation("navegar_presentacion", direction="previous", target="student")
        target = self._presentation_student_view()
        target.prev_slide()
        target.get_current_slide(self._after_presentation_navigation)

    def presentation_prev_slide(self):
        target = self._presentation_student_view()
        target.close_image_zoom_if_open(
            lambda was_open: self._presentation_prev_slide_after_image_guard(was_open, target)
        )

    def _presentation_prev_slide_after_image_guard(self, image_was_open, target):
        if image_was_open:
            self._presentation_hold_opened = False
            self._presentation_hold_long_attempted = False
            self._log_operation("cerrar_imagen_presentacion_pulsacion")
            return
        if self._is_presentation_double_press("prev"):
            target.close_image_zoom_if_open(
                lambda was_open: None if was_open else self._perform_presentation_prev_slide()
            )
            return
        self._perform_presentation_prev_slide()

    def teacher_presentation_next_slide(self):
        self._log_operation("navegar_presentacion", direction="next", target="teacher")
        teacher_view = self._presentation_teacher_view()
        if teacher_view:
            teacher_view.next_slide()

    def teacher_presentation_prev_slide(self):
        self._log_operation("navegar_presentacion", direction="previous", target="teacher")
        teacher_view = self._presentation_teacher_view()
        if teacher_view:
            teacher_view.prev_slide()

    def _after_presentation_navigation(self, slide_index, sync_teacher=True):
        try:
            slide_index = max(0, int(slide_index))
        except (TypeError, ValueError):
            slide_index = 0
        # Do not turn the embedded editing preview into a second presentation
        # controller while the dedicated dual console is on screen.
        if not self.dual_control_window:
            self.preview.goto_slide(slide_index)
        self._center_editor_on_slide(slide_index)
        if sync_teacher:
            self._sync_teacher_local_presentation_to_slide(slide_index)
            self._sync_teacher_preview_to_student_slide(slide_index)
        self._remember_current_file_preferences(slide_index=slide_index)
        self._update_preview_slide_label(slide_index)

    def _dual_presentation_sync_active(self):
        if not self.teacher_script_content:
            return False
        return self._presentation_teacher_view() is not None

    def _initial_teacher_presentation_slide(self, student_slide_index):
        """Choose the teacher's manual starting point for dual presentation.

        If student slide 1 is explicitly paired with a later teacher slide,
        start the teacher at slide 1 too.  The teacher then reaches the pair
        with the normal Q/W navigation, while the student remains on slide 1.
        """
        try:
            student_slide_index = max(0, int(student_slide_index))
        except (TypeError, ValueError):
            student_slide_index = 0

        paired_teacher_slide = self._synced_teacher_slide_for_student(student_slide_index)
        if student_slide_index == 0 and paired_teacher_slide is not None and paired_teacher_slide > 0:
            return 0, True, paired_teacher_slide
        return self._matching_teacher_slide_index(student_slide_index), False, paired_teacher_slide

    def _prepare_dual_presentation_next_slide(self, current_student_slide):
        try:
            current_student_slide = max(0, int(current_student_slide))
        except (TypeError, ValueError):
            current_student_slide = 0

        # Before moving the student, close any pending gap for the slide that
        # is already on screen.  This makes the regular student controls
        # (arrows/Space) advance the teacher first when its paired slide is
        # later in the teacher script.
        current_teacher_target = self._synced_teacher_slide_for_student(current_student_slide)
        teacher_view = self._presentation_teacher_view()
        if current_teacher_target is not None and teacher_view is not None:
            teacher_view.get_current_slide(
                lambda current_teacher_slide: self._finish_current_dual_sync_gap(
                    current_student_slide,
                    current_teacher_target,
                    current_teacher_slide,
                )
            )
            return

        self._prepare_next_student_advance(current_student_slide)

    def _finish_current_dual_sync_gap(self, student_slide_index, target_teacher_slide, current_teacher_slide):
        """Advance only the teacher until it reaches the current student pair."""
        try:
            current_teacher_slide = max(0, int(current_teacher_slide))
        except (TypeError, ValueError):
            current_teacher_slide = 0

        teacher_view = self._presentation_teacher_view()
        if teacher_view is None:
            self._prepare_next_student_advance(student_slide_index)
            return

        if current_teacher_slide < target_teacher_slide:
            next_teacher_slide = current_teacher_slide + 1
            teacher_view.goto_slide(next_teacher_slide)
            if next_teacher_slide == target_teacher_slide:
                self.statusBar().showMessage(
                    f"Sincronizados en alumno {student_slide_index + 1} y profesor {target_teacher_slide + 1}. "
                    "El siguiente avance pasara al alumno.",
                    3000,
                )
            else:
                self.statusBar().showMessage(
                    f"Alumno espera en slide {student_slide_index + 1}; profesor avanzando a slide "
                    f"{target_teacher_slide + 1}",
                    2500,
                )
            return

        self._prepare_next_student_advance(student_slide_index)

    def _prepare_next_student_advance(self, current_student_slide):
        """Apply the existing pair-aware rule for the student's next slide."""

        student_total = len(get_slide_metadata(self._presentation_markdown_text()))
        if student_total <= 0 or current_student_slide >= student_total - 1:
            self._advance_student_normally()
            return

        next_student_slide = current_student_slide + 1
        target_teacher_slide = self._synced_teacher_slide_for_student(next_student_slide)
        teacher_view = self._presentation_teacher_view()
        if target_teacher_slide is None or teacher_view is None:
            self._advance_student_normally()
            return

        teacher_view.get_current_slide(
            lambda current_teacher_slide: self._finish_dual_presentation_next_slide(
                current_student_slide,
                next_student_slide,
                target_teacher_slide,
                current_teacher_slide,
            )
        )

    def _finish_dual_presentation_next_slide(self, current_student_slide, next_student_slide, target_teacher_slide, current_teacher_slide):
        try:
            current_teacher_slide = max(0, int(current_teacher_slide))
        except (TypeError, ValueError):
            current_teacher_slide = 0

        teacher_view = self._presentation_teacher_view()
        student_view = self._presentation_student_view()
        if teacher_view is None:
            self._advance_student_normally()
            return

        if current_teacher_slide < target_teacher_slide:
            next_teacher_slide = current_teacher_slide + 1
            teacher_view.goto_slide(next_teacher_slide)
            if next_teacher_slide >= target_teacher_slide:
                student_view.goto_slide(next_student_slide)
                self._after_presentation_navigation(next_student_slide, sync_teacher=False)
                self.statusBar().showMessage(
                    f"Sincronizados: alumno {next_student_slide + 1} y profesor {target_teacher_slide + 1}",
                    2500,
                )
                return
            self.statusBar().showMessage(
                f"Alumno pausado en slide {current_student_slide + 1}; profesor avanzando a sincronizacion {target_teacher_slide + 1}",
                2500,
            )
            return

        if current_teacher_slide > target_teacher_slide:
            teacher_view.goto_slide(target_teacher_slide)

        student_view.goto_slide(next_student_slide)
        self._after_presentation_navigation(next_student_slide, sync_teacher=False)

    def _advance_student_normally(self):
        target = self._presentation_student_view()
        target.next_slide()
        if self._dual_presentation_sync_active():
            target.get_current_slide(lambda slide_index: self._after_presentation_navigation(slide_index, sync_teacher=False))
        else:
            target.get_current_slide(self._after_presentation_navigation)

    def create_statusbar(self):
        self.statusBar().setStyleSheet("font-size: 12px;")

        self.autosave_notice_label = QLabel("")
        self.autosave_notice_label.setObjectName("autosaveNotice")
        self.autosave_notice_label.setVisible(False)
        self.autosave_notice_label.setToolTip("Ultimo autosave de recuperacion")
        self.statusBar().addWidget(self.autosave_notice_label, 1)
        self.autosave_notice_timer = QTimer(self)
        self.autosave_notice_timer.setSingleShot(True)
        self.autosave_notice_timer.timeout.connect(self.autosave_notice_label.hide)

        self.mobile_link_label = QLabel(self._mobile_link_address_text())
        self.mobile_link_label.setObjectName("mobileLinkAddress")
        self.mobile_link_label.hide()

        self.mobile_link_qr_button = QPushButton("QR Mobile", self)
        self.mobile_link_qr_button.clicked.connect(self._show_mobile_link_qr)
        self.mobile_link_qr_button.hide()

        self.mobile_direct_button = QPushButton("Conexión directa", self)
        self.mobile_direct_button.clicked.connect(self._show_direct_connections)
        self.mobile_direct_button.hide()

        self.mobile_control_btn = QToolButton(self)
        self.mobile_control_btn.setObjectName("mobileControlBtn")
        self.mobile_control_btn.setText("Control móvil")
        self.mobile_control_btn.setToolTip("Emparejar NUMA Deck Android-Link mediante QR, Bluetooth o Wi-Fi Direct")
        self.mobile_control_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        mobile_menu = QMenu(self.mobile_control_btn)
        mobile_menu.addAction("Mostrar código QR (Wi-Fi)", self._show_mobile_link_qr)
        mobile_menu.addAction("Conexión directa (Bluetooth / Wi-Fi Direct)", self._show_direct_connections)
        mobile_menu.addSeparator()
        mobile_menu.addAction("Copiar enlace de emparejamiento", self._copy_mobile_link_url)
        self.mobile_control_btn.setMenu(mobile_menu)
        self.statusBar().addPermanentWidget(self.mobile_control_btn)

        # Left side: normal status message
        self.status_label = QLabel("Listo")
        self.statusBar().addPermanentWidget(self.status_label)

        # Right side: position info
        self.pos_label = QLabel("Ln 1, Col 1")
        self.pos_label.setMinimumWidth(100)
        self.statusBar().addPermanentWidget(self.pos_label)

        self.words_label = QLabel("0 palabras")
        self.words_label.setMinimumWidth(100)
        self.statusBar().addPermanentWidget(self.words_label)

        self.mode_label = QLabel("Diapositivas")
        self.mode_label.setMinimumWidth(90)
        self.statusBar().addPermanentWidget(self.mode_label)

        self.preview_slide_label = QLabel("Slide 1/1")
        self.preview_slide_label.setMinimumWidth(80)
        self.statusBar().addPermanentWidget(self.preview_slide_label)

        try:
            self._active_markdown_editor()._emit_word_count()
        except Exception:
            pass

    def _show_direct_connections(self):
        dialog = DirectConnectionsDialog(self.direct_connections, self)
        dialog.exec()

    def _copy_mobile_link_url(self):
        QApplication.clipboard().setText(self._mobile_link_connection_url())
        self.statusBar().showMessage("Enlace de Control móvil copiado al portapapeles", 2500)

    def _mobile_link_address_text(self):
        """Return a usable LAN address for the Android-Link client."""
        addresses = []
        try:
            hostname = socket.gethostname()
            _, _, resolved = socket.gethostbyname_ex(hostname)
            addresses.extend(resolved)
        except OSError:
            pass
        addresses = [address for address in addresses if not address.startswith("127.")]
        address = addresses[0] if addresses else "127.0.0.1"
        token = getattr(getattr(self, "mobile_link", None), "auth_token", "")
        token_suffix = f"/?token={token}" if token else ""
        return f"Mobile-Link: ws://{address}:8765{token_suffix}"

    def _mobile_link_connection_url(self):
        """Return the current WebSocket URL without the visible status label."""
        return self._mobile_link_address_text().split("Mobile-Link: ", 1)[-1].strip()

    def _mobile_link_qr_payload(self):
        """Build the versioned QR payload consumed by NUMA Deck Android-Link."""
        return f"NUMA-LINK|1|{self._mobile_link_connection_url()}"

    def _show_mobile_link_qr(self):
        """Show the current Mobile-Link address and pairing token as a QR code."""
        try:
            import qrcode
        except ImportError:
            QMessageBox.warning(
                self,
                "QR no disponible",
                "Instala las dependencias del proyecto para generar códigos QR:\n\n"
                "python -m pip install -r requirements.txt",
            )
            self._log_operation("mobile_link_qr_dependencia_faltante")
            return

        connection_url = self._mobile_link_connection_url()
        qr_payload = self._mobile_link_qr_payload()
        try:
            code = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=10,
                border=4,
            )
            code.add_data(qr_payload)
            code.make(fit=True)
            image = code.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            pixmap = QPixmap()
            if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
                raise ValueError("No se pudo convertir el QR a una imagen Qt")
        except Exception as error:
            self._log_operation("mobile_link_qr_error", error=str(error))
            QMessageBox.critical(self, "Error al generar QR", str(error))
            return

        dialog = QDialog(self)
        self.mobile_link_qr_dialog = dialog
        dialog.finished.connect(
            lambda: setattr(self, "mobile_link_qr_dialog", None)
            if self.mobile_link_qr_dialog is dialog else None
        )
        dialog.setWindowTitle("Emparejar NUMA Deck Android-Link")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        image_label = QLabel(dialog)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setPixmap(pixmap.scaled(
            420,
            420,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        layout.addWidget(image_label)
        address_label = QLabel(
            f"Escanea este código desde Mobile:\n{connection_url}",
            dialog,
        )
        address_label.setWordWrap(True)
        layout.addWidget(address_label)
        copy_button = QPushButton("Copiar dirección", dialog)
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(connection_url)
        )
        layout.addWidget(copy_button)
        close_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        close_button.rejected.connect(dialog.reject)
        layout.addWidget(close_button)
        self._log_operation("mobile_link_qr_mostrado")
        dialog.exec()

    def _show_autosave_notice(self, paths):
        """Show the temporary red recovery-backup notice in the lower left."""
        if not paths or not hasattr(self, "autosave_notice_label"):
            return
        names = []
        for path in paths:
            name = os.path.basename(path)
            if name and name not in names:
                names.append(name)
        timestamp = time.strftime("%H:%M:%S")
        self.autosave_notice_label.setText(
            f"Autosave {timestamp}: {', '.join(names)}"
        )
        self.autosave_notice_label.setStyleSheet(
            "color: #DC2626; font-weight: 700; padding-left: 6px;"
        )
        self.autosave_notice_label.setVisible(True)
        self.autosave_notice_timer.start(7000)

    # ── Theme ─────────────────────────────────────────────

    def _app_preferences_config_path(self):
        return os.path.join(os.path.expanduser("~"), ".numa_deck_settings.json")

    def _load_app_preferences(self):
        """Load global settings that do not belong to a Markdown document."""
        try:
            with open(self._app_preferences_config_path(), "r", encoding="utf-8") as file:
                data = json.load(file)
            preference = data.get("theme_preference", "system")
            if preference in {"system", "light", "dark"}:
                self.theme_preference = preference
        except (OSError, ValueError, AttributeError):
            self.theme_preference = "system"

    def _save_app_preferences(self):
        try:
            path = self._app_preferences_config_path()
            temporary_path = f"{path}.tmp"
            with open(temporary_path, "w", encoding="utf-8") as file:
                json.dump({"theme_preference": self.theme_preference}, file, indent=2)
            os.replace(temporary_path, path)
        except OSError as error:
            self._log_operation("guardar_tema_fallido", error=str(error))

    @staticmethod
    def _system_prefers_dark():
        """Read the desktop color mode, with the Windows registry as fallback."""
        hints = QApplication.instance().styleHints() if QApplication.instance() else None
        if hints and hasattr(hints, "colorScheme"):
            scheme = hints.colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return True
            if scheme == Qt.ColorScheme.Light:
                return False

        if sys.platform.startswith("win"):
            try:
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    apps_use_light_theme, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return not bool(apps_use_light_theme)
            except OSError:
                pass
        return False

    def _effective_dark_mode(self):
        if self.theme_preference == "dark":
            return True
        if self.theme_preference == "light":
            return False
        return self._system_prefers_dark()

    def _sync_automatic_theme(self):
        if self.theme_preference == "system":
            self._apply_configured_theme()

    def _apply_configured_theme(self, force=False):
        dark_mode = self._effective_dark_mode()
        if force or dark_mode != self.is_dark_mode:
            self.is_dark_mode = dark_mode
            self.apply_theme()

    def _set_theme_preference(self, preference):
        if preference not in {"system", "light", "dark"}:
            return
        self.theme_preference = preference
        self._save_app_preferences()
        self._apply_configured_theme(force=True)
        self._log_operation("cambiar_tema", preference=preference, dark_mode=self.is_dark_mode)
        labels = {
            "system": "Tema automatico activado",
            "light": "Tema claro activado",
            "dark": "Tema oscuro activado",
        }
        self.statusBar().showMessage(labels[preference], 2000)

    def apply_theme(self):
        qss = get_app_stylesheet(is_dark=self.is_dark_mode)
        self.setStyleSheet(qss)
        self.editor.set_dark_mode(self.is_dark_mode)
        self.teacher_editor.set_dark_mode(self.is_dark_mode)
        self.preview.set_dark_mode(self.is_dark_mode)
        self.teacher_preview.set_dark_mode(self.is_dark_mode)
        labels = {
            "system": "Tema: Auto",
            "light": "Modo Claro",
            "dark": "Modo Oscuro",
        }
        self.theme_btn.setText(labels.get(self.theme_preference, "Tema: Auto"))
        if hasattr(self, "theme_auto_act"):
            self.theme_auto_act.setChecked(self.theme_preference == "system")
            self.theme_light_act.setChecked(self.theme_preference == "light")
            self.theme_dark_act.setChecked(self.theme_preference == "dark")
        self._update_md_toolbar_theme()
        self._update_presentation_toolbar_theme()
        self._update_navigation_theme()
        self._update_tab_theme()
        self._apply_split_editor_state()
        self._apply_preview_visibility()

    def toggle_theme(self):
        self._set_theme_preference("light" if self.is_dark_mode else "dark")

    # ── Presentation Mode ─────────────────────────────────

    def _set_presentation_mode(self, mode, refresh=True, persist=True):
        """Apply the selected preview mode only to the active document tab."""
        if mode not in {"slide", "scroll", "paper"}:
            mode = "slide"

        if refresh:
            self.preview.set_presentation_mode(mode)
            self.teacher_preview.set_presentation_mode(mode)
        else:
            self.preview.presentation_mode = mode
            self.teacher_preview.presentation_mode = mode

        labels = {
            "slide": "Diapositivas",
            "scroll": "Continuo",
            "paper": "Hoja impresa",
        }
        label = labels[mode]
        self.mode_btn.setText(f"Modo: {label}")
        self.mode_label.setText(label)
        self._update_paper_controls_visibility()

        if 0 <= self.current_tab_index < len(self.tabs):
            self.tabs[self.current_tab_index]["presentation_mode"] = mode

        if persist and self.current_filepath:
            prefs = dict(self.file_preferences.get(self._preference_key(self.current_filepath), {}))
            prefs["presentation_mode"] = mode
            self.file_preferences[self._preference_key(self.current_filepath)] = prefs
            self._save_file_preferences()

    def set_presentation_mode(self, mode):
        self._set_presentation_mode(mode)
        labels = {"slide": "diapositivas", "scroll": "continuo", "paper": "hoja impresa"}
        self._log_operation("cambiar_modo_previa", mode=labels.get(mode, mode))
        self.statusBar().showMessage(f"Modo {labels.get(mode, mode).title()}", 2000)
        if mode == "scroll":
            QTimer.singleShot(120, lambda: self._schedule_continuous_preview_centering(
                self._active_markdown_editor()
            ))

    def toggle_presentation_mode(self):
        """Keep the legacy shortcut behavior between slides and continuous."""
        if self.preview.presentation_mode == "slide":
            self.set_presentation_mode("scroll")
        else:
            self.set_presentation_mode("slide")

    def _update_paper_controls_visibility(self):
        visible = self.preview.presentation_mode == "paper"
        self.paper_toolbar.hide()
        if hasattr(self, "page_settings_btn"):
            self.page_settings_btn.setVisible(visible)
        if hasattr(self, "page_settings_action"):
            self.page_settings_action.setVisible(visible)
        if hasattr(self, "toolbar"):
            self.toolbar.updateGeometry()
            self.toolbar.update()
        self.paper_settings_content.setVisible(visible and not self.paper_settings_collapsed)
        self.paper_settings_toggle_btn.setText(
            "Configuracion de hoja impresa +"
            if self.paper_settings_collapsed
            else "Configuracion de hoja impresa -"
        )
        for control in (
            self.paper_size_combo,
            self.paper_orientation_combo,
            self.exact_zoom_input,
            self.paper_header_combo,
            self.paper_footer_combo,
            self.paper_custom_header_input,
            self.paper_header_right_combo,
            self.paper_header_right_input,
            self.paper_footer_left_combo,
            self.paper_footer_left_input,
            self.paper_font_scale_input,
        ):
            control.setVisible(visible)
        if visible:
            self.exact_zoom_input.blockSignals(True)
            self.exact_zoom_input.setValue(max(1, int(round(self.preview.zoom_factor * 100))))
            self.exact_zoom_input.blockSignals(False)
        QTimer.singleShot(0, self._fit_paper_settings_block)

    def show_paper_settings_popup(self):
        """Open paper settings on demand instead of reserving a toolbar row."""
        if self.preview.presentation_mode != "paper":
            self.set_presentation_mode("paper")
        if self.paper_settings_collapsed:
            self.paper_settings_collapsed = False
            self._update_paper_controls_visibility()

        popup = QMenu(self)
        action = QWidgetAction(popup)
        content = self.paper_settings_content
        host_layout = self.paper_toolbar.layout()
        if host_layout is not None:
            host_layout.removeWidget(content)
        content.setParent(popup)
        content.setVisible(True)
        action.setDefaultWidget(content)
        popup.addAction(action)
        popup.setMinimumWidth(min(760, max(420, self.width() - 40)))
        popup.exec(self.page_settings_btn.mapToGlobal(QPoint(0, self.page_settings_btn.height())))
        popup.removeAction(action)
        content.setParent(self.paper_toolbar)
        if host_layout is not None:
            host_layout.addWidget(content)
        content.hide()

    def _fit_paper_settings_block(self):
        """Fit the paper controls to their exact wrapped height without clipping."""
        if not self.paper_toolbar.isVisible():
            return
        if self.paper_settings_collapsed:
            height = self.paper_settings_toggle_btn.sizeHint().height() + 4
        else:
            width = max(1, self.paper_toolbar.width() - 4)
            content_height = self.paper_toolbar_layout.heightForWidth(width)
            content_height = max(FlowToolbar.MIN_TOOLBAR_HEIGHT, content_height)
            self.paper_settings_content.setFixedHeight(content_height)
            height = self.paper_settings_toggle_btn.sizeHint().height() + content_height + 8
        self.paper_toolbar.setMinimumHeight(height)
        self.paper_toolbar.setMaximumHeight(height)
        self.paper_toolbar.updateGeometry()

    def toggle_paper_settings(self):
        self.paper_settings_collapsed = not self.paper_settings_collapsed
        self._update_paper_controls_visibility()
        self.paper_toolbar.updateGeometry()
        self.statusBar().showMessage(
            "Configuracion de hoja oculta"
            if self.paper_settings_collapsed
            else "Configuracion de hoja visible",
            1500,
        )

    def _set_paper_options(self, size, orientation, refresh=True, persist=True):
        if size not in {"letter", "legal", "a4", "a3"}:
            size = "letter"
        if orientation not in {"portrait", "landscape"}:
            orientation = "portrait"
        for preview in (self.preview, self.teacher_preview):
            preview.paper_size = size
            preview.paper_orientation = orientation
        if hasattr(self, "paper_size_combo"):
            self.paper_size_combo.blockSignals(True)
            self.paper_size_combo.setCurrentIndex(max(0, self.paper_size_combo.findData(size)))
            self.paper_size_combo.blockSignals(False)
            self.paper_orientation_combo.blockSignals(True)
            self.paper_orientation_combo.setCurrentIndex(
                max(0, self.paper_orientation_combo.findData(orientation))
            )
            self.paper_orientation_combo.blockSignals(False)
        if 0 <= self.current_tab_index < len(self.tabs):
            self.tabs[self.current_tab_index]["paper_size"] = size
            self.tabs[self.current_tab_index]["paper_orientation"] = orientation
        if refresh and self.preview.presentation_mode == "paper":
            self.update_preview()
        if persist and self.current_filepath:
            self._remember_current_file_preferences(include_visual=True)

    @staticmethod
    def _paper_document_headings(markdown_text):
        """Suggest running text from the first title and subtitle in Markdown."""
        headings = re.findall(r"^\s{0,3}(#{1,2})\s+(.+?)\s*$", markdown_text or "", re.MULTILINE)
        title = ""
        subtitle = ""
        for marker, value in headings:
            cleaned = re.sub(r"\s+#+\s*$", "", value).strip()
            if len(marker) == 1 and not title:
                title = cleaned
            elif len(marker) == 2 and not subtitle:
                subtitle = cleaned
            if title and subtitle:
                break
        if not title and headings:
            title = re.sub(r"\s+#+\s*$", "", headings[0][1]).strip()
        return title, subtitle

    def _set_paper_running_matter(self, header_mode, footer_mode, custom_header, refresh=True, persist=True):
        valid_headers = {"auto_title", "subtitle", "auto_hierarchy", "custom", "none"}
        valid_footers = {"page_of_total", "page", "auto_hierarchy", "none"}
        header_mode = header_mode if header_mode in valid_headers else "auto_title"
        footer_mode = footer_mode if footer_mode in valid_footers else "page_of_total"
        custom_header = (custom_header or "").strip()
        title, subtitle = self._paper_document_headings(self._presentation_markdown_text())
        for preview in (self.preview, self.teacher_preview):
            preview.paper_title = title
            preview.paper_subtitle = subtitle
            preview.paper_header_mode = header_mode
            preview.paper_footer_mode = footer_mode
            preview.paper_custom_header = custom_header
        if hasattr(self, "paper_header_combo"):
            for combo, value in (
                (self.paper_header_combo, header_mode),
                (self.paper_footer_combo, footer_mode),
            ):
                combo.blockSignals(True)
                combo.setCurrentIndex(max(0, combo.findData(value)))
                combo.blockSignals(False)
            self.paper_custom_header_input.setText(custom_header)
            self.paper_custom_header_input.setEnabled(header_mode == "custom")
        if 0 <= self.current_tab_index < len(self.tabs):
            tab = self.tabs[self.current_tab_index]
            tab["paper_header_mode"] = header_mode
            tab["paper_footer_mode"] = footer_mode
            tab["paper_custom_header"] = custom_header
        if refresh and self.preview.presentation_mode == "paper":
            self.update_preview()
        if persist and self.current_filepath:
            self._remember_current_file_preferences(include_visual=True)

    def _paper_running_matter_changed(self):
        self._set_paper_running_matter(
            self.paper_header_combo.currentData() or "auto_title",
            self.paper_footer_combo.currentData() or "page_of_total",
            self.paper_custom_header_input.text(),
        )

    def _set_paper_secondary_matter(self, header_right_mode, header_right_text, footer_left_mode, footer_left_text, refresh=True, persist=True):
        valid_modes = {"title", "subtitle", "auto_hierarchy", "custom", "none"}
        header_right_mode = header_right_mode if header_right_mode in valid_modes else "none"
        footer_left_mode = footer_left_mode if footer_left_mode in valid_modes else "none"
        header_right_text = (header_right_text or "").strip()
        footer_left_text = (footer_left_text or "").strip()
        for preview in (self.preview, self.teacher_preview):
            preview.paper_header_right_mode = header_right_mode
            preview.paper_header_right_text = header_right_text
            preview.paper_footer_left_mode = footer_left_mode
            preview.paper_footer_left_text = footer_left_text
        for combo, value in (
            (self.paper_header_right_combo, header_right_mode),
            (self.paper_footer_left_combo, footer_left_mode),
        ):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)
        self.paper_header_right_input.setText(header_right_text)
        self.paper_footer_left_input.setText(footer_left_text)
        self.paper_header_right_input.setEnabled(header_right_mode == "custom")
        self.paper_footer_left_input.setEnabled(footer_left_mode == "custom")
        if refresh and self.preview.presentation_mode == "paper":
            self.update_preview()
        if persist and self.current_filepath:
            self._remember_current_file_preferences(include_visual=True)

    def _paper_secondary_matter_changed(self):
        self._set_paper_secondary_matter(
            self.paper_header_right_combo.currentData() or "none",
            self.paper_header_right_input.text(),
            self.paper_footer_left_combo.currentData() or "none",
            self.paper_footer_left_input.text(),
        )

    def _set_paper_font_scale(self, percent, refresh=True, persist=True):
        try:
            scale = max(0.5, min(int(percent) / 100.0, 2.0))
        except (TypeError, ValueError):
            return
        for preview in (self.preview, self.teacher_preview):
            preview.paper_font_scale = scale
        self.paper_font_scale_input.blockSignals(True)
        self.paper_font_scale_input.setValue(int(round(scale * 100)))
        self.paper_font_scale_input.blockSignals(False)
        if refresh and self.preview.presentation_mode == "paper":
            self.update_preview()
        if persist and self.current_filepath:
            self._remember_current_file_preferences(include_visual=True)

    def _paper_options_changed(self):
        self._set_paper_options(
            self.paper_size_combo.currentData() or "letter",
            self.paper_orientation_combo.currentData() or "portrait",
        )

    def set_exact_preview_zoom(self, percent):
        if self.preview.presentation_mode != "paper":
            return
        try:
            factor = max(0.01, int(percent) / 100.0)
        except (TypeError, ValueError):
            return
        self.preview.zoom_factor = factor
        self.preview._apply_zoom()
        self.preview.zoom_changed.emit(factor)
        self.zoom_label.setText(f"{int(round(factor * 100))}%")
        self._log_operation("zoom_previa", direction="exact", percent=int(round(factor * 100)))

    def zoom_in(self):
        self.preview.zoom_in()
        QTimer.singleShot(80, lambda: self._schedule_continuous_preview_centering(self.editor))
        pct = int(self.preview.zoom_factor * 100)
        self._log_operation("zoom_previa", direction="in", percent=pct)
        self.zoom_label.setText(f"{pct}%")
        self.statusBar().showMessage(f"Zoom: {pct}%", 1500)

    def zoom_out(self):
        self.preview.zoom_out()
        QTimer.singleShot(80, lambda: self._schedule_continuous_preview_centering(self.editor))
        pct = int(self.preview.zoom_factor * 100)
        self._log_operation("zoom_previa", direction="out", percent=pct)
        self.zoom_label.setText(f"{pct}%")
        self.statusBar().showMessage(f"Zoom: {pct}%", 1500)

    def zoom_reset(self):
        self.preview.reset_zoom()
        QTimer.singleShot(80, lambda: self._schedule_continuous_preview_centering(self.editor))
        self._log_operation("zoom_previa", direction="reset", percent=100)
        self.zoom_label.setText("100%")
        self.statusBar().showMessage("Zoom restablecido (100%)", 1500)

    def _on_preview_zoom_changed(self, target, factor):
        """Persist user zoom separately for the student and teacher preview."""
        try:
            factor = max(0.01, float(factor))
        except (TypeError, ValueError):
            return

        if 0 <= self.current_tab_index < len(self.tabs):
            key = "teacher_preview_zoom" if target == "teacher" else "student_preview_zoom"
            self.tabs[self.current_tab_index][key] = factor

        if self.current_filepath:
            prefs = dict(self.file_preferences.get(self._preference_key(self.current_filepath), {}))
            prefs["student_preview_zoom"] = float(self.preview.zoom_factor)
            prefs["teacher_preview_zoom"] = float(self.teacher_preview.zoom_factor)
            self.file_preferences[self._preference_key(self.current_filepath)] = prefs
            self._save_file_preferences()

        if target == "student":
            self.zoom_label.setText(f"{int(factor * 100)}%")
        editor = self.teacher_editor if target == "teacher" else self.editor
        QTimer.singleShot(80, lambda: self._schedule_continuous_preview_centering(editor))
        self._log_operation("zoom_previa_mouse", target=target, percent=int(factor * 100))

    # ── Font Size (content, not zoom) ─────────────────────

    def _dual_font_shortcuts_active(self):
        return bool(self.is_fullscreen_presentation and self._presentation_teacher_view())

    def _handle_f8_presentation_shortcut(self):
        if self._dual_font_shortcuts_active():
            self.increase_teacher_font_size()
        else:
            self.toggle_borderless()

    def increase_student_font_size(self):
        size = self.preview.increase_font_size()
        if self.presentation_output_window:
            self.presentation_output_window.preview.set_font_size(size)
        if self.dual_control_window:
            self.dual_control_window.student_preview.set_font_size(size)
        self._remember_current_file_preferences(include_visual=True)
        self.statusBar().showMessage(f"Tamano de fuente alumno: {size}px", 1500)

    def decrease_student_font_size(self):
        size = self.preview.decrease_font_size()
        if self.presentation_output_window:
            self.presentation_output_window.preview.set_font_size(size)
        if self.dual_control_window:
            self.dual_control_window.student_preview.set_font_size(size)
        self._remember_current_file_preferences(include_visual=True)
        self.statusBar().showMessage(f"Tamano de fuente alumno: {size}px", 1500)

    # Kept as the public student-size actions used by existing integrations.
    def increase_font_size(self):
        self.increase_student_font_size()

    def decrease_font_size(self):
        self.decrease_student_font_size()

    def increase_teacher_font_size(self):
        if not self._dual_font_shortcuts_active():
            return
        size = self.teacher_preview.increase_font_size()
        if self.teacher_local_presentation_window:
            self.teacher_local_presentation_window.preview.set_font_size(size)
        if self.dual_control_window:
            self.dual_control_window.teacher_preview.set_font_size(size)
        self.statusBar().showMessage(f"Tamano de fuente profesor: {size}px", 1500)

    def decrease_teacher_font_size(self):
        if not self._dual_font_shortcuts_active():
            return
        size = self.teacher_preview.decrease_font_size()
        if self.teacher_local_presentation_window:
            self.teacher_local_presentation_window.preview.set_font_size(size)
        if self.dual_control_window:
            self.dual_control_window.teacher_preview.set_font_size(size)
        self.statusBar().showMessage(f"Tamano de fuente profesor: {size}px", 1500)

    # ── Borderless Mode ───────────────────────────────────

    def _set_borderless_state(self, borderless, persist=True):
        """Apply one per-file frame state to every active preview surface."""
        borderless = bool(borderless)
        for view in (self.preview, self.teacher_preview):
            view.set_borderless(borderless)
        for window in (
            self.presentation_output_window,
            self.teacher_local_presentation_window,
        ):
            if window and hasattr(window, "preview"):
                window.preview.set_borderless(borderless)
        if self.dual_control_window:
            self.dual_control_window.student_preview.set_borderless(borderless)
            self.dual_control_window.teacher_preview.set_borderless(borderless)

        self.borderless_btn.blockSignals(True)
        self.borderless_btn.setChecked(borderless)
        self.borderless_btn.blockSignals(False)
        if 0 <= self.current_tab_index < len(self.tabs):
            self.tabs[self.current_tab_index]["borderless"] = borderless
        if persist:
            self._remember_current_file_preferences(include_visual=True)
        return borderless

    def toggle_borderless(self, checked=None):
        if isinstance(checked, bool):
            is_borderless = checked
        else:
            is_borderless = not self.preview.borderless
        self._set_borderless_state(is_borderless, persist=True)
        self._log_operation("cambiar_marco", borderless=is_borderless)
        mode_text = "sin marco" if is_borderless else "con marco"
        self.statusBar().showMessage(f"Modo presentacion: {mode_text}", 2000)

    # ── Presentation Time Overlay ─────────────────────────

    def _time_overlay_label(self):
        return {
            "clock": "Reloj",
            "stopwatch": "Cronometro",
            "timer": "Temporizador",
        }.get(self.preview.clock_mode, "Reloj")

    def _update_time_overlay_controls(self):
        """Show only the controls needed by the selected time overlay."""
        mode = self.clock_mode_combo.currentData() or "clock"
        is_clock = mode == "clock"
        is_timer = mode == "timer"
        is_running = self.preview.timer_running

        dynamic_controls = (
            (self.clock_seconds_btn, is_clock),
            (self.timer_minutes_input, is_timer),
            (self.timer_start_btn, not is_clock),
            (self.timer_reset_btn, not is_clock),
        )
        for widget, visible in dynamic_controls:
            widget.setVisible(visible and not getattr(self, "compact_header_enabled", False))
        self.timer_start_btn.setText("Pausar" if is_running and not is_clock else "Iniciar")
        self.timer_start_btn.setToolTip(
            "Pausar el " + self._time_overlay_label().lower()
            if is_running and not is_clock
            else "Iniciar el " + self._time_overlay_label().lower()
        )
        self.clock_btn.setText("Mostrar")
        self.time_toolbar.updateGeometry()

    @staticmethod
    def _normalise_time_overlay_target(target):
        return target if target in {"student", "teacher", "both"} else "both"

    def _apply_time_overlay_visibility(self):
        """Apply the chosen time-indicator audience without changing its settings."""
        target = self._normalise_time_overlay_target(self.time_overlay_target)
        self.time_overlay_target = target
        enabled = self.clock_btn.isChecked() or self._presentation_clock_override is not None
        self.preview.set_clock_visible(enabled and target in {"student", "both"})
        self.teacher_preview.set_clock_visible(enabled and target in {"teacher", "both"})
        if self.dual_control_window:
            self.dual_control_window.student_preview.set_clock_visible(enabled and target in {"student", "both"})
            self.dual_control_window.teacher_preview.set_clock_visible(enabled and target in {"teacher", "both"})

    def _set_presentation_clock_override(self, active):
        """Show the clock on both presentation audiences without changing saved preferences."""
        if active:
            if self._presentation_clock_override is None:
                self._presentation_clock_override = self.time_overlay_target
            self.time_overlay_target = "both"
        elif self._presentation_clock_override is not None:
            self.time_overlay_target = self._presentation_clock_override
            self._presentation_clock_override = None
        self._apply_time_overlay_visibility()
        self._sync_time_overlay_to_previews()

    def _update_presentation_power_inhibit(self):
        """Prevent Windows from sleeping while any presentation surface is active."""
        active = bool(
            self.is_fullscreen_presentation
            or self.presentation_output_window
            or self.teacher_local_presentation_window
            or self.dual_control_window
        )
        if active == self._presentation_power_inhibited:
            return
        self._presentation_power_inhibited = active
        if active:
            self._install_presentation_alt_tab_hook()
        else:
            self._uninstall_presentation_alt_tab_hook()
        if os.name != "nt":
            return
        try:
            execution_state = ctypes.windll.kernel32.SetThreadExecutionState
            flags = 0x80000000 | 0x00000001 | 0x00000002 if active else 0x80000000
            result = execution_state(flags)
            if not result:
                LOGGER.warning("No se pudo actualizar la politica de energia de presentacion | active=%s", active)
            else:
                self._log_operation("bloqueo_suspension_presentacion", active=active)
        except Exception:
            LOGGER.exception("Error actualizando la politica de energia de presentacion | active=%s", active)

    def _toggle_current_slide_image(self):
        """Toggle the image overlay for the current student presentation slide."""
        if not self._presentation_power_inhibited:
            return
        target = self._presentation_student_view()
        target.close_image_zoom_if_open(
            lambda was_open: None if was_open else target.open_current_slide_image()
        )
        self._log_operation("alternar_imagen_presentacion_alt_tab")

    def _on_presentation_navigation_key_down(self, direction):
        """Handle a navigation key captured from a wireless presenter."""
        if direction in self._presentation_hold_pressed:
            if self._presentation_hold_opened and direction in {"page_next", "page_prev"}:
                self._adjust_presentation_image_zoom(direction)
            return
        if self._presentation_hold_opened:
            if direction in {"page_next", "page_prev"}:
                self._presentation_hold_pressed.add(direction)
                self._presentation_hold_suppress_release.add(direction)
                self._adjust_presentation_image_zoom(direction)
                self._presentation_image_zoom_hold_direction = direction
                self._presentation_image_zoom_hold_timer.start()
                return
            self._presentation_hold_suppress_release.add(direction)
            self._presentation_hold_opened = False
            self._close_presentation_image_overlays()
            self._log_operation("cerrar_imagen_presentacion_pulsacion")
            return
        self._presentation_hold_pressed.add(direction)
        self._presentation_hold_direction = direction
        self._presentation_hold_long_attempted = False
        # Only the presenter's Tab button is allowed to open an image. All
        # other navigation keys retain their normal tap behavior.
        if direction == "tab_next":
            self._presentation_hold_timer.start()

    def _on_presentation_navigation_key_up(self, direction):
        """Finish a wireless-presenter tap without double-navigating a held key."""
        self._presentation_hold_pressed.discard(direction)
        if direction == self._presentation_image_zoom_hold_direction:
            self._presentation_image_zoom_hold_timer.stop()
            self._presentation_image_zoom_hold_direction = None
        if direction in self._presentation_hold_suppress_release:
            self._presentation_hold_suppress_release.discard(direction)
            return
        if self._presentation_hold_direction != direction:
            return
        self._presentation_hold_timer.stop()
        self._presentation_hold_direction = None
        if not self._presentation_hold_long_attempted:
            if direction in {"next", "page_next", "tab_next"}:
                self.presentation_next_slide()
            else:
                self.presentation_prev_slide()

    def _on_presentation_long_press(self):
        """Open the current slide image after holding a navigation button."""
        direction = self._presentation_hold_direction
        if direction != "tab_next" or direction not in self._presentation_hold_pressed:
            return
        self._presentation_hold_long_attempted = True
        target = self._presentation_student_view()
        # Set this before the asynchronous WebView call so the next presenter
        # press can always be reserved for closing the overlay.
        self._presentation_hold_opened = True

        def remember_opened(opened):
            if opened:
                self._log_operation("abrir_imagen_presentacion_pulsacion_larga")
            else:
                # Do not clear the guard here. The WebView callback can be
                # delayed or return an empty value after the overlay is
                # already visible; the next presenter press must still be
                # reserved for closing it instead of advancing the slide.
                self._log_operation("resultado_apertura_imagen_presentacion", opened=False)

        target.open_current_slide_image(remember_opened)

    def _open_presentation_image_from_presenter_action(self):
        """Open the student image for a long presenter action."""
        if self._presentation_hold_opened:
            return
        self._presentation_hold_timer.stop()
        self._presentation_hold_long_attempted = True
        self._presentation_hold_opened = True
        target = self._presentation_student_view()

        def remember_opened(opened):
            if opened:
                self._log_operation("abrir_imagen_presentacion_accion_larga")
            else:
                self._log_operation("resultado_apertura_imagen_presentacion", opened=False)

        target.open_current_slide_image(remember_opened)

    def _open_presentation_image_from_shortcut(self):
        """Open the active presentation image independently of presenter state."""
        self._presentation_hold_timer.stop()
        self._presentation_hold_long_attempted = True
        self._presentation_hold_opened = True
        target = self._presentation_student_view()

        def remember_opened(opened):
            if opened:
                self._log_operation("abrir_imagen_presentacion_atajo")
            else:
                self._log_operation("resultado_apertura_imagen_presentacion", opened=False)

        target.open_current_slide_image(remember_opened)

    def _adjust_presentation_image_zoom(self, direction):
        target = self._presentation_student_view()
        target.adjust_image_zoom(0.18 if direction == "page_next" else -0.18)

    def _zoom_in_presentation_image_shortcut(self):
        self._adjust_presentation_image_zoom("page_next")
        self._log_operation("zoom_imagen_presentacion", direction="in")

    def _zoom_out_presentation_image_shortcut(self):
        self._adjust_presentation_image_zoom("page_prev")
        self._log_operation("zoom_imagen_presentacion", direction="out")

    def _repeat_presentation_image_zoom(self):
        direction = self._presentation_image_zoom_hold_direction
        if direction in self._presentation_hold_pressed and self._presentation_hold_opened:
            self._adjust_presentation_image_zoom(direction)

    def _close_presentation_image_overlays(self):
        """Close image overlays in every presentation view attached to this session."""
        views = [self._presentation_student_view()]
        if self.presentation_output_window:
            views.append(self.presentation_output_window.preview)
        if self.teacher_local_presentation_window:
            views.append(self.teacher_local_presentation_window.preview)
        if self.dual_control_window:
            views.extend([
                self.dual_control_window.student_preview,
                self.dual_control_window.teacher_preview,
            ])
        seen = set()
        for view in views:
            if view is not None and id(view) not in seen:
                seen.add(id(view))
                view.close_image_zoom_if_open()

    def _install_presentation_alt_tab_hook(self):
        """Temporarily replace Windows Alt+Tab with the presentation image action."""
        if os.name != "nt" or self._presentation_alt_tab_hook:
            return
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.SetWindowsHookExW.argtypes = [
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
            ]
            user32.CallNextHookEx.restype = ctypes.c_long
            user32.CallNextHookEx.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_void_p,
            ]
            user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            kernel32.GetModuleHandleW.restype = ctypes.c_void_p

            class KbdLlHookStruct(ctypes.Structure):
                _fields_ = [
                    ("vkCode", ctypes.c_uint32),
                    ("scanCode", ctypes.c_uint32),
                    ("flags", ctypes.c_uint32),
                    ("time", ctypes.c_uint32),
                    ("dwExtraInfo", ctypes.c_void_p),
                ]

            callback_type = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.POINTER(KbdLlHookStruct),
            )

            def record_hook_event(phase, vk_code, w_param, info):
                """Keep a low-cost audit trail for presenter input callbacks."""
                self._presentation_hook_event_count += 1
                self._presentation_hook_last_event = {
                    "phase": phase,
                    "vk": int(vk_code),
                    "message": int(w_param),
                    "scan": int(getattr(info, "scanCode", 0)) if info else None,
                    "flags": int(getattr(info, "flags", 0)) if info else None,
                    "time": int(getattr(info, "time", 0)) if info else None,
                }
                _write_session_diagnostic(
                    "PRESENTACION_HOOK | phase={0} vk=0x{1:02X} message=0x{2:04X} scan={3} flags={4} count={5}".format(
                        phase, int(vk_code), int(w_param),
                        self._presentation_hook_last_event["scan"],
                        self._presentation_hook_last_event["flags"],
                        self._presentation_hook_event_count,
                    )
                )
                LOGGER.info(
                    "PRESENTACION_HOOK | pid=%s thread=%s phase=%s vk=0x%02X message=0x%04X scan=%s flags=%s count=%s",
                    os.getpid(), threading.get_ident(), phase, int(vk_code), int(w_param),
                    self._presentation_hook_last_event["scan"],
                    self._presentation_hook_last_event["flags"],
                    self._presentation_hook_event_count,
                )

            def keyboard_proc(n_code, w_param, info):
                try:
                    if n_code == 0 and info:
                        vk_code = info.contents.vkCode
                        if w_param in (0x0100, 0x0104):  # WM_KEYDOWN / WM_SYSKEYDOWN
                            record_hook_event("down", vk_code, w_param, info.contents)
                            if vk_code == 0x09 and user32.GetAsyncKeyState(0x12) & 0x8000:
                                self._presentation_alt_tab_tab_release = True
                                self.presentation_alt_tab_requested.emit()
                                return 1
                            # Some presenter firmware changes a held Tab into a
                            # Windows-key press. Treat only that derived event as
                            # the image-opening command.
                            if vk_code in (0x5B, 0x5C) and "tab_next" in self._presentation_hold_pressed:
                                self._presentation_synthetic_key_release.add(vk_code)
                                self._open_presentation_image_from_presenter_action()
                                return 1
                            # Other firmware variants emit Escape/B while holding
                            # PageDown/PageUp. Absorb those derived keys so they
                            # cannot close the presentation or type into it.
                            if vk_code == 0x1B and "page_next" in self._presentation_hold_pressed:
                                self._presentation_synthetic_key_release.add(vk_code)
                                return 1
                            if vk_code == 0x42 and "page_prev" in self._presentation_hold_pressed:
                                self._presentation_synthetic_key_release.add(vk_code)
                                return 1
                            navigation_keys = {
                                0x22: "page_next",  # PageDown
                                0x27: "next",  # Right
                                0x20: "next",  # Space
                                0x0D: "next",  # Enter
                                0x28: "next",  # Down
                                0x09: "tab_next",  # Tab (image-opening button)
                                0x21: "page_prev",  # PageUp
                                0x25: "prev",  # Left
                                0x08: "prev",  # Backspace
                                0x26: "prev",  # Up
                            }
                            direction = navigation_keys.get(vk_code)
                            if direction:
                                LOGGER.info(
                                    "PRESENTACION_INPUT | phase=down vk=0x%02X direction=%s hold=%s opened=%s",
                                    int(vk_code), direction, sorted(self._presentation_hold_pressed),
                                    self._presentation_hold_opened,
                                )
                                self.presentation_navigation_key_down.emit(direction)
                                return 1
                        elif w_param in (0x0101, 0x0105):  # WM_KEYUP / WM_SYSKEYUP
                            record_hook_event("up", vk_code, w_param, info.contents)
                            if vk_code in self._presentation_synthetic_key_release:
                                self._presentation_synthetic_key_release.discard(vk_code)
                                return 1
                            if vk_code == 0x09 and self._presentation_alt_tab_tab_release:
                                self._presentation_alt_tab_tab_release = False
                                return 1
                            navigation_keys = {
                                0x22: "page_next", 0x27: "next", 0x20: "next",
                                0x0D: "next", 0x28: "next", 0x09: "tab_next",
                                0x21: "page_prev",
                                0x25: "prev", 0x08: "prev", 0x26: "prev",
                            }
                            direction = navigation_keys.get(vk_code)
                            if direction:
                                LOGGER.info(
                                    "PRESENTACION_INPUT | phase=up vk=0x%02X direction=%s hold=%s opened=%s",
                                    int(vk_code), direction, sorted(self._presentation_hold_pressed),
                                    self._presentation_hold_opened,
                                )
                                self.presentation_navigation_key_up.emit(direction)
                                return 1
                except Exception as error:
                    self._presentation_hook_error_count += 1
                    self._presentation_hook_last_error = f"{type(error).__name__}: {error}"
                    try:
                        failed_vk = info.contents.vkCode if info else None
                    except Exception:
                        failed_vk = None
                    LOGGER.exception(
                        "Error dentro del callback del hook de presentacion | pid=%s thread=%s vk=%s message=%s",
                        os.getpid(), threading.get_ident(),
                        failed_vk,
                        w_param,
                    )
                return user32.CallNextHookEx(self._presentation_alt_tab_hook or 0, n_code, w_param, info)

            callback = callback_type(keyboard_proc)
            hook = user32.SetWindowsHookExW(
                13, callback, kernel32.GetModuleHandleW(None), 0
            )
            if not hook:
                LOGGER.warning(
                    "No se pudo instalar el hook de Alt+Tab para presentacion | pid=%s last_error=%s",
                    os.getpid(), ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else "no_disponible",
                )
                return
            self._presentation_alt_tab_callback = callback
            self._presentation_alt_tab_user32 = user32
            self._presentation_alt_tab_hook = hook
            def native_handle_value(value):
                try:
                    return int(value.value) if hasattr(value, "value") else int(value)
                except (TypeError, ValueError):
                    return 0
            self._log_operation(
                "alt_tab_bloqueado_presentacion",
                active=True,
                hook_handle=native_handle_value(hook),
                callback_pointer=int(ctypes.cast(callback, ctypes.c_void_p).value or 0),
                module_handle=native_handle_value(kernel32.GetModuleHandleW(None)),
            )
        except Exception:
            LOGGER.exception("Error instalando el hook de Alt+Tab para presentacion")

    def _uninstall_presentation_alt_tab_hook(self):
        """Restore Windows Alt+Tab after presentation mode ends."""
        hook = self._presentation_alt_tab_hook
        if not hook:
            return
        try:
            if self._presentation_alt_tab_user32:
                result = self._presentation_alt_tab_user32.UnhookWindowsHookEx(hook)
                self._log_operation(
                    "hook_presentacion_liberado",
                    hook_handle=(hook.value if hasattr(hook, "value") else hook),
                    result=bool(result),
                    event_count=self._presentation_hook_event_count,
                    error_count=self._presentation_hook_error_count,
                    last_event=self._presentation_hook_last_event,
                )
        except Exception:
            LOGGER.exception("Error liberando el hook de Alt+Tab para presentacion")
        finally:
            self._presentation_hold_timer.stop()
            self._presentation_image_zoom_hold_timer.stop()
            self._presentation_hold_pressed.clear()
            self._presentation_hold_suppress_release.clear()
            self._presentation_hold_direction = None
            self._presentation_hold_long_attempted = False
            self._presentation_hold_opened = False
            self._presentation_image_zoom_hold_direction = None
            self._presentation_alt_tab_tab_release = False
            self._presentation_synthetic_key_release.clear()
            self._presentation_alt_tab_hook = None
            self._presentation_alt_tab_callback = None
            self._presentation_alt_tab_user32 = None
            self._log_operation("alt_tab_bloqueado_presentacion", active=False)

    def _sync_time_overlay_to_previews(self):
        """Copy the active time overlay state to the teacher preview and outputs."""
        source = self.preview
        teacher = self.teacher_preview
        teacher.clock_mode = source.clock_mode
        teacher.clock_show_seconds = source.clock_show_seconds
        teacher.clock_size = source.clock_size
        teacher.clock_position = source.clock_position
        teacher.timer_duration_seconds = source.timer_duration_seconds
        teacher.timer_elapsed_seconds = source.timer_elapsed_seconds
        teacher.timer_running = source.timer_running
        teacher._timer_started_at = source._timer_started_at
        self._apply_time_overlay_visibility()
        teacher.apply_clock_settings()
        self._sync_output_window_style()
        self._sync_teacher_local_window_style()
        if self.dual_control_window:
            self._sync_dual_control_window_style()
            self.dual_control_window.student_preview.apply_clock_settings()
            self.dual_control_window.teacher_preview.apply_clock_settings()

    def change_clock_mode(self):
        mode = self.clock_mode_combo.currentData() or "clock"
        self.preview.set_clock_mode(mode)
        self.clock_btn.setChecked(True)
        self._sync_time_overlay_to_previews()
        self._update_time_overlay_controls()
        self._remember_current_file_preferences(include_visual=True)
        self._log_operation("cambiar_indicador_tiempo", mode=mode)
        self.statusBar().showMessage(f"{self._time_overlay_label()} activado", 1800)

    def toggle_clock(self):
        visible = self.clock_btn.isChecked()
        self._sync_time_overlay_to_previews()
        self._remember_current_file_preferences(include_visual=True)
        self._log_operation("cambiar_indicador_tiempo", visible=visible, mode=self.preview.clock_mode)
        self.statusBar().showMessage(
            f"{self._time_overlay_label()} {'visible' if visible else 'oculto'}", 1500
        )

    def change_time_overlay_target(self):
        target = self._normalise_time_overlay_target(self.clock_target_combo.currentData())
        self.time_overlay_target = target
        self._sync_time_overlay_to_previews()
        self._remember_current_file_preferences(include_visual=True)
        labels = {"student": "alumno", "teacher": "profesor", "both": "ambas presentaciones"}
        self._log_operation("cambiar_destino_indicador_tiempo", target=target)
        self.statusBar().showMessage(
            f"{self._time_overlay_label()} configurado para {labels[target]}", 1800
        )

    def toggle_clock_seconds(self):
        show_seconds = self.clock_seconds_btn.isChecked()
        self.preview.set_clock_show_seconds(show_seconds)
        self._sync_time_overlay_to_previews()
        self._remember_current_file_preferences(include_visual=True)
        self._log_operation("cambiar_reloj_segundos", visible=show_seconds)
        label = "con segundos" if show_seconds else "sin segundos"
        self.statusBar().showMessage(f"Reloj {label}", 1500)

    def change_timer_duration(self, minutes):
        self.preview.set_timer_duration_minutes(minutes)
        self._sync_time_overlay_to_previews()
        self._update_time_overlay_controls()
        self._remember_current_file_preferences(include_visual=True)
        self._log_operation("cambiar_duracion_temporizador", minutes=minutes)

    def toggle_timer_running(self):
        if self.preview.clock_mode == "clock":
            return
        self.preview.toggle_timer_running()
        self._sync_time_overlay_to_previews()
        self._update_time_overlay_controls()
        state = "iniciado" if self.preview.timer_running else "pausado"
        self._log_operation("cambiar_ejecucion_indicador", mode=self.preview.clock_mode, state=state)
        self.statusBar().showMessage(f"{self._time_overlay_label()} {state}", 1500)

    def reset_timer(self):
        if self.preview.clock_mode == "clock":
            return
        self.preview.reset_timer()
        self._sync_time_overlay_to_previews()
        self._update_time_overlay_controls()
        self._log_operation("reiniciar_indicador_tiempo", mode=self.preview.clock_mode)
        self.statusBar().showMessage(f"{self._time_overlay_label()} reiniciado", 1500)

    def increase_clock_size(self):
        size = self.preview.increase_clock_size()
        self.teacher_preview.set_clock_size(size)
        self._sync_output_window_style()
        self._sync_teacher_local_window_style()
        self._remember_current_file_preferences(include_visual=True)
        self.statusBar().showMessage(f"Tamano de {self._time_overlay_label().lower()}: {size}px", 1500)

    def decrease_clock_size(self):
        size = self.preview.decrease_clock_size()
        self.teacher_preview.set_clock_size(size)
        self._sync_output_window_style()
        self._sync_teacher_local_window_style()
        self._remember_current_file_preferences(include_visual=True)
        self.statusBar().showMessage(f"Tamano de {self._time_overlay_label().lower()}: {size}px", 1500)

    def change_clock_position(self):
        position = self.clock_position_combo.currentData()
        self.preview.set_clock_position(position)
        self.teacher_preview.set_clock_position(position)
        self._sync_output_window_style()
        self._sync_teacher_local_window_style()
        self._remember_current_file_preferences(include_visual=True)
        self._log_operation("cambiar_posicion_reloj", position=position)

    def load_student_presentation(self):
        """Load an independent student-facing Markdown source for dual mode."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Elegir presentacion para el alumnado",
            "",
            "Markdown (*.md);;Texto (*.txt);;Todos (*)",
        )
        if not file_path:
            return
        try:
            content, recovered = self._read_with_autosave_offer(file_path, "la presentación del alumno")
            content, _ = ensure_slide_ids(content)
        except Exception as e:
            LOGGER.exception("No se pudo cargar la presentacion del alumnado: %s", file_path)
            QMessageBox.critical(self, "Error", f"No se pudo cargar la presentacion:\n{e}")
            return

        self.presentation_script_path = os.path.abspath(file_path)
        self.presentation_script_content = content
        if self.editor_role == "student" or self.split_editor_enabled:
            self._load_student_editor_source()
        self._sync_current_tab_from_editor()
        if self.teacher_preview_mode != "dual":
            self.teacher_preview_combo.setCurrentIndex(
                max(0, self.teacher_preview_combo.findData("dual"))
            )
        else:
            self.update_preview()
        self.statusBar().showMessage(
            f"Presentacion del alumnado cargada{(' desde backup' if recovered else '')}: {file_path}",
            3000,
        )
        self._log_operation("presentacion_alumnado_cargada", presentation_file=self.presentation_script_path)

    def _presentation_markdown_text(self):
        """Return the optional dual-mode student presentation or the edited document."""
        if self._uses_external_student_presentation():
            return self.presentation_script_content
        return self._student_markdown_text()

    def _uses_external_student_presentation(self):
        return self.teacher_preview_mode == "dual" and bool(self.presentation_script_content)

    def _student_editor_text(self):
        if self._uses_external_student_presentation():
            return self.presentation_script_content
        if 0 <= self.current_tab_index < len(self.tabs):
            return self.tabs[self.current_tab_index].get("content", "")
        return self.editor.toPlainText()

    def _student_editor_path(self):
        if self._uses_external_student_presentation() and self.presentation_script_path:
            return self.presentation_script_path
        return self.current_filepath

    def _load_student_editor_source(self):
        """Load the student source that is currently bound to the student preview."""
        self._set_editor_text_quietly(self._student_editor_text(), self._student_editor_path())

    def _presentation_document_base_path(self):
        if self.teacher_preview_mode == "dual" and self.presentation_script_path:
            return os.path.dirname(os.path.abspath(self.presentation_script_path))
        return self._current_document_base_path()

    def load_teacher_script(self):
        """Load a separate teacher Markdown script for dual preview mode."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar guion del profesor",
            "",
            "Markdown (*.md);;Texto (*.txt);;Todos (*)"
        )
        if not file_path:
            return
        try:
            content, recovered = self._read_with_autosave_offer(file_path, "el guion del profesor")
            content, _ = ensure_slide_ids(content)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo cargar el guion del profesor:\n{e}")
            return

        self.teacher_script_path = os.path.abspath(file_path)
        self.teacher_script_content = content
        self.teacher_editor.set_document_path(self.teacher_script_path)
        self.teacher_editor.blockSignals(True)
        self.teacher_editor.setPlainText(self.teacher_script_content)
        self.teacher_editor.blockSignals(False)
        self.teacher_is_modified = bool(recovered)
        self._sync_current_tab_from_editor()
        self._update_teacher_presentation_button()
        self._apply_split_editor_state()
        if self.teacher_preview_mode == "student":
            self.teacher_preview_combo.setCurrentIndex(max(0, self.teacher_preview_combo.findData("dual")))
        else:
            self.update_preview()
        self.statusBar().showMessage(
            f"Guion del profesor cargado{(' desde backup' if recovered else '')}: {file_path}",
            3000,
        )
        self._log_operation("guion_profesor_cargado", teacher_file=self.teacher_script_path)

    def change_teacher_preview_mode(self):
        """Switch preview between student, teacher, and synchronized dual mode."""
        # Save against the previous source before the mode changes which
        # student document is bound to the upper editor.
        self._sync_current_tab_from_editor()
        self.teacher_preview_mode = self.teacher_preview_combo.currentData() or "student"
        teacher_source_was_loaded = bool(self.teacher_script_content)
        if self.teacher_preview_mode in {"dual", "teacher"} and not self.teacher_script_content:
            self.load_teacher_script()
            if not self.teacher_script_content:
                self.teacher_preview_mode = "student"
                self.teacher_preview_combo.setCurrentIndex(max(0, self.teacher_preview_combo.findData("student")))
                return
        if self.editor_role == "student" or self.split_editor_enabled:
            self._load_student_editor_source()
        if (
            teacher_source_was_loaded
            and self.teacher_preview_mode in {"dual", "teacher"}
            and 0 <= self.current_tab_index < len(self.tabs)
        ):
            # Check a retained teacher source only when entering a
            # teacher-facing mode, never while the tab is simply a student view.
            self.tabs[self.current_tab_index]["teacher_preview_mode"] = self.teacher_preview_mode
            self._check_tab_autosaves(
                self.tabs[self.current_tab_index],
                check_student=False,
                check_teacher=True,
            )
        self._sync_current_tab_from_editor()
        self.update_preview()
        self._update_tab_visual(self.current_tab_index)
        self._log_operation("cambiar_modo_dual", mode=self.teacher_preview_mode)

    def toggle_student_preview_collapsed(self):
        self.dual_student_collapsed = not self.dual_student_collapsed
        if self.dual_student_collapsed and self.dual_teacher_collapsed:
            self.dual_teacher_collapsed = False
        self._sync_current_tab_from_editor()
        self._apply_preview_visibility()

    def toggle_teacher_preview_collapsed(self):
        self.dual_teacher_collapsed = not self.dual_teacher_collapsed
        if self.dual_student_collapsed and self.dual_teacher_collapsed:
            self.dual_student_collapsed = False
        self._sync_current_tab_from_editor()
        self._apply_preview_visibility()

    def adjust_dual_preview_zoom(self, target, delta):
        preview = self.teacher_preview if target == "teacher" else self.preview
        if delta > 0:
            preview.zoom_factor = preview.zoom_factor * 1.1
        else:
            preview.zoom_factor = max(preview.zoom_factor / 1.1, 0.01)
        preview._apply_zoom()
        self._on_preview_zoom_changed(target, preview.zoom_factor)
        self._sync_current_tab_from_editor()
        label = "profesor" if target == "teacher" else "alumno"
        visual_zoom = int(preview.zoom_factor * 100)
        self._log_operation("zoom_previa_dual", target=target, percent=visual_zoom)
        self.statusBar().showMessage(f"Zoom {label}: {visual_zoom}%", 1500)

    def _student_markdown_text(self):
        if self._uses_external_student_presentation():
            return self.presentation_script_content
        if self.editor_role == "student" or self.split_editor_enabled:
            return self.editor.toPlainText()
        if 0 <= self.current_tab_index < len(self.tabs):
            return self.tabs[self.current_tab_index].get("content", "")
        return self.editor.toPlainText()

    def _active_markdown_editor(self):
        if hasattr(self, "teacher_editor") and self.teacher_editor.hasFocus():
            return self.teacher_editor
        if self.editor.hasFocus():
            return self.editor
        last_editor = getattr(self, "_last_active_markdown_editor", None)
        if last_editor in (self.editor, getattr(self, "teacher_editor", None)):
            return last_editor
        return self.editor

    def _replace_editor_text_preserving_view(self, editor, text):
        cursor = editor.textCursor()
        position = cursor.position()
        anchor = cursor.anchor()
        vertical = editor.verticalScrollBar().value()
        horizontal = editor.horizontalScrollBar().value()
        had_focus = editor.hasFocus()

        editor.blockSignals(True)
        editor.setPlainText(text)
        new_cursor = editor.textCursor()
        max_pos = max(0, len(text))
        new_cursor.setPosition(min(anchor, max_pos))
        new_cursor.setPosition(min(position, max_pos), QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(new_cursor)
        editor.verticalScrollBar().setValue(min(vertical, editor.verticalScrollBar().maximum()))
        editor.horizontalScrollBar().setValue(min(horizontal, editor.horizontalScrollBar().maximum()))
        editor.blockSignals(False)

        if had_focus:
            editor.setFocus()

    def _set_editor_text_quietly(self, text, path=None):
        self._loading_tab = True
        self.editor.set_document_path(path)
        self._replace_editor_text_preserving_view(self.editor, text)
        self._loading_tab = False

    def _save_active_editor_content(self):
        if self.editor_role == "teacher" and not self.split_editor_enabled:
            self.teacher_script_content = self.editor.toPlainText()
            self.teacher_is_modified = True
        elif 0 <= self.current_tab_index < len(self.tabs):
            self.tabs[self.current_tab_index]["content"] = self.editor.toPlainText()

    def activate_editor_for(self, role):
        if role == "teacher" and not self.teacher_script_content:
            return

        if self.split_editor_enabled:
            target = self.teacher_editor if role == "teacher" else self.editor
            target.setFocus()
            self.editor_role = role
            self._sync_current_tab_from_editor()
            if self.nav_mode == "slides":
                self.build_slide_outline()
            self.statusBar().showMessage(
                "Editor activo: profesor" if role == "teacher" else "Editor activo: alumno",
                1500
            )
            return

        if role == self.editor_role:
            self.editor.setFocus()
            return

        self._save_active_editor_content()
        self.editor_role = role
        if role == "teacher":
            self._set_editor_text_quietly(self.teacher_script_content, self.teacher_script_path)
            self.statusBar().showMessage("Editor cargado con guion del profesor", 1800)
        else:
            self._load_student_editor_source()
            self.statusBar().showMessage("Editor cargado con guion del alumno", 1800)
        self.editor.setFocus()
        self._sync_current_tab_from_editor()
        if self.nav_mode == "slides":
            self.build_slide_outline()

    def toggle_split_editor(self):
        if not self.teacher_script_content:
            self.load_teacher_script()
            if not self.teacher_script_content:
                return

        self._save_active_editor_content()
        self.split_editor_enabled = not self.split_editor_enabled
        if self.split_editor_enabled:
            self._load_student_editor_source()
            self.teacher_editor.set_document_path(self.teacher_script_path)
            self.teacher_editor.blockSignals(True)
            self.teacher_editor.setPlainText(self.teacher_script_content)
            self.teacher_editor.blockSignals(False)
            self.teacher_editor.show()
            self.editor_splitter.setSizes([1, 1])
            self.editor_role = "student"
        else:
            self.teacher_script_content = self.teacher_editor.toPlainText()
            self.teacher_is_modified = True
            self.teacher_editor.hide()
            self.editor_role = "student"
            self._load_student_editor_source()
        self._apply_split_editor_state()
        self._sync_current_tab_from_editor()
        self.update_preview()
        self._log_operation("cambiar_editor_dual", enabled=self.split_editor_enabled)

    def _apply_split_editor_state(self):
        if not hasattr(self, "teacher_editor"):
            return
        self.teacher_editor.setVisible(self.split_editor_enabled and bool(self.teacher_script_content))
        self.split_editor_btn.setText("Editor Simple" if self.split_editor_enabled else "Editor Dual")
        self.split_editor_btn.setObjectName("primaryBtn" if self.split_editor_enabled else "")
        self.split_editor_btn.style().unpolish(self.split_editor_btn)
        self.split_editor_btn.style().polish(self.split_editor_btn)
        if hasattr(self, "save_act"):
            dual_save = self.split_editor_enabled and bool(self.teacher_script_content)
            self.save_act.setText("Guardar Alumno" if dual_save else "Guardar")
            self.save_act.setStatusTip(
                "Guardar solamente el documento del alumno" if dual_save else "Guardar el documento actual"
            )
            self.save_teacher_act.setVisible(dual_save)

    def _update_teacher_presentation_button(self):
        if not hasattr(self, "present_teacher_btn"):
            return
        active = self.teacher_local_presentation_window is not None
        self.present_teacher_btn.setText("Cerrar Profesor" if active else "Presentar Profesor")
        self.present_teacher_btn.setEnabled(not bool(self.dual_control_window))
        if hasattr(self, "present_dual_btn"):
            dual_active = self.dual_control_window is not None
            self.present_dual_btn.setText("Cerrar Dual" if dual_active else "Presentar Dual")
            self.present_dual_btn.setEnabled(True)

    def _update_teacher_marker_controls(self):
        if not hasattr(self, "teacher_marker_btn"):
            return
        self.teacher_marker_btn.blockSignals(True)
        self.teacher_marker_btn.setChecked(bool(self.teacher_marker_visible))
        self.teacher_marker_btn.blockSignals(False)
        self.teacher_marker_text_input.blockSignals(True)
        self.teacher_marker_text_input.setText(self.teacher_marker_text or "PROFESOR")
        self.teacher_marker_text_input.blockSignals(False)
        self._apply_teacher_marker_settings()

    def _apply_teacher_marker_settings(self):
        if hasattr(self, "preview"):
            self.preview.set_teacher_marker(False, "PROFESOR")
        if hasattr(self, "teacher_preview"):
            self.teacher_preview.set_teacher_marker(self.teacher_marker_visible, self.teacher_marker_text)
        if self.teacher_local_presentation_window:
            self.teacher_local_presentation_window.preview.set_teacher_marker(
                self.teacher_marker_visible,
                self.teacher_marker_text
            )
        if self.dual_control_window:
            self.dual_control_window.teacher_preview.set_teacher_marker(
                self.teacher_marker_visible,
                self.teacher_marker_text,
            )

    def toggle_teacher_marker(self):
        self.teacher_marker_visible = self.teacher_marker_btn.isChecked()
        self._apply_teacher_marker_settings()
        self._sync_current_tab_from_editor()
        state = "activada" if self.teacher_marker_visible else "desactivada"
        self._log_operation("cambiar_marca_profesor", visible=self.teacher_marker_visible)
        self.statusBar().showMessage(f"Marca visual del profesor {state}", 1800)

    def change_teacher_marker_text(self):
        text = self.teacher_marker_text_input.text().strip() or "PROFESOR"
        self.teacher_marker_text = text
        self.teacher_marker_text_input.setText(text)
        self._apply_teacher_marker_settings()
        self._sync_current_tab_from_editor()
        self._log_operation("cambiar_texto_marca_profesor", text=self.teacher_marker_text)
        self.statusBar().showMessage(f"Marca profesor: {text}", 1800)

    def toggle_teacher_local_presentation(self):
        if self.dual_control_window:
            return
        if self.teacher_local_presentation_window:
            self.teacher_local_presentation_window.close()
            self.teacher_local_presentation_window = None
            self.present_teacher_locally = False
            self._update_presentation_power_inhibit()
            if not self.is_fullscreen_presentation:
                self._set_presentation_clock_override(False)
            self._update_teacher_presentation_button()
            self._log_operation("presentacion_profesor_cerrada")
            return

        if not self.teacher_script_content:
            self.load_teacher_script()
            if not self.teacher_script_content:
                self._update_teacher_presentation_button()
                return

        # When the professor screen is opened after the student presentation,
        # both presentations must begin at slide 1.  The dual-navigation rule
        # will advance the professor manually until its first paired slide.
        if self.is_fullscreen_presentation or self.presentation_output_window:
            teacher_slide = 0
        else:
            student_slide = self.editor.current_slide_index()
            teacher_slide = self._matching_teacher_slide_index(student_slide)
        self.teacher_local_presentation_window = PresentationOutputWindow(self)
        self._bind_teacher_output_shortcuts(self.teacher_local_presentation_window)
        self.teacher_local_presentation_window.setWindowTitle("NUMA Presentacion - Profesor")
        self._sync_teacher_local_window_style()
        self.teacher_local_presentation_window.preview.restore_slide_after_next_load(teacher_slide)
        self.teacher_local_presentation_window.preview.set_content(
            self.teacher_script_content,
            base_path=self._teacher_document_base_path()
        )
        self.teacher_local_presentation_window.setGeometry((self.screen() or QApplication.primaryScreen()).geometry())
        self.teacher_local_presentation_window.showFullScreen()
        self.present_teacher_locally = True
        self._set_presentation_clock_override(True)
        self._update_presentation_power_inhibit()
        self._sync_current_tab_from_editor()
        self._update_teacher_presentation_button()
        self._log_operation("presentacion_profesor_iniciada", teacher_slide=teacher_slide + 1)

    def toggle_dual_control_presentation(self):
        """Open a teacher-side dual console plus a student-only projector view."""
        if self.dual_control_window:
            self.exit_presentation_mode()
            return
        if self.is_fullscreen_presentation:
            QMessageBox.information(
                self,
                "Presentacion activa",
                "Cierra la presentacion actual antes de iniciar el control dual.",
            )
            return
        if not self.teacher_script_content:
            self.load_teacher_script()
            if not self.teacher_script_content:
                return

        target_screen = self._presentation_target_screen()
        if not target_screen:
            QMessageBox.warning(
                self,
                "Se requiere segunda pantalla",
                "El modo Presentar Dual necesita una segunda pantalla para proyectar al alumnado.",
            )
            return
        self.preview.get_current_slide(self._start_dual_control_presentation)

    def _start_dual_control_presentation(self, slide_index):
        try:
            student_slide = max(0, int(slide_index))
        except (TypeError, ValueError):
            student_slide = self.editor.current_slide_index()

        target_screen = self._presentation_target_screen()
        if not target_screen:
            return

        teacher_slide, teacher_waiting, paired_teacher_slide = self._initial_teacher_presentation_slide(student_slide)
        self.is_fullscreen_presentation = True
        self._presentation_next_press_at = 0.0
        self._presentation_prev_press_at = 0.0
        self._set_presentation_clock_override(True)
        self._update_presentation_power_inhibit()
        self.present_teacher_locally = False
        self._enable_presentation_shortcuts()

        self.dual_control_window = DualPresentationControlWindow(self)
        self._bind_dual_control_shortcuts(self.dual_control_window)
        self._sync_dual_control_window_style()
        control = self.dual_control_window
        control.student_preview.student_sync_label_activated.connect(self.open_teacher_slide_from_student_label)
        control.student_preview.interactive_state_changed.connect(self._mirror_dual_student_interaction)
        control.student_preview.restore_slide_after_next_load(student_slide)
        control.student_preview.set_content(
            self._presentation_markdown_text(),
            base_path=self._presentation_document_base_path(),
        )
        control.teacher_preview.restore_slide_after_next_load(teacher_slide)
        control.teacher_preview.set_content(
            self.teacher_script_content,
            base_path=self._teacher_document_base_path(),
        )

        self.presentation_output_window = PresentationOutputWindow(self)
        # The external output renders the student Markdown at its own full
        # screen dimensions. It is passive, and receives only the interactive
        # state from the upper student presentation in the dual console.
        self.presentation_output_window.set_cast_mode(False)
        self.presentation_output_window.preview.set_interaction_enabled(False)
        self._sync_output_window_style()
        self.presentation_output_window.preview.set_student_sync_label(False, {})
        self.presentation_output_window.preview.restore_slide_after_next_load(student_slide)
        self.presentation_output_window.preview.set_content(
            self._presentation_markdown_text(),
            base_path=self._presentation_document_base_path(),
        )
        self.presentation_output_window.setGeometry(target_screen.geometry())
        self.presentation_output_window.showFullScreen()

        primary_screen = self.screen() or QApplication.primaryScreen()
        self.dual_control_window.setGeometry(primary_screen.geometry())
        self.dual_control_window.showFullScreen()
        self._dual_projection_state = None
        self._dual_projection_sync_pending = False
        self._dual_projection_sync_timer.start()
        self._update_teacher_presentation_button()
        self._log_operation(
            "presentacion_dual_iniciada",
            student_slide=student_slide + 1,
            teacher_slide=teacher_slide + 1,
            waiting_for_teacher=teacher_waiting,
        )
        message = "Control dual activo: alumno arriba, profesor abajo; proyeccion solo para alumno."
        if teacher_waiting:
            message += f" Profesor avanza manualmente hasta el slide {paired_teacher_slide + 1}."
        self.statusBar().showMessage(message, 5000)

    def sync_teacher_preview_manual(self):
        """Pair the current student slide with the current teacher slide."""
        if not self.teacher_script_content:
            self.load_teacher_script()
            if not self.teacher_script_content:
                return

        self.preview.get_current_slide(self._start_manual_teacher_sync)

    def _start_manual_teacher_sync(self, student_slide_index):
        try:
            student_slide_index = max(0, int(student_slide_index))
        except (TypeError, ValueError):
            student_slide_index = self.editor.current_slide_index()
        self.teacher_preview.get_current_slide(
            lambda teacher_slide_index: self._finish_manual_teacher_sync(
                teacher_slide_index,
                student_slide_index,
            )
        )

    def _finish_manual_teacher_sync(self, teacher_slide_index, student_slide_index=None):
        try:
            teacher_slide_index = max(0, int(teacher_slide_index))
        except (TypeError, ValueError):
            teacher_slide_index = 0

        if student_slide_index is None:
            student_slide_index = self.editor.current_slide_index() if self.editor_role == "student" or self.split_editor_enabled else 0
        sync_id = create_sync_id()
        student_text, student_changed = set_slide_sync_id(
            self._presentation_markdown_text(),
            student_slide_index,
            sync_id
        )
        teacher_text, teacher_changed = set_slide_sync_id(
            self.teacher_script_content,
            teacher_slide_index,
            sync_id
        )

        if student_changed:
            if self.teacher_preview_mode == "dual" and self.presentation_script_content:
                self.presentation_script_content = student_text
                if self.editor_role == "student" or self.split_editor_enabled:
                    self._replace_editor_text_preserving_view(self.editor, student_text)
                if 0 <= self.current_tab_index < len(self.tabs):
                    self.tabs[self.current_tab_index]["presentation_script_content"] = student_text
            else:
                if self.editor_role == "student" or self.split_editor_enabled:
                    self._replace_editor_text_preserving_view(self.editor, student_text)
                if 0 <= self.current_tab_index < len(self.tabs):
                    self.tabs[self.current_tab_index]["content"] = student_text
                self.is_modified = True

        if teacher_changed:
            self.teacher_script_content = teacher_text
            if self.editor_role == "teacher" and not self.split_editor_enabled:
                self._replace_editor_text_preserving_view(self.editor, teacher_text)
            else:
                self._replace_editor_text_preserving_view(self.teacher_editor, teacher_text)
            self.teacher_is_modified = True

        self._sync_current_tab_from_editor()
        verified_teacher_slide = self._synced_teacher_slide_for_student(student_slide_index)
        sync_verified = verified_teacher_slide == teacher_slide_index
        if sync_verified:
            # A successful link should immediately expose its label so the
            # user can verify the pair from the student preview.
            self.student_sync_label_visible = True
            self.student_sync_label_btn.setChecked(True)
        self.teacher_preview.restore_slide_after_next_load(teacher_slide_index)
        self.update_preview(target_slide=student_slide_index)
        self.statusBar().showMessage(
            (
                f"Sincronizacion confirmada: alumno {student_slide_index + 1} "
                f"-> profesor {teacher_slide_index + 1}"
                if sync_verified
                else "No se pudo confirmar la sincronizacion del slide"
            ),
            3500
        )
        self._log_operation(
            "sincronizacion_manual_aplicada",
            student_slide=student_slide_index + 1,
            teacher_slide=teacher_slide_index + 1,
            changed_student=student_changed,
            changed_teacher=teacher_changed,
            verified=sync_verified,
        )

    def clear_dual_sync(self):
        """Remove all explicit student/teacher slide-pairing markers."""
        if not self.teacher_script_content:
            self.statusBar().showMessage("Carga primero un guion del profesor para borrar sincronizaciones", 2500)
            return

        reply = QMessageBox.question(
            self,
            "Desvincular documento",
            "Se eliminaran todos los vinculos de sincronizacion entre alumno y profesor. "
            "Podras crear nuevos vinculos despues.\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        second_reply = QMessageBox.question(
            self,
            "Confirmar desvinculacion total",
            "Esta accion quitara todos los vinculos del documento del alumno y del guion del profesor. "
            "La operacion no se puede deshacer automaticamente.\n\n¿Confirmar desvincular documento?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if second_reply != QMessageBox.Yes:
            return

        student_text, student_changed = clear_slide_sync_ids(self._presentation_markdown_text())
        teacher_text, teacher_changed = clear_slide_sync_ids(self.teacher_script_content)
        if not student_changed and not teacher_changed:
            self.statusBar().showMessage("No hay sincronizaciones que borrar", 2000)
            return

        if self._uses_external_student_presentation():
            self.presentation_script_content = student_text
        elif 0 <= self.current_tab_index < len(self.tabs):
            self.tabs[self.current_tab_index]["content"] = student_text
            self.is_modified = self.is_modified or student_changed

        if self.editor_role == "student" or self.split_editor_enabled:
            self._replace_editor_text_preserving_view(self.editor, student_text)

        self.teacher_script_content = teacher_text
        self.teacher_is_modified = self.teacher_is_modified or teacher_changed
        if self.editor_role == "teacher" and not self.split_editor_enabled:
            self._replace_editor_text_preserving_view(self.editor, teacher_text)
        else:
            self._replace_editor_text_preserving_view(self.teacher_editor, teacher_text)

        self._sync_current_tab_from_editor()
        self.update_preview()
        self.statusBar().showMessage("Sincronizaciones eliminadas. Puedes crear nuevas parejas de slides.", 3000)
        self._log_operation(
            "sincronizaciones_eliminadas",
            changed_student=student_changed,
            changed_teacher=teacher_changed,
        )

    def clear_current_slide_sync(self):
        """Remove only the explicit pairing for the current student slide."""
        if not self.teacher_script_content:
            self.statusBar().showMessage(
                "Carga primero un guion del profesor para desvincular un slide",
                2500,
            )
            return

        self.preview.get_current_slide(self._finish_clear_current_slide_sync)

    def _finish_clear_current_slide_sync(self, student_slide_index):
        try:
            student_slide_index = max(0, int(student_slide_index))
        except (TypeError, ValueError):
            student_slide_index = self.editor.current_slide_index()

        student_metadata = get_slide_metadata(self._presentation_markdown_text())
        if not (0 <= student_slide_index < len(student_metadata)):
            self.statusBar().showMessage("No se encontro el slide actual del alumno", 2500)
            return

        sync_id = student_metadata[student_slide_index].get("sync_id")
        if not sync_id:
            self.statusBar().showMessage("El slide actual no tiene un vinculo", 2500)
            return

        teacher_metadata = get_slide_metadata(self.teacher_script_content)
        teacher_slide_index = next(
            (
                item["index"]
                for item in teacher_metadata
                if item.get("sync_id") == sync_id
            ),
            None,
        )
        student_text, student_changed = clear_slide_sync_id(
            self._presentation_markdown_text(),
            student_slide_index,
            sync_id,
        )
        teacher_text, teacher_changed = (self.teacher_script_content, False)
        if teacher_slide_index is not None:
            teacher_text, teacher_changed = clear_slide_sync_id(
                self.teacher_script_content,
                teacher_slide_index,
                sync_id,
            )

        if not student_changed and not teacher_changed:
            self.statusBar().showMessage("No se pudo desvincular el slide actual", 2500)
            return

        reply = QMessageBox.question(
            self,
            "Desvincular slide",
            f"Se quitara el vinculo del slide {student_slide_index + 1} del alumno"
            + (
                f" con el slide {teacher_slide_index + 1} del profesor."
                if teacher_slide_index is not None
                else "."
            )
            + "\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        if self._uses_external_student_presentation():
            self.presentation_script_content = student_text
        elif 0 <= self.current_tab_index < len(self.tabs):
            self.tabs[self.current_tab_index]["content"] = student_text
            self.is_modified = self.is_modified or student_changed

        if self.editor_role == "student" or self.split_editor_enabled:
            self._replace_editor_text_preserving_view(self.editor, student_text)

        self.teacher_script_content = teacher_text
        self.teacher_is_modified = self.teacher_is_modified or teacher_changed
        if not self.split_editor_enabled and self.editor_role == "teacher":
            self._replace_editor_text_preserving_view(self.editor, teacher_text)
        else:
            self._replace_editor_text_preserving_view(self.teacher_editor, teacher_text)

        self._sync_current_tab_from_editor()
        self.update_preview(target_slide=student_slide_index)
        teacher_message = (
            f" y profesor {teacher_slide_index + 1}"
            if teacher_slide_index is not None
            else ""
        )
        self.statusBar().showMessage(
            f"Slide de alumno {student_slide_index + 1}{teacher_message} desvinculado",
            3000,
        )
        self._log_operation(
            "desvincular_slide",
            student_slide=student_slide_index + 1,
            teacher_slide=(teacher_slide_index + 1) if teacher_slide_index is not None else None,
            sync_id=sync_id,
            changed_student=student_changed,
            changed_teacher=teacher_changed,
        )

    def _student_sync_label_map(self):
        """Map student slide indexes to the explicitly linked teacher slide numbers."""
        student_meta = get_slide_metadata(self._presentation_markdown_text())
        teacher_meta = get_slide_metadata(self.teacher_script_content)
        teacher_by_sync_id = {
            item.get("sync_id"): item["index"] + 1
            for item in teacher_meta
            if item.get("sync_id")
        }
        return {
            item["index"]: teacher_by_sync_id[item["sync_id"]]
            for item in student_meta
            if item.get("sync_id") in teacher_by_sync_id
        }

    def _apply_student_sync_label(self):
        self.preview.set_student_sync_label(
            self.student_sync_label_visible,
            self._student_sync_label_map(),
        )
        if self.dual_control_window:
            self.dual_control_window.student_preview.set_student_sync_label(
                self.student_sync_label_visible,
                self._student_sync_label_map(),
            )

    def open_teacher_slide_from_student_label(self, teacher_slide_number):
        """Open the teacher slide named by the student's sync label."""
        if not self.teacher_script_content:
            return
        try:
            teacher_slide_index = max(0, int(teacher_slide_number) - 1)
        except (TypeError, ValueError):
            return

        teacher_lines = self.teacher_script_content.splitlines()
        slide_start_line = self._rendered_slide_start_line(
            teacher_lines,
            teacher_slide_index,
        )
        if slide_start_line is None:
            return

        self.activate_editor_for("teacher")
        # Set the role before moving the cursor so the cursor-position signal
        # cannot briefly navigate the student preview back to the old slide.
        self.editor_role = "teacher"
        editor = self.teacher_editor if self.split_editor_enabled else self.editor
        block = editor.document().findBlockByNumber(slide_start_line)
        if block.isValid():
            editor.setTextCursor(QTextCursor(block))
            editor.centerCursor()
            self._last_active_markdown_editor = editor
            editor.setFocus()
        self.teacher_preview.goto_slide(teacher_slide_index)
        if self.nav_mode == "slides":
            self.build_slide_outline()
            self._highlight_outline_slide(teacher_slide_index)
        self.statusBar().showMessage(
            f"Profesor: slide {teacher_slide_index + 1}",
            2000,
        )
        self._log_operation(
            "abrir_slide_profesor_desde_etiqueta",
            teacher_slide=teacher_slide_index + 1,
        )

    @staticmethod
    def _rendered_slide_start_line(lines, target_slide_index):
        """Return the first visible source line of a rendered slide."""
        current_slide = 0
        section_start = 0
        for line_index in range(len(lines) + 1):
            at_end = line_index == len(lines)
            line = "" if at_end else lines[line_index]
            if not at_end and line.strip() != "---":
                continue

            section = "\n".join(lines[section_start:line_index])
            visible = re.sub(
                r"<!--\s*numa-(?:slide|sync)-id:\s*[^>]*-->",
                "",
                section,
            )
            if visible.strip():
                if current_slide == target_slide_index:
                    for source_line in range(section_start, line_index):
                        candidate = lines[source_line].strip()
                        if candidate and not re.match(
                            r"<!--\s*numa-(?:slide|sync)-id:\s*[^>]*-->$",
                            candidate,
                        ):
                            return source_line
                    return section_start
                current_slide += 1
            section_start = line_index + 1

        return None

    def toggle_student_sync_label(self):
        self.student_sync_label_visible = self.student_sync_label_btn.isChecked()
        self._apply_student_sync_label()
        self._remember_current_file_preferences(include_visual=True)
        self._sync_current_tab_from_editor()
        self._log_operation(
            "alternar_etiqueta_sincronizacion_alumno",
            visible=self.student_sync_label_visible,
        )
        self.statusBar().showMessage(
            "Etiqueta de vinculo del profesor visible"
            if self.student_sync_label_visible
            else "Etiqueta de vinculo del profesor oculta",
            1800,
        )

    def _save_teacher_script_if_possible(self, show_error=False):
        if not self.teacher_script_path:
            self._log_operation("guion_profesor_no_guardado", reason="ruta_no_definida")
            if show_error:
                QMessageBox.warning(self, "Guion profesor no guardado", "No hay ruta definida para el guion del profesor.")
            return False
        try:
            with open(self.teacher_script_path, "w", encoding="utf-8") as f:
                f.write(self.teacher_script_content)
            # A normal save supersedes any recovery copy created before it.
            self._remove_autosave(self.teacher_script_path)
            self.teacher_is_modified = False
            if 0 <= self.current_tab_index < len(self.tabs):
                self.tabs[self.current_tab_index]["teacher_modified"] = False
                self.tabs[self.current_tab_index]["teacher_script_content"] = self.teacher_script_content
                self.tabs[self.current_tab_index]["teacher_script_path"] = self.teacher_script_path
            return True
        except Exception as e:
            LOGGER.exception("No se pudo guardar el guion del profesor: %s", self.teacher_script_path)
            self._log_operation("guion_profesor_no_guardado", path=self.teacher_script_path, error=type(e).__name__)
            if show_error:
                QMessageBox.warning(
                    self,
                    "Guion profesor no guardado",
                    f"No se pudo guardar el guion del profesor:\n{e}"
                )
            return False

    def _teacher_document_base_path(self):
        if self.teacher_script_path:
            return os.path.dirname(os.path.abspath(self.teacher_script_path))
        return self._current_document_base_path()

    def _matching_teacher_slide_index(self, student_slide_index):
        """Map the current student slide to the related teacher slide."""
        student_meta = get_slide_metadata(self._presentation_markdown_text())
        teacher_meta = get_slide_metadata(self.teacher_script_content)
        if not teacher_meta:
            return 0
        if not student_meta or not (0 <= student_slide_index < len(student_meta)):
            return min(max(0, student_slide_index), len(teacher_meta) - 1)

        student = student_meta[student_slide_index]
        sync_id = student.get("sync_id")
        if sync_id:
            for slide in teacher_meta:
                if slide.get("sync_id") == sync_id:
                    return slide["index"]

        student_key = student.get("key")
        if student_key:
            for slide in teacher_meta:
                if slide.get("key") == student_key:
                    return slide["index"]

        return min(max(0, student_slide_index), len(teacher_meta) - 1)

    def _synced_teacher_slide_for_student(self, student_slide_index):
        """Return the teacher slide explicitly paired by numa-sync-id, or None."""
        student_meta = get_slide_metadata(self._presentation_markdown_text())
        teacher_meta = get_slide_metadata(self.teacher_script_content)
        if not student_meta or not teacher_meta or not (0 <= student_slide_index < len(student_meta)):
            return None
        sync_id = student_meta[student_slide_index].get("sync_id")
        if not sync_id:
            return None
        for slide in teacher_meta:
            if slide.get("sync_id") == sync_id:
                return slide["index"]
        return None

    def _sync_teacher_preview_to_student_slide(self, student_slide_index):
        if not self.teacher_script_content or self.teacher_preview_mode not in {"dual", "teacher"}:
            return
        teacher_slide = self._matching_teacher_slide_index(student_slide_index)
        self.teacher_preview.restore_slide_after_next_load(teacher_slide)
        self.teacher_preview.goto_slide(teacher_slide)

    def _apply_preview_visibility(self):
        has_teacher = bool(self.teacher_script_content)
        show_student = self.teacher_preview_mode in {"student", "dual"} or not has_teacher
        show_teacher = has_teacher and self.teacher_preview_mode in {"teacher", "dual"}
        if self.teacher_preview_mode == "dual":
            show_student = show_student and not self.dual_student_collapsed
            show_teacher = show_teacher and not self.dual_teacher_collapsed
            if not show_student and not show_teacher:
                show_student = True
        self.preview.setVisible(show_student)
        self.teacher_preview.setVisible(show_teacher)
        dual_ready = has_teacher and self.teacher_preview_mode == "dual"
        self.student_collapse_btn.setEnabled(dual_ready)
        self.teacher_collapse_btn.setEnabled(dual_ready)
        self.student_zoom_out_btn.setEnabled(show_student)
        self.student_zoom_in_btn.setEnabled(show_student)
        self.teacher_zoom_out_btn.setEnabled(show_teacher)
        self.teacher_zoom_in_btn.setEnabled(show_teacher)
        self.teacher_marker_btn.setEnabled(has_teacher)
        self.teacher_marker_text_input.setEnabled(has_teacher)
        self._update_teacher_presentation_button()
        self.student_collapse_btn.setText("Alumno +" if self.dual_student_collapsed else "Alumno -")
        self.teacher_collapse_btn.setText("Profesor +" if self.dual_teacher_collapsed else "Profesor -")
        self.student_collapse_btn.setObjectName("hiddenPreviewBtn" if self.dual_student_collapsed else "")
        self.teacher_collapse_btn.setObjectName("hiddenPreviewBtn" if self.dual_teacher_collapsed else "")
        for button in (self.student_collapse_btn, self.teacher_collapse_btn):
            button.style().unpolish(button)
            button.style().polish(button)

    def update_preview(self, target_slide=None, sync_teacher=True, teacher_target_slide=None):
        self._sync_preview_output_aspect_ratio()
        # A plain refresh (typing, formatting or visual configuration) must
        # retain both previews where they already are.  Only callers that pass
        # a target slide are deliberately navigating a presentation.
        if target_slide is not None:
            self.preview.restore_slide_after_next_load(target_slide)
            self._update_preview_slide_label(target_slide)
            if sync_teacher:
                self._sync_teacher_preview_to_student_slide(target_slide)
        keep_editor_focus = self.editor.hasFocus() and not self.is_fullscreen_presentation
        if keep_editor_focus:
            self._restore_editor_focus_pending = True
        self._apply_preview_visibility()
        student_text = self._presentation_markdown_text()
        student_base_path = self._presentation_document_base_path()
        if self.preview.presentation_mode == "paper":
            title, subtitle = self._paper_document_headings(student_text)
            self.preview.paper_title = title
            self.preview.paper_subtitle = subtitle
        self.preview.set_content(student_text, base_path=student_base_path)
        self._apply_student_sync_label()
        self.preview.set_teacher_marker(False, "PROFESOR")
        if self.presentation_output_window:
            self._sync_output_window_style()
            if target_slide is not None:
                self.presentation_output_window.preview.restore_slide_after_next_load(target_slide)
            self.presentation_output_window.preview.set_content(
                student_text,
                base_path=student_base_path
            )
            if self.teacher_local_presentation_window and self.teacher_script_content:
                self._sync_teacher_local_window_style()
                teacher_slide = (
                    teacher_target_slide
                    if teacher_target_slide is not None
                    else self._matching_teacher_slide_index(target_slide or 0)
                )
                self.teacher_local_presentation_window.preview.restore_slide_after_next_load(teacher_slide)
                self.teacher_local_presentation_window.preview.set_content(
                    self.teacher_script_content,
                    base_path=self._teacher_document_base_path()
                )
        # Do not rebuild the dual console from editor/preview refreshes. Its
        # state changes only through its presentation controls and is mirrored
        # from there to the secondary display.
        if self.teacher_script_content:
            self.teacher_preview.presentation_mode = self.preview.presentation_mode
            self.teacher_preview.borderless = self.preview.borderless
            self.teacher_preview.set_output_aspect_ratio(self.preview.output_width, self.preview.output_height)
            if teacher_target_slide is not None:
                self.teacher_preview.restore_slide_after_next_load(teacher_target_slide)
            self.teacher_preview.set_content(
                self.teacher_script_content,
                base_path=self._teacher_document_base_path()
            )
            self.teacher_preview.set_teacher_marker(self.teacher_marker_visible, self.teacher_marker_text)
        if keep_editor_focus:
            QTimer.singleShot(0, self._restore_editor_focus)
            QTimer.singleShot(60, self._restore_editor_focus)

    def _current_document_base_path(self):
        """Return the folder used to resolve relative media links in preview/PDF."""
        if self.current_filepath:
            return os.path.dirname(os.path.abspath(self.current_filepath))
        return os.getcwd()

    def _restore_editor_focus(self):
        """Keep typing uninterrupted while the live preview refreshes."""
        if self._restore_editor_focus_pending and not self.is_fullscreen_presentation:
            self.editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def _restore_editor_focus_after_preview_load(self, ok):
        if ok:
            self._restore_editor_focus()
        self._restore_editor_focus_pending = False

    def _sync_preview_output_aspect_ratio(self):
        """Match the preview canvas to the current output screen aspect ratio."""
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            self.preview.set_output_aspect_ratio(16, 9)
            return

        geometry = screen.geometry()
        self.preview.set_output_aspect_ratio(geometry.width(), geometry.height())

    # ── Fullscreen Presentation ───────────────────────────

    def toggle_fullscreen_presentation(self):
        if self.is_fullscreen_presentation:
            self._log_operation("solicitar_salida_presentacion")
            self.exit_presentation_mode()
        else:
            # The main Present button always starts the student-only output.
            # Teacher and dual outputs have dedicated buttons.
            if self.teacher_local_presentation_window:
                self.teacher_local_presentation_window.close()
                self.teacher_local_presentation_window = None
            self.present_teacher_locally = False
            self._update_presentation_power_inhibit()
            self._update_teacher_presentation_button()
            self._presentation_saved_preview_mode = self.teacher_preview_mode
            self._presentation_student_only_active = True
            if self.teacher_preview_mode != "student":
                self.teacher_preview_mode = "student"
                self.teacher_preview_combo.blockSignals(True)
                self.teacher_preview_combo.setCurrentIndex(
                    max(0, self.teacher_preview_combo.findData("student"))
                )
                self.teacher_preview_combo.blockSignals(False)
                self._apply_preview_visibility()
            self._log_operation("solicitar_presentacion")
            self.preview.get_current_slide(self._start_presentation_from_preview)

    def _start_presentation_from_preview(self, slide_index):
        """Start safely even if WebEngine has not returned its slide state yet."""
        try:
            start_slide = max(0, int(slide_index))
        except (TypeError, ValueError):
            start_slide = self.editor.current_slide_index()
            LOGGER.warning(
                "La vista previa no devolvio un slide valido al presentar; se usa el cursor: %s",
                start_slide,
            )
        self.enter_presentation_mode(start_slide)

    def handle_presentation_escape(self):
        """Close image zoom first; only exit presentation when no zoom is open."""
        if not self.is_fullscreen_presentation and not self.teacher_local_presentation_window and not self.dual_control_window:
            return

        self._log_operation("tecla_escape_presentacion")

        if self.dual_control_window:
            # Student is the focused, upper presentation in the dual console.
            # Close its image overlay before considering any presentation exit.
            self.dual_control_window.student_preview.close_image_zoom_if_open(
                self._after_dual_student_escape_check
            )
            return
        else:
            zoom_target = self.teacher_local_presentation_window.preview if self.teacher_local_presentation_window else self.preview
        zoom_target.close_image_zoom_if_open(self._after_presentation_escape_check)

    def _after_dual_student_escape_check(self, zoom_was_open):
        if zoom_was_open:
            return
        if not self.dual_control_window:
            return
        # A teacher image can also be open in the lower pane. Only after both
        # overlays are closed does Esc continue with the normal dual behavior.
        self.dual_control_window.teacher_preview.close_image_zoom_if_open(
            self._after_presentation_escape_check
        )

    def _after_presentation_escape_check(self, zoom_was_open):
        if zoom_was_open:
            return
        if self.dual_control_window:
            self.dual_control_window.close()
            self.dual_control_window = None
            self._dual_projection_sync_timer.stop()
            self._dual_projection_state = None
            self._dual_projection_sync_pending = False
            self._update_teacher_presentation_button()
            self.statusBar().showMessage("Consola dual cerrada; la proyeccion del alumno sigue activa", 2500)
            return
        if self.teacher_local_presentation_window:
            self.teacher_local_presentation_window.close()
            self.teacher_local_presentation_window = None
            self.present_teacher_locally = False
            self._update_presentation_power_inhibit()
            if not self.is_fullscreen_presentation:
                self._set_presentation_clock_override(False)
            self._sync_current_tab_from_editor()
            self._update_teacher_presentation_button()
            self.statusBar().showMessage("Presentacion del profesor cerrada", 2000)
            return
        if not zoom_was_open:
            self.exit_presentation_mode()

    def enter_presentation_mode(self, start_slide=0):
        try:
            start_slide = max(0, int(start_slide))
        except (TypeError, ValueError):
            start_slide = self.editor.current_slide_index()
        self._remember_current_file_preferences(slide_index=start_slide)
        self.is_fullscreen_presentation = True
        self._presentation_next_press_at = 0.0
        self._presentation_prev_press_at = 0.0
        self._set_presentation_clock_override(True)
        self._update_presentation_power_inhibit()
        self._enable_presentation_shortcuts()
        target_screen = self._presentation_target_screen()
        screen_count = len(QApplication.screens())
        self._log_operation(
            "presentacion_iniciada",
            start_slide=start_slide + 1,
            output_screen=bool(target_screen),
            screen_count=screen_count,
            teacher_local=self.present_teacher_locally,
        )
        if target_screen:
            self.presentation_output_window = PresentationOutputWindow(self)
            self._bind_student_output_shortcuts(self.presentation_output_window)
            self._sync_output_window_style()
            self.presentation_output_window.preview.restore_slide_after_next_load(start_slide)
            self.presentation_output_window.preview.set_content(
                self._presentation_markdown_text(),
                base_path=self._presentation_document_base_path()
            )
            self.presentation_output_window.setGeometry(target_screen.geometry())
            self.presentation_output_window.showFullScreen()
            self.statusBar().showMessage("Presentacion enviada a la segunda pantalla", 2500)
            teacher_slide = None
            teacher_waiting = False
            self.preview.restore_slide_after_next_load(start_slide)
            self.update_preview(
                target_slide=start_slide,
                sync_teacher=True,
                teacher_target_slide=None,
            )
            return

        self.preview.set_preview_canvas(False)
        self.teacher_controls_widget.hide()
        self.teacher_preview.hide()
        self.preview.show()
        self.time_toolbar.hide()
        self.paper_toolbar.hide()
        self.shortcut_toolbar.hide()
        self.md_toolbar.hide()
        self.presentation_toolbar.hide()
        self.tab_bar.hide()
        self.nav_container.hide()
        self.editor_container.hide()
        self.toolbar.hide()
        self.statusBar().hide()
        self.central_widget.layout().setContentsMargins(0, 0, 0, 0)
        self.showFullScreen()
        self.preview.setFocus()
        self.preview.restore_slide_after_next_load(start_slide)
        self.update_preview(target_slide=start_slide)

    def exit_presentation_mode(self):
        if not self.is_fullscreen_presentation:
            return
        self._log_operation("presentacion_finalizada")
        self._capture_current_slide_preference()
        mobile_pointer_views = [self.preview]
        if self.presentation_output_window:
            mobile_pointer_views.append(self.presentation_output_window.preview)
        if self.dual_control_window:
            mobile_pointer_views.extend([
                self.dual_control_window.student_preview,
                self.dual_control_window.teacher_preview,
            ])
        for pointer_view in mobile_pointer_views:
            pointer_view.set_mobile_pointer(0.5, 0.5, False)
        self.is_fullscreen_presentation = False
        self._presentation_next_press_at = 0.0
        self._presentation_prev_press_at = 0.0
        if self._presentation_student_only_active:
            saved_preview_mode = self._presentation_saved_preview_mode or "student"
            self._presentation_saved_preview_mode = None
            self._presentation_student_only_active = False
            self.teacher_preview_mode = saved_preview_mode
            self.teacher_preview_combo.blockSignals(True)
            self.teacher_preview_combo.setCurrentIndex(
                max(0, self.teacher_preview_combo.findData(saved_preview_mode))
            )
            self.teacher_preview_combo.blockSignals(False)
        self._set_presentation_clock_override(False)
        self._disable_presentation_shortcuts()
        if self.presentation_output_window:
            self.presentation_output_window.close()
            self.presentation_output_window = None
            if self.teacher_local_presentation_window:
                self.teacher_local_presentation_window.close()
                self.teacher_local_presentation_window = None
            if self.dual_control_window:
                self.dual_control_window.close()
                self.dual_control_window = None
                self._dual_projection_sync_timer.stop()
                self._dual_projection_state = None
                self._dual_projection_sync_pending = False
            self.present_teacher_locally = False
            self._update_presentation_power_inhibit()
            self._sync_current_tab_from_editor()
            self._update_teacher_presentation_button()
            self.update_preview()
            return
        self.preview.set_preview_canvas(True)
        self.teacher_controls_widget.hide()
        self._apply_preview_visibility()
        self.time_toolbar.show()
        self._update_paper_controls_visibility()
        self.shortcut_toolbar.setVisible(not self.shortcut_settings_collapsed)
        if hasattr(self, "shortcuts_toolbar_direct_btn"):
            self.shortcuts_toolbar_direct_btn.setChecked(not self.shortcut_settings_collapsed)
        self.md_toolbar.setVisible(self.md_toolbar_visible)
        self.presentation_toolbar.setVisible(self.presentation_toolbar_visible)
        self.image_toolbar.setVisible(self.image_toolbar_visible)
        self.links_toolbar.setVisible(self.links_toolbar_visible)
        self.tab_bar.show()
        self.nav_container.show()
        self.editor_container.show()
        self.toolbar.show()
        self.statusBar().show()
        self.central_widget.layout().setContentsMargins(12, 12, 12, 12)
        self.showNormal()
        self._update_presentation_power_inhibit()
        self.editor.setFocus()
        self.update_preview()

    # ── Status Updates ────────────────────────────────────

    def _on_text_changed(self):
        if self._loading_tab:
            return
        if self.editor_role == "teacher" and not self.split_editor_enabled:
            self.teacher_script_content = self.editor.toPlainText()
            self.teacher_is_modified = True
            if 0 <= self.current_tab_index < len(self.tabs):
                self.tabs[self.current_tab_index]["teacher_script_content"] = self.teacher_script_content
                self.tabs[self.current_tab_index]["teacher_modified"] = self.teacher_is_modified
            self._sync_current_tab_from_editor()
            self.update_preview()
            return
        self.is_modified = True
        self._sync_current_tab_from_editor()
        self._update_title()
        if self.nav_mode == "slides":
            self.build_slide_outline()
        self.update_preview()

    def _on_teacher_editor_text_changed(self):
        if self._loading_tab:
            return
        self.teacher_script_content = self.teacher_editor.toPlainText()
        self.teacher_is_modified = True
        if 0 <= self.current_tab_index < len(self.tabs):
            self.tabs[self.current_tab_index]["teacher_script_content"] = self.teacher_script_content
            self.tabs[self.current_tab_index]["teacher_modified"] = self.teacher_is_modified
        self._sync_current_tab_from_editor()
        self.update_preview()

    def _on_teacher_editor_scroll_to_slide(self, slide_index):
        if self._loading_tab:
            return
        self.editor_role = "teacher"
        self.teacher_preview.goto_slide(slide_index)
        if self.nav_mode == "slides":
            if getattr(self, "_outline_current_role", None) != "teacher":
                self.build_slide_outline()
            else:
                self._highlight_outline_slide(slide_index)

    def _on_cursor_changed(self, line, col, editor=None):
        self.pos_label.setText(f"Ln {line}, Col {col}")
        if self._loading_tab:
            return
        self._schedule_continuous_preview_centering(editor)

    def _schedule_continuous_preview_centering(self, editor=None):
        """Follow the active editor cursor in continuous and paper previews."""
        editor = editor or self.sender()
        if editor not in (self.editor, self.teacher_editor):
            return

        is_teacher_editor = (
            editor is self.teacher_editor
            or (editor is self.editor and self.editor_role == "teacher" and not self.split_editor_enabled)
        )
        preview = self.teacher_preview if is_teacher_editor else self.preview
        if preview.presentation_mode not in {"scroll", "paper"} or not preview.isVisible():
            return

        self._continuous_preview_request = (editor, preview)
        if self._continuous_preview_sync_scheduled:
            return
        self._continuous_preview_sync_scheduled = True
        QTimer.singleShot(70, self._apply_continuous_preview_centering)

    def _apply_continuous_preview_centering(self):
        self._continuous_preview_sync_scheduled = False
        request = self._continuous_preview_request
        self._continuous_preview_request = None
        if not request:
            return

        editor, preview = request
        if preview.presentation_mode not in {"scroll", "paper"} or not preview.isVisible():
            return
        cursor_line = editor.textCursor().blockNumber()
        context = self._editor_cursor_context(editor)

        image_context = self._editor_cursor_image(editor)
        if image_context:
            target, occurrence = image_context
            preview.center_on_image(target, occurrence)
            return

        if preview.presentation_mode == "paper":
            # A table of contents repeats headings and link labels. Scope the
            # search to the Markdown section selected by the cursor so the
            # printed preview follows the real content, not its TOC entry.
            preview.center_on_paper_cursor(
                context,
                editor.current_slide_index() if hasattr(editor, "current_slide_index") else 0,
            )
            return

        def center_by_editor_progress(found):
            # Ignore stale async lookups after the user moved the cursor.
            if found or editor.textCursor().blockNumber() != cursor_line:
                return
            editor_scrollbar = editor.verticalScrollBar()
            editor_maximum = editor_scrollbar.maximum()
            if editor_maximum > 0:
                progress = editor_scrollbar.value() / editor_maximum
            else:
                progress = cursor_line / max(1, editor.blockCount() - 1)
            preview.center_on_progress(progress)

        if context:
            preview.center_on_text(context, center_by_editor_progress)
        else:
            center_by_editor_progress(False)

    def _center_active_cursor_after_preview_load(self, preview, ok):
        """Reapply cursor centering after a continuous preview finishes loading."""
        if not ok:
            return

        def schedule_if_active():
            editor = self._active_markdown_editor()
            is_teacher_editor = (
                editor is self.teacher_editor
                or (editor is self.editor and self.editor_role == "teacher" and not self.split_editor_enabled)
            )
            active_preview = self.teacher_preview if is_teacher_editor else self.preview
            if active_preview is preview:
                self._schedule_continuous_preview_centering(editor)

        # setHtml/loadFinished can arrive before the editor/tab restoration
        # sequence completes. Delay slightly so it uses the final cursor.
        QTimer.singleShot(120, schedule_if_active)

    @staticmethod
    def _editor_cursor_image(editor):
        """Locate an image on the cursor line or in its caption paragraph."""
        text = editor.toPlainText()
        lines = text.splitlines(keepends=True)
        if not lines:
            return None
        line = min(editor.textCursor().blockNumber(), len(lines) - 1)
        first = line
        last = line
        while first > 0 and lines[first - 1].strip():
            first -= 1
        while last + 1 < len(lines) and lines[last + 1].strip():
            last += 1
        start = sum(map(len, lines[:first]))
        end = sum(map(len, lines[:last + 1]))
        cursor_start = sum(map(len, lines[:line]))
        matches = list(_iter_markdown_image_links(text))
        candidates = [(i, item) for i, item in enumerate(matches)
                      if start <= item[0] < end]
        if not candidates:
            return None
        index, image = min(candidates, key=lambda pair: abs(pair[1][0] - cursor_start))
        target = image[3]
        occurrence = sum(1 for item in matches[:index] if item[3] == target)
        return target, occurrence

    @staticmethod
    def _editor_cursor_context(editor):
        """Return nearby visible Markdown text suitable for locating the preview."""
        lines = editor.toPlainText().splitlines()
        if not lines:
            return ""
        current = min(max(0, editor.textCursor().blockNumber()), len(lines) - 1)
        positions = [current]
        positions.extend(range(current - 1, max(-1, current - 5), -1))
        positions.extend(range(current + 1, min(len(lines), current + 5)))

        for index in positions:
            candidate = lines[index].strip()
            if not candidate or candidate == "---" or candidate.startswith("<!-- numa-"):
                continue
            candidate = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", candidate)
            candidate = re.sub(r"^[#>*+\-\d.\s]+", "", candidate)
            candidate = re.sub(r"[*_`~]", "", candidate).strip()
            if candidate:
                return candidate[:240]
        return ""

    def _on_word_count_changed(self, count):
        if hasattr(self, "words_label"):
            self.words_label.setText(f"{count} palabras")

    def _refresh_word_count(self):
        if not hasattr(self, "words_label"):
            return
        try:
            text = self._active_markdown_editor().toPlainText().strip()
        except Exception:
            text = ""
        words = len(text.split()) if text else 0
        self.words_label.setText(f"{words} palabras")

    def _on_preview_paper_page_changed(self, page_index, total_pages):
        if getattr(self.preview, "presentation_mode", "slide") != "paper":
            return
        total = max(1, int(total_pages or 1))
        page_number = max(1, min(int(page_index or 0) + 1, total))
        if hasattr(self, "preview_slide_label"):
            self.preview_slide_label.setText(f"Hoja {page_number}/{total}")
        if hasattr(self, "preview_slide_counter_label"):
            self.preview_slide_counter_label.setText(f"Hoja {page_number} / {total}")
        if hasattr(self, "quick_prev_slide_btn"):
            self.quick_prev_slide_btn.setToolTip("Ir a la hoja anterior")
        if hasattr(self, "quick_next_slide_btn"):
            self.quick_next_slide_btn.setToolTip("Pasar a la siguiente hoja")

    def _update_preview_slide_label(self, slide_index=None):
        if not hasattr(self, "preview_slide_label"):
            return
        if getattr(self.preview, "presentation_mode", "slide") == "paper":
            if hasattr(self, "quick_prev_slide_btn"):
                self.quick_prev_slide_btn.setToolTip("Ir a la hoja anterior")
            if hasattr(self, "quick_next_slide_btn"):
                self.quick_next_slide_btn.setToolTip("Pasar a la siguiente hoja")
            self.preview.get_paper_page_state()
            return
        if hasattr(self, "quick_prev_slide_btn"):
            self.quick_prev_slide_btn.setToolTip("Ir a la diapositiva anterior")
        if hasattr(self, "quick_next_slide_btn"):
            self.quick_next_slide_btn.setToolTip("Pasar a la siguiente diapositiva")
        if slide_index is None:
            slide_index = self.editor.current_slide_index()
        try:
            slide_index = int(slide_index)
        except (TypeError, ValueError):
            slide_index = self.editor.current_slide_index()
        total = self._slide_count()
        slide_number = max(1, min(slide_index + 1, total))
        self.preview_slide_label.setText(f"Slide {slide_number}/{total}")
        if hasattr(self, "preview_slide_counter_label"):
            self.preview_slide_counter_label.setText(f"Diapositiva {slide_number} / {total}")

    def _on_scroll_to_slide(self, slide_index):
        """Navigate preview to the slide matching the editor cursor position."""
        if self._loading_tab:
            return
        self.editor_role = "student"
        self.preview.goto_slide(slide_index)
        self._sync_output_window_to_slide(slide_index)
        self._sync_teacher_preview_to_student_slide(slide_index)
        self._remember_current_file_preferences(slide_index=slide_index)
        self._update_preview_slide_label(slide_index)
        if self.nav_mode == "slides":
            if getattr(self, "_outline_current_role", None) != "student":
                self.build_slide_outline()
            else:
                self._highlight_outline_slide(slide_index)

    def _update_title(self):
        name = os.path.basename(self.current_filepath) if self.current_filepath else "Sin titulo"
        mod = "*" if self.is_modified else ""
        self.setWindowTitle(f"{mod}{name} - NUMA Deck Presentations")
        self._update_quick_file_buttons()

    def _update_quick_file_buttons(self):
        """Keep the direct save button synchronized with the active document."""
        button = getattr(self, "save_quick_btn", None)
        if button is None:
            return
        dirty = bool(self.is_modified)
        button.setProperty("dirty", dirty)
        button.setToolTip(
            "Guardar cambios pendientes (Ctrl+S)"
            if dirty else "Guardar el documento activo (Ctrl+S)"
        )
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    # ── About ─────────────────────────────────────────────

    def show_about(self):
        dlg = AboutDialog(self, is_dark=self.is_dark_mode)
        dlg.exec()

    # ── Recent Files ──────────────────────────────────────

    def _shortcut_preferences_path(self):
        return os.path.join(os.path.expanduser("~"), ".numa_deck_shortcuts.json")

    def _load_shortcut_preferences(self):
        """Load global shortcut bindings while preserving new defaults."""
        self.shortcut_bindings = {
            action_id: default
            for action_id, description, default, callback, scope in self.SHORTCUT_DEFINITIONS
        }
        try:
            path = self._shortcut_preferences_path()
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                return
            valid_ids = set(self.shortcut_bindings)
            for action_id, sequence in data.items():
                if action_id in valid_ids and isinstance(sequence, str):
                    self.shortcut_bindings[action_id] = sequence
        except Exception:
            LOGGER.exception("No se pudieron cargar los atajos personalizados")

    def _save_shortcut_preferences(self):
        """Persist shortcut bindings atomically in the user profile."""
        try:
            path = self._shortcut_preferences_path()
            temporary_path = f"{path}.tmp"
            with open(temporary_path, "w", encoding="utf-8") as file:
                json.dump(self.shortcut_bindings, file, ensure_ascii=False, indent=2)
            os.replace(temporary_path, path)
        except Exception as error:
            self._log_operation("guardar_atajos_fallido", error=str(error))

    def _preferences_config_path(self):
        return os.path.join(os.path.expanduser("~"), ".numa_deck_file_preferences.json")

    def _session_config_path(self):
        return os.path.join(os.path.expanduser("~"), ".numa_deck_session.json")

    def _preference_key(self, file_path):
        return os.path.normcase(os.path.abspath(file_path)) if file_path else None

    def _load_file_preferences(self):
        """Load per-file presentation preferences."""
        try:
            config_path = self._preferences_config_path()
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.file_preferences = data
        except Exception:
            self.file_preferences = {}

    def _save_file_preferences(self):
        """Save per-file presentation preferences."""
        try:
            path = self._preferences_config_path()
            temporary_path = f"{path}.tmp"
            with open(temporary_path, "w", encoding="utf-8") as f:
                json.dump(self.file_preferences, f, ensure_ascii=False, indent=2)
            os.replace(temporary_path, path)
        except Exception as error:
            self._log_operation("guardar_preferencias_fallido", error=str(error))

    def _remember_open_file_visual_preferences(self):
        """Persist visual state for every open file without touching its text."""
        self._sync_current_tab_from_editor()
        for tab in self.tabs:
            file_path = tab.get("path")
            key = self._preference_key(file_path)
            if not key:
                continue

            prefs = dict(self.file_preferences.get(key, {}))
            prefs.update({
                "borderless": bool(tab.get("borderless", False)),
                "font_size": int(tab.get("font_size", 24) or 24),
                "presentation_mode": tab.get("presentation_mode", "slide"),
                "student_preview_zoom": float(tab.get("student_preview_zoom", 1.0) or 1.0),
                "teacher_preview_zoom": float(tab.get("teacher_preview_zoom", 1.0) or 1.0),
                "clock_visible": bool(tab.get("clock_visible", False)),
                "time_overlay_target": tab.get("time_overlay_target", "both"),
                "clock_mode": tab.get("clock_mode", "clock"),
                "clock_show_seconds": bool(tab.get("clock_show_seconds", False)),
                "clock_size": int(tab.get("clock_size", 22) or 22),
                "clock_position": tab.get("clock_position", "top-right"),
                "timer_duration_minutes": int(tab.get("timer_duration_minutes", 5) or 5),
                "paper_size": tab.get("paper_size", "letter"),
                "paper_orientation": tab.get("paper_orientation", "portrait"),
                "paper_header_mode": tab.get("paper_header_mode", "auto_title"),
                "paper_footer_mode": tab.get("paper_footer_mode", "page_of_total"),
                "paper_custom_header": tab.get("paper_custom_header", ""),
                "paper_header_right_mode": tab.get("paper_header_right_mode", "none"),
                "paper_header_right_text": tab.get("paper_header_right_text", ""),
                "paper_footer_left_mode": tab.get("paper_footer_left_mode", "none"),
                "paper_footer_left_text": tab.get("paper_footer_left_text", ""),
                "paper_font_scale": float(tab.get("paper_font_scale", 1.0) or 1.0),
                "student_sync_label_visible": bool(tab.get("student_sync_label_visible", False)),
            })
            self.file_preferences[key] = prefs
        self._save_file_preferences()

    def _restore_tabs_session(self):
        """Restore document tabs left open in the previous session."""
        try:
            path = self._session_config_path()
            if not os.path.exists(path):
                return False
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False

        tabs = data.get("tabs", []) if isinstance(data, dict) else []
        if not tabs:
            return False

        restored = []
        for tab in tabs:
            file_path = tab.get("path")
            content = tab.get("content", "")
            modified = bool(tab.get("modified", False))
            presentation_path = tab.get("presentation_script_path")
            presentation_content = tab.get("presentation_script_content", "")
            teacher_path = tab.get("teacher_script_path")
            teacher_content = tab.get("teacher_script_content", "")
            teacher_mode = tab.get("teacher_preview_mode", "student")
            dual_student_collapsed = bool(tab.get("dual_student_collapsed", False))
            dual_teacher_collapsed = bool(tab.get("dual_teacher_collapsed", False))
            student_preview_zoom = float(tab.get("student_preview_zoom", 1.0) or 1.0)
            teacher_preview_zoom = float(tab.get("teacher_preview_zoom", 1.0) or 1.0)
            present_teacher_locally = bool(tab.get("present_teacher_locally", False))
            split_editor_enabled = bool(tab.get("split_editor_enabled", False))
            editor_role = tab.get("editor_role", "student")
            teacher_modified = bool(tab.get("teacher_modified", False))
            teacher_marker_visible = bool(tab.get("teacher_marker_visible", True))
            teacher_marker_text = (tab.get("teacher_marker_text", "PROFESOR") or "PROFESOR").strip() or "PROFESOR"
            student_sync_label_visible = bool(tab.get("student_sync_label_visible", False))
            presentation_mode = tab.get("presentation_mode", "slide")
            clock_visible = bool(tab.get("clock_visible", False))
            time_overlay_target = self._normalise_time_overlay_target(
                tab.get("time_overlay_target", "both")
            )
            clock_mode = tab.get("clock_mode", "clock")
            if clock_mode not in {"clock", "stopwatch", "timer"}:
                clock_mode = "clock"
            try:
                timer_duration_minutes = max(1, min(int(tab.get("timer_duration_minutes", 5)), 24 * 60))
            except (TypeError, ValueError):
                timer_duration_minutes = 5
            if presentation_mode not in {"slide", "scroll", "paper"}:
                presentation_mode = "slide"
            if file_path and os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    content, _ = ensure_slide_ids(content)
                    modified = False
                except Exception:
                    pass
            elif content:
                content, _ = ensure_slide_ids(content)
            if presentation_path and os.path.exists(presentation_path):
                try:
                    with open(presentation_path, "r", encoding="utf-8") as f:
                        presentation_content = f.read()
                    presentation_content, _ = ensure_slide_ids(presentation_content)
                except Exception:
                    presentation_content = presentation_content or ""
            if teacher_path and os.path.exists(teacher_path) and not teacher_modified:
                try:
                    with open(teacher_path, "r", encoding="utf-8") as f:
                        teacher_content = f.read()
                    teacher_content, _ = ensure_slide_ids(teacher_content)
                except Exception:
                    teacher_content = teacher_content or ""
            if teacher_mode not in {"student", "dual", "teacher"}:
                teacher_mode = "student"
            visual_state = tab.get("visual_state", {})
            if not isinstance(visual_state, dict):
                visual_state = {}
            restored.append((
                file_path,
                content,
                modified,
                presentation_path,
                presentation_content,
                teacher_path,
                teacher_content,
                teacher_mode,
                dual_student_collapsed,
                dual_teacher_collapsed,
                student_preview_zoom,
                teacher_preview_zoom,
                present_teacher_locally,
                split_editor_enabled,
                editor_role,
                teacher_modified,
                teacher_marker_visible,
                teacher_marker_text,
                student_sync_label_visible,
                presentation_mode,
                clock_visible,
                time_overlay_target,
                clock_mode,
                timer_duration_minutes,
                visual_state,
            ))

        if not restored:
            return False

        for (
            file_path,
            content,
            modified,
            presentation_path,
            presentation_content,
            teacher_path,
            teacher_content,
            teacher_mode,
            dual_student_collapsed,
            dual_teacher_collapsed,
            student_preview_zoom,
            teacher_preview_zoom,
            present_teacher_locally,
            split_editor_enabled,
            editor_role,
            teacher_modified,
            teacher_marker_visible,
            teacher_marker_text,
            student_sync_label_visible,
            presentation_mode,
            clock_visible,
            time_overlay_target,
            clock_mode,
            timer_duration_minutes,
            visual_state,
        ) in restored:
            index = self._create_tab(file_path, content, modified=modified, switch=False)
            self.tabs[index]["presentation_script_path"] = presentation_path
            self.tabs[index]["presentation_script_content"] = presentation_content
            self.tabs[index]["teacher_script_path"] = teacher_path
            self.tabs[index]["teacher_script_content"] = teacher_content
            self.tabs[index]["teacher_preview_mode"] = teacher_mode if teacher_content else "student"
            self.tabs[index]["dual_student_collapsed"] = dual_student_collapsed
            self.tabs[index]["dual_teacher_collapsed"] = dual_teacher_collapsed
            self.tabs[index]["student_preview_zoom"] = student_preview_zoom
            self.tabs[index]["teacher_preview_zoom"] = teacher_preview_zoom
            self.tabs[index]["present_teacher_locally"] = present_teacher_locally
            self.tabs[index]["split_editor_enabled"] = split_editor_enabled
            self.tabs[index]["editor_role"] = editor_role if editor_role in {"student", "teacher"} else "student"
            self.tabs[index]["teacher_modified"] = teacher_modified
            self.tabs[index]["teacher_marker_visible"] = teacher_marker_visible
            self.tabs[index]["teacher_marker_text"] = teacher_marker_text
            self.tabs[index]["student_sync_label_visible"] = student_sync_label_visible
            self.tabs[index]["presentation_mode"] = presentation_mode
            self.tabs[index]["clock_visible"] = clock_visible
            self.tabs[index]["time_overlay_target"] = time_overlay_target
            self.tabs[index]["clock_mode"] = clock_mode
            self.tabs[index]["timer_duration_minutes"] = timer_duration_minutes
            if visual_state:
                self.tabs[index].update(visual_state)
                self.tabs[index]["visual_state_saved"] = True

        index = data.get("active_index", 0) if isinstance(data, dict) else 0
        try:
            index = max(0, min(int(index), len(self.tabs) - 1))
        except (TypeError, ValueError):
            index = 0
        self.tab_bar.setCurrentIndex(index)
        self._load_tab(index)
        return True

    def _save_tabs_session(self):
        """Persist the open tabs for the next application launch."""
        self._sync_current_tab_from_editor()
        tabs = []
        for tab in self.tabs:
            tabs.append({
                "path": tab.get("path"),
                "content": tab.get("content", ""),
                "modified": bool(tab.get("modified", False)),
                "presentation_script_path": tab.get("presentation_script_path"),
                "presentation_script_content": tab.get("presentation_script_content", ""),
                "teacher_script_path": tab.get("teacher_script_path"),
                "teacher_script_content": tab.get("teacher_script_content", ""),
                "teacher_preview_mode": tab.get("teacher_preview_mode", "student"),
                "dual_student_collapsed": bool(tab.get("dual_student_collapsed", False)),
                "dual_teacher_collapsed": bool(tab.get("dual_teacher_collapsed", False)),
                "student_preview_zoom": float(tab.get("student_preview_zoom", 1.0) or 1.0),
                "teacher_preview_zoom": float(tab.get("teacher_preview_zoom", 1.0) or 1.0),
                "present_teacher_locally": bool(tab.get("present_teacher_locally", False)),
                "split_editor_enabled": bool(tab.get("split_editor_enabled", False)),
                "editor_role": tab.get("editor_role", "student"),
                "teacher_modified": bool(tab.get("teacher_modified", False)),
                "teacher_marker_visible": bool(tab.get("teacher_marker_visible", True)),
                "teacher_marker_text": tab.get("teacher_marker_text", "PROFESOR") or "PROFESOR",
                "student_sync_label_visible": bool(tab.get("student_sync_label_visible", False)),
                "presentation_mode": tab.get("presentation_mode", "slide"),
                "clock_visible": bool(tab.get("clock_visible", False)),
                "time_overlay_target": tab.get("time_overlay_target", "both"),
                "clock_mode": tab.get("clock_mode", "clock"),
                "timer_duration_minutes": int(tab.get("timer_duration_minutes", 5) or 5),
                "visual_state": {
                    "borderless": bool(tab.get("borderless", False)),
                    "font_size": int(tab.get("font_size", 24) or 24),
                    "presentation_mode": tab.get("presentation_mode", "slide"),
                    "student_preview_zoom": float(tab.get("student_preview_zoom", 1.0) or 1.0),
                    "teacher_preview_zoom": float(tab.get("teacher_preview_zoom", 1.0) or 1.0),
                    "clock_visible": bool(tab.get("clock_visible", False)),
                    "time_overlay_target": tab.get("time_overlay_target", "both"),
                    "clock_mode": tab.get("clock_mode", "clock"),
                    "clock_show_seconds": bool(tab.get("clock_show_seconds", False)),
                    "clock_size": int(tab.get("clock_size", 22) or 22),
                    "clock_position": tab.get("clock_position", "top-right"),
                    "timer_duration_minutes": int(tab.get("timer_duration_minutes", 5) or 5),
                    "paper_size": tab.get("paper_size", "letter"),
                    "paper_orientation": tab.get("paper_orientation", "portrait"),
                    "paper_header_mode": tab.get("paper_header_mode", "auto_title"),
                    "paper_footer_mode": tab.get("paper_footer_mode", "page_of_total"),
                    "paper_custom_header": tab.get("paper_custom_header", ""),
                    "paper_header_right_mode": tab.get("paper_header_right_mode", "none"),
                    "paper_header_right_text": tab.get("paper_header_right_text", ""),
                    "paper_footer_left_mode": tab.get("paper_footer_left_mode", "none"),
                    "paper_footer_left_text": tab.get("paper_footer_left_text", ""),
                    "paper_font_scale": float(tab.get("paper_font_scale", 1.0) or 1.0),
                    "student_sync_label_visible": bool(tab.get("student_sync_label_visible", False)),
                },
            })

        data = {
            "active_index": self.current_tab_index,
            "tabs": tabs,
        }
        try:
            with open(self._session_config_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _remember_current_file_preferences(
        self,
        slide_index=None,
        include_visual=False,
        include_image_choice=False,
    ):
        """Persist presentation preferences for the open file."""
        key = self._preference_key(self.current_filepath)
        if not key:
            return

        prefs = dict(self.file_preferences.get(key, {}))
        if slide_index is not None:
            try:
                slide_index = max(0, int(slide_index))
            except (TypeError, ValueError):
                slide_index = 0
            prefs["slide_index"] = slide_index
            self._last_saved_slide_index = slide_index

        if include_visual:
            prefs.update({
                "borderless": bool(self.borderless_btn.isChecked()),
                "font_size": int(self.preview.font_size),
                "student_preview_zoom": self._preview_zoom_for_persistence(self.preview),
                "teacher_preview_zoom": self._preview_zoom_for_persistence(self.teacher_preview),
                "clock_visible": bool(self.clock_btn.isChecked()),
                "time_overlay_target": self.time_overlay_target,
                "clock_mode": self.preview.clock_mode,
                "clock_show_seconds": bool(self.clock_seconds_btn.isChecked()),
                "clock_size": int(self.preview.clock_size),
                "clock_position": self.preview.clock_position,
                "timer_duration_minutes": max(1, self.preview.timer_duration_seconds // 60),
                "presentation_mode": self.preview.presentation_mode,
                "paper_size": self.preview.paper_size,
                "paper_orientation": self.preview.paper_orientation,
                "paper_header_mode": self.preview.paper_header_mode,
                "paper_footer_mode": self.preview.paper_footer_mode,
                "paper_custom_header": self.preview.paper_custom_header,
                "paper_header_right_mode": self.preview.paper_header_right_mode,
                "paper_header_right_text": self.preview.paper_header_right_text,
                "paper_footer_left_mode": self.preview.paper_footer_left_mode,
                "paper_footer_left_text": self.preview.paper_footer_left_text,
                "paper_font_scale": self.preview.paper_font_scale,
                "student_sync_label_visible": self.student_sync_label_visible,
            })

        if include_image_choice and self.editor.saved_choice is not None:
            prefs["image_link_choice"] = int(self.editor.saved_choice)

        if not prefs:
            return

        self.file_preferences[key] = prefs
        if include_visual and 0 <= self.current_tab_index < len(self.tabs):
            tab = self.tabs[self.current_tab_index]
            tab["borderless"] = bool(self.borderless_btn.isChecked())
            tab["font_size"] = int(self.preview.font_size)
            tab["student_preview_zoom"] = self._preview_zoom_for_persistence(self.preview)
            tab["teacher_preview_zoom"] = self._preview_zoom_for_persistence(self.teacher_preview)
            tab["clock_visible"] = bool(self.clock_btn.isChecked())
            tab["time_overlay_target"] = self.time_overlay_target
            tab["clock_mode"] = self.preview.clock_mode
            tab["clock_show_seconds"] = bool(self.clock_seconds_btn.isChecked())
            tab["clock_size"] = int(self.preview.clock_size)
            tab["clock_position"] = self.preview.clock_position
            tab["timer_duration_minutes"] = max(1, self.preview.timer_duration_seconds // 60)
            tab["presentation_mode"] = self.preview.presentation_mode
            tab["paper_size"] = self.preview.paper_size
            tab["paper_orientation"] = self.preview.paper_orientation
            tab["paper_header_mode"] = self.preview.paper_header_mode
            tab["paper_footer_mode"] = self.preview.paper_footer_mode
            tab["paper_custom_header"] = self.preview.paper_custom_header
            tab["paper_header_right_mode"] = self.preview.paper_header_right_mode
            tab["paper_header_right_text"] = self.preview.paper_header_right_text
            tab["paper_footer_left_mode"] = self.preview.paper_footer_left_mode
            tab["paper_footer_left_text"] = self.preview.paper_footer_left_text
            tab["paper_font_scale"] = self.preview.paper_font_scale
            tab["student_sync_label_visible"] = self.student_sync_label_visible
        self._save_file_preferences()

    def _capture_current_slide_preference(self):
        """Capture the currently visible slide for the open file."""
        if not self.current_filepath or self.preview.presentation_mode != "slide":
            return
        self.preview.get_current_slide(self._store_current_slide_preference)

    def _store_current_slide_preference(self, slide_index):
        if self.current_filepath:
            self._remember_current_file_preferences(slide_index=slide_index)

    def _apply_file_preferences(self, file_path):
        """Apply remembered presentation preferences for a file."""
        prefs = self.file_preferences.get(self._preference_key(file_path), {})
        presentation_mode = prefs.get("presentation_mode", self.preview.presentation_mode)
        paper_size = prefs.get("paper_size", self.preview.paper_size)
        paper_orientation = prefs.get("paper_orientation", self.preview.paper_orientation)
        self._set_paper_options(paper_size, paper_orientation, refresh=False, persist=False)
        self._set_paper_running_matter(
            prefs.get("paper_header_mode", "auto_title"),
            prefs.get("paper_footer_mode", "page_of_total"),
            prefs.get("paper_custom_header", ""),
            refresh=False,
            persist=False,
        )
        self._set_paper_secondary_matter(
            prefs.get("paper_header_right_mode", "none"),
            prefs.get("paper_header_right_text", ""),
            prefs.get("paper_footer_left_mode", "none"),
            prefs.get("paper_footer_left_text", ""),
            refresh=False,
            persist=False,
        )
        self._set_paper_font_scale(
            int(float(prefs.get("paper_font_scale", 1.0) or 1.0) * 100),
            refresh=False,
            persist=False,
        )
        self._set_presentation_mode(presentation_mode, refresh=False, persist=False)
        try:
            student_zoom = max(0.01, float(prefs.get("student_preview_zoom", self.preview.zoom_factor)))
        except (TypeError, ValueError):
            student_zoom = self.preview.zoom_factor
        try:
            teacher_zoom = max(0.01, float(prefs.get("teacher_preview_zoom", self.teacher_preview.zoom_factor)))
        except (TypeError, ValueError):
            teacher_zoom = self.teacher_preview.zoom_factor
        self.preview.zoom_factor = student_zoom
        self.teacher_preview.zoom_factor = teacher_zoom
        self.zoom_label.setText(f"{int(student_zoom * 100)}%")
        borderless = bool(prefs.get("borderless", False))

        try:
            font_size = int(prefs.get("font_size", 24))
        except (TypeError, ValueError):
            font_size = 24
        font_size = max(10, min(font_size, 72))

        self.preview.font_size = font_size
        self.teacher_preview.set_font_size(font_size)
        self._set_borderless_state(borderless, persist=False)

        clock_position = prefs.get("clock_position", "top-right")
        if clock_position not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
            clock_position = "top-right"
        try:
            clock_size = int(prefs.get("clock_size", 22))
        except (TypeError, ValueError):
            clock_size = 22
        clock_size = max(10, min(clock_size, 72))

        clock_mode = prefs.get("clock_mode", "clock")
        if clock_mode not in {"clock", "stopwatch", "timer"}:
            clock_mode = "clock"
        try:
            timer_duration_minutes = int(prefs.get("timer_duration_minutes", 5))
        except (TypeError, ValueError):
            timer_duration_minutes = 5
        timer_duration_minutes = max(1, min(timer_duration_minutes, 24 * 60))

        clock_visible = bool(prefs.get("clock_visible", False))
        self.time_overlay_target = self._normalise_time_overlay_target(
            prefs.get("time_overlay_target", "both")
        )
        self.preview.clock_visible = clock_visible
        self.preview.clock_mode = clock_mode
        self.preview.clock_show_seconds = bool(prefs.get("clock_show_seconds", False))
        self.preview.clock_size = clock_size
        self.preview.clock_position = clock_position
        self.preview.timer_duration_seconds = timer_duration_minutes * 60
        self.preview.timer_elapsed_seconds = 0.0
        self.preview.timer_running = False
        self.preview._timer_started_at = None
        self.preview.apply_clock_settings()
        self.teacher_preview.clock_mode = clock_mode
        self.teacher_preview.clock_show_seconds = self.preview.clock_show_seconds
        self.teacher_preview.clock_size = clock_size
        self.teacher_preview.clock_position = clock_position
        self.teacher_preview.timer_duration_seconds = self.preview.timer_duration_seconds
        self.teacher_preview.timer_elapsed_seconds = 0.0
        self.teacher_preview.timer_running = False
        self.teacher_preview._timer_started_at = None
        self.teacher_preview.apply_clock_settings()
        self._sync_output_window_style()
        self._sync_teacher_local_window_style()
        self.clock_btn.setChecked(clock_visible)
        self.clock_mode_combo.blockSignals(True)
        self.clock_mode_combo.setCurrentIndex(max(0, self.clock_mode_combo.findData(clock_mode)))
        self.clock_mode_combo.blockSignals(False)
        self.clock_seconds_btn.setChecked(self.preview.clock_show_seconds)
        self.clock_target_combo.blockSignals(True)
        self.clock_target_combo.setCurrentIndex(
            max(0, self.clock_target_combo.findData(self.time_overlay_target))
        )
        self.clock_target_combo.blockSignals(False)
        self.timer_minutes_input.blockSignals(True)
        self.timer_minutes_input.setValue(timer_duration_minutes)
        self.timer_minutes_input.blockSignals(False)
        self.clock_position_combo.setCurrentIndex(max(0, self.clock_position_combo.findData(clock_position)))
        self._sync_time_overlay_to_previews()
        self._update_time_overlay_controls()

        self.student_sync_label_visible = bool(
            prefs.get("student_sync_label_visible", self.student_sync_label_visible)
        )
        self.student_sync_label_btn.setChecked(self.student_sync_label_visible)
        self._apply_student_sync_label()

        image_link_choice = prefs.get("image_link_choice")
        if image_link_choice in (1, 2, 3):
            self.editor.saved_choice = int(image_link_choice)
        else:
            self.editor.saved_choice = None

        try:
            self._last_saved_slide_index = max(0, int(prefs.get("slide_index", 0)))
        except (TypeError, ValueError):
            self._last_saved_slide_index = 0
        self.preview.restore_slide_after_next_load(self._last_saved_slide_index)

    def _remember_image_link_choice(self, choice):
        """Remember the selected image-link mode for the current file."""
        if choice in (1, 2, 3):
            self.editor.saved_choice = int(choice)
            self._remember_current_file_preferences(include_image_choice=True)

    def _load_recent_files(self):
        """Load recent files list from config."""
        config_path = os.path.join(os.path.expanduser("~"), ".numa_deck_recent.json")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self.recent_files = json.load(f)
        except Exception:
            self.recent_files = []

    def _save_recent_files(self):
        """Save recent files list to config."""
        config_path = os.path.join(os.path.expanduser("~"), ".numa_deck_recent.json")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.recent_files, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _add_to_recent(self, file_path):
        """Add a file to the recent files list."""
        if not file_path:
            return
        # Remove if already in list
        if file_path in self.recent_files:
            self.recent_files.remove(file_path)
        # Add to front
        self.recent_files.insert(0, file_path)
        # Trim to max
        self.recent_files = self.recent_files[:self.MAX_RECENT]
        self._save_recent_files()

    def show_recent_files(self):
        """Show a dialog with recent files list."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QLabel

        dlg = QDialog(self)
        dlg.setWindowTitle("Archivos Recientes")
        dlg.resize(500, 380)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Selecciona un archivo para abrir:", dlg)
        title.setFont(QFont("Inter", 12, QFont.Bold))
        layout.addWidget(title)

        list_widget = QListWidget(dlg)
        list_widget.setAlternatingRowColors(True)

        if not self.recent_files:
            list_widget.addItem("(No hay archivos recientes)")
            list_widget.setEnabled(False)
        else:
            for path in self.recent_files:
                name = os.path.basename(path)
                item = QListWidgetItem(f"{name}  —  {path}")
                item.setData(Qt.ItemDataRole.UserRole, path)
                list_widget.addItem(item)

        layout.addWidget(list_widget)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        open_btn = QPushButton("Abrir", dlg)
        open_btn.setObjectName("primaryBtn")
        open_btn.clicked.connect(lambda: self._open_recent(list_widget, dlg))
        btn_layout.addWidget(open_btn)

        clear_btn = QPushButton("Limpiar Historial", dlg)
        clear_btn.clicked.connect(lambda: self._clear_recent(list_widget))
        btn_layout.addWidget(clear_btn)

        close_btn = QPushButton("Cerrar", dlg)
        close_btn.clicked.connect(dlg.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        # Double click to open
        list_widget.itemDoubleClicked.connect(lambda item: self._open_recent(list_widget, dlg))

        # Apply theme
        bg = "#0E1324" if self.is_dark_mode else "#F7FAFF"
        surface = "#141B2F" if self.is_dark_mode else "#FFFFFF"
        text = "#EEF2FF" if self.is_dark_mode else "#111827"
        border = "#EEF2FF" if self.is_dark_mode else "#0B0F1A"

        dlg.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; border: 2px solid {border}; border-radius: 12px; }}
            QLabel {{ color: {text}; background: transparent; }}
            QListWidget {{
                background-color: {surface};
                color: {text};
                border: 2px solid {border};
                border-radius: 8px;
                padding: 6px;
                font-size: 12px;
            }}
            QListWidget::item {{ padding: 8px; border-radius: 4px; }}
            QListWidget::item:selected {{ background-color: #2563FF; color: #FFFFFF; }}
            QListWidget::item:alternate {{ background-color: rgba(0,0,0,0.03); }}
            QPushButton {{
                background-color: {surface};
                color: {text};
                border: 2px solid {border};
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: #4B5563; color: #FFFFFF; }}
            QPushButton#primaryBtn {{ background-color: #2563FF; color: #FFFFFF; }}
            QPushButton#primaryBtn:hover {{ background-color: #0A84FF; }}
        """)

        dlg.exec()

    def _open_recent(self, list_widget, dlg):
        """Open the selected recent file."""
        item = list_widget.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole):
            file_path = item.data(Qt.ItemDataRole.UserRole)
            if os.path.exists(file_path):
                dlg.accept()
                self._open_file(file_path)
            else:
                QMessageBox.warning(self, "Archivo no encontrado",
                    f"El archivo ya no existe:\n{file_path}")
                # Remove from recent
                if file_path in self.recent_files:
                    self.recent_files.remove(file_path)
                    self._save_recent_files()

    def _clear_recent(self, list_widget):
        """Clear the recent files history."""
        self.recent_files = []
        self._save_recent_files()
        list_widget.clear()
        list_widget.addItem("(No hay archivos recientes)")
        list_widget.setEnabled(False)

    def _open_file(self, file_path):
        """Open a file by path and add to recent list."""
        try:
            normalized = os.path.abspath(file_path)
            for i, tab in enumerate(self.tabs):
                if tab.get("path") and os.path.normcase(os.path.abspath(tab["path"])) == os.path.normcase(normalized):
                    self.tab_bar.setCurrentIndex(i)
                    self.statusBar().showMessage(f"Archivo ya abierto: {normalized}", 2000)
                    self._log_operation("archivo_ya_abierto", path=normalized, target_tab=i + 1)
                    return

            content, recovered = self._read_with_autosave_offer(normalized)
            content, _ = ensure_slide_ids(content)
            self._sync_current_tab_from_editor()
            # The file was already checked above. Do not ask for the same
            # backup again while the new tab is being activated.
            self._create_tab(
                normalized,
                content,
                modified=recovered,
                switch=True,
                check_autosave=False,
            )
            self._add_to_recent(file_path)
            self.statusBar().showMessage(
                f"Archivo cargado{(' desde backup' if recovered else '')}: {file_path}",
                3000,
            )
            self._log_operation("archivo_abierto", path=normalized, bytes=len(content.encode("utf-8")))
        except Exception as e:
            LOGGER.exception("No se pudo abrir el archivo: %s", file_path)
            QMessageBox.critical(self, "Error", f"No se pudo abrir el archivo:\n{e}")

    def _offer_broken_image_repair(self, file_path):
        """Offer to relink missing local images when a document is first activated."""
        if not file_path or not self.current_filepath:
            return

        normalized = os.path.normcase(os.path.abspath(file_path))
        current = os.path.normcase(os.path.abspath(self.current_filepath))
        if normalized != current or normalized in self._image_repair_checked_paths:
            return
        self._image_repair_checked_paths.add(normalized)

        if not (0 <= self.current_tab_index < len(self.tabs)):
            return
        tab = self.tabs[self.current_tab_index]
        student_text = (
            self.editor.toPlainText()
            if self.editor_role == "student" or self.split_editor_enabled
            else tab.get("content", "")
        )
        broken_links = find_broken_local_image_links(student_text, os.path.dirname(file_path))
        if not broken_links:
            return

        broken_directories = []
        for link in broken_links:
            directory = os.path.dirname(link["path"])
            if directory and directory not in broken_directories:
                broken_directories.append(directory)
        directory_summary = "\n".join(f"- {path}" for path in broken_directories[:3])
        if len(broken_directories) > 3:
            directory_summary += f"\n- ... y {len(broken_directories) - 3} directorios mas"

        reply = QMessageBox.question(
            self,
            "Imagenes no encontradas",
            f"Se detectaron {len(broken_links)} imagenes locales que ya no existen en sus rutas.\n\n"
            f"Directorios rotos:\n{directory_summary}\n\n"
            "¿Deseas seleccionar otra carpeta para buscarlas y actualizar sus enlaces?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        search_directory = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta de imagenes",
            os.path.dirname(file_path),
        )
        if not search_directory:
            return

        updated_text, repaired_count, unresolved = repair_broken_local_image_links(
            student_text,
            broken_links,
            search_directory,
        )
        if repaired_count:
            tab["content"] = updated_text
            tab["modified"] = True
            self.is_modified = True
            if self.editor_role == "student" or self.split_editor_enabled:
                self._set_editor_text_quietly(updated_text, self.current_filepath)
            self._sync_current_tab_from_editor()
            self._update_title()
            if self.nav_mode == "slides":
                self.build_slide_outline()
            self.update_preview()

        if repaired_count and not unresolved:
            QMessageBox.information(
                self,
                "Imagenes reparadas",
                f"Se actualizaron correctamente los {repaired_count} enlaces de imagen.",
            )
        elif repaired_count:
            QMessageBox.warning(
                self,
                "Reparacion parcial",
                f"Se actualizaron {repaired_count} enlaces. "
                f"No se encontraron {len(unresolved)} imagenes por su nombre de archivo.",
            )
        else:
            QMessageBox.warning(
                self,
                "Imagenes no encontradas",
                "La carpeta seleccionada no contiene ninguna de las imagenes buscadas.",
            )

    # ── File Operations ───────────────────────────────────

    def file_new(self):
        if self.is_modified:
            reply = QMessageBox.question(
                self, "Nuevo Documento",
                "Hay cambios sin guardar. ¿Deseas descartarlos?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        self._sync_current_tab_from_editor()
        self._create_tab(None, "", modified=False, switch=True)
        self.editor.saved_choice = None
        self.preview.font_size = 24
        self.preview.set_borderless(False)
        self.borderless_btn.setChecked(False)
        self.preview.clock_visible = False
        self.time_overlay_target = "both"
        self.preview.clock_mode = "clock"
        self.preview.clock_show_seconds = False
        self.preview.clock_size = 22
        self.preview.clock_position = "top-right"
        self.preview.timer_duration_seconds = 5 * 60
        self.preview.timer_elapsed_seconds = 0.0
        self.preview.timer_running = False
        self.preview._timer_started_at = None
        self.preview.apply_clock_settings()
        self._sync_time_overlay_to_previews()
        self.teacher_marker_visible = True
        self.teacher_marker_text = "PROFESOR"
        self.student_sync_label_visible = False
        self._update_teacher_marker_controls()
        self.student_sync_label_btn.setChecked(False)
        self.clock_btn.setChecked(False)
        self.clock_mode_combo.blockSignals(True)
        self.clock_mode_combo.setCurrentIndex(0)
        self.clock_mode_combo.blockSignals(False)
        self.clock_seconds_btn.setChecked(False)
        self.clock_target_combo.blockSignals(True)
        self.clock_target_combo.setCurrentIndex(2)
        self.clock_target_combo.blockSignals(False)
        self.timer_minutes_input.blockSignals(True)
        self.timer_minutes_input.setValue(5)
        self.timer_minutes_input.blockSignals(False)
        self.clock_position_combo.setCurrentIndex(1)
        self._update_time_overlay_controls()
        self._update_title()
        self.update_preview(target_slide=0)
        self._log_operation("documento_nuevo")

    def file_open(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Abrir Presentacion", "",
            "Markdown (*.md);;Texto (*.txt);;Todos (*)"
        )
        if file_path:
            self._open_file(file_path)

    def file_save(self):
        if self.teacher_preview_mode == "dual" and self.teacher_script_content:
            return self._save_dual_documents()
        path = self._student_editor_path() or self.current_filepath
        if path:
            return self._save_to(path)
        return self.file_save_as()

    def _save_dual_documents(self):
        """Save both student and teacher sources from the primary Save action."""
        if self.split_editor_enabled:
            self.teacher_script_content = self.teacher_editor.toPlainText()
        elif self.editor_role == "teacher":
            self.teacher_script_content = self.editor.toPlainText()

        student_path = self._student_editor_path() or self.current_filepath
        if not student_path:
            student_path, _ = QFileDialog.getSaveFileName(
                self,
                "Guardar documento del alumno",
                "",
                "Markdown (*.md);;Todos (*)",
            )
            if not student_path:
                return False
            if not student_path.endswith(".md"):
                student_path += ".md"
            self.current_filepath = student_path
            self.editor.set_document_path(student_path)

        teacher_path = self.teacher_script_path
        if not teacher_path:
            teacher_path, _ = QFileDialog.getSaveFileName(
                self,
                "Guardar guion del profesor",
                "",
                "Markdown (*.md);;Todos (*)",
            )
            if not teacher_path:
                return False
            if not teacher_path.endswith(".md"):
                teacher_path += ".md"
            self.teacher_script_path = teacher_path
            self.teacher_editor.set_document_path(teacher_path)

        try:
            with open(student_path, "w", encoding="utf-8") as file:
                file.write(self._student_markdown_text())
            with open(teacher_path, "w", encoding="utf-8") as file:
                file.write(self.teacher_script_content)
            self._remove_autosave(student_path)
            self._remove_autosave(teacher_path)
        except Exception as error:
            LOGGER.exception("No se pudieron guardar ambos documentos")
            QMessageBox.critical(self, "Error", f"No se pudieron guardar ambos documentos:\n{error}")
            return False

        self.is_modified = False
        self.teacher_is_modified = False
        self._add_to_recent(student_path)
        self._remember_current_file_preferences(include_visual=True)
        self._sync_current_tab_from_editor()
        self._update_title()
        self.statusBar().showMessage("Guardados los documentos del alumno y del profesor", 3500)
        self._show_save_confirmation(
            "Documentos guardados",
            "Se guardaron ambos documentos:\n"
            f"Alumno: {student_path}\n"
            f"Profesor: {teacher_path}",
        )
        self._log_operation(
            "documentos_duales_guardados",
            student_path=student_path,
            teacher_path=teacher_path,
        )
        return True

    def _show_save_confirmation(self, title, message):
        QMessageBox.information(self, title, message)

    def file_save_teacher(self):
        if not self.teacher_script_content and not (self.split_editor_enabled and self.teacher_editor.toPlainText().strip()):
            QMessageBox.information(self, "Guardar Profesor", "No hay guion del profesor cargado para guardar.")
            return False

        if self.split_editor_enabled:
            self.teacher_script_content = self.teacher_editor.toPlainText()
        elif self.editor_role == "teacher":
            self.teacher_script_content = self.editor.toPlainText()

        if not self.teacher_script_path:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Guardar Guion Profesor", "",
                "Markdown (*.md);;Todos (*)"
            )
            if not file_path:
                return False
            if not file_path.endswith(".md"):
                file_path += ".md"
            self.teacher_script_path = file_path
            self.teacher_editor.set_document_path(file_path)

        saved = self._save_teacher_script_if_possible(show_error=True)
        if saved:
            self._sync_current_tab_from_editor()
            self.statusBar().showMessage(f"Guardado profesor: {self.teacher_script_path}", 3000)
            self._show_save_confirmation(
                "Profesor guardado",
                f"Se guardaron los cambios del profesor en:\n{self.teacher_script_path}"
            )
            self._log_operation("guion_profesor_guardado", path=self.teacher_script_path)
        return saved

    def file_save_as(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Presentacion", "",
            "Markdown (*.md);;Todos (*)"
        )
        if not file_path:
            return False
        if not file_path.endswith(".md"):
            file_path += ".md"
        self.current_filepath = file_path
        self.editor.set_document_path(file_path)
        self._remember_current_file_preferences(include_visual=True)
        saved = self._save_to(file_path)
        if saved:
            self._sync_current_tab_from_editor()
            if 0 <= self.current_tab_index < len(self.tabs):
                self.tab_bar.setTabToolTip(self.current_tab_index, file_path)
        return saved

    def _reconcile_saved_tab_flags(self):
        """Clear stale dirty flags only when the source matches its saved file."""
        for index, tab in enumerate(self.tabs):
            student_path = tab.get("presentation_script_path") or tab.get("path")
            student_content = (tab.get("presentation_script_content", "")
                               if tab.get("presentation_script_path") else tab.get("content", ""))
            sources = (("modified", student_path, student_content),
                       ("teacher_modified", tab.get("teacher_script_path"),
                        tab.get("teacher_script_content", "")))
            for flag, path, content in sources:
                if not tab.get(flag):
                    continue
                if not path:
                    if flag == "teacher_modified" and not content:
                        tab[flag] = False
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as saved:
                        if saved.read() == content:
                            tab[flag] = False
                except (OSError, UnicodeError):
                    continue
            if index == self.current_tab_index:
                self.is_modified = bool(tab.get("modified"))
                self.teacher_is_modified = bool(tab.get("teacher_modified"))

    def _save_to(self, path):
        try:
            if self.editor_role == "teacher" and not self.split_editor_enabled:
                self.teacher_script_content = self.editor.toPlainText()
                saved_teacher = self._save_teacher_script_if_possible(show_error=True)
                if saved_teacher:
                    self.statusBar().showMessage(f"Guardado guion profesor: {self.teacher_script_path}", 3000)
                    self._sync_current_tab_from_editor()
                    self._show_save_confirmation(
                        "Profesor guardado",
                        f"Se guardaron los cambios del profesor en:\n{self.teacher_script_path}"
                    )
                    self._log_operation("guion_profesor_guardado", path=self.teacher_script_path)
                return saved_teacher
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._student_markdown_text())
            # Do not offer a stale pre-save recovery copy on the next open.
            self._remove_autosave(path)
            self.is_modified = False
            self._update_title()
            self._add_to_recent(path)
            self._remember_current_file_preferences()
            self._sync_current_tab_from_editor()
            self.statusBar().showMessage(f"Guardado: {path}", 3000)
            title = "Alumno guardado" if self.split_editor_enabled else "Documento guardado"
            label = "del alumno" if self.split_editor_enabled else "del documento"
            self._show_save_confirmation(
                title,
                f"Se guardaron los cambios {label} en:\n{path}"
            )
            self._log_operation("documento_guardado", path=path)
            return True
        except Exception as e:
            LOGGER.exception("No se pudo guardar el documento: %s", path)
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{e}")
            return False

    # ── PDF Export ─────────────────────────────────────────

    def export_pdf(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar como PDF", "",
            "PDF (*.pdf);;Todos (*)"
        )
        if not file_path:
            self._log_operation("exportacion_pdf_cancelada", stage="selector_archivo")
            return
        if not file_path.endswith(".pdf"):
            file_path += ".pdf"

        self._log_operation("exportacion_pdf_iniciada", path=file_path)

        self.statusBar().showMessage("Preparando vista previa PDF...", 0)
        QApplication.processEvents()
        self._ensure_slide_ids_in_editor(mark_modified=False)
        restore_slide = self.editor.current_slide_index()
        base_path = self._current_document_base_path()

        student_text = self._student_markdown_text()
        preview_dialog = PdfPreviewDialog(student_text, base_path, self)
        preview_dialog.preview.restore_slide_after_next_load(restore_slide)
        if preview_dialog.exec() != QDialog.Accepted:
            self.statusBar().showMessage("Exportacion PDF cancelada", 2500)
            self._log_operation("exportacion_pdf_cancelada", stage="vista_previa")
            return
        export_text = preview_dialog.export_md_text
        export_mode = preview_dialog.export_mode
        self._log_operation("exportacion_pdf_configurada", path=file_path, mode=export_mode)

        self.statusBar().showMessage("Exportando PDF...", 0)
        QApplication.processEvents()

        # Use QWebEngineView's built-in print to PDF
        from PySide6.QtCore import QMarginsF, QSizeF
        from PySide6.QtGui import QPageLayout, QPageSize

        if export_mode == "document":
            page_layout = QPageLayout(
                QPageSize(QPageSize.PageSizeId.Letter),
                QPageLayout.Orientation.Portrait,
                QMarginsF(42, 42, 42, 42),
            )
        elif export_mode == "paper":
            paper_page_sizes = {
                "letter": QPageSize.PageSizeId.Letter,
                "legal": QPageSize.PageSizeId.Legal,
                "a4": QPageSize.PageSizeId.A4,
                "a3": QPageSize.PageSizeId.A3,
            }
            paper_orientation = (
                QPageLayout.Orientation.Landscape
                if self.preview.paper_orientation == "landscape"
                else QPageLayout.Orientation.Portrait
            )
            page_layout = QPageLayout(
                QPageSize(paper_page_sizes.get(self.preview.paper_size, QPageSize.PageSizeId.Letter)),
                paper_orientation,
                QMarginsF(0, 0, 0, 0),
            )
        else:
            page_layout = QPageLayout(
                QPageSize(QSizeF(16, 9), QPageSize.Unit.Inch, "16:9"),
                QPageLayout.Orientation.Portrait,
                QMarginsF(0, 0, 0, 0),
            )

        page = self.preview.web_view.page()

        def print_after_images(total, failed, timed_out):
            if failed or timed_out:
                details = []
                if failed:
                    details.append(f"{failed} imagen(es) no pudieron cargarse")
                if timed_out:
                    details.append("algunas imagenes siguen cargando")
                reply = QMessageBox.question(
                    self,
                    "Imagenes pendientes en el PDF",
                    ". ".join(details) + ".\n\n¿Deseas exportar de todos modos?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    try:
                        page.pdfPrintingFinished.disconnect(finish_pdf_export)
                    except (TypeError, RuntimeError):
                        pass
                    self.preview.restore_slide_after_next_load(restore_slide)
                    self.preview.set_content(student_text, base_path=base_path)
                    self.statusBar().showMessage("Exportacion PDF cancelada por imagenes sin cargar", 3500)
                    self._log_operation(
                        "exportacion_pdf_cancelada",
                        stage="imagenes",
                        failed_images=failed,
                        timed_out=timed_out,
                    )
                    return
            page.printToPdf(file_path, page_layout)

        def print_prepared_pdf(ok):
            try:
                self.preview.web_view.loadFinished.disconnect(print_prepared_pdf)
            except (TypeError, RuntimeError):
                pass
            if not ok:
                self.preview.set_content(student_text, base_path=base_path)
                self.preview.goto_slide(restore_slide)
                QMessageBox.critical(self, "Error", "No se pudo preparar el PDF con enlaces internos.")
                self._log_operation("exportacion_pdf_fallida", stage="preparar_html")
                return
            self.preview.wait_for_images(print_after_images)

        def finish_pdf_export(path, success):
            try:
                page.pdfPrintingFinished.disconnect(finish_pdf_export)
            except (TypeError, RuntimeError):
                pass
            self.preview.restore_slide_after_next_load(restore_slide)
            self.preview.set_content(student_text, base_path=base_path)
            if success:
                self._on_pdf_exported(file_path)
            else:
                self._log_operation("exportacion_pdf_fallida", stage="print_to_pdf", returned_path=path)
                QMessageBox.critical(self, "Error", f"No se pudo exportar el PDF:\n{path}")

        page.pdfPrintingFinished.connect(finish_pdf_export)
        self.preview.web_view.loadFinished.connect(print_prepared_pdf)
        self.preview.set_content(
            export_text,
            pdf_export=True,
            base_path=base_path,
            pdf_mode=export_mode,
        )

    def _on_pdf_exported(self, file_path):
        self.statusBar().showMessage(f"PDF exportado: {file_path}", 5000)
        self._log_operation("exportacion_pdf_completada", path=file_path)
        QMessageBox.information(
            self, "PDF Exportado",
            f"La presentacion se ha exportado correctamente a:\n{file_path}"
        )

    # ── Close Event ───────────────────────────────────────

    def closeEvent(self, event):
        self._log_operation("solicitar_cierre_aplicacion", tab_count=len(self.tabs))
        # Always release Windows' execution-state request, including an
        # application shutdown while a presentation window is still open.
        self._presentation_power_inhibited = False
        self._uninstall_presentation_alt_tab_hook()
        if os.name == "nt":
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except Exception:
                LOGGER.exception("Error liberando la politica de energia al cerrar la aplicacion")
        # Persist view state separately from the Markdown save/discard choice.
        self._remember_open_file_visual_preferences()
        self._sync_current_tab_from_editor()
        self._reconcile_saved_tab_flags()
        modified_indexes = [
            i for i, tab in enumerate(self.tabs)
            if tab.get("modified") or tab.get("teacher_modified")
        ]
        if modified_indexes:
            reply = QMessageBox.question(
                self, "Salir",
                "Hay cambios sin guardar en una o mas pestanas. ¿Deseas guardar antes de salir?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )
            if reply == QMessageBox.Save:
                for index in modified_indexes:
                    # Closing must ask only about unsaved edits. Backup
                    # recovery belongs to opening/activating a document, not
                    # to the loop that saves the remaining tabs on exit.
                    self._load_tab(index, check_autosave=False)
                    tab = self.tabs[index]
                    if tab.get("modified") and not self.file_save():
                        event.ignore()
                        return
                    if tab.get("teacher_modified"):
                        if self.split_editor_enabled:
                            self.teacher_script_content = self.teacher_editor.toPlainText()
                        elif self.editor_role == "teacher":
                            self.teacher_script_content = self.editor.toPlainText()
                        if not self._save_teacher_script_if_possible(show_error=True):
                            event.ignore()
                            return
                self._save_tabs_session()
                self._clear_autosaves_for_open_documents()
                if getattr(self, "mobile_link", None):
                    self.direct_connections.stop_all()
                    self.mobile_link.stop()
                self._log_operation("aplicacion_cerrada", saved_changes=True)
                event.accept()
            elif reply == QMessageBox.Cancel:
                event.ignore()
            else:
                self._save_tabs_session()
                self._clear_autosaves_for_open_documents()
                if getattr(self, "mobile_link", None):
                    self.direct_connections.stop_all()
                    self.mobile_link.stop()
                self._log_operation("aplicacion_cerrada", saved_changes=False)
                event.accept()
        else:
            self._save_tabs_session()
            self._clear_autosaves_for_open_documents()
            if getattr(self, "mobile_link", None):
                self.direct_connections.stop_all()
                self.mobile_link.stop()
            self._log_operation("aplicacion_cerrada", saved_changes=False)
            event.accept()


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────

def _load_app_icon():
    icons_dir = Path(__file__).resolve().parent / "assets" / "icons"
    for filename in ("numa_deck.ico", "numa_deck.png"):
        icon_path = icons_dir / filename
        if icon_path.is_file():
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                return icon
    return QIcon()


def main():
    configure_logging()
    sys.excepthook = _log_unhandled_exception
    sys.unraisablehook = _log_unraisable_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = _log_thread_exception
    qInstallMessageHandler(_log_qt_message)
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NUMA.Deck.Presentations")
        except Exception:
            pass
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    try:
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(APP_VERSION)
        app.setOrganizationName("NUMA")
        app_icon = _load_app_icon()
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)

        cli_files = [
            os.path.abspath(arg)
            for arg in sys.argv[1:]
            if arg and not arg.startswith("-") and os.path.isfile(arg)
        ]

        # Session and per-file view settings are shared files.  A second
        # process can otherwise save an older in-memory copy after the newer
        # window closes, reverting mode, frame, or zoom.
        lock_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NUMA Deck Presentations"
        lock_dir.mkdir(parents=True, exist_ok=True)
        instance_lock = QLockFile(str(lock_dir / "numa_deck.lock"))
        instance_lock.setStaleLockTime(60 * 60 * 1000)
        if not instance_lock.tryLock(100):
            if cli_files:
                queue_path = lock_dir / "pending_open_files.json"
                existing = []
                if queue_path.is_file():
                    try:
                        loaded = json.loads(queue_path.read_text(encoding="utf-8"))
                        if isinstance(loaded, list):
                            existing = loaded
                    except Exception:
                        existing = []
                queue_path.write_text(
                    json.dumps(existing + cli_files, ensure_ascii=False),
                    encoding="utf-8",
                )
                return 0
            QMessageBox.warning(
                None,
                "NUMA ya esta abierto",
                "Ya hay una instancia de NUMA en ejecucion. Cierrala antes de abrir otra para conservar correctamente las preferencias de cada documento.",
            )
            return 0
        app.aboutToQuit.connect(instance_lock.unlock)
        app.aboutToQuit.connect(_mark_clean_shutdown)

        # Set default font to suppress Qt font warnings
        default_font = QFont("Inter", 10)
        default_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        app.setFont(default_font)

        window = NumaDeckWindow()
        if not app_icon.isNull():
            window.setWindowIcon(app_icon)
        for cli_path in cli_files:
            window._open_file(cli_path)
        window._consume_pending_open_files()
        window.show()
        LOGGER.info("Ventana principal mostrada")
        return app.exec()
    except Exception:
        LOGGER.exception("Fallo durante el arranque de NUMA")
        raise


if __name__ == "__main__":
    sys.exit(main())
