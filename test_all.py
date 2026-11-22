import os
import sys
import tempfile
sys.path.insert(0, '.')

from styles import get_app_stylesheet, get_html_template, LIGHT_THEME, DARK_THEME
from parser import (
    filter_slides_with_file_links,
    find_broken_local_image_links,
    parse_markdown_to_html,
    repair_broken_local_image_links,
    slide_has_file_link,
)
from editor import MarkdownEditor, MarkdownHighlighter, ImageDropDialog, LineNumberArea
from preview import PresentationView

# Test stylesheet generation
qss_light = get_app_stylesheet(is_dark=False)
qss_dark = get_app_stylesheet(is_dark=True)
print(f"Light QSS: {len(qss_light)} chars")
print(f"Dark QSS: {len(qss_dark)} chars")
assert len(qss_light) > 100
assert len(qss_dark) > 100

# Test parser - slide mode
slide_md = "# Slide 1\n\nContent here\n\n---\n\n# Slide 2\n\nMore content"
slide_html = parse_markdown_to_html(slide_md, mode="slide")
print(f"Slide HTML: {len(slide_html)} chars")
assert "slide" in slide_html
assert "Slide 1" in slide_html
assert "Slide 2" in slide_html

# Test parser - scroll mode
scroll_html = parse_markdown_to_html("# Title\n\nContent", mode="scroll")
print(f"Scroll HTML: {len(scroll_html)} chars")
assert "continuous-document" in scroll_html

# Paper mode turns each slide-delimited section into a distinct preview page.
paper_html = parse_markdown_to_html("# Pagina 1\n\n---\n\n# Pagina 2", mode="paper")
assert paper_html.count('class="print-page"') == 2
assert 'data-slide-index="0"' in paper_html
assert 'data-slide-index="1"' in paper_html

# Invisible NUMA identifiers between adjacent separators must not become blank pages.
paper_without_blank = parse_markdown_to_html(
    "# Pagina 1\n\n---\n<!-- numa-slide-id: abc123 -->\n---\n\n# Pagina 2",
    mode="paper",
)
assert paper_without_blank.count('class="print-page"') == 2

# Test letter-document PDF rendering ignores slide boundaries for pagination.
document_md = "# Section 1\n\nText\n\n---\n\n# Section 2\n\nMore text"
document_content = parse_markdown_to_html(document_md, mode="scroll", pdf_export=True)
assert "document-section" in document_content
assert "slide-divider" not in document_content
document_html = get_html_template(
    document_content,
    style_mode="scroll",
    font_size=18,
    is_dark=True,
    pdf_export=True,
    pdf_document=True,
)
assert "size: Letter portrait" in document_html
assert "background: #FFFFFF" in document_html

# JavaScript needs two literal backslashes so KaTeX treats only \\[ and \\]
# as display-math delimiters. Plain [ref: 1] remains ordinary text.
assert "{left: '\\\\[', right: '\\\\]', display: true}" in document_html

# Test parser - empty input
empty = parse_markdown_to_html("", mode="slide")
assert "iniciar" in empty.lower()

# TeX block delimiters survive Markdown and arrive at KaTeX as display math.
tex_bracket_math = parse_markdown_to_html(
    "Una formula:\n\n\\[\nE = \\frac{D_p}{D_t}\n\\]",
    mode="scroll",
)
assert "$$" in tex_bracket_math
assert "frac{D_p}{D_t}" in tex_bracket_math

# Escaped square-bracket bibliography references are text, not display math.
reference_html = parse_markdown_to_html(r"Texto \[ref: 1; ref: 2\].", mode="scroll")
assert "[ref: 1; ref: 2]" in reference_html
assert "$$ref: 1; ref: 2$$" not in reference_html
reference_html_with_inner_brackets = parse_markdown_to_html(
    r"Texto \[[ref: 1; ref: 2]\].", mode="scroll"
)
assert "[ref: 1; ref: 2]" in reference_html_with_inner_brackets
assert "$$ref: 1; ref: 2$$" not in reference_html_with_inner_brackets
reference_as_display_math = parse_markdown_to_html("$$ref: 1; ref: 2$$", mode="scroll")
assert '<span class="numa-reference">[ref: 1; ref: 2]</span>' in reference_as_display_math

# Test PDF filtering for slides with clickable local-file links.
file_link_md = """# Keep image
![Plano](assets/plano.png)

---

# Skip local file
[Abrir PDF](<file:///C:/docs/plano.pdf>)

---

# Keep web and internal links
[Sitio](https://example.com) [Siguiente](slide:1)
"""
filtered_md, removed_count, kept_count = filter_slides_with_file_links(file_link_md)
assert removed_count == 1
assert kept_count == 2
assert "Skip local file" not in filtered_md
assert "Keep image" in filtered_md
assert "Keep web and internal links" in filtered_md
assert slide_has_file_link("[Archivo relativo](documentos/anexo.docx)")
assert not slide_has_file_link("![Imagen](documentos/foto.jpg)")

# TeX stays untouched through Markdown parsing and is rendered later by KaTeX.
math_md = r"""La escala es $1:500$.

$$
D\_{terreno} = \frac{D_{plano}}{N} \times \sqrt{25}\text{ m}^2
$$

```markdown
$$
D = \frac{A}{B}
$$
```

Costo normal: $100 y $200.
"""
math_html = parse_markdown_to_html(math_md, mode="slide")
assert "$1:500$" in math_html
assert "\\frac{D_{plano}}{N}" in math_html
assert "D_{terreno}" in math_html
assert "<code>$$" in math_html
assert "$100 y $200" in math_html

# Raw Windows image paths may contain spaces and parentheses in the filename.
image_with_parentheses = (
    "![Figura](L:/Material de clase/recursos/ChatGPT Image (1).png)"
)
image_html = parse_markdown_to_html(image_with_parentheses, mode="slide")
assert 'src="file:///L:/Material%20de%20clase/recursos/ChatGPT%20Image%20%281%29.png"' in image_html
assert ".png)</p>" not in image_html

# Test broken local image detection and recursive relinking.
with tempfile.TemporaryDirectory() as temp_root:
    document_dir = os.path.join(temp_root, "documentos")
    replacement_dir = os.path.join(temp_root, "recursos", "mapas")
    os.makedirs(document_dir)
    os.makedirs(replacement_dir)
    replacement_image = os.path.join(replacement_dir, "curvas.jpg")
    with open(replacement_image, "wb") as image_file:
        image_file.write(b"test-image")

    broken_md = "![Curvas](CLASE-2/recursos/curvas.jpg)\n![Web](https://example.com/mapa.jpg)"
    broken_images = find_broken_local_image_links(broken_md, document_dir)
    assert len(broken_images) == 1
    assert broken_images[0]["name"] == "curvas.jpg"

    repaired_md, repaired_count, unresolved = repair_broken_local_image_links(
        broken_md,
        broken_images,
        os.path.join(temp_root, "recursos"),
    )
    assert repaired_count == 1
    assert not unresolved
    assert replacement_image.replace("\\", "/") in repaired_md
    assert "https://example.com/mapa.jpg" in repaired_md

# Test HTML template
html = get_html_template(slide_html, style_mode="slide", font_size=24, is_dark=False)
print(f"Full HTML: {len(html)} chars")
assert "<!DOCTYPE html>" in html
assert "Cabinet Grotesk" in html
assert "Inter" in html

paper_document_html = get_html_template(
    paper_html,
    style_mode="paper",
    font_size=24,
    paper_size="a4",
    paper_orientation="landscape",
)
assert ".print-page" in paper_document_html
assert "width: 297mm" in paper_document_html
assert "height: 210mm" in paper_document_html

# Test HTML template - dark mode
html_dark = get_html_template(scroll_html, style_mode="scroll", font_size=20, is_dark=True)
assert "#0E1324" in html_dark or "0E1324" in html_dark

print()
print("ALL TESTS PASSED")
