from io import BytesIO

import pytest
from docx import Document
from openpyxl import Workbook

from labelspec.documents import infer_document_role, parse_standard_document


def test_text_and_office_documents_are_extracted() -> None:
    markdown = parse_standard_document("rules.md", "text/markdown", "# 标签\n贷款定义".encode())
    assert "贷款定义" in markdown.extracted_text

    document = Document()
    document.add_heading("汽车", level=1)
    document.add_paragraph("购车定义")
    docx = BytesIO()
    document.save(docx)
    parsed_docx = parse_standard_document(
        "rules.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", docx.getvalue()
    )
    assert "购车定义" in parsed_docx.extracted_text

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["一级", "二级", "定义"])
    sheet.append(["金融", "贷款", "借贷相关"])
    xlsx = BytesIO()
    workbook.save(xlsx)
    parsed_xlsx = parse_standard_document(
        "taxonomy.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", xlsx.getvalue()
    )
    assert "金融\t贷款\t借贷相关" in parsed_xlsx.extracted_text


def test_unsupported_document_is_rejected() -> None:
    with pytest.raises(ValueError, match="不支持"):
        parse_standard_document("rules.exe", "application/octet-stream", b"content")


def test_document_role_is_inferred_from_filename() -> None:
    assert infer_document_role("example-confusion-boundary.md") == "boundary"
    assert infer_document_role("priority-rules.md") == "priority"
    assert infer_document_role("分类标准.md") == "definition"
    assert infer_document_role("notes.md") == "auto"
