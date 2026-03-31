import os
import re
from html import escape


def _has_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _shape_arabic_for_pdf(text: str) -> str:
    # Keep direct Unicode text for maximum compatibility with fpdf2 runtime.
    # Advanced shaping can fail on some environments and crash PDF generation.
    return text


def _markdown_to_html(md_text: str) -> str:
    try:
        import markdown

        return markdown.markdown(md_text, extensions=["extra", "smarty", "sane_lists"])
    except Exception:
        return "<p>" + escape(md_text).replace("\n", "<br/>") + "</p>"


def _generate_pdf_with_weasy(html_out: str, template_path: str, output_path: str) -> bool:
    try:
        from weasyprint import HTML

        HTML(string=html_out, base_url=os.path.dirname(template_path)).write_pdf(output_path)
        print(f"PDF generated with WeasyPrint: {output_path}")
        return True
    except Exception:
        return False


def _strip_markdown_tokens(line: str) -> str:
    line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
    line = re.sub(r"^\s*[-*+]\s+", "", line)
    line = re.sub(r"^\s*\d+[\.)]\s+", "", line)
    line = line.replace("**", "").replace("__", "").replace("`", "")
    return line.strip()


def _sanitize_pdf_text(line: str) -> str:
    # Remove invisible/control chars that can break fpdf line wrapping.
    return "".join(ch for ch in line if ch >= " " and ch not in {"\u200e", "\u200f", "\u202a", "\u202b", "\u202c"})


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _generate_minimal_pdf(text: str, output_path: str):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        lines = ["RFP Document"]

    content_lines = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"]
    for line in lines[:120]:
        safe = _pdf_escape(line.encode("latin-1", "replace").decode("latin-1"))
        content_lines.append(f"({safe}) Tj")
        content_lines.append("T*")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", "replace")

    objects = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    objects.append(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n"
    )
    objects.append(
        f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    header = b"%PDF-1.4\n"
    offsets = []
    body = b""
    cur = len(header)
    for obj in objects:
        offsets.append(cur)
        body += obj
        cur += len(obj)

    xref_pos = len(header) + len(body)
    xref = [b"xref\n", f"0 {len(objects) + 1}\n".encode("latin-1"), b"0000000000 65535 f \n"]
    for off in offsets:
        xref.append(f"{off:010d} 00000 n \n".encode("latin-1"))
    trailer = (
        b"trailer\n"
        + f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("latin-1")
        + b"startxref\n"
        + f"{xref_pos}\n".encode("latin-1")
        + b"%%EOF\n"
    )

    with open(output_path, "wb") as f:
        f.write(header)
        f.write(body)
        f.writelines(xref)
        f.write(trailer)
    print(f"PDF generated with minimal engine: {output_path}")


def _generate_pdf_with_fpdf(md_text: str, template_path: str, output_path: str):
    try:
        from fpdf import FPDF
    except Exception:
        _generate_minimal_pdf(md_text, output_path)
        return

    base_dir = os.path.dirname(template_path) or "."
    gig_logo = os.path.join(base_dir, "gig_logo.png")
    if not os.path.exists(gig_logo):
        gig_logo = os.path.join(base_dir, "Logochi.png")

    pdf = FPDF()
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(True, 18)
    pdf.add_page()

    font_ready = False
    try:
        pdf.add_font("DejaVu", "", os.path.join(base_dir, "DejaVuSans.ttf"))
        pdf.add_font("DejaVu", "B", os.path.join(base_dir, "DejaVuSans-Bold.ttf"))
        pdf.set_font("DejaVu", "B", 16)
        font_ready = True
    except Exception:
        pdf.set_font("Helvetica", "B", 16)

    if os.path.exists(gig_logo):
        try:
            logo_w = 34
            x_logo = pdf.w - pdf.r_margin - logo_w
            pdf.image(gig_logo, x=x_logo, y=10, w=logo_w)
        except Exception:
            pass

    title = "طلب عروض - GIG الأردن"
    pdf.set_text_color(0, 102, 179)
    pdf.cell(0, 10, _shape_arabic_for_pdf(title), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    if font_ready:
        pdf.set_font("DejaVu", "", 12)
    else:
        pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(20, 20, 20)

    for raw_line in md_text.splitlines() or [md_text]:
        clean = _strip_markdown_tokens(raw_line)
        line = _sanitize_pdf_text(_shape_arabic_for_pdf(clean if clean else " "))
        align = "R" if _has_arabic(clean) else "L"
        pdf.multi_cell(0, 8, line, align=align, wrapmode="CHAR")

    pdf.output(output_path)
    print(f"PDF generated with fallback engine: {output_path}")


def generate_pdf(md_text: str, template_path: str, output_path: str):
    html_body = _markdown_to_html(md_text)

    html_out = None
    try:
        from jinja2 import Template

        with open(template_path, "r", encoding="utf-8") as f:
            tpl = Template(f.read())
        html_out = tpl.render(content=html_body)
    except Exception:
        html_out = None

    if html_out and _generate_pdf_with_weasy(html_out, template_path, output_path):
        return

    # Last-resort fallback to avoid HTTP 500 if WeasyPrint fails at runtime.
    _generate_minimal_pdf(md_text, output_path)
