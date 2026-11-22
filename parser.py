import re
import os
import markdown
import html
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse


SLIDE_DELIMITER_PATTERN = re.compile(r'^\s*---\s*$', re.MULTILINE)
DOCUMENT_ALIGNMENT_PATTERN = re.compile(
    r'^\s*<!--\s*numa-document-align:\s*(left|center|right|justify)\s*-->\s*$',
    re.IGNORECASE | re.MULTILINE,
)
IMAGE_DISPLAY_DIRECTIVE_PATTERN = re.compile(
    r'<!--\s*numa-image:\s*width=(auto|(?:[1-9]\d?|100)%),\s*'
    r'align=(left|center|right),\s*spacing=(compact|normal|wide)'
    r'(?:,\s*orientation=(0|90|180|270))?'
    r'(?:,\s*color=(color|grayscale))?'
    r'(?:,\s*frame=(none|plain|shadow))?\s*-->',
    re.IGNORECASE,
)
SLIDE_ID_PATTERN = re.compile(r'<!--\s*numa-slide-id:\s*([a-zA-Z0-9_-]+)\s*-->')
SYNC_ID_PATTERN = re.compile(r'<!--\s*numa-sync-id:\s*([a-zA-Z0-9_-]+)\s*-->')
SLIDE_LINK_PATTERN = re.compile(r'\]\((slide-id:[^)]+|slide-key:[^)]+|slide:[^)]+|#slide-\d+)\)')
MARKDOWN_FILE_LINK_PATTERN = re.compile(
    r'(?<!!)\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["\'][^)]*["\'])?\s*\)',
    re.IGNORECASE,
)
HTML_FILE_LINK_PATTERN = re.compile(
    r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
MARKDOWN_IMAGE_PATTERN = re.compile(
    r'!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^)]+?))\s*\)',
    re.IGNORECASE,
)
MATH_BLOCK_PATTERN = re.compile(r'(?<!\\)\$\$(.+?)(?<!\\)\$\$', re.DOTALL)
MATH_TEX_BLOCK_PATTERN = re.compile(r'(?<!\\)\\\[(.+?)(?<!\\)\\\]', re.DOTALL)
MATH_INLINE_PATTERN = re.compile(r'(?<!\\)(?<!\$)\$(?!\$)([^\n$]+?)(?<!\\)\$(?!\$)')


def get_slide_metadata(md_text):
    """Return slide number, title, and stable target metadata for a Markdown deck."""
    sections = _split_slide_sections(md_text)
    used_keys = {}
    metadata = []
    for index, section in enumerate(sections):
        slide_num = index + 1
        slide_id = _extract_slide_id(section)
        sync_id = _extract_sync_id(section)
        title = _extract_slide_title(section, f"Slide {slide_num}")
        key = _make_slide_key(title, slide_num, used_keys)
        metadata.append({
            "index": index,
            "number": slide_num,
            "title": title,
            "key": key,
            "id": slide_id,
            "sync_id": sync_id,
            "target": slide_id or key,
        })
    return metadata


def ensure_slide_ids(md_text):
    """Insert invisible stable IDs into slides that do not have one."""
    if md_text is None:
        return "", False

    parts = re.split(r'(^\s*---\s*$)', md_text, flags=re.MULTILINE)
    changed = False
    next_is_slide = True
    result = []

    for part in parts:
        if re.match(r'^\s*---\s*$', part or ""):
            result.append(part)
            next_is_slide = True
            continue

        if not next_is_slide:
            result.append(part)
            continue

        if part.strip() and not _extract_slide_id(part):
            part = _insert_slide_id(part, _new_slide_id())
            changed = True
        result.append(part)
        next_is_slide = False

    return "".join(result), changed


def filter_slides_with_file_links(md_text):
    """Return an export-only deck without slides containing local-file links."""
    sections = _split_slide_sections(md_text)
    kept_sections = [section for section in sections if not slide_has_file_link(section)]
    removed_count = len(sections) - len(kept_sections)
    return "\n\n---\n\n".join(kept_sections), removed_count, len(kept_sections)


def find_broken_local_image_links(md_text, base_path):
    """Return local Markdown image references whose target file no longer exists."""
    broken = []
    for start, end, alt, target in _iter_markdown_image_links(md_text):
        image_path = _local_target_path(target, base_path)
        if image_path and not os.path.isfile(image_path):
            broken.append({
                "start": start,
                "end": end,
                "alt": alt,
                "target": target,
                "path": image_path,
                "name": os.path.basename(image_path),
            })
    return broken


def repair_broken_local_image_links(md_text, broken_links, search_directory):
    """Relink broken images by matching their filenames inside a selected directory."""
    file_index = {}
    for root, _, files in os.walk(search_directory):
        for filename in files:
            file_index.setdefault(filename.casefold(), []).append(os.path.join(root, filename))

    replacements = []
    unresolved = []
    for link in broken_links:
        candidates = file_index.get(link["name"].casefold(), [])
        if not candidates:
            unresolved.append(link)
            continue
        direct_candidate = os.path.join(search_directory, link["name"])
        candidate = direct_candidate if os.path.isfile(direct_candidate) else candidates[0]
        target = Path(candidate).resolve().as_posix()
        replacements.append((link["start"], link["end"], f'![{link["alt"]}](<{target}>)'))

    updated = md_text or ""
    for start, end, replacement in reversed(replacements):
        updated = updated[:start] + replacement + updated[end:]
    return updated, len(replacements), unresolved


def _local_target_path(target, base_path):
    value = html.unescape((target or "").strip()).strip("<>")
    lower = value.lower()
    if not value or lower.startswith(("http://", "https://", "data:")):
        return None
    if lower.startswith("file:"):
        parsed = urlparse(value)
        path = unquote(parsed.path)
        if parsed.netloc:
            path = f"//{parsed.netloc}{path}"
        if re.match(r"^/[a-zA-Z]:/", path):
            path = path[1:]
        return os.path.normpath(path)
    if re.match(r"^[a-zA-Z]:[\\/]", value) or value.startswith(("\\\\", "//")):
        return os.path.normpath(value)
    return os.path.normpath(os.path.join(base_path or os.getcwd(), value))


def slide_has_file_link(section):
    """Detect clickable local-file links while ignoring images and web/slide URLs."""
    targets = []
    for match in MARKDOWN_FILE_LINK_PATTERN.finditer(section or ""):
        targets.append(match.group(1) or match.group(2) or "")
    targets.extend(HTML_FILE_LINK_PATTERN.findall(section or ""))
    return any(_is_local_file_target(target) for target in targets)


def _is_local_file_target(target):
    value = html.unescape((target or "").strip()).strip("<>")
    if not value:
        return False

    lower = value.lower()
    if lower.startswith(("slide:", "slide-id:", "slide-key:", "#")):
        return False
    if lower.startswith(("http://", "https://", "mailto:", "tel:", "data:", "javascript:")):
        return False
    if lower.startswith("file:"):
        return True
    if re.match(r"^[a-zA-Z]:[\\/]", value) or value.startswith(("\\\\", "//", "./", "../")):
        return True

    clean_value = re.split(r"[?#]", value, maxsplit=1)[0]
    return bool(Path(clean_value).suffix) and ":" not in clean_value


def create_slide_id_marker():
    """Return the invisible Markdown marker used to identify a slide."""
    return f"<!-- numa-slide-id: {_new_slide_id()} -->"


def create_sync_id():
    """Return a stable ID used to pair student and teacher slides."""
    return f"sync-{_new_slide_id()}"


def set_slide_sync_id(md_text, slide_index, sync_id):
    """Set or replace a hidden sync ID in a specific slide section."""
    parts = re.split(r'(^\s*---\s*$)', md_text or "", flags=re.MULTILINE)
    changed = False
    rendered_slide = 0
    result = []

    for part in parts:
        if re.match(r'^\s*---\s*$', part or ""):
            result.append(part)
            continue

        visible = re.sub(
            r'<!--\s*numa-(?:slide|sync)-id:\s*[^>]*-->',
            '',
            part,
        ).strip()
        if rendered_slide == slide_index and visible:
            if SYNC_ID_PATTERN.search(part):
                part = SYNC_ID_PATTERN.sub(f"<!-- numa-sync-id: {sync_id} -->", part, count=1)
            else:
                part = _insert_sync_id(part, sync_id)
            changed = True
        if visible:
            rendered_slide += 1
        result.append(part)

    return "".join(result), changed


def clear_slide_sync_ids(md_text):
    """Remove all invisible NUMA sync markers without changing slide content."""
    text = md_text or ""
    updated = re.sub(r'^\s*<!--\s*numa-sync-id:\s*[^>]+-->\s*\n?', '', text, flags=re.MULTILINE)
    return updated, updated != text


def clear_slide_sync_id(md_text, slide_index, sync_id=None):
    """Remove one slide's sync marker, optionally matching a specific pair ID."""
    parts = re.split(r'(^\s*---\s*$)', md_text or "", flags=re.MULTILINE)
    rendered_slide = 0
    changed = False
    result = []

    for part in parts:
        if re.match(r'^\s*---\s*$', part or ""):
            result.append(part)
            continue

        visible = re.sub(
            r'<!--\s*numa-(?:slide|sync)-id:\s*[^>]*-->',
            '',
            part,
        ).strip()
        if rendered_slide == slide_index and visible:
            def remove_marker(match):
                nonlocal changed
                marker_id = match.group(1).strip()
                if sync_id is None or marker_id == sync_id:
                    changed = True
                    return ""
                return match.group(0)

            part = re.sub(
                r'^\s*<!--\s*numa-sync-id:\s*([^>]+?)\s*-->\s*\n?',
                remove_marker,
                part,
                count=1,
                flags=re.MULTILINE,
            )
        if visible:
            rendered_slide += 1
        result.append(part)

    return "".join(result), changed


def find_broken_slide_id_links(md_text):
    """Return slide-id links that no longer match any slide ID in the document."""
    valid_ids = {slide["id"] for slide in get_slide_metadata(md_text) if slide.get("id")}
    broken = []
    seen = set()
    for match in re.finditer(r'\]\(slide-id:([a-zA-Z0-9_-]+)\)', md_text or ""):
        slide_id = match.group(1)
        if slide_id not in valid_ids and slide_id not in seen:
            seen.add(slide_id)
            broken.append(slide_id)
    return broken


def find_broken_internal_slide_links(md_text):
    """Return internal slide links that no longer resolve to a current slide."""
    metadata = get_slide_metadata(md_text)
    valid_ids = {slide["id"] for slide in metadata if slide.get("id")}
    valid_keys = {slide["key"] for slide in metadata if slide.get("key")}
    broken = []
    seen = set()

    for match in re.finditer(r'\]\((slide-id|slide-key):([a-zA-Z0-9_-]+)\)', md_text or ""):
        scheme = match.group(1)
        target = match.group(2)
        exists = target in valid_ids if scheme == "slide-id" else target in valid_keys
        marker = (scheme, target)
        if not exists and marker not in seen:
            seen.add(marker)
            broken.append({"scheme": scheme, "target": target})
    return broken


def replace_slide_id_link(md_text, old_id, new_id):
    return re.sub(
        rf'(\]\()slide-id:{re.escape(old_id)}(\))',
        rf'\1slide-id:{new_id}\2',
        md_text or ""
    )


def replace_internal_slide_link(md_text, scheme, old_target, new_id):
    return re.sub(
        rf'(\]\(){re.escape(scheme)}:{re.escape(old_target)}(\))',
        rf'\1slide-id:{new_id}\2',
        md_text or ""
    )


def parse_markdown_to_html(md_text, mode="slide", pdf_export=False):
    """
    Parses Markdown text into HTML.
    Supports splitting sections by '---' if mode is 'slide'.
    """
    # Handle None or empty input
    if not md_text or not md_text.strip():
        if mode == "slide":
            return _wrap_slide("Escribe algo aquí para iniciar tu presentación.", 1, 1)
        if mode == "paper":
            return _wrap_paper_pages(["Escribe algo aquí para iniciar tu documento."])
        else:
            return _wrap_continuous("Escribe algo aquí para iniciar tu presentación.")

    source_md_text = md_text
    alignment_match = DOCUMENT_ALIGNMENT_PATTERN.search(md_text)
    document_alignment = alignment_match.group(1).lower() if alignment_match else None
    if document_alignment:
        md_text = DOCUMENT_ALIGNMENT_PATTERN.sub("", md_text)
        source_md_text = DOCUMENT_ALIGNMENT_PATTERN.sub("", source_md_text)
    md_text, math_tokens = _protect_math_expressions(md_text)
    md_text = _normalize_local_image_links(md_text)
    md_text = _normalize_local_file_links(md_text)
    if pdf_export:
        md_text = _prepare_internal_links_for_pdf(md_text)

    # Configure Markdown extensions
    extensions = [
        'markdown.extensions.fenced_code',
        'markdown.extensions.codehilite',
        'markdown.extensions.tables',
        'markdown.extensions.nl2br',
        'markdown.extensions.sane_lists',
        'markdown.extensions.toc',
        'markdown.extensions.smarty',
        'pymdownx.superfences',
        'pymdownx.betterem',
        'pymdownx.tasklist',
    ]

    extension_configs = {
        'markdown.extensions.codehilite': {
            'css_class': 'code-highlight',
            'linenums': False,
        },
    }

    md_parser = markdown.Markdown(
        extensions=extensions,
        extension_configs=extension_configs
    )

    if mode == "slide":
        sections = _split_slide_sections(md_text)
        metadata = get_slide_metadata(source_md_text)

        slides_html = []
        total_slides = len(sections)
        for i, sec in enumerate(sections):
            html_content = _restore_math_expressions(md_parser.convert(sec), math_tokens)
            html_content = _render_reference_blocks_as_text(html_content)
            html_content = _apply_image_display_options(html_content)
            # Reset parser to prevent state carrying over between slides
            md_parser.reset()
            slides_html.append(_wrap_slide(
                html_content,
                i + 1,
                total_slides,
                metadata[i]["key"],
                metadata[i]["id"],
                pdf_export,
                document_alignment,
            ))

        return "\n".join(slides_html)

    if mode == "paper":
        pages = []
        for section in _split_slide_sections(md_text):
            html_content = _restore_math_expressions(md_parser.convert(section), math_tokens)
            html_content = _render_reference_blocks_as_text(html_content)
            html_content = _apply_image_display_options(html_content)
            md_parser.reset()
            pages.append(html_content)
        return _wrap_paper_pages(pages, document_alignment)

    else:
        # Scroll mode - render everything as a single body
        # Split by '---' delimiters, parse each section, then rejoin with <hr>
        sections = _split_slide_sections(md_text)
        metadata = get_slide_metadata(source_md_text) if pdf_export else []

        html_parts = []
        for i, sec in enumerate(sections):
            sec = sec.strip()
            if not sec:
                continue
            html_content = _restore_math_expressions(md_parser.convert(sec), math_tokens)
            html_content = _render_reference_blocks_as_text(html_content)
            html_content = _apply_image_display_options(html_content)
            md_parser.reset()
            if pdf_export:
                slide_id = metadata[i].get("id")
                slide_key = metadata[i].get("key")
                anchors = [f'pdf-slide-{i + 1}']
                if slide_id:
                    anchors.append(f'slide-id-{slide_id}')
                if slide_key:
                    anchors.append(f'slide-key-{slide_key}')
                anchor_html = "".join(f'<span id="{anchor}"></span>' for anchor in anchors)
                html_content = f'<section class="document-section">{anchor_html}{html_content}</section>'
            html_parts.append(html_content)

        separator = '' if pdf_export else '<hr class="slide-divider"/>'
        full_html = separator.join(html_parts)
        return _wrap_continuous(full_html, document_alignment)


def _split_slide_sections(md_text):
    """Split Markdown into non-empty slide sections."""
    sections = SLIDE_DELIMITER_PATTERN.split(md_text or "")
    sections = [s.strip() for s in sections if _has_renderable_markdown(s)]
    return sections or ["Escribe algo aquí para iniciar tu presentación."]


def _has_renderable_markdown(section):
    """Ignore separator-only sections that contain only NUMA's invisible IDs."""
    visible = re.sub(r'<!--\s*numa-(?:slide|sync)-id:\s*[^>]*-->', '', section or '')
    return bool(visible.strip())


def _protect_math_expressions(md_text):
    """Keep valid TeX intact while Markdown parses the surrounding document."""
    tokens = {}
    counter = 0

    def token_for(delimiter, expression):
        nonlocal counter
        token = f"NUMAMATHTOKEN{counter}X"
        counter += 1
        # Accept a Markdown-escaped subscript marker without changing the source.
        tex_expression = re.sub(r"\\_(?=\{)", "_", expression)
        tokens[token] = html.escape(f"{delimiter}{tex_expression}{delimiter}")
        return token

    def replace_block(match):
        return token_for("$$", match.group(1))

    def replace_tex_block(match):
        expression = match.group(1)
        # Some source documents escape square brackets around bibliography
        # references (for example, \[ref: 1; ref: 2\]).  Those brackets are
        # also TeX display delimiters, but a reference must remain text.
        if _is_reference_block(expression):
            return f"[{expression}]"
        return token_for("$$", expression)

    protected = MATH_BLOCK_PATTERN.sub(replace_block, md_text or "")
    # TeX also permits \[ ... \] as a display-math delimiter. Markdown would
    # otherwise consume those escape characters before KaTeX can see them.
    protected = MATH_TEX_BLOCK_PATTERN.sub(replace_tex_block, protected)

    def replace_inline(match):
        expression = match.group(1)
        if not _is_valid_inline_math(expression):
            return match.group(0)
        return token_for("$", expression)

    return MATH_INLINE_PATTERN.sub(replace_inline, protected), tokens


def _is_valid_inline_math(expression):
    """Avoid treating ordinary currency-like dollar text as TeX delimiters."""
    value = (expression or "")
    if not value or value != value.strip():
        return False
    return bool(re.search(
        r"\\[A-Za-z]+|[=_^{}]|\d\s*:\s*\d|[+*/<>≤≥≈]|^[A-Za-zα-ωΑ-Ω]$",
        value,
    ))


def _is_reference_block(expression):
    """Return True for bracketed bibliography references, not TeX formulas."""
    value = (expression or "").strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1].strip()
    return bool(re.fullmatch(
        r"ref(?:erencia)?s?\s*:\s*[^\[\]]+",
        value,
        re.IGNORECASE,
    ))


def _restore_math_expressions(html_text, tokens):
    for token, expression in (tokens or {}).items():
        html_text = html_text.replace(token, expression)
    return html_text


def _render_reference_blocks_as_text(html_text):
    """Prevent bibliography references from reaching KaTeX as display math."""
    def replace_display_math(match):
        expression = html.unescape(match.group(1))
        if not _is_reference_block(expression):
            return match.group(0)
        return f'<span class="numa-reference">[{html.escape(expression.strip())}]</span>'

    html_text = re.sub(
        r"(?<!\\)\$\$(.+?)(?<!\\)\$\$",
        replace_display_math,
        html_text or "",
        flags=re.DOTALL,
    )

    def replace_tex_brackets(match):
        expression = html.unescape(match.group(1))
        if not _is_reference_block(expression):
            return match.group(0)
        return f'<span class="numa-reference">[{html.escape(expression.strip())}]</span>'

    return re.sub(
        r"(?<!\\)\\\[(.+?)(?<!\\)\\\]",
        replace_tex_brackets,
        html_text,
        flags=re.DOTALL,
    )


def _extract_slide_title(section, fallback):
    """Use the first Markdown heading in a slide as its persistent target label."""
    for line in (section or "").splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            title = re.sub(r"[*_`~\[\]()>#]", "", match.group(1)).strip()
            return title or fallback
    return fallback


def _extract_slide_id(section):
    match = SLIDE_ID_PATTERN.search(section or "")
    return match.group(1) if match else None


def _extract_sync_id(section):
    match = SYNC_ID_PATTERN.search(section or "")
    return match.group(1) if match else None


def _new_slide_id():
    return uuid.uuid4().hex[:12]


def _insert_slide_id(section, slide_id):
    leading = re.match(r'^(\s*)', section or "").group(1)
    body = (section or "")[len(leading):]
    separator = "" if body.startswith("\n") else "\n"
    return f"{leading}<!-- numa-slide-id: {slide_id} -->{separator}{body}"


def _insert_sync_id(section, sync_id):
    leading = re.match(r'^(\s*)', section or "").group(1)
    body = (section or "")[len(leading):]
    separator = "" if body.startswith("\n") else "\n"
    return f"{leading}<!-- numa-sync-id: {sync_id} -->{separator}{body}"


def _make_slide_key(title, slide_num, used_keys):
    normalized = unicodedata.normalize("NFKD", title or "")
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")
    base = base or f"slide-{slide_num}"
    count = used_keys.get(base, 0) + 1
    used_keys[base] = count
    return base if count == 1 else f"{base}-{count}"


def _wrap_slide(
    html_content,
    slide_num,
    total,
    slide_key=None,
    slide_id=None,
    pdf_export=False,
    document_alignment=None,
):
    """Wraps a slide's content in the slide container div."""
    slide_index = slide_num - 1
    key_attr = html.escape(slide_key or f"slide-{slide_num}", quote=True)
    id_attr = html.escape(slide_id or "", quote=True)
    pdf_anchor = ""
    if pdf_export:
        pdf_anchor = f'<span id="pdf-slide-{slide_num}" class="pdf-anchor"></span>'
        if slide_id:
            pdf_anchor += f'<span id="slide-id-{id_attr}" class="pdf-anchor"></span>'
        if slide_key:
            pdf_anchor += f'<span id="slide-key-{key_attr}" class="pdf-anchor"></span>'
    return f"""
    <div class="slide" id="slide-{slide_num}" data-slide-index="{slide_index}" data-slide-number="{slide_num}" data-slide-key="{key_attr}" data-slide-id="{id_attr}">
        {pdf_anchor}
        <div class="slide-content{' numa-document-align-' + document_alignment if document_alignment else ''}">
            {html_content}
        </div>
        <div class="slide-footer">{slide_num} / {total}</div>
    </div>
    """


def _wrap_continuous(html_content, document_alignment=None):
    """Wraps content for continuous scroll mode."""
    return f"""
    <div class="continuous-document{' numa-document-align-' + document_alignment if document_alignment else ''}">
        {html_content}
    </div>
    """


def _wrap_paper_pages(pages, document_alignment=None):
    """Wrap each Markdown slide section as one printable preview page."""
    rendered_pages = []
    total = max(1, len(pages))
    for index, page in enumerate(pages):
        rendered_pages.append(
            f'<section class="print-page" data-slide-index="{index}">'
            f'<div class="print-page-content">{page}</div>'
            f'<div class="print-page-number">{index + 1} / {total}</div>'
            '</section>'
        )
    alignment_class = f' numa-document-align-{document_alignment}' if document_alignment else ''
    return f'<div class="print-document{alignment_class}">' + ''.join(rendered_pages) + '</div>'


def _normalize_local_file_links(md_text):
    """Convert absolute Windows paths in Markdown links to file URLs."""
    pattern = re.compile(r'(\[[^\]]+\]\()(?!<)([a-zA-Z]:[\\/][^)]+)(\))')

    def repl(match):
        path = match.group(2).strip()
        file_url = Path(path).as_uri()
        return f"{match.group(1)}<{file_url}>{match.group(3)}"

    return pattern.sub(repl, md_text)


def _iter_markdown_image_links(md_text):
    """Yield Markdown image ranges while allowing parentheses in raw paths."""
    text = md_text or ""
    position = 0
    while True:
        start = text.find("![", position)
        if start < 0:
            return

        alt_end = text.find("](", start + 2)
        if alt_end < 0:
            return

        target_start = alt_end + 2
        if target_start < len(text) and text[target_start] == "<":
            target_end = text.find(">", target_start + 1)
            if target_end < 0 or target_end + 1 >= len(text) or text[target_end + 1] != ")":
                position = target_start
                continue
            end = target_end + 2
            target = text[target_start + 1:target_end].strip()
        else:
            depth = 1
            cursor = target_start
            while cursor < len(text) and depth:
                if text[cursor] == "(":
                    depth += 1
                elif text[cursor] == ")":
                    depth -= 1
                cursor += 1
            if depth:
                position = target_start
                continue
            end = cursor
            target = text[target_start:cursor - 1].strip()

        yield start, end, text[start + 2:alt_end], target
        position = end


def find_markdown_image_at_position(md_text, position):
    """Return the Markdown image containing the cursor or sharing its line."""
    text = md_text or ""
    try:
        position = max(0, min(int(position), len(text)))
    except (TypeError, ValueError):
        position = 0

    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end < 0:
        line_end = len(text)

    for start, end, alt, target in _iter_markdown_image_links(text):
        if start <= position <= end or (line_start <= start and end <= line_end):
            return {
                "start": start,
                "end": end,
                "alt": alt,
                "target": target,
            }
    return None


def get_image_display_options(md_text, image_start):
    """Read a NUMA image directive placed immediately before an image."""
    text = md_text or ""
    prefix = text[:max(0, int(image_start))]
    match = None
    for candidate in IMAGE_DISPLAY_DIRECTIVE_PATTERN.finditer(prefix):
        if not prefix[candidate.end():].strip():
            match = candidate
    if not match:
        return {"width": "auto", "align": "center", "spacing": "normal", "orientation": "0", "color": "color", "frame": "none"}, None
    return {
        "width": match.group(1).lower(),
        "align": match.group(2).lower(),
        "spacing": match.group(3).lower(),
        "orientation": (match.group(4) or "0").lower(),
        "color": (match.group(5) or "color").lower(),
        "frame": (match.group(6) or "none").lower(),
    }, (match.start(), match.end())


def _apply_image_display_options(html_text):
    """Turn a NUMA image directive plus Markdown image into a styled figure."""
    pattern = re.compile(
        r'<!--\s*numa-image:\s*width=(auto|(?:[1-9]\d?|100)%),\s*'
        r'align=(left|center|right),\s*spacing=(compact|normal|wide)'
        r'(?:,\s*orientation=(0|90|180|270))?'
        r'(?:,\s*color=(color|grayscale))?'
        r'(?:,\s*frame=(none|plain|shadow))?\s*-->\s*'
        r'<p>\s*(<img\b[^>]*>)((?:(?!</?p\b).)*)</p>',
        re.IGNORECASE | re.DOTALL,
    )

    def replace(match):
        width, align, spacing, orientation, color, frame, image, trailing = match.groups()
        orientation = orientation or "0"
        color = color or "color"
        frame = frame or "none"
        width_class = "numa-image-width-auto" if width.lower() == "auto" else ""
        style = "" if width_class else f' style="--numa-image-width: {width};"'
        classes = " ".join(
            value for value in (
                "numa-image",
                width_class,
                f"numa-image-align-{align.lower()}",
                f"numa-image-spacing-{spacing.lower()}",
                f"numa-image-orientation-{orientation}",
                f"numa-image-color-{color.lower()}",
                f"numa-image-frame-{frame.lower()}",
            ) if value
        )
        # Keep the caption outside the figure so image-only styles do not affect it.
        trailing = re.sub(r'^\s*(?:<br\s*/?>\s*)+', '', trailing, flags=re.IGNORECASE)
        caption = f'<p>{trailing}</p>' if trailing.strip() else ''
        return f'<figure class="{classes}"{style}>{image}</figure>{caption}'

    return pattern.sub(replace, html_text or "")


def _normalize_local_image_links(md_text):
    """Convert raw absolute Windows image paths to protected file URLs."""
    replacements = []
    for start, end, alt, target in _iter_markdown_image_links(md_text):
        if target.startswith("<") or not re.match(r"^[a-zA-Z]:[\\/]", target):
            continue
        replacements.append((start, end, f"![{alt}](<{Path(target).as_uri()}>)"))

    normalized = md_text or ""
    for start, end, replacement in reversed(replacements):
        normalized = normalized[:start] + replacement + normalized[end:]
    return normalized


def _prepare_internal_links_for_pdf(md_text):
    """Convert interactive slide links into HTML anchors that PDF readers can follow."""
    text = md_text or ""
    text = re.sub(r'\]\(slide-id:([a-zA-Z0-9_-]+)\)', r'](#slide-id-\1)', text)
    text = re.sub(r'\]\(slide-key:([a-zA-Z0-9_-]+)\)', r'](#slide-key-\1)', text)
    text = re.sub(r'\]\(slide:(\d+)\)', r'](#pdf-slide-\1)', text)
    return text
