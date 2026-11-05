import io


def office_bytes(kind: str) -> bytes:
    buffer = io.BytesIO()
    if kind == "docx":
        from docx import Document

        doc = Document()
        doc.add_heading("项目研究", level=1)
        doc.add_paragraph("企业盈利能力与客户验证仍需核实。")
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "收入（待核验）"
        table.cell(0, 1).text = "123"
        doc.save(buffer)
    elif kind == "xlsx":
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = "财务草稿"
        sheet.append(["收入（未核验）", 123])
        sheet.append(["公式", "=SUM(B1:B1)"])
        book.save(buffer)
    elif kind == "pptx":
        from pptx import Presentation
        from pptx.util import Inches

        slides = Presentation()
        slide = slides.slides.add_slide(slides.slide_layouts[6])
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(3))
        box.text = "企业技术成熟度和客户验证"
        slides.save(buffer)
    elif kind == "pdf":
        from reportlab.pdfgen import canvas

        page = canvas.Canvas(buffer)
        page.drawString(50, 750, "Private investment evidence. Revenue remains unverified.")
        page.showPage()
        page.save()
    else:
        raise ValueError(kind)
    return buffer.getvalue()
