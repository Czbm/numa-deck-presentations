import json
import os
import re
import json
import base64
import hashlib
import html as html_lib
import urllib.parse
import mimetypes
import tempfile
import time
import logging

from PySide6.QtCore import Qt, QUrl, QTimer, Signal, QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from styles import get_html_template
from parser import parse_markdown_to_html


LOGGER = logging.getLogger("numa.preview")


class ExternalLinkPage(QWebEnginePage):
    """Open clicked links with the system's default applications."""

    student_sync_requested = Signal(int)
    slide_navigated_by_key = Signal(int)

    def javaScriptConsoleMessage(self, level, message, line, source):
        if isinstance(message, str) and message.startswith("NUMA_SLIDE:"):
            try:
                self.slide_navigated_by_key.emit(int(message.split(":", 1)[1]))
            except ValueError:
                pass
            return
        super().javaScriptConsoleMessage(level, message, line, source)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme().lower() == "numa-sync":
            match = re.search(r"(\d+)", url.toString())
            if match:
                self.student_sync_requested.emit(int(match.group(1)))
            return False

        if nav_type != QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            return True

        url_text = url.toString()
        if url.scheme().lower() in {"slide", "slide-key", "slide-id"} or url_text.startswith("#slide-"):
            return True

        local_path = url.toLocalFile()

        if local_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(local_path))
        elif re.match(r"^[a-zA-Z]:[\\/]", url_text):
            QDesktopServices.openUrl(QUrl.fromLocalFile(url_text))
        else:
            QDesktopServices.openUrl(url)

        return False


class PreviewWebView(QWebEngineView):
    """WebView that gives NUMA first ownership of preview wheel input."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.wheel_handler = None

    def wheelEvent(self, event):
        if self.wheel_handler and self.wheel_handler(event):
            event.accept()
            return
        super().wheelEvent(event)


class PresentationView(QWidget):
    """
    Presentation View containing a QWebEngineView.
    Supports continuous vertical scrolling and slideshow mode.
    """
    clicked = Signal()
    zoom_changed = Signal(float)
    slide_navigated_by_key = Signal(int)
    student_sync_label_activated = Signal(int)
    markdown_file_dropped = Signal(str)
    paper_page_changed = Signal(int, int)
    # Emitted after an interaction handled by the embedded presentation HTML.
    # Consumers can mirror its state without rebuilding the Markdown preview.
    interactive_state_changed = Signal()

    def __init__(self, parent=None, is_dark=False):
        super().__init__(parent)
        self.is_dark = is_dark
        self.presentation_mode = "slide"
        self.font_size = 24
        self.zoom_factor = 1.0
        self.borderless = False
        self.clock_visible = False
        self.clock_mode = "clock"
        self.clock_show_seconds = False
        self.clock_size = 22
        self.clock_position = "top-right"
        self.timer_duration_seconds = 5 * 60
        self.timer_elapsed_seconds = 0.0
        self.timer_running = False
        self._timer_started_at = None
        self.student_sync_label_visible = False
        self.student_sync_label_map = {}
        self.teacher_marker_visible = False
        self.teacher_marker_text = "PROFESOR"
        self.preview_canvas = True
        self.output_aspect_ratio = "16 / 9"
        self.output_width = 1920
        self.output_height = 1080
        self.paper_size = "letter"
        self.paper_orientation = "portrait"
        self.paper_title = ""
        self.paper_subtitle = ""
        self.paper_header_mode = "auto_title"
        self.paper_footer_mode = "page_of_total"
        self.paper_custom_header = ""
        self.paper_header_right_mode = "none"
        self.paper_header_right_text = ""
        self.paper_footer_left_mode = "none"
        self.paper_footer_left_text = ""
        self.paper_font_scale = 1.0
        self.raw_markdown = ""
        self.content_base_path = os.getcwd()
        self._loaded = False  # Track if content has been loaded
        self._pending_slide_index = None
        # The last slide selected by NUMA.  A live HTML rebuild must preserve
        # this position instead of silently returning the WebView to slide 1.
        self._last_known_slide_index = 0
        self._pending_scroll_query = None
        self._pending_paper_position = None
        self._last_paper_position = {"page": 0, "offset": 0.0}
        self._pending_render_zoom_factor = 1.0
        self._content_generation = 0
        self._pdf_document_render = False
        self._temporary_html_path = None
        self.interaction_enabled = True
        self._interactive_state_timer = QTimer(self)
        self._interactive_state_timer.setSingleShot(True)
        self._interactive_state_timer.timeout.connect(self.interactive_state_changed)
        self._forcing_slide_page_zoom = False
        self._render_metrics = {
            "render_count": 0,
            "load_success_count": 0,
            "load_failure_count": 0,
            "last_prepare_ms": None,
            "last_load_ms": None,
            "last_markdown_bytes": 0,
            "last_html_bytes": 0,
            "last_mode": self.presentation_mode,
        }
        self._render_started_at = None

        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.web_view = PreviewWebView(self)
        self.web_view.wheel_handler = self._handle_wheel_event
        self.web_view.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.web_view.setAcceptDrops(True)
        page = ExternalLinkPage(self.web_view)
        page.student_sync_requested.connect(self.student_sync_label_activated)
        page.slide_navigated_by_key.connect(self.slide_navigated_by_key)
        page.zoomFactorChanged.connect(self._on_page_zoom_factor_changed)
        self.web_view.setPage(page)
        self.web_view.installEventFilter(self)

        settings = self.web_view.settings()
        # Markdown may load local images, but the presentation should not
        # silently fetch remote resources from an opened document.
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self.web_view.loadFinished.connect(self._on_load_finished)
        self.layout.addWidget(self.web_view, stretch=1)

    def _handle_wheel_event(self, event):
        """Handle preview zoom/pan before Chromium can reinterpret the wheel."""
        if not self.interaction_enabled:
            return True

        delta = event.angleDelta().y()
        if not delta:
            delta = event.pixelDelta().y()
        if not delta:
            return True

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            return True

        if self.presentation_mode != "slide":
            return False

        position = event.position()
        x = int(position.x())
        y = int(position.y())
        self._inject_js(
            "(function() {"
            "var delta = " + str(int(-delta)) + ";"
            "var target = document.elementFromPoint(" + str(x) + "," + str(y) + ");"
            "while (target && target !== document.body) {"
            "if (target.scrollHeight > target.clientHeight + 1) {"
            "target.scrollTop += delta; return;"
            "}"
            "target = target.parentElement;"
            "}"
            "var root = document.documentElement;"
            "var current = parseFloat(getComputedStyle(root).getPropertyValue('--numa-pan-y')) || 0;"
            "root.style.setProperty('--numa-pan-y', (current + delta) + 'px');"
            "})();"
        )
        return True

    def eventFilter(self, obj, event):
        web_targets = (self.web_view,)
        if obj in web_targets and event.type() == QEvent.Type.DragEnter:
            if any(self._is_markdown_file(url.toLocalFile()) for url in event.mimeData().urls()):
                event.acceptProposedAction()
                return True
        if obj in web_targets and event.type() == QEvent.Type.Drop:
            paths = [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if self._is_markdown_file(url.toLocalFile())
            ]
            if paths:
                event.acceptProposedAction()
                for path in paths:
                    self.markdown_file_dropped.emit(path)
                return True
        if (
            obj in web_targets
            and not self.interaction_enabled
            and event.type() in {
                QEvent.Type.KeyPress,
                QEvent.Type.KeyRelease,
                QEvent.Type.ShortcutOverride,
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseMove,
                QEvent.Type.Wheel,
            }
        ):
            # Projector mirrors must never become an independent controller.
            event.accept()
            return True
        if obj in web_targets and event.type() == QEvent.Type.MouseButtonPress:
            self.clicked.emit()
        if obj in web_targets and event.type() in {
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.KeyRelease,
        }:
            # Let Chromium finish its click/key handler before querying state.
            self._schedule_interactive_state_changed()
        if (
            obj in web_targets
            and event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
            return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _is_markdown_file(path):
        return os.path.splitext(path.lower())[1] in {".md", ".markdown"}

    def _schedule_interactive_state_changed(self):
        """Coalesce browser-originated interactions into one state update."""
        self._interactive_state_timer.start(80)

    def set_interaction_enabled(self, enabled):
        """Enable direct browser input, or make this view a passive mirror."""
        self.interaction_enabled = bool(enabled)
        self.web_view.setFocusPolicy(
            Qt.FocusPolicy.ClickFocus if self.interaction_enabled else Qt.FocusPolicy.NoFocus
        )

    def set_content(self, md_text, is_dark=None, pdf_export=False, base_path=None, pdf_mode="slides"):
        """Rebuild content while retaining the visible paper page when possible."""
        self._content_generation += 1
        generation = self._content_generation
        if not pdf_export and self.presentation_mode == "paper" and self._loaded:
            # Paper mode uses QWebEngine's native zoom.  Capture the factor
            # currently visible before replacing the document; the model value
            # can lag behind it while a previous page is still loading.
            visible_zoom = self.visible_zoom_factor()
            script = """
            (function() {
                const pages = Array.from(document.querySelectorAll('.print-page'));
                if (!pages.length) return JSON.stringify({page: 0, offset: 0});
                const viewportTop = 0;
                let pageIndex = 0;
                for (let index = 0; index < pages.length; index += 1) {
                    const rect = pages[index].getBoundingClientRect();
                    if (rect.bottom > viewportTop) {
                        pageIndex = index;
                        const offset = Math.max(0, Math.min(1, (viewportTop - rect.top) / Math.max(1, rect.height)));
                        return JSON.stringify({page: pageIndex, offset: offset});
                    }
                }
                return JSON.stringify({page: pages.length - 1, offset: 1});
            })();
            """

            def render_after_capture(result):
                if generation != self._content_generation:
                    return
                try:
                    position = json.loads(result) if isinstance(result, str) else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    position = {}
                self._pending_paper_position = position if isinstance(position, dict) else None
                if self._pending_paper_position is not None:
                    self._last_paper_position = self._pending_paper_position
                self._set_content_now(
                    md_text,
                    is_dark,
                    pdf_export,
                    base_path,
                    pdf_mode,
                    preserved_zoom=visible_zoom,
                )

            self.web_view.page().runJavaScript(script, render_after_capture)
            return

        if not pdf_export and self.presentation_mode == "paper":
            self._pending_paper_position = self._last_paper_position
        else:
            self._pending_paper_position = None
        self._set_content_now(md_text, is_dark, pdf_export, base_path, pdf_mode)

    def diagnostics_snapshot(self):
        """Return content-free render metrics for the Desk heartbeat."""
        return dict(self._render_metrics)

    def _set_content_now(
        self,
        md_text,
        is_dark=None,
        pdf_export=False,
        base_path=None,
        pdf_mode="slides",
        preserved_zoom=None,
    ):
        """Parse Markdown and update the WebView after any position capture."""
        render_started_at = time.perf_counter()
        # A paper edit replaces the whole HTML document.  Its native browser
        # zoom must be restored from the view that was actually on screen,
        # rather than from a potentially stale persisted preference.
        if preserved_zoom is None:
            preserved_zoom = self.zoom_factor
        self._pending_render_zoom_factor = max(0.01, float(preserved_zoom))
        self.zoom_factor = self._pending_render_zoom_factor
        if (
            not pdf_export
            and self.presentation_mode == "slide"
            and self._pending_slide_index is None
        ):
            self.restore_slide_after_next_load(self._last_known_slide_index)
        self._loaded = False
        if not pdf_export:
            self.raw_markdown = md_text
        if base_path:
            self.content_base_path = base_path
        if is_dark is not None:
            self.is_dark = is_dark
        if pdf_export:
            md_text = self._embed_local_images_for_pdf(md_text)

        pdf_document = bool(pdf_export and pdf_mode == "document")
        pdf_paper = bool(pdf_export and pdf_mode == "paper")
        self._pdf_document_render = pdf_document
        render_mode = (
            "paper"
            if pdf_paper
            else ("scroll" if pdf_document else ("slide" if pdf_export else self.presentation_mode))
        )
        parsed_html = parse_markdown_to_html(md_text, mode=render_mode, pdf_export=pdf_export)
        parsed_html = self._inline_svg_external_images(parsed_html)
        full_html = get_html_template(
            content_html=parsed_html,
            style_mode=render_mode,
            font_size=self.font_size,
            is_dark=False if (pdf_document or pdf_paper) else self.is_dark,
            borderless=self.borderless,
            clock_visible=False if pdf_export else self.clock_visible,
            clock_mode=self.clock_mode,
            clock_show_seconds=self.clock_show_seconds,
            clock_size=self.clock_size,
            clock_position=self.clock_position,
            timer_duration_seconds=self.timer_duration_seconds,
            timer_elapsed_seconds=self._current_timer_elapsed_seconds(),
            timer_running=self.timer_running,
            student_sync_label_visible=False if pdf_export else self.student_sync_label_visible,
            student_sync_label_map=self.student_sync_label_map,
            preview_canvas=(self.preview_canvas and render_mode == "slide" and not pdf_export),
            output_aspect_ratio=self.output_aspect_ratio,
            output_width=self.output_width,
            output_height=self.output_height,
            preview_zoom=1.0 if pdf_export else self.zoom_factor,
            pdf_export=pdf_export,
            pdf_document=pdf_document,
            paper_size=self.paper_size,
            paper_orientation=self.paper_orientation,
            paper_title=self.paper_title,
            paper_subtitle=self.paper_subtitle,
            paper_header_mode=self.paper_header_mode,
            paper_footer_mode=self.paper_footer_mode,
            paper_custom_header=self.paper_custom_header,
            paper_header_right_mode=self.paper_header_right_mode,
            paper_header_right_text=self.paper_header_right_text,
            paper_footer_left_mode=self.paper_footer_left_mode,
            paper_footer_left_text=self.paper_footer_left_text,
            paper_font_scale=self.paper_font_scale,
        )

        # Paper pagination runs while the document is loading. Include the
        # selected text scale in that first HTML pass, rather than enlarging
        # an already paginated document after it has been laid out.
        if (self.presentation_mode == "paper" and not pdf_export) or pdf_paper:
            paper_font_pixels = max(6.0, self.font_size * 0.72 * self.paper_font_scale)
            full_html = full_html.replace(
                "font-size: calc(var(--font-size) * 0.72);",
                f"font-size: {paper_font_pixels}px;",
                1,
            )

        if pdf_export:
            self._load_large_html_document(full_html)
        else:
            self._remove_temporary_html_document()
            base_url = QUrl.fromLocalFile(os.path.abspath(self.content_base_path) + os.sep)
            self.web_view.setHtml(full_html, base_url)
        self._apply_zoom()
        prepare_ms = (time.perf_counter() - render_started_at) * 1000.0
        self._render_started_at = time.monotonic()
        self._render_metrics.update({
            "render_count": self._render_metrics["render_count"] + 1,
            "last_prepare_ms": round(prepare_ms, 2),
            "last_markdown_bytes": len((md_text or "").encode("utf-8")),
            "last_html_bytes": len(full_html.encode("utf-8")),
            "last_mode": render_mode,
        })
        LOGGER.debug(
            "Render preparado | mode=%s | markdown_bytes=%s | html_bytes=%s | prepare_ms=%.2f",
            render_mode,
            self._render_metrics["last_markdown_bytes"],
            self._render_metrics["last_html_bytes"],
            prepare_ms,
        )

    def _load_large_html_document(self, html_document):
        """Load printable HTML from disk to avoid Qt's setHtml size limit."""
        self._remove_temporary_html_document()
        handle, path = tempfile.mkstemp(prefix="numa-pdf-", suffix=".html")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as html_file:
                html_file.write(html_document)
        except Exception:
            try:
                os.close(handle)
            except OSError:
                pass
            try:
                os.remove(path)
            except OSError:
                pass
            raise
        self._temporary_html_path = path
        self.web_view.load(QUrl.fromLocalFile(path))

    def _remove_temporary_html_document(self):
        path = self._temporary_html_path
        self._temporary_html_path = None
        if not path:
            return
        try:
            os.remove(path)
        except OSError:
            pass

    def _resolve_local_path(self, target, base_dir):
        """Turn a file URL / absolute / relative reference into a local path."""
        target = urllib.parse.unquote(html_lib.unescape((target or "").strip()))
        target = re.split(r"[?#]", target, maxsplit=1)[0]
        if not target or target.lower().startswith(("http://", "https://", "data:", "blob:")):
            return None
        if target.lower().startswith("file:"):
            path = QUrl(target).toLocalFile()
        elif re.match(r"^[a-zA-Z]:[\\/]", target) or target.startswith("\\\\"):
            path = target
        else:
            path = os.path.join(base_dir, target)
        path = os.path.abspath(os.path.normpath(path))
        return path if os.path.isfile(path) else None

    def _inline_svg_external_images(self, html_text):
        """Make SVGs show images they reference externally.

        An SVG loaded through <img> cannot fetch linked files, so the preview
        would show blank frames.  Rewrite such SVGs (in a temp cache) with the
        referenced images embedded as data URIs and point the <img> at them.
        """
        if not html_text or ".svg" not in html_text.lower():
            return html_text

        img_pattern = re.compile(
            r'(<img\b[^>]*?\bsrc=)(["\'])([^"\']+?\.svg(?:[?#][^"\']*)?)\2',
            re.IGNORECASE,
        )
        href_pattern = re.compile(
            r'((?:xlink:)?href\s*=\s*)(["\'])(?!#|data:|https?:)(.*?)\2',
            re.IGNORECASE | re.DOTALL,
        )
        cache_dir = os.path.join(tempfile.gettempdir(), "numa-svg-cache")

        def embed_refs(svg_bytes, svg_dir):
            changed = [False]
            text = svg_bytes.decode("utf-8", errors="replace")

            def replace_href(match):
                ref_path = self._resolve_local_path(match.group(3), svg_dir)
                if not ref_path:
                    return match.group(0)
                mime = mimetypes.guess_type(ref_path)[0] or ""
                if not mime.startswith("image/"):
                    return match.group(0)
                try:
                    with open(ref_path, "rb") as handle:
                        data = handle.read()
                except OSError:
                    return match.group(0)
                if mime == "image/svg+xml":
                    data = embed_refs(data, os.path.dirname(ref_path))[0].encode("utf-8")
                changed[0] = True
                encoded = base64.b64encode(data).decode("ascii")
                return f"{match.group(1)}{match.group(2)}data:{mime};base64,{encoded}{match.group(2)}"

            text = href_pattern.sub(replace_href, text)
            return text, changed[0]

        def replace_img(match):
            svg_path = self._resolve_local_path(match.group(3), self.content_base_path)
            if not svg_path:
                return match.group(0)
            try:
                with open(svg_path, "rb") as handle:
                    raw = handle.read()
                text, changed = embed_refs(raw, os.path.dirname(svg_path))
                if not changed:
                    return match.group(0)
                os.makedirs(cache_dir, exist_ok=True)
                digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
                out_path = os.path.join(cache_dir, f"{digest}.svg")
                if not os.path.isfile(out_path):
                    with open(out_path, "w", encoding="utf-8", newline="") as out:
                        out.write(text)
            except Exception:
                LOGGER.exception("No se pudieron incrustar imagenes del SVG: %s", svg_path)
                return match.group(0)
            return f"{match.group(1)}{match.group(2)}{QUrl.fromLocalFile(out_path).toString()}{match.group(2)}"

        return img_pattern.sub(replace_img, html_text)

    def _embed_local_images_for_pdf(self, md_text):
        """Inline local images so Chromium printing cannot lose file-based resources."""
        pattern = re.compile(r'!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^)]+?))\s*\)')

        def replace_image(match):
            alt_text = match.group(1)
            target = (match.group(2) or match.group(3) or "").strip()
            if not target or target.lower().startswith(("http://", "https://", "data:")):
                return match.group(0)

            if target.lower().startswith("file:"):
                image_path = QUrl(target).toLocalFile()
            elif re.match(r"^[a-zA-Z]:[\\/]", target):
                image_path = target
            else:
                image_path = os.path.join(self.content_base_path, target)
            image_path = os.path.abspath(os.path.normpath(image_path))
            if not os.path.isfile(image_path):
                return match.group(0)

            mime_type = mimetypes.guess_type(image_path)[0] or "application/octet-stream"
            if not mime_type.startswith("image/"):
                return match.group(0)
            if os.path.getsize(image_path) > 256 * 1024:
                return f"![{alt_text}](<{QUrl.fromLocalFile(image_path).toString()}>)"
            try:
                with open(image_path, "rb") as image_file:
                    encoded = base64.b64encode(image_file.read()).decode("ascii")
            except OSError:
                return match.group(0)
            return f"![{alt_text}](data:{mime_type};base64,{encoded})"

        return pattern.sub(replace_image, md_text or "")

    def _on_load_finished(self, ok):
        """Keep live CSS state after the WebView rebuilds its HTML."""
        self._loaded = ok
        if self._render_started_at is not None:
            load_ms = (time.monotonic() - self._render_started_at) * 1000.0
            self._render_metrics["last_load_ms"] = round(load_ms, 2)
            self._render_started_at = None
        key = "load_success_count" if ok else "load_failure_count"
        self._render_metrics[key] += 1
        LOGGER.debug(
            "Render cargado | ok=%s | mode=%s | load_ms=%s",
            ok,
            self._render_metrics["last_mode"],
            self._render_metrics["last_load_ms"],
        )
        if ok:
            if not self._pdf_document_render:
                self._apply_borderless_css()
            self._apply_zoom()
            # setHtml() may reset Chromium's page zoom after loadFinished.
            # Reapply the exact factor captured for this rebuild once layout
            # and paper pagination have completed.
            if self.presentation_mode == "paper":
                QTimer.singleShot(0, self._restore_render_zoom)
            if self._pending_slide_index is not None:
                slide_index = self._pending_slide_index
                self._pending_slide_index = None
                self._last_known_slide_index = slide_index
                QTimer.singleShot(0, lambda: self.goto_slide(slide_index))
            if self.presentation_mode == "paper" and self._pending_paper_position is not None:
                position = self._pending_paper_position
                self._pending_paper_position = None
                self._last_paper_position = position
                QTimer.singleShot(100, lambda: self._restore_paper_position(position))
            if self.presentation_mode == "paper":
                QTimer.singleShot(160, self._emit_current_paper_page_state)
            self.apply_clock_settings()
            self.apply_student_sync_label()
            self.apply_teacher_marker()
            if self._pending_scroll_query and self.presentation_mode == "scroll":
                QTimer.singleShot(0, self._apply_pending_scroll_query)

    def _restore_paper_position(self, position):
        """Return to the same paper page and relative reading point after a rebuild."""
        try:
            page = max(0, int(position.get("page", 0)))
            offset = max(0.0, min(1.0, float(position.get("offset", 0))))
        except (AttributeError, TypeError, ValueError):
            return
        script = f"""
        (function() {{
            const pages = Array.from(document.querySelectorAll('.print-page'));
            const target = pages[Math.min({page}, Math.max(0, pages.length - 1))];
            if (!target) return false;
            const rect = target.getBoundingClientRect();
            const top = (window.scrollY || document.documentElement.scrollTop || 0) + rect.top + (rect.height * {offset});
            window.scrollTo(0, Math.max(0, top));
            return true;
        }})();
        """
        self.web_view.page().runJavaScript(script)

    def _restore_render_zoom(self):
        """Restore the visual paper zoom that was active before HTML reload."""
        if self.presentation_mode != "paper":
            return
        self.zoom_factor = max(0.01, float(self._pending_render_zoom_factor))
        self._apply_zoom()
        self.zoom_changed.emit(self.zoom_factor)

    def wait_for_images(self, callback, max_attempts=100):
        """Wait until printable images finish loading or the bounded wait expires."""
        script = """
        (function() {
            const images = Array.from(document.images || []);
            return {
                total: images.length,
                pending: images.filter(img => !img.complete).length,
                failed: images.filter(img => img.complete && img.naturalWidth === 0).length
            };
        })();
        """

        def poll(attempt=0):
            def handle(result):
                result = result if isinstance(result, dict) else {}
                pending = int(result.get("pending", 0) or 0)
                if pending > 0 and attempt < max_attempts:
                    QTimer.singleShot(100, lambda: poll(attempt + 1))
                    return
                callback(
                    int(result.get("total", 0) or 0),
                    int(result.get("failed", 0) or 0),
                    pending > 0,
                )

            self.web_view.page().runJavaScript(script, handle)

        poll()

    def _inject_css(self, css_rule):
        """Inject a CSS rule via JavaScript without rebuilding the page."""
        css_json = json.dumps(css_rule)
        js = f"""
        (function() {{
            var style = document.getElementById('numa-dynamic-css');
            if (!style) {{
                style = document.createElement('style');
                style.id = 'numa-dynamic-css';
                document.head.appendChild(style);
            }}
            style.textContent = {css_json};
        }})();
        """
        self.web_view.page().runJavaScript(js)

    def _inject_js(self, js_code):
        """Inject arbitrary JavaScript."""
        self.web_view.page().runJavaScript(js_code)

    def _teacher_marker_config_js(self):
        text = (self.teacher_marker_text or "PROFESOR").strip() or "PROFESOR"
        repeated = " - ".join([text] * 18)
        return json.dumps({
            "visible": bool(self.teacher_marker_visible),
            "text": repeated,
        })

    def apply_teacher_marker(self):
        js = f"""
        (function() {{
            var config = {self._teacher_marker_config_js()};
            var marker = document.getElementById('numaTeacherMarker');
            if (!marker) {{
                marker = document.createElement('div');
                marker.id = 'numaTeacherMarker';
                marker.innerHTML = '<span></span>';
                document.body.appendChild(marker);
            }}
            var span = marker.querySelector('span');
            if (span) span.textContent = config.text;
            marker.style.display = config.visible ? 'flex' : 'none';

            var css = document.getElementById('numa-teacher-marker-css');
            if (!css) {{
                css = document.createElement('style');
                css.id = 'numa-teacher-marker-css';
                document.head.appendChild(css);
            }}
            css.textContent = `
                #numaTeacherMarker {{
                    position: fixed;
                    left: 0;
                    top: 0;
                    bottom: 0;
                    width: 56px;
                    background: #DC2626;
                    color: #FFFFFF;
                    z-index: 999999;
                    align-items: center;
                    justify-content: center;
                    overflow: hidden;
                    box-shadow: 4px 0 0 rgba(17, 24, 39, 0.95);
                    pointer-events: none;
                }}
                #numaTeacherMarker span {{
                    display: block;
                    writing-mode: vertical-rl;
                    text-orientation: mixed;
                    white-space: nowrap;
                    font-family: Arial, Helvetica, sans-serif;
                    font-size: 18px;
                    font-weight: 900;
                    letter-spacing: 1px;
                    line-height: 1;
                }}
            `;
        }})();
        """
        self.web_view.page().runJavaScript(js)

    def set_teacher_marker(self, visible=None, text=None):
        if visible is not None:
            self.teacher_marker_visible = bool(visible)
        if text is not None:
            self.teacher_marker_text = (str(text).strip() or "PROFESOR")
        self.apply_teacher_marker()

    def set_presentation_mode(self, mode):
        if mode in ["slide", "scroll", "paper"]:
            self.presentation_mode = mode
            self.set_content(self.raw_markdown)

    def center_on_text(self, text, callback=None):
        """Center the rendered block containing text in scroll or paper mode."""
        if self.presentation_mode not in {"scroll", "paper"}:
            if callback:
                callback(False)
            return
        query = (text or "").strip()
        if not query:
            if callback:
                callback(False)
            return
        self._pending_scroll_query = query
        if self._loaded:
            self._apply_pending_scroll_query(callback)

    def center_on_image(self, target, occurrence=0, callback=None):
        """Find the actual image after pagination instead of its section page."""
        if self.presentation_mode not in {"scroll", "paper"} or not self._loaded:
            if callback:
                callback(False)
            return
        self._pending_scroll_query = None
        js = f"""
        (function() {{
            const normalize = function(value) {{
                try {{ value = decodeURI(value); }} catch (error) {{}}
                value = value.replace(/\\\\/g, '/').replace(/^file:\\/+/i, '');
                return /^[a-z]:\\//i.test(value) ? value.toLowerCase() : value;
            }};
            const target = normalize({json.dumps(target)});
            const images = Array.from(document.querySelectorAll('#presentation-container img'))
                .filter(image => normalize(image.getAttribute('src') || '') === target);
            const image = images[{int(occurrence)}];
            if (!image) return false;
            const rect = image.getBoundingClientRect();
            const root = document.scrollingElement || document.documentElement;
            const top = root.scrollTop + rect.top - root.clientHeight / 2 + rect.height / 2;
            window.scrollTo({{top: Math.max(0, top), behavior: 'auto'}});
            return true;
        }})();
        """
        if callback:
            self.web_view.page().runJavaScript(js, lambda result: callback(bool(result)))
        else:
            self.web_view.page().runJavaScript(js)

    def center_on_paper_cursor(self, text, slide_index, callback=None):
        """Center a paper page using the editor's structural slide context."""
        if self.presentation_mode != "paper" or not self._loaded:
            if callback:
                callback(False)
            return
        try:
            slide_index = max(0, int(slide_index))
        except (TypeError, ValueError):
            slide_index = 0
        query = (text or "").strip()
        js = f"""
        (function() {{
            const index = {slide_index};
            const query = {json.dumps(query)};
            const normalize = function(value) {{
                return (value || '').replace(/\\s+/g, ' ').trim().toLocaleLowerCase();
            }};
            const pages = Array.from(document.querySelectorAll(
                '.print-page[data-slide-index="' + index + '"], ' +
                '.print-page[data-source-slide-index="' + index + '"]'
            ));
            if (!pages.length) return false;
            const center = function(element) {{
                const rect = element.getBoundingClientRect();
                const root = document.scrollingElement || document.documentElement || document.body;
                const top = (root.scrollTop || window.scrollY) + rect.top -
                    (root.clientHeight / 2) + (rect.height / 2);
                window.scrollTo({{top: Math.max(0, top), behavior: 'auto'}});
                return true;
            }};
            const targetText = normalize(query);
            if (targetText) {{
                for (const page of pages) {{
                    const walker = document.createTreeWalker(page, NodeFilter.SHOW_TEXT);
                    let node;
                    while ((node = walker.nextNode())) {{
                        const parent = node.parentElement;
                        if (!parent || parent.closest('script, style')) continue;
                        const block = parent.closest('p, li, h1, h2, h3, h4, h5, h6, blockquote, td, th, pre');
                        if (block && normalize(block.textContent).includes(targetText)) {{
                            return center(block);
                        }}
                    }}
                }}
            }}
            return center(pages[0]);
        }})();
        """
        if callback:
            self.web_view.page().runJavaScript(js, lambda result: callback(bool(result)))
        else:
            self.web_view.page().runJavaScript(js)

    def center_on_line_position(self, line_number, total_lines):
        """Use source-line progress as a reliable continuous-preview fallback."""
        if self.presentation_mode != "scroll" or not self._loaded:
            return
        # A delayed text lookup from an earlier cursor event can otherwise
        # overwrite this deterministic source-position scroll.
        self._pending_scroll_query = None
        try:
            progress = max(0.0, min(1.0, int(line_number) / max(1, int(total_lines) - 1)))
        except (TypeError, ValueError):
            return
        js = f"""
        (function() {{
            const progress = {progress!r};
            const root = document.scrollingElement || document.documentElement || document.body;
            if (!root) return false;
            // clientHeight reflects the effective viewport after Chromium
            // applies the user zoom factor; window.innerHeight does not
            // always do so in an embedded QWebEngineView.
            const visibleHeight = root.clientHeight || window.innerHeight;
            const maximum = Math.max(0, root.scrollHeight - visibleHeight);
            const top = maximum * progress;
            root.scrollTop = top;
            document.documentElement.scrollTop = top;
            document.body.scrollTop = top;
            window.scrollTo(0, top);
            return true;
        }})();
        """
        self.web_view.page().runJavaScript(js)

    def center_on_progress(self, progress):
        """Scroll the continuous document to a normalized editor position."""
        if self.presentation_mode != "scroll" or not self._loaded:
            return
        try:
            progress = max(0.0, min(1.0, float(progress)))
        except (TypeError, ValueError):
            return
        self.center_on_line_position(int(progress * 10000), 10001)

    def _apply_pending_scroll_query(self, callback=None):
        if self.presentation_mode not in {"scroll", "paper"} or not self._pending_scroll_query:
            return
        query = self._pending_scroll_query
        self._pending_scroll_query = None
        js = f"""
        (function() {{
            const container = document.getElementById('presentation-container');
            const query = {json.dumps(query)};
            if (!container || !query) return false;

            const normalize = function(value) {{
                return (value || '').replace(/\\s+/g, ' ').trim().toLocaleLowerCase();
            }};
            const targetText = normalize(query);
            if (!targetText) return false;

            const centerElement = function(element) {{
                const rect = element.getBoundingClientRect();
                const root = document.scrollingElement || document.documentElement || document.body;
                const top = (root.scrollTop || window.scrollY) + rect.top - (root.clientHeight / 2) + (rect.height / 2);
                root.scrollTop = Math.max(0, top);
                window.scrollTo({{ top: Math.max(0, top), behavior: 'auto' }});
                return true;
            }};

            const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {{
                acceptNode: function(node) {{
                    const parent = node.parentElement;
                    if (!parent || parent.closest('script, style')) {{
                        return NodeFilter.FILTER_REJECT;
                    }}
                    // Ignore formatting whitespace around the full document.
                    // Its parent container contains every section and would
                    // otherwise be selected as a false whole-page match.
                    if (!normalize(node.nodeValue)) {{
                        return NodeFilter.FILTER_REJECT;
                    }}
                    return NodeFilter.FILTER_ACCEPT;
                }}
            }});

            let node;
            const inspected = new Set();
            while ((node = walker.nextNode())) {{
                const element = node.parentElement.closest(
                    'p, li, h1, h2, h3, h4, h5, h6, blockquote, td, th, pre'
                ) || node.parentElement;
                if (inspected.has(element)) continue;
                inspected.add(element);
                const renderedText = normalize(element.textContent);
                // Only accept the cursor text inside a rendered block. The
                // previous reverse match could select a short, unrelated
                // heading and leave the preview in another section.
                if (renderedText.includes(targetText)) {{
                    return centerElement(element);
                }}
            }}
            return false;
        }})();
        """
        if callback:
            self.web_view.page().runJavaScript(js, lambda result: callback(bool(result)))
        else:
            self.web_view.page().runJavaScript(js)

    def set_dark_mode(self, is_dark):
        self.is_dark = is_dark
        self.set_content(self.raw_markdown)

    def set_preview_canvas(self, enabled):
        self.preview_canvas = bool(enabled)

    def set_output_aspect_ratio(self, width, height):
        try:
            width = max(1, int(width))
            height = max(1, int(height))
        except (TypeError, ValueError):
            width, height = 16, 9
        self.output_width = width
        self.output_height = height
        self.output_aspect_ratio = f"{width} / {height}"

    # ── Font Size (content text size, NOT zoom) ───────────
    # Uses CSS injection to avoid rebuilding HTML and losing slide position

    def _dynamic_state_css(self):
        return f":root {{ --font-size: {self.font_size}px; }}\n{self._borderless_css()}"

    def increase_font_size(self):
        self.font_size = min(self.font_size + 2, 72)
        self._inject_css(self._dynamic_state_css())
        return self.font_size

    def set_font_size(self, size):
        self.font_size = max(10, min(int(size), 72))
        self._inject_css(self._dynamic_state_css())
        return self.font_size

    def decrease_font_size(self):
        self.font_size = max(self.font_size - 2, 10)
        self._inject_css(self._dynamic_state_css())
        return self.font_size

    def reset_font_size(self):
        self.font_size = 24
        self._inject_css(self._dynamic_state_css())
        return self.font_size

    # ── Zoom (viewport scale) ─────────────────────────────

    def _uses_css_preview_zoom(self):
        # Slide zoom must be applied inside the rendered stage. Using
        # QWebEngine's page zoom makes fixed overlays grow while responsive
        # slides shrink, which is the inverse behavior users see in dual mode.
        return self.presentation_mode == "slide"

    def _on_page_zoom_factor_changed(self, factor):
        """Keep Chromium's page zoom neutral while slides use CSS zoom."""
        if not self._uses_css_preview_zoom() or self._forcing_slide_page_zoom:
            return
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            return
        if abs(factor - 1.0) < 0.001:
            return
        self._forcing_slide_page_zoom = True
        try:
            self.web_view.setZoomFactor(1.0)
        finally:
            self._forcing_slide_page_zoom = False
        self._apply_css_preview_zoom()

    def visible_zoom_factor(self):
        """Return the zoom currently displayed by the active rendering mode."""
        if self.presentation_mode in {"paper", "scroll"}:
            try:
                return max(0.01, float(self.web_view.zoomFactor()))
            except (AttributeError, TypeError, ValueError):
                pass
        return max(0.01, float(self.zoom_factor))

    def _apply_zoom(self):
        if self._uses_css_preview_zoom():
            self._forcing_slide_page_zoom = True
            try:
                self.web_view.setZoomFactor(1.0)
            finally:
                self._forcing_slide_page_zoom = False
            self._apply_css_preview_zoom()
        else:
            self.web_view.setZoomFactor(max(self.zoom_factor, 0.01))

    def _apply_css_preview_zoom(self):
        """Scale only the slide stage; fixed sync/teacher layers stay stable."""
        self._inject_js(
                "(function() {"
                "var factor = " + json.dumps(float(max(self.zoom_factor, 0.01))) + ";"
                "document.documentElement.style.setProperty('--numa-user-zoom', String(factor));"
                "document.documentElement.style.setProperty('--numa-zoom-percent', String(Math.round(factor * 100)) + '%');"
                "var container = document.getElementById('presentation-container');"
                "if (container) {"
                "container.style.transformOrigin = 'center center';"
                "container.style.transform = 'scale(' + factor + ')';"
                "}"
                "})();"
            )

    def zoom_in(self):
        self.zoom_factor = self.zoom_factor + 0.1
        self._apply_zoom()
        self.zoom_changed.emit(self.zoom_factor)

    def zoom_out(self):
        self.zoom_factor = max(self.zoom_factor - 0.1, 0.01)
        self._apply_zoom()
        self.zoom_changed.emit(self.zoom_factor)

    def reset_zoom(self):
        self.zoom_factor = 1.0
        self._apply_zoom()
        self.zoom_changed.emit(self.zoom_factor)

    # ── Clock Overlay ─────────────────────────────────────

    def _clock_config_js(self):
        return json.dumps({
            "visible": self.clock_visible,
            "mode": self.clock_mode,
            "showSeconds": self.clock_show_seconds,
            "size": self.clock_size,
            "position": self.clock_position,
            "durationSeconds": self.timer_duration_seconds,
            "elapsedSeconds": self._current_timer_elapsed_seconds(),
            "running": self.timer_running,
        })

    def apply_clock_settings(self):
        js = f"""
        (function() {{
            if (window.setNumaClockConfig) {{
                window.setNumaClockConfig({self._clock_config_js()});
            }}
        }})();
        """
        self.web_view.page().runJavaScript(js)

    def set_clock_visible(self, visible):
        self.clock_visible = bool(visible)
        self.apply_clock_settings()

    def _current_timer_elapsed_seconds(self):
        if self.timer_running and self._timer_started_at is not None:
            return self.timer_elapsed_seconds + max(0.0, time.monotonic() - self._timer_started_at)
        return self.timer_elapsed_seconds

    def set_clock_mode(self, mode):
        if mode not in {"clock", "stopwatch", "timer"}:
            mode = "clock"
        self.clock_mode = mode
        self.apply_clock_settings()

    def set_timer_duration_minutes(self, minutes):
        try:
            minutes = max(1, min(int(minutes), 24 * 60))
        except (TypeError, ValueError):
            minutes = 5
        self.timer_duration_seconds = minutes * 60
        self.reset_timer()

    def start_timer(self):
        if not self.timer_running:
            self._timer_started_at = time.monotonic()
            self.timer_running = True
            self.apply_clock_settings()

    def pause_timer(self):
        if self.timer_running:
            self.timer_elapsed_seconds = self._current_timer_elapsed_seconds()
            self._timer_started_at = None
            self.timer_running = False
            self.apply_clock_settings()

    def toggle_timer_running(self):
        if self.timer_running:
            self.pause_timer()
        else:
            self.start_timer()

    def reset_timer(self):
        self.timer_elapsed_seconds = 0.0
        self.timer_running = False
        self._timer_started_at = None
        self.apply_clock_settings()

    def set_clock_show_seconds(self, show_seconds):
        self.clock_show_seconds = bool(show_seconds)
        self.apply_clock_settings()

    def increase_clock_size(self):
        self.clock_size = min(self.clock_size + 2, 72)
        self.apply_clock_settings()
        return self.clock_size

    def set_clock_size(self, size):
        self.clock_size = max(10, min(int(size), 72))
        self.apply_clock_settings()
        return self.clock_size

    def decrease_clock_size(self):
        self.clock_size = max(self.clock_size - 2, 10)
        self.apply_clock_settings()
        return self.clock_size

    def set_clock_position(self, position):
        valid = {"top-left", "top-right", "bottom-left", "bottom-right"}
        if position in valid:
            self.clock_position = position
            self.apply_clock_settings()

    # ── Student/teacher sync label ────────────────────────

    def _student_sync_label_config_js(self):
        return json.dumps({
            "visible": self.student_sync_label_visible,
            "labels": self.student_sync_label_map,
        })

    def apply_student_sync_label(self):
        self.web_view.page().runJavaScript(
            "window.setNumaStudentSyncLabelConfig && "
            f"window.setNumaStudentSyncLabelConfig({self._student_sync_label_config_js()});"
        )

    def set_student_sync_label(self, visible, label_map=None):
        self.student_sync_label_visible = bool(visible)
        if label_map is not None:
            self.student_sync_label_map = {
                str(key): int(value) for key, value in label_map.items()
            }
        self.apply_student_sync_label()

    # ── Borderless mode ───────────────────────────────────
    # Uses CSS injection to toggle borders without rebuilding

    def _borderless_css(self):
        if self.borderless:
            return """
            .slide-content, .continuous-document, .print-page {
                border: none !important;
                border-radius: 0 !important;
                box-shadow: none !important;
            }
            """
        return """
            .slide-content {
                border: 3px solid var(--border) !important;
                border-radius: var(--radius-lg) !important;
                box-shadow: 0 8px 0 var(--shadow) !important;
            }
            .continuous-document {
                border: 3px solid var(--border) !important;
                border-radius: var(--radius-lg) !important;
                box-shadow: 0 8px 0 var(--shadow) !important;
            }
            .print-page {
                border: 2px solid var(--border) !important;
                border-radius: var(--radius) !important;
                box-shadow: 0 2px 12px rgba(15, 23, 42, 0.24) !important;
            }
            """

    def _apply_borderless_css(self):
        self._inject_css(self._dynamic_state_css())

    def set_borderless(self, borderless):
        self.borderless = borderless
        self._apply_borderless_css()
        return self.borderless

    def toggle_borderless(self):
        self.set_borderless(not self.borderless)
        return self.borderless

    # ── Slide & Paper page navigation ─────────────────────

    def _emit_current_paper_page_state(self):
        if self.presentation_mode == "paper" and self._loaded:
            self.get_paper_page_state()

    def get_paper_page_state(self, callback=None):
        """Return and emit the currently visible printed page index and total pages."""
        if self.presentation_mode != "paper" or not self._loaded:
            if callback:
                callback({"page": 0, "total": 0})
            return
        js = """
        (function() {
            const pages = Array.from(document.querySelectorAll('.print-page'));
            const total = pages.length;
            if (!total) return JSON.stringify({ page: 0, total: 0 });
            const vh = window.innerHeight || document.documentElement.clientHeight || 1;
            let bestIndex = 0;
            let bestVisible = -1;
            for (let i = 0; i < total; i += 1) {
                const rect = pages[i].getBoundingClientRect();
                const visible = Math.max(0, Math.min(rect.bottom, vh) - Math.max(rect.top, 0));
                if (visible > bestVisible) {
                    bestVisible = visible;
                    bestIndex = i;
                }
            }
            return JSON.stringify({ page: bestIndex, total: total });
        })();
        """

        def capture(result):
            try:
                data = json.loads(result) if isinstance(result, str) else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                data = {}
            total = max(0, int(data.get("total", 0) or 0))
            page = max(0, min(int(data.get("page", 0) or 0), max(0, total - 1)))
            if total > 0:
                self._last_paper_position = {
                    "page": page,
                    "offset": float((self._last_paper_position or {}).get("offset", 0.0)),
                }
                self.paper_page_changed.emit(page, total)
            if callback:
                callback({"page": page, "total": total})

        self.web_view.page().runJavaScript(js, capture)

    def step_paper_page(self, delta, callback=None):
        """Scroll to the previous (-1) or next (+1) printed sheet in paper mode."""
        if self.presentation_mode != "paper" or not self._loaded:
            if callback:
                callback({"page": 0, "total": 0})
            return
        try:
            step = int(delta)
        except (TypeError, ValueError):
            step = 0
        js = f"""
        (function() {{
            const pages = Array.from(document.querySelectorAll('.print-page'));
            const total = pages.length;
            if (!total) return JSON.stringify({{ page: 0, total: 0 }});
            const vh = window.innerHeight || document.documentElement.clientHeight || 1;
            const currentScroll = window.scrollY || document.documentElement.scrollTop || 0;
            let currentIndex = 0;
            if (
                typeof window.__numaPaperPageIndex === 'number' &&
                typeof window.__numaPaperScrollY === 'number' &&
                Math.abs(currentScroll - window.__numaPaperScrollY) <= 6
            ) {{
                currentIndex = Math.max(0, Math.min(total - 1, window.__numaPaperPageIndex));
            }} else {{
                let bestVisible = -1;
                for (let i = 0; i < total; i += 1) {{
                    const rect = pages[i].getBoundingClientRect();
                    const visible = Math.max(0, Math.min(rect.bottom, vh) - Math.max(rect.top, 0));
                    if (visible > bestVisible) {{
                        bestVisible = visible;
                        currentIndex = i;
                    }}
                }}
            }}
            const targetIndex = Math.max(0, Math.min(total - 1, currentIndex + ({step})));
            const target = pages[targetIndex];
            let slideIndex = -1;
            const snippets = [];
            if (target) {{
                const rect = target.getBoundingClientRect();
                const targetTop = Math.max(0, currentScroll + rect.top - 12);
                window.scrollTo(0, targetTop);
                window.__numaPaperPageIndex = targetIndex;
                window.__numaPaperScrollY = window.scrollY || document.documentElement.scrollTop || targetTop;
                const rawSlide = target.getAttribute('data-source-slide-index') || target.getAttribute('data-slide-index');
                if (rawSlide !== null && rawSlide !== '') {{
                    const parsedSlide = parseInt(rawSlide, 10);
                    if (!Number.isNaN(parsedSlide)) slideIndex = parsedSlide;
                }}
                const bodyRoot = target.querySelector('.print-page-content') || target;
                const blocks = bodyRoot.querySelectorAll('h1, h2, h3, h4, h5, h6, p, li, blockquote, td, th, pre, figcaption');
                for (const el of blocks) {{
                    const txt = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (txt.length >= 6) {{
                        snippets.push(txt.slice(0, 120));
                        if (snippets.length >= 4) break;
                    }}
                }}
                if (!snippets.length) {{
                    const img = bodyRoot.querySelector('img[alt]');
                    if (img && img.alt && img.alt.trim()) {{
                        snippets.push(img.alt.trim().slice(0, 120));
                    }}
                }}
            }}
            return JSON.stringify({{ page: targetIndex, total: total, slideIndex: slideIndex, snippets: snippets }});
        }})();
        """

        def capture(result):
            try:
                data = json.loads(result) if isinstance(result, str) else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                data = {}
            total = max(0, int(data.get("total", 0) or 0))
            page = max(0, min(int(data.get("page", 0) or 0), max(0, total - 1)))
            raw_slide = data.get("slideIndex", -1)
            try:
                slide_index = int(raw_slide)
            except (TypeError, ValueError):
                slide_index = -1
            raw_snippets = data.get("snippets")
            snippets = [str(s) for s in raw_snippets if isinstance(s, str) and s.strip()] if isinstance(raw_snippets, list) else []
            if total > 0:
                self._last_paper_position = {"page": page, "offset": 0.0}
                self.paper_page_changed.emit(page, total)
            if callback:
                callback({
                    "page": page,
                    "total": total,
                    "slideIndex": slide_index,
                    "snippets": snippets,
                })

        self.web_view.page().runJavaScript(js, capture)

    def next_slide(self):
        if self.presentation_mode == "slide":
            self._last_known_slide_index += 1
            self._inject_js("window.nextSlide();")
        elif self.presentation_mode == "paper":
            self.step_paper_page(1)

    def prev_slide(self):
        if self.presentation_mode == "slide":
            self._last_known_slide_index = max(0, self._last_known_slide_index - 1)
            self._inject_js("window.prevSlide();")
        elif self.presentation_mode == "paper":
            self.step_paper_page(-1)

    def goto_slide(self, index):
        try:
            self._last_known_slide_index = max(0, int(index))
        except (TypeError, ValueError):
            self._last_known_slide_index = 0
        if self.presentation_mode == "slide":
            self._inject_js(f"window.gotoSlide({index});")
        elif self.presentation_mode == "paper":
            self._inject_js(
                "(function() { const page = document.querySelector("
                + json.dumps(f'.print-page[data-slide-index="{self._last_known_slide_index}"]')
                + "); if (page) { page.scrollIntoView({block: 'start'}); return true; } return false; })();"
            )

    def get_current_slide(self, callback):
        """Return the currently active slide index from the rendered preview."""
        js = """
        (function() {
            if (typeof window.currentSlide === 'number') return window.currentSlide;
            return 0;
        })();
        """
        def capture(result):
            try:
                self._last_known_slide_index = max(0, int(result))
            except (TypeError, ValueError):
                pass
            callback(result)

        self.web_view.page().runJavaScript(js, capture)

    def get_interactive_state(self, callback):
        """Return slide and image-overlay state for a mirrored presentation."""
        js = """
        (function() {
            if (typeof window.getNumaInteractiveState === 'function') {
                return JSON.stringify(window.getNumaInteractiveState());
            }
            return JSON.stringify({ slide: (typeof window.currentSlide === 'number' ? window.currentSlide : 0) });
        })();
        """

        def capture(result):
            try:
                state = json.loads(result) if isinstance(result, str) else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                state = {}
            if isinstance(state, dict):
                try:
                    self._last_known_slide_index = max(0, int(state.get("slide", 0)))
                except (TypeError, ValueError):
                    pass
            callback(state if isinstance(state, dict) else {})

        self.web_view.page().runJavaScript(js, capture)

    def apply_interactive_state(self, state, callback=None):
        """Apply a state captured from another PresentationView."""
        if not isinstance(state, dict):
            if callback:
                callback(False)
            return
        try:
            self._last_known_slide_index = max(0, int(state.get("slide", 0)))
        except (TypeError, ValueError):
            pass
        state_json = json.dumps(state)
        js = (
            "(function() {"
            "if (typeof window.applyNumaInteractiveState !== 'function') return false;"
            "window.applyNumaInteractiveState(" + state_json + ");"
            "return true;"
            "})();"
        )
        if callback:
            self.web_view.page().runJavaScript(js, lambda result: callback(bool(result)))
        else:
            self.web_view.page().runJavaScript(js)

    def restore_slide_after_next_load(self, index):
        """Request a slide jump as soon as the next HTML rebuild finishes."""
        try:
            self._pending_slide_index = max(0, int(index))
            self._last_known_slide_index = self._pending_slide_index
        except (TypeError, ValueError):
            self._pending_slide_index = 0
            self._last_known_slide_index = 0

    def close_image_zoom_if_open(self, callback=None):
        """Close the image zoom overlay if present, then report whether it handled Esc."""
        js = """
        (function() {
            if (window.isImageZoomOpen && window.isImageZoomOpen()) {
                if (window.closeImageZoom) window.closeImageZoom();
                return true;
            }
            return false;
        })();
        """
        # PySide6 interprets the second positional argument as ``worldId``;
        # passing None here raises ValueError. Use the one-argument overload
        # when no result callback is needed.
        if callback:
            self.web_view.page().runJavaScript(js, callback)
        else:
            self.web_view.page().runJavaScript(js)

    def adjust_image_zoom(self, delta):
        """Adjust the active image overlay zoom from presentation controls."""
        js = f"""
        (function() {{
            if (typeof window.adjustImageZoom !== 'function') return false;
            return window.adjustImageZoom({float(delta)});
        }})();
        """
        self.web_view.page().runJavaScript(js)

    def set_mobile_pointer(self, x, y, visible=True):
        """Position the Mobile-Link pointer over the active slide."""
        try:
            x = max(0.0, min(1.0, float(x)))
            y = max(0.0, min(1.0, float(y)))
        except (TypeError, ValueError):
            return
        js = (
            "window.setNumaMobilePointer && "
            f"window.setNumaMobilePointer({x}, {y}, {str(bool(visible)).lower()});"
        )
        self.web_view.page().runJavaScript(js)

    def set_mobile_pointer_config(self, size=24, shape="ring", color="#39FF14", trail=0, trail_mode="dots"):
        """Configure the Mobile-Link pointer appearance in the rendered slide."""
        config = {
            "size": max(8, min(96, int(size))),
            "shape": "dot" if shape == "dot" else "ring",
            "color": color if isinstance(color, str) else "#39FF14",
            "trail": max(0, min(48, int(trail))),
            "trail_mode": str(trail_mode),
        }
        self.web_view.page().runJavaScript(
            "window.setNumaMobilePointerConfig && "
            f"window.setNumaMobilePointerConfig({json.dumps(config)});"
        )

    def mobile_mouse_click(self, x, y, click_count=1):
        """Click an image or interactive presentation element at normalized coordinates."""
        try:
            x = max(0.0, min(1.0, float(x)))
            y = max(0.0, min(1.0, float(y)))
            click_count = max(1, min(2, int(click_count)))
        except (TypeError, ValueError):
            return
        self.web_view.page().runJavaScript(
            "window.mobileMouseClick && "
            f"window.mobileMouseClick({x}, {y}, {click_count});"
        )

    def mobile_mouse_move(self, x, y):
        """Move the conventional mouse surface over the active slide."""
        try:
            x = max(0.0, min(1.0, float(x)))
            y = max(0.0, min(1.0, float(y)))
        except (TypeError, ValueError):
            return
        self.web_view.page().runJavaScript(
            "window.mobileMouseMove && "
            f"window.mobileMouseMove({x}, {y});"
        )

    def mobile_mouse_scroll(self, x, y, delta_y):
        """Scroll the active rendered presentation from Mobile mouse mode."""
        try:
            x = max(0.0, min(1.0, float(x)))
            y = max(0.0, min(1.0, float(y)))
            delta_y = max(-1.0, min(1.0, float(delta_y)))
        except (TypeError, ValueError):
            return
        self.web_view.page().runJavaScript(
            "window.mobileMouseScroll && "
            f"window.mobileMouseScroll({x}, {y}, {delta_y});"
        )

    def open_current_slide_image(self, callback=None):
        """Open the first image in the active slide, if one exists."""
        js = """
        (function() {
            const slides = document.querySelectorAll('.slide');
            const slide = slides[window.currentSlide || 0];
            const image = slide ? slide.querySelector('img') : null;
            if (!image || typeof window.openImageZoom !== 'function') return false;
            window.openImageZoom(image);
            return true;
        })();
        """
        if callback:
            self.web_view.page().runJavaScript(js, lambda result: callback(bool(result)))
        else:
            self.web_view.page().runJavaScript(js)
