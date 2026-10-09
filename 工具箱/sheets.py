"""读名单：Excel（.xlsx）和 CSV。

只用 Python 自带的库，Mac 上不用另外安装任何东西。
数字和日期会尽量按 Excel 里看到的样子显示（比如 8,500.00、2026/10/9）。
"""
import csv
import datetime
import io
from decimal import Decimal, ROUND_HALF_UP
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET


class SheetError(Exception):
    """给用户看的错误，文字直接显示在页面上。"""


# ---------------------------------------------------------------- 入口

def read_table(filename, data, sheet=None):
    """读一个名单文件。

    返回 {'sheets': [...], 'sheet': 当前表名, 'columns': [...], 'rows': [...]}，
    rows 里每一行是 {'_row': Excel 里的行号, 列名: 文字, ...}。
    """
    name = filename.lower()
    if name.endswith('.numbers'):
        raise SheetError('这是 Numbers 文件。请在 Numbers 里点「文件 → 导出为 → Excel」，再选导出的 .xlsx。')
    if name.endswith('.xls'):
        raise SheetError('这是老版本的 .xls 格式。请用 Excel 或 WPS 打开，「另存为」.xlsx 再选。')
    if name.endswith(('.xlsx', '.xlsm')) or data[:2] == b'PK':
        sheets, grid_of = _read_xlsx(data)
        if sheet not in sheets:
            sheet = sheets[0]
        grid = grid_of(sheet)
    elif name.endswith(('.csv', '.tsv', '.txt')):
        sheets, grid = ['CSV'], _read_csv(data)
        sheet = 'CSV'
    else:
        raise SheetError('只支持 Excel（.xlsx）和 CSV 文件。')
    columns, rows = _grid_to_rows(grid)
    if not columns:
        raise SheetError('这张表是空的。' + ('试试换一张工作表。' if len(sheets) > 1 else ''))
    return {'sheets': sheets, 'sheet': sheet, 'columns': columns, 'rows': rows}


def _grid_to_rows(grid):
    """第一行有内容的行当表头，下面的每一行变成 {列名: 值}。整行空的跳过。"""
    header_at = None
    for i, (_, cells) in enumerate(grid):
        if any(c.strip() for c in cells):
            header_at = i
            break
    if header_at is None:
        return [], []
    width = max(len(cells) for _, cells in grid[header_at:])
    head = grid[header_at][1] + [''] * width
    columns, seen = [], {}
    for j in range(width):
        col = head[j].strip() or '第%s列' % _col_letter(j)
        if col in seen:
            seen[col] += 1
            col = '%s(%d)' % (col, seen[col])
        else:
            seen[col] = 1
        columns.append(col)
    rows = []
    for rownum, cells in grid[header_at + 1:]:
        if not any(c.strip() for c in cells):
            continue
        row = {'_row': rownum}
        for j, col in enumerate(columns):
            row[col] = cells[j].strip() if j < len(cells) else ''
        rows.append(row)
    return columns, rows


def _col_letter(j):
    s = ''
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


# ---------------------------------------------------------------- CSV

def _read_csv(data):
    for enc in ('utf-8-sig', 'gb18030'):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SheetError('认不出这个 CSV 的文字编码。请用 Excel 打开后另存为 .xlsx 再试。')
    first = text.split('\n', 1)[0]
    delim = max([',', '\t', ';'], key=first.count)
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delim)
    return [(i + 1, row) for i, row in enumerate(reader)]


# ---------------------------------------------------------------- XLSX

def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _attr(el, name):
    """取属性，不管它带不带命名空间（比如 r:id）。"""
    for k, v in el.attrib.items():
        if _local(k) == name:
            return v
    return None


def _read_xlsx(data):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SheetError('这个 Excel 文件打不开，可能已损坏，或者设置了打开密码。')
    names = set(z.namelist())

    def xml(path):
        return ET.fromstring(z.read(path)) if path in names else None

    wb = xml('xl/workbook.xml')
    if wb is None:
        raise SheetError('这个文件不像是 Excel 表格，或者设置了打开密码。')
    rels = {}
    rel_root = xml('xl/_rels/workbook.xml.rels')
    for r in (rel_root if rel_root is not None else []):
        target = r.get('Target', '')
        target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
        rels[r.get('Id')] = target

    date1904 = False
    pr = _child(wb, 'workbookPr')
    if pr is not None and pr.get('date1904') in ('1', 'true'):
        date1904 = True

    sheets, hidden = [], []
    sheets_el = _child(wb, 'sheets')
    for s in (sheets_el if sheets_el is not None else []):
        path = rels.get(_attr(s, 'id'))
        if path in names:
            item = (s.get('name'), path)
            (hidden if s.get('state') in ('hidden', 'veryHidden') else sheets).append(item)
    sheets += hidden
    if not sheets:
        raise SheetError('这个 Excel 里没有找到工作表。')

    shared = []
    sst = xml('xl/sharedStrings.xml')
    for si in (sst if sst is not None else []):
        shared.append(_rich_text(si))

    styles = _read_styles(xml('xl/styles.xml'))
    paths = dict(sheets)

    def grid_of(sheet_name):
        return _read_sheet(xml(paths[sheet_name]), shared, styles, date1904)

    return [n for n, _ in sheets], grid_of


def _rich_text(si):
    """一个字符串格子的文字：<t> 或多段 <r><t>，跳过注音 <rPh>。"""
    parts = []
    for el in si:
        tag = _local(el.tag)
        if tag == 't':
            parts.append(el.text or '')
        elif tag == 'r':
            t = _child(el, 't')
            if t is not None:
                parts.append(t.text or '')
    return ''.join(parts)


def _read_styles(root):
    """返回列表：第 i 个样式对应的数字格式代码。"""
    if root is None:
        return []
    custom = {}
    nf = _child(root, 'numFmts')
    for f in (nf if nf is not None else []):
        custom[int(f.get('numFmtId', '0'))] = f.get('formatCode', '')
    out = []
    xfs = _child(root, 'cellXfs')
    for xf in (xfs if xfs is not None else []):
        fid = int(xf.get('numFmtId', '0') or 0)
        out.append(custom.get(fid, BUILTIN_FORMATS.get(fid, 'General')))
    return out


_CELL_REF = re.compile(r'([A-Z]+)(\d+)')


def _col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _read_sheet(root, shared, styles, date1904):
    grid = []
    data = _child(root, 'sheetData') if root is not None else None
    next_row = 1
    for row in (data if data is not None else []):
        rownum = int(row.get('r') or next_row)
        next_row = rownum + 1
        cells = []
        for c in _children(row, 'c'):
            m = _CELL_REF.match(c.get('r') or '')
            j = _col_index(m.group(1)) if m else len(cells)
            while len(cells) < j:
                cells.append('')
            cells.append(_cell_text(c, shared, styles, date1904))
        grid.append((rownum, cells))
    return grid


def _cell_text(c, shared, styles, date1904):
    t = c.get('t', 'n')
    v = _child(c, 'v')
    v = v.text if v is not None and v.text is not None else None
    if t == 'inlineStr':
        is_ = _child(c, 'is')
        return _rich_text(is_) if is_ is not None else ''
    if v is None:
        return ''
    if t == 's':
        try:
            return shared[int(v)]
        except (ValueError, IndexError):
            return ''
    if t == 'b':
        return 'TRUE' if v == '1' else 'FALSE'
    if t in ('str', 'e'):
        return v
    if t == 'd':
        return v.replace('T', ' ')
    try:
        num = float(v)
    except ValueError:
        return v
    s = int(c.get('s') or 0)
    code = styles[s] if s < len(styles) else 'General'
    return format_value(num, code, date1904)


# ---------------------------------------------------------------- 数字格式

# Excel 内置格式里常用的那些（日期按中文版 Excel 的显示）
BUILTIN_FORMATS = {
    0: 'General', 1: '0', 2: '0.00', 3: '#,##0', 4: '#,##0.00',
    9: '0%', 10: '0.00%', 11: '0.00E+00', 12: '# ?/?', 13: '# ??/??',
    14: 'yyyy/m/d', 15: 'd-mmm-yy', 16: 'd-mmm', 17: 'mmm-yy',
    18: 'h:mm AM/PM', 19: 'h:mm:ss AM/PM', 20: 'h:mm', 21: 'h:mm:ss',
    22: 'yyyy/m/d h:mm',
    27: 'yyyy"年"m"月"', 28: 'm"月"d"日"', 29: 'm"月"d"日"', 30: 'm-d-yy',
    31: 'yyyy"年"m"月"d"日"', 32: 'h"时"mm"分"', 33: 'h"时"mm"分"ss"秒"',
    34: 'h"时"mm"分"', 35: 'h"时"mm"分"ss"秒"', 36: 'yyyy"年"m"月"',
    37: '#,##0 ;(#,##0)', 38: '#,##0 ;(#,##0)', 39: '#,##0.00;(#,##0.00)',
    40: '#,##0.00;(#,##0.00)', 45: 'mm:ss', 46: '[h]:mm:ss', 47: 'mm:ss.0',
    48: '##0.0E+0', 49: '@',
    50: 'yyyy"年"m"月"', 51: 'm"月"d"日"', 52: 'yyyy"年"m"月"', 53: 'm"月"d"日"',
    54: 'm"月"d"日"', 55: 'h"时"mm"分"', 56: 'h"时"mm"分"ss"秒"',
    57: 'yyyy"年"m"月"', 58: 'm"月"d"日"',
}

_TOKEN = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.|AM/PM|A/P|上午/下午|'
                    r'y+|m+|d+|h+|s+|e+|a{3,4}|[^"\\\[_*ymdhsea]+|.', re.I)


def _split_sections(code):
    parts, buf, quoted = [], '', False
    i = 0
    while i < len(code):
        ch = code[i]
        if ch == '"':
            quoted = not quoted
        elif ch == '\\' and not quoted and i + 1 < len(code):
            buf += code[i:i + 2]
            i += 2
            continue
        elif ch == ';' and not quoted:
            parts.append(buf)
            buf = ''
            i += 1
            continue
        buf += ch
        i += 1
    parts.append(buf)
    return parts


def _is_date_format(sec):
    stripped = re.sub(r'"[^"]*"|\\.|\[\$[^\]]*\]|\[[^\]hms]*\]|_.|\*.', '', sec, flags=re.I)
    return bool(re.search(r'[ymdhs]', stripped, re.I)) and not re.search(r'[0#?]', stripped.replace('.0', ''))


def format_value(num, code, date1904=False):
    if not code or code.lower() in ('general', '@'):
        return _general(num)
    sections = _split_sections(code)
    sec = sections[0]
    if num < 0 and len(sections) >= 2 and sections[1].strip():
        sec, num = sections[1], -num
    elif num == 0 and len(sections) >= 3 and sections[2].strip():
        sec = sections[2]
    if sec.strip().lower() in ('general', ''):
        return _general(num)
    try:
        if _is_date_format(sec):
            return _format_date(num, sec, date1904)
        return _format_number(num, sec)
    except (ValueError, OverflowError):
        return _general(num)


def _general(num):
    if num == int(num) and abs(num) < 1e15:
        return str(int(num))
    return '%.15g' % num


def _literal(tok):
    if tok.startswith('"'):
        return tok[1:-1]
    if tok.startswith('\\'):
        return tok[1:]
    if tok.startswith('[$'):
        return tok[2:-1].split('-', 1)[0]  # [$¥-804] → ¥
    if tok.startswith('[') or tok[0] in '_*':
        return ''
    return None


def _format_number(num, sec):
    # 把格式拆成：前面的文字 + 数字部分 + 后面的文字
    toks = re.findall(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.|[0#?.,%Ee+\-]+|.', sec)
    pre, pattern, post = '', '', ''
    for tok in toks:
        lit = _literal(tok)
        if lit is None and re.search(r'[0#?]', tok):
            if post:  # 数字部分被文字隔开了，后面的也算数字部分
                pattern += post
                post = ''
            pattern += tok
            continue
        text = tok if lit is None else lit
        if pattern:
            post += text
        else:
            pre += text
    if not pattern:
        return pre + post or _general(num)
    if '%' in pattern:
        num *= 100
        post = '%' * pattern.count('%') + post
        pattern = pattern.replace('%', '')
    elif '%' in post:
        num *= 100
    if re.search(r'E[+-]', pattern, re.I):
        mant = re.split(r'E', pattern, flags=re.I)[0]
        decimals = len(re.findall(r'[0#]', mant.split('.', 1)[1])) if '.' in mant else 0
        m, e = (('%.' + str(decimals) + 'E') % num).split('E')
        return pre + m + 'E' + ('+' if int(e) >= 0 else '-') + '%02d' % abs(int(e)) + post
    int_part, _, frac_part = pattern.partition('.')
    decimals = len(re.findall(r'[0#?]', frac_part))
    group = ',' in int_part
    min_int = len(re.findall(r'0', int_part))
    # 四舍五入按 Excel 的习惯（2.675 → 2.68），不是 Python 默认的银行家舍入
    value = Decimal(repr(abs(num))).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    text = ('{:,.%df}' if group else '{:.%df}').replace('%d', str(decimals)).format(value)
    if decimals and re.fullmatch(r'[#?]+', frac_part.replace(',', '')):
        text = text.rstrip('0').rstrip('.')
    head = text.split('.')[0]
    if head.replace(',', '') == '0' and min_int == 0:
        text = text[len(head):]
    elif not group and len(head) < min_int:
        text = head.zfill(min_int) + text[len(head):]
    sign = '-' if num < 0 and value != 0 else ''
    return sign + pre + text + post


_WEEK_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
_WEEK_EN_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
_WEEK_ZH = '一二三四五六日'
_MON_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
_MON_EN_FULL = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December']


def _format_date(num, sec, date1904):
    base = datetime.datetime(1904, 1, 1) if date1904 else datetime.datetime(1899, 12, 30)
    dt = base + datetime.timedelta(seconds=round(num * 86400))
    toks = _TOKEN.findall(sec)
    has_ampm = any(t.upper() in ('AM/PM', 'A/P') or t == '上午/下午' for t in toks)
    kinds = []
    for t in toks:
        lo = t.lower()
        kinds.append(lo[0] if lo and lo[0] in 'ymdhse' and lo.strip(lo[0]) == '' else None)
    out = []
    for i, t in enumerate(toks):
        lo, k = t.lower(), kinds[i]
        if k in ('y', 'e'):
            out.append(str(dt.year)[-2:] if len(t) <= 2 and k == 'y' else str(dt.year))
        elif k == 'm':
            prev = next((kinds[j] for j in range(i - 1, -1, -1) if kinds[j]), None)
            nxt = next((kinds[j] for j in range(i + 1, len(toks)) if kinds[j]), None)
            if len(t) <= 2 and (prev == 'h' or nxt == 's'):
                out.append('%02d' % dt.minute if len(t) == 2 else str(dt.minute))
            elif len(t) == 1:
                out.append(str(dt.month))
            elif len(t) == 2:
                out.append('%02d' % dt.month)
            elif len(t) == 3:
                out.append(_MON_EN[dt.month - 1])
            elif len(t) == 4:
                out.append(_MON_EN_FULL[dt.month - 1])
            else:
                out.append(_MON_EN[dt.month - 1][0])
        elif k == 'd':
            if len(t) == 1:
                out.append(str(dt.day))
            elif len(t) == 2:
                out.append('%02d' % dt.day)
            elif len(t) == 3:
                out.append(_WEEK_EN[dt.weekday()])
            else:
                out.append(_WEEK_EN_FULL[dt.weekday()])
        elif k == 'h':
            h = dt.hour
            if has_ampm:
                h = h % 12 or 12
            out.append('%02d' % h if len(t) == 2 else str(h))
        elif k == 's':
            out.append('%02d' % dt.second if len(t) == 2 else str(dt.second))
        elif lo in ('aaa', 'aaaa'):
            out.append(('星期' if lo == 'aaaa' else '') + _WEEK_ZH[dt.weekday()])
        elif t.upper() == 'AM/PM':
            out.append('AM' if dt.hour < 12 else 'PM')
        elif t.upper() == 'A/P':
            out.append('A' if dt.hour < 12 else 'P')
        elif t == '上午/下午':
            out.append('上午' if dt.hour < 12 else '下午')
        elif lo in ('[h]', '[hh]'):
            out.append(str(int(num * 24)))
        elif lo in ('[m]', '[mm]'):
            out.append(str(int(num * 1440)))
        elif lo in ('[s]', '[ss]'):
            out.append(str(int(num * 86400)))
        else:
            lit = _literal(t)
            out.append(t if lit is None else lit)
    return ''.join(out)
