from fpdf import FPDF, HTMLMixin
import markdown

class MarkdownPDF(FPDF, HTMLMixin):
    def __init__(self,
                 title: str,
                 logo_path: str = 'Logochi.png',
                 brand_rgb: tuple[int,int,int] = (40,70,150),
                 font_dir: str = '.'):
        super().__init__()
        self.set_margins(20, 20, 20)
        self.set_auto_page_break(True, 20)
        self.logo_path = logo_path
        self.brand_rgb = brand_rgb
        self.doc_title = title
        self.add_font('DejaVu', '', f'{font_dir}/DejaVuSans.ttf', uni=True)
        self.add_font('DejaVu', 'B', f'{font_dir}/DejaVuSans-Bold.ttf', uni=True)

    def header(self):
        # Place logo on the right for RTL
        if self.logo_path:
            logo_width = 30
            x_logo = self.w - self.r_margin - logo_width
            self.image(self.logo_path, x=x_logo, y=10, w=logo_width)
        # Center the title, ensuring no overlap with logo
        self.set_font('DejaVu', 'B', 18)
        self.set_text_color(*self.brand_rgb)
        self.set_xy(0, 15)
        self.cell(self.w - (self.r_margin + self.l_margin), 10, self.doc_title, ln=1, align='C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('DejaVu', '', 10)
        self.set_text_color(128)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

    def add_markdown(self, md_text: str):
        html = markdown.markdown(
            md_text,
            extensions=['extra', 'sane_lists', 'smarty']
        )
        self.write_html(html, True, True)


def build_pdf_from_markdown(md_text: str,
                            output_path: str = 'RFP_Evaluation.pdf',
                            title: str = 'Request for Proposal',
                            logo_path: str = 'Logochi.png',
                            brand_rgb: tuple = (40,70,150),
                            font_dir: str = '.'):
    pdf = MarkdownPDF(
        title=title,
        logo_path=logo_path,
        brand_rgb=brand_rgb,
        font_dir=font_dir
    )
    pdf.add_page()
    pdf.set_font('DejaVu', '', 12)
    pdf.add_markdown(md_text)
    pdf.output(output_path)
    return output_path
