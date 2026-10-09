'use strict';
(function () {
  var TOKEN = document.querySelector('meta[name=token]').content;
  var $ = function (id) { return document.getElementById(id); };

  // 当前页面的状态
  var S = {
    settings: null, presets: {}, table: null, files: [], preview: null,
    cur: 0, excluded: {}, filter: 'all', job: null, lastField: null, templates: [],
    editingAcct: false
  };

  // ------------------------------------------------------------ 小工具
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function size(n) {
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(0) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }
  function api(path, body) {
    var opt = { method: body === undefined ? 'GET' : 'POST', headers: { 'X-Token': TOKEN } };
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    return fetch(path, opt).then(handle, offline);
  }
  function upload(path, params, blob) {
    var q = Object.keys(params).map(function (k) { return k + '=' + encodeURIComponent(params[k]); }).join('&');
    return fetch(path + '?' + q, { method: 'POST', headers: { 'X-Token': TOKEN }, body: blob }).then(handle, function () {
      throw new Error('读不了文件「' + params.name + '」。如果它在 iCloud 云盘里，先在访达里右键选「立即下载」，再选一次。' +
        '（也可能是工具箱的终端窗口被关掉了。）');
    });
  }
  function handle(r) {
    return r.json().catch(function () { return {}; }).then(function (d) {
      if (!r.ok) throw new Error(d.error || ('出错了（' + r.status + '）'));
      return d;
    });
  }
  function offline() {
    throw new Error('连不上工具箱了。终端窗口是不是被关掉了？重新双击「双击打开.command」就好。');
  }
  var toastTimer;
  function toast(msg, bad) {
    var t = $('toast');
    t.textContent = msg; t.className = 'toast show' + (bad ? ' bad' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.className = 'toast' + (bad ? ' bad' : ''); }, bad ? 5000 : 2600);
  }
  function fail(e) { toast(e.message || String(e), true); }
  function debounce(fn, ms) {
    var t; return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }
  function dialog(title, html, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var d = $('dlg');
      $('dlgTitle').textContent = title;
      $('dlgBody').innerHTML = html;
      $('dlgInput').hidden = !opts.input;
      $('dlgInput').value = opts.value || '';
      $('dlgOk').textContent = opts.ok || '确定';
      $('dlgCancel').hidden = !!opts.alert;
      d.returnValue = '';
      $('dlgCancel').onclick = function () { d.close('cancel'); };
      d.onclose = function () {
        resolve(d.returnValue === 'ok' ? (opts.input ? $('dlgInput').value.trim() : true) : null);
      };
      d.showModal();
      if (opts.input) { $('dlgInput').focus(); $('dlgInput').select(); }
    });
  }
  function msg(el, text, kind) { el.textContent = text || ''; el.className = 'status-line' + (kind ? ' ' + kind : ''); }

  // ------------------------------------------------------------ 1 发件邮箱
  function fillPresets() {
    var sel = $('fPreset');
    sel.innerHTML = Object.keys(S.presets).map(function (k) {
      return '<option value="' + k + '">' + esc(S.presets[k].label) + '</option>';
    }).join('');
  }
  function guessPreset(addr) {
    var dom = (addr.split('@')[1] || '').toLowerCase().trim();
    for (var k in S.presets) if (S.presets[k].domains.indexOf(dom) >= 0) return k;
    return null;
  }
  function applyPreset(k, keepServer) {
    var p = S.presets[k] || S.presets.custom;
    $('presetHelp').textContent = p.help;
    $('pwLabel').textContent = k === 'gmail' ? '应用专用密码' : (k === 'qq' || k === '163' || k === '126') ? '授权码' : '密码 / 授权码';
    if (!keepServer) { $('fHost').value = p.host; $('fPort').value = p.port; $('fSec').value = p.security; }
    if (k === 'custom') $('fHost').closest('details').open = true;
  }
  function renderAcct() {
    var s = S.settings, done = s.user && s.has_password;
    $('s1').classList.toggle('done', !!done);
    var editing = !done || S.editingAcct;
    $('acctForm').hidden = !editing;
    $('cancelAcct').hidden = !(done && S.editingAcct);
    if (done) {
      var label = (S.presets[s.preset] || {}).label || '';
      $('acctSummary').innerHTML = '<span class="acct"><span class="dot"></span>' + esc(s.user) +
        '<span class="muted">' + esc(label) + '</span>' +
        (editing ? '' : '<button class="ghost small" id="editAcct">修改</button>') + '</span>';
      var b = $('editAcct');
      if (b) b.onclick = function () { S.editingAcct = true; fillAcctForm(); renderAcct(); };
    } else {
      $('acctSummary').innerHTML = '';
    }
  }
  function fillAcctForm() {
    var s = S.settings;
    $('fUser').value = s.user || '';
    $('fPreset').value = s.preset || 'qq';
    $('fName').value = s.name || '';
    $('fRemember').checked = s.remember !== false;
    $('fHost').value = s.host || ''; $('fPort').value = s.port || ''; $('fSec').value = s.security || 'ssl';
    $('fPass').value = '';
    $('fPass').placeholder = s.has_password ? '已经存好了（要换才需要重新填）' : '';
    applyPreset($('fPreset').value, true);
  }
  function acctPayload() {
    return {
      user: $('fUser').value.trim(), preset: $('fPreset').value, name: $('fName').value.trim(),
      remember: $('fRemember').checked, host: $('fHost').value.trim(), port: parseInt($('fPort').value, 10) || 0,
      security: $('fSec').value, password: $('fPass').value
    };
  }
  function bindAcct() {
    $('fUser').addEventListener('change', function () {
      var k = guessPreset(this.value);
      if (k && k !== $('fPreset').value) { $('fPreset').value = k; applyPreset(k); }
    });
    $('fPreset').addEventListener('change', function () { applyPreset(this.value); });
    $('loginBtn').onclick = function () {
      var p = acctPayload();
      if (!p.user || p.user.indexOf('@') < 0) return msg($('loginMsg'), '先填邮箱地址。', 'bad');
      if (!p.password && !S.settings.has_password) return msg($('loginMsg'), '授权码要填。', 'bad');
      if (!p.host) return msg($('loginMsg'), '服务器地址要填（在「服务器设置」里）。', 'bad');
      msg($('loginMsg'), '正在登录…');
      $('loginBtn').disabled = true;
      var warning = '';
      api('/api/test_login', p).then(function (r) {
        warning = r.warning || '';
        return api('/api/init');
      }).then(function (d) {
        S.settings = d.settings; S.editingAcct = false;
        renderAcct(); msg($('loginMsg'), '');
        toast(warning || '登录成功，邮箱设置好了', !!warning);
        updateSend();
      }).catch(function (e) {
        msg($('loginMsg'), e.message, 'bad');
        api('/api/init').then(function (d) { S.settings = d.settings; });
      }).then(function () { $('loginBtn').disabled = false; });
    };
    $('cancelAcct').onclick = function () { S.editingAcct = false; renderAcct(); msg($('loginMsg'), ''); };
  }

  // ------------------------------------------------------------ 2 名单
  function loadTableFile(file) {
    if (!file) return;
    $('tableSide').innerHTML = '<span class="muted small">正在读取…</span>';
    upload('/api/upload_table', { name: file.name }, file).then(function (t) {
      S.excluded = {}; S.cur = 0;
      setTable(t, true);
    }).catch(function (e) { $('tableSide').innerHTML = ''; fail(e); });
  }
  function emailColumn(cols, rows) {
    var re = /邮箱|邮件|e-?mail|mail/i;
    for (var i = 0; i < cols.length; i++) if (re.test(cols[i])) return cols[i];
    var best = null, bestN = 0;
    cols.forEach(function (c) {
      var n = rows.slice(0, 30).filter(function (r) { return /\S+@\S+\.\S+/.test(r[c]); }).length;
      if (n > bestN) { best = c; bestN = n; }
    });
    return best;
  }
  function setTable(t, fresh) {
    S.table = t;
    if (!t) {
      $('drop').hidden = false; $('tableView').hidden = true; $('tableSide').innerHTML = '';
      $('s2').classList.remove('done'); renderVars(); refreshPreview(); return;
    }
    $('drop').hidden = true; $('tableView').hidden = false; $('s2').classList.add('done');
    $('tableSide').innerHTML = '';
    $('tableName').textContent = t.filename;
    $('tableCount').textContent = '共 ' + t.rows.length + ' 行';
    $('sheetWrap').hidden = t.sheets.length < 2;
    $('sheetSel').innerHTML = t.sheets.map(function (n) {
      return '<option' + (n === t.sheet ? ' selected' : '') + '>' + esc(n) + '</option>';
    }).join('');
    renderTable();
    // 收件人没填、或者填的列这张表里没有：自动用邮箱那一列
    var to = $('tTo').value.trim();
    var m = /^\{([^{}]+)\}$/.exec(to);
    if (!to || (m && t.columns.indexOf(m[1]) < 0 && fresh)) {
      var col = emailColumn(t.columns, t.rows);
      if (col) { $('tTo').value = '{' + col + '}'; saveDraft(); }
    }
    renderVars();
    refreshPreview();
  }
  function renderTable() {
    var t = S.table, used = (S.preview && S.preview.used) || [];
    var show = t.rows.slice(0, 50);
    var h = '<thead><tr><th class="rn">行</th>' + t.columns.map(function (c) {
      return '<th' + (used.indexOf(c) >= 0 ? ' class="used"' : '') + '>' + esc(c) + '</th>';
    }).join('') + '</tr></thead><tbody>';
    show.forEach(function (r) {
      h += '<tr><td class="rn">' + r._row + '</td>' + t.columns.map(function (c) {
        return '<td title="' + esc(r[c]) + '">' + esc(r[c]) + '</td>';
      }).join('') + '</tr>';
    });
    $('tableData').innerHTML = h + '</tbody>';
    $('tableMore').textContent = t.rows.length > show.length ? '只显示了前 50 行，其余 ' + (t.rows.length - show.length) + ' 行一样会处理。' : '';
  }
  function bindTable() {
    var drop = $('drop');
    $('tableInput').onchange = function () { loadTableFile(this.files[0]); this.value = ''; };
    ['dragenter', 'dragover'].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); });
    });
    drop.addEventListener('drop', function (e) { loadTableFile(e.dataTransfer.files[0]); });
    // 拖到页面其他地方，不要让浏览器把文件打开
    window.addEventListener('dragover', function (e) { e.preventDefault(); });
    window.addEventListener('drop', function (e) { e.preventDefault(); });
    $('tableChange').onclick = function () { $('tableInput').click(); };
    $('sheetSel').onchange = function () {
      api('/api/select_sheet', { sheet: this.value }).then(function (t) { S.excluded = {}; S.cur = 0; setTable(t, true); }).catch(fail);
    };
  }

  // ------------------------------------------------------------ 3 写邮件
  var FIELDS = ['tTo', 'tCc', 'tBcc', 'tSubject', 'tBody', 'tRule'];
  function template() {
    var t = {};
    FIELDS.forEach(function (id) { var el = $(id); t[el.dataset.key] = el.value; });
    return t;
  }
  function setTemplate(t) {
    t = t || {};
    FIELDS.forEach(function (id) { var el = $(id); el.value = t[el.dataset.key] || ''; });
    if (t.cc || t.bcc) showCc();
  }
  function showCc() { $('ccRow').hidden = false; $('ccToggle').hidden = true; }
  function renderVars() {
    var box = $('vars');
    if (!S.table) {
      box.innerHTML = '<span class="muted">先在第 2 步选名单，这里会出现表格里的列，点一下就能插入到光标的位置。</span>';
      return;
    }
    var used = (S.preview && S.preview.used) || [];
    box.innerHTML = '<span class="muted">点一下插入：</span>' + S.table.columns.map(function (c) {
      return '<button class="var' + (used.indexOf(c) >= 0 ? ' used' : '') + '" data-col="' + esc(c) + '">{' + esc(c) + '}</button>';
    }).join('');
  }
  function insertVar(col) {
    var el = S.lastField || $('tBody');
    var text = '{' + col + '}';
    var a = el.selectionStart == null ? el.value.length : el.selectionStart;
    var b = el.selectionEnd == null ? a : el.selectionEnd;
    el.focus();
    el.value = el.value.slice(0, a) + text + el.value.slice(b);
    el.selectionStart = el.selectionEnd = a + text.length;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }
  // 中文输入法下 { 会变成「，提醒一下
  function braceHint() {
    var hint = $('braceHint');
    if (!S.table) { hint.hidden = true; return; }
    var all = FIELDS.map(function (id) { return $(id).value; }).join('\n');
    var re = /[「【\[〔]([^」】\]〕\n]{1,30})[」】\]〕]/g, m, found = [];
    while ((m = re.exec(all))) {
      var name = m[1].trim();
      if (S.table.columns.indexOf(name) >= 0 && found.indexOf(m[0]) < 0) found.push(m[0]);
    }
    hint.hidden = !found.length;
    if (found.length) {
      hint.textContent = '注意：' + found.join('、') + ' 不会被替换。要用英文花括号，比如 {' +
        /^.(.*).$/.exec(found[0])[1] + '}。中文输入法下打不出来的话，点上面的按钮插入就行。';
    }
  }
  var saveDraft = debounce(function () {
    api('/api/draft', {
      draft: {
        template: template(), interval: $('interval').value, bcc_self: $('bccSelf').checked
      }
    }).catch(function () {});
  }, 600);
  var refreshPreview = debounce(doPreview, 350);

  function renderFiles() {
    var common = S.files.filter(function (f) { return f.group === 'common'; });
    var folder = S.files.filter(function (f) { return f.group === 'folder'; });
    $('commonList').innerHTML = common.map(function (f) {
      return '<span class="chip">' + esc(f.name) + ' <span class="size">' + size(f.size) +
        '</span><button class="x" data-id="' + f.id + '" title="去掉">×</button></span>';
    }).join('');
    if (folder.length) {
      var total = folder.reduce(function (s, f) { return s + f.size; }, 0);
      $('folderInfo').textContent = '已选 ' + folder.length + ' 个文件（' + size(total) + '）';
      $('folderClear').hidden = false;
    } else {
      $('folderInfo').textContent = '还没选';
      $('folderClear').hidden = true;
    }
  }
  function uploadMany(list, group, progress) {
    var i = 0, out = [];
    function next() {
      if (i >= list.length) return Promise.resolve(out);
      var f = list[i++];
      progress && progress(i, list.length);
      return upload('/api/upload_file', { group: group, name: f.name, rel: f.webkitRelativePath || f.name }, f)
        .then(function (info) { out.push(info); return next(); });
    }
    return next();
  }
  function skipFile(f) {
    var n = f.name;
    return n.charAt(0) === '.' || n.indexOf('~$') === 0 || n === 'Thumbs.db' || n === 'desktop.ini';
  }
  function bindCompose() {
    FIELDS.forEach(function (id) {
      var el = $(id);
      el.addEventListener('focus', function () { S.lastField = el; });
      el.addEventListener('input', function () { saveDraft(); refreshPreview(); braceHint(); });
    });
    $('vars').addEventListener('mousedown', function (e) {
      var b = e.target.closest('.var'); if (!b) return;
      e.preventDefault(); insertVar(b.dataset.col);
    });
    $('ccShow').onclick = showCc;

    $('commonAdd').onclick = function () { $('commonInput').click(); };
    $('commonInput').onchange = function () {
      var list = Array.prototype.slice.call(this.files); this.value = '';
      uploadMany(list, 'common').then(function (added) {
        S.files = S.files.concat(added); renderFiles(); refreshPreview();
      }).catch(fail);
    };
    $('commonList').addEventListener('click', function (e) {
      var b = e.target.closest('.x'); if (!b) return;
      api('/api/remove_files', { id: b.dataset.id }).then(function (d) { S.files = d.files; renderFiles(); refreshPreview(); }).catch(fail);
    });
    $('folderAdd').onclick = function () { $('folderInput').click(); };
    $('folderInput').onchange = function () {
      var list = Array.prototype.slice.call(this.files).filter(function (f) { return !skipFile(f); });
      this.value = '';
      if (!list.length) return toast('这个文件夹里没有文件', true);
      api('/api/remove_files', { group: 'folder' }).then(function (d) {
        S.files = d.files;
        return uploadMany(list, 'folder', function (i, n) { $('folderInfo').textContent = '正在读取 ' + i + ' / ' + n + '…'; });
      }).then(function (added) {
        S.files = S.files.concat(added); renderFiles();
        if (!$('tRule').value.trim() && S.table) {
          var nameCol = S.table.columns.filter(function (c) { return /姓名|名字|name/i.test(c); })[0];
          if (nameCol) { $('tRule').value = '{' + nameCol + '}'; saveDraft(); }
        }
        refreshPreview();
      }).catch(function (e) { renderFiles(); fail(e); });
    };
    $('folderClear').onclick = function () {
      api('/api/remove_files', { group: 'folder' }).then(function (d) { S.files = d.files; renderFiles(); refreshPreview(); }).catch(fail);
    };

    // 模板
    $('tplSave').onclick = function () {
      var cur = $('tplSel').value;
      dialog('存为模板', '给这个模板起个名字。以后在「载入模板」里选它，主题、正文、收件人和附件规则都会填回来（附件文件本身不会存）。',
        { input: true, value: cur || $('tSubject').value.slice(0, 20), ok: '保存' }).then(function (name) {
        if (!name) return;
        return api('/api/template_save', { name: name, template: template() }).then(function (d) {
          if (S.templates.indexOf(d.name) < 0) S.templates.push(d.name);
          S.templates.sort(); renderTemplates(d.name); toast('模板「' + d.name + '」存好了');
        });
      }).catch(fail);
    };
    $('tplSel').onchange = function () {
      var name = this.value;
      $('tplDel').hidden = !name;
      if (!name) return;
      var hasText = $('tSubject').value.trim() || $('tBody').value.trim();
      (hasText ? dialog('载入模板', '会用「' + esc(name) + '」替换现在写的主题和正文。', { ok: '载入' }) : Promise.resolve(true))
        .then(function (ok) {
          if (!ok) { renderTemplates(''); return; }
          return api('/api/template_load', { name: name }).then(function (d) {
            setTemplate(d.template); saveDraft(); refreshPreview(); braceHint(); toast('已载入「' + name + '」');
          });
        }).catch(fail);
    };
    $('tplDel').onclick = function () {
      var name = $('tplSel').value; if (!name) return;
      dialog('删除模板', '确定删除「' + esc(name) + '」吗？', { ok: '删除' }).then(function (ok) {
        if (!ok) return;
        return api('/api/template_delete', { name: name }).then(function () {
          S.templates = S.templates.filter(function (n) { return n !== name; }); renderTemplates('');
        });
      }).catch(fail);
    };
  }
  function renderTemplates(sel) {
    $('tplSel').innerHTML = '<option value="">' + (S.templates.length ? '载入模板…' : '还没有存过模板') + '</option>' +
      S.templates.map(function (n) { return '<option' + (n === sel ? ' selected' : '') + '>' + esc(n) + '</option>'; }).join('');
    $('tplDel').hidden = !sel;
  }

  // ------------------------------------------------------------ 4 检查
  function kind(it) { return it.errors.length ? 'bad' : it.warnings.length ? 'warn' : 'ok'; }
  function isOn(it) {
    if (it.errors.length) return false;
    if (S.excluded[it.row]) return false;
    if ($('skipSent').checked && it.sent_before) return false;
    return true;
  }
  function doPreview() {
    if (!S.table) { S.preview = null; renderCheck(); return; }
    api('/api/preview', { template: template() }).then(function (d) {
      S.preview = d;
      if (S.cur >= d.items.length) S.cur = 0;
      renderCheck(); renderVars(); renderTable();
    }).catch(fail);
  }
  function renderCheck() {
    var p = S.preview;
    var has = p && p.items.length;
    $('checkEmpty').hidden = !!has; $('checkView').hidden = !has;
    if (!has) { $('checkSide').innerHTML = ''; updateSend(); return; }
    var items = p.items;
    var nBad = items.filter(function (i) { return kind(i) === 'bad'; }).length;
    var nWarn = items.filter(function (i) { return kind(i) === 'warn'; }).length;
    var nSent = items.filter(function (i) { return i.sent_before; }).length;
    var f = [['all', '全部', items.length], ['bad', '有问题', nBad], ['warn', '要留意', nWarn]];
    if (S.filter !== 'all' && !f.some(function (x) { return x[0] === S.filter && x[2]; })) S.filter = 'all';
    $('filters').innerHTML = f.filter(function (x) { return x[0] === 'all' || x[2]; }).map(function (x) {
      return '<button class="pill' + (S.filter === x[0] ? ' on' : '') + '" data-f="' + x[0] + '">' + x[1] + '<b>' + x[2] + '</b></button>';
    }).join('');
    $('checkSide').innerHTML = nBad ? '<span class="badge bad">' + nBad + ' 封有问题，不会发</span>' :
      '<span class="badge ok">都没问题</span>';
    $('s4').classList.toggle('done', !nBad);
    $('skipSentWrap').hidden = !nSent;
    $('skipSentLabel').textContent = '跳过最近已经发过同样主题的人（' + nSent + ' 个）';

    var shown = items.filter(function (it) { return S.filter === 'all' || kind(it) === S.filter; });
    $('list').innerHTML = shown.length ? shown.map(function (it) {
      var k = kind(it), on = isOn(it);
      var label = k === 'bad' ? '有问题' : k === 'warn' ? '留意' : '好了';
      return '<div class="item' + (it.index === S.cur ? ' cur' : '') + (on ? '' : ' off') + '" data-i="' + it.index + '">' +
        '<input type="checkbox"' + (on ? ' checked' : '') + (k === 'bad' ? ' disabled' : '') + ' data-row="' + it.row + '">' +
        '<span class="rn">第' + it.row + '行</span>' +
        '<span class="who">' + esc(it.to.join(', ') || '（没有收件人）') + '</span>' +
        '<span class="badge ' + k + '">' + label + '</span></div>';
    }).join('') : '<div class="empty">没有</div>';
    var nOn = items.filter(isOn).length;
    var nCan = items.filter(function (i) { return !i.errors.length; }).length;
    $('selAll').checked = nOn === nCan && nCan > 0;
    $('selAll').indeterminate = nOn > 0 && nOn < nCan;
    $('selCount').textContent = '选中 ' + nOn + ' 封';
    renderMail();
    updateSend();
  }
  function renderMail() {
    var it = S.preview && S.preview.items[S.cur];
    if (!it) { $('mailPreview').innerHTML = '<div class="mail-empty">点左边一封看看</div>'; return; }
    var s = S.settings || {};
    var from = (s.name ? s.name + ' ' : '') + '<' + (s.user || '还没设置发件邮箱') + '>';
    var h = '<dl class="mail-head">' +
      '<dt>发件人</dt><dd>' + esc(from) + '</dd>' +
      '<dt>收件人</dt><dd>' + esc(it.to.join(', ') || '—') + '</dd>' +
      (it.cc.length ? '<dt>抄送</dt><dd>' + esc(it.cc.join(', ')) + '</dd>' : '') +
      (it.bcc.length ? '<dt>密送</dt><dd>' + esc(it.bcc.join(', ')) + '</dd>' : '') +
      '<dt>主题</dt><dd class="mail-subject">' + esc(it.subject || '（没有主题）') + '</dd>' +
      (it.attachments.length ? '<dt>附件</dt><dd><div class="chips">' + it.attachments.map(function (a) {
        return '<span class="chip">' + esc(a.name) + ' <span class="size">' + size(a.size) + '</span>&nbsp;</span>';
      }).join('') + '</div></dd>' : '') + '</dl>';
    h += '<div class="mail-body">' + (it.body ? esc(it.body) : '<span class="muted">（正文是空的）</span>') + '</div>';
    if (it.errors.length || it.warnings.length) {
      h += '<div class="mail-problems">' + it.errors.map(function (e) { return '<div class="bad">✕ ' + esc(e) + '</div>'; }).join('') +
        it.warnings.map(function (w) { return '<div class="warn">! ' + esc(w) + '</div>'; }).join('') + '</div>';
    }
    $('mailPreview').innerHTML = h;
    $('testBtn').disabled = !!it.errors.length;
  }
  function bindCheck() {
    $('filters').addEventListener('click', function (e) {
      var b = e.target.closest('.pill'); if (!b) return;
      S.filter = b.dataset.f; renderCheck();
    });
    $('list').addEventListener('click', function (e) {
      var row = e.target.closest('.item'); if (!row) return;
      if (e.target.tagName === 'INPUT') {
        var r = e.target.dataset.row;
        if (e.target.checked) delete S.excluded[r]; else S.excluded[r] = true;
        var it = S.preview.items[+row.dataset.i];
        if (e.target.checked && it.sent_before && $('skipSent').checked) {
          toast('这个人最近收到过同样主题的邮件。要发给他，先取消下面「跳过最近已经发过」的勾。', true);
        }
      } else {
        S.cur = +row.dataset.i;
      }
      renderCheck();
    });
    $('selAll').onchange = function () {
      var on = this.checked;
      S.preview.items.forEach(function (it) { if (on) delete S.excluded[it.row]; else S.excluded[it.row] = true; });
      renderCheck();
    };
    $('testBtn').onclick = function () {
      msg($('testMsg'), '正在发送…');
      $('testBtn').disabled = true;
      api('/api/test_send', { template: template(), index: S.cur }).then(function (d) {
        msg($('testMsg'), '已发到 ' + d.to + '，去收件箱看看效果。', 'ok');
      }).catch(function (e) { msg($('testMsg'), e.message, 'bad'); })
        .then(function () { $('testBtn').disabled = false; });
    };
  }

  // ------------------------------------------------------------ 5 发送
  function selectedIndexes() {
    return S.preview ? S.preview.items.filter(isOn).map(function (it) { return it.index; }) : [];
  }
  function duration(sec) {
    if (sec < 60) return Math.max(1, Math.round(sec)) + ' 秒';
    if (sec < 3600) return Math.round(sec / 60) + ' 分钟';
    return (sec / 3600).toFixed(1) + ' 小时';
  }
  function updateSend() {
    var n = selectedIndexes().length;
    var acctOk = S.settings && S.settings.user && S.settings.has_password;
    var busy = S.job && (S.job.state === 'running' || S.job.state === 'paused');
    $('sendBtn').disabled = !n || !acctOk || busy;
    $('sendBtn').textContent = n ? '开始发送 ' + n + ' 封' : '开始发送';
    var hint = '';
    if (!acctOk) hint = '先在第 1 步设置发件邮箱。';
    else if (!S.table) hint = '先在第 2 步选名单。';
    else if (!n) hint = '没有可以发的邮件。';
    else hint = '大约需要 ' + duration(n * (parseFloat($('interval').value) || 0) + n * 1.5) + '。';
    msg($('sendHint'), hint);
  }
  function bindSend() {
    $('interval').addEventListener('input', function () { saveDraft(); updateSend(); });
    $('bccSelf').addEventListener('change', saveDraft);
    $('skipSent').addEventListener('change', renderCheck);
    $('sendBtn').onclick = function () {
      var idx = selectedIndexes(), n = idx.length;
      var bad = S.preview.items.filter(function (i) { return i.errors.length; }).length;
      var warn = S.preview.items.filter(function (i) { return isOn(i) && i.warnings.length; }).length;
      var interval = parseFloat($('interval').value) || 0;
      var html = '会从 <b>' + esc(S.settings.user) + '</b> 发出 <b>' + n + '</b> 封邮件，大约需要 ' +
        duration(n * interval + n * 1.5) + '。';
      if (bad) html += '<br>有 ' + bad + ' 封有问题，不会发。';
      if (warn) html += '<br>有 ' + warn + ' 封有「要留意」的提醒，确定都看过了吗？';
      html += '<br><br>发送过程中<b>不要关掉终端窗口</b>。网页可以关，重新打开还能看到进度。';
      dialog('确定开始发送吗？', html, { ok: '开始发送' }).then(function (ok) {
        if (!ok) return;
        return api('/api/send', {
          template: template(), indexes: idx, interval: interval, bcc_self: $('bccSelf').checked
        }).then(function (job) { S.job = job; renderJob(); poll(); });
      }).catch(fail);
    };
    $('pauseBtn').onclick = function () { jobAction('pause'); };
    $('resumeBtn').onclick = function () { jobAction('resume'); };
    $('stopBtn').onclick = function () {
      dialog('停止发送', '还没发的就不发了。已经发出去的收不回来。', { ok: '停止' }).then(function (ok) { if (ok) jobAction('stop'); });
    };
    $('retryBtn').onclick = function () {
      api('/api/retry_failed', {}).then(function (job) { S.job = job; renderJob(); poll(); }).catch(fail);
    };
    $('logBtn').onclick = function () { api('/api/open_folder', { path: S.job && S.job.log }).catch(fail); };
    $('newBatch').onclick = function () {
      api('/api/job', { action: 'clear' }).then(function () { S.job = null; renderJob(); doPreview(); }).catch(fail);
    };
    $('openData').onclick = function () { api('/api/open_folder', {}).catch(fail); };
  }
  function jobAction(a) {
    api('/api/job', { action: a }).then(function (d) { S.job = d.job; renderJob(); poll(); }).catch(fail);
  }
  var pollTimer = null;
  function poll() {
    clearTimeout(pollTimer);
    if (!S.job || S.job.state === 'done' || S.job.state === 'stopped') return;
    pollTimer = setTimeout(function () {
      api('/api/status').then(function (d) {
        var was = S.job && S.job.state;
        S.job = d.job; renderJob();
        if (S.job && (S.job.state === 'done' || S.job.state === 'stopped') && was !== S.job.state) {
          doPreview();
        }
        poll();
      }).catch(function () { pollTimer = setTimeout(poll, 3000); });
    }, 1000);
  }
  var STATUS = {
    waiting: ['wait', '等待'], sending: ['run', '发送中'], sent: ['ok', '已发送'],
    failed: ['bad', '失败'], skipped: ['wait', '没发']
  };
  function renderJob() {
    var j = S.job;
    $('jobView').hidden = !j; $('sendSetup').hidden = !!j;
    if (!j) { updateSend(); return; }
    var c = j.counts, sent = c.sent || 0, failed = c.failed || 0, skipped = c.skipped || 0;
    var finished = j.state === 'done' || j.state === 'stopped';
    var left = j.total - sent - failed - skipped;
    $('jobBar').style.width = (j.total ? (sent + failed + skipped) / j.total * 100 : 0) + '%';
    var text = '已发送 <b>' + sent + '</b> / ' + j.total;
    if (failed) text += ' · 失败 <b>' + failed + '</b>';
    if (skipped) text += ' · 没发 ' + skipped;
    if (!finished && left > 0) text += ' · 还剩约 ' + duration(left * (j.interval + 1.5));
    $('jobText').innerHTML = text;
    var b = $('jobBanner');
    if (j.state === 'paused') {
      b.hidden = false; b.className = 'banner'; b.textContent = j.message || '已暂停。';
    } else if (finished) {
      b.hidden = false;
      b.className = 'banner ' + (failed || j.state === 'stopped' ? 'bad' : 'ok');
      b.textContent = j.message || (j.state === 'stopped' ? '已停止。' :
        failed ? '发完了，但有 ' + failed + ' 封没发出去，原因写在下面。' : '全部发送成功！');
    } else {
      b.hidden = true;
    }
    $('pauseBtn').hidden = j.state !== 'running';
    $('resumeBtn').hidden = j.state !== 'paused';
    $('stopBtn').hidden = finished;
    $('jobDone').hidden = !finished;
    var again = failed + skipped;
    $('retryBtn').hidden = !again;
    $('retryBtn').textContent = '重发没发出去的 ' + again + ' 封';
    $('jobList').innerHTML = j.items.map(function (it) {
      var st = STATUS[it.status] || ['wait', it.status];
      return '<div class="item"><span class="rn">第' + it.row + '行</span>' +
        '<span class="who">' + esc(it.to.join(', ')) + '<small>' + esc(it.time ? it.time.slice(11, 19) : '') + '</small></span>' +
        '<span class="badge ' + st[0] + '">' + st[1] + '</span>' +
        (it.error ? '<span class="err">' + esc(it.error) + '</span>' : '') + '</div>';
    }).join('');
    updateSend();
  }

  // ------------------------------------------------------------ 启动
  function init() {
    bindAcct(); bindTable(); bindCompose(); bindCheck(); bindSend();
    $('quitBtn').onclick = function () {
      var busy = S.job && (S.job.state === 'running' || S.job.state === 'paused');
      dialog('退出工具箱', busy ? '<b>还在发送中！</b>退出的话，没发的就不发了。' : '关掉工具箱。下次用的时候再双击「双击打开.command」。',
        { ok: '退出' }).then(function (ok) {
        if (!ok) return;
        api('/api/quit', {}).catch(function () {}).then(function () { $('closed').hidden = false; });
      });
    };
    api('/api/init').then(function (d) {
      S.settings = d.settings; S.presets = d.presets; S.files = d.files; S.templates = d.templates; S.job = d.job;
      fillPresets(); fillAcctForm(); renderAcct();
      if (sysNotMac(d.platform)) $('rememberLabel').textContent = '记住授权码（存在本机的数据文件夹里）';
      var dr = d.draft || {};
      setTemplate(dr.template);
      if (dr.interval !== undefined && dr.interval !== '') $('interval').value = dr.interval;
      $('bccSelf').checked = !!dr.bcc_self;
      $('dataDir').textContent = d.data_dir;
      renderTemplates('');
      renderFiles();
      setTable(d.table, false);
      renderJob(); poll();
      braceHint();
    }).catch(fail);
  }
  function sysNotMac(p) { return p && p !== 'darwin'; }
  init();
})();
