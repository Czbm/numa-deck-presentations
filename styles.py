"""
NUMA Deck Presentations - Style System
Implements the NUMA Design System tokens for PySide6 and HTML rendering.
"""

from pathlib import Path
import json


KATEX_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "katex"
KATEX_CSS_URL = (KATEX_ASSET_DIR / "katex.min.css").as_uri()
KATEX_JS_URL = (KATEX_ASSET_DIR / "katex.min.js").as_uri()
KATEX_AUTORENDER_JS_URL = (KATEX_ASSET_DIR / "auto-render.min.js").as_uri()
ICONS_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "icons"
CHEVRON_DOWN_LIGHT_PATH = (ICONS_ASSET_DIR / "chevron-down-light.svg").as_posix()
CHEVRON_DOWN_DARK_PATH = (ICONS_ASSET_DIR / "chevron-down-dark.svg").as_posix()

# ─────────────────────────────────────────────────────────────
# NUMA Design Tokens
# ─────────────────────────────────────────────────────────────

LIGHT_THEME = {
    "background": "#F7FAFF",
    "surface": "#FFFFFF",
    "surface-alt": "#F1F5F9",
    "text-primary": "#111827",
    "text-secondary": "#4B5563",
    "text-muted": "#9CA3AF",
    "border": "#0B0F1A",
    "border-subtle": "#CBD5E1",
    "shadow": "#0B0F1A",
    "electric-blue": "#2563FF",
    "deep-blue": "#0A84FF",
    "mango": "#FFB347",
    "mango-strong": "#FF8A00",
    "mint": "#2EE6C5",
    "mint-soft": "#A8F5E4",
    "focus-ring": "#2563FF",
}

DARK_THEME = {
    "background": "#0E1324",
    "surface": "#141B2F",
    "surface-alt": "#1A2340",
    "text-primary": "#EEF2FF",
    "text-secondary": "#9CA3AF",
    "text-muted": "#6B7280",
    "border": "#EEF2FF",
    "border-subtle": "#2A3555",
    "shadow": "#000000",
    "electric-blue": "#2563FF",
    "deep-blue": "#0A84FF",
    "mango": "#FFB347",
    "mango-strong": "#FF8A00",
    "mint": "#2EE6C5",
    "mint-soft": "#A8F5E4",
    "focus-ring": "#2563FF",
}

FONTS = {
    "brand": "'Cabinet Grotesk', 'Arial Black', Impact, sans-serif",
    "functional": "'Inter', 'Segoe UI', Arial, sans-serif",
    "monospace": "'Consolas', 'Cascadia Code', 'Courier New', monospace",
}


# ─────────────────────────────────────────────────────────────
# QSS Stylesheet (PySide6 Widgets)
# ─────────────────────────────────────────────────────────────

def get_app_stylesheet(is_dark=False):
    t = DARK_THEME if is_dark else LIGHT_THEME
    chevron_path = CHEVRON_DOWN_DARK_PATH if is_dark else CHEVRON_DOWN_LIGHT_PATH
    tool_hover_bg = "rgba(37, 99, 255, 0.22)" if is_dark else "rgba(37, 99, 255, 0.10)"
    tool_checked_bg = "rgba(37, 99, 255, 0.30)" if is_dark else "rgba(37, 99, 255, 0.16)"
    tool_checked_text = "#EEF2FF" if is_dark else "#1D4ED8"
    btn_hover_bg = "rgba(37, 99, 255, 0.20)" if is_dark else "rgba(37, 99, 255, 0.10)"

    return f"""
    /* ── Base ─────────────────────────────────────────── */
    QMainWindow {{
        background-color: {t['background']};
    }}

    QWidget {{
        color: {t['text-primary']};
        font-family: {FONTS['functional']};
        font-size: 13px;
        selection-background-color: {t['electric-blue']};
        selection-color: #FFFFFF;
    }}

    /* ── Splitter ─────────────────────────────────────── */
    QSplitter::handle {{
        background-color: {t['border-subtle']};
        width: 2px;
    }}

    QSplitter::handle:hover {{
        background-color: {t['electric-blue']};
    }}

    /* ── Panels ───────────────────────────────────────── */
    QFrame#editorContainer,
    QFrame#previewContainer {{
        background-color: {t['surface']};
        border: 1.5px solid {t['border-subtle']};
        border-radius: 14px;
    }}

    /* ── Text Editor ──────────────────────────────────── */
    QPlainTextEdit {{
        background-color: {t['surface']};
        color: {t['text-primary']};
        border: none;
        font-family: {FONTS['monospace']};
        font-size: 14px;
        padding: 12px;
        line-height: 1.5;
    }}

    QPlainTextEdit:focus {{
        outline: none;
    }}

    QPlainTextEdit::placeholder {{
        color: {t['text-muted']};
    }}

    /* ── Buttons ──────────────────────────────────────── */
    QPushButton {{
        background-color: {t['surface']};
        color: {t['text-primary']};
        border: 1.5px solid {t['border-subtle']};
        border-radius: 10px;
        padding: 6px 12px;
        font-weight: 600;
        font-family: {FONTS['functional']};
        font-size: 12px;
        min-height: 18px;
    }}

    QPushButton:hover {{
        background-color: {btn_hover_bg};
        color: {t['text-primary']};
        border-color: {t['electric-blue']};
    }}

    QPushButton:pressed {{
        background-color: {t['electric-blue']};
        color: #FFFFFF;
        border-color: {t['electric-blue']};
    }}

    QPushButton:focus {{
        border: 2px solid {t['electric-blue']};
    }}

    QPushButton:disabled {{
        opacity: 0.38;
        color: {t['text-muted']};
    }}

    QPushButton#zoomPctBtn {{
        background-color: {t['surface-alt']};
        color: {t['text-primary']};
        border: 1.5px solid {t['border-subtle']};
        border-radius: 10px;
        padding: 6px 8px;
        font-weight: 700;
    }}

    QPushButton#zoomPctBtn:hover {{
        background-color: {btn_hover_bg};
        border-color: {t['electric-blue']};
    }}

    /* ── Tool Buttons (NUMA tonal selection, no OS neon accent) ── */
    QToolButton {{
        background-color: transparent;
        color: {t['text-primary']};
        border: 1.5px solid transparent;
        border-radius: 10px;
        padding: 5px 10px;
        font-family: {FONTS['functional']};
        font-size: 12px;
        font-weight: 600;
    }}

    QToolButton:hover {{
        background-color: {tool_hover_bg};
        border-color: rgba(37, 99, 255, 0.35);
    }}

    QToolButton:pressed {{
        background-color: {tool_checked_bg};
        border-color: {t['electric-blue']};
    }}

    QToolButton:checked {{
        background-color: {tool_checked_bg};
        color: {tool_checked_text};
        border: 1.5px solid {t['electric-blue']};
        font-weight: 700;
    }}

    QToolButton:checked:hover {{
        background-color: rgba(37, 99, 255, 0.36);
        color: {tool_checked_text};
        border-color: {t['deep-blue']};
    }}

    QToolButton::menu-indicator {{
        subcontrol-position: right center;
        subcontrol-origin: padding;
        left: -2px;
    }}

    QLabel#shortcutFeedback {{
        color: #15803D;
        background-color: #ECFDF5;
        border: 1px solid #86EFAC;
        border-radius: 6px;
        padding: 4px 8px;
        font-weight: 700;
    }}

    /* Direct file actions beside the Archivo menu (secondary hierarchy). */
    QToolButton#quickOpenBtn {{
        background-color: {t['surface']};
        color: {t['text-primary']};
        border: 1.5px solid {t['border-subtle']};
        border-radius: 10px;
        padding: 6px 12px;
        font-weight: 600;
    }}

    QToolButton#quickOpenBtn:hover {{
        background-color: {btn_hover_bg};
        border-color: {t['electric-blue']};
    }}

    QToolButton#quickSaveBtn {{
        background-color: {t['surface']};
        color: {t['text-primary']};
        border: 1.5px solid {t['border-subtle']};
        border-radius: 10px;
        padding: 6px 12px;
        font-weight: 600;
    }}

    QToolButton#quickSaveBtn:hover {{
        background-color: {btn_hover_bg};
        border-color: {t['electric-blue']};
    }}

    QToolButton#quickSaveBtn[dirty="true"] {{
        background-color: rgba(255, 179, 71, 0.24);
        color: {t['text-primary']};
        border: 1.5px solid {t['mango-strong']};
        font-weight: 700;
    }}

    QToolButton#quickSaveBtn[dirty="true"]:hover {{
        background-color: rgba(255, 179, 71, 0.38);
        border-color: {t['mango-strong']};
    }}

    /* Accent (Mango) */
    QPushButton#accentBtn {{
        background-color: {t['mango']};
        color: #111827;
        border: 2px solid {t['mango-strong']};
        border-radius: 10px;
        font-weight: 700;
        padding: 7px 16px;
    }}

    QPushButton#accentBtn:hover {{
        background-color: {t['mango-strong']};
        color: #111827;
    }}

    /* Primary (Electric Blue — dominant screen CTA) */
    QPushButton#primaryBtn {{
        background-color: {t['electric-blue']};
        color: #EEF2FF;
        border: 2px solid {t['deep-blue']};
        border-radius: 10px;
        font-weight: 700;
        padding: 7px 16px;
    }}

    QPushButton#primaryBtn:hover {{
        background-color: {t['deep-blue']};
        color: #FFFFFF;
        border-color: {t['electric-blue']};
    }}

    QPushButton#primaryBtn:pressed {{
        background-color: #1D4ED8;
        color: #FFFFFF;
    }}

    /* Soft accents preserve hierarchy without competing with Presentar. */
    QPushButton#softBlueBtn {{
        background-color: rgba(37, 99, 255, 0.12);
        color: {t['text-primary']};
        border: 1.5px solid rgba(37, 99, 255, 0.45);
    }}

    QPushButton#softBlueBtn:hover {{
        background-color: rgba(37, 99, 255, 0.22);
        border-color: {t['electric-blue']};
    }}

    QPushButton#softMintBtn {{
        background-color: rgba(46, 230, 197, 0.14);
        color: {t['text-primary']};
        border: 1.5px solid rgba(46, 230, 197, 0.55);
    }}

    QPushButton#softMintBtn:hover {{
        background-color: rgba(46, 230, 197, 0.26);
        border-color: {t['mint']};
    }}

    QPushButton#softMangoBtn {{
        background-color: rgba(255, 179, 71, 0.20);
        color: {t['text-primary']};
        border: 1.5px solid rgba(255, 138, 0, 0.55);
    }}

    QPushButton#softMangoBtn:hover {{
        background-color: rgba(255, 179, 71, 0.34);
        border-color: {t['mango-strong']};
    }}

    QPushButton#hiddenPreviewBtn {{
        background-color: {t['mango']};
        color: #111827;
        border: 2px solid {t['mango-strong']};
    }}

    QPushButton#hiddenPreviewBtn:hover {{
        background-color: {t['mango-strong']};
        color: #111827;
    }}

    /* ── Toolbar ──────────────────────────────────────── */
    QToolBar {{
        background-color: {t['surface']};
        border-bottom: 1.5px solid {t['border-subtle']};
        spacing: 6px;
        padding: 5px 10px;
    }}

    QToolBar::separator {{
        background-color: {t['border-subtle']};
        width: 1px;
        margin: 5px 4px;
    }}

    QWidget#timeToolbarContainer {{
        background-color: {t['surface-alt']};
        border-bottom: 1px solid {t['border-subtle']};
    }}

    QWidget#previewControls {{
        background-color: {t['surface']};
        border-top: 1px solid {t['border-subtle']};
        border-bottom: 1px solid {t['border-subtle']};
    }}

    QFrame#presentationActionsBlock {{
        background-color: {t['surface']};
        border: 1px solid {t['border-subtle']};
        border-radius: 10px;
    }}

    QLabel#timeToolbarLabel {{
        color: {t['text-secondary']};
        font-weight: 700;
        padding: 4px 2px 4px 4px;
    }}

    /* ── Combo Boxes ───────────────────────────────────── */
    QComboBox {{
        background-color: {t['surface']};
        color: {t['text-primary']};
        border: 1.5px solid {t['border-subtle']};
        border-radius: 10px;
        padding: 5px 28px 5px 10px;
        font-family: {FONTS['functional']};
        font-size: 12px;
        font-weight: 600;
        min-height: 22px;
        selection-background-color: {t['electric-blue']};
        selection-color: #FFFFFF;
    }}

    QComboBox:hover,
    QComboBox:focus {{
        border-color: {t['electric-blue']};
    }}

    QComboBox:disabled {{
        color: {t['text-muted']};
        background-color: {t['surface-alt']};
        border-color: {t['border-subtle']};
    }}

    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 24px;
        border-left: 1px solid {t['border-subtle']};
        background: transparent;
    }}

    QComboBox::down-arrow {{
        image: url("{chevron_path}");
        width: 12px;
        height: 12px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {t['surface']};
        color: {t['text-primary']};
        border: 1.5px solid {t['border-subtle']};
        border-radius: 10px;
        selection-background-color: {t['electric-blue']};
        selection-color: #FFFFFF;
        outline: none;
        padding: 4px;
    }}

    QComboBox QAbstractItemView::item {{
        min-height: 24px;
        padding: 6px 10px;
        color: {t['text-primary']};
        background-color: {t['surface']};
    }}

    QComboBox QAbstractItemView::item:hover,
    QComboBox QAbstractItemView::item:selected {{
        color: #FFFFFF;
        background-color: {t['electric-blue']};
    }}

    QComboBox QAbstractItemView::item:disabled {{
        color: {t['text-muted']};
        background-color: {t['surface']};
    }}

    /* ── Context menus ─────────────────────────────────── */
    QMenu {{
        background-color: {t['surface']};
        color: {t['text-primary']};
        border: 1px solid {t['border-subtle']};
        border-radius: 6px;
        padding: 4px;
    }}

    QMenu::item {{
        background-color: transparent;
        color: {t['text-primary']};
        padding: 7px 28px 7px 10px;
        min-height: 22px;
    }}

    QMenu::item:selected {{
        background-color: {t['electric-blue']};
        color: #FFFFFF;
    }}

    QMenu::item:disabled {{
        color: {t['text-muted']};
        background-color: transparent;
    }}

    QMenu::separator {{
        height: 1px;
        background-color: {t['border-subtle']};
        margin: 4px 7px;
    }}

    /* ── Status Bar ───────────────────────────────────── */
    QStatusBar {{
        background-color: {t['surface']};
        border-top: 1px solid {t['border-subtle']};
        color: {t['text-secondary']};
        font-size: 11px;
        padding: 2px 8px;
    }}

    QStatusBar::item {{
        border: none;
    }}

    /* ── Labels ───────────────────────────────────────── */
    QLabel {{
        background: transparent;
    }}

    QLabel#mobileLinkAddress {{
        color: {t['text-primary']};
        font-weight: 600;
        padding: 0 8px;
    }}

    QLabel#previewSlideCounter {{
        color: {t['text-secondary']};
        font-weight: 700;
        font-size: 12px;
        padding: 0 8px;
    }}

    QToolButton#mobileControlBtn {{
        background-color: {t['surface-alt']};
        color: {t['text-primary']};
        border: 1px solid {t['border-subtle']};
        border-radius: 999px;
        padding: 3px 12px;
        font-size: 11px;
        font-weight: 600;
    }}

    QToolButton#mobileControlBtn:hover {{
        border-color: {t['electric-blue']};
        background-color: {tool_hover_bg};
    }}

    /* ── Dialogs ──────────────────────────────────────── */
    QDialog {{
        background-color: {t['background']};
        border: 2px solid {t['border']};
    }}

    /* ── Scrollbars ───────────────────────────────────── */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}

    QScrollBar::handle:vertical {{
        background-color: {t['border-subtle']};
        border-radius: 5px;
        min-height: 30px;
    }}

    QScrollBar::handle:vertical:hover {{
        background-color: {t['text-muted']};
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 0;
    }}

    QScrollBar::handle:horizontal {{
        background-color: {t['border-subtle']};
        border-radius: 5px;
        min-width: 30px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background-color: {t['text-muted']};
    }}

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
    """


# ─────────────────────────────────────────────────────────────
# HTML Template (Presentation Render)
# ─────────────────────────────────────────────────────────────

def get_html_template(
    content_html,
    style_mode="slide",
    font_size=24,
    is_dark=False,
    borderless=False,
    clock_visible=False,
    clock_mode="clock",
    clock_show_seconds=False,
    clock_size=22,
    clock_position="top-right",
    timer_duration_seconds=300,
    timer_elapsed_seconds=0,
    timer_running=False,
    student_sync_label_visible=False,
    student_sync_label_map=None,
    preview_canvas=False,
    output_aspect_ratio="16 / 9",
    output_width=1920,
    output_height=1080,
    preview_zoom=1.0,
    pdf_export=False,
    pdf_document=False,
    paper_size="letter",
    paper_orientation="portrait",
    paper_title="",
    paper_subtitle="",
    paper_header_mode="auto_title",
    paper_footer_mode="page_of_total",
    paper_custom_header="",
    paper_header_right_mode="none",
    paper_header_right_text="",
    paper_footer_left_mode="none",
    paper_footer_left_text="",
    paper_font_scale=1.0,
):
    t = DARK_THEME if is_dark else LIGHT_THEME

    bg = t["background"]
    surf = t["surface"]
    txt = t["text-primary"]
    txt_sec = t["text-secondary"]
    border_color = t["border"]
    blue = t["electric-blue"]
    mango = t["mango"]
    mint = t["mint"]
    shadow = t["shadow"]

    try:
        paper_font_scale = max(0.5, min(float(paper_font_scale), 2.0))
    except (TypeError, ValueError):
        paper_font_scale = 1.0
    is_slide_mode = style_mode == "slide"
    is_paper_mode = style_mode == "paper"
    paper_sizes = {
        "letter": ("8.5in", "11in"),
        "legal": ("8.5in", "14in"),
        "a4": ("210mm", "297mm"),
        "a3": ("297mm", "420mm"),
    }
    paper_width, paper_height = paper_sizes.get(paper_size, paper_sizes["letter"])
    if paper_orientation == "landscape":
        paper_width, paper_height = paper_height, paper_width
    clock_display = "block" if clock_visible else "none"
    sync_label_display = "block" if student_sync_label_visible else "none"
    sync_label_map_json = json.dumps(student_sync_label_map or {})
    try:
        output_width = max(1, int(output_width))
        output_height = max(1, int(output_height))
    except (TypeError, ValueError):
        output_width, output_height = 1920, 1080
    try:
        preview_zoom = max(0.01, float(preview_zoom))
    except (TypeError, ValueError):
        preview_zoom = 1.0
    slide_max_height = f"{int(output_height * 0.88)}px" if preview_canvas and is_slide_mode else ("none" if pdf_export and is_slide_mode else "88vh")
    image_max_height = f"{int(output_height * 0.42)}px" if preview_canvas and is_slide_mode else ("42%" if pdf_export and is_slide_mode else "42vh")

    # Slide mode: full viewport, absolute positioning
    # Scroll mode: full width container with vertical flow
    if is_slide_mode:
        if pdf_export:
            container_css = f"""
@page {{
    size: 16in 9in;
    margin: 0;
}}

#presentation-stage {{
    width: 16in;
    min-height: 9in;
    background: var(--bg);
    overflow: visible;
    position: static;
    transform: none;
}}

#presentation-container {{
    width: 16in;
    overflow: visible;
    position: static;
}}
"""
            body_extra = "overflow: visible; display: block; background: var(--bg);"
        elif preview_canvas:
            container_css = f"""
#presentation-stage {{
    width: {output_width}px;
    height: {output_height}px;
    aspect-ratio: {output_aspect_ratio};
    background: var(--bg);
    overflow: visible;
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(calc(-50% + var(--numa-pan-x, 0px)), calc(-50% + var(--numa-pan-y, 0px))) scale(var(--preview-scale, 1));
    transform-origin: center center;
}}

#presentation-container {{
    width: 100%;
    height: 100%;
    overflow: visible;
    position: relative;
    transform: scale(var(--numa-user-zoom, 1));
    transform-origin: center center;
}}
"""
            body_extra = "overflow: auto;"
        else:
            container_css = """
#presentation-stage {
    width: 100%;
    height: 100%;
    overflow: visible;
    position: relative;
    transform: translate(var(--numa-pan-x, 0px), var(--numa-pan-y, 0px));
}

#presentation-container {
    width: 100%;
    height: 100%;
    overflow: visible;
    position: relative;
    transform: scale(var(--numa-user-zoom, 1));
    transform-origin: center center;
}
"""
            body_extra = "overflow: auto;"
    else:
        if pdf_document:
            container_css = """
@page {
    size: Letter portrait;
    margin: 0;
}

#presentation-stage {
    width: 100%;
    transform: none;
}

#presentation-container {
    width: 100%;
    padding: 0;
}
"""
            body_extra = "overflow: visible; display: block; background: #FFFFFF;"
        else:
            container_css = """
#presentation-stage {
    width: 100%;
    transform: translate(var(--numa-pan-x, 0px), var(--numa-pan-y, 0px));
}

#presentation-container {
    width: 100%;
    padding: 32px 16px;
}
"""
            body_extra = "overflow-y: auto;"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NUMA Deck</title>
<link rel="stylesheet" href="{KATEX_CSS_URL}">
<script src="{KATEX_JS_URL}"></script>
<script src="{KATEX_AUTORENDER_JS_URL}"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Cabinet+Grotesk:wght@700;800&display=swap');

:root {{
    --bg: {bg};
    --surface: {surf};
    --text: {txt};
    --text-sec: {txt_sec};
    --border: {border_color};
    --primary: {blue};
    --accent: {mango};
    --mint: {mint};
    --shadow: {shadow};
    --font-size: {font_size}px;
    --numa-user-zoom: {preview_zoom};
    --numa-pan-x: 0px;
    --numa-pan-y: 0px;
    --radius: 14px;
    --radius-lg: 18px;
}}

*, *::before, *::after {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}}

html {{
    scroll-behavior: smooth;
    height: 100%;
    margin: 0;
    padding: 0;
}}

body {{
    background-color: var(--bg);
    color: var(--text);
    font-family: 'Inter', 'Segoe UI', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Apple Color Emoji', 'Noto Color Emoji', sans-serif;
    font-size: var(--font-size);
    line-height: 1.65;
    margin: 0;
    padding: 0;
    height: 100%;
    width: 100%;
    display: flex;
    justify-content: center;
    align-items: stretch;
    flex-wrap: nowrap;
    transform-origin: center center;
    {body_extra}
}}

body.dragging-presentation {{
    cursor: grabbing !important;
    user-select: none;
}}

#presentation-stage {{
    cursor: grab;
}}

{container_css}

{"""
/* PDF pages: one rendered slide per page, matching presentation aspect ratio */
.slide {
    position: relative !important;
    display: flex !important;
    width: 16in !important;
    height: 9in !important;
    opacity: 1 !important;
    visibility: visible !important;
    transform: none !important;
    page-break-after: always;
    break-after: page;
    padding: 0.45in 0.55in !important;
}

.slide:last-child {
    page-break-after: auto;
    break-after: auto;
}

.slide-content {
    width: 100% !important;
    max-height: none !important;
    height: auto !important;
    overflow: visible !important;
}

.slide-footer {
    position: absolute !important;
    right: 0.45in !important;
    bottom: 0.25in !important;
}
""" if pdf_export and is_slide_mode else ""}

{"""
/* Letter-size document export: natural flow across pages. */
.continuous-document {
    width: 100% !important;
    max-width: none !important;
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    background: #FFFFFF !important;
    color: #111827 !important;
    overflow: visible !important;
    font-size: 11pt !important;
    line-height: 1.55 !important;
}

.slide-divider {
    display: none !important;
}

img {
    max-width: 100% !important;
    max-height: 8in !important;
    width: auto !important;
    height: auto !important;
    margin: 0.22in auto !important;
    border: 1px solid #9CA3AF !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    break-inside: avoid;
    page-break-inside: avoid;
}

table, pre, blockquote {
    break-inside: avoid;
    page-break-inside: avoid;
}

h1, h2, h3, h4, h5, h6 {
    break-after: avoid;
    page-break-after: avoid;
    color: #30343B !important;
    font-family: 'Inter', 'Segoe UI', sans-serif !important;
}

h1 {
    font-size: 22pt !important;
    border-bottom: 1px solid #D1D5DB !important;
    padding-bottom: 0.12in !important;
    margin-bottom: 0.22in !important;
}

h2 {
    font-size: 16pt !important;
    margin-top: 0.22in !important;
    margin-bottom: 0.12in !important;
}

h3 {
    font-size: 13pt !important;
}

table {
    width: 100% !important;
    border-collapse: collapse !important;
    font-size: 10.5pt !important;
    margin: 0.18in 0 !important;
}

th, td {
    border: 1px solid #D1D5DB !important;
    padding: 6px 10px !important;
    color: #30343B !important;
}

th {
    background: #F3F4F6 !important;
    color: #30343B !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
}

blockquote {
    border-left: 4px solid #E5E7EB !important;
    background: transparent !important;
    color: #6B7280 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}
""" if pdf_document else ""}

{"""
/* Paper preview: each Markdown section is a physical page. */
#presentation-stage {
    width: 100%;
    min-height: 100%;
    padding: 28px;
    background: #D9DEE8;
    transform: translate(var(--numa-pan-x, 0px), var(--numa-pan-y, 0px));
}

#presentation-container {
    width: 100%;
    padding: 0;
}

.print-document {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 28px;
    width: 100%;
}

.print-page {
    width: """ + paper_width + ";\n    height: " + paper_height + ";\n    position: relative;\n    background: #FFFFFF;\n    color: #111827;\n    padding: 0.55in 0.6in 0.65in;\n    box-shadow: 0 2px 12px rgba(15, 23, 42, 0.24);\n    overflow: hidden;\n}\n\n.print-page-content {\n    height: calc(100% - 0.5in);\n    overflow: hidden;\n    font-size: calc(var(--font-size) * 0.72);\n    line-height: 1.55;\n}\n\n.print-page-header {\n    height: 0.24in;\n    margin-bottom: 0.14in;\n    padding-bottom: 0.04in;\n    border-bottom: 1px solid #9CA3AF;\n    font-family: 'Inter', sans-serif;\n    font-size: 9pt;\n    font-weight: 700;\n    color: #374151;\n    white-space: nowrap;\n    overflow: hidden;\n    text-overflow: ellipsis;\n}\n\n.print-page-number {\n    position: absolute;\n    right: 0.35in;\n    bottom: 0.22in;\n    font-family: 'Inter', sans-serif;\n    font-size: 9pt;\n    color: #4B5563;\n}\n\n.print-page h1, .print-page h2, .print-page h3, .print-page h4, .print-page h5, .print-page h6 {\n    color: #111827;\n}\n\n.print-page img {\n    max-width: 100%;\n    height: auto;\n    display: block;\n    margin: 0.2in auto;\n}\n\n.print-page table {\n    width: 100%;\n    border-collapse: collapse;\n    font-size: 0.9em;\n}\n\n.print-page th, .print-page td {\n    border: 1px solid #9CA3AF;\n    padding: 6px 8px;\n}\n""" if is_paper_mode else ""}

{"""
/* Printed paper export: one configured sheet per PDF page. */
@page {
    size: """ + paper_width + " " + paper_height + ";\n    margin: 0;\n}\n\nbody {\n    display: block;\n    background: #FFFFFF;\n}\n\n#presentation-stage {\n    min-height: 0;\n    padding: 0;\n    background: #FFFFFF;\n    transform: none;\n}\n\n.print-document {\n    display: block;\n    margin: 0;\n    padding: 0;\n}\n\n.print-page {\n    margin: 0;\n    box-shadow: none;\n    break-after: page;\n    page-break-after: always;\n}\n\n.print-page:last-child {\n    break-after: auto;\n    page-break-after: auto;\n}\n""" if pdf_export and is_paper_mode else ""}

/* ── Slide Container ────────────────────────────── */
.slide {{
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    padding: 24px 32px;
    position: absolute;
    top: 0; left: 0;
    opacity: 0;
    visibility: hidden;
    transform: translateY(16px);
    transition: opacity 0.3s cubic-bezier(0.25, 1, 0.5, 1),
                transform 0.3s cubic-bezier(0.25, 1, 0.5, 1);
}}

.slide.active {{
    opacity: 1;
    visibility: visible;
    transform: translateY(0);
}}

.pdf-anchor {{
    display: block;
    height: 0;
    overflow: hidden;
    position: relative;
    top: 0;
}}

.slide-content {{
    background-color: var(--surface);
    {"border: none; border-radius: 0; box-shadow: none;" if borderless else "border: 3px solid var(--border); border-radius: var(--radius-lg); box-shadow: 0 8px 0 var(--shadow);"}
    padding: 40px 48px;
    width: 100%;
    max-height: {slide_max_height};
    overflow-y: auto;
    position: relative;
}}

/* ── Continuous Document ────────────────────────── */
.continuous-document {{
    background-color: var(--surface);
    {"border: none; border-radius: 0; box-shadow: none;" if borderless else "border: 3px solid var(--border); border-radius: var(--radius-lg); box-shadow: 0 8px 0 var(--shadow);"}
    padding: 40px 48px;
    width: 100%;
    margin-bottom: 32px;
}}

/* ── Typography ─────────────────────────────────── */
h1, h2, h3, h4, h5, h6 {{
    font-family: 'Cabinet Grotesk', 'Arial Black', Impact, 'Segoe UI Emoji', 'Segoe UI Symbol', sans-serif;
    color: var(--text);
    line-height: 1.2;
    margin-top: 0;
}}

h1 {{
    font-size: calc(var(--font-size) * 1.65);
    font-weight: 800;
    border-bottom: 3px solid var(--border);
    padding-bottom: 14px;
    margin-bottom: 28px;
}}

h2 {{
    font-size: calc(var(--font-size) * 1.3);
    font-weight: 700;
    margin-bottom: 20px;
}}

h3 {{
    font-size: calc(var(--font-size) * 1.1);
    font-weight: 700;
    margin-bottom: 16px;
}}

p {{
    margin-bottom: 1em;
}}

ul, ol {{
    margin-bottom: 1em;
    padding-left: 1.8em;
}}

li {{
    margin-bottom: 0.4em;
}}

strong {{
    font-weight: 700;
}}

em {{
    font-style: italic;
}}

a {{
    color: var(--primary);
    text-decoration: underline;
    text-decoration-style: dotted;
    text-underline-offset: 3px;
}}

a:hover {{
    text-decoration-style: solid;
}}

/* ── Code ───────────────────────────────────────── */
code {{
    background-color: rgba(37, 99, 255, 0.08);
    color: var(--primary);
    padding: 2px 7px;
    border-radius: 6px;
    font-family: 'Consolas', 'Cascadia Code', monospace;
    font-size: 0.88em;
    border: 1px solid rgba(37, 99, 255, 0.15);
}}

pre {{
    background-color: rgba(0, 0, 0, 0.04);
    border: 2px solid var(--border);
    border-radius: var(--radius);
    padding: 20px 24px;
    overflow-x: auto;
    margin: 20px 0;
}}

pre code {{
    background: transparent;
    color: var(--text);
    padding: 0;
    border: none;
    font-size: 0.92em;
    line-height: 1.5;
}}

/* Tree / connector diagrams (box-drawing characters) */
pre.numa-tree {{
    white-space: pre;
    overflow-x: auto;
    font-variant-ligatures: none;
}}

pre.numa-tree code {{
    display: inline-block;
    white-space: pre;
    line-height: normal;
    letter-spacing: 0;
    font-family: 'Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', 'Courier New', monospace;
    font-variant-ligatures: none;
    tab-size: 4;
}}

/* Physical sheets stay light regardless of the application theme. */
.print-page pre {{
    background: #F3F4F6;
    color: #111827;
    border-color: #CBD5E1;
    box-sizing: border-box;
    max-width: 100%;
    padding: 12px 14px;
}}

.print-page code {{
    color: #1D4ED8;
}}

.print-page pre code {{
    color: #111827;
}}

/* ── Mathematics (KaTeX) ─────────────────────────── */
.katex-display {{
    margin: 0.85em 0;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0.1em 0;
}}

.katex-error {{
    color: #B42318;
    font-family: 'Consolas', 'Cascadia Code', monospace;
    font-size: 0.88em;
    white-space: pre-wrap;
}}

/* ── Blockquote ─────────────────────────────────── */
blockquote {{
    border-left: 6px solid var(--primary);
    background-color: rgba(37, 99, 255, 0.06);
    padding: 16px 24px;
    margin: 20px 0;
    border-radius: 0 var(--radius) var(--radius) 0;
    font-style: italic;
    color: var(--text-sec);
}}

blockquote p:last-child {{
    margin-bottom: 0;
}}

/* ── Images ─────────────────────────────────────── */
img {{
    max-width: 100%;
    max-height: {image_max_height};
    display: block;
    margin: 24px auto;
    border: 2px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 4px 0 var(--shadow);
    object-fit: contain;
    cursor: zoom-in;
}}

.image-zoom-overlay {{
    position: fixed;
    inset: 0;
    z-index: 9999;
    display: none;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.78);
    cursor: zoom-out;
}}

.image-zoom-overlay.active {{
    display: flex;
}}

.image-zoom-stage {{
    width: 100vw;
    height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    cursor: grab;
}}

.image-zoom-stage.dragging {{
    cursor: grabbing;
}}

.image-zoom-overlay img {{
    width: 100%;
    height: 100%;
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    margin: 0;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    transform-origin: center center;
    cursor: grab;
    user-select: none;
    -webkit-user-drag: none;
}}

.image-zoom-help {{
    position: fixed;
    left: 24px;
    bottom: 22px;
    color: #FFFFFF;
    background: rgba(0, 0, 0, 0.46);
    border: 1px solid rgba(255, 255, 255, 0.35);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 700;
    font-family: 'Inter', sans-serif;
    pointer-events: auto;
    cursor: pointer;
}}

/* ── Tables ─────────────────────────────────────── */
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 24px 0;
    font-size: calc(var(--font-size) * 0.88);
}}

th, td {{
    border: 2px solid var(--border);
    padding: 12px 14px;
    text-align: left;
}}

th {{
    background-color: var(--primary);
    color: #FFFFFF;
    font-weight: 700;
    font-size: calc(var(--font-size) * 0.85);
    text-transform: uppercase;
    letter-spacing: 0.03em;
}}

tr:nth-child(even) {{
    background-color: rgba(0, 0, 0, 0.02);
}}

.print-page table {{
    table-layout: fixed;
    max-width: 100%;
    box-sizing: border-box;
}}

.print-page th, .print-page td {{
    min-width: 0;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: normal;
    vertical-align: top;
}}

.print-page th {{
    font-size: inherit;
    letter-spacing: 0;
}}

/* ── Markdown text alignment ────────────────────── */
.numa-document-align-left {{ text-align: left; }}
.numa-document-align-center {{ text-align: center; }}
.numa-document-align-right {{ text-align: right; }}
.numa-document-align-justify {{ text-align: justify; }}
.numa-align-left {{ text-align: left; }}
.numa-align-center {{ text-align: center; }}
.numa-align-right {{ text-align: right; }}
.numa-align-justify {{ text-align: justify; }}

/* ── Per-image display options ───────────────────── */
figure.numa-image {{
    width: var(--numa-image-width, auto);
    max-width: 100%;
    box-sizing: border-box;
    padding: 0;
    overflow: visible;
    break-inside: avoid;
    page-break-inside: avoid;
}}

figure.numa-image img {{
    display: block;
    width: 100% !important;
    max-width: 100% !important;
    max-height: none !important;
    height: auto !important;
    margin: 0 !important;
    box-sizing: border-box;
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    object-fit: contain;
}}

figure.numa-image-width-auto {{
    width: fit-content;
}}

figure.numa-image-width-auto img {{
    width: auto !important;
    max-width: 100% !important;
}}

/* Percentage-sized SVGs have no intrinsic width for a fit-content parent. */
figure.numa-image-width-auto:has(> img:is([src$=".svg" i], [src*=".svg?" i], [src*=".svg#" i], [src^="data:image/svg+xml" i])) {{
    width: 100%;
}}

figure.numa-image-width-auto > img:is([src$=".svg" i], [src*=".svg?" i], [src*=".svg#" i], [src^="data:image/svg+xml" i]) {{
    width: 100% !important;
}}

figure.numa-image-align-left {{ margin-left: 0; margin-right: auto; }}
figure.numa-image-align-center {{ margin-left: auto; margin-right: auto; }}
figure.numa-image-align-right {{ margin-left: auto; margin-right: 0; }}
figure.numa-image-spacing-compact {{ margin-top: 0.35em; margin-bottom: 0.35em; }}
figure.numa-image-spacing-normal {{ margin-top: 1em; margin-bottom: 1em; }}
figure.numa-image-spacing-wide {{ margin-top: 1.8em; margin-bottom: 1.8em; }}
figure.numa-image-color-grayscale img {{ filter: grayscale(1); }}
figure.numa-image-color-color img {{ filter: none; }}
figure.numa-image-frame-none {{ border: none; box-shadow: none; }}
figure.numa-image-frame-plain {{ border: 1px solid #1F2937; box-shadow: none; }}
figure.numa-image-frame-shadow {{
    border: 1px solid #1F2937;
    box-shadow: 0 3px 8px rgba(15, 23, 42, 0.28);
}}
figure.numa-image-frame-none img {{
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}}
figure.numa-image-frame-plain img {{
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}}
figure.numa-image-frame-shadow img {{
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}}
figure.numa-image-orientation-90 img {{ transform: rotate(90deg); }}
figure.numa-image-orientation-180 img {{ transform: rotate(180deg); }}
figure.numa-image-orientation-270 img {{ transform: rotate(270deg); }}

/* Reserve the running header before paper blocks are distributed. */
.print-page.has-print-header .print-page-content {{
    height: calc(100% - 0.92in);
}}

/* ── Horizontal Rule / Slide Divider ────────────── */
hr, .slide-divider {{
    border: none;
    border-top: 3px solid var(--border);
    margin: 40px 0;
}}

/* ── Slide Footer (page indicator) ──────────────── */
.slide-footer {{
    position: absolute;
    bottom: 22px;
    right: 44px;
    font-size: 13px;
    font-weight: 700;
    font-family: 'Inter', sans-serif;
    color: #000000;
    background-color: var(--accent);
    border: 2px solid var(--border);
    padding: 4px 12px;
    border-radius: 10px;
    box-shadow: 0 2px 0 var(--shadow);
    letter-spacing: 0.02em;
}}

/* ── Presentation Clock ─────────────────────────── */
.presentation-clock {{
    position: fixed;
    z-index: 9000;
    display: {clock_display};
    padding: 8px 14px;
    font-family: 'Inter', 'Segoe UI', 'Segoe UI Emoji', sans-serif;
    font-size: {clock_size}px;
    font-weight: 800;
    line-height: 1;
    color: var(--text);
    background: var(--surface);
    border: 2px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 4px 0 var(--shadow);
    pointer-events: none;
}}

.presentation-clock.top-left {{
    top: 22px;
    left: 24px;
}}

.presentation-clock.top-right {{
    top: 22px;
    right: 24px;
}}

.presentation-clock.bottom-left {{
    bottom: 22px;
    left: 24px;
}}

.presentation-clock.bottom-right {{
    bottom: 22px;
    right: 24px;
}}

/* ── Student/teacher synchronization indicator ───────── */
.student-sync-label {{
    position: fixed;
    z-index: 8990;
    display: {sync_label_display};
    left: 24px;
    bottom: 22px;
    padding: 7px 11px;
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
    font-weight: 800;
    color: #FFFFFF;
    background: var(--primary);
    border: 2px solid var(--border);
    border-radius: 6px;
    box-shadow: 3px 3px 0 var(--shadow);
    pointer-events: auto;
    cursor: pointer;
}}

.student-sync-label a {{
    display: block;
    color: inherit;
    text-decoration: none;
    cursor: pointer;
}}

/* ── Mobile-Link pointer ─────────────────────────────── */
#numaMobilePointer {{
    position: fixed;
    z-index: 10001;
    display: none;
    width: 24px;
    height: 24px;
    margin: -12px 0 0 -12px;
    border: 3px solid var(--electric-blue);
    border-radius: 50%;
    background: var(--electric-blue);
    box-shadow: 0 0 0 2px var(--border), 0 3px 8px rgba(0, 0, 0, 0.45);
    pointer-events: none;
    will-change: transform;
    transform: translate3d(0, 0, 0);
}}

#numaMobileTrail {{
    position: fixed;
    inset: 0;
    z-index: 10000;
    pointer-events: none;
}}

#numaMobileTrailCanvas {{
    position: fixed;
    inset: 0;
    z-index: 10000;
    width: 100vw;
    height: 100vh;
    pointer-events: none;
}}

.numa-mobile-trail-dot {{
    position: fixed;
    border-radius: 50%;
    pointer-events: none;
    opacity: 0.7;
    transform: translate(-50%, -50%);
    animation: numaMobileTrailFade 700ms ease-out forwards;
}}

@keyframes numaMobileTrailFade {{
    from {{ opacity: 0.72; }}
    to {{ opacity: 0; }}
}}

#numaMobilePointer.active {{
    display: block;
}}

/* ── Scrollbar (inside webview) ─────────────────── */
::-webkit-scrollbar {{
    width: 8px;
}}

::-webkit-scrollbar-track {{
    background: transparent;
}}

::-webkit-scrollbar-thumb {{
    background: var(--border);
    border-radius: 4px;
}}

::-webkit-scrollbar-thumb:hover {{
    background: var(--text-sec);
}}
</style>
</head>
<body>
<div id="presentation-stage">
    <div id="presentation-container">
    {content_html}
    </div>
</div>
<div id="presentationClock" class="presentation-clock {clock_position}"></div>
<div id="studentSyncLabel" class="student-sync-label"></div>
<div id="numaMobilePointer" aria-hidden="true"></div>
<div id="numaMobileTrail" aria-hidden="true"></div>
<canvas id="numaMobileTrailCanvas" aria-hidden="true"></canvas>
<div class="image-zoom-overlay" id="imageZoomOverlay" aria-hidden="true">
    <div class="image-zoom-stage" id="imageZoomStage">
        <img id="imageZoomTarget" alt="">
    </div>
    <div class="image-zoom-help">Rueda: zoom | Arrastra: mover | L/R: rotar 90° | Esc: cerrar</div>
</div>

<script>
(function() {{
    function renderNumaMath() {{
        if (!window.renderMathInElement) return;
        window.renderMathInElement(document.getElementById('presentation-container'), {{
            delimiters: [
                {{left: '$$', right: '$$', display: true}},
                {{left: '\\\\[', right: '\\\\]', display: true}},
                {{left: '$', right: '$', display: false}}
            ],
            throwOnError: false,
            strict: 'ignore',
            errorColor: '#B42318',
            ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
        }});
    }}

    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', renderNumaMath, {{once: true}});
    }} else {{
        renderNumaMath();
    }}

    // Tree / connector diagrams (box-drawing characters) need a seamless
    // monospace layout: natural line height, no wrapping, aligned glyphs.
    function markNumaTreeBlocks() {{
        const boxChars = /[\u2500-\u257F]/;
        document.querySelectorAll('pre').forEach(function(pre) {{
            if (boxChars.test(pre.textContent || '')) {{
                pre.classList.add('numa-tree');
            }}
        }});
    }}
    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', markNumaTreeBlocks, {{once: true}});
    }} else {{
        markNumaTreeBlocks();
    }}
}})();
</script>

<script>
(function() {{
    window.currentSlide = 0;
    const slides = document.querySelectorAll('.slide');
    const totalSlides = slides.length;
    const slideMode = {str(is_slide_mode).lower()};
    const paperMode = {str(is_paper_mode).lower()};
    const paperConfig = {json.dumps({
        "title": paper_title,
        "subtitle": paper_subtitle,
        "headerMode": paper_header_mode,
        "footerMode": paper_footer_mode,
        "customHeader": paper_custom_header,
        "headerRightMode": paper_header_right_mode,
        "headerRightText": paper_header_right_text,
        "footerLeftMode": paper_footer_left_mode,
        "footerLeftText": paper_footer_left_text,
    })};
    const previewCanvasEnabled = {str(preview_canvas).lower()};
    const outputWidth = {output_width};
    const outputHeight = {output_height};
    const presentationStage = document.getElementById('presentation-stage');
    const presentationContainer = document.getElementById('presentation-container');
    const overlay = document.getElementById('imageZoomOverlay');
    const zoomStage = document.getElementById('imageZoomStage');
    const zoomTarget = document.getElementById('imageZoomTarget');
    const presentationClock = document.getElementById('presentationClock');
    const studentSyncLabel = document.getElementById('studentSyncLabel');
    const mobilePointer = document.getElementById('numaMobilePointer');
    const mobileTrail = document.getElementById('numaMobileTrail');
    const mobileTrailCanvas = document.getElementById('numaMobileTrailCanvas');
    const mobileTrailContext = mobileTrailCanvas ? mobileTrailCanvas.getContext('2d') : null;
    let mobilePointerState = {{ x: 0.5, y: 0.5, visible: false }};
    let mobilePointerConfig = {{ size: 24, shape: 'ring', color: '#39FF14', trail: 0, trail_mode: 'none' }};
    let mobileTrailPoints = [];
    let mobileTrailFrame = 0;
    let mobilePointerFrame = 0;

    // Chromium may consume Ctrl+wheel before Qt receives the QWheelEvent.
    // Handle it in the document as well so slide zoom never falls back to
    // browser page zoom or becomes dependent on event propagation.
    if (slideMode) {{
        document.addEventListener('wheel', function(event) {{
            if (!event.ctrlKey) return;
            event.preventDefault();
            event.stopPropagation();
            const root = document.documentElement;
            const container = presentationContainer;
            if (!container) return;
            let factor = parseFloat(getComputedStyle(root).getPropertyValue('--numa-user-zoom')) || 1;
            factor += event.deltaY < 0 ? 0.1 : -0.1;
            factor = Math.max(0.01, Math.min(10, factor));
            root.style.setProperty('--numa-user-zoom', String(factor));
            root.style.setProperty('--numa-zoom-percent', Math.round(factor * 100) + '%');
            container.style.transformOrigin = 'center center';
            container.style.transform = 'scale(' + factor + ')';
        }}, {{capture: true, passive: false}});
    }}

    function paperHeaderText() {{
        return paperTextFor(paperConfig.headerMode, paperConfig.customHeader);
    }}

    function paperTextFor(mode, customText) {{
        if (mode === 'none') return '';
        if (mode === 'custom') return customText || paperConfig.title;
        if (mode === 'subtitle') return paperConfig.subtitle || paperConfig.title;
        if (mode === 'auto_hierarchy') {{
            return [paperConfig.title, paperConfig.subtitle].filter(Boolean).join(' - ');
        }}
        return paperConfig.title || paperConfig.subtitle;
    }}

    function paperFooterText(index, total) {{
        if (paperConfig.footerMode === 'none') return '';
        if (paperConfig.footerMode === 'page') return 'Pagina ' + index;
        if (paperConfig.footerMode === 'auto_hierarchy') {{
            const hierarchy = [paperConfig.title, paperConfig.subtitle].filter(Boolean).join(' - ');
            return hierarchy ? hierarchy + ' | ' + index + ' / ' + total : index + ' / ' + total;
        }}
        return 'Pagina ' + index + ' de ' + total;
    }}

    function fitPaperCodeBlocks() {{
        document.querySelectorAll('.print-page pre code').forEach(function(code) {{
            const pre = code.parentElement;
            const style = getComputedStyle(pre);
            const available = pre.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
            if (available <= 0) return;
            code.style.display = 'block';
            code.style.whiteSpace = 'pre';
            code.style.width = 'max-content';
            const fontSize = parseFloat(getComputedStyle(code).fontSize);
            const width = code.offsetWidth;
            if (width > available) {{
                code.style.fontSize = (fontSize * available / width * 0.98) + 'px';
            }}
        }});
    }}

    function fitPaperMathBlocks() {{
        document.querySelectorAll('.print-page .katex-display').forEach(function(display) {{
            const math = display.querySelector('.katex');
            if (!math || display.clientWidth <= 0) return;
            math.style.display = 'inline-block';
            math.style.width = 'max-content';
            math.style.maxWidth = 'none';
            const fontSize = parseFloat(getComputedStyle(math).fontSize);
            const width = math.getBoundingClientRect().width;
            if (width > display.clientWidth) {{
                math.style.fontSize = (fontSize * display.clientWidth / width * 0.98) + 'px';
            }}
        }});
    }}

    function paginatePaperPages() {{
        if (!paperMode || document.documentElement.dataset.numaPaperPaginated) return;
        fitPaperCodeBlocks();
        fitPaperMathBlocks();
        document.documentElement.dataset.numaPaperPaginated = 'true';
        const sourcePages = Array.from(document.querySelectorAll('.print-page'));
        const hasPaperHeader = !!(
            paperHeaderText() || paperTextFor(paperConfig.headerRightMode, paperConfig.headerRightText)
        );
        sourcePages.forEach(function(page) {{
            page.classList.toggle('has-print-header', hasPaperHeader);
        }});
        sourcePages.forEach(function(sourcePage) {{
            const sourceContent = sourcePage.querySelector('.print-page-content');
            if (!sourceContent) return;
            const blocks = Array.from(sourceContent.children);
            if (!blocks.length) return;
            blocks.forEach(function(block) {{ block.remove(); }});
            let currentPage = sourcePage;
            let currentContent = sourceContent;
            const createPage = function() {{
                const page = sourcePage.cloneNode(false);
                page.dataset.generated = 'true';
                if (sourcePage.dataset.slideIndex) {{
                    page.dataset.sourceSlideIndex = sourcePage.dataset.slideIndex;
                }}
                page.removeAttribute('data-slide-index');
                const content = document.createElement('div');
                content.className = 'print-page-content';
                const footer = document.createElement('div');
                footer.className = 'print-page-number';
                page.appendChild(content);
                page.appendChild(footer);
                currentPage.parentNode.insertBefore(page, currentPage.nextSibling);
                return [page, content];
            }};
            blocks.forEach(function(block) {{
                if (block.matches('table')) {{
                    const rows = Array.from(block.querySelectorAll(':scope > tbody > tr, :scope > tr'));
                    let table, body;
                    const startTable = function() {{
                        table = block.cloneNode(false);
                        Array.from(block.children).forEach(function(child) {{
                            if (child.matches('caption, colgroup, thead')) table.appendChild(child.cloneNode(true));
                        }});
                        body = document.createElement('tbody');
                        table.appendChild(body);
                        currentContent.appendChild(table);
                    }};
                    const nextTable = function() {{
                        if (!body.children.length) table.remove();
                        const next = createPage();
                        currentPage = next[0];
                        currentContent = next[1];
                        startTable();
                    }};
                    const overflows = function() {{
                        return currentContent.scrollHeight > currentContent.clientHeight + 1;
                    }};
                    // Clone a text range, retaining inline markup in continued cells.
                    const sliceCell = function(cell, start, end) {{
                        const clone = cell.cloneNode(false);
                        const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
                        const nodes = [];
                        let node, offset = 0;
                        while ((node = walker.nextNode())) {{
                            nodes.push([node, offset]);
                            offset += node.length;
                        }}
                        if (start >= end || !nodes.length) return clone;
                        const point = function(position) {{
                            for (const entry of nodes) {{
                                if (position <= entry[1] + entry[0].length)
                                    return [entry[0], position - entry[1]];
                            }}
                            const last = nodes[nodes.length - 1][0];
                            return [last, last.length];
                        }};
                        const range = document.createRange();
                        range.setStart(...point(start));
                        range.setEnd(...point(end));
                        clone.appendChild(range.cloneContents());
                        return clone;
                    }};
                    startTable();
                    rows.forEach(function(original) {{
                        let row = original;
                        body.appendChild(row);
                        if (!overflows()) return;
                        row.remove();
                        if (body.children.length || currentContent.children.length > 1) nextTable();
                        body.appendChild(row);
                        while (overflows()) {{
                            row.remove();
                            const cells = Array.from(row.cells);
                            const length = Math.max(...cells.map(cell => cell.textContent.length));
                            if (length < 2) {{
                                // Non-text media cannot be split into character ranges.
                                body.appendChild(row);
                                row.querySelectorAll('img').forEach(function(img) {{
                                    img.style.maxHeight = Math.max(20, currentContent.clientHeight - 100) + 'px';
                                    img.style.width = 'auto';
                                }});
                                break;
                            }}
                            let low = 1, high = length - 1, best = 0;
                            const fragment = function(count, remainder) {{
                                const part = row.cloneNode(false);
                                cells.forEach(function(cell) {{
                                    const cut = Math.min(count, cell.textContent.length);
                                    part.appendChild(sliceCell(cell, remainder ? cut : 0,
                                        remainder ? cell.textContent.length : cut));
                                }});
                                return part;
                            }};
                            while (low <= high) {{
                                const mid = Math.floor((low + high) / 2);
                                const trial = fragment(mid, false);
                                body.appendChild(trial);
                                if (!overflows()) {{ best = mid; low = mid + 1; }}
                                else high = mid - 1;
                                trial.remove();
                            }}
                            if (!best) {{
                                // Retry on a fresh page before splitting an oversized row.
                                if (body.children.length || currentContent.children.length > 1) {{
                                    nextTable();
                                    body.appendChild(row);
                                    continue;
                                }}
                                best = 1;
                            }}
                            body.appendChild(fragment(best, false));
                            row = fragment(best, true);
                            nextTable();
                            body.appendChild(row);
                        }}
                    }});
                    const footer = block.querySelector(':scope > tfoot');
                    if (footer) {{
                        table.appendChild(footer);
                        if (overflows()) {{ footer.remove(); nextTable(); table.appendChild(footer); }}
                    }}
                    return;
                }}
                if (block.matches('ol, ul')) {{
                    const items = Array.from(block.children);
                    let list = block.cloneNode(false);
                    let number = block.hasAttribute('start') ? Number(block.getAttribute('start')) : 1;
                    const step = block.hasAttribute('reversed') ? -1 : 1;
                    if (block.hasAttribute('reversed') && !block.hasAttribute('start')) number = items.length;
                    if (block.tagName === 'OL') list.setAttribute('start', number);
                    currentContent.appendChild(list);
                    items.forEach(function(item) {{
                        if (item.hasAttribute('value')) number = Number(item.getAttribute('value'));
                        list.appendChild(item);
                        if (currentContent.scrollHeight > currentContent.clientHeight + 1 &&
                            (list.children.length > 1 || currentContent.children.length > 1)) {{
                            item.remove();
                            if (!list.children.length) list.remove();
                            const next = createPage();
                            currentPage = next[0];
                            currentContent = next[1];
                            list = block.cloneNode(false);
                            if (block.tagName === 'OL') list.setAttribute('start', number);
                            currentContent.appendChild(list);
                            list.appendChild(item);
                        }}
                        number += step;
                    }});
                    return;
                }}
                currentContent.appendChild(block);
                if (currentContent.scrollHeight <= currentContent.clientHeight + 1) return;
                if (currentContent.children.length === 1) return;
                currentContent.removeChild(block);
                const next = createPage();
                currentPage = next[0];
                currentContent = next[1];
                currentContent.appendChild(block);
            }});
        }});
        Array.from(document.querySelectorAll('.print-page')).forEach(function(page) {{
            const content = page.querySelector('.print-page-content');
            if (!content) return;
            const hasText = (content.textContent || '').trim().length > 0;
            const hasMedia = !!content.querySelector('img, video, audio, iframe, table, pre, svg, canvas');
            if (!hasText && !hasMedia) page.remove();
        }});
        const pages = Array.from(document.querySelectorAll('.print-page'));
        pages.forEach(function(page, index) {{
            let header = page.querySelector('.print-page-header');
            const headerText = paperHeaderText();
            const rightText = paperTextFor(paperConfig.headerRightMode, paperConfig.headerRightText);
            if (headerText || rightText) {{
                if (!header) {{
                    header = document.createElement('div');
                    header.className = 'print-page-header';
                    page.insertBefore(header, page.firstChild);
                }}
                header.textContent = headerText;
                header.style.display = 'flex';
                header.style.justifyContent = 'space-between';
                let right = header.querySelector('.print-page-header-right');
                if (rightText) {{
                    if (!right) {{
                        right = document.createElement('span');
                        right.className = 'print-page-header-right';
                        header.appendChild(right);
                    }}
                    right.textContent = rightText;
                    right.style.textAlign = 'right';
                    right.style.overflow = 'hidden';
                    right.style.textOverflow = 'ellipsis';
                }} else if (right) {{
                    right.remove();
                }}
            }} else if (header) {{
                header.remove();
            }}
            const footer = page.querySelector('.print-page-number');
            if (footer) footer.textContent = paperFooterText(index + 1, pages.length);
            const leftText = paperTextFor(paperConfig.footerLeftMode, paperConfig.footerLeftText);
            let footerLeft = page.querySelector('.print-page-footer-left');
            if (leftText) {{
                if (!footerLeft) {{
                    footerLeft = document.createElement('div');
                    footerLeft.className = 'print-page-footer-left';
                    page.appendChild(footerLeft);
                }}
                footerLeft.textContent = leftText;
                footerLeft.style.position = 'absolute';
                footerLeft.style.left = '0.35in';
                footerLeft.style.bottom = '0.22in';
                footerLeft.style.fontSize = '9pt';
            }} else if (footerLeft) {{
                footerLeft.remove();
            }}
        }});
    }}
    let clockConfig = {{
        visible: {str(clock_visible).lower()},
        mode: '{clock_mode}',
        showSeconds: {str(clock_show_seconds).lower()},
        size: {int(clock_size)},
        position: '{clock_position}',
        durationSeconds: {max(1, int(timer_duration_seconds))},
        elapsedSeconds: {max(0, float(timer_elapsed_seconds))},
        running: {str(timer_running).lower()},
        configuredAt: Date.now()
    }};
    let studentSyncLabelConfig = {{
        visible: {str(student_sync_label_visible).lower()},
        labels: {sync_label_map_json}
    }};
    let imageZoom = 1;
    let imagePanX = 0;
    let imagePanY = 0;
    let imageRotation = 0;
    let isDraggingImage = false;
    let isDraggingPresentation = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let presentationDragMode = null;
    let presentationDragMoved = false;
    let presentationPanX = 0;
    let presentationPanY = 0;
    let presentationStartPanX = 0;
    let presentationStartPanY = 0;
    let presentationScrollTarget = null;
    let presentationStartScrollLeft = 0;
    let presentationStartScrollTop = 0;

    function showSlide(index) {{
        if (totalSlides === 0) return;
        slides.forEach(function(s) {{ s.classList.remove('active'); }});
        window.currentSlide = ((index % totalSlides) + totalSlides) % totalSlides;
        slides[window.currentSlide].classList.add('active');
        updateStudentSyncLabel();
        resetPresentationPan();
        updateMobilePointer();
    }}

    function updateMobilePointer() {{
        if (!mobilePointer) return;
        const activeSlide = document.querySelector('.slide.active');
        if (!mobilePointerState.visible || !activeSlide) {{
            mobilePointer.classList.remove('active');
            mobileTrailPoints = [];
            drawMobileTrail();
            return;
        }}
        const rect = activeSlide.getBoundingClientRect();
        const pointerRect = overlay && overlay.classList.contains('active') && zoomTarget
            ? zoomTarget.getBoundingClientRect() : rect;
        const left = pointerRect.left + pointerRect.width * mobilePointerState.x;
        const top = pointerRect.top + pointerRect.height * mobilePointerState.y;
        mobilePointer.style.left = '0px';
        mobilePointer.style.top = '0px';
        mobilePointer.style.margin = '0';
        mobilePointer.style.transform = 'translate3d(' + left + 'px, ' + top + 'px, 0) translate(-50%, -50%)';
        if (mobilePointerConfig.trail > 0 && mobilePointerConfig.trail_mode === 'dots') {{
            const dot = document.createElement('span');
            const trailSize = Math.max(4, mobilePointerConfig.size * 0.45);
            dot.className = 'numa-mobile-trail-dot';
            dot.style.left = left + 'px';
            dot.style.top = top + 'px';
            dot.style.width = trailSize + 'px';
            dot.style.height = trailSize + 'px';
            dot.style.background = mobilePointerConfig.color;
            mobileTrail.appendChild(dot);
            while (mobileTrail.children.length > mobilePointerConfig.trail) {{
                mobileTrail.removeChild(mobileTrail.firstChild);
            }}
            window.setTimeout(function() {{ if (dot.parentNode) dot.remove(); }}, 720);
        }}
        if (mobilePointerConfig.trail > 0 && mobilePointerConfig.trail_mode === 'continuous') {{
            mobileTrailPoints.push({{ left: left, top: top, time: performance.now() }});
            while (mobileTrailPoints.length > mobilePointerConfig.trail) mobileTrailPoints.shift();
            drawMobileTrail();
        }}
        mobilePointer.classList.add('active');
    }}

    function resizeMobileTrailCanvas() {{
        if (!mobileTrailCanvas) return;
        const ratio = window.devicePixelRatio || 1;
        mobileTrailCanvas.width = Math.max(1, Math.round(window.innerWidth * ratio));
        mobileTrailCanvas.height = Math.max(1, Math.round(window.innerHeight * ratio));
        mobileTrailCanvas.style.width = window.innerWidth + 'px';
        mobileTrailCanvas.style.height = window.innerHeight + 'px';
        if (mobileTrailContext) mobileTrailContext.setTransform(ratio, 0, 0, ratio, 0, 0);
    }}

    function drawMobileTrail() {{
        if (!mobileTrailContext || !mobileTrailCanvas) return;
        mobileTrailContext.clearRect(0, 0, window.innerWidth, window.innerHeight);
        if (mobilePointerConfig.trail_mode !== 'continuous' || mobileTrailPoints.length < 2) {{
            mobileTrailFrame = 0;
            return;
        }}
        const now = performance.now();
        const duration = 900;
        mobileTrailContext.lineCap = 'round';
        mobileTrailContext.lineJoin = 'round';
        for (let i = 1; i < mobileTrailPoints.length; i++) {{
            const previous = mobileTrailPoints[i - 1];
            const point = mobileTrailPoints[i];
            const alpha = Math.max(0, 1 - (now - point.time) / duration) * 0.75;
            if (alpha <= 0) continue;
            mobileTrailContext.globalAlpha = alpha;
            mobileTrailContext.strokeStyle = mobilePointerConfig.color;
            mobileTrailContext.lineWidth = Math.max(3, Number(mobilePointerConfig.size) * 0.42);
            mobileTrailContext.beginPath();
            mobileTrailContext.moveTo(previous.left, previous.top);
            mobileTrailContext.lineTo(point.left, point.top);
            mobileTrailContext.stroke();
        }}
        mobileTrailContext.globalAlpha = 1;
        mobileTrailPoints = mobileTrailPoints.filter(function(point) {{ return now - point.time < duration; }});
        if (mobileTrailPoints.length > 1) {{
            mobileTrailFrame = window.requestAnimationFrame(drawMobileTrail);
        }} else {{
            mobileTrailFrame = 0;
        }}
    }}

    function applyMobilePointerConfig() {{
        if (!mobilePointer) return;
        const size = Math.max(8, Math.min(96, Number(mobilePointerConfig.size) || 24));
        const color = mobilePointerConfig.color || '#39FF14';
        mobilePointer.style.width = size + 'px';
        mobilePointer.style.height = size + 'px';
        mobilePointer.style.margin = '0';
        mobilePointer.style.background = mobilePointerConfig.shape === 'dot' ? color : 'transparent';
        mobilePointer.style.border = mobilePointerConfig.shape === 'dot' ? '0' : '3px solid ' + color;
        mobilePointer.style.boxShadow = mobilePointerConfig.shape === 'dot'
            ? '0 0 0 2px ' + color + ', 0 3px 8px rgba(0, 0, 0, 0.45)'
            : '0 0 0 2px ' + color + ', 0 3px 8px rgba(0, 0, 0, 0.45)';
    }}

    window.setNumaMobilePointerConfig = function(config) {{
        config = config || {{}};
        mobilePointerConfig.size = Math.max(8, Math.min(96, Number(config.size) || 24));
        mobilePointerConfig.shape = config.shape === 'dot' ? 'dot' : 'ring';
        mobilePointerConfig.color = /^#[0-9A-Fa-f]{{6}}$/.test(config.color || '') ? config.color : '#39FF14';
        mobilePointerConfig.trail = Math.max(0, Math.min(48, Number(config.trail) || 0));
        mobilePointerConfig.trail_mode = ['none', 'dots', 'continuous'].includes(config.trail_mode)
            ? config.trail_mode : (mobilePointerConfig.trail ? 'dots' : 'none');
        mobileTrailPoints = [];
        if (mobileTrail) mobileTrail.replaceChildren();
        if (mobileTrailContext && mobileTrailCanvas) mobileTrailContext.clearRect(0, 0, window.innerWidth, window.innerHeight);
        applyMobilePointerConfig();
    }};

    window.setNumaMobilePointer = function(x, y, visible) {{
        mobilePointerState.x = Math.max(0, Math.min(1, Number(x) || 0));
        mobilePointerState.y = Math.max(0, Math.min(1, Number(y) || 0));
        mobilePointerState.visible = Boolean(visible);
        if (!mobilePointerFrame) {{
            mobilePointerFrame = window.requestAnimationFrame(function() {{
                mobilePointerFrame = 0;
                updateMobilePointer();
            }});
        }}
    }};

    function mobilePointerViewportPoint(x, y) {{
        const activeSlide = document.querySelector('.slide.active');
        if (!activeSlide) return null;
        const rect = activeSlide.getBoundingClientRect();
        return {{
            x: rect.left + rect.width * Math.max(0, Math.min(1, Number(x) || 0)),
            y: rect.top + rect.height * Math.max(0, Math.min(1, Number(y) || 0))
        }};
    }}

    window.mobileMouseClick = function(x, y, clickCount) {{
        if (overlay && overlay.classList.contains('active')) return false;
        const point = mobilePointerViewportPoint(x, y);
        if (!point) return false;
        const element = document.elementFromPoint(point.x, point.y);
        const image = element ? element.closest('img') : null;
        if (image && presentationContainer.contains(image)) {{
            openImageZoom(image);
            return true;
        }}
        const link = element ? element.closest('a, button') : null;
        if (link && presentationContainer.contains(link)) {{
            if (Number(clickCount || 1) >= 2) {{
                link.dispatchEvent(new MouseEvent('dblclick', {{ bubbles: true, cancelable: true }}));
            }} else {{
                link.click();
            }}
            return true;
        }}
        return false;
    }};

    window.mobileMouseMove = function(x, y) {{
        if (overlay && overlay.classList.contains('active')) return false;
        const point = mobilePointerViewportPoint(x, y);
        if (!point) return false;
        const element = document.elementFromPoint(point.x, point.y);
        if (!element) return false;
        element.dispatchEvent(new MouseEvent('mousemove', {{
            bubbles: true,
            cancelable: true,
            clientX: point.x,
            clientY: point.y,
            screenX: point.x,
            screenY: point.y
        }}));
        return true;
    }};

    window.mobileMouseScroll = function(x, y, deltaY) {{
        if (overlay && overlay.classList.contains('active')) {{
            const zoomDelta = -Number(deltaY || 0) * 1.5;
            imageZoom = Math.max(1, Math.min(6, imageZoom + zoomDelta));
            if (imageZoom === 1) {{
                imagePanX = 0;
                imagePanY = 0;
            }}
            applyImageZoom();
            return true;
        }}
        const point = mobilePointerViewportPoint(x, y);
        const element = point ? document.elementFromPoint(point.x, point.y) : document.body;
        const target = findScrollableDragTarget(element);
        const amount = Number(deltaY || 0) * Math.max(320, window.innerHeight * 1.8);
        if (target && target !== document.body && target !== document.documentElement) {{
            target.scrollTop += amount;
        }} else {{
            window.scrollBy(0, amount);
        }}
        return true;
    }};

    applyMobilePointerConfig();

    resizeMobileTrailCanvas();
    window.addEventListener('resize', function() {{ resizeMobileTrailCanvas(); updateMobilePointer(); }});
    window.addEventListener('scroll', updateMobilePointer, true);

    function resetPresentationPan() {{
        presentationPanX = 0;
        presentationPanY = 0;
        document.documentElement.style.setProperty('--numa-pan-x', '0px');
        document.documentElement.style.setProperty('--numa-pan-y', '0px');
    }}

    function fitPreviewCanvas() {{
        if (!previewCanvasEnabled) return;
        var margin = 24;
        var scaleX = Math.max(0.05, (window.innerWidth - margin) / outputWidth);
        var scaleY = Math.max(0.05, (window.innerHeight - margin) / outputHeight);
        document.documentElement.style.setProperty('--preview-scale', Math.min(scaleX, scaleY));
    }}

    function applyImageZoom() {{
        zoomTarget.style.transform = 'translate(' + imagePanX + 'px, ' + imagePanY + 'px) rotate(' + imageRotation + 'deg) scale(' + imageZoom + ')';
        updateMobilePointer();
    }}

    function rotateImage(delta) {{
        imageRotation = (imageRotation + delta) % 360;
        applyImageZoom();
    }}

    function closeImageZoom() {{
        overlay.classList.remove('active');
        overlay.setAttribute('aria-hidden', 'true');
        zoomTarget.removeAttribute('src');
        isDraggingImage = false;
        zoomStage.classList.remove('dragging');
        updateMobilePointer();
    }}

    window.isImageZoomOpen = function() {{
        return overlay.classList.contains('active');
    }};

    window.closeImageZoom = closeImageZoom;

    window.adjustImageZoom = function(delta) {{
        if (!overlay.classList.contains('active')) return false;
        imageZoom = Math.max(1, imageZoom + Number(delta || 0));
        if (imageZoom === 1) {{
            imagePanX = 0;
            imagePanY = 0;
        }}
        applyImageZoom();
        return true;
    }};

    window.getNumaInteractiveState = function() {{
        return {{
            slide: Number(window.currentSlide || 0),
            imageOpen: overlay.classList.contains('active'),
            imageSrc: zoomTarget.currentSrc || zoomTarget.src || '',
            imageAlt: zoomTarget.alt || '',
            imageZoom: Number(imageZoom || 1),
            imagePanX: Number(imagePanX || 0),
            imagePanY: Number(imagePanY || 0),
            imageRotation: Number(imageRotation || 0),
            presentationPanX: Number(presentationPanX || 0),
            presentationPanY: Number(presentationPanY || 0)
        }};
    }};

    window.applyNumaInteractiveState = function(state) {{
        state = state || {{}};
        if (typeof state.slide === 'number' && totalSlides > 0) {{
            showSlide(state.slide);
        }}
        presentationPanX = Number(state.presentationPanX || 0);
        presentationPanY = Number(state.presentationPanY || 0);
        document.documentElement.style.setProperty('--numa-pan-x', presentationPanX + 'px');
        document.documentElement.style.setProperty('--numa-pan-y', presentationPanY + 'px');
        if (state.imageOpen && state.imageSrc) {{
            imageZoom = Math.max(1, Number(state.imageZoom || 1));
            imagePanX = Number(state.imagePanX || 0);
            imagePanY = Number(state.imagePanY || 0);
            imageRotation = Number(state.imageRotation || 0);
            zoomTarget.src = state.imageSrc;
            zoomTarget.alt = state.imageAlt || '';
            applyImageZoom();
            overlay.classList.add('active');
            overlay.setAttribute('aria-hidden', 'false');
            updateMobilePointer();
        }} else {{
            closeImageZoom();
        }}
    }};

    function openImageZoom(img) {{
        imageZoom = 1;
        imagePanX = 0;
        imagePanY = 0;
        imageRotation = 0;
        zoomTarget.src = img.currentSrc || img.src;
        zoomTarget.alt = img.alt || '';
        applyImageZoom();
        overlay.classList.add('active');
        overlay.setAttribute('aria-hidden', 'false');
        updateMobilePointer();
    }}

    window.openImageZoom = openImageZoom;

    window.nextSlide = function() {{ showSlide(window.currentSlide + 1); }};
    window.prevSlide = function() {{ showSlide(window.currentSlide - 1); }};
    window.gotoSlide = function(i) {{ showSlide(i); }};

    function isInteractiveDragTarget(target) {{
        if (!target) return false;
        return !!target.closest('a, button, input, textarea, select, label, img, video, audio, iframe, .image-zoom-overlay, #numaTeacherMarker');
    }}

    function findScrollableDragTarget(target) {{
        var node = target;
        while (node && node !== document.body && node !== document.documentElement) {{
            if (node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth) {{
                return node;
            }}
            node = node.parentElement;
        }}
        return document.scrollingElement || document.documentElement;
    }}

    function startPresentationDrag(e) {{
        if (e.button !== 0 || overlay.classList.contains('active')) return;
        if (!presentationContainer.contains(e.target) || isInteractiveDragTarget(e.target)) return;
        isDraggingPresentation = true;
        presentationDragMoved = false;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        document.body.classList.add('dragging-presentation');

        if (slideMode && previewCanvasEnabled) {{
            presentationDragMode = 'pan';
            presentationStartPanX = presentationPanX;
            presentationStartPanY = presentationPanY;
        }} else {{
            presentationDragMode = 'scroll';
            presentationScrollTarget = findScrollableDragTarget(e.target);
            presentationStartScrollLeft = presentationScrollTarget.scrollLeft;
            presentationStartScrollTop = presentationScrollTarget.scrollTop;
        }}
        e.preventDefault();
    }}

    function movePresentationDrag(e) {{
        if (!isDraggingPresentation) return;
        var dx = e.clientX - dragStartX;
        var dy = e.clientY - dragStartY;
        if (Math.abs(dx) + Math.abs(dy) > 3) {{
            presentationDragMoved = true;
        }}
        if (presentationDragMode === 'pan') {{
            presentationPanX = presentationStartPanX + dx;
            presentationPanY = presentationStartPanY + dy;
            document.documentElement.style.setProperty('--numa-pan-x', presentationPanX + 'px');
            document.documentElement.style.setProperty('--numa-pan-y', presentationPanY + 'px');
        }} else if (presentationScrollTarget) {{
            presentationScrollTarget.scrollLeft = presentationStartScrollLeft - dx;
            presentationScrollTarget.scrollTop = presentationStartScrollTop - dy;
        }}
        e.preventDefault();
    }}

    function stopPresentationDrag() {{
        if (!isDraggingPresentation) return;
        isDraggingPresentation = false;
        presentationDragMode = null;
        presentationScrollTarget = null;
        document.body.classList.remove('dragging-presentation');
        setTimeout(function() {{ presentationDragMoved = false; }}, 0);
    }}

    function updateClock() {{
        if (clockConfig.mode === 'stopwatch' || clockConfig.mode === 'timer') {{
            var elapsed = Number(clockConfig.elapsedSeconds || 0);
            if (clockConfig.running) {{
                elapsed += Math.max(0, (Date.now() - Number(clockConfig.configuredAt || Date.now())) / 1000);
            }}
            var value = clockConfig.mode === 'timer'
                ? Math.max(0, Number(clockConfig.durationSeconds || 0) - elapsed)
                : Math.max(0, elapsed);
            if (clockConfig.mode === 'timer' && value <= 0 && clockConfig.running) {{
                clockConfig.elapsedSeconds = Number(clockConfig.durationSeconds || 0);
                clockConfig.running = false;
            }}
            var totalSeconds = Math.floor(value);
            var hours = Math.floor(totalSeconds / 3600);
            var minutes = Math.floor((totalSeconds % 3600) / 60);
            var seconds = totalSeconds % 60;
            presentationClock.textContent = (hours > 0 ? String(hours).padStart(2, '0') + ':' : '')
                + String(minutes).padStart(2, '0') + ':' + String(seconds).padStart(2, '0');
            return;
        }}
        var now = new Date();
        var options = {{
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        }};
        if (clockConfig.showSeconds) options.second = '2-digit';
        presentationClock.textContent = now.toLocaleTimeString([], options);
    }}

    function applyClockConfig() {{
        presentationClock.style.display = clockConfig.visible ? 'block' : 'none';
        presentationClock.style.fontSize = clockConfig.size + 'px';
        presentationClock.classList.remove('top-left', 'top-right', 'bottom-left', 'bottom-right');
        presentationClock.classList.add(clockConfig.position);
        updateClock();
    }}

    window.setNumaClockConfig = function(config) {{
        clockConfig = Object.assign(clockConfig, config || {{}});
        clockConfig.configuredAt = Date.now();
        applyClockConfig();
    }};

    function updateStudentSyncLabel() {{
        if (!studentSyncLabel) return;
        if (!studentSyncLabelConfig.visible) {{
            studentSyncLabel.style.display = 'none';
            return;
        }}
        const slideNumber = studentSyncLabelConfig.labels[String(window.currentSlide)];
        studentSyncLabel.innerHTML = slideNumber
            ? '<a href="numa-sync:' + slideNumber + '">Profesor: diapositiva ' + slideNumber + '</a>'
            : 'Profesor: sin sincronizar';
        studentSyncLabel.title = slideNumber
            ? 'Ir al slide vinculado del profesor'
            : '';
        studentSyncLabel.style.display = 'block';
    }}

    window.setNumaStudentSyncLabelConfig = function(config) {{
        studentSyncLabelConfig = Object.assign(studentSyncLabelConfig, config || {{}});
        updateStudentSyncLabel();
    }};

    function resolveSlideTarget(href) {{
        if (!href) return null;
        var value = href.trim();
        var lower = value.toLowerCase();
        var target = null;

        if (lower.indexOf('slide-id:') === 0) {{
            target = value.slice(9).trim();
            try {{
                target = decodeURIComponent(target);
            }} catch (err) {{}}
            for (var idIndex = 0; idIndex < slides.length; idIndex++) {{
                if (slides[idIndex].getAttribute('data-slide-id') === target) {{
                    return idIndex;
                }}
            }}
            return null;
        }}

        if (lower.indexOf('slide-key:') === 0) {{
            target = value.slice(10).trim();
            try {{
                target = decodeURIComponent(target);
            }} catch (err) {{}}
            for (var i = 0; i < slides.length; i++) {{
                if (slides[i].getAttribute('data-slide-key') === target) {{
                    return i;
                }}
            }}
            return null;
        }}

        if (lower.indexOf('slide:') === 0) {{
            target = value.slice(6).trim();
        }} else if (lower.indexOf('#slide-') === 0) {{
            target = value.slice(7).trim();
        }} else {{
            return null;
        }}

        if (/^[+-]\\d+$/.test(target)) {{
            return window.currentSlide + parseInt(target, 10);
        }}
        if (/^\\d+$/.test(target)) {{
            return parseInt(target, 10) - 1;
        }}
        return null;
    }}

    document.querySelectorAll('#presentation-container a').forEach(function(link) {{
        link.addEventListener('click', function(e) {{
            if (presentationDragMoved) {{
                e.preventDefault();
                e.stopPropagation();
                return;
            }}
            var targetSlide = resolveSlideTarget(link.getAttribute('href'));
            if (targetSlide === null) return;
            showSlide(targetSlide);
            e.preventDefault();
            e.stopPropagation();
        }});
    }});

    document.querySelectorAll('#presentation-container img').forEach(function(img) {{
        img.addEventListener('click', function(e) {{
            if (presentationDragMoved) {{
                e.preventDefault();
                e.stopPropagation();
                return;
            }}
            openImageZoom(img);
            e.preventDefault();
            e.stopPropagation();
        }});
    }});

    presentationContainer.addEventListener('mousedown', startPresentationDrag);
    document.addEventListener('mousemove', movePresentationDrag);
    document.addEventListener('mouseup', stopPresentationDrag);
    document.addEventListener('mouseleave', stopPresentationDrag);

    overlay.addEventListener('click', function(e) {{
        if (e.target === overlay) closeImageZoom();
    }});

    zoomStage.addEventListener('wheel', function(e) {{
        if (!overlay.classList.contains('active')) return;
        var delta = e.deltaY < 0 ? 0.18 : -0.18;
        imageZoom = Math.max(1, imageZoom + delta);
        if (imageZoom === 1) {{
            imagePanX = 0;
            imagePanY = 0;
        }}
        applyImageZoom();
        e.preventDefault();
    }}, {{ passive: false }});

    zoomTarget.addEventListener('mousedown', function(e) {{
        if (imageZoom <= 1) return;
        isDraggingImage = true;
        dragStartX = e.clientX - imagePanX;
        dragStartY = e.clientY - imagePanY;
        zoomStage.classList.add('dragging');
        e.preventDefault();
    }});

    zoomTarget.addEventListener('load', function() {{
        updateMobilePointer();
    }});

    document.addEventListener('mousemove', function(e) {{
        if (!isDraggingImage) return;
        imagePanX = e.clientX - dragStartX;
        imagePanY = e.clientY - dragStartY;
        applyImageZoom();
    }});

    document.addEventListener('mouseup', function() {{
        isDraggingImage = false;
        zoomStage.classList.remove('dragging');
    }});

    document.addEventListener('keydown', function(e) {{
        if (overlay.classList.contains('active')) {{
            if (e.key === 'Escape') {{
                closeImageZoom();
                e.preventDefault();
            }} else if (e.key === 'l' || e.key === 'L') {{
                rotateImage(-90);
                e.preventDefault();
            }} else if (e.key === 'r' || e.key === 'R') {{
                rotateImage(90);
                e.preventDefault();
            }}
            return;
        }}
        if (totalSlides === 0) return;
        var key = e.key;
        if (key === 'ArrowRight' || key === ' ' || key === 'PageDown') {{
            window.nextSlide();
            console.log('NUMA_SLIDE:' + window.currentSlide);
            e.preventDefault();
        }} else if (key === 'ArrowLeft' || key === 'Backspace' || key === 'PageUp') {{
            window.prevSlide();
            console.log('NUMA_SLIDE:' + window.currentSlide);
            e.preventDefault();
        }}
    }});

    applyClockConfig();
    if (paperMode) {{
        // Wait for images before calculating page breaks so their final
        // dimensions cannot hide subsequent paragraph blocks.
        window.addEventListener('load', function() {{
            document.fonts.ready.then(paginatePaperPages);
        }}, {{ once: true }});
    }}
    setInterval(updateClock, 1000);
    fitPreviewCanvas();
    window.addEventListener('resize', fitPreviewCanvas);

    if (totalSlides > 0) showSlide(0);
}})();
</script>
</body>
</html>"""
