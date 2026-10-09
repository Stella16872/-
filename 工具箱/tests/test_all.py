"""端到端测试：启动工具箱和一个假邮件服务器，走一遍完整流程。

    python3 tests/test_all.py

不会真的发邮件，也不会动 ~/工具箱数据（用临时文件夹）。
"""
import email
import email.header
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import fake_smtp  # noqa: E402
import mailer  # noqa: E402
import sheets  # noqa: E402

SAMPLE = os.path.join(ROOT, '示例名单.xlsx')


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def decode(h):
    return str(email.header.make_header(email.header.decode_header(h or '')))


class Unit(unittest.TestCase):
    def test_render(self):
        cols = ['姓名', '公司', '邮箱']
        row = {'姓名': '张三', '公司': '', '邮箱': 'a@b.com'}
        self.assertEqual(mailer.render('{姓名}您好', row, cols)[0], '张三您好')
        self.assertEqual(mailer.render('｛姓名｝', row, cols)[0], '张三')
        self.assertEqual(mailer.render('{ 姓名 }', row, cols)[0], '张三')
        self.assertEqual(mailer.render('{公司|贵公司}', row, cols)[0], '贵公司')
        self.assertEqual(mailer.render('{{原样}}', row, cols)[0], '{原样}')
        _, err, warn = mailer.render('{公司}{职位}', row, cols)
        self.assertEqual(err, ['表格里没有「职位」这一列'])
        self.assertEqual(warn, ['「公司」是空的'])

    def test_addresses(self):
        self.assertEqual(mailer.parse_addresses('a@b.com；c@d.cn、 e@f.org')[0], ['a@b.com', 'c@d.cn', 'e@f.org'])
        self.assertEqual(mailer.parse_addresses('张三 <a@b.com>')[0], ['a@b.com'])
        self.assertTrue(mailer.parse_addresses('a＠b.com')[1])
        self.assertTrue(mailer.parse_addresses('abc')[1])
        self.assertTrue(mailer.parse_addresses('a@b')[1])
        self.assertEqual(mailer.parse_addresses('A@b.com, a@b.com')[0], ['A@b.com'])

    def test_attachments(self):
        files = [{'id': str(i), 'name': n, 'rel': n} for i, n in
                 enumerate(['张三.pdf', '张三丰.pdf', '李四_9月工资条.pdf', 'a[1].txt', 'sub/x.doc'])]
        cols = ['姓名', '附件']

        def names(rule, row):
            got, err, _ = mailer.match_attachments(rule, row, cols, files)
            return [f['name'] for f in got], err
        self.assertEqual(names('{姓名}', {'姓名': '张三'}), (['张三.pdf'], []))
        self.assertEqual(names('{姓名}*', {'姓名': '李四'}), (['李四_9月工资条.pdf'], []))
        self.assertEqual(names('{附件}', {'附件': 'a[1].txt; 张三.pdf'}), (['a[1].txt', '张三.pdf'], []))
        self.assertEqual(names('{姓名}', {'姓名': '王五'})[1], ['附件文件夹里找不到「王五」'])

    def test_attachment_subfolders(self):
        files = [{'id': str(i), 'name': n.split('/')[-1], 'rel': n} for i, n in
                 enumerate(['张三/工资条.pdf', '张三/照片.jpg', '李四/工资条.pdf'])]
        got, err, _ = mailer.match_attachments('{姓名}/*', {'姓名': '张三'}, ['姓名'], files)
        self.assertEqual([f['rel'] for f in got], ['张三/工资条.pdf', '张三/照片.jpg'])
        self.assertEqual(err, [])

    def test_file_types(self):
        self.assertEqual(mailer.guess_type('合同.DOCX'),
                         'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        self.assertEqual(mailer.guess_type('IMG_0001.HEIC'), 'image/heic')
        self.assertEqual(mailer.guess_type('照片.jpeg'), 'image/jpeg')
        self.assertEqual(mailer.guess_type('奇怪的文件.xyz123'), 'application/octet-stream')
        self.assertEqual(mailer.guess_type('a.tar.gz'), 'application/octet-stream')

    def test_csv(self):
        data = '姓名,邮箱\n张三,a@b.com\n\n李四,c@d.com\n'.encode('gbk')
        t = sheets.read_table('x.csv', data)
        self.assertEqual(t['columns'], ['姓名', '邮箱'])
        self.assertEqual([r['姓名'] for r in t['rows']], ['张三', '李四'])
        t = sheets.read_table('x.csv', '﻿姓名\t邮箱\n王五\te@f.com\n'.encode('utf-8'))
        self.assertEqual(t['rows'][0]['邮箱'], 'e@f.com')

    def test_sample_xlsx(self):
        with open(SAMPLE, 'rb') as f:
            t = sheets.read_table('示例名单.xlsx', f.read())
        self.assertIn('邮箱', t['columns'])
        self.assertTrue(t['rows'])

    def test_formats(self):
        f = sheets.format_value
        self.assertEqual(f(8500, '#,##0.00'), '8,500.00')
        self.assertEqual(f(2.675, '0.00'), '2.68')
        self.assertEqual(f(0.125, '0.0%'), '12.5%')
        self.assertEqual(f(-5, '¥#,##0.00'), '-¥5.00')
        self.assertEqual(f(46304, 'yyyy"年"m"月"d"日"'), '2026年10月9日')
        self.assertEqual(f(46304.5, 'yyyy/m/d h:mm'), '2026/10/9 12:00')
        self.assertEqual(f(13800138000, 'General'), '13800138000')

    def test_message(self):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, 'f')
        with open(p, 'wb') as fp:
            fp.write(b'%PDF-1.4 hello')
        data, _ = mailer.build_message('星光 科技', 'me@qq.com', ['a@b.com'], ['c@d.com'], '您好，张三', '正文\n第二行',
                                       [(p, '张三 9月工资条.pdf')])
        m = email.message_from_bytes(data)
        self.assertEqual(decode(m['Subject']), '您好，张三')
        self.assertIn('me@qq.com', m['From'])
        self.assertEqual(decode(email.utils.parseaddr(m['From'])[0]), '星光 科技')
        parts = list(m.walk())
        self.assertEqual(parts[1].get_payload(decode=True).decode('utf-8'), '正文\n第二行')
        self.assertEqual(decode(parts[2].get_param('filename', header='Content-Disposition')), '张三 9月工资条.pdf')
        self.assertEqual(parts[2].get_payload(decode=True), b'%PDF-1.4 hello')
        shutil.rmtree(tmp)


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.inbox = os.path.join(cls.tmp, 'inbox')
        cls.smtp_port = free_port()
        cls.smtp = fake_smtp.serve(cls.smtp_port, cls.inbox)
        threading.Thread(target=cls.smtp.serve_forever, daemon=True).start()
        # 假的 sips（Mac 自带的图片转换工具）：直接复制，用来测 HEIC 转 JPG 的流程
        bindir = os.path.join(cls.tmp, 'bin')
        os.makedirs(bindir)
        with open(os.path.join(bindir, 'sips'), 'w') as f:
            f.write('#!/bin/sh\n# sips -s format jpeg IN --out OUT\ncp "$4" "$6"\n')
        os.chmod(os.path.join(bindir, 'sips'), 0o755)
        env = dict(os.environ, TOOLBOX_DATA=os.path.join(cls.tmp, 'data'),
                   PATH=bindir + os.pathsep + os.environ.get('PATH', ''))
        cls.proc = subprocess.Popen([sys.executable, os.path.join(ROOT, 'app.py'), '--no-browser',
                                     '--port', str(free_port())], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        line = ''
        while 'http://' not in line:
            line = cls.proc.stdout.readline().decode()
            if not line and cls.proc.poll() is not None:
                raise RuntimeError('工具箱没启动起来')
        cls.base = line[line.index('http://'):].strip()
        html = urllib.request.urlopen(cls.base).read().decode()
        cls.token = html.split('name="token" content="')[1].split('"')[0]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait()
        cls.proc.stdout.close()
        cls.smtp.shutdown()
        cls.smtp.server_close()
        shutil.rmtree(cls.tmp)

    def setUp(self):
        # 每个测试从干净的状态开始
        self.call('/api/job', {'action': 'clear'})
        self.call('/api/remove_files', {'group': 'folder'})
        self.call('/api/remove_files', {'group': 'common'})
        self.call('/api/clear_table', {})

    def call(self, path, body=None, raw=None, query='', expect=200):
        url = self.base.rstrip('/') + path + (('?' + query) if query else '')
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(url, data=data, headers={'X-Token': self.token})
        try:
            with urllib.request.urlopen(req) as r:
                code, out = r.status, json.load(r)
        except urllib.error.HTTPError as e:
            code, out = e.code, json.load(e)
        self.assertEqual(code, expect, out)
        return out

    def login(self):
        self.call('/api/test_login', {'user': 'me@example.com', 'preset': 'custom', 'host': '127.0.0.1',
                                      'port': self.smtp_port, 'security': 'none', 'name': '', 'remember': False,
                                      'password': 'good-password'})

    def wait_job(self):
        for _ in range(200):
            job = self.call('/api/status')['job']
            if job['state'] in ('done', 'stopped', 'paused'):
                return job
            time.sleep(0.1)
        self.fail('发送一直没结束')

    def test_flow(self):
        # 没有 token 的请求被拒
        req = urllib.request.Request(self.base + 'api/init')
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(req)

        acct = {'user': 'me@example.com', 'preset': 'custom', 'host': '127.0.0.1', 'port': self.smtp_port,
                'security': 'none', 'name': '星光科技', 'remember': True}
        err = self.call('/api/test_login', dict(acct, user='other@example.com', password='wrong'), expect=400)
        self.assertIn('登录失败', err['error'])
        self.assertFalse(self.call('/api/init')['settings']['has_password'])  # 密码不对就不会被记住
        self.call('/api/test_login', dict(acct, password='good-password'))
        self.assertTrue(self.call('/api/init')['settings']['has_password'])

        csv_data = ('姓名,邮箱,金额\n张三,zhang@example.com,100\n李四,reject@example.com,200\n'
                    '王五,,300\n赵六,zhao@example.com,400\n张三,zhang@example.com,500\n').encode('utf-8')
        t = self.call('/api/upload_table', raw=csv_data, query='name=list.csv')
        self.assertEqual(len(t['rows']), 5)

        self.call('/api/upload_file', raw=b'common-file', query='group=common&name=%E8%AF%B4%E6%98%8E.txt')
        for n in ('张三.txt', '赵六.txt', '李四.txt'):
            self.call('/api/upload_file', raw=n.encode(), query='group=folder&name=%s&rel=folder/%s' % (
                urllib.parse.quote(n), urllib.parse.quote(n)))

        tpl = {'to': '{邮箱}', 'cc': '', 'bcc': '', 'subject': '{姓名}的通知', 'body': '{姓名}您好，金额 {金额} 元。',
               'rule': '{姓名}'}
        p = self.call('/api/preview', {'template': tpl})
        items = p['items']
        self.assertEqual(items[0]['body'], '张三您好，金额 100 元。')
        self.assertEqual([a['name'] for a in items[0]['attachments']], ['说明.txt', '张三.txt'])
        self.assertIn('收件人是空的', items[2]['errors'])
        self.assertTrue(any('第 6 行也出现了' in w for w in items[0]['warnings']))
        self.assertEqual(p['used'], ['邮箱', '姓名', '金额'])

        self.call('/api/test_send', {'template': tpl, 'index': 0})
        test_mail = email.message_from_bytes(open(sorted(glob.glob(self.inbox + '/*.eml'))[-1], 'rb').read())
        self.assertEqual(decode(test_mail['Subject']), '[测试] 张三的通知')
        self.assertIn('me@example.com', test_mail['X-Envelope-To'])

        # 发第 2、4、5 行之外的：张三(0)、李四(1, 地址会被拒)、赵六(3)
        self.call('/api/send', {'template': tpl, 'indexes': [0, 1, 3], 'interval': 0, 'bcc_self': True})
        job = self.wait_job()
        self.assertEqual(job['state'], 'done')
        st = [it['status'] for it in job['items']]
        self.assertEqual(st, ['sent', 'failed', 'sent'])
        self.assertIn('收件地址被拒', job['items'][1]['error'])
        self.assertTrue(os.path.exists(job['log']))
        with open(job['log'], encoding='utf-8-sig') as fp:
            log = fp.read()
        self.assertIn('zhao@example.com', log)
        last = email.message_from_bytes(open(sorted(glob.glob(self.inbox + '/*.eml'))[-1], 'rb').read())
        self.assertIn('me@example.com', last['X-Envelope-To'])  # 密送给自己
        self.assertNotIn('me@example.com', last['To'])

        # 发过的再预览会提醒
        p = self.call('/api/preview', {'template': tpl})
        self.assertTrue(p['items'][0]['sent_before'])
        self.assertFalse(p['items'][3]['sent_before'] is None)

        # 重发失败的
        job = self.call('/api/retry_failed', {})
        self.assertEqual(len(job['items']), 1)
        self.wait_job()

    def get_raw(self, path):
        with urllib.request.urlopen(self.base.rstrip('/') + path) as r:
            return r.status, r.headers.get('Content-Type'), r.read()

    def test_attachments_photos_and_documents(self):
        self.login()
        csv_data = '姓名,邮箱\n张三,a@example.com\n张三丰,b@example.com\n李四,c@example.com\n'.encode()
        self.call('/api/upload_table', raw=csv_data, query='name=l.csv')
        up = lambda name, group='folder': self.call('/api/upload_file', raw=b'data-' + name.encode(), query=(
            'group=%s&name=%s&rel=f/%s' % (group, urllib.parse.quote(name), urllib.parse.quote(name))))
        photo = up('IMG_0001.HEIC', 'common')
        self.assertEqual(photo['name'], 'IMG_0001.jpg')
        self.assertEqual(photo['converted_from'], 'IMG_0001.HEIC')
        self.assertTrue(photo['image'])
        for n in ('张三_合同.docx', '张三丰_合同.docx', '张叁_合同.docx'):
            up(n)
        tpl = {'to': '{邮箱}', 'subject': '合同', 'body': 'hi', 'rule': '{姓名}*'}
        p = self.call('/api/preview', {'template': tpl})
        zhang = p['items'][0]
        self.assertEqual([a['name'] for a in zhang['attachments']], ['IMG_0001.jpg', '张三_合同.docx', '张三丰_合同.docx'])
        self.assertTrue(any('也会发给第 3 行' in w for w in zhang['warnings']), zhang['warnings'])
        self.assertEqual(p['unused'], ['张叁_合同.docx'])
        self.assertIn('附件文件夹里找不到「李四*」', p['items'][2]['errors'])
        # 规则写成 {姓名}_* 就不会把张三丰的合同发给张三
        p = self.call('/api/preview', {'template': dict(tpl, rule='{姓名}_*')})
        self.assertEqual([a['name'] for a in p['items'][0]['attachments']], ['IMG_0001.jpg', '张三_合同.docx'])
        self.assertFalse(any('也会发给' in w for w in p['items'][0]['warnings']))
        # 预览里能打开附件；没有口令打不开
        status, ctype, data = self.get_raw('/api/file?id=%s&t=%s' % (photo['id'], self.token))
        self.assertEqual((status, ctype, data), (200, 'image/jpeg', b'data-IMG_0001.HEIC'))
        with self.assertRaises(urllib.error.HTTPError):
            self.get_raw('/api/file?id=%s&t=wrong' % photo['id'])
        # 发出去的邮件里，附件类型和名字都对
        self.call('/api/send', {'template': dict(tpl, rule='{姓名}_*'), 'indexes': [0], 'interval': 0})
        self.wait_job()
        msg = email.message_from_bytes(open(sorted(glob.glob(self.inbox + '/*.eml'))[-1], 'rb').read())
        parts = [(pt.get_content_type(), decode(pt.get_param('filename', header='Content-Disposition')))
                 for pt in msg.walk() if pt.get_param('filename', header='Content-Disposition')]
        self.assertEqual(parts, [('image/jpeg', 'IMG_0001.jpg'), (
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '张三_合同.docx')])
        self.call('/api/job', {'action': 'clear'})

    def source(self, name):
        with open(os.path.join(ROOT, '示例表格', name), 'rb') as f:
            return self.call('/api/source_upload', raw=f.read(), query='name=' + urllib.parse.quote(name))

    def download(self, d):
        status, ctype, data = self.get_raw('/api/download?id=%s&t=%s' % (d['id'], self.token))
        self.assertEqual(status, 200)
        return sheets.read_table(d['filename'], data)

    def test_tools_merge_split_send(self):
        # 合并：两个部门的工资表，标题行、合计行、列顺序不同、「名字」≠「姓名」
        a, b = self.source('销售部.xlsx'), self.source('技术部.xlsx')
        self.assertEqual((a['header_row'], a['total']), (2, 5))
        req = {'sources': [{'sid': a['sid']}, {'sid': b['sid']}], 'add_source': True, 'drop_totals': True}
        m = self.call('/api/merge', req)
        self.assertIn('名字', m['columns'])  # 没改名之前是两列
        m = self.call('/api/merge', dict(req, rename={'名字': '姓名'}, export=True))
        self.assertNotIn('名字', m['columns'])
        self.assertEqual((m['total'], m['removed_totals']), (7, 2))
        self.assertEqual([x['in'] for x in m['matrix'] if x['column'] == '备注'], [[False, True]])
        merged = self.download(m['download'])
        self.assertEqual(len(merged['rows']), 7)
        self.assertEqual(merged['rows'][4]['姓名'], '赵六')
        self.assertEqual(merged['rows'][0]['工资'], '8,500.00')
        self.assertEqual(sheets.cell_value(merged['rows'][0], merged['columns'], '工资'), (8500.0, '#,##0.00'))

        # 拆分：合并结果按姓名拆成每人一个文件
        src = {'sid': m['source']['sid']}
        p = self.call('/api/split', dict(src, column='姓名', name_tpl='{值}_9月工资条'))
        self.assertEqual(len(p['groups']), 7)
        self.assertEqual(p['groups'][0]['filename'], '张三_9月工资条.xlsx')
        out = self.call('/api/split', dict(src, column='姓名', name_tpl='{值}_9月工资条', export=True))
        self.assertEqual(len(os.listdir(out['folder'])), 7)
        one = sheets.read_table('x.xlsx', open(os.path.join(out['folder'], '李四_9月工资条.xlsx'), 'rb').read())
        self.assertEqual([r['工资'] for r in one['rows']], ['9,200.50'])
        sheets_mode = self.call('/api/split', dict(src, column='来源', mode='sheets', export=True))
        self.assertEqual(len(self.download(sheets_mode['download'])['sheets']), 2)

        # 拆好的工资条直接交给群发：名单用合并结果，附件按姓名对上
        r = self.call('/api/split_to_mail', {})
        self.assertEqual((r['rule'], r['count'], r['table_set']), ('{姓名}_9月工资条', 7, True))
        tpl = {'to': '{邮箱}', 'subject': '{姓名} 9 月工资条', 'body': '见附件', 'rule': r['rule']}
        items = self.call('/api/preview', {'template': tpl})['items']
        self.assertEqual([i['attachments'][0]['name'] for i in items][:2], ['张三_9月工资条.xlsx', '李四_9月工资条.xlsx'])
        self.assertFalse(any(i['errors'] for i in items))
        self.assertFalse(any('也会发给' in w for i in items for w in i['warnings']))  # 张三 和 张三丰 没混

    def test_tools_compare_then_remind(self):
        a, b = self.source('全员名单.xlsx'), self.source('已交材料.xlsx')
        req = {'a': {'sid': a['sid']}, 'b': {'sid': b['sid']}, 'key_a': '姓名', 'key_b': '名字', 'loose': True}
        r = self.call('/api/compare', dict(req, export=True))
        self.assertEqual([row[1] for row in r['only_a']], ['王五', '张三丰', '钱七', '孙八'])
        self.assertEqual([row[1] for row in r['only_b']], ['周九'])
        self.assertEqual([(d['key'], d['changes'][0]['column']) for d in r['diffs']], [('李四', '部门')])
        self.assertEqual(r['dup_b'], [{'key': '张三', 'rows': [2, 6]}])
        self.assertEqual(r['same'], 2)
        status, _, data = self.get_raw('/api/download?id=%s&t=%s' % (r['download']['id'], self.token))
        self.assertEqual(sheets.read_table('r.xlsx', data)['sheets'], ['汇总', '只在A里', '只在B里', '内容不同'])
        # 只比「部门」以外的列 → 没有不一样的
        r2 = self.call('/api/compare', dict(req, columns=[]))
        self.assertEqual(r2['n_diffs'], 0)
        # 没交的人直接做成群发名单
        m = self.call('/api/compare_to_mail', dict(req, which='a'))
        self.assertEqual(m['count'], 4)
        init = self.call('/api/init')
        self.assertTrue(init['table']['filename'].startswith('核对结果'))
        items = self.call('/api/preview', {'template': {'to': '{邮箱}', 'subject': '催一下', 'body': '{姓名}，记得交材料'}})['items']
        self.assertEqual([i['to'] for i in items], [['wangwu@example.com'], ['zhangsanfeng@example.com'],
                                                   ['qianqi@example.com'], ['sunba@example.com']])
        self.call('/api/select_sheet', {'sheet': 'x'}, expect=400)  # 核对结果不能换工作表

    def test_rate_limit_pauses(self):
        port = free_port()
        acct = {'user': 'me@example.com', 'preset': 'custom', 'host': '127.0.0.1', 'port': port,
                'security': 'none', 'name': '', 'remember': False}
        limited = fake_smtp.serve(port, os.path.join(self.tmp, 'limited'), limit=1)
        threading.Thread(target=limited.serve_forever, daemon=True).start()
        try:
            self.call('/api/test_login', dict(acct, password='good-password'))
            csv_data = '姓名,邮箱\n甲,a@example.com\n乙,b@example.com\n丙,c@example.com\n'.encode()
            self.call('/api/upload_table', raw=csv_data, query='name=l.csv')
            tpl = {'to': '{邮箱}', 'subject': '限流测试 {姓名}', 'body': 'hi', 'rule': ''}
            self.call('/api/send', {'template': tpl, 'indexes': [0, 1, 2], 'interval': 0})
            job = self.wait_job()
            self.assertEqual(job['state'], 'paused')
            self.assertIn('发得太多', job['message'])
            self.assertEqual([it['status'] for it in job['items']], ['sent', 'waiting', 'waiting'])
            limited.limit = None
            self.call('/api/job', {'action': 'resume'})
            time.sleep(0.3)
            job = self.wait_job()
            self.assertEqual([it['status'] for it in job['items']], ['sent', 'sent', 'sent'])
        finally:
            limited.shutdown()
            limited.server_close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
