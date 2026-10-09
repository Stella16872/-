"""表格工具（合并、拆分、核对）的网页接口。由 app.py 挂上去。"""
import datetime
import os
import secrets
import shutil

import sheets
import tables

PREVIEW_ROWS = 100


def _texts(row, n=None):
    cells = row['_cells'] if isinstance(row, dict) else row
    return [tables.cell_text(c if isinstance(c, tuple) else (c, None)) for c in cells[:n]]


class Tools:
    def __init__(self, state, out_dir, mail_table_hook):
        self.state = state                    # app.STATE：lock、tmpdir、files、table
        self.out_dir = out_dir                # 拆分结果放这里
        self.mail_table_hook = mail_table_hook
        self.sources = {}                     # sid -> {'filename', 'data'}
        self.cache = {}                       # (sid, sheet, header_row) -> 表
        self.outputs = {}                     # 下载用：id -> (文件名, 内容)
        self.last_split = None

    def routes(self):
        return {
            ('POST', '/api/source_upload'): self.source_upload,
            ('POST', '/api/source_view'): self.source_view,
            ('POST', '/api/source_remove'): self.source_remove,
            ('POST', '/api/merge'): self.merge,
            ('POST', '/api/split'): self.split,
            ('POST', '/api/split_to_mail'): self.split_to_mail,
            ('POST', '/api/compare'): self.compare,
            ('POST', '/api/compare_to_mail'): self.compare_to_mail,
        }

    # ------------------------------------------------------------ 读表
    def table(self, ref):
        """ref: {'sid', 'sheet', 'header_row'} → 读出来的表（会缓存）。"""
        src = self.sources.get(ref.get('sid'))
        if not src:
            raise sheets.SheetError('文件已经不在了（工具箱重新打开过？），请重新选一次。')
        key = (ref['sid'], ref.get('sheet'), ref.get('header_row'))
        if key not in self.cache:
            t = sheets.read_table(src['filename'], src['data'], ref.get('sheet'), ref.get('header_row'))
            t['filename'] = src['filename']
            self.cache[key] = t
        return self.cache[key]

    def view(self, sid, t):
        return {'sid': sid, 'filename': t['filename'], 'sheets': t['sheets'], 'sheet': t['sheet'],
                'header_row': t['header_row'], 'candidates': t['candidates'], 'columns': t['columns'],
                'total': len(t['rows']), 'preview': [[r['_row']] + _texts(r) for r in t['rows'][:30]]}

    def add_source(self, name, data):
        sid = secrets.token_hex(6)
        self.sources[sid] = {'filename': name, 'data': data}
        return sid

    def source_upload(self, q, body):
        name = q.get('name', 'table.xlsx')
        sid = self.add_source(name, body)
        try:
            return self.view(sid, self.table({'sid': sid}))
        except sheets.SheetError:
            del self.sources[sid]
            raise

    def source_view(self, _q, b):
        return self.view(b['sid'], self.table(b))

    def source_remove(self, _q, b):
        self.sources.pop(b.get('sid'), None)
        for k in [k for k in self.cache if k[0] == b.get('sid')]:
            del self.cache[k]
        return {'ok': True}

    def _download(self, filename, data):
        oid = secrets.token_hex(8)
        self.outputs[oid] = (filename, data)
        while len(self.outputs) > 20:
            del self.outputs[next(iter(self.outputs))]
        return {'id': oid, 'filename': filename}

    def get_output(self, oid):
        return self.outputs.get(oid)

    # ------------------------------------------------------------ 合并
    def merge(self, _q, b):
        parts, skipped = [], []
        for ref in b.get('sources', []):
            if ref.get('all_sheets'):
                first = self.table({'sid': ref['sid']})
                for name in first['sheets']:
                    try:
                        t = self.table({'sid': ref['sid'], 'sheet': name})
                    except sheets.SheetError:
                        skipped.append('%s · %s' % (first['filename'], name))
                        continue
                    label = first['filename'] if len(first['sheets']) == 1 else '%s · %s' % (first['filename'], name)
                    parts.append((label, t))
            else:
                t = self.table(ref)
                parts.append((t['filename'], t))
        if not parts:
            raise sheets.SheetError('先添加要合并的表格。')
        m = tables.merge(parts, rename=b.get('rename') or {}, add_source=b.get('add_source', True),
                         drop_totals=b.get('drop_totals', True), dedupe=b.get('dedupe', False))
        out = {'columns': m['columns'], 'total': len(m['rows']), 'labels': [p[0] for p in parts],
               'counts': [len(p[1]['rows']) for p in parts], 'matrix': m['matrix'],
               'removed_totals': m['removed_totals'], 'removed_dupes': m['removed_dupes'], 'skipped': skipped,
               'preview': [_texts(r) for r in m['rows'][:PREVIEW_ROWS]]}
        if b.get('export'):
            data = sheets.write_xlsx([{'name': '合并结果', 'columns': m['columns'], 'rows': m['rows']}])
            stamp = datetime.datetime.now().strftime('%m%d_%H%M')
            out['download'] = self._download('合并结果_%s.xlsx' % stamp, data)
            # 合并结果也登记成一个来源，「接着拆分 / 核对」时直接用
            sid = self.add_source(out['download']['filename'], data)
            out['source'] = self.view(sid, self.table({'sid': sid}))
        return out

    # ------------------------------------------------------------ 拆分
    def split(self, _q, b):
        t = self.table(b)
        column = b.get('column') or ''
        groups, removed = tables.split(t, column, drop_totals=b.get('drop_totals', True))
        template = (b.get('name_tpl') or '{值}').strip()
        if template.lower().endswith('.xlsx'):
            template = template[:-5]
        names = tables.split_filenames([v for v, _ in groups], template)
        out = {'groups': [{'value': v, 'count': len(rs), 'filename': n + '.xlsx'}
                          for (v, rs), n in zip(groups, names)],
               'total': sum(len(rs) for _, rs in groups), 'removed': removed}
        if not b.get('export'):
            return out
        if not groups:
            raise sheets.SheetError('没有可以拆分的行。')
        stem = os.path.splitext(t['filename'])[0]
        if b.get('mode') == 'sheets':
            data = sheets.write_xlsx([{'name': v, 'columns': t['columns'], 'rows': [r['_cells'] for r in rs]}
                                      for v, rs in groups])
            out['download'] = self._download(tables.safe_filename('%s_按%s拆分.xlsx' % (stem, column)), data)
            return out
        stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
        folder = os.path.join(self.out_dir, tables.safe_filename('%s_%s_按%s拆分' % (stamp, stem, column)))
        os.makedirs(folder, exist_ok=True)
        files = []
        for (v, rs), n in zip(groups, names):
            path = os.path.join(folder, n + '.xlsx')
            with open(path, 'wb') as f:
                f.write(sheets.write_xlsx([{'name': v, 'columns': t['columns'],
                                            'rows': [r['_cells'] for r in rs]}]))
            files.append((path, n + '.xlsx'))
        self.last_split = {'folder': folder, 'files': files, 'column': column, 'template': template,
                           'source': {k: b.get(k) for k in ('sid', 'sheet', 'header_row')}}
        out['folder'] = folder
        return out

    def split_to_mail(self, _q, _b):
        """把刚拆好的文件交给「群发邮件」，当作每个人不一样的附件。"""
        ls = self.last_split
        if not ls:
            raise sheets.SheetError('还没有拆分过。')
        st = self.state
        with st.lock:
            for fid in [k for k, f in st.files.items() if f['group'] == 'folder']:
                shutil.rmtree(os.path.dirname(st.files[fid]['path']), ignore_errors=True)
                del st.files[fid]
            for path, name in ls['files']:
                if not os.path.exists(path):
                    continue
                fid = secrets.token_hex(8)
                d = os.path.join(st.tmpdir, fid)
                os.makedirs(d)
                dest = os.path.join(d, name)
                shutil.copyfile(path, dest)
                st.files[fid] = {'id': fid, 'group': 'folder', 'name': name, 'rel': name, 'path': dest,
                                 'size': os.path.getsize(dest)}
        rule = ls['template'].replace('{值}', '{%s}' % ls['column']) if '{值}' in ls['template'] \
            else ls['template'] + '{%s}' % ls['column']
        # 群发那边还没有名单的话，把拆分用的这张表当名单（里面有邮箱列才行）
        table_set = False
        try:
            t = dict(self.table(ls['source']), data=self.sources[ls['source']['sid']]['data'])
            table_set = self.mail_table_hook(t, only_if_empty=True)
        except (sheets.SheetError, KeyError):
            pass
        return {'rule': rule, 'count': len(ls['files']), 'table_set': table_set}

    # ------------------------------------------------------------ 核对
    def _compare(self, b):
        a, bb = self.table(b['a']), self.table(b['b'])
        cols = b.get('columns')
        cols = [tuple(c) for c in cols] if cols is not None else None
        res = tables.compare(a, bb, b.get('key_a'), b.get('key_b'), cols, loose=b.get('loose', True))
        return a, bb, res

    def compare(self, _q, b):
        a, bb, res = self._compare(b)

        def cells(ch):
            return {'column': ch['column'], 'a': tables.cell_text(ch['a']), 'b': tables.cell_text(ch['b'])}
        out = {
            'columns_a': a['columns'], 'columns_b': bb['columns'],
            'common': [list(p) for p in tables.common_columns(a, bb, b.get('key_a'), b.get('key_b'))],
            'compared': [list(p) for p in res['columns']],
            'only_a': [[r['_row']] + _texts(r) for r in res['only_a'][:500]], 'n_only_a': len(res['only_a']),
            'only_b': [[r['_row']] + _texts(r) for r in res['only_b'][:500]], 'n_only_b': len(res['only_b']),
            'diffs': [{'key': d['key'], 'row_a': d['row_a'], 'row_b': d['row_b'],
                       'changes': [cells(ch) for ch in d['changes']]} for d in res['diffs'][:500]],
            'n_diffs': len(res['diffs']), 'same': res['same'],
            'dup_a': res['dup_a'], 'dup_b': res['dup_b'], 'blank_a': res['blank_a'], 'blank_b': res['blank_b'],
        }
        if b.get('export'):
            data = tables.compare_report(a, bb, b['key_a'], b['key_b'], res, a['filename'], bb['filename'])
            stamp = datetime.datetime.now().strftime('%m%d_%H%M')
            out['download'] = self._download('核对结果_%s.xlsx' % stamp, data)
        return out

    def compare_to_mail(self, _q, b):
        a, bb, res = self._compare(b)
        which = 'b' if b.get('which') == 'b' else 'a'
        t = a if which == 'a' else bb
        rows = res['only_a'] if which == 'a' else res['only_b']
        if not rows:
            raise sheets.SheetError('没有需要发的人。')
        label = '核对结果：只在 %s 里（%s）' % (which.upper(), t['filename'])
        sub = {'filename': label, 'data': None, 'sheets': ['核对结果'], 'sheet': '核对结果', 'header_row': None,
               'candidates': [], 'columns': t['columns'], 'rows': rows}
        self.mail_table_hook(sub, only_if_empty=False)
        return {'count': len(rows), 'label': label}
