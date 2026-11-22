"""NUMA-styled onboarding dialogs: Template Picker and Quick Markdown Guide."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from styles import DARK_THEME, LIGHT_THEME


DOCUMENT_TEMPLATES = (
    (
        "blank",
        "Presentación básica",
        "Portada y una primera diapositiva lista para empezar desde cero.",
        "2 diapositivas",
        """# Título de tu presentación

Subtítulo o nombre del expositor

---

## Primera diapositiva

- Idea principal 1
- Idea principal 2
- Idea principal 3
""",
    ),
    (
        "class",
        "Clase o conferencia",
        "Estructura didáctica con portada, agenda, temas, actividad y cierre.",
        "5 diapositivas",
        """# Nombre de la clase o sesión

**Tema principal** · Fecha o grupo

---

## Agenda de hoy

1. Introducción y objetivo
2. Conceptos clave
3. Ejemplo práctico
4. Conclusiones y preguntas

---

## Conceptos clave

- **Concepto A:** explicación breve y clara.
- **Concepto B:** punto relevante para recordar.

> Destaca aquí la idea más importante de la sesión.

---

## Actividad práctica

1. Analiza el caso propuesto en equipo.
2. Identifica al menos dos soluciones posibles.
3. Comparte tus conclusiones en plenaria.

---

## Resumen y preguntas

- Repaso de los 3 puntos clave de la sesión.
- ¿Dudas o comentarios?
""",
    ),
    (
        "pitch",
        "Propuesta o proyecto",
        "Flujo ejecutivo: problema, solución, beneficios y siguientes pasos.",
        "5 diapositivas",
        """# Nombre del proyecto

Propuesta de valor en una frase clara

---

## El problema

- ¿Qué necesidad o fricción existe hoy?
- ¿A quién afecta y cuál es su impacto?

---

## Nuestra solución

Describe en 2 o 3 puntos cómo resuelve el problema de forma simple y medible.

- **Simple:** fácil de adoptar.
- **Rápido:** resultados desde el primer día.

---

## Beneficios clave

| Aspecto | Situación actual | Con la propuesta |
| --- | --- | --- |
| Tiempo | Proceso manual | Flujo automatizado |
| Claridad | Información dispersa | Vista unificada |

---

## Próximos pasos

1. Validar alcance y fechas.
2. Ejecutar fase piloto.
3. Revisar resultados y escalar.
""",
    ),
    (
        "guide",
        "Guía interactiva NUMA",
        "Documento de ejemplo para aprender a usar NUMA Deck en 1 minuto.",
        "4 diapositivas",
        None,  # Resolved dynamically to DEFAULT_MARKDOWN
    ),
)


MARKDOWN_SNIPPETS = (
    (
        "Nueva diapositiva",
        "Separa tu contenido en una nueva diapositiva con tres guiones.",
        "---",
        "\n---\n\n## Nueva diapositiva\n\n",
    ),
    (
        "Título y subtítulo",
        "Encabezados principales para portada o inicio de sección.",
        "# Título\n## Subtítulo",
        "# Título principal\n\n## Subtítulo descriptivo\n",
    ),
    (
        "Lista con viñetas",
        "Organiza ideas clave en puntos cortos y fáciles de leer.",
        "- Punto 1\n- Punto 2",
        "- Punto clave 1\n- Punto clave 2\n- Punto clave 3\n",
    ),
    (
        "Tabla rápida",
        "Compara datos o muestra agendas estructuradas.",
        "| Columna A | Columna B |",
        "| Columna 1 | Columna 2 |\n| --- | --- |\n| Dato A | Dato B |\n| Dato C | Dato D |\n",
    ),
    (
        "Cita destacada",
        "Resalta una frase, definición o conclusión importante.",
        "> Idea destacada",
        "> Escribe aquí una idea o frase importante para destacar.\n",
    ),
    (
        "Fórmula matemática",
        "Escribe ecuaciones renderizadas con KaTeX.",
        "$$ E = mc^2 $$",
        "$$\nE = mc^2\n$$\n",
    ),
    (
        "Bloque de código",
        "Muestra fragmentos de código con resaltado de sintaxis.",
        "```python ... ```",
        "```python\ndef saludar(nombre):\n    print(f\"Hola, {nombre}\")\n```\n",
    ),
)


ESSENTIAL_SHORTCUTS = (
    ("F11 / F5", "Iniciar o salir de la presentación en pantalla completa"),
    ("← / → / Espacio", "Ir a la diapositiva anterior o siguiente al presentar"),
    ("Esc", "Salir del modo presentación"),
    ("Ctrl + S", "Guardar el documento actual"),
    ("Ctrl + O", "Abrir un documento Markdown"),
    ("Ctrl + E", "Abrir vista previa y exportar a PDF"),
    ("Ctrl + Shift + M", "Mostrar u ocultar la barra de formato Markdown"),
    ("Ctrl + F / Ctrl + H", "Buscar o reemplazar texto en el editor"),
    ("Ctrl + + / − / 0", "Aumentar, disminuir o restablecer zoom al 100%"),
    ("F8", "Alternar modo Sin Marco en las diapositivas"),
)


def _dialog_stylesheet(is_dark):
    t = DARK_THEME if is_dark else LIGHT_THEME
    card_hover = "rgba(37, 99, 255, 0.16)" if is_dark else "rgba(37, 99, 255, 0.08)"
    badge_bg = "rgba(46, 230, 197, 0.16)" if is_dark else "rgba(46, 230, 197, 0.22)"
    badge_text = "#A8F5E4" if is_dark else "#0F766E"
    code_bg = "#0E1324" if is_dark else "#F1F5F9"
    return f"""
        QDialog {{
            background-color: {t['background']};
            color: {t['text-primary']};
        }}
        QLabel#dialogTitle {{
            color: {t['text-primary']};
            font-size: 20px;
            font-weight: 800;
        }}
        QLabel#dialogSubtitle {{
            color: {t['text-secondary']};
            font-size: 13px;
        }}
        QFrame#numaCard {{
            background-color: {t['surface']};
            border: 1.5px solid {t['border-subtle']};
            border-radius: 14px;
        }}
        QFrame#numaCard:hover {{
            border-color: {t['electric-blue']};
            background-color: {card_hover};
        }}
        QLabel#cardTitle {{
            color: {t['text-primary']};
            font-size: 14px;
            font-weight: 700;
        }}
        QLabel#cardDesc {{
            color: {t['text-secondary']};
            font-size: 12px;
        }}
        QLabel#cardBadge {{
            background-color: {badge_bg};
            color: {badge_text};
            border-radius: 999px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: 700;
        }}
        QLabel#codePreview {{
            background-color: {code_bg};
            color: {t['text-primary']};
            border: 1px solid {t['border-subtle']};
            border-radius: 8px;
            padding: 4px 8px;
            font-family: 'Consolas', 'Cascadia Code', monospace;
            font-size: 11px;
        }}
        QLabel#shortcutKey {{
            background-color: {t['surface-alt']};
            color: {t['text-primary']};
            border: 1px solid {t['border-subtle']};
            border-radius: 8px;
            padding: 4px 10px;
            font-family: 'Consolas', 'Cascadia Code', monospace;
            font-size: 12px;
            font-weight: 700;
        }}
        QTabWidget::pane {{
            border: 1.5px solid {t['border-subtle']};
            border-radius: 12px;
            background-color: {t['surface']};
            padding: 8px;
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
            font-size: 12px;
        }}
        QTabBar::tab:selected {{
            background-color: {t['electric-blue']};
            color: #FFFFFF;
            border-color: {t['electric-blue']};
        }}
        QScrollArea {{
            border: none;
            background: transparent;
        }}
    """


class TemplatePickerDialog(QDialog):
    """NUMA-styled dialog to create a new presentation from a ready-made template."""

    def __init__(self, default_markdown="", is_dark=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nueva presentación desde plantilla — NUMA Deck")
        self.resize(680, 460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.selected_content = None
        self._default_markdown = default_markdown

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        title = QLabel("Elige cómo empezar", self)
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Selecciona una plantilla para abrir una nueva pestaña con estructura lista para editar.",
            self,
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        grid = QGridLayout()
        grid.setSpacing(12)
        for index, (tpl_id, name, desc, badge, content) in enumerate(DOCUMENT_TEMPLATES):
            card = QFrame(self)
            card.setObjectName("numaCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(8)

            top_row = QHBoxLayout()
            name_lbl = QLabel(name, card)
            name_lbl.setObjectName("cardTitle")
            badge_lbl = QLabel(badge, card)
            badge_lbl.setObjectName("cardBadge")
            top_row.addWidget(name_lbl)
            top_row.addStretch(1)
            top_row.addWidget(badge_lbl)
            card_layout.addLayout(top_row)

            desc_lbl = QLabel(desc, card)
            desc_lbl.setObjectName("cardDesc")
            desc_lbl.setWordWrap(True)
            card_layout.addWidget(desc_lbl)
            card_layout.addStretch(1)

            use_btn = QPushButton("Usar plantilla", card)
            use_btn.setObjectName("primaryBtn" if index == 0 else "softBlueBtn")
            resolved_content = self._default_markdown if content is None else content
            use_btn.clicked.connect(
                lambda checked=False, text=resolved_content: self._select_template(text)
            )
            card_layout.addWidget(use_btn, alignment=Qt.AlignmentFlag.AlignRight)

            grid.addWidget(card, index // 2, index % 2)

        root.addLayout(grid, stretch=1)

        buttons = QDialogButtonBox(self)
        cancel_btn = buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_btn.clicked.connect(self.reject)
        root.addWidget(buttons)

        self.setStyleSheet(_dialog_stylesheet(is_dark))

    def _select_template(self, content):
        self.selected_content = content
        self.accept()


class QuickGuideDialog(QDialog):
    """NUMA-styled Quick Markdown & Shortcuts Guide with 1-click snippet insertion."""

    def __init__(self, on_insert=None, is_dark=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Guía rápida — NUMA Deck")
        self.resize(680, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._on_insert = on_insert

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(12)

        title = QLabel("Guía rápida de NUMA Deck", self)
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Aprende los bloques esenciales de Markdown e insértalos con un clic, o consulta los atajos principales.",
            self,
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_snippets_tab(), "Bloques Markdown")
        tabs.addTab(self._build_shortcuts_tab(), "Atajos esenciales")
        root.addWidget(tabs, stretch=1)

        buttons = QDialogButtonBox(self)
        close_btn = buttons.addButton("Cerrar", QDialogButtonBox.ButtonRole.AcceptRole)
        close_btn.clicked.connect(self.accept)
        root.addWidget(buttons)

        self.setStyleSheet(_dialog_stylesheet(is_dark))

    def _build_snippets_tab(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget(scroll)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        for name, desc, preview_code, snippet in MARKDOWN_SNIPPETS:
            row_card = QFrame(inner)
            row_card.setObjectName("numaCard")
            row_layout = QHBoxLayout(row_card)
            row_layout.setContentsMargins(14, 10, 14, 10)
            row_layout.setSpacing(12)

            info_col = QVBoxLayout()
            info_col.setSpacing(4)
            name_lbl = QLabel(name, row_card)
            name_lbl.setObjectName("cardTitle")
            desc_lbl = QLabel(desc, row_card)
            desc_lbl.setObjectName("cardDesc")
            desc_lbl.setWordWrap(True)
            code_lbl = QLabel(preview_code, row_card)
            code_lbl.setObjectName("codePreview")
            info_col.addWidget(name_lbl)
            info_col.addWidget(desc_lbl)
            info_col.addWidget(code_lbl, alignment=Qt.AlignmentFlag.AlignLeft)
            row_layout.addLayout(info_col, stretch=1)

            insert_btn = QPushButton("Insertar", row_card)
            insert_btn.setObjectName("softBlueBtn")
            insert_btn.setToolTip(f"Insertar '{name}' en el editor activo")
            insert_btn.clicked.connect(
                lambda checked=False, text=snippet: self._insert_snippet(text)
            )
            row_layout.addWidget(insert_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(row_card)

        layout.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    def _build_shortcuts_tab(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget(scroll)
        grid = QGridLayout(inner)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        for row, (keys, description) in enumerate(ESSENTIAL_SHORTCUTS):
            key_lbl = QLabel(keys, inner)
            key_lbl.setObjectName("shortcutKey")
            key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_lbl = QLabel(description, inner)
            desc_lbl.setObjectName("cardDesc")
            desc_lbl.setWordWrap(True)
            grid.addWidget(key_lbl, row, 0)
            grid.addWidget(desc_lbl, row, 1)

        grid.setColumnStretch(1, 1)
        grid.setRowStretch(len(ESSENTIAL_SHORTCUTS), 1)
        scroll.setWidget(inner)
        return scroll

    def _insert_snippet(self, snippet):
        if callable(self._on_insert):
            self._on_insert(snippet)
