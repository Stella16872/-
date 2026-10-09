"""测试用的假邮件服务器：收到的邮件存进一个文件夹，不会真的发出去。

    python3 tests/fake_smtp.py 端口 存邮件的文件夹 [--limit N]

登录：任何用户名，密码必须是 good-password。
收件地址里带 reject 的会被拒；--limit N 表示收满 N 封以后开始报「发送频率超限」。
"""
import base64
import os
import socketserver
import sys

PASSWORD = 'good-password'


class Handler(socketserver.StreamRequestHandler):
    def reply(self, line):
        self.wfile.write((line + '\r\n').encode())

    def handle(self):
        srv = self.server
        self.reply('220 fake ESMTP ready')
        authed, rcpts, mail_from = False, [], None
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode('utf-8', 'replace').rstrip('\r\n')
            cmd = line.split(' ', 1)[0].upper()
            arg = line[len(cmd):].strip()
            if cmd in ('EHLO', 'HELO'):
                self.wfile.write(b'250-fake\r\n250-AUTH PLAIN LOGIN\r\n250 SIZE 10485760\r\n')
            elif cmd == 'AUTH':
                parts = arg.split()
                if parts[0].upper() == 'PLAIN':
                    if len(parts) > 1:
                        data = parts[1]
                    else:
                        self.reply('334 ')
                        data = self.rfile.readline().decode().strip()
                    pw = base64.b64decode(data).split(b'\0')[-1].decode()
                else:
                    self.reply('334 VXNlcm5hbWU6')
                    self.rfile.readline()
                    self.reply('334 UGFzc3dvcmQ6')
                    pw = base64.b64decode(self.rfile.readline().strip()).decode()
                if pw == PASSWORD:
                    authed = True
                    self.reply('235 ok')
                else:
                    self.reply('535 Login fail. Please enter your authorization code to login.')
            elif cmd == 'MAIL':
                if not authed:
                    self.reply('530 need auth')
                    continue
                if srv.limit is not None and srv.count >= srv.limit:
                    self.reply('550 Mail sending frequency limited, please retry later.')
                    continue
                mail_from, rcpts = arg, []
                self.reply('250 ok')
            elif cmd == 'RCPT':
                if 'reject' in arg.lower():
                    self.reply('550 Mailbox not found or access denied')
                else:
                    rcpts.append(arg)
                    self.reply('250 ok')
            elif cmd == 'DATA':
                if not rcpts:
                    self.reply('503 no valid recipients')
                    continue
                self.reply('354 go ahead')
                buf = []
                while True:
                    l = self.rfile.readline()
                    if l in (b'.\r\n', b'.\n', b''):
                        break
                    buf.append(l[1:] if l.startswith(b'..') else l)
                srv.count += 1
                name = os.path.join(srv.outdir, '%04d.eml' % srv.count)
                with open(name, 'wb') as f:
                    f.write(('X-Envelope-From: %s\r\nX-Envelope-To: %s\r\n' % (mail_from, ' '.join(rcpts))).encode())
                    f.write(b''.join(buf))
                self.reply('250 queued')
            elif cmd == 'RSET':
                rcpts, mail_from = [], None
                self.reply('250 ok')
            elif cmd == 'NOOP':
                self.reply('250 ok')
            elif cmd == 'QUIT':
                self.reply('221 bye')
                return
            else:
                self.reply('502 unknown')


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(port, outdir, limit=None):
    os.makedirs(outdir, exist_ok=True)
    srv = Server(('127.0.0.1', port), Handler)
    srv.outdir, srv.limit, srv.count = outdir, limit, 0
    return srv


if __name__ == '__main__':
    lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
    serve(int(sys.argv[1]), sys.argv[2], lim).serve_forever()
