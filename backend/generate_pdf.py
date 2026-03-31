from fpdf import FPDF
import os
from markdown_it import MarkdownIt

class StyledPDF(FPDF):
    def __init__(self, title, logo_path=None, brand_rgb=(40, 70, 150), font_dir='.'):
        super().__init__()
        self.set_margins(20, 20, 20)
        self.set_auto_page_break(True, 20)
        self.logo_path = logo_path
        self.brand_rgb = brand_rgb
        self.doc_title = title
        # Font loading with error handling
        try:
            self.add_font('DejaVu', '', os.path.join(font_dir, 'DejaVuSans.ttf'), uni=True)
            self.add_font('DejaVu', 'B', os.path.join(font_dir, 'DejaVuSans-Bold.ttf'), uni=True)
        except Exception as e:
            raise RuntimeError("DejaVuSans.ttf and DejaVuSans-Bold.ttf must be in the backend directory. Error: " + str(e))

    def header(self):
        if self.logo_path and os.path.exists(self.logo_path):
            self.image(self.logo_path, x=self.l_margin, y=10, w=30)
        self.set_font('DejaVu', 'B', 18)
        self.set_text_color(*self.brand_rgb)
        self.cell(0, 10, self.doc_title, ln=1, align='C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('DejaVu', '', 10)
        self.set_text_color(128)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

    def section_header(self, txt):
        self.set_font('DejaVu', 'B', 14)
        self.set_text_color(*self.brand_rgb)
        self.cell(0, 8, txt, ln=1)
        self.set_draw_color(*self.brand_rgb)
        self.set_line_width(0.6)
        y = self.get_y()
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(4)
        self.set_font('DejaVu', '', 12)
        self.set_text_color(0)

    def bullet_list(self, items):
        self.set_font('DejaVu', '', 12)
        for item in items:
            self.cell(8)
            self.multi_cell(0, 6, f'• {item}')
        self.ln(4)

    def rubric_table(self, rows):
        col_w = (self.w - self.l_margin - self.r_margin) / 2
        self.set_font('DejaVu', 'B', 12)
        self.set_fill_color(*[min(255, c+50) for c in self.brand_rgb])
        self.cell(col_w, 8, 'Criteria', border=1, fill=True)
        self.cell(col_w, 8, 'Weight', border=1, ln=1, fill=True)
        self.set_font('DejaVu', '', 12)
        for crit, wt in rows:
            self.cell(col_w, 8, crit, border=1)
            self.cell(col_w, 8, wt, border=1, ln=1)
        self.ln(6)

from fpdf.errors import FPDFException

def safe_multicell(pdf, text):
    if not text.strip():
        return
    max_word_length = 100
    words = []
    for word in text.split():
        if len(word) > max_word_length:
            word = '[content too long]'
        words.append(word)
    safe_text = ' '.join(words)
    try:
        pdf.multi_cell(0, 7, safe_text)
    except FPDFException:
        pdf.multi_cell(0, 7, '[unrenderable content]')

def render_markdown_to_pdf(pdf, markdown_text):
    md = MarkdownIt()
    tokens = md.parse(markdown_text)
    pdf.set_font('DejaVu', '', 12)
    pdf.set_text_color(0)
    bullet_indent = 8
    for token in tokens:
        if token.type == 'heading_open':
            level = int(token.tag[1])
            size = 18 if level == 1 else 16 if level == 2 else 14
            pdf.set_font('DejaVu', 'B', size)
            pdf.set_text_color(*pdf.brand_rgb)
        elif token.type == 'heading_close':
            pdf.ln(4)
            pdf.set_font('DejaVu', '', 12)
            pdf.set_text_color(0)
        elif token.type == 'paragraph_open':
            pdf.set_font('DejaVu', '', 12)
            pdf.set_text_color(0)
        elif token.type == 'inline':
            text = ''
            bold = False
            for child in token.children:
                if child.type == 'text':
                    text += child.content
                elif child.type == 'strong_open':
                    bold = True
                elif child.type == 'strong_close':
                    bold = False
                elif child.type == 'softbreak':
                    text += '\n'
                # Add more inline types as needed
            if bold:
                pdf.set_font('DejaVu', 'B', 12)
            safe_multicell(pdf, text)
            if bold:
                pdf.set_font('DejaVu', '', 12)
        elif token.type == 'bullet_list_open':
            pdf.ln(2)
        elif token.type == 'list_item_open':
            pdf.cell(bullet_indent)
            pdf.cell(0, 7, u'• ', ln=0)
        elif token.type == 'list_item_close':
            pdf.ln(7)
        # Add more cases as needed
    pdf.ln(4)

def build_pdf(sections, output_path='RFP_Evaluation.pdf', title='RFP Evaluation', logo_path=None, brand_rgb=(40,70,150), font_dir='.'): 
    # Use labiba_logo.png as the default logo if not provided
    if logo_path is None:
        logo_path = 'labiba_logo.png'
    pdf = StyledPDF(title=title, logo_path=logo_path, brand_rgb=brand_rgb, font_dir=font_dir)
    pdf.add_page()
    for section in sections:
        pdf.section_header(section['title'])
        # Always render markdown if present, but also render plain body text if available
        if 'markdown' in section:
            render_markdown_to_pdf(pdf, section['markdown'])
            if 'body' in section and section['body'].strip():
                pdf.set_font('DejaVu', '', 12)
                pdf.multi_cell(0, 7, section['body'])
                pdf.ln(2)
        else:
            if 'body' in section:
                pdf.set_font('DejaVu', '', 12)
                pdf.multi_cell(0, 7, section['body'])
                pdf.ln(2)
        if 'bullets' in section and section['bullets']:
            pdf.bullet_list(section['bullets'])
        if 'table' in section and section['table']:
            pdf.rubric_table(section['table'])
    pdf.output(output_path)
    return output_path
