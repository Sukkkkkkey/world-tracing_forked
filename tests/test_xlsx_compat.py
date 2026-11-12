from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment

from evaluation.xlsx_compat import normalize_comment_parts


def test_comments_preserved_with_exceljs_part_names(tmp_path):
    path = tmp_path / 'ledger.xlsx'
    book = Workbook()
    sheet = book.active
    sheet.title = '实验总览'
    sheet['A1'] = '人工结论'
    sheet['A1'].comment = Comment('记录键：["实验", "样本"]\n保留备注', '研究者')
    sheet['B2'] = 0.012345678901234
    sheet['B2'].number_format = '0.0000'
    sheet['C2'] = '证据'
    sheet['C2'].hyperlink = '/data1/results/config.json'
    sheet.merge_cells('A1:C1')
    sheet.freeze_panes = 'B3'
    book.save(path)
    with ZipFile(path) as archive:
        before = {name: archive.read(name) for name in archive.namelist()}

    normalize_comment_parts(path)

    with ZipFile(path) as archive:
        assert archive.testzip() is None
        assert archive.read('xl/comments1.xml') == before['xl/comments/comment1.xml']
        assert archive.read('xl/drawings/vmlDrawing1.vml') == before['xl/drawings/commentsDrawing1.vml']
        for name, data in before.items():
            if name == '[Content_Types].xml' or name.endswith('.rels') or name in {
                'xl/comments/comment1.xml', 'xl/drawings/commentsDrawing1.vml'
            }:
                continue
            assert archive.read(name) == data
        rels = archive.read('xl/worksheets/_rels/sheet1.xml.rels')
        assert b'Target="../comments1.xml"' in rels
        assert b'Target="../drawings/vmlDrawing1.vml"' in rels
        assert b'Target="/data1/results/config.json"' in rels
    loaded = load_workbook(path)
    assert loaded.active['A1'].comment == sheet['A1'].comment
    assert loaded.active['B2'].value == sheet['B2'].value
    assert loaded.active.freeze_panes == 'B3'
    assert str(loaded.active.merged_cells) == 'A1:C1'
    loaded.close()
    before_second_pass = path.read_bytes()
    normalize_comment_parts(path)
    assert path.read_bytes() == before_second_pass


def test_export_applies_compatibility(tmp_path, monkeypatch):
    from evaluation import research_workbook

    book = Workbook()
    book.active['A1'] = '结论'
    book.active['A1'].comment = Comment('备注', '作者')
    monkeypatch.setattr(research_workbook, 'collect_experiments', lambda _: ([], {}))
    monkeypatch.setattr(
        research_workbook, 'build_workbook',
        lambda *args: (book, {'cells': [], 'experiments': []})
    )
    output = tmp_path / 'export.xlsx'
    research_workbook.export(tmp_path, output)
    with ZipFile(output) as archive:
        assert 'xl/comments1.xml' in archive.namelist()
    loaded = load_workbook(output)
    assert loaded.active['A1'].comment.text == '备注'
    loaded.close()
