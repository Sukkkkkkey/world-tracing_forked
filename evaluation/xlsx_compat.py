"""Keep openpyxl comments readable by Office Viewer 4.2.2 / ExcelJS.

ExcelJS recognizes xl/commentsN.xml and xl/drawings/vmlDrawingN.vml,
but not openpyxl's comments/commentN.xml and commentsDrawingN.vml.
Only package names and their internal references change; cell and comment
XML, styles, external links and other workbook parts remain byte-identical.
"""
from copy import copy
import os
from pathlib import Path
import posixpath
import re
import tempfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZipFile


def normalize_comment_parts(path):
    """Atomically normalize comment parts in an openpyxl-produced XLSX."""
    path = Path(path)
    temporary = None
    try:
        with ZipFile(path) as source:
            renames = {}
            for name in source.namelist():
                match = re.fullmatch(r'xl/comments/comment(\d+)\.xml', name)
                if match:
                    renames[name] = f'xl/comments{match[1]}.xml'
                match = re.fullmatch(r'xl/drawings/commentsDrawing(\d+)\.vml', name)
                if match:
                    renames[name] = f'xl/drawings/vmlDrawing{match[1]}.vml'
            if not renames:
                return
            if set(renames.values()) & set(source.namelist()):
                raise ValueError('Conflicting XLSX comment part names')
            with tempfile.NamedTemporaryFile(
                prefix='.xlsx-comments-', suffix='.xlsx', dir=path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
            with ZipFile(temporary, 'w') as target:
                target.comment = source.comment
                for original in source.infolist():
                    data = source.read(original)
                    if original.filename == '[Content_Types].xml':
                        for old, new in renames.items():
                            data = data.replace(
                                f'PartName="/{old}"'.encode(), f'PartName="/{new}"'.encode()
                            )
                    elif original.filename.endswith('.rels'):
                        base = posixpath.dirname(posixpath.dirname(original.filename))
                        for rel in ET.fromstring(data):
                            old = rel.get('Target', '')
                            if rel.get('TargetMode') == 'External':
                                continue
                            resolved = posixpath.normpath(
                                old.lstrip('/') if old.startswith('/') else posixpath.join(base, old)
                            )
                            if resolved in renames:
                                new = posixpath.relpath(renames[resolved], base or '.')
                                old = escape(old, {'"': '&quot;'})
                                data = data.replace(
                                    f'Target="{old}"'.encode(), f'Target="{new}"'.encode()
                                )
                    item = copy(original)
                    item.filename = renames.get(original.filename, original.filename)
                    target.writestr(item, data)
        os.chmod(temporary, path.stat().st_mode & 0o777)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
