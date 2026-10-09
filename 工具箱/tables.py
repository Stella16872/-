"""表格小工具：合并、拆分、核对。

输入都是 sheets.read_table() 读出来的表；每行的 '_cells' 里有原始值和数字格式，
所以写出来的新表里，数字还是数字、日期还是日期。
"""
import re
import unicodedata

import sheets

EMPTY_CELL = (None, None)


def norm(s):
    """比较列名、比较内容用：全角半角统一，去掉空白。"""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s))).lower()


def cell_text(cell):
    """(原始值, 格式) → 看到的文字。"""
    value, code = cell
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, float):
        return sheets.format_value(value, code or 'General')
    return str(value)


def _has_value(cell):
    return cell[0] not in (None, '')


# ---------------------------------------------------------------- 合并

_TOTAL_WORDS = ('合计', '总计', '小计', '总和', '共计', '总数', 'total', 'subtotal', 'sum')


def is_total_row(row, columns):
    """「合计 / 总计 / 小计」这种汇总行：前几个有内容的格子里有这些字。"""
    seen = 0
    for c in columns:
        text = norm(row.get(c, '')).rstrip(':：')
        if not text:
            continue
        if len(text) <= 8 and any(text.startswith(w) for w in _TOTAL_WORDS):
            return True
        seen += 1
        if seen >= 3:
            break
    return False


def merge(sources, rename=None, add_source=True, drop_totals=True, dedupe=False):
    """把几张表上下拼成一张，按列名对齐（列的顺序不一样也没关系）。

    sources: [(来源名, 表), ...]
    rename: {原列名: 新列名}，用来把「名字」和「姓名」这种对齐成同一列。
    """
    rename = rename or {}
    order, display, originals = [], {}, {}
    per_source = []
    for label, t in sources:
        keys = []
        for c in t['columns']:
            name = (rename.get(c) or c).strip() or c
            k = norm(name)
            if k not in display:
                display[k] = name
                order.append(k)
                originals[k] = []
            if c not in originals[k]:
                originals[k].append(c)
            keys.append(k)
        per_source.append(keys)

    source_col = '来源'
    while add_source and norm(source_col) in display:
        source_col += '文件'
    columns = ([source_col] if add_source else []) + [display[k] for k in order]

    rows, removed_totals = [], 0
    for (label, t), keys in zip(sources, per_source):
        for r in t['rows']:
            if drop_totals and is_total_row(r, t['columns']):
                removed_totals += 1
                continue
            values = {}
            for j, k in enumerate(keys):
                cell = r['_cells'][j]
                if k not in values or (not _has_value(values[k]) and _has_value(cell)):
                    values[k] = cell
            row = ([(label, None)] if add_source else []) + [values.get(k, EMPTY_CELL) for k in order]
            rows.append(row)

    removed_dupes = 0
    if dedupe:
        seen, kept = set(), []
        start = 1 if add_source else 0
        for row in rows:
            sig = tuple(norm(cell_text(c)) for c in row[start:])
            if sig in seen:
                removed_dupes += 1
                continue
            seen.add(sig)
            kept.append(row)
        rows = kept

    matrix = [{'column': display[k], 'originals': originals[k],
               'in': [k in keys for keys in per_source]} for k in order]
    return {'columns': columns, 'rows': rows, 'matrix': matrix,
            'removed_totals': removed_totals, 'removed_dupes': removed_dupes}


# ---------------------------------------------------------------- 拆分

BLANK = '（空白）'


def split(table, column, drop_totals=True):
    """按某一列的值分组。返回 ([(值, [行...]), ...], 去掉的合计行数)，顺序和第一次出现的顺序一样。"""
    if column not in table['columns']:
        raise sheets.SheetError('表格里没有「%s」这一列。' % column)
    groups, order, removed = {}, [], 0
    for r in table['rows']:
        if drop_totals and is_total_row(r, table['columns']):
            removed += 1
            continue
        value = r.get(column, '').strip() or BLANK
        if value not in groups:
            groups[value] = []
            order.append(value)
        groups[value].append(r)
    return [(v, groups[v]) for v in order], removed


def safe_filename(name, limit=80):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', str(name)).strip().strip('.')
    return name[:limit] or '未命名'


def split_filenames(values, template):
    """每组的文件名（不带 .xlsx）。template 里的 {值} 换成这一组的值；重名的加 (2)。"""
    out, used = [], set()
    for v in values:
        base = safe_filename(template.replace('{值}', v) if '{值}' in template else template + v)
        name, n = base, 1
        while name.lower() in used:
            n += 1
            name = '%s(%d)' % (base, n)
        used.add(name.lower())
        out.append(name)
    return out


# ---------------------------------------------------------------- 核对

def _key_of(row, columns, col, loose):
    value, _ = sheets.cell_value(row, columns, col)
    if isinstance(value, float):  # 工号这类数字：1001 和 "1001" 算同一个
        text = sheets.format_value(value, 'General')
    else:
        text = row.get(col, '')
    text = unicodedata.normalize('NFKC', text).strip()
    return norm(text) if loose else text


def _same(a, b, loose):
    va, vb = a[0], b[0]
    if isinstance(va, float) and isinstance(vb, float):
        return abs(va - vb) < 1e-9
    ta, tb = cell_text(a).strip(), cell_text(b).strip()
    if isinstance(va, float) != isinstance(vb, float):
        # 一边是数字一边是文字（比如 8500 和 "8500"）：按数字比
        try:
            return abs(float(ta.replace(',', '')) - float(tb.replace(',', ''))) < 1e-9
        except ValueError:
            pass
    if loose:
        return norm(ta) == norm(tb)
    return ta == tb


def common_columns(a, b, key_a=None, key_b=None):
    """两张表里名字一样的列（不含用来对应的那一列）。"""
    bk = {norm(c): c for c in b['columns']}
    out = []
    for c in a['columns']:
        if c == key_a:
            continue
        other = bk.get(norm(c))
        if other and other != key_b:
            out.append((c, other))
    return out


def compare(a, b, key_a, key_b, columns=None, loose=True):
    """按 key 列把两张表对上，找出：只在 A 里的、只在 B 里的、两边都有但内容不一样的。

    columns: 要比较内容的列 [(A 的列名, B 的列名), ...]；不填就比所有名字一样的列。
    """
    for t, k, label in ((a, key_a, 'A'), (b, key_b, 'B')):
        if k not in t['columns']:
            raise sheets.SheetError('表 %s 里没有「%s」这一列。' % (label, k))
    if columns is None:
        columns = common_columns(a, b, key_a, key_b)

    def index(t, key):
        idx, order, blank = {}, [], 0
        for r in t['rows']:
            k = _key_of(r, t['columns'], key, loose)
            if not k:
                blank += 1
                continue
            if k not in idx:
                idx[k] = []
                order.append(k)
            idx[k].append(r)
        return idx, order, blank

    ia, oa, blank_a = index(a, key_a)
    ib, ob, blank_b = index(b, key_b)
    only_a = [r for k in oa if k not in ib for r in ia[k]]
    only_b = [r for k in ob if k not in ia for r in ib[k]]
    diffs, same = [], 0
    for k in oa:
        if k not in ib:
            continue
        ra, rb = ia[k][0], ib[k][0]
        changed = []
        for ca, cb in columns:
            cell_a = sheets.cell_value(ra, a['columns'], ca)
            cell_b = sheets.cell_value(rb, b['columns'], cb)
            if not _same(cell_a, cell_b, loose):
                changed.append({'column': ca, 'a': cell_a, 'b': cell_b})
        if changed:
            diffs.append({'key': ra.get(key_a, ''), 'row_a': ra['_row'], 'row_b': rb['_row'], 'changes': changed})
        else:
            same += 1
    dup_a = [{'key': ia[k][0].get(key_a, ''), 'rows': [r['_row'] for r in ia[k]]} for k in oa if len(ia[k]) > 1]
    dup_b = [{'key': ib[k][0].get(key_b, ''), 'rows': [r['_row'] for r in ib[k]]} for k in ob if len(ib[k]) > 1]
    return {'only_a': only_a, 'only_b': only_b, 'diffs': diffs, 'same': same, 'columns': columns,
            'dup_a': dup_a, 'dup_b': dup_b, 'blank_a': blank_a, 'blank_b': blank_b}


def compare_report(a, b, key_a, key_b, result, name_a, name_b):
    """核对结果写成一个 Excel：汇总 + 只在 A 里 + 只在 B 里 + 内容不同。"""
    summary = [
        ['表 A', name_a, '%d 行' % len(a['rows'])],
        ['表 B', name_b, '%d 行' % len(b['rows'])],
        ['用来对应的列', '%s ↔ %s' % (key_a, key_b), ''],
        ['只在 A 里', '%d 行' % len(result['only_a']), '见「只在A里」'],
        ['只在 B 里', '%d 行' % len(result['only_b']), '见「只在B里」'],
        ['两边都有、内容不同', '%d 个' % len(result['diffs']), '见「内容不同」，不一样的格子标了黄色'],
        ['两边都有、内容一样', '%d 个' % result['same'], ''],
    ]
    for label, dups in (('A', result['dup_a']), ('B', result['dup_b'])):
        for d in dups:
            summary.append(['表 %s 里重复' % label, d['key'], '第 %s 行' % '、'.join(str(r) for r in d['rows'])])
    out = [{'name': '汇总', 'columns': ['项目', '内容', '说明'], 'rows': summary}]
    out.append({'name': '只在A里', 'columns': ['表A行号'] + a['columns'],
                'rows': [[r['_row']] + list(r['_cells']) for r in result['only_a']]})
    out.append({'name': '只在B里', 'columns': ['表B行号'] + b['columns'],
                'rows': [[r['_row']] + list(r['_cells']) for r in result['only_b']]})
    changed_cols = []
    for d in result['diffs']:
        for ch in d['changes']:
            if ch['column'] not in changed_cols:
                changed_cols.append(ch['column'])
    cols = [key_a, '表A行号', '表B行号']
    for c in changed_cols:
        cols += ['%s（A）' % c, '%s（B）' % c]
    rows, marks = [], set()
    for i, d in enumerate(result['diffs']):
        by_col = {ch['column']: ch for ch in d['changes']}
        row = [d['key'], d['row_a'], d['row_b']]
        for j, c in enumerate(changed_cols):
            ch = by_col.get(c)
            if ch:
                row += [ch['a'], ch['b']]
                marks.add((i, 3 + 2 * j))
                marks.add((i, 4 + 2 * j))
            else:
                row += [None, None]
        rows.append(row)
    out.append({'name': '内容不同', 'columns': cols, 'rows': rows, 'marks': marks})
    return sheets.write_xlsx(out)
