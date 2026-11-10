# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Spreadsheets as grids of text, with their number formats applied."""

from .base import (
    _rewound,
)
from .office import (
    _member_xml,
    ODF_TEXT,
    SS,
)
from .suite import (
    office_suite,
    _office_suite_kind,
    _suite_convert,
)


# ------------------------------------------------------------- spreadsheets
# A workbook is a grid, not a page, so it gets a grid: the cells come back as
# text and the daemon puts them in a table with one tab per sheet. The XML
# containers (xlsx/ods) are read here with the standard library alone; a
# legacy .xls is first converted to xlsx by LibreOffice, when there is one.
SHEET_MAX_SHEETS = 24


SHEET_MAX_ROWS = 2000


SHEET_MAX_COLS = 64


SHEET_MAX_CELL_CHARS = 512


# Excel's epoch is 1899-12-30: 1900 is treated as a leap year by the format,
# so counting from the 30th makes the off-by-one come out right for every
# date a preview will ever show.
_EXCEL_EPOCH_ORDINAL = 693594  # date(1899, 12, 30).toordinal()


ODF_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"


ODF_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"


REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


DOC_REL = (
    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
)


def read_workbook(fd: int, name: str = "", engine: str = "libreoffice") -> dict:
    """Read a spreadsheet's cells as text, sheet by sheet.

    Returns {"sheets": [{"name", "rows", "cols", "align", "clipped"}, ...],
    "clipped": bool}. Every sheet is bounded (rows, columns and the length of
    one cell), so a workbook with a million-row sheet costs the same as a
    small one: the daemon is showing a preview, not opening the file.

    A legacy binary .xls has no reader here. When LibreOffice is there and
    engine allows it, it converts the workbook to xlsx in the jail, and the
    xlsx reader below reads that — so an old workbook gets the same grid
    and tabs as a new one, number formats included.
    """
    import tempfile
    import zipfile

    with _rewound(fd) as fh:
        if zipfile.is_zipfile(fh):
            sheets = _workbook_sheets(fh)
        elif (engine != "builtin" and office_suite()
                and _office_suite_kind(fh) == ".xls"):
            with tempfile.TemporaryDirectory(prefix="qv-office-") as tmp:
                with open(_suite_convert(fh, ".xls", "xlsx", tmp), "rb") as xlsx:
                    sheets = _workbook_sheets(xlsx)
        else:
            raise RuntimeError("not a spreadsheet")

    clipped = len(sheets) > SHEET_MAX_SHEETS
    sheets = sheets[:SHEET_MAX_SHEETS]
    if not any(sheet["rows"] for sheet in sheets):
        raise RuntimeError("no cells to show")
    return {"sheets": sheets, "clipped": clipped}


def _workbook_sheets(fh) -> list:
    """The sheets of an xlsx or ods container."""
    import zipfile

    fh.seek(0)
    with zipfile.ZipFile(fh) as zf:
        names = set(zf.namelist())
        if "xl/workbook.xml" in names:
            return _xlsx_sheets(zf, names)
        if "content.xml" in names:
            return _ods_sheets(zf)
    raise RuntimeError("no spreadsheet part in this container")


def _column_alignment(rows: list, cols: int) -> list:
    """Per column: "r" when its body reads as numbers, "l" otherwise.

    Alignment is decided by column rather than by cell because that is what
    a spreadsheet looks like — one stray text cell in a column of figures
    should not knock a single number out of line. The first row is skipped:
    it is usually a header, and a header is not evidence about the data.
    """
    align = []
    for col in range(cols):
        numbers = other = 0
        for row in rows[1:]:
            text = row[col] if col < len(row) else ""
            if not text:
                continue
            if _looks_numeric(text):
                numbers += 1
            else:
                other += 1
        align.append("r" if numbers > other else "l")
    return align


def _looks_numeric(text: str) -> bool:
    stripped = text.strip().lstrip("+-").replace(",", "")
    for suffix in ("%", "€", "$", "£"):
        stripped = stripped.rstrip(suffix)
    if not stripped:
        return False
    try:
        float(stripped)
    except ValueError:
        return False
    return True


def _sheet_payload(sheet_name: str, grid: dict, clipped: bool) -> dict:
    """Turn {(row, col): text} into a rectangle of rows, trimmed of the
    empty edges a spreadsheet almost always carries around its data."""
    if not grid:
        return {"name": sheet_name, "rows": [], "cols": 0, "align": [],
                "clipped": clipped}
    top = min(r for r, _c in grid)
    bottom = max(r for r, _c in grid)
    left = min(c for _r, c in grid)
    right = max(c for _r, c in grid)
    cols = min(right - left + 1, SHEET_MAX_COLS)
    clipped = clipped or right - left + 1 > cols
    rows = []
    for r in range(top, min(bottom, top + SHEET_MAX_ROWS - 1) + 1):
        rows.append([grid.get((r, left + c), "") for c in range(cols)])
    clipped = clipped or bottom - top + 1 > len(rows)
    return {
        "name": sheet_name,
        "rows": rows,
        "cols": cols,
        "align": _column_alignment(rows, cols),
        "clipped": clipped,
        "first_col": left,   # so the daemon can letter the columns truthfully
        "first_row": top,
    }


def _col_index(ref: str) -> int:
    """"BC12" -> 54. The letters are base-26 with no zero digit."""
    index = 0
    for ch in ref:
        if not ch.isalpha():
            break
        index = index * 26 + (ord(ch.upper()) - 64)
    return index - 1


def _xlsx_sheets(zf, names) -> list:
    """Sheet name and grid per visible worksheet, in workbook order."""
    shared = []
    if "xl/sharedStrings.xml" in names:
        root = _member_xml(zf, "xl/sharedStrings.xml")
        shared = [
            "".join(node.text or "" for node in item.iter(SS + "t"))
            for item in root.iter(SS + "si")
        ]
    formats = _xlsx_formats(zf, names)

    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        root = _member_xml(zf, "xl/_rels/workbook.xml.rels")
        for rel in root.iter(REL + "Relationship"):
            target = rel.get("Target", "").lstrip("./")
            member = target if target.startswith("xl/") else "xl/" + target
            rels[rel.get("Id")] = member

    entries = []
    book = _member_xml(zf, "xl/workbook.xml")
    for node in book.iter(SS + "sheet"):
        if node.get("state") in ("hidden", "veryHidden"):
            continue  # hidden in Excel, hidden here
        member = rels.get(node.get(DOC_REL + "id"))
        if member in names:
            entries.append((node.get("name") or "Sheet", member))
    if not entries:  # no rels, or a workbook part that lied about them
        entries = [
            (n.rsplit("/", 1)[-1][:-4], n) for n in sorted(
                n for n in names
                if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
            )
        ]

    sheets = []
    for sheet_name, member in entries[:SHEET_MAX_SHEETS]:
        grid, clipped = _xlsx_grid(zf, member, shared, formats)
        sheets.append(_sheet_payload(sheet_name, grid, clipped))
    return sheets


def _xlsx_grid(zf, member: str, shared: list, formats: dict) -> tuple:
    """{(row, col): text} for one worksheet, plus whether it was cut short.

    Cells are placed by their own reference rather than by the order they
    appear in: a sparse row omits the empty cells entirely, so counting them
    off would slide every value left of where it belongs.
    """
    root = _member_xml(zf, member)
    grid, clipped = {}, False
    for index, row in enumerate(root.iter(SS + "row")):
        try:
            number = int(row.get("r") or index + 1)
        except ValueError:
            number = index + 1
        for position, cell in enumerate(row.iter(SS + "c")):
            ref = cell.get("r") or ""
            col = _col_index(ref) if ref else position
            if col < 0:
                continue
            text = _xlsx_cell_text(cell, shared, formats)
            if text:
                grid[(number, col)] = text[:SHEET_MAX_CELL_CHARS]
        if len(grid) > SHEET_MAX_ROWS * SHEET_MAX_COLS:
            clipped = True
            break
    return grid, clipped


def _xlsx_cell_text(cell, shared: list, formats: dict) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        node = cell.find(SS + "is")
        return "".join(t.text or "" for t in node.iter(SS + "t")) if (
            node is not None
        ) else ""
    value = cell.find(SS + "v")
    if value is None or value.text is None:
        return ""
    raw = value.text
    if kind == "s":
        try:  # see _office_text: one bad cell, not one bad file
            index = int(raw)
        except ValueError:
            return ""
        return shared[index] if 0 <= index < len(shared) else ""
    if kind == "b":
        return "TRUE" if raw.strip() not in ("0", "") else "FALSE"
    if kind in ("str", "e"):
        return raw
    kind, code = formats.get(cell.get("s") or "0", ("", ""))
    if kind == "number":
        formatted = _format_number(raw, code)
        if formatted is not None:
            return formatted
    elif kind:
        formatted = _serial_to_date(raw, kind)
        if formatted:
            return formatted
    return _trim_number(raw)


def _trim_number(raw: str) -> str:
    """15.700000000000001 -> "15.7". Spreadsheets store binary floats and
    print them rounded; showing the stored digits reads as a bug."""
    try:
        number = float(raw)
    except ValueError:
        return raw
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return ("%.10g" % number)


def _format_number(raw: str, code: str):
    """A number as its Excel format code prints it, or None to fall back.

    Covers what workbooks actually use for figures: decimals ("0.00"),
    thousands separators ("#,##0"), percentages ("0.0%"), currency written
    as a literal ("$", "\\ €") or a locale tag ("[$€-408]"), scientific
    notation, and the positive;negative;zero sections that put negatives in
    brackets or a zero as a dash. Conditional sections ("[>100]"),
    fractions and digit layouts such as phone numbers are rarer, and get
    the plain number rather than a guess.
    """
    import re

    try:
        value = float(raw)
    except ValueError:
        return None
    sections = _format_sections(code)
    if not sections or len(sections) > 4:
        return None
    if any(re.search(r"\[[<>=]", sec) for sec in sections):
        return None
    if value < 0 and len(sections) > 1:
        section, value, sign = sections[1], -value, ""
    elif value == 0 and len(sections) > 2:
        section, sign = sections[2], ""
    else:
        section = sections[0]
        sign = "-" if value < 0 else ""
        value = abs(value)
    tokens = _format_tokens(section)
    if tokens is None:
        return None
    # The pattern: one unbroken run of digit placeholders, with literals on
    # either side. Two runs ("000-0000", "# ?/?") is a layout, not a number.
    runs = [i for i, (kind, _t) in enumerate(tokens) if kind == "digits"]
    if not runs:
        if any(kind == "general" for kind, _t in tokens):
            body = _trim_number(repr(value))
        elif any(kind == "text" for kind, _t in tokens):
            return None
        else:
            body = ""  # a section of pure literal, such as a zero as "-"
        runs = None
    elif len(runs) > 1:
        return None
    else:
        pattern = tokens[runs[0]][1]
        percent = sum(t.count("%") for kind, t in tokens if kind == "lit")
        body = _format_digits(value * 100 ** percent, pattern)
        if body is None:
            return None
    out = []
    for i, (kind, text) in enumerate(tokens):
        if runs is not None and i == runs[0]:
            out.append(body)
        elif kind == "lit":
            out.append(text)
        elif kind == "general" and runs is None:
            out.append(body)
    text = "".join(out).strip()
    if runs is None and not any(k == "general" for k, _t in tokens):
        return text
    return sign + text if text else None


def _format_sections(code: str) -> list:
    """Split a format code on the semicolons that are not quoted or escaped."""
    sections, cur, quoted, i = [], [], False, 0
    while i < len(code):
        ch = code[i]
        if ch == "\\" and not quoted and i + 1 < len(code):
            cur.append(code[i:i + 2])
            i += 2
            continue
        if ch == '"':
            quoted = not quoted
        if ch == ";" and not quoted:
            sections.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    sections.append("".join(cur))
    return sections


_FORMAT_DIGITS = set("0#?.,Ee+-")


def _format_tokens(section: str):
    """[(kind, text)] for one section: "lit", "digits", "general", "text".

    Quoted strings, backslash escapes and bracketed currency are literal;
    _x pads with a space the width of x and *x fills with x, both of which
    a preview shows as a single space and nothing. Colours print nothing.
    """
    tokens, i, n = [], 0, len(section)

    def lit(text):
        if tokens and tokens[-1][0] == "lit":
            tokens[-1] = ("lit", tokens[-1][1] + text)
        else:
            tokens.append(("lit", text))

    while i < n:
        ch = section[i]
        if ch == '"':
            end = section.find('"', i + 1)
            end = n if end == -1 else end
            lit(section[i + 1:end])
            i = end + 1
        elif ch == "\\":
            lit(section[i + 1:i + 2])
            i += 2
        elif ch == "_":
            lit(" ")
            i += 2
        elif ch == "*":
            i += 2
        elif ch == "[":
            end = section.find("]", i)
            if end == -1:
                return None
            inner = section[i + 1:end]
            if inner.startswith("$"):
                lit(inner[1:].split("-", 1)[0])  # [$€-408] -> €
            i = end + 1
        elif section[i:i + 7].lower() == "general":
            tokens.append(("general", ""))
            i += 7
        elif ch == "@":
            tokens.append(("text", ""))
            i += 1
        elif ch in "0#?" or (ch in ".," and _digit_near(section, i)):
            start = i
            while i < n and (section[i] in "0#?.," or (
                section[i] in "Ee" and i + 1 < n and section[i + 1] in "+-"
            ) or (section[i] in "+-" and i > start
                  and section[i - 1] in "Ee")):
                i += 1
            tokens.append(("digits", section[start:i]))
        else:
            lit(ch)
            i += 1
    return tokens


def _digit_near(section: str, i: int) -> bool:
    """Is the "." or "," at i part of a number pattern rather than text?"""
    after = section[i + 1:i + 2]
    before = section[i - 1:i] if i else ""
    return after in ("0", "#", "?") or before in ("0", "#", "?")


def _format_digits(value: float, pattern: str):
    """value (already non-negative, and scaled for %) through a digit run."""
    import re
    from decimal import ROUND_HALF_UP, Decimal

    if "E" in pattern.upper():
        mantissa, _e, exponent = re.split(r"([Ee][+-])", pattern, maxsplit=1)
        places = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
        digits = len(exponent.replace("#", "0"))
        text = "%.*e" % (places, value)
        num, exp = text.split("e")
        exp_val = int(exp)
        plus = "+" in pattern
        exp_sign = "-" if exp_val < 0 else ("+" if plus else "")
        return "%sE%s%0*d" % (num, exp_sign, digits, abs(exp_val))

    int_part, _dot, frac_part = pattern.partition(".")
    # Commas after the last digit scale by a thousand each ("#,##0," = k).
    stripped = int_part.rstrip(",")
    value /= 1000 ** (len(int_part) - len(stripped))
    grouping = "," in stripped
    int_min = stripped.count("0")
    frac_min = frac_part.count("0")
    frac_max = sum(frac_part.count(c) for c in "0#?")
    # Excel rounds half away from zero; Python's % rounds half to even.
    quant = Decimal(1).scaleb(-frac_max)
    number = Decimal(repr(value)).quantize(quant, rounding=ROUND_HALF_UP)
    text = "{:f}".format(number)
    whole, _d, frac = text.partition(".")
    frac = frac.rstrip("0").ljust(frac_min, "0") if frac_max else ""
    if whole == "0" and int_min == 0:
        whole = ""
    whole = whole.rjust(int_min, "0")
    if grouping and whole:
        whole = "{:,}".format(int(whole))
    return whole + ("." + frac if frac else "")


def _serial_to_date(raw: str, style: str) -> str:
    import datetime

    try:
        serial = float(raw)
    except ValueError:
        return ""
    if not 0 < serial < 2958466:  # 1900-01-01 .. 9999-12-31
        return ""
    days = int(serial)
    try:
        day = datetime.date.fromordinal(_EXCEL_EPOCH_ORDINAL + days)
    except (ValueError, OverflowError):
        return ""
    if style == "time":
        seconds = round((serial - days) * 86400)
        return "%02d:%02d:%02d" % (
            seconds // 3600 % 24, seconds // 60 % 60, seconds % 60
        )
    text = day.isoformat()
    if style == "datetime":
        seconds = round((serial - days) * 86400)
        text += " %02d:%02d" % (seconds // 3600 % 24, seconds // 60 % 60)
    return text


# Built-in number formats: the ids a workbook may use without writing the
# code out. 5-8 and 41-44 are locale-dependent currency and accounting
# formats, which the file does not spell out, so they stay General.
_XLSX_BUILTIN_FORMATS = {
    "1": "0", "2": "0.00", "3": "#,##0", "4": "#,##0.00",
    "9": "0%", "10": "0.00%", "11": "0.00E+00",
    "37": "#,##0 ;(#,##0)", "38": "#,##0 ;(#,##0)",
    "39": "#,##0.00;(#,##0.00)", "40": "#,##0.00;(#,##0.00)",
    "48": "##0.0E+0",
}


def _xlsx_formats(zf, names) -> dict:
    """Cell-format index -> (kind, code): how that style's numbers print.

    kind is "date", "datetime" or "time" — a date in xlsx is an ordinary
    number wearing a format, so without this every date in the file shows
    up as a five-digit serial — or "number", with the format code that
    gives a figure its decimals, thousands separators, currency and sign.
    """
    if "xl/styles.xml" not in names:
        return {}
    try:
        root = _member_xml(zf, "xl/styles.xml")
    except Exception:
        return {}
    builtin = {
        **{str(i): "date" for i in (14, 15, 16, 17, 30, 34, 35)},
        **{str(i): "datetime" for i in (22,)},
        **{str(i): "time" for i in (18, 19, 20, 21, 45, 46, 47)},
    }
    codes = dict(_XLSX_BUILTIN_FORMATS)
    for node in root.iter(SS + "numFmt"):
        codes[node.get("numFmtId")] = node.get("formatCode", "")
    formats, index = {}, 0
    for xfs in root.iter(SS + "cellXfs"):
        for xf in xfs.iter(SS + "xf"):
            fmt_id = xf.get("numFmtId", "0")
            kind = builtin.get(fmt_id)
            code = codes.get(fmt_id, "")
            if kind is None and code:
                kind = _classify_format(code) or "number"
            if kind:
                formats[str(index)] = (kind, code)
            index += 1
    return formats


def _classify_format(code: str) -> str:
    """Read a custom number-format code well enough to spot dates.

    Only the date/time letters outside quoted literals matter here; "m" is
    minutes or months depending on its neighbours, which is why a code with
    hours *and* a day is a datetime rather than either alone.
    """
    import re

    body, quoted = [], False
    for ch in code:
        if ch in ('"', "'"):
            quoted = not quoted
        elif not quoted:
            body.append(ch)
    text = "".join(body).lower()
    if "%" in text:
        return ""  # a percentage is a number with a format, not a date
    # Bracketed parts are colours, conditions and currency, not date letters.
    text = re.sub(r"\[[^\]]*\]", "", text)
    has_day = "y" in text or "d" in text
    has_time = "h" in text or "s" in text
    if has_day and has_time:
        return "datetime"
    if has_day:
        return "date"
    if has_time:
        return "time"
    return ""


def _ods_sheets(zf) -> list:
    """Same shape from an OpenDocument spreadsheet.

    ODF writes the displayed text alongside the value and run-length encodes
    repeats, so the text is taken straight from the cell and the repeat
    counts are expanded — bounded, since an empty trailing cell may claim to
    repeat a thousand times.
    """
    root = _member_xml(zf, "content.xml")
    sheets = []
    for table in root.iter(ODF_TABLE + "table"):
        grid, clipped = {}, False
        row_number = 1  # spreadsheets count rows from one, and so does the
        for row in table.iter(ODF_TABLE + "table-row"):  # preview's gutter
            repeat = _int_attr(row, ODF_TABLE + "number-rows-repeated", 1)
            cells, col = [], 0
            for cell in row:
                if cell.tag not in (
                    ODF_TABLE + "table-cell", ODF_TABLE + "covered-table-cell"
                ):
                    continue
                span = _int_attr(cell, ODF_TABLE + "number-columns-repeated", 1)
                text = " ".join(
                    "".join(p.itertext()).strip()
                    for p in cell.iter(ODF_TEXT + "p")
                ).strip()
                if text:
                    for offset in range(min(span, SHEET_MAX_COLS)):
                        cells.append((col + offset, text))
                col += span
                if col > SHEET_MAX_COLS * 4:
                    break
            # A row repeated a thousand times is padding unless it has
            # content, and padding is not worth a thousand rows of preview.
            repeat = min(repeat, 100 if cells else 1)
            for line in range(repeat):
                for column, text in cells:
                    grid[(row_number + line, column)] = (
                        text[:SHEET_MAX_CELL_CHARS]
                    )
            row_number += repeat
            if len(grid) > SHEET_MAX_ROWS * SHEET_MAX_COLS:
                clipped = True
                break
        sheets.append(_sheet_payload(
            table.get(ODF_TABLE + "name") or "Sheet", grid, clipped
        ))
    return sheets


def _int_attr(node, attr: str, default: int) -> int:
    try:
        return max(int(node.get(attr, default)), 1)
    except (TypeError, ValueError):
        return default
