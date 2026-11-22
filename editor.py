import os
import re
import shutil
import tempfile
from PySide6.QtCore import Qt, QMimeData, QUrl, Signal, QRegularExpression
from PySide6.QtWidgets import (
    QWidget, QPlainTextEdit, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QRadioButton, QPushButton, QButtonGroup, QCheckBox,
    QFileDialog, QMessageBox
)
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QTextCursor, QFont,
    QSyntaxHighlighter, QTextCharFormat, QColor, QPainter
)


# ─────────────────────────────────────────────────────────────
# Markdown Syntax Highlighter
# ─────────────────────────────────────────────────────────────

class MarkdownHighlighter(QSyntaxHighlighter):
    """
    Basic syntax highlighter for Markdown.
    Uses NUMA color tokens for the highlight styles.
    """

    def __init__(self, parent=None, is_dark=False):
        super().__init__(parent)
        self.is_dark = is_dark
        self._update_rules()

    def set_dark_mode(self, is_dark):
        self.is_dark = is_dark
        self._update_rules()
        self.rehighlight()

    def _update_rules(self):
        # NUMA colors
        if self.is_dark:
            color_heading = QColor("#2563FF")   # Electric Blue
            color_bold = QColor("#FFB347")      # Mango
            color_italic = QColor("#2EE6C5")    # Mint
            color_code = QColor("#A8F5E4")      # Mint Soft
            color_link = QColor("#0A84FF")      # Deep Blue
            color_comment = QColor("#6B7280")   # Neutral
            color_list = QColor("#FFB347")      # Mango
            color_blockquote = QColor("#2563FF")
            color_hr = QColor("#6B7280")
            color_image = QColor("#2EE6C5")
        else:
            color_heading = QColor("#0A84FF")   # Deep Blue
            color_bold = QColor("#FF8A00")      # Mango Strong
            color_italic = QColor("#059669")
            color_code = QColor("#6D28D9")      # Purple
            color_link = QColor("#2563FF")      # Electric Blue
            color_comment = QColor("#9CA3AF")
            color_list = QColor("#FF8A00")
            color_blockquote = QColor("#2563FF")
            color_hr = QColor("#9CA3AF")
            color_image = QColor("#059669")

        self._rules = []

        # Headings (# ... ######)
        fmt_h = QTextCharFormat()
        fmt_h.setForeground(color_heading)
        fmt_h.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r'^#{1,6}\s.*$'), fmt_h))

        # Bold (**text**)
        fmt_bold = QTextCharFormat()
        fmt_bold.setForeground(color_bold)
        fmt_bold.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r'\*\*[^*]+\*\*'), fmt_bold))
        self._rules.append((QRegularExpression(r'__[^_]+__'), fmt_bold))

        # Italic (*text*)
        fmt_italic = QTextCharFormat()
        fmt_italic.setForeground(color_italic)
        fmt_italic.setFontItalic(True)
        self._rules.append((QRegularExpression(r'(?<!\*)\*(?!\*)[^*]+\*(?!\*)'), fmt_italic))
        self._rules.append((QRegularExpression(r'(?<!_)_(?!_)[^_]+_(?!_)'), fmt_italic))

        # Inline code (`code`)
        fmt_code = QTextCharFormat()
        fmt_code.setForeground(color_code)
        fmt_code.setFontFamily("Consolas, Courier New, monospace")
        self._rules.append((QRegularExpression(r'`[^`]+`'), fmt_code))

        # Links [text](url)
        fmt_link = QTextCharFormat()
        fmt_link.setForeground(color_link)
        fmt_link.setFontUnderline(True)
        self._rules.append((QRegularExpression(r'\[([^\]]+)\]\([^\)]+\)'), fmt_link))

        # Images ![alt](url)
        fmt_image = QTextCharFormat()
        fmt_image.setForeground(color_image)
        self._rules.append((QRegularExpression(r'!\[([^\]]*)\]\([^\)]+\)'), fmt_image))

        # Lists (- item, * item, 1. item)
        fmt_list = QTextCharFormat()
        fmt_list.setForeground(color_list)
        self._rules.append((QRegularExpression(r'^\s*[-*+]\s'), fmt_list))
        self._rules.append((QRegularExpression(r'^\s*\d+\.\s'), fmt_list))

        # Blockquote (> text)
        fmt_bq = QTextCharFormat()
        fmt_bq.setForeground(color_blockquote)
        self._rules.append((QRegularExpression(r'^\s*>.*$'), fmt_bq))

        # Horizontal rule (--- or ***)
        fmt_hr = QTextCharFormat()
        fmt_hr.setForeground(color_hr)
        self._rules.append((QRegularExpression(r'^\s*[-*_]{3,}\s*$'), fmt_hr))

        # Slide delimiter (standalone ---)
        fmt_delim = QTextCharFormat()
        fmt_delim.setForeground(color_hr)
        fmt_delim.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r'^\s*---\s*$'), fmt_delim))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            match_iter = pattern.globalMatch(text)
            while match_iter.hasNext():
                match = match_iter.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


# ─────────────────────────────────────────────────────────────
# Line Number Area
# ─────────────────────────────────────────────────────────────

class LineNumberArea(QWidget):
    """Widget that draws line numbers next to the editor."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return self.editor.line_number_area_size_hint()

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


# ─────────────────────────────────────────────────────────────
# Image Drop Dialog (NUMA Neobrutalist)
# ─────────────────────────────────────────────────────────────

class ImageDropDialog(QDialog):
    """
    NUMA-styled prompt for determining where to save dropped images.
    """
    def __init__(self, parent=None, is_dark=False):
        super().__init__(parent)
        self.setWindowTitle("Guardar Imagen - NUMA Deck")
        self.resize(480, 320)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.is_dark = is_dark

        # Colors from NUMA style
        self.bg_color = "#0E1324" if is_dark else "#F7FAFF"
        self.surface_color = "#141B2F" if is_dark else "#FFFFFF"
        self.text_color = "#EEF2FF" if is_dark else "#111827"
        self.border_color = "#EEF2FF" if is_dark else "#0B0F1A"
        self.accent_color = "#FFB347"   # Mango
        self.primary_color = "#2563FF"  # Electric Blue
        self.secondary_text = "#9CA3AF" if is_dark else "#6B7280"

        self.init_ui()
        self.apply_style()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        title_label = QLabel("⚡ Imagen detectada", self)
        title_font = QFont("Inter", 18, QFont.Bold)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        subtitle_label = QLabel(
            "Selecciona cómo deseas guardar y vincular esta imagen a tu documento:",
            self
        )
        subtitle_font = QFont("Inter", 11)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setStyleSheet(f"color: {self.secondary_text};")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)

        layout.addSpacing(4)

        # Radio options
        self.options_group = QButtonGroup(self)

        self.opt_assets = QRadioButton(
            "Guardar en carpeta 'assets/' al lado del documento (Recomendado)", self
        )
        self.opt_assets.setChecked(True)
        self.options_group.addButton(self.opt_assets, 1)
        layout.addWidget(self.opt_assets)

        self.opt_temp = QRadioButton(
            "Guardar en carpeta temporal global de la aplicación", self
        )
        self.options_group.addButton(self.opt_temp, 2)
        layout.addWidget(self.opt_temp)

        self.opt_absolute = QRadioButton(
            "Mantener ruta absoluta original (No copiar el archivo)", self
        )
        self.options_group.addButton(self.opt_absolute, 3)
        layout.addWidget(self.opt_absolute)

        # Remember checkbox
        self.remember_cb = QCheckBox("Recordar mi elección para este archivo", self)
        self.remember_cb.setStyleSheet("margin-top: 8px;")
        layout.addWidget(self.remember_cb)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.cancel_btn = QPushButton("Cancelar", self)
        self.cancel_btn.clicked.connect(self.reject)

        self.confirm_btn = QPushButton("Vincular imagen", self)
        self.confirm_btn.setObjectName("primaryBtn")
        self.confirm_btn.clicked.connect(self.accept)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.confirm_btn)
        layout.addLayout(btn_layout)

    def apply_style(self):
        stylesheet = f"""
        QDialog {{
            background-color: {self.bg_color};
            border: 3px solid {self.border_color};
            border-radius: 14px;
        }}

        QLabel {{
            color: {self.text_color};
            background: transparent;
        }}

        QRadioButton {{
            color: {self.text_color};
            font-size: 13px;
            spacing: 10px;
            padding: 6px 0;
        }}

        QRadioButton::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid {self.border_color};
            border-radius: 10px;
            background-color: {self.surface_color};
        }}

        QRadioButton::indicator:checked {{
            background-color: {self.primary_color};
            border: 2px solid {self.primary_color};
        }}

        QCheckBox {{
            color: {self.secondary_text};
            font-size: 12px;
            font-weight: 500;
        }}

        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid {self.border_color};
            border-radius: 5px;
            background-color: {self.surface_color};
        }}

        QCheckBox::indicator:checked {{
            background-color: {self.accent_color};
            border: 2px solid {self.accent_color};
        }}

        QPushButton {{
            background-color: {self.surface_color};
            color: {self.text_color};
            border: 2px solid {self.border_color};
            border-radius: 10px;
            padding: 10px 20px;
            font-weight: bold;
            font-size: 13px;
        }}

        QPushButton:hover {{
            background-color: #4B5563;
            color: #FFFFFF;
        }}

        QPushButton:pressed {{
            margin-top: 2px;
            margin-left: 2px;
        }}

        QPushButton#primaryBtn {{
            background-color: {self.primary_color};
            color: #FFFFFF;
        }}

        QPushButton#primaryBtn:hover {{
            background-color: #0A84FF;
        }}
        """
        self.setStyleSheet(stylesheet)

    def get_choice(self):
        return self.options_group.checkedId(), self.remember_cb.isChecked()


# ─────────────────────────────────────────────────────────────
# Markdown Editor (Main Component)
# ─────────────────────────────────────────────────────────────

class MarkdownEditor(QPlainTextEdit):
    """
    Custom Markdown PlainTextEdit supporting:
    - Drag & Drop for images with NUMA dialog
    - Syntax highlighting
    - Line numbers
    - Tab handling
    """
    image_dropped = Signal(str)
    markdown_file_dropped = Signal(str)
    cursor_position_changed = Signal(int, int)  # line, col
    word_count_changed = Signal(int)  # word count
    scroll_to_slide = Signal(int)  # slide index based on cursor position

    def __init__(self, parent=None, is_dark=False):
        super().__init__(parent)
        self.is_dark = is_dark
        self.setAcceptDrops(True)
        self.document_path = None
        self.saved_choice = None
        self.image_link_choice_changed = None

        # Tab handling
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)

        # Placeholder
        self.setPlaceholderText(
            "Escribe tu Markdown aqui...\n"
            "Usa '---' en una linea sola para separar diapositivas.\n"
            "Arrastra imagenes para insertarlas directamente."
        )

        # Syntax highlighter
        self.highlighter = MarkdownHighlighter(self.document(), is_dark=is_dark)

        # Line numbers
        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.cursorPositionChanged.connect(self._emit_cursor_position)
        self.cursorPositionChanged.connect(self._emit_slide_for_cursor)
        self.textChanged.connect(self._emit_word_count)
        self.textChanged.connect(self._hide_internal_metadata_blocks)
        self._update_line_number_area_width(0)

        # Initial state
        self._highlight_current_line()
        self._hide_internal_metadata_blocks()

    def set_document_path(self, path):
        self.document_path = path

    def set_dark_mode(self, is_dark):
        self.is_dark = is_dark
        self.highlighter.set_dark_mode(is_dark)

    def setPlainText(self, text):
        super().setPlainText(text)
        self._hide_internal_metadata_blocks()

    def _hide_internal_metadata_blocks(self):
        """Keep NUMA slide IDs in the file while hiding them from the editor view."""
        pattern = re.compile(r'^\s*<!--\s*numa-(?:slide|sync)-id:\s*[a-zA-Z0-9_-]+\s*-->\s*$')
        block = self.document().firstBlock()
        changed = False
        while block.isValid():
            should_hide = bool(pattern.match(block.text()))
            if block.isVisible() == should_hide:
                block.setVisible(not should_hide)
                try:
                    block.setLineCount(0 if should_hide else 1)
                except AttributeError:
                    pass
                changed = True
            block = block.next()

        if changed:
            self.document().markContentsDirty(0, self.document().characterCount())
            self._update_line_number_area_width(0)
            self.viewport().update()

    # ── Line Numbers ──────────────────────────────────────

    def line_number_area_size_hint(self):
        digits = max(1, len(str(self.blockCount())))
        space = 12 + self.fontMetrics().horizontalAdvance('9') * digits + 12
        return space

    def _update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_size_hint(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            cr.left(), cr.top(), self.line_number_area_size_hint(), cr.height()
        )

    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_number_area)

        if self.is_dark:
            bg = QColor("#141B2F")
            text_color = QColor("#6B7280")
            active_color = QColor("#EEF2FF")
        else:
            bg = QColor("#FFFFFF")
            text_color = QColor("#9CA3AF")
            active_color = QColor("#111827")

        painter.fillRect(event.rect(), bg)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        current_line = self.textCursor().blockNumber()

        font = QFont("Consolas", 10)
        painter.setFont(font)

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number == current_line:
                    painter.setPen(active_color)
                    font.setBold(True)
                    painter.setFont(font)
                else:
                    painter.setPen(text_color)
                    font.setBold(False)
                    painter.setFont(font)

                painter.drawText(
                    0, top, self._line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignRight | Qt.AlignVCenter, number
                )

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

        painter.end()

    def _highlight_current_line(self):
        extra_selections = []
        if not self.isReadOnly():
            from PySide6.QtWidgets import QTextEdit
            selection = QTextEdit.ExtraSelection()
            if self.is_dark:
                selection.format.setBackground(QColor("#1E2740"))
            else:
                selection.format.setBackground(QColor("#F0F4FF"))
            selection.format.setProperty(QTextCharFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        self.setExtraSelections(extra_selections)

    def _emit_cursor_position(self):
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self.cursor_position_changed.emit(line, col)

    def _emit_word_count(self):
        text = self.toPlainText().strip()
        if text:
            words = len(text.split())
        else:
            words = 0
        self.word_count_changed.emit(words)

    def _emit_slide_for_cursor(self):
        """Determine which slide the cursor is on and emit scroll_to_slide."""
        self.scroll_to_slide.emit(self.current_slide_index())

    def current_slide_index(self):
        """Return the slide index where the text cursor is located."""
        cursor = self.textCursor()
        current_block = cursor.blockNumber()  # 0-indexed
        text = self.toPlainText()
        lines = text.split('\n')

        # Keep this calculation aligned with parser._split_slide_sections:
        # empty sections and sections containing only NUMA metadata are not
        # rendered, so their separators must not advance the preview index.
        slide_index = 0
        section_lines = []
        for i in range(min(current_block, len(lines))):
            line = lines[i].strip()
            if line == '---':
                section = '\n'.join(section_lines)
                visible = re.sub(
                    r'<!--\s*numa-(?:slide|sync)-id:\s*[^>]*-->',
                    '',
                    section,
                )
                if visible.strip():
                    slide_index += 1
                section_lines = []
            else:
                section_lines.append(lines[i])
        return slide_index

    # ── Key Events ────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Tab:
            self.insertPlainText("    ")
        elif event.key() == Qt.Key_Backtab:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.Up, QTextCursor.MoveAnchor)
            cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.MoveAnchor)
            cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            text = cursor.selectedText()
            if text.startswith("    "):
                cursor.insertText(text[4:])
        elif event.key() == Qt.Key_B and event.modifiers() & Qt.ControlModifier:
            self._toggle_inline("**")
        elif event.key() == Qt.Key_I and event.modifiers() & Qt.ControlModifier:
            self._toggle_inline("*")
        elif event.key() == Qt.Key_K and event.modifiers() & Qt.ControlModifier:
            self._insert_link()
        else:
            super().keyPressEvent(event)

    def _toggle_inline(self, marker):
        cursor = self.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            cursor.insertText(f"{marker}{text}{marker}")
        else:
            cursor.insertText(f"{marker}{marker}")
            cursor.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, len(marker))
            self.setTextCursor(cursor)

    def _insert_link(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            cursor.insertText(f"[{text}](url)")
        else:
            cursor.insertText("[texto](url)")

    # ── Drag & Drop ───────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if self._is_image_file(file_path) or self._is_markdown_file(file_path):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            for url in mime_data.urls():
                file_path = url.toLocalFile()
                if self._is_markdown_file(file_path):
                    event.acceptProposedAction()
                    self.markdown_file_dropped.emit(file_path)
                    continue
                if self._is_image_file(file_path):
                    event.acceptProposedAction()
                    self._process_image_drop(file_path)
                    break
        else:
            super().dropEvent(event)

    @staticmethod
    def _is_image_file(path):
        _, ext = os.path.splitext(path.lower())
        return ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg')

    @staticmethod
    def _is_markdown_file(path):
        _, ext = os.path.splitext(path.lower())
        return ext in ('.md', '.markdown')

    def _process_image_drop(self, file_path):
        choice = self.saved_choice
        remember = False

        if choice is None:
            dialog = ImageDropDialog(self, is_dark=self.is_dark)
            if dialog.exec() == QDialog.Accepted:
                choice, remember = dialog.get_choice()
                if remember:
                    self.saved_choice = choice
                    if callable(self.image_link_choice_changed):
                        self.image_link_choice_changed(choice)
            else:
                return

        target_path = file_path

        if choice == 1:
            target_path = self._copy_to_assets(file_path)
        elif choice == 2:
            target_path = self._copy_to_temp(file_path)
        elif choice == 3:
            target_path = file_path.replace('\\', '/')

        if target_path is None:
            return

        cursor = self.textCursor()
        img_name = os.path.splitext(os.path.basename(file_path))[0]
        markdown_code = f"![{img_name}]({target_path})"
        cursor.insertText(markdown_code)
        self.image_dropped.emit(target_path)

    def _copy_to_assets(self, file_path):
        if self.document_path:
            doc_dir = os.path.dirname(self.document_path)
        else:
            doc_dir = os.getcwd()

        assets_dir = os.path.join(doc_dir, "assets")
        os.makedirs(assets_dir, exist_ok=True)

        filename = os.path.basename(file_path)
        dest = os.path.join(assets_dir, filename)
        dest = self._unique_path(dest)

        try:
            shutil.copy2(file_path, dest)
            if self.document_path:
                return os.path.relpath(dest, doc_dir).replace('\\', '/')
            else:
                return f"assets/{os.path.basename(dest)}"
        except Exception as e:
            QMessageBox.critical(
                self, "Error al copiar",
                f"No se pudo copiar la imagen a assets:\n{e}"
            )
            return None

    def _copy_to_temp(self, file_path):
        temp_dir = os.path.join(tempfile.gettempdir(), "numa_deck_assets")
        os.makedirs(temp_dir, exist_ok=True)

        filename = os.path.basename(file_path)
        dest = os.path.join(temp_dir, filename)
        dest = self._unique_path(dest)

        try:
            shutil.copy2(file_path, dest)
            return dest.replace('\\', '/')
        except Exception as e:
            QMessageBox.critical(
                self, "Error al copiar",
                f"No se pudo copiar la imagen a temporales:\n{e}"
            )
            return None

    @staticmethod
    def _unique_path(dest):
        if not os.path.exists(dest):
            return dest
        directory, filename = os.path.split(dest)
        name, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(os.path.join(directory, f"{name}_{counter}{ext}")):
            counter += 1
        return os.path.join(directory, f"{name}_{counter}{ext}")
