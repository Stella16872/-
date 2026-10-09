"""邮件这一块：模板填空、检查收件地址、找附件、拼邮件、通过 SMTP 发出去。"""
import fnmatch
import mimetypes
import os
import re
import smtplib
import socket
import ssl
import time
import unicodedata
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from email.utils import formataddr, formatdate, make_msgid


# ---------------------------------------------------------------- 邮箱服务商

PRESETS = {
    'qq': {'label': 'QQ 邮箱', 'host': 'smtp.qq.com', 'port': 465, 'security': 'ssl',
           'domains': ['qq.com', 'foxmail.com', 'vip.qq.com'],
           'help': '用「授权码」登录，不是 QQ 密码。网页版 QQ 邮箱 → 设置 → 账号（新版界面在「账号与安全 → 安全设置」）'
                   '→ 开启「POP3/IMAP/SMTP 服务」，按提示生成授权码。'},
    'gmail': {'label': 'Gmail', 'host': 'smtp.gmail.com', 'port': 465, 'security': 'ssl',
              'domains': ['gmail.com', 'googlemail.com'],
              'help': '用「应用专用密码」（16 位字母），不是 Gmail 登录密码。要先在 Google 账号里开启'
                      '两步验证，再打开 myaccount.google.com/apppasswords 生成。'},
    '163': {'label': '网易 163 邮箱', 'host': 'smtp.163.com', 'port': 465, 'security': 'ssl',
            'domains': ['163.com'],
            'help': '用「授权码」登录。网页版 163 邮箱 → 设置 → POP3/SMTP/IMAP → 开启服务并生成授权码。'},
    '126': {'label': '网易 126 邮箱', 'host': 'smtp.126.com', 'port': 465, 'security': 'ssl',
            'domains': ['126.com'],
            'help': '用「授权码」登录。网页版 126 邮箱 → 设置 → POP3/SMTP/IMAP → 开启服务并生成授权码。'},
    'outlook': {'label': 'Outlook / Hotmail', 'host': 'smtp-mail.outlook.com', 'port': 587,
                'security': 'starttls', 'domains': ['outlook.com', 'hotmail.com', 'live.com', 'msn.com'],
                'help': '微软这几年在收紧第三方程序用密码登录，很可能登不上。登不上的话建议换 QQ 邮箱或 Gmail。'},
    'exmail': {'label': '腾讯企业邮', 'host': 'smtp.exmail.qq.com', 'port': 465, 'security': 'ssl',
               'domains': [], 'help': '一般用邮箱密码；如果开了安全登录，要用「客户端专用密码」。'},
    'aliyun': {'label': '阿里企业邮', 'host': 'smtp.qiye.aliyun.com', 'port': 465, 'security': 'ssl',
               'domains': [], 'help': '一般用邮箱密码；如果开了三方客户端安全密码，要用那个密码。'},
    'custom': {'label': '其他（手动填服务器）', 'host': '', 'port': 465, 'security': 'ssl',
               'domains': [], 'help': '服务器地址、端口一般在邮箱的「设置 → 客户端设置 / SMTP」里能找到。'},
}


def guess_preset(address):
    domain = address.rsplit('@', 1)[-1].strip().lower()
    for key, p in PRESETS.items():
        if domain in p['domains']:
            return key
    return None


# ---------------------------------------------------------------- 模板填空

# {列名} 或 {列名|空着时用的默认值}；全角的｛｝也认。{{ 和 }} 表示字面的花括号。
_PLACEHOLDER = re.compile(r'\{\{|\}\}|[{｛]([^{}｛｝\n]{1,80})[}｝]')


def _norm(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', s)).lower()


def find_column(name, columns):
    if name in columns:
        return name
    key = _norm(name)
    for c in columns:
        if _norm(c) == key:
            return c
    return None


def render(template, row, columns):
    """把模板里的 {列名} 换成这一行的值。返回 (结果, 错误列表, 提醒列表)。"""
    errors, warnings = [], []

    def sub(m):
        whole = m.group(0)
        if whole == '{{':
            return '{'
        if whole == '}}':
            return '}'
        inner = m.group(1)
        name, sep, default = inner.partition('|')
        col = find_column(name.strip(), columns)
        if col is None:
            errors.append('表格里没有「%s」这一列' % name.strip())
            return whole
        value = row.get(col, '')
        if not value.strip():
            if sep:
                return default
            warnings.append('「%s」是空的' % col)
        return value

    return _PLACEHOLDER.sub(sub, template or ''), errors, warnings


def used_columns(template, columns):
    out = []
    for m in _PLACEHOLDER.finditer(template or ''):
        if m.group(1):
            col = find_column(m.group(1).partition('|')[0].strip(), columns)
            if col and col not in out:
                out.append(col)
    return out


# ---------------------------------------------------------------- 收件地址

_EMAIL = re.compile(r"[A-Za-z0-9._%+'\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")


def parse_addresses(text):
    """从一格文字里找出所有邮箱。地址之间可以用逗号、分号、顿号、空格、换行隔开。

    返回 (地址列表, 错误列表)。
    """
    text = (text or '').strip()
    if not text:
        return [], []
    if '＠' in text:
        return [], ['「%s」里的 ＠ 是全角的，要改成半角 @' % text]
    found = _EMAIL.findall(text)
    rest = _EMAIL.sub(' ', text)
    if '@' in rest or not found:
        return found, ['「%s」不是有效的邮箱地址' % text]
    out = []
    for a in found:
        if a.lower() not in [x.lower() for x in out]:
            out.append(a)
    return out, []


# ---------------------------------------------------------------- 附件

def _nfc(s):
    return unicodedata.normalize('NFC', s)


def _glob_escape(s):
    return re.sub(r'([*?\[])', r'[\1]', s)


def match_attachments(rule_template, row, columns, files):
    """按「文件名规则」给这一行找附件。

    files: [{'id', 'name', 'rel'(文件夹里的相对路径)}]
    规则写法（多条用分号或换行隔开）：
      {姓名}          → 找文件名（去掉扩展名）正好是「张三」的文件，比如 张三.pdf
      {姓名}.pdf      → 正好叫 张三.pdf 的文件
      {姓名}*         → 以「张三」开头的所有文件，比如 张三_9月工资条.pdf
      {附件}          → 表格里「附件」那一列写的文件名
    返回 (匹配到的文件列表, 错误列表, 提醒列表)。
    """
    if not (rule_template or '').strip():
        return [], [], []
    # 先把列值换进去；值里的 * ? [ 当普通字符
    escaped_row = {k: (_glob_escape(v) if isinstance(v, str) else v) for k, v in row.items()}
    text, errors, warnings = render(rule_template, escaped_row, columns)
    if errors:
        return [], errors, []
    picked = []
    for pattern in re.split(r'[;；\n]+', text):
        pattern = _nfc(pattern.strip())
        if not pattern:
            continue
        has_glob = bool(re.search(r'(?<!\[)[*?](?!\])', pattern))
        plain = re.sub(r'\[([*?\[])\]', r'\1', pattern)
        hits = []
        for f in files:
            name, rel = _nfc(f['name']), _nfc(f.get('rel') or f['name'])
            target = rel if '/' in plain else name
            if has_glob:
                ok = fnmatch.fnmatch(target.lower(), pattern.lower())
            else:
                stem = os.path.splitext(target)[0]
                ok = target.lower() == plain.lower() or stem.lower() == plain.lower()
            if ok:
                hits.append(f)
        if not hits:
            errors.append('附件文件夹里找不到「%s」' % plain)
        for f in hits:
            if f not in picked:
                picked.append(f)
    return picked, errors, warnings


# ---------------------------------------------------------------- 拼邮件

def _encode_word(s):
    """附件名用 =?utf-8?b?...?= 这种写法，QQ 邮箱、Outlook、Gmail、苹果邮件都认。"""
    try:
        s.encode('ascii')
        return s
    except UnicodeEncodeError:
        return Header(s, 'utf-8').encode(maxlinelen=10000)


def build_message(sender_name, sender_addr, to, cc, subject, body, attachments):
    """attachments: [(文件路径, 显示的文件名)]。返回 (邮件字节, Message-ID)。"""
    if attachments:
        msg = MIMEMultipart('mixed')
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
    else:
        msg = MIMEText(body, 'plain', 'utf-8')
    msg['From'] = formataddr((Header(sender_name, 'utf-8').encode() if sender_name else '', sender_addr))
    msg['To'] = ', '.join(to)
    if cc:
        msg['Cc'] = ', '.join(cc)
    msg['Subject'] = Header(subject, 'utf-8')
    msg['Date'] = formatdate(localtime=True)
    domain = sender_addr.rsplit('@', 1)[-1] if '@' in sender_addr else None
    msgid = make_msgid(domain=domain)
    msg['Message-ID'] = msgid
    for path, filename in attachments:
        ctype, encoding = mimetypes.guess_type(filename)
        if ctype is None or encoding is not None:
            ctype = 'application/octet-stream'
        maintype, subtype = ctype.split('/', 1)
        part = MIMEBase(maintype, subtype)
        with open(path, 'rb') as fp:
            part.set_payload(fp.read())
        encoders.encode_base64(part)
        encoded = _encode_word(filename)
        part.set_param('name', encoded)
        part.add_header('Content-Disposition', 'attachment', filename=encoded)
        msg.attach(part)
    return msg.as_bytes(), msgid


# ---------------------------------------------------------------- SMTP

class SendError(Exception):
    """发送失败；message 是给人看的中文说明，temporary 表示过一会儿重试可能就好了。"""

    def __init__(self, message, temporary=False, fatal=False):
        Exception.__init__(self, message)
        self.temporary = temporary
        self.fatal = fatal  # 登录失败这类，后面的也不用试了


def _ssl_context():
    ctx = ssl.create_default_context()
    # python.org 装的 Python 有时没带根证书，Mac 系统自己有一份
    try:
        if not ctx.cert_store_stats().get('x509_ca') and os.path.exists('/etc/ssl/cert.pem'):
            ctx.load_verify_locations('/etc/ssl/cert.pem')
    except (ssl.SSLError, OSError):
        pass
    return ctx


class Sender:
    def __init__(self, cfg, timeout=30):
        self.cfg = cfg
        self.timeout = timeout
        self.conn = None

    def connect(self):
        c = self.cfg
        host, port, sec = c['host'].strip(), int(c['port']), c.get('security', 'ssl')
        try:
            if sec == 'ssl':
                conn = smtplib.SMTP_SSL(host, port, timeout=self.timeout, context=_ssl_context())
            else:
                conn = smtplib.SMTP(host, port, timeout=self.timeout)
                if sec == 'starttls':
                    conn.starttls(context=_ssl_context())
            if c.get('password'):
                conn.login(c['user'].strip(), c['password'])
        except Exception as e:  # noqa: BLE001 —— 所有错误都要翻译成人话
            raise explain(e, c)
        self.conn = conn

    def send(self, from_addr, rcpts, data):
        for attempt in (1, 2):
            if self.conn is None:
                self.connect()
            try:
                refused = self.conn.sendmail(from_addr, rcpts, data)
                return refused
            except (smtplib.SMTPServerDisconnected, ConnectionError, socket.timeout, ssl.SSLError) as e:
                self.close()
                if attempt == 2:
                    raise explain(e, self.cfg)
            except Exception as e:  # noqa: BLE001
                err = explain(e, self.cfg)
                if isinstance(e, (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError, smtplib.SMTPSenderRefused)):
                    # 被拒之后连接状态不确定，重新连比较稳
                    self.close()
                raise err

    def close(self):
        if self.conn is not None:
            try:
                self.conn.quit()
            except Exception:  # noqa: BLE001
                pass
            self.conn = None


def test_login(cfg):
    s = Sender(cfg, timeout=20)
    s.connect()
    s.close()


def _smtp_text(e):
    msg = getattr(e, 'smtp_error', b'')
    if isinstance(msg, bytes):
        msg = msg.decode('utf-8', 'replace')
    return msg or str(e)


def _looks_rate_limited(text):
    low = text.lower()
    if 'size' in low:  # "message size exceeds limit" 是太大，不是太快
        return False
    return any(k in low for k in ('frequen', 'limit', 'too many', 'spam', 'quota', '频率', '超限', '过多'))


def refused_text(refused):
    """sendmail 返回的 {地址: (代码, 原话)} 变成一句话。"""
    parts = []
    for addr, (code, text) in refused.items():
        if isinstance(text, bytes):
            text = text.decode('utf-8', 'replace')
        parts.append('%s（%s %s）' % (addr, code, text[:120]))
    return '；'.join(parts)


def explain(e, cfg):
    """把各种 SMTP / 网络错误翻译成中文说明。"""
    preset = cfg.get('preset', 'custom')
    if isinstance(e, SendError):
        return e
    if isinstance(e, smtplib.SMTPAuthenticationError):
        hint = {
            'qq': '登录失败。QQ 邮箱要用「授权码」，不是 QQ 密码；也确认一下已经开启了 SMTP 服务。',
            '163': '登录失败。163 邮箱要用「授权码」，不是登录密码；也确认一下已经开启了 SMTP 服务。',
            '126': '登录失败。126 邮箱要用「授权码」，不是登录密码；也确认一下已经开启了 SMTP 服务。',
            'gmail': '登录失败。Gmail 要用 16 位「应用专用密码」，不是登录密码；没开两步验证的话生成不了这个密码。',
            'outlook': '登录失败。微软很可能已经不允许这种方式登录了，建议换 QQ 邮箱或 Gmail。',
        }.get(preset, '登录失败：邮箱地址或密码 / 授权码不对。')
        return SendError(hint + '（服务器原话：%s）' % _smtp_text(e)[:200], fatal=True)
    if isinstance(e, smtplib.SMTPNotSupportedError) or (
            isinstance(e, smtplib.SMTPException) and 'AUTH' in str(e) and 'not supported' in str(e)):
        return SendError('服务器不接受这种登录方式，检查一下端口和加密方式。', fatal=True)
    if isinstance(e, socket.gaierror):
        return SendError('找不到服务器「%s」。检查一下网络，或者服务器地址是不是写错了。' % cfg.get('host'),
                         temporary=True, fatal=True)
    if isinstance(e, ssl.SSLCertVerificationError):
        return SendError('服务器证书验证失败。如果开着代理 / 梯子，先关掉再试。（%s）' % e, fatal=True)
    if isinstance(e, ssl.SSLError):
        return SendError('加密连接没建立起来：端口和加密方式可能不匹配（465 配 SSL，587 配 STARTTLS）。（%s）' % e,
                         fatal=True)
    if isinstance(e, (socket.timeout, TimeoutError)):
        return SendError('连接服务器超时。检查网络；公司网络或代理有时会拦邮件端口。', temporary=True)
    if isinstance(e, ConnectionRefusedError):
        return SendError('服务器拒绝连接：端口可能不对。', fatal=True)
    if isinstance(e, (smtplib.SMTPServerDisconnected, ConnectionError)):
        return SendError('和服务器的连接断了。（%s）' % e, temporary=True)
    if isinstance(e, smtplib.SMTPResponseException) and _looks_rate_limited(_smtp_text(e)):
        return SendError('邮箱提示发得太多或太快，可能触发了限制。先停一停，过一阵再发，并把间隔调大。（服务器原话：%s）'
                         % _smtp_text(e)[:200], temporary=True, fatal=True)
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return SendError('收件地址被拒绝，可能地址不存在或写错了：' + refused_text(e.recipients))
    if isinstance(e, smtplib.SMTPSenderRefused):
        return SendError('发件人地址被拒绝：发件邮箱必须和登录的邮箱一致。（服务器原话：%s）' % _smtp_text(e)[:200],
                         fatal=True)
    if isinstance(e, smtplib.SMTPResponseException):
        text = _smtp_text(e)
        low = text.lower()
        if e.smtp_code == 552 or 'size' in low and 'exceed' in low:
            return SendError('邮件太大了，附件超过了邮箱的大小限制。（%s）' % text[:200])
        return SendError('服务器拒绝了这封邮件（%s %s）' % (e.smtp_code, text[:200]),
                         temporary=400 <= e.smtp_code < 500)
    if isinstance(e, OSError):
        return SendError('网络出错了：%s' % e, temporary=True)
    return SendError('出错了：%s' % e)


def wait(seconds, should_stop):
    """睡一会儿，但是能被「停止」打断。"""
    end = time.time() + seconds
    while time.time() < end:
        if should_stop():
            return
        time.sleep(min(0.2, end - time.time()) if end > time.time() else 0)
