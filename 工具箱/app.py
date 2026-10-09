"""工具箱：在自己电脑上运行的小程序，界面在浏览器里。

启动：双击「双击打开.command」，或者在终端里运行  python3 app.py
所有东西都只在这台电脑上：名单、附件、邮箱授权码都不会上传到别的地方，
邮件是直接从你的邮箱服务器发出去的。
"""
import csv
import datetime
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mailer  # noqa: E402
import sheets  # noqa: E402

APP_ID = 'toolbox-mail-v1'
PORTS = range(8765, 8776)
DATA_DIR = os.environ.get('TOOLBOX_DATA') or os.path.join(os.path.expanduser('~'), '工具箱数据')
RECORD_DIR = os.path.join(DATA_DIR, '发送记录')
TEMPLATE_DIR = os.path.join(DATA_DIR, '模板')
HISTORY_FILE = os.path.join(RECORD_DIR, '已发送.jsonl')
KEYCHAIN_SERVICE = 'toolbox-mail'
HISTORY_DAYS = 30


# ---------------------------------------------------------------- 存取小文件

def _ensure_dirs():
    for d in (DATA_DIR, RECORD_DIR, TEMPLATE_DIR):
        os.makedirs(d, exist_ok=True)


def load_json(name, default):
    try:
        with open(os.path.join(DATA_DIR, name), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(name, value):
    _ensure_dirs()
    path = os.path.join(DATA_DIR, name)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _safe_name(s, limit=40):
    s = re.sub(r'[\\/:*?"<>|\n\r\t]+', ' ', s).strip().strip('.')
    return s[:limit] or '未命名'


# ---------------------------------------------------------------- 授权码：存进 Mac 钥匙串

def password_get(account):
    if not account:
        return None
    if sys.platform == 'darwin':
        r = subprocess.run(['security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', account, '-w'],
                           capture_output=True, text=True)
        return r.stdout.rstrip('\n') if r.returncode == 0 else None
    return load_json('.password.json', {}).get(account)


def password_set(account, password):
    if sys.platform == 'darwin':
        r = subprocess.run(['security', 'add-generic-password', '-U', '-s', KEYCHAIN_SERVICE,
                            '-a', account, '-w', password], capture_output=True, text=True)
        return r.returncode == 0
    # 不是 Mac（比如开发测试时）：存在数据文件夹里，只有自己能读
    data = load_json('.password.json', {})
    data[account] = password
    save_json('.password.json', data)
    os.chmod(os.path.join(DATA_DIR, '.password.json'), 0o600)
    return True


def password_delete(account):
    if not account:
        return
    if sys.platform == 'darwin':
        subprocess.run(['security', 'delete-generic-password', '-s', KEYCHAIN_SERVICE, '-a', account],
                       capture_output=True, text=True)
    else:
        data = load_json('.password.json', {})
        if data.pop(account, None) is not None:
            save_json('.password.json', data)


# ---------------------------------------------------------------- 发送历史（防止重复发）

_history_lock = threading.Lock()


def history_add(addresses, subject, when):
    _ensure_dirs()
    line = json.dumps({'t': when, 'to': addresses, 'subject': subject}, ensure_ascii=False)
    with _history_lock, open(HISTORY_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def history_index():
    """{(邮箱小写, 主题): 最近一次发送时间}，只看最近 30 天。"""
    out = {}
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=HISTORY_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    try:
        with _history_lock, open(HISTORY_FILE, encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get('t', '') < cutoff:
            continue
        for a in rec.get('to', []):
            key = (a.lower(), rec.get('subject', ''))
            if rec['t'] > out.get(key, ''):
                out[key] = rec['t']
    return out


# ---------------------------------------------------------------- 当前状态

class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.tmpdir = tempfile.mkdtemp(prefix='toolbox-')
        self.table = None      # {'filename', 'data', 'sheets', 'sheet', 'columns', 'rows'}
        self.files = {}        # id -> {'id', 'group', 'name', 'rel', 'path', 'size'}
        self.password = None   # 这次运行里用的授权码（只在内存里）
        self.job = None
        self.last_job_args = None

    def settings(self):
        s = load_json('设置.json', {})
        s.setdefault('preset', 'qq')
        p = mailer.PRESETS.get(s['preset'], mailer.PRESETS['custom'])
        s.setdefault('host', p['host'])
        s.setdefault('port', p['port'])
        s.setdefault('security', p['security'])
        s.setdefault('user', '')
        s.setdefault('name', '')
        s.setdefault('remember', True)
        return s

    def smtp_config(self):
        cfg = dict(self.settings())
        cfg['password'] = self.password or password_get(cfg['user'])
        return cfg

    def files_in(self, group):
        return [f for f in self.files.values() if f['group'] == group]


STATE = State()


# ---------------------------------------------------------------- 把模板套到每一行

def prepare(template, row, columns, files_common, files_folder):
    """一封邮件的全部内容，以及发现的问题。"""
    errors, warnings = [], []

    def field(key):
        text, e, w = mailer.render(template.get(key, ''), row, columns)
        errors.extend(e)
        warnings.extend(w)
        return text

    to_text, cc_text, bcc_text = field('to'), field('cc'), field('bcc')
    subject, body = field('subject').strip(), field('body')
    to, e1 = mailer.parse_addresses(to_text)
    cc, e2 = mailer.parse_addresses(cc_text)
    bcc, e3 = mailer.parse_addresses(bcc_text)
    errors += e1 + e2 + e3
    if not to and not e1:
        errors.append('收件人是空的')
    if not subject:
        errors.append('主题是空的')
    picked, e4, w4 = mailer.match_attachments(template.get('rule', ''), row, columns, files_folder)
    errors += e4
    warnings += w4
    attachments = list(files_common) + [f for f in picked if f not in files_common]
    size = sum(f['size'] for f in attachments)
    if size > 18 * 1024 * 1024:
        warnings.append('附件一共 %.1f MB，可能超过邮箱的大小限制（一般 20 MB 左右）' % (size / 1048576))
    # 去掉重复的提醒
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    return {'row': row.get('_row'), 'to': to, 'cc': cc, 'bcc': bcc, 'subject': subject, 'body': body,
            'attachments': attachments, 'size': size, 'errors': errors, 'warnings': warnings}


def preview_all(template):
    with STATE.lock:
        table = STATE.table
        common, folder = STATE.files_in('common'), STATE.files_in('folder')
    if not table:
        return {'items': [], 'columns': []}
    columns = table['columns']
    items, seen = [], {}
    sent = history_index()
    for i, row in enumerate(table['rows']):
        it = prepare(template, row, columns, common, folder)
        it['index'] = i
        for a in it['to']:
            seen.setdefault(a.lower(), []).append(it['row'])
        hits = [sent[(a.lower(), it['subject'])] for a in it['to'] if (a.lower(), it['subject']) in sent]
        it['sent_before'] = max(hits) if hits else None
        if hits:
            it['warnings'].append('%s 已经给这个人发过同样主题的邮件' % max(hits)[5:16])
        items.append(it)
    for it in items:
        for a in it['to']:
            rows = seen[a.lower()]
            if len(rows) > 1:
                others = '、'.join(str(r) for r in rows if r != it['row'])
                it['warnings'].append('%s 在第 %s 行也出现了，会收到不止一封' % (a, others))
    return {'items': [_public_item(it) for it in items],
            'used': mailer.used_columns(' '.join(str(v) for v in template.values()), columns)}


def _public_item(it):
    out = dict(it)
    out['attachments'] = [{'name': f['name'], 'size': f['size']} for f in it['attachments']]
    return out


# ---------------------------------------------------------------- 发送任务

class Job(threading.Thread):
    def __init__(self, template, indexes, interval, bcc_self):
        threading.Thread.__init__(self, daemon=True)
        with STATE.lock:
            self.table = STATE.table
            self.common = STATE.files_in('common')
            self.folder = STATE.files_in('folder')
        self.template = template
        self.interval = max(0.0, float(interval))
        self.bcc_self = bcc_self
        self.state = 'running'      # running / paused / done / stopped
        self.message = ''
        self.stop_flag = False
        self.pause_flag = False
        self.cfg = STATE.smtp_config()
        rows = self.table['rows']
        self.items = []
        for i in indexes:
            if 0 <= i < len(rows):
                row = rows[i]
                pre = prepare(template, row, self.table['columns'], self.common, self.folder)
                self.items.append({'index': i, 'row': row.get('_row'), 'to': pre['to'], 'subject': pre['subject'],
                                   'status': 'waiting', 'error': '', 'time': ''})
        stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
        subj = self.items[0]['subject'] if self.items else ''
        self.log_path = os.path.join(RECORD_DIR, '%s_%s.csv' % (stamp, _safe_name(subj, 30)))
        self.started = time.time()
        self.caffeinate = None

    # 状态给网页看
    def snapshot(self):
        counts = {}
        for it in self.items:
            counts[it['status']] = counts.get(it['status'], 0) + 1
        return {'state': self.state, 'message': self.message, 'items': self.items, 'counts': counts,
                'total': len(self.items), 'log': self.log_path, 'interval': self.interval}

    def pause(self, message=''):
        self.pause_flag = True
        if message:
            self.message = message

    def resume(self):
        self.pause_flag = False
        self.message = ''

    def stop(self):
        self.stop_flag = True
        self.pause_flag = False

    def _log(self, it, cc, attachments):
        new = not os.path.exists(self.log_path)
        with open(self.log_path, 'a', encoding='utf-8-sig' if new else 'utf-8', newline='') as f:
            w = csv.writer(f)
            if new:
                w.writerow(['时间', '表格行号', '收件人', '抄送', '主题', '附件', '结果', '说明'])
            w.writerow([it['time'], it['row'], ', '.join(it['to']), ', '.join(cc), it['subject'],
                        ', '.join(attachments), {'sent': '成功', 'failed': '失败'}.get(it['status'], it['status']),
                        it['error']])

    def _keep_awake(self, on):
        if sys.platform != 'darwin':
            return
        if on and self.caffeinate is None:
            try:
                self.caffeinate = subprocess.Popen(['caffeinate', '-i', '-w', str(os.getpid())])
            except OSError:
                pass
        elif not on and self.caffeinate is not None:
            self.caffeinate.terminate()
            self.caffeinate = None

    def run(self):
        _ensure_dirs()
        self._keep_awake(True)
        sender = mailer.Sender(self.cfg)
        fails_in_row = 0
        try:
            k = 0
            while k < len(self.items):
                it = self.items[k]
                if self.pause_flag:
                    self.state = 'paused'
                    sender.close()
                    while self.pause_flag and not self.stop_flag:
                        time.sleep(0.2)
                    if not self.stop_flag:
                        self.cfg = STATE.smtp_config()  # 暂停期间可能改了授权码
                        sender = mailer.Sender(self.cfg)
                        fails_in_row = 0
                if self.stop_flag:
                    break
                self.state = 'running'
                it['status'] = 'sending'
                outcome = self._send_one(sender, it)
                if outcome == 'retry-later':
                    continue  # 已经暂停了，恢复后重发这一封
                if it['status'] == 'failed':
                    fails_in_row += 1
                    if fails_in_row >= 3:
                        self.pause('连着 %d 封都没发出去，先暂停了。看一下下面的出错原因，处理好再点「继续」。' % fails_in_row)
                else:
                    fails_in_row = 0
                k += 1
                if k < len(self.items) and not self.stop_flag and not self.pause_flag:
                    jitter = self.interval * random.uniform(-0.2, 0.2)
                    mailer.wait(self.interval + jitter, lambda: self.stop_flag or self.pause_flag)
            for it in self.items:
                if it['status'] in ('waiting', 'sending'):
                    it['status'] = 'skipped'
            self.state = 'stopped' if self.stop_flag else 'done'
        except Exception as e:  # noqa: BLE001 —— 万一有没想到的错误，也要让网页知道
            self.state = 'stopped'
            self.message = '程序出错停下了：%s' % e
            for it in self.items:
                if it['status'] in ('waiting', 'sending'):
                    it['status'] = 'skipped'
        finally:
            sender.close()
            self._keep_awake(False)

    def _send_one(self, sender, it):
        rows = self.table['rows']
        pre = prepare(self.template, rows[it['index']], self.table['columns'], self.common, self.folder)
        it['to'], it['subject'] = pre['to'], pre['subject']
        names = [f['name'] for f in pre['attachments']]
        it['time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if pre['errors']:
            it['status'], it['error'] = 'failed', '；'.join(pre['errors'])
            self._log(it, pre['cc'], names)
            return 'done'
        from_addr = self.cfg['user'].strip()
        rcpts = pre['to'] + pre['cc'] + pre['bcc'] + ([from_addr] if self.bcc_self else [])
        rcpts = list(dict.fromkeys(rcpts))
        last_err = None
        for attempt in (1, 2):
            try:
                data, _ = mailer.build_message(self.cfg.get('name', ''), from_addr, pre['to'], pre['cc'],
                                               pre['subject'], pre['body'],
                                               [(f['path'], f['name']) for f in pre['attachments']])
                refused = sender.send(from_addr, rcpts, data) or {}
                it['time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                bad = {a.lower() for a in refused}
                if all(a.lower() in bad for a in pre['to']):
                    # 收件人全被拒了（只有抄送或密送给自己的那份发出去了），这封算失败
                    it['status'] = 'failed'
                    it['error'] = '收件地址被拒绝，可能地址不存在或写错了：' + mailer.refused_text(refused)
                else:
                    it['status'] = 'sent'
                    it['error'] = ('发出去了，但这些地址被拒：' + mailer.refused_text(refused)) if refused else ''
                    history_add(pre['to'], pre['subject'], it['time'])
                self._log(it, pre['cc'], names)
                return 'done'
            except mailer.SendError as e:
                last_err = e
                if e.fatal:
                    break
                if e.temporary and attempt == 1:
                    mailer.wait(15, lambda: self.stop_flag)
                    if self.stop_flag:
                        break
                    continue
                break
            except OSError as e:
                last_err = mailer.SendError('读附件出错：%s' % e)
                break
        if last_err is not None and last_err.fatal and not self.stop_flag:
            # 登录失败、被限流这类：这封不算失败，暂停，等处理好了再从这封继续
            it['status'], it['error'] = 'waiting', ''
            self.pause(str(last_err))
            return 'retry-later'
        it['status'], it['error'] = 'failed', str(last_err) if last_err else '已停止'
        self._log(it, pre['cc'], names)
        return 'done'


def test_send(template, index):
    with STATE.lock:
        table = STATE.table
        common, folder = STATE.files_in('common'), STATE.files_in('folder')
    if not table or not (0 <= index < len(table['rows'])):
        raise mailer.SendError('先选好名单。')
    cfg = STATE.smtp_config()
    me = cfg['user'].strip()
    if not me or not cfg.get('password'):
        raise mailer.SendError('先在第 1 步填好发件邮箱和授权码。')
    pre = prepare(template, table['rows'][index], table['columns'], common, folder)
    if pre['errors']:
        raise mailer.SendError('这一封还有问题：' + '；'.join(pre['errors']))
    note = '【测试邮件】正式发送时，这封会发给：%s' % ', '.join(pre['to'])
    if pre['cc']:
        note += '；抄送：%s' % ', '.join(pre['cc'])
    if pre['bcc']:
        note += '；密送：%s' % ', '.join(pre['bcc'])
    data, _ = mailer.build_message(cfg.get('name', ''), me, [me], [], '[测试] ' + pre['subject'],
                                   note + '\n' + '-' * 30 + '\n\n' + pre['body'],
                                   [(f['path'], f['name']) for f in pre['attachments']])
    s = mailer.Sender(cfg)
    try:
        s.send(me, [me], data)
    finally:
        s.close()
    return me


# ---------------------------------------------------------------- 网页接口

TOKEN = secrets.token_urlsafe(24)
WEB = os.path.join(HERE, 'web')
STATIC = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'),
          '/app.js': ('app.js', 'application/javascript; charset=utf-8')}


def _table_summary(t):
    if not t:
        return None
    return {'filename': t['filename'], 'sheets': t['sheets'], 'sheet': t['sheet'],
            'columns': t['columns'], 'rows': t['rows']}


def _file_public(f):
    return {'id': f['id'], 'group': f['group'], 'name': f['name'], 'rel': f['rel'], 'size': f['size']}


def _settings_public():
    s = STATE.settings()
    s['has_password'] = bool(STATE.password or password_get(s['user']))
    return s


def api_init(_q, _b):
    with STATE.lock:
        job = STATE.job.snapshot() if STATE.job else None
        files = [_file_public(f) for f in STATE.files.values()]
        table = _table_summary(STATE.table)
    names = sorted(n[:-5] for n in os.listdir(TEMPLATE_DIR) if n.endswith('.json')) if os.path.isdir(TEMPLATE_DIR) else []
    presets = {k: {kk: v[kk] for kk in ('label', 'host', 'port', 'security', 'help', 'domains')}
               for k, v in mailer.PRESETS.items()}
    return {'settings': _settings_public(), 'presets': presets, 'draft': load_json('草稿.json', None),
            'templates': names, 'table': table, 'files': files, 'job': job, 'data_dir': DATA_DIR,
            'platform': sys.platform}


def _update_settings(b):
    """保存表单里的设置；返回 (设置, 新填的授权码或 None)。授权码先不存。"""
    s = STATE.settings()
    old_user = s['user']
    for k in ('preset', 'host', 'port', 'security', 'user', 'name', 'remember'):
        if k in b:
            s[k] = b[k]
    s['user'] = s['user'].strip()
    s['port'] = int(s['port'] or 0)
    save_json('设置.json', s)
    if s['user'] != old_user:
        STATE.password = None
    pw = b.get('password') or ''
    pw = re.sub(r'\s+', '', pw) if s['preset'] == 'gmail' else pw.strip()
    return s, (pw or None)


def api_test_login(_q, b):
    s, pw = _update_settings(b)
    cfg = STATE.smtp_config()
    if pw:
        cfg['password'] = pw
    if not cfg['user'] or not cfg.get('password'):
        raise mailer.SendError('邮箱地址和授权码都要填。')
    mailer.test_login(cfg)  # 登录不上会抛错，下面的就不执行了
    STATE.password = cfg['password']
    if s['remember']:
        if not password_set(s['user'], STATE.password):
            return {'ok': True, 'warning': '登录成功，但授权码没能存进钥匙串，下次打开要重新填。'}
    else:
        password_delete(s['user'])
    return {'ok': True}


def api_upload_table(q, body):
    name = q.get('name', 'list.xlsx')
    t = sheets.read_table(name, body)
    t['filename'], t['data'] = name, body
    with STATE.lock:
        STATE.table = t
    return _table_summary(t)


def api_select_sheet(_q, b):
    with STATE.lock:
        t = STATE.table
    if not t:
        raise sheets.SheetError('还没有选名单文件。')
    nt = sheets.read_table(t['filename'], t['data'], b.get('sheet'))
    nt['filename'], nt['data'] = t['filename'], t['data']
    with STATE.lock:
        STATE.table = nt
    return _table_summary(nt)


def api_clear_table(_q, _b):
    with STATE.lock:
        STATE.table = None
    return {'ok': True}


def api_upload_file(q, body):
    group = 'folder' if q.get('group') == 'folder' else 'common'
    name = os.path.basename(q.get('name') or 'file')
    rel = q.get('rel') or name
    if '/' in rel:
        rel = rel.split('/', 1)[1]  # 去掉最外层文件夹名
    fid = secrets.token_hex(8)
    folder = os.path.join(STATE.tmpdir, fid)
    os.makedirs(folder)
    path = os.path.join(folder, name)
    with open(path, 'wb') as f:
        f.write(body)
    info = {'id': fid, 'group': group, 'name': name, 'rel': rel, 'path': path, 'size': len(body)}
    with STATE.lock:
        STATE.files[fid] = info
    return _file_public(info)


def api_remove_files(_q, b):
    with STATE.lock:
        for fid in list(STATE.files):
            f = STATE.files[fid]
            if fid == b.get('id') or (b.get('group') and f['group'] == b['group']):
                shutil.rmtree(os.path.dirname(f['path']), ignore_errors=True)
                del STATE.files[fid]
        return {'files': [_file_public(f) for f in STATE.files.values()]}


def api_preview(_q, b):
    return preview_all(b.get('template') or {})


def api_test_send(_q, b):
    me = test_send(b.get('template') or {}, int(b.get('index', 0)))
    return {'ok': True, 'to': me}


def api_send(_q, b):
    with STATE.lock:
        if STATE.job and STATE.job.is_alive():
            raise mailer.SendError('上一批还在发送中。')
        if not STATE.table:
            raise mailer.SendError('先选好名单。')
        cfg = STATE.smtp_config()
        if not cfg['user'] or not cfg.get('password'):
            raise mailer.SendError('先在第 1 步填好发件邮箱和授权码。')
        args = (b.get('template') or {}, [int(i) for i in b.get('indexes', [])],
                float(b.get('interval', 5)), bool(b.get('bcc_self')))
        job = Job(*args)
        if not job.items:
            raise mailer.SendError('没有选中要发的邮件。')
        STATE.job, STATE.last_job_args = job, args
    job.start()
    return job.snapshot()


def api_status(_q, _b):
    with STATE.lock:
        return {'job': STATE.job.snapshot() if STATE.job else None}


def api_job(_q, b):
    with STATE.lock:
        job = STATE.job
    if not job:
        return {'job': None}
    action = b.get('action')
    if action == 'pause':
        job.pause('已暂停。')
    elif action == 'resume':
        job.resume()
    elif action == 'stop':
        job.stop()
    elif action == 'interval':
        job.interval = max(0.0, float(b.get('interval', job.interval)))
    elif action == 'clear' and not job.is_alive():
        with STATE.lock:
            STATE.job = None
        return {'job': None}
    return {'job': job.snapshot()}


def api_retry_failed(_q, _b):
    with STATE.lock:
        old = STATE.job
        if not old or old.is_alive():
            raise mailer.SendError('现在没有可以重发的。')
        failed = [it['index'] for it in old.items if it['status'] in ('failed', 'skipped')]
        if not failed:
            raise mailer.SendError('没有失败的邮件。')
        template, _, interval, bcc_self = STATE.last_job_args
        job = Job(template, failed, interval, bcc_self)
        STATE.job = job
    job.start()
    return job.snapshot()


def api_draft(_q, b):
    save_json('草稿.json', b.get('draft') or {})
    return {'ok': True}


def api_template_save(_q, b):
    name = _safe_name(b.get('name', ''))
    _ensure_dirs()
    with open(os.path.join(TEMPLATE_DIR, name + '.json'), 'w', encoding='utf-8') as f:
        json.dump(b.get('template') or {}, f, ensure_ascii=False, indent=2)
    return {'name': name}


def api_template_load(_q, b):
    path = os.path.join(TEMPLATE_DIR, _safe_name(b.get('name', '')) + '.json')
    with open(path, encoding='utf-8') as f:
        return {'template': json.load(f)}


def api_template_delete(_q, b):
    path = os.path.join(TEMPLATE_DIR, _safe_name(b.get('name', '')) + '.json')
    if os.path.exists(path):
        os.remove(path)
    return {'ok': True}


def api_open_folder(_q, b):
    _ensure_dirs()
    path = b.get('path') if b.get('path', '').startswith(DATA_DIR) else RECORD_DIR
    if os.path.isfile(path):
        cmd = ['open', '-R', path] if sys.platform == 'darwin' else ['xdg-open', os.path.dirname(path)]
    else:
        cmd = ['open' if sys.platform == 'darwin' else 'xdg-open', path]
    try:
        subprocess.Popen(cmd)
    except OSError:
        pass
    return {'ok': True, 'path': path}


def api_quit(_q, _b):
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return {'ok': True}


ROUTES = {
    ('GET', '/api/init'): api_init,
    ('GET', '/api/status'): api_status,
    ('POST', '/api/test_login'): api_test_login,
    ('POST', '/api/upload_table'): api_upload_table,
    ('POST', '/api/select_sheet'): api_select_sheet,
    ('POST', '/api/clear_table'): api_clear_table,
    ('POST', '/api/upload_file'): api_upload_file,
    ('POST', '/api/remove_files'): api_remove_files,
    ('POST', '/api/preview'): api_preview,
    ('POST', '/api/test_send'): api_test_send,
    ('POST', '/api/send'): api_send,
    ('POST', '/api/job'): api_job,
    ('POST', '/api/retry_failed'): api_retry_failed,
    ('POST', '/api/draft'): api_draft,
    ('POST', '/api/template_save'): api_template_save,
    ('POST', '/api/template_load'): api_template_load,
    ('POST', '/api/template_delete'): api_template_delete,
    ('POST', '/api/open_folder'): api_open_folder,
    ('POST', '/api/quit'): api_quit,
}
RAW_BODY = {'/api/upload_table', '/api/upload_file'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'Toolbox'

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
        return host in ('127.0.0.1', 'localhost')

    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')

    def _handle(self, method):
        url = urllib.parse.urlsplit(self.path)
        if not self._host_ok():
            return self._send(403, {'error': 'forbidden'})
        if method == 'GET' and url.path == '/api/ping':
            return self._send(200, {'app': APP_ID})
        if method == 'GET' and url.path in STATIC:
            fname, ctype = STATIC[url.path]
            with open(os.path.join(WEB, fname), 'rb') as f:
                data = f.read()
            if fname == 'index.html':
                data = data.replace(b'__TOKEN__', TOKEN.encode())
            return self._send(200, data, ctype)
        fn = ROUTES.get((method, url.path))
        if fn is None:
            return self._send(404, {'error': '没有这个地址'})
        # 只认本页面发来的请求，别的网页没法冒用
        if self.headers.get('X-Token') != TOKEN:
            return self._send(403, {'error': '页面过期了，请刷新一下。'})
        query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        try:
            if url.path in RAW_BODY:
                result = fn(query, raw)
            else:
                result = fn(query, json.loads(raw.decode('utf-8')) if raw else {})
            self._send(200, result)
        except (mailer.SendError, sheets.SheetError) as e:
            self._send(400, {'error': str(e)})
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._send(500, {'error': '程序出错了：%s' % e})


# ---------------------------------------------------------------- 启动

def _already_running(port):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/ping' % port, timeout=1) as r:
            return json.load(r).get('app') == APP_ID
    except Exception:  # noqa: BLE001
        return False


def main():
    _ensure_dirs()
    no_browser = '--no-browser' in sys.argv
    ports = PORTS
    if '--port' in sys.argv:  # 测试用：指定端口
        ports = [int(sys.argv[sys.argv.index('--port') + 1])]
    server = None
    for port in ports:
        if ports is PORTS and _already_running(port):
            url = 'http://127.0.0.1:%d/' % port
            print('工具箱已经开着了，直接在浏览器里打开：' + url)
            if not no_browser:
                webbrowser.open(url)
            return
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
            break
        except OSError:
            continue
    if server is None:
        print('找不到可用的端口（%d–%d 都被占用了）。' % (ports[0], ports[-1]))
        sys.exit(1)
    server.daemon_threads = True
    url = 'http://127.0.0.1:%d/' % server.server_address[1]
    print()
    print('  工具箱已经打开：' + url)
    print('  数据（发送记录、模板）存在：' + DATA_DIR)
    print()
    print('  用的时候不要关掉这个窗口；用完了直接关掉就行。')
    print()
    sys.stdout.flush()
    if not no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutil.rmtree(STATE.tmpdir, ignore_errors=True)


if __name__ == '__main__':
    main()
