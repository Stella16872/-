'use strict';
// 各个工具共用的小东西：发请求、提示条、弹窗……都挂在 window.TB 上。
(function () {
  var TOKEN = document.querySelector('meta[name=token]').content;
  var $ = function (id) { return document.getElementById(id); };

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

  function download(d) {
    // 让浏览器下载服务器刚生成的文件（Mac 上会存到「下载」文件夹）
    var a = document.createElement('a');
    a.href = '/api/download?id=' + encodeURIComponent(d.id) + '&t=' + encodeURIComponent(TOKEN);
    a.download = d.filename;
    document.body.appendChild(a); a.click(); a.remove();
  }
  function tableHtml(columns, rows, opts) {
    // rows: [[行号, 格子...]]（opts.rowNum 为 true 时第一个是行号）
    opts = opts || {};
    var h = '<thead><tr>' + (opts.rowNum ? '<th class="rn">行</th>' : '') + columns.map(function (c) {
      return '<th>' + esc(c) + '</th>';
    }).join('') + '</tr></thead><tbody>';
    rows.forEach(function (r) {
      var cells = opts.rowNum ? r.slice(1) : r;
      h += '<tr>' + (opts.rowNum ? '<td class="rn">' + r[0] + '</td>' : '') + cells.map(function (c) {
        return '<td title="' + esc(c) + '">' + esc(c) + '</td>';
      }).join('') + '</tr>';
    });
    return h + '</tbody>';
  }

  function headerOptions(sel, t) {
    // 「表头在第几行」下拉框：列出前几行的内容，方便认
    sel.innerHTML = (t.candidates || []).map(function (c) {
      return '<option value="' + c.row + '"' + (c.row === t.header_row ? ' selected' : '') + '>第 ' + c.row + ' 行：' +
        esc(c.text.length > 24 ? c.text.slice(0, 24) + '…' : c.text) + '</option>';
    }).join('');
  }

  window.TB = {
    TOKEN: TOKEN, $: $, esc: esc, size: size, api: api, upload: upload, toast: toast, fail: fail,
    debounce: debounce, dialog: dialog, msg: msg, download: download, tableHtml: tableHtml,
    headerOptions: headerOptions
  };
})();
