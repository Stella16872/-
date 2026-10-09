'use strict';
// 表格工具：合并、拆分、核对。共用的小东西在 common.js（window.TB）。
(function () {
  var TB = window.TB, $ = TB.$, api = TB.api, upload = TB.upload, esc = TB.esc, toast = TB.toast,
    fail = TB.fail, debounce = TB.debounce, msg = TB.msg;
  var ACCEPT = '.xlsx,.xlsm,.csv,.tsv,.txt,.xls,.numbers';

  // ------------------------------------------------------------ 顶部标签
  function showTab(name) {
    var tabs = document.querySelectorAll('.tab');
    for (var i = 0; i < tabs.length; i++) {
      var on = tabs[i].dataset.tab === name;
      tabs[i].classList.toggle('on', on);
      tabs[i].setAttribute('aria-selected', on ? 'true' : 'false');
    }
    var pages = document.querySelectorAll('main.page');
    for (var j = 0; j < pages.length; j++) pages[j].hidden = pages[j].id !== 'tab-' + name;
    try { localStorage.setItem('toolbox-tab', name); } catch (e) { /* 存不了就算了 */ }
    window.scrollTo(0, 0);
  }
  document.querySelector('.tabs').addEventListener('click', function (e) {
    var b = e.target.closest('.tab'); if (b) showTab(b.dataset.tab);
  });
  try {
    var last = localStorage.getItem('toolbox-tab');
    if (last && $('tab-' + last)) showTab(last);
  } catch (e) { /* 没有就用默认的 */ }

  function dragdrop(el, cb) {
    ['dragenter', 'dragover'].forEach(function (ev) {
      el.addEventListener(ev, function (e) { e.preventDefault(); el.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      el.addEventListener(ev, function (e) { e.preventDefault(); el.classList.remove('over'); });
    });
    el.addEventListener('drop', function (e) { cb(Array.prototype.slice.call(e.dataTransfer.files)); });
  }
  function options(list, selected) {
    return list.map(function (v) {
      return '<option' + (v === selected ? ' selected' : '') + '>' + esc(v) + '</option>';
    }).join('');
  }
  function stem(name) { return name.replace(/\.[^.]+$/, ''); }

  // ------------------------------------------------------------ 选一张表（拆分、核对用）
  function Picker(root, onChange) {
    var self = this;
    this.view = null;
    this.onChange = onChange;
    root.innerHTML =
      '<label class="drop small"><input type="file" accept="' + ACCEPT + '" hidden>' +
      '<div class="drop-main">把 Excel 或 CSV 拖到这里，或者<u>点这里选择</u></div></label>' +
      '<div class="picked" hidden><div class="table-bar"><span class="file-chip"></span>' +
      '<label class="inline sheet">工作表 <select></select></label>' +
      '<label class="inline head">表头在 <select></select></label>' +
      '<span class="muted count"></span><span class="grow"></span>' +
      '<button class="ghost small change">换一个</button></div>' +
      '<div class="table-wrap"><table class="data"></table></div><div class="muted small more"></div></div>';
    this.q = function (sel) { return root.querySelector(sel); };
    var input = this.q('input');
    input.onchange = function () { var f = this.files[0]; this.value = ''; if (f) self.load(f); };
    dragdrop(this.q('.drop'), function (files) { if (files[0]) self.load(files[0]); });
    this.q('.change').onclick = function () { input.click(); };
    this.q('.sheet select').onchange = function () { self.refresh({ sheet: this.value }); };
    this.q('.head select').onchange = function () { self.refresh({ sheet: self.view.sheet, header_row: +this.value }); };
  }
  Picker.prototype.load = function (file) {
    var self = this;
    this.q('.drop-main').textContent = '正在读取…';
    upload('/api/source_upload', { name: file.name }, file).then(function (v) { self.set(v); }).catch(function (e) {
      self.q('.drop-main').innerHTML = '把 Excel 或 CSV 拖到这里，或者<u>点这里选择</u>';
      fail(e);
    });
  };
  Picker.prototype.refresh = function (o) {
    var self = this;
    api('/api/source_view', { sid: this.view.sid, sheet: o.sheet, header_row: o.header_row || null })
      .then(function (v) { self.set(v); }).catch(fail);
  };
  Picker.prototype.set = function (v) {
    var q = this.q;
    this.view = v;
    q('.drop').hidden = !!v;
    q('.picked').hidden = !v;
    if (v) {
      q('.file-chip').textContent = v.filename;
      q('.sheet select').innerHTML = options(v.sheets, v.sheet);
      q('.sheet').hidden = v.sheets.length < 2;
      TB.headerOptions(q('.head select'), v);
      q('.head').hidden = v.candidates.length < 2;
      q('.count').textContent = '共 ' + v.total + ' 行';
      q('table').innerHTML = TB.tableHtml(v.columns, v.preview.slice(0, 6), { rowNum: true });
      q('.more').textContent = v.total > 6 ? '只显示了前 6 行。表头不对的话，在上面的「表头在」里改。' : '';
    }
    if (this.onChange) this.onChange(v);
  };
  Picker.prototype.ref = function () {
    var v = this.view;
    return v ? { sid: v.sid, sheet: v.sheet, header_row: v.header_row } : null;
  };

  // ------------------------------------------------------------ 合并
  var M = { sources: [], rename: {}, result: null };

  function addMerge(files) {
    var i = 0;
    function next() {
      if (i >= files.length) { renderMergeList(); mergePreview(); return; }
      var f = files[i++];
      msg($('mMsg'), '');
      $('mDrop').querySelector('.drop-main').textContent = '正在读取 ' + f.name + '…';
      upload('/api/source_upload', { name: f.name }, f).then(function (v) {
        M.sources.push({ view: v, all: false });
      }).catch(fail).then(next);
    }
    next();
  }
  function renderMergeList() {
    $('mDrop').querySelector('.drop-main').innerHTML = M.sources.length ?
      '还要加表格？拖到这里，或者<u>点这里选择</u>' : '把几个 Excel / CSV 文件一起拖到这里，或者<u>点这里选择</u>（可以多选）';
    $('mDrop').classList.toggle('small', M.sources.length > 0);
    $('mList').innerHTML = M.sources.map(function (s, i) {
      var v = s.view, multi = v.sheets.length > 1;
      return '<div class="src" data-i="' + i + '"><span class="file-chip">' + esc(v.filename) + '</span>' +
        (multi ? '<label class="inline">工作表 <select class="sh">' + options(v.sheets, s.all ? null : v.sheet) +
          '<option value="*"' + (s.all ? ' selected' : '') + '>全部工作表（' + v.sheets.length + ' 张）</option></select></label>' : '') +
        (!s.all && v.candidates.length > 1 ? '<label class="inline">表头在 <select class="hd"></select></label>' : '') +
        '<span class="muted small">' + (s.all ? '' : v.total + ' 行') + '</span><span class="grow"></span>' +
        '<button class="link rm">去掉</button></div>';
    }).join('');
    M.sources.forEach(function (s, i) {
      var hd = $('mList').querySelector('.src[data-i="' + i + '"] .hd');
      if (hd) TB.headerOptions(hd, s.view);
    });
    var has = M.sources.length > 0;
    $('mColsCard').hidden = !has;
    $('mResultCard').hidden = !has;
  }
  function mergeReq(exp) {
    return {
      sources: M.sources.map(function (s) {
        return s.all ? { sid: s.view.sid, all_sheets: true } :
          { sid: s.view.sid, sheet: s.view.sheet, header_row: s.view.header_row };
      }),
      rename: M.rename, add_source: $('mSource').checked, drop_totals: $('mTotals').checked,
      dedupe: $('mDedupe').checked, export: !!exp
    };
  }
  var mergePreview = debounce(function () {
    if (!M.sources.length) return;
    api('/api/merge', mergeReq()).then(renderMerge).catch(fail);
  }, 250);
  function renderMerge(r) {
    M.result = r;
    var labels = r.labels.map(function (l) { return stem(l.replace(/\.[^.·]+( · |$)/, '$1')); });
    var partial = 0;
    var h = '<thead><tr><th>列</th>' + labels.map(function (l, i) {
      return '<th class="mk" title="' + esc(r.labels[i]) + '">' + esc(l) + '<small>' + r.counts[i] + ' 行</small></th>';
    }).join('') + '<th>合并后叫</th></tr></thead><tbody>';
    r.matrix.forEach(function (x) {
      var all = x.in.every(Boolean);
      if (!all) partial++;
      h += '<tr class="' + (all ? '' : 'partial') + '"><td>' + esc(x.column) +
        (x.originals.length > 1 ? '<small>由「' + x.originals.map(esc).join('」「') + '」合成</small>' : '') + '</td>' +
        x.in.map(function (b) { return '<td class="mk">' + (b ? '✓' : '—') + '</td>'; }).join('') +
        '<td><input type="text" class="rn-in" value="' + esc(x.column) + '" data-orig="' +
        esc(JSON.stringify(x.originals)) + '"></td></tr>';
    });
    $('mMatrix').innerHTML = h + '</tbody>';
    $('mColsHint').hidden = !partial || r.labels.length < 2;
    $('mColsHint').textContent = '有 ' + partial + ' 列不是每张表都有（标黄的行）。如果其实是同一个意思、只是名字不一样' +
      '（比如「名字」和「姓名」），把右边「合并后叫」改成一样的名字，就会合成一列。';
    $('mColsSide').textContent = '合并后一共 ' + r.matrix.length + ' 列';
    $('mTotalsLabel').textContent = '去掉「合计 / 小计」行' + (r.removed_totals ? '（去掉了 ' + r.removed_totals + ' 行）' : '');
    $('mDedupeLabel').textContent = '去掉完全重复的行' + (r.removed_dupes ? '（去掉了 ' + r.removed_dupes + ' 行）' : '');
    $('mCount').textContent = '共 ' + r.total + ' 行，来自 ' + r.labels.length + ' 张表' +
      (r.skipped.length ? '（' + r.skipped.length + ' 张空表跳过了）' : '');
    $('mPreview').innerHTML = TB.tableHtml(r.columns, r.preview);
    $('mMore').textContent = r.total > r.preview.length ? '只显示了前 ' + r.preview.length + ' 行，下载的文件里是全部 ' + r.total + ' 行。' : '';
  }
  function exportMerge(download) {
    msg($('mMsg'), '正在生成…');
    return api('/api/merge', mergeReq(true)).then(function (r) {
      renderMerge(r);
      if (download) {
        TB.download(r.download);
        msg($('mMsg'), '已下载「' + r.download.filename + '」，在「下载」文件夹里。', 'ok');
      } else {
        msg($('mMsg'), '');
      }
      return r.source;
    }).catch(function (e) { msg($('mMsg'), e.message, 'bad'); throw e; });
  }
  function bindMerge() {
    $('mInput').onchange = function () { var fs = Array.prototype.slice.call(this.files); this.value = ''; addMerge(fs); };
    dragdrop($('mDrop'), addMerge);
    $('mList').addEventListener('change', function (e) {
      var row = e.target.closest('.src'); if (!row) return;
      var s = M.sources[+row.dataset.i];
      var req = null;
      if (e.target.classList.contains('sh')) {
        s.all = e.target.value === '*';
        if (!s.all) req = { sid: s.view.sid, sheet: e.target.value };
      } else if (e.target.classList.contains('hd')) {
        req = { sid: s.view.sid, sheet: s.view.sheet, header_row: +e.target.value };
      }
      (req ? api('/api/source_view', req).then(function (v) { s.view = v; }) : Promise.resolve())
        .then(function () { renderMergeList(); mergePreview(); }).catch(fail);
    });
    $('mList').addEventListener('click', function (e) {
      if (!e.target.classList.contains('rm')) return;
      var i = +e.target.closest('.src').dataset.i;
      api('/api/source_remove', { sid: M.sources[i].view.sid }).catch(function () {});
      M.sources.splice(i, 1);
      renderMergeList(); mergePreview();
    });
    $('mMatrix').addEventListener('change', function (e) {
      if (!e.target.classList.contains('rn-in')) return;
      var name = e.target.value.trim();
      JSON.parse(e.target.dataset.orig).forEach(function (o) {
        if (name && name !== o) M.rename[o] = name; else delete M.rename[o];
      });
      mergePreview();
    });
    ['mSource', 'mTotals', 'mDedupe'].forEach(function (id) { $(id).addEventListener('change', mergePreview); });
    $('mExport').onclick = function () { exportMerge(true).catch(function () {}); };
    $('mToSplit').onclick = function () {
      exportMerge(false).then(function (src) { SP.picker.set(src); showTab('split'); }).catch(function () {});
    };
    $('mToCompare').onclick = function () {
      exportMerge(false).then(function (src) {
        (C.a.view ? C.b : C.a).set(src); showTab('compare');
      }).catch(function () {});
    };
  }

  // ------------------------------------------------------------ 拆分
  var SP = {};
  function onSplitTable(v) {
    $('sGroupCard').hidden = !v;
    $('sOutCard').hidden = !v;
    $('sResult').hidden = true;
    msg($('sMsg'), '');
    if (!v) return;
    var prev = $('sCol').value;
    $('sCol').innerHTML = options(v.columns);
    var guess = v.columns.indexOf(prev) >= 0 ? prev : (v.columns.filter(function (c) {
      return /部门|姓名|名字|组别|班级|地区|城市|门店|分公司|类别|类型/.test(c);
    })[0] || v.columns[0]);
    $('sCol').value = guess;
    splitPreview();
  }
  function splitReq(exp) {
    var ref = SP.picker.ref();
    ref.column = $('sCol').value;
    ref.drop_totals = $('sTotals').checked;
    ref.mode = document.querySelector('input[name=sMode]:checked').value;
    ref.name_tpl = $('sName').value;
    ref.export = !!exp;
    return ref;
  }
  var splitPreview = debounce(function () {
    if (!SP.picker.view) return;
    api('/api/split', splitReq()).then(renderGroups).catch(fail);
  }, 250);
  function renderGroups(r) {
    var col = $('sCol').value, n = r.groups.length;
    var blank = r.groups.filter(function (g) { return g.value === '（空白）'; })[0];
    var single = n > 1 && r.groups.every(function (g) { return g.count === 1; });
    $('sGroups').innerHTML = '<div class="groups-head">会拆成 <b>' + n + '</b> 份，一共 ' + r.total + ' 行' +
      (single ? '（每份正好一行，适合每人一份发出去）' : '') + '</div><div class="chips">' +
      r.groups.slice(0, 200).map(function (g) {
        return '<span class="chip">' + esc(g.value) + ' <span class="size">' + g.count + ' 行</span>&nbsp;</span>';
      }).join('') + (n > 200 ? '<span class="muted small">…还有 ' + (n - 200) + ' 份</span>' : '') + '</div>';
    $('sBlankHint').hidden = !blank;
    if (blank) $('sBlankHint').textContent = '有 ' + blank.count + ' 行的「' + col + '」是空的，会单独拆成一份「（空白）」。';
    $('sTotalsLabel').textContent = '去掉「合计 / 小计」行' + (r.removed ? '（去掉了 ' + r.removed + ' 行）' : '');
    var eg = r.groups.slice(0, 2).map(function (g) { return '<code>' + esc(g.filename) + '</code>'; }).join('、');
    $('sNameHelp').innerHTML = '<code>{值}</code> 会换成每一份的「' + esc(col) + '」。比如写成 <code>{值}_9月工资条</code>。' +
      (eg ? '<br>现在的文件名会是：' + eg + (n > 2 ? ' ……' : '') : '');
    $('sExport').textContent = '开始拆分（' + n + ' 份）';
  }
  function bindSplit() {
    SP.picker = new Picker($('sPicker'), onSplitTable);
    $('sCol').onchange = splitPreview;
    $('sTotals').onchange = splitPreview;
    $('sName').addEventListener('input', splitPreview);
    Array.prototype.forEach.call(document.querySelectorAll('input[name=sMode]'), function (r) {
      r.addEventListener('change', function () {
        var files = document.querySelector('input[name=sMode]:checked').value === 'files';
        $('sNameWrap').hidden = !files; $('sNameHelp').hidden = !files;
        $('sResult').hidden = true;
      });
    });
    $('sExport').onclick = function () {
      msg($('sMsg'), '正在拆分…');
      $('sExport').disabled = true;
      api('/api/split', splitReq(true)).then(function (r) {
        msg($('sMsg'), '');
        $('sResult').hidden = false;
        if (r.download) {
          TB.download(r.download);
          $('sDone').textContent = '拆好了，已下载「' + r.download.filename + '」，在「下载」文件夹里。';
          $('sOpen').hidden = true; $('sToMail').hidden = true;
        } else {
          SP.folder = r.folder;
          $('sDone').textContent = '拆好了：' + r.groups.length + ' 个文件，放在 ' + r.folder;
          $('sOpen').hidden = false; $('sToMail').hidden = false;
        }
      }).catch(function (e) { msg($('sMsg'), e.message, 'bad'); })
        .then(function () { $('sExport').disabled = false; });
    };
    $('sOpen').onclick = function () { api('/api/open_folder', { path: SP.folder }).catch(fail); };
    $('sToMail').onclick = function () {
      api('/api/split_to_mail', {}).then(function (r) {
        return window.Mail.reload({ rule: r.rule }).then(function () {
          showTab('mail');
          toast('已把 ' + r.count + ' 个文件放进「每个人不一样的附件」' +
            (r.table_set ? '，名单也用了这张表。' : '。还要在第 2 步选名单（里面要有姓名和邮箱）。'));
        });
      }).catch(fail);
    };
  }

  // ------------------------------------------------------------ 核对
  var C = { tab: 'only_a', result: null, cols: null };
  var KEY_WORDS = /姓名|名字|工号|编号|学号|员工号|邮箱|e-?mail|手机|电话|身份证|账号|^id$/i;
  var SAME = [['姓名', '名字', '名称', 'name'], ['工号', '员工编号', '员工号', '编号', '学号'],
    ['邮箱', '邮件', 'email', 'e-mail', '电子邮箱'], ['手机', '手机号', '电话', '手机号码', '联系电话']];
  function norm(s) { return String(s).replace(/\s+/g, '').toLowerCase(); }
  function guessKeys(ca, cb) {
    var nb = cb.map(norm), i, j;
    for (i = 0; i < ca.length; i++) {  // 两边名字一样、又像是 key 的列
      if (KEY_WORDS.test(ca[i]) && nb.indexOf(norm(ca[i])) >= 0) return [ca[i], cb[nb.indexOf(norm(ca[i]))]];
    }
    for (i = 0; i < SAME.length; i++) {  // 「姓名」对「名字」这种
      var ga = ca.filter(function (c) { return SAME[i].indexOf(norm(c)) >= 0; })[0];
      var gb = cb.filter(function (c) { return SAME[i].indexOf(norm(c)) >= 0; })[0];
      if (ga && gb) return [ga, gb];
    }
    for (j = 0; j < ca.length; j++) {
      if (nb.indexOf(norm(ca[j])) >= 0) return [ca[j], cb[nb.indexOf(norm(ca[j]))]];
    }
    return [ca[0], cb[0]];
  }
  function onCmpTable() {
    var va = C.a.view, vb = C.b.view;
    $('cKeyCard').hidden = !(va && vb);
    $('cResultCard').hidden = true;
    if (!va || !vb) return;
    var keys = guessKeys(va.columns, vb.columns);
    var ka = va.columns.indexOf($('cKeyA').value) >= 0 ? $('cKeyA').value : keys[0];
    var kb = vb.columns.indexOf($('cKeyB').value) >= 0 ? $('cKeyB').value : keys[1];
    $('cKeyA').innerHTML = options(va.columns, ka);
    $('cKeyB').innerHTML = options(vb.columns, kb);
    C.cols = null;
    cmpRun();
  }
  function cmpReq(exp) {
    return { a: C.a.ref(), b: C.b.ref(), key_a: $('cKeyA').value, key_b: $('cKeyB').value,
      loose: $('cLoose').checked, columns: C.cols, export: !!exp };
  }
  var cmpRun = debounce(function () {
    if (!C.a.view || !C.b.view) return;
    api('/api/compare', cmpReq()).then(renderCmp).catch(fail);
  }, 250);
  function renderCmp(r) {
    C.result = r;
    $('cResultCard').hidden = false;
    var compared = r.compared.map(function (p) { return p.join('\u0000'); });
    $('cColsWrap').hidden = !r.common.length;
    $('cCols').innerHTML = r.common.map(function (p) {
      var on = compared.indexOf(p.join('\u0000')) >= 0;
      return '<label class="chip check small"><input type="checkbox" data-a="' + esc(p[0]) + '" data-b="' + esc(p[1]) + '"' +
        (on ? ' checked' : '') + '> <span>' + esc(p[0] === p[1] ? p[0] : p[0] + ' / ' + p[1]) + '</span></label>';
    }).join('');
    var stats = [
      ['only_a', '只在 A 里', r.n_only_a, 'A 有、B 没有'], ['only_b', '只在 B 里', r.n_only_b, 'B 有、A 没有'],
      ['diffs', '内容不同', r.n_diffs, '两边都有，但有的格子不一样'], ['same', '两边一样', r.same, '两边都有，内容也一样']
    ];
    $('cStats').innerHTML = stats.map(function (s) {
      return '<button class="stat' + (C.tab === s[0] ? ' on' : '') + (s[2] && s[0] !== 'same' ? ' has' : '') +
        '" data-tab="' + s[0] + '"><b>' + s[2] + '</b><span>' + s[1] + '</span><small>' + s[3] + '</small></button>';
    }).join('');
    var warns = [];
    r.dup_a.forEach(function (d) { warns.push('表 A 里「' + d.key + '」出现了 ' + d.rows.length + ' 次（第 ' + d.rows.join('、') + ' 行）'); });
    r.dup_b.forEach(function (d) { warns.push('表 B 里「' + d.key + '」出现了 ' + d.rows.length + ' 次（第 ' + d.rows.join('、') + ' 行）'); });
    if (r.blank_a) warns.push('表 A 有 ' + r.blank_a + ' 行的「' + $('cKeyA').value + '」是空的，没参加核对');
    if (r.blank_b) warns.push('表 B 有 ' + r.blank_b + ' 行的「' + $('cKeyB').value + '」是空的，没参加核对');
    $('cWarn').hidden = !warns.length;
    $('cWarn').textContent = warns.join('；') + (r.dup_a.length || r.dup_b.length ? '。重复的只用第一次出现的那行来比较内容。' : '。');
    var t = $('cTable'), more = '', n = 0;
    if (C.tab === 'only_a') { t.innerHTML = TB.tableHtml(r.columns_a, r.only_a, { rowNum: true }); n = r.n_only_a; }
    else if (C.tab === 'only_b') { t.innerHTML = TB.tableHtml(r.columns_b, r.only_b, { rowNum: true }); n = r.n_only_b; }
    else if (C.tab === 'diffs') {
      var rows = [];
      r.diffs.forEach(function (d) {
        d.changes.forEach(function (ch, i) {
          rows.push('<tr><td>' + (i ? '' : esc(d.key)) + '</td><td class="rn">' + (i ? '' : d.row_a + ' / ' + d.row_b) +
            '</td><td>' + esc(ch.column) + '</td><td class="diff">' + esc(ch.a) + '</td><td class="diff">' + esc(ch.b) + '</td></tr>');
        });
      });
      t.innerHTML = '<thead><tr><th>' + esc($('cKeyA').value) + '</th><th class="rn">行号 A / B</th><th>列</th><th>表 A 里是</th>' +
        '<th>表 B 里是</th></tr></thead><tbody>' + rows.join('') + '</tbody>';
      n = r.n_diffs;
    } else {
      t.innerHTML = '<tbody><tr><td class="empty-cell">' + r.same + ' 个两边完全一样，不用管。</td></tr></tbody>';
    }
    if (!n && C.tab !== 'same') t.innerHTML = '<tbody><tr><td class="empty-cell">没有。</td></tr></tbody>';
    if (n > 500) more = '页面上只显示前 500 个，下载的文件里是全部 ' + n + ' 个。';
    $('cMore').textContent = more;
    var who = C.tab === 'only_a' ? r.n_only_a : C.tab === 'only_b' ? r.n_only_b : 0;
    $('cToMail').hidden = !who;
    $('cToMail').textContent = '给这 ' + who + ' 个人发邮件 →';
  }
  function bindCompare() {
    C.a = new Picker($('cPickerA'), onCmpTable);
    C.b = new Picker($('cPickerB'), onCmpTable);
    ['cKeyA', 'cKeyB'].forEach(function (id) { $(id).onchange = function () { C.cols = null; cmpRun(); }; });
    $('cLoose').onchange = cmpRun;
    $('cCols').addEventListener('change', function () {
      C.cols = Array.prototype.map.call($('cCols').querySelectorAll('input:checked'), function (el) {
        return [el.dataset.a, el.dataset.b];
      });
      cmpRun();
    });
    $('cStats').addEventListener('click', function (e) {
      var b = e.target.closest('.stat'); if (!b) return;
      C.tab = b.dataset.tab; renderCmp(C.result);
    });
    $('cExport').onclick = function () {
      msg($('cMsg'), '正在生成…');
      api('/api/compare', cmpReq(true)).then(function (r) {
        TB.download(r.download);
        msg($('cMsg'), '已下载「' + r.download.filename + '」，在「下载」文件夹里。', 'ok');
      }).catch(function (e) { msg($('cMsg'), e.message, 'bad'); });
    };
    $('cToMail').onclick = function () {
      var which = C.tab === 'only_b' ? 'b' : 'a';
      var n = which === 'a' ? C.result.n_only_a : C.result.n_only_b;
      var ask = window.Mail.hasTable() ?
        TB.dialog('换成这 ' + n + ' 个人？', '「群发邮件」那边现在的名单会换成这 ' + n + ' 个人。', { ok: '换' }) : Promise.resolve(true);
      ask.then(function (ok) {
        if (!ok) return;
        var req = cmpReq();
        req.which = which;
        return api('/api/compare_to_mail', req).then(function () {
          return window.Mail.reload();
        }).then(function () {
          showTab('mail');
          toast('名单换成了这 ' + n + ' 个人，写好邮件就能发。');
        });
      }).catch(fail);
    };
  }

  bindMerge(); bindSplit(); bindCompare();
  window.Tools = { showTab: showTab };
})();
