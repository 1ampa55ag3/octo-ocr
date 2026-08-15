// OctoOCR 离线工作台前端（纯本地资源，零外网依赖）
var current = null;   // 当前项目
var pageIdx = 0;
var quill = null;

function $(id) { return document.getElementById(id); }
// 状态提示统一走顶部 toast（showToast）；任务进度显示在顶栏 #jobStatus

// 注入内联 SVG 图标（Lucide，currentColor 随主题着色）
injectIcons();

// ---- 明暗主题切换（localStorage 持久化，初始跟随系统）----
function applyTheme(t) {
  document.body.setAttribute("data-theme", t);
  // 深色下显示太阳（点击切亮色），浅色下显示月亮
  // 注意：图标必须包裹 .icn 容器，否则 SVG 以 24px 原始尺寸渲染撑大按钮
  $("btnTheme").innerHTML = '<span class="icn">' + ICONS[t === "dark" ? "sun" : "moon"] + "</span>";
}
(function initTheme() {
  var saved = null;
  try { saved = localStorage.getItem("octo-theme"); } catch (e) {}
  var sysDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (sysDark ? "dark" : "light"));
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function (e) {
      if (!localStorage.getItem("octo-theme")) applyTheme(e.matches ? "dark" : "light");
    });
  }
})();
$("btnTheme").onclick = function () {
  var next = document.body.getAttribute("data-theme") === "dark" ? "light" : "dark";
  try { localStorage.setItem("octo-theme", next); } catch (e) {}
  applyTheme(next);
};

// ---- 页面划分开关（仅隐藏分隔块，ops 映射保留）----
$("btnDivide").onclick = function () {
  var box = $("editorBox");
  var on = box.classList.toggle("no-divide");
  $("btnDivide").innerHTML = '<span class="icn">' + ICONS["rows-3"] + "</span>" + (on ? " 显示页面划分" : " 隐藏页面划分");
};
// (esc 已移除：任务卡/标题均用 textContent 渲染，无需转义)

// ---- 页面分隔块（自定义 Block Embed，Quill 序列化保留 data-page）----
var BlockEmbed = Quill.import("blots/block/embed");
class PageBreakBlot extends BlockEmbed {
  static create(value) {
    var node = super.create();
    node.setAttribute("data-page", value);
    node.setAttribute("contenteditable", "false");
    node.textContent = "— 第 " + (value + 1) + " 页 —";
    return node;
  }
  static value(node) {
    return parseInt(node.getAttribute("data-page"), 10);
  }
}
PageBreakBlot.blotName = "mdunPage";
PageBreakBlot.tagName = "div";
PageBreakBlot.className = "mdun-page-break";
Quill.register({ "formats/mdunPage": PageBreakBlot }, true);

// ---- 真实表格块（可编辑单元格，delta 同步）----
class MdunTableBlot extends BlockEmbed {
  static create(rows) {
    var node = super.create();
    var table = document.createElement("table");
    table.className = "mdun-table";
    (rows || []).forEach(function (r, rIdx) {
      var tr = document.createElement("tr");
      (r || []).forEach(function (cell, cIdx) {
        var td = document.createElement("td");
        td.setAttribute("data-r", String(rIdx));
        td.setAttribute("data-c", String(cIdx));
        td.textContent = cell || "";
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    node.appendChild(table);
    return node;
  }
  static value(node) {
    var rows = [];
    node.querySelectorAll("tr").forEach(function (tr) {
      var r = [];
      tr.querySelectorAll("td").forEach(function (td) { r.push(td.textContent.trim()); });
      rows.push(r);
    });
    return rows;
  }
}
MdunTableBlot.blotName = "mdunTable";
MdunTableBlot.tagName = "div";
MdunTableBlot.className = "mdun-table-block";
Quill.register({ "formats/mdunTable": MdunTableBlot }, true);

// ---- 拼写错误标记（红色波浪线 + 建议数据）----
var Inline = Quill.import("blots/inline");
class SpellBlot extends Inline {
  static create(value) {
    var node = super.create();
    node.classList.add("spell-err");
    var v = value || {};
    node.setAttribute("data-word", v.word || "");
    node.setAttribute("data-sug", JSON.stringify(v.suggestions || []));
    return node;
  }
  static formats(node) {
    return { word: node.getAttribute("data-word"), suggestions: JSON.parse(node.getAttribute("data-sug") || "[]") };
  }
}
SpellBlot.blotName = "spell";
SpellBlot.tagName = "span";
Quill.register({ "formats/spell": SpellBlot }, true);

// 低置信标记（黄色高亮，点击定位原文）
class LowConfBlot extends Inline {
  static create(value) {
    var node = super.create();
    node.setAttribute("class", "low-conf");
    return node;
  }
  static formats(node) {
    return true;
  }
}
LowConfBlot.blotName = "lowconf";
LowConfBlot.tagName = "span";
Quill.register({ "formats/lowconf": LowConfBlot }, true);

// ---- 公式样式（居中斜体等宽）----
class FormulaBlot extends Inline {
  static create() { return super.create(); }
}
FormulaBlot.blotName = "formula";
FormulaBlot.tagName = "span";
FormulaBlot.className = "mdun-formula";
Quill.register({ "formats/formula": FormulaBlot }, true);

// 单元格编辑：点击 td → 浮层输入 → 提交 delta（避免直接改 embed 内部 DOM 与 Quill 冲突）
var cellOverlay = null;
function closeCellEdit() {
  if (cellOverlay) { cellOverlay.remove(); cellOverlay = null; }
}
function openCellEdit(td) {
  closeCellEdit();
  var wrap = td.closest(".mdun-table-block");
  if (!wrap) return;
  var r = parseInt(td.getAttribute("data-r"), 10);
  var c = parseInt(td.getAttribute("data-c"), 10);
  var overlay = document.createElement("div");
  overlay.className = "cell-edit";
  var input = document.createElement("input");
  input.type = "text";
  input.value = td.textContent.trim();
  overlay.appendChild(input);
  document.body.appendChild(overlay);
  var rect = td.getBoundingClientRect();
  overlay.style.left = Math.max(8, rect.left) + "px";
  overlay.style.top = Math.max(8, rect.top - 6) + "px";
  overlay.style.width = Math.max(rect.width, 140) + "px";
  cellOverlay = overlay;
  input.focus();
  input.select();
  var commit = function () {
    var v = input.value;
    var rows = MdunTableBlot.value(wrap);
    if (r < rows.length && c < rows[r].length) rows[r][c] = v;
    var blot = Quill.find(wrap);
    if (blot) {
      var idx = quill.getIndex(blot);
      var Delta = Quill.import("delta");
      quill.updateContents(new Delta().retain(idx).delete(1).insert({ mdunTable: rows }), "user");
    }
    closeCellEdit();
    showToast("单元格已更新");
  };
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    if (e.key === "Escape") { closeCellEdit(); }
  });
  input.addEventListener("blur", function () { commit(); });
}
$("editorBox").addEventListener("click", function (e) {
  var td = e.target && e.target.closest ? e.target.closest(".mdun-table td") : null;
  if (td) openCellEdit(td);
});

// ---- Quill 初始化 ----
quill = new Quill("#editorBox", {
  theme: "snow",
  modules: {
    toolbar: "#toolbar",
    history: { delay: 1000, maxStack: 500, userOnly: false },
  },
  placeholder: "导入文件后，整篇文档将在此显示，可直接编辑",
});

// ---- 轻提示 ----
function showToast(msg, kind) {
  var box = $("toastBox");
  var t = document.createElement("div");
  t.className = "toast" + (kind ? " " + kind : "");
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(function () {
    t.style.opacity = "0";
    t.style.transition = "opacity .25s";
    setTimeout(function () { t.remove(); }, 300);
  }, 3200);
}

// ---- 上传与任务轮询（拖拽/粘贴/点击共用）----
var ACCEPT_EXTS = [".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"];
function uploadFile(f) {
  var ext = "." + (f.name || "").split(".").pop().toLowerCase();
  if (ACCEPT_EXTS.indexOf(ext) < 0) {
    showToast("不支持的格式: " + ext + "（支持 PDF/PNG/JPG/TIFF/BMP/WebP）", "err");
    return;
  }
  var fd = new FormData();
  fd.append("file", f);
  $("jobStatus").classList.remove("hidden");
  $("progressBar").classList.remove("hidden");
  $("jobStatus").textContent = "上传中…";
  showToast("开始粗识别: " + f.name + "（可在预览栏点击「全文识别」升级精度）");
  fetch("/api/ocr", { method: "POST", body: fd })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.error) throw new Error(data.error);
      pollJob(data.job_id);
    })
    .catch(function (err) {
      $("jobStatus").textContent = "失败: " + err.message;
      showToast("上传失败: " + err.message, "err");
    });
}
$("fileInput").addEventListener("change", function (e) {
  if (e.target.files[0]) uploadFile(e.target.files[0]);
});

// ---- 拖拽文件放入识别 ----
(function initDrop() {
  var zone = $("dropZone");
  var depth = 0;
  window.addEventListener("dragenter", function (e) {
    e.preventDefault();
    if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types, "Files") >= 0) {
      depth++;
      zone.classList.remove("hidden");
    }
  });
  window.addEventListener("dragover", function (e) { e.preventDefault(); });
  window.addEventListener("dragleave", function (e) {
    e.preventDefault();
    depth = Math.max(0, depth - 1);
    if (depth === 0) zone.classList.add("hidden");
  });
  window.addEventListener("drop", function (e) {
    e.preventDefault();
    depth = 0;
    zone.classList.add("hidden");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadFile(e.dataTransfer.files[0]);
    }
  });
})();

// ---- 粘贴导入（⌘V / Ctrl+V：文件或剪贴板图片）----
document.addEventListener("paste", function (e) {
  var cd = e.clipboardData;
  if (!cd) return;
  if (cd.files && cd.files.length > 0) {
    e.preventDefault();
    uploadFile(cd.files[0]);
    return;
  }
  var items = cd.items || [];
  for (var i = 0; i < items.length; i++) {
    if (items[i].type && items[i].type.indexOf("image") === 0) {
      var blob = items[i].getAsFile();
      if (blob) {
        e.preventDefault();
        var ts = new Date().getTime();
        uploadFile(new File([blob], "clipboard-" + ts + ".png", { type: blob.type }));
        break;
      }
    }
  }
});

function pollJob(jobId) {
  fetch("/api/job/" + jobId)
    .then(function (r) { return r.json(); })
    .then(function (job) {
      var p = job.progress || {};
      if (job.status === "done") {
        $("jobStatus").textContent = "识别完成（" + (p.done || 0) + " 页）";
        $("progressFill").style.width = "100%";
        setTimeout(function () { $("jobStatus").classList.add("hidden"); $("progressBar").classList.add("hidden"); }, 2000);
        fetch("/api/project/" + job.project_id)
          .then(function (r) { return r.json(); })
          .then(openProject)
          .catch(function (e) { showToast("加载项目失败: " + e.message, "err"); });
        return;
      }
      if (job.status === "error") {
        showToast("识别失败: " + (job.error || "未知错误"), "err");
        $("jobStatus").textContent = "失败";
        return;
      }
      if (job.status === "canceled") {
        showToast("识别已取消");
        $("jobStatus").textContent = "已取消";
        return;
      }
      var total = p.total || 0;
      $("jobStatus").textContent = "识别中… " + (p.done || 0) + (total ? " / " + total + " 页" : "");
      if (total > 0) $("progressFill").style.width = Math.round(100 * p.done / total) + "%";
      setTimeout(function () { pollJob(jobId); }, 800);
    });
}

// ---- 项目列表 ----
function listProjects() {
  fetch("/api/list").then(function (r) { return r.json(); }).then(function (items) {
    var box = $("projects");
    box.innerHTML = "";
    $("emptyHint").classList.toggle("hidden", items.length > 0);
    items.forEach(function (it) {
      var div = document.createElement("div");
      div.className = "proj" + (current && it.id === current.id ? " active" : "");
      var name = document.createElement("span");
      name.className = "p-name";
      name.textContent = it.source;
      name.title = it.source;
      var pages = document.createElement("span");
      pages.className = "p-pages";
      pages.textContent = it.pages + " 页";
      var re = document.createElement("span");
      re.className = "p-act";
      re.title = "重新识别（全文高精度）";
      re.innerHTML = '<span class="icn">' + ICONS["scan-text"] + "</span>";
      re.onclick = function (e) {
        e.stopPropagation();
        $("jobStatus").textContent = "重新识别排队中…";
        $("jobStatus").classList.remove("hidden");
        $("progressBar").classList.remove("hidden");
        fetch("/api/reprocess", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: it.id }),
        }).then(function (r) { return r.json(); }).then(function (d) {
          if (d.error) throw new Error(d.error);
          pollJob(d.job_id);
        }).catch(function (err) {
          $("jobStatus").classList.add("hidden");
          $("progressBar").classList.add("hidden");
          showToast("重新识别失败: " + err.message, "err");
        });
      };
      var del = document.createElement("span");
      del.className = "p-del";
      del.title = "删除任务";
      del.innerHTML = '<span class="icn">' + ICONS["x"] + "</span>";
      del.onclick = function (e) {
        e.stopPropagation();
        if (!window.confirm("删除任务 " + it.source + " ？")) return;
        fetch("/api/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: it.id }),
        }).then(function () {
          if (current && current.id === it.id) { current = null; quill.setContents([]); $("imageBox").innerHTML = '<div class="placeholder">导入文件后在此预览原图</div>'; }
          listProjects();
          showToast("任务已删除");
        });
      };
      div.appendChild(name);
      div.appendChild(pages);
      div.appendChild(re);
      div.appendChild(del);
      div.onclick = function () {
        fetch("/api/project/" + it.id).then(function (r) { return r.json(); }).then(openProject);
      };
      box.appendChild(div);
    });
  });
}

// ---- 编辑内容版本管理（每项目内存快照）+ 区域结果视图 ----
var versions = [];
var fullOps = [];
var viewMode = "full";   // "full" | "region"
function pushVersion(label) {
  if (!quill) return;
  versions.push({ time: Date.now(), label: label, ops: quill.getContents().ops });
  if (versions.length > 30) versions.shift();
  renderVersions();
}
function fmtTime(t) {
  var d = new Date(t);
  function p2(n) { return (n < 10 ? "0" : "") + n; }
  return p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" + p2(d.getSeconds());
}
function renderVersions() {
  var menu = $("versionMenu");
  if (!menu) return;
  menu.innerHTML = "";
  if (!versions.length) {
    var empty = document.createElement("div");
    empty.className = "vm-empty";
    empty.textContent = "暂无版本";
    menu.appendChild(empty);
    return;
  }
  versions.slice().reverse().forEach(function (v, ri) {
    var idx = versions.length - 1 - ri;
    var b = document.createElement("button");
    b.className = "vm-item";
    var lab = document.createElement("span");
    lab.className = "vm-label";
    lab.textContent = v.label;
    var tm = document.createElement("span");
    tm.className = "vm-time";
    tm.textContent = fmtTime(v.time);
    b.appendChild(lab);
    b.appendChild(tm);
    b.onclick = function () { restoreVersion(idx); };
    menu.appendChild(b);
  });
}
function restoreVersion(idx) {
  var v = versions[idx];
  if (!v || !quill) return;
  var cur = JSON.stringify(quill.getContents().ops);
  var last = versions.length ? JSON.stringify(versions[versions.length - 1].ops) : null;
  if (cur !== last) pushVersion("未保存编辑");
  quill.setContents(v.ops, "silent");
  quill.history.clear();
  fullOps = v.ops;
  viewMode = "full";
  $("regionBar").classList.add("hidden");
  $("versionMenu").classList.add("hidden");
  showToast("已恢复到版本：" + v.label, "ok");
}
$("btnVersions").onclick = function (e) {
  if (!current) { showToast("请先导入文件", "err"); return; }
  e.stopPropagation();
  $("versionMenu").classList.toggle("hidden");
};
document.addEventListener("click", function (e) {
  var menu = $("versionMenu");
  if (menu.classList.contains("hidden")) return;
  if (!menu.contains(e.target) && !$("btnVersions").contains(e.target)) menu.classList.add("hidden");
});
function buildRegionOps(proj, d) {
  var p = proj.pages[pageIdx];
  var ops = [];
  if (d.tables > 0 && p.tables && p.tables.length) {
    var t = p.tables[p.tables.length - 1];
    if (t.rows && t.rows.length) { ops.push({ insert: { mdunTable: t.rows } }); ops.push({ insert: "\n" }); }
  } else if (d.formulas > 0 && p.formulas && p.formulas.length) {
    var f = p.formulas[p.formulas.length - 1];
    ops.push({ insert: f.latex, attributes: { formula: true } });
    ops.push({ insert: "\n" });
  } else if (d.text) {
    ops.push({ insert: d.text });
    ops.push({ insert: "\n" });
  }
  return ops;
}
function showRegionView(d) {
  viewMode = "region";
  var ops = buildRegionOps(current, d);
  if (ops.length) {
    quill.setContents(ops, "silent");
    quill.history.clear();
    pushVersion("区域识别结果");
  }
  $("regionBar").classList.remove("hidden");
}
$("btnBackFull").onclick = function () {
  viewMode = "full";
  quill.setContents(fullOps.length ? fullOps : [], "silent");
  quill.history.clear();
  $("regionBar").classList.add("hidden");
  showToast("已回到全文");
};

// ---- 打开项目：整篇文档装入编辑器 ----
function openProject(data, keepPage) {
  current = data;
  if (!keepPage || !data.pages || pageIdx >= data.pages.length) pageIdx = 0;
  var ops = [];
  (data.pages || []).forEach(function (p, i) {
    ops.push({ insert: { mdunPage: i } });
    ops.push({ insert: "\n" });
    (p.paras || []).forEach(function (para) {
      var t = para.text;
      if (!t) return;
      var attrs = {};
      if (para.kind === "heading") attrs.header = 2;
      ops.push({ insert: t });
      ops.push({ insert: "\n", attributes: attrs });
    });
    // 表格：真实表格块（单元格可直接编辑）
    (p.tables || []).forEach(function (t) {
      if (!t.rows || !t.rows.length) return;
      ops.push({ insert: { mdunTable: t.rows } });
      ops.push({ insert: "\n" });
    });
    // 公式：居中样式 LaTeX 行
    (p.formulas || []).forEach(function (f) {
      ops.push({ insert: f.latex, attributes: { formula: true } });
      ops.push({ insert: "\n" });
    });
  });
  quill.setContents(ops, "silent");
  quill.history.clear();
  fullOps = ops;
  viewMode = "full";
  if (!keepPage) zoomScale = 1;   // 新任务回到 100%，同一任务切页保留缩放
  $("regionBar").classList.add("hidden");
  if (!keepPage) versions = [{ time: Date.now(), label: "载入全文", ops: ops }];
  renderVersions();
  renderPage();
  listProjects();
  applyLowConfMarks();
  if (!keepPage) showToast("已载入 " + data.pages.length + " 页，可在右侧编辑全文", "ok");
}

// ---- 低置信标记与图文对照（黄色高亮 / 段落点击定位原文）----
function pageTextBounds() {
  // 返回每页在编辑器纯文本中的 [start, end) 边界
  var ops = quill.getContents().ops;
  var bounds = [];
  var pos = 0;
  ops.forEach(function (op) {
    if (typeof op.insert === "object" && op.insert && op.insert.mdunPage !== undefined) {
      bounds.push(pos);
    } else if (typeof op.insert === "string") {
      pos += op.insert.length;
    }
  });
  bounds.push(Infinity);
  return bounds;
}
function applyLowConfMarks() {
  if (!current || !current.pages) return;
  var bounds = pageTextBounds();
  var full = quill.getText();
  current.pages.forEach(function (p, pi) {
    if (!p.low_conf || !p.low_conf.length) return;
    p.low_conf.forEach(function (lc) {
      var t = (lc.text || "").trim();
      if (t.length < 2) return;
      var pos = full.indexOf(t, bounds[pi]);
      if (pos < 0 || pos >= bounds[pi + 1]) return;
      quill.formatText(pos, t.length, "lowconf", true, "silent");
    });
  });
}
var focusData = null;   // {page, box:[x0,y0,x1,y1]}（持久保存，缩放/切页后仍可重绘）
var focusTimer = null;
function drawFocusBox() {
  if (!annotWrapEl) return;
  annotWrapEl.querySelectorAll(".focus-box").forEach(function (n) { n.remove(); });
  if (!focusData || focusData.page !== pageIdx) return;
  var r = annotWrapEl.getBoundingClientRect();
  var p = current && current.pages[pageIdx];
  var w = (p && p.width) || r.width, h = (p && p.height) || r.height;
  var b = focusData.box;
  var div = document.createElement("div");
  div.className = "focus-box";
  div.style.left = (b[0] / w * r.width) + "px";
  div.style.top = (b[1] / h * r.height) + "px";
  div.style.width = ((b[2] - b[0]) / w * r.width) + "px";
  div.style.height = ((b[3] - b[1]) / h * r.height) + "px";
  annotWrapEl.appendChild(div);
}
var sealLayerOn = true;
$("btnSealLayer").onclick = function () {
  sealLayerOn = !sealLayerOn;
  $("btnSealLayer").classList.toggle("active", sealLayerOn);
  renderSealBoxes();
  showToast(sealLayerOn ? "印章图层已显示" : "印章图层已隐藏");
};
function renderSealBoxes() {
  if (!annotWrapEl) return;
  annotWrapEl.querySelectorAll(".seal-box").forEach(function (n) { n.remove(); });
  if (!sealLayerOn || !current || !current.pages[pageIdx] || !current.pages[pageIdx].seals) return;
  var p = current.pages[pageIdx];
  var r = annotWrapEl.getBoundingClientRect();
  var w = p.width || r.width, h = p.height || r.height;
  p.seals.forEach(function (s) {
    var b = s.box;
    var div = document.createElement("div");
    div.className = "seal-box";
    div.style.left = (b[0] / w * r.width) + "px";
    div.style.top = (b[1] / h * r.height) + "px";
    div.style.width = ((b[2] - b[0]) / w * r.width) + "px";
    div.style.height = ((b[3] - b[1]) / h * r.height) + "px";
    var lab = document.createElement("span");
    lab.className = "seal-label";
    lab.textContent = "印章";
    div.appendChild(lab);
    annotWrapEl.appendChild(div);
  });
}
function jumpToPageBox(pageIdx, box, label) {
  if (!current || pageIdx >= current.pages.length) return;
  focusData = { page: pageIdx, box: box };
  gotoPage(pageIdx);
  drawFocusBox();
  if (focusTimer) clearTimeout(focusTimer);
  focusTimer = setTimeout(function () {
    focusData = null;
    drawFocusBox();
  }, 8000);
  if (label) showToast(label);
}
$("editorBox").addEventListener("click", function (e) {
  var el = e.target && e.target.closest ? e.target.closest(".low-conf") : null;
  if (el) {
    var blot = Quill.find(el);
    if (!blot) return;
    var off = blot.offset();
    var txt = quill.getText(off, blot.length()).trim();
    var bounds = pageTextBounds();
    var page = -1;
    for (var i = 0; i < bounds.length - 1; i++) {
      if (off >= bounds[i] && off < bounds[i + 1]) { page = i; break; }
    }
    if (page >= 0 && current.pages[page] && current.pages[page].low_conf) {
      var lc = null;
      current.pages[page].low_conf.forEach(function (x) { if (!lc && x.text.trim() === txt) lc = x; });
      if (lc) jumpToPageBox(page, lc.box, "已定位到第 " + (page + 1) + " 页低置信原文");
    }
    return;
  }
  if (!linkMode) return;
  var pEl = e.target && e.target.closest ? e.target.closest(".ql-editor p, .ql-editor h1, .ql-editor h2, .ql-editor h3") : null;
  if (!pEl) return;
  var lineBlot = Quill.find(pEl);
  if (!lineBlot) return;
  var off2 = lineBlot.offset();
  var bounds2 = pageTextBounds();
  var page2 = -1;
  for (var j = 0; j < bounds2.length - 1; j++) {
    if (off2 >= bounds2[j] && off2 < bounds2[j + 1]) { page2 = j; break; }
  }
  if (page2 < 0) return;
  var lineText = quill.getText(off2, Math.max(0, lineBlot.length() - 1)).trim();
  var hit = null;
  (current.pages[page2].paras || []).forEach(function (para) {
    if (!hit && para.box && (para.box[2] - para.box[0]) > 0 && (para.text || "").indexOf(lineText.slice(0, 10)) >= 0) hit = para;
  });
  if (hit) jumpToPageBox(page2, hit.box, "已定位到第 " + (page2 + 1) + " 页原文");
  else { gotoPage(page2); showToast("已跳到第 " + (page2 + 1) + " 页（该段无原始坐标）"); }
});
var linkMode = false;
$("btnLink").onclick = function () {
  if (!current) { showToast("请先导入文件", "err"); return; }
  linkMode = !linkMode;
  $("btnLink").classList.toggle("active", linkMode);
  $("editorBox").classList.toggle("link-mode", linkMode);
  showToast(linkMode ? "图文对照已开启：鼠标移到段落会有提示框，点击定位到原文" : "图文对照已关闭");
};

// ---- 页面联动 ----
function gotoPage(n) {
  if (!current) return;
  pageIdx = Math.max(0, Math.min(n, current.pages.length - 1));
  renderPage();
  var nodes = $("editorBox").querySelectorAll(".mdun-page-break");
  if (nodes[pageIdx]) nodes[pageIdx].scrollIntoView({ block: "start", behavior: "smooth" });
}
// renderPage 定义见下文（预览层构建）
$("prevPage").onclick = function () { gotoPage(pageIdx - 1); };
$("nextPage").onclick = function () { gotoPage(pageIdx + 1); };

// ---- 工具：行结构 ----
function isPageBreakLine(line) {
  return !!(line.domNode && line.domNode.querySelector && line.domNode.querySelector(".mdun-page-break"));
}
function collectLines() {
  // Quill 2: getLines() 返回 Line 对象数组，offset 经 line.offset() 获取
  var lines = quill.getLines();
  var out = [];
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (!line) continue;
    var off = line.offset();
    var len = line.length();
    var text = quill.getText(off, Math.max(0, len - 1));
    out.push({ line: line, offset: off, length: len, text: text, pageBreak: isPageBreakLine(line) });
  }
  return out;
}

// ---- 标点修复 ----
function repairLineText(text) {
  return fetch("/api/repair", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: text }),
  }).then(function (r) { return r.json(); });
}

// ---- 修复建议面板（可见 + 可逐条还原）----
var puncSuggestions = [];
var REASON_LABELS = {
  "width:ascii2full": "全角转换",
  "conf:cjk-comma": "逗号修正", "conf:cjk-period": "句号修正", "conf:cjk-colon": "冒号修正", "conf:cjk-semicolon": "分号修正",
  "conf:cjk-period-end": "行尾句点", "conf:dedup": "重复标点",
  "pair:quote": "引号配对", "pair:squote": "单引号配对", "pair:mismatch": "括号配对", "pair:close-at-end": "括号补闭",
  "end:add-period": "补句号",
  "sixpoint:open": "六角括号", "sixpoint:close": "六角括号",
  "selection": "选区修复",
};
function renderDiffPanel() {
  var panel = $("diffPanel");
  if (!panel) return;
  var list = $("diffList");
  list.innerHTML = "";
  $("diffCount").textContent = String(puncSuggestions.length);
  panel.classList.toggle("hidden", puncSuggestions.length === 0);
  puncSuggestions.forEach(function (s, i) {
    var row = document.createElement("div");
    row.className = "diff-row";
    var why = document.createElement("span");
    why.className = "why";
    why.textContent = REASON_LABELS[s.reason] || s.reason;
    var del = document.createElement("span");
    del.className = "del";
    del.textContent = s.old || "∅";
    var arrow = document.createElement("span");
    arrow.className = "arrow";
    arrow.textContent = "→";
    var ins = document.createElement("span");
    ins.className = "ins";
    ins.textContent = s.new || "∅";
    var rej = document.createElement("button");
    rej.className = "diff-reject";
    rej.textContent = "还原";
    rej.onclick = function () { rejectSuggestion(i); };
    row.appendChild(why);
    row.appendChild(del);
    row.appendChild(arrow);
    row.appendChild(ins);
    row.appendChild(rej);
    list.appendChild(row);
  });
}
function rejectSuggestion(idx) {
  var s = puncSuggestions[idx];
  if (!s || !quill) return;
  quill.deleteText(s.finalStart, s.new.length, "user");
  if (s.old) quill.insertText(s.finalStart, s.old, "user");
  // 之后位置的建议随本次长度变化平移，保持坐标有效
  var delta = s.old.length - s.new.length;
  for (var i = 0; i < puncSuggestions.length; i++) {
    if (puncSuggestions[i].finalStart > s.finalStart) puncSuggestions[i].finalStart += delta;
  }
  puncSuggestions.splice(idx, 1);
  renderDiffPanel();
  showToast("已还原该处建议");
}
$("btnDiffClose").onclick = function () {
  $("diffPanel").classList.add("hidden");
};

// ---- 存档位置（项目持久化，支持用户指定文件夹）----
function renderStoragePath() {
  fetch("/api/storage", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
    .then(function (r) { return r.json(); }).then(function (d) {
      if (d.path) {
        $("storagePath").textContent = d.path;
        $("storagePath").title = d.path;
      }
    }).catch(function () {});
}
$("btnStorage").onclick = function () {
  $("storageEdit").classList.toggle("hidden");
  if (!$("storageEdit").classList.contains("hidden")) $("storageInput").value = $("storagePath").textContent;
};
$("btnStorageCancel").onclick = function () { $("storageEdit").classList.add("hidden"); };
function applyStoragePath(p) {
  fetch("/api/storage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: p }),
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) throw new Error(d.error);
    $("storageEdit").classList.add("hidden");
    renderStoragePath();
    showToast("存档位置已改为：" + d.path + (d.moved ? "（迁移 " + d.moved + " 个项目）" : ""), "ok");
  }).catch(function (e) { showToast("设置失败: " + e.message, "err"); });
}
$("btnStorageSave").onclick = function () {
  var p = $("storageInput").value.trim();
  if (!p) { showToast("请输入或选择文件夹", "err"); return; }
  applyStoragePath(p);
};
$("btnStoragePick").onclick = function () {
  showToast("正在打开系统文件夹选择框…");
  fetch("/api/pick_folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
    .then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) throw new Error(d.error);
      if (d.canceled) { showToast("已取消选择"); return; }
      $("storageInput").value = d.path;
      applyStoragePath(d.path);
    }).catch(function (e) { showToast("选择文件夹失败: " + e.message, "err"); });
};
renderStoragePath();

// ---- 开源软件许可（任务栏底部入口，点击展示）----
$("btnLicenses").onclick = function () {
  $("licenseModal").classList.remove("hidden");
};
$("btnLicenseClose").onclick = function () {
  $("licenseModal").classList.add("hidden");
};
$("licenseModal").addEventListener("click", function (e) {
  if (e.target === $("licenseModal")) $("licenseModal").classList.add("hidden");
});

$("btnPunc").onclick = function () {
  if (!current) return;
  var lines = collectLines().filter(function (l) { return !l.pageBreak && l.text.trim(); });
  pushVersion("标点修复前");
  showToast("标点修复中（" + lines.length + " 行）…");
  var idx = 0;
  var windowSize = 6;
  var results = [];
  function worker() {
    if (idx >= lines.length) return Promise.resolve();
    var l = lines[idx++];
    return repairLineText(l.text).then(function (d) {
      results.push({ line: l, data: d });
      return worker();
    });
  }
  var tasks = [];
  for (var i = 0; i < Math.min(windowSize, lines.length); i++) tasks.push(worker());
  Promise.all(tasks).then(function () {
    var changes = results.filter(Boolean).filter(function (r) { return r.data.text !== r.line.text; });
    var suggestions = [];
    changes.forEach(function (r) {
      (r.data.edits || []).forEach(function (e) {
        suggestions.push({
          start: r.line.offset + e.start, end: r.line.offset + e.end,
          old: e.old, new: e.new, reason: e.reason, finalStart: 0,
        });
      });
    });
    // 应用后坐标：按绝对位置升序累计长度漂移
    suggestions.sort(function (a, b) { return a.start - b.start; });
    var shift = 0;
    suggestions.forEach(function (s) {
      s.finalStart = s.start + shift;
      shift += s.new.length - (s.end - s.start);
    });
    // 应用（整行替换，自底向上）
    changes.sort(function (a, b) { return b.line.offset - a.line.offset; });
    changes.forEach(function (r) {
      var l = r.line;
      var fmts = quill.getFormat(l.offset, 1);
      quill.deleteText(l.offset, l.length - 1);
      quill.insertText(l.offset, r.data.text, fmts);
    });
    puncSuggestions = suggestions;
    renderDiffPanel();
    showToast("标点修复完成：" + changes.length + " 行有修改，共 " + suggestions.length + " 处建议（面板可逐条还原）", suggestions.length ? "ok" : undefined);
  }).catch(function (e) { showToast("修复失败: " + e.message, "err"); });
};

$("btnPuncSel").onclick = function () {
  if (!current) return;
  var sel = quill.getSelection();
  if (!sel || sel.length === 0) { showToast("请先选中要修复的文字", "err"); return; }
  var text = quill.getText(sel.index, sel.length);
  repairLineText(text).then(function (d) {
    if (d.text === text) { showToast("选区无需修复"); return; }
    pushVersion("选区修复前");
    quill.deleteText(sel.index, sel.length);
    quill.insertText(sel.index, d.text);
    puncSuggestions = [{ start: sel.index, end: sel.index + text.length, old: text, new: d.text, reason: "selection", finalStart: sel.index }];
    renderDiffPanel();
    showToast("选区修复完成（" + d.edits.length + " 处）", d.edits.length ? "ok" : undefined);
  });
};

// ---- 段落快捷修复 ----
var TERMINAL = /[。！？…"”』」；：]$/;
var PAGE_LIKE = /^\s*(?:第\s*\d+\s*页(?:\s*共\s*\d+\s*页)?|-\s*\d+\s*-|\d{1,4})\s*$/;
// 多级标题：一、 （一） 1. 1、 ① 第X章/节/条
var HEAD_RE = /^(?:[（(][一二三四五六七八九十]{1,3}[)）]|[一二三四五六七八九十]{1,3}、|\d{1,2}[.、]|第[一二三四五六七八九十\d]{1,4}[章节条款]|[①②③④⑤⑥⑦⑧⑨⑩])/;
var HEAD_ANY = /(?:[（(][一二三四五六七八九十]{1,3}[)）]|[一二三四五六七八九十]{1,3}、|\d{1,2}[.、]|第[一二三四五六七八九十\d]{1,4}[章节条款]|[①②③④⑤⑥⑦⑧⑨⑩])/;
$("btnPara").onclick = function () {
  if (!current) return;
  pushVersion("段落修复前");
  var lines = collectLines();
  var plan = [];
  var removed = 0, merged = 0, heads = 0;
  for (var i = 0; i < lines.length; i++) {
    var l = lines[i];
    if (l.pageBreak) continue;
    if (!l.text.trim()) continue;
    var t = l.text.trim();
    if (PAGE_LIKE.test(t) && t.length <= 12) {
      plan.push({ type: "del", offset: l.offset, length: l.length });
      removed++;
      continue;
    }
    // 行首即标题：独立成段，不参与合并
    if (HEAD_RE.test(t)) {
      heads++;
      continue;
    }
    // 行内出现标题：拆分为新段落（去掉标题前的空白）
    var hm = HEAD_ANY.exec(t);
    if (hm && hm.index > 0) {
      var killPrev = (t[hm.index - 1] === " " || t[hm.index - 1] === "　") ? 1 : 0;
      plan.push({ type: "split", offset: l.offset + hm.index, killPrev: killPrev });
      heads++;
      continue;
    }
    if (i > 0) {
      var prev = lines[i - 1];
      if (!prev.pageBreak && prev.text.trim() && !TERMINAL.test(prev.text.trim()) &&
          !HEAD_RE.test(prev.text.trim()) &&
          !/^[\s　]/.test(l.text) && l.text.trim().length > 1) {
        plan.push({ type: "merge", offset: prev.offset + prev.length - 1, length: 1 });
        merged++;
      }
    }
  }
  plan.sort(function (a, b) { return b.offset - a.offset; });
  plan.forEach(function (p) {
    if (p.type === "split") {
      if (p.killPrev) quill.deleteText(p.offset - p.killPrev, p.killPrev);
      quill.insertText(p.offset - (p.killPrev || 0), "\n");
    } else {
      quill.deleteText(p.offset, p.length);
    }
  });
  showToast("段落修复完成：合并碎行 " + merged + " 处，删除页码/页脚 " + removed + " 处，标题单独成段 " + heads + " 处");
};

$("btnUndoFix").onclick = function () {
  if (!current) return;
  quill.history.undo();
  showToast("已撤销上一步");
};

// ---- 繁体转简体（opencc 本地词典）----
$("btnT2S").onclick = function () {
  if (!current) return;
  var lines = collectLines().filter(function (l) { return !l.pageBreak && l.text.trim(); });
  if (!lines.length) { showToast("没有可转换的文字"); return; }
  pushVersion("繁转简前");
  showToast("繁体转简体中…");
  fetch("/api/t2s", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texts: lines.map(function (l) { return l.text; }) }),
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) throw new Error(d.error);
    var changed = 0;
    for (var i = lines.length - 1; i >= 0; i--) {
      var l = lines[i];
      var nt = d.texts[i] || l.text;
      if (nt !== l.text) {
        var fmts = quill.getFormat(l.offset, 1);
        quill.deleteText(l.offset, l.length - 1);
        quill.insertText(l.offset, nt, fmts);
        changed++;
      }
    }
    showToast("繁转简完成：" + changed + " 行有变化", changed ? "ok" : undefined);
  }).catch(function (e) { showToast("繁转简失败: " + e.message, "err"); });
};

// ---- 导出：单按钮，点击弹出格式选择（保存编辑 → 导出）----
// ---- 目录生成（标题 + 页码）----
var tocOn = false;
var HEAD_ANY_TOC = /^(?:[（(][一二三四五六七八九十]{1,3}[)）]|[一二三四五六七八九十]{1,3}、|\d{1,2}[.、]|第[一二三四五六七八九十\d]{1,4}[章节条款]|[①②③④⑤⑥⑦⑧⑨⑩])/;
$("btnToc").onclick = function () {
  if (!current) { showToast("请先导入文件", "err"); return; }
  tocOn = !tocOn;
  $("btnToc").classList.toggle("active", tocOn);
  if (tocOn) {
    var n = buildToc().length;
    showToast("目录已开启：导出 Word 时自动生成（识别到 " + n + " 个标题）", n ? "ok" : undefined);
  } else {
    showToast("目录已关闭");
  }
};
function buildToc() {
  var out = [];
  var page = 0;
  var ops = quill.getContents().ops;
  var buf = "";
  function flush(attrs) {
    var t = buf.trim();
    buf = "";
    if (!t) return;
    var level = 0;
    if (attrs && attrs.header) level = parseInt(attrs.header, 10) || 0;
    else if (HEAD_ANY_TOC.test(t)) level = 2;
    if (level > 0 && t.length <= 60) out.push({ level: level, text: t, page: page + 1 });
  }
  ops.forEach(function (op) {
    if (typeof op.insert === "object" && op.insert && op.insert.mdunPage !== undefined) {
      flush(null);
      page = op.insert.mdunPage;
      return;
    }
    if (typeof op.insert === "string") {
      var parts = op.insert.split("\n");
      for (var i = 0; i < parts.length; i++) {
        if (i > 0) { flush(op.attributes); }
        buf += parts[i];
      }
      return;
    }
    flush(null);
  });
  flush(null);
  return out;
}

function doExport(fmt) {
  if (!current) { showToast("请先导入文件", "err"); return; }
  var ops = quill.getContents().ops;
  var payload = { id: current.id, ops: ops };
  if (fmt === "docx" && tocOn) payload.toc = buildToc();
  fetch("/api/save_edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(function (r) { return r.json(); }).then(function (s) {
    if (s.error) throw new Error(s.error);
    return fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: current.id, format: fmt, toc: payload.toc || null }),
    }).then(function (r) { return r.json(); });
  }).then(function (d) {
    if (d.file) {
      showToast("已导出: " + d.filename, "ok");
      if (d.download) {
        var a = document.createElement("a");
        a.href = d.download;
        a.download = d.filename || "";
        document.body.appendChild(a);
        a.click();
        a.remove();
      }
    } else {
      showToast("导出失败: " + (d.error || "未知错误"), "err");
    }
  }).catch(function (e) { showToast("导出失败: " + e.message, "err"); });
}
$("btnExport").onclick = function (e) {
  if (!current) { showToast("请先导入文件", "err"); return; }
  e.stopPropagation();
  $("exportMenu").classList.toggle("hidden");
};
document.addEventListener("click", function (e) {
  var menu = $("exportMenu");
  if (menu.classList.contains("hidden")) return;
  // 命中按钮内图标（svg）也算点按钮，否则菜单刚开即关
  if (!menu.contains(e.target) && !$("btnExport").contains(e.target)) menu.classList.add("hidden");
});
document.querySelectorAll(".export-menu button").forEach(function (b) {
  b.onclick = function () {
    $("exportMenu").classList.add("hidden");
    doExport(b.getAttribute("data-fmt"));
  };
});

listProjects();

// ---- 三栏拖拽调宽（localStorage 持久化）----
(function initSplitters() {
  var MIN = { aside: 140, viewer: 240, editor: 320 };
  var KEY = "octo-layout";
  var saved = null;
  try { saved = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) {}
  if (saved && typeof saved.aside === "number" && typeof saved.viewer === "number") {
    $("projectList").style.width = Math.max(MIN.aside, saved.aside) + "px";
    $("viewer").style.width = Math.max(MIN.viewer, saved.viewer) + "px";
  }
  function setup(handleId, leftId, rightId) {
    var handle = $(handleId);
    handle.addEventListener("mousedown", function (e) {
      e.preventDefault();
      handle.classList.add("dragging");
      var left = $(leftId), right = $(rightId);
      var startX = e.clientX;
      var startL = left.getBoundingClientRect().width;
      var startR = right.getBoundingClientRect().width;
      function onMove(ev) {
        var dx = ev.clientX - startX;
        // 双向钳制：两侧都尊重最小宽度，总宽不变（修复单侧钳制导致宽度漂移）
        var minL = MIN[leftId] || 140, minR = MIN[rightId] || 300;
        var newR = Math.max(minR, startR - dx);
        var newL = Math.max(minL, startL + startR - newR);
        left.style.width = newL + "px";
        right.style.width = newR + "px";
        save();
      }
      function onUp() {
        handle.classList.remove("dragging");
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }
  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify({
        aside: $("projectList").getBoundingClientRect().width,
        viewer: $("viewer").getBoundingClientRect().width,
      }));
    } catch (e) {}
  }
  setup("splitA", "projectList", "viewer");
  setup("splitB", "viewer", "editor");
})();

// ---- 特殊格式识别（手动触发：低阈值重扫当前页表格/公式）----
$("btnDetect").onclick = function () {
  if (!current) { showToast("请先导入文件", "err"); return; }
  showToast("正在重扫第 " + (pageIdx + 1) + " 页的表格/公式…");
  fetch("/api/detect_regions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: current.id, page: pageIdx }),
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) throw new Error(d.error);
    var cand = d.candidates || [];
    var summary = cand.slice(0, 6).map(function (c) { return c.type + " " + c.score.toFixed(2); }).join(", ");
    showToast("识别完成：表格 " + d.tables + " 个，公式 " + d.formulas + " 个" +
      (summary ? "（候选: " + summary + (cand.length > 6 ? "…" : "") + "）" : ""),
      d.tables + d.formulas > 0 ? "ok" : undefined);
    // 重新拉取项目并重建编辑器（更新表格/公式结构块）
    fetch("/api/project/" + current.id).then(function (r) { return r.json(); }).then(function (proj) {
      openProject(proj);
    });
  }).catch(function (e) {
    showToast("特殊格式识别失败: " + e.message, "err");
  });
};

// ---- 拼写检查（中文易错词对 + 英文 SymSpell，红色波浪线标记，点击替换）----
function clearSpellMarks() {
  var nodes = $("editorBox").querySelectorAll(".spell-err");
  nodes.forEach(function (n) {
    var blot = Quill.find(n);
    if (blot) quill.formatText(blot.offset(), blot.length(), "spell", false, "silent");
  });
}
// delta 双坐标系：embed 在 delta 占 1 索引、在纯文本占 0 字符
function deltaTextMap() {
  var ops = quill.getContents().ops;
  var text = "";
  var map = [];
  var di = 0;
  ops.forEach(function (op) {
    var ins = op.insert;
    if (typeof ins === "string") {
      for (var k = 0; k < ins.length; k++) { map.push(di + k); }
      text += ins;
      di += ins.length;
    } else if (ins && typeof ins === "object") {
      di += 1;
    }
  });
  return { text: text, map: map };
}
$("btnSpell").onclick = function () {
  if (!current) { showToast("请先导入文件", "err"); return; }
  clearSpellMarks();
  var tm = deltaTextMap();
  showToast("拼写检查中…");
  fetch("/api/spellcheck", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: tm.text }),
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) throw new Error(d.error);
    var items = d.items || [];
    items.slice().sort(function (a, b) { return b.start - a.start; }).forEach(function (it) {
      var ds = tm.map[it.start];
      var de = it.end < tm.map.length ? tm.map[it.end - 1] + 1 : quill.getLength() - 1;
      quill.formatText(ds, de - ds, "spell",
        { word: it.word, suggestions: it.suggestions }, "silent");
    });
    var zh = items.filter(function (i) { return i.lang === "zh"; }).length;
    var en = items.length - zh;
    showToast("拼写检查：发现 " + items.length + " 处（中文 " + zh + " / 英文 " + en + "），点击波浪线词替换",
      items.length ? "ok" : undefined);
  }).catch(function (e) { showToast("拼写检查失败: " + e.message, "err"); });
};
$("editorBox").addEventListener("click", function (e) {
  var t = e.target && e.target.closest ? e.target.closest(".spell-err") : null;
  if (!t) return;
  var sugg = JSON.parse(t.getAttribute("data-sug") || "[]");
  if (!sugg.length) return;
  var blot = Quill.find(t);
  if (!blot) return;
  var start = quill.getIndex(blot);
  var len = blot.length();
  var Delta = Quill.import("delta");
  quill.updateContents(new Delta().retain(start).delete(len).insert(sugg[0]), "user");
  showToast("已替换: " + t.getAttribute("data-word") + " → " + sugg[0], "ok");
});

// ---- 任务栏收纳（左缘把手展开）----
(function initSideCollapse() {
  var s = $("projectList");
  var btn = $("btnCollapseSide");
  var tab = $("btnExpandSide");
  function render() {
    var collapsed = s.classList.contains("collapsed");
    btn.innerHTML = '<span class="icn">' + ICONS[collapsed ? "chevrons-right" : "chevrons-left"] + "</span>";
    tab.classList.toggle("hidden", !collapsed);
    $("splitA").classList.toggle("hidden", collapsed);
  }
  function setCollapsed(collapsed) {
    if (collapsed) {
      s.dataset.prevWidth = s.style.width || "190px";
      s.classList.add("collapsed");
      s.style.width = "0px";
    } else {
      s.classList.remove("collapsed");
      s.style.width = s.dataset.prevWidth || "190px";
    }
    try {
      localStorage.setItem("octo-side-collapsed", collapsed ? "1" : "0");
      localStorage.setItem("octo-side-prev", s.dataset.prevWidth || "190px");
    } catch (e) {}
    render();
  }
  try {
    if (localStorage.getItem("octo-side-collapsed") === "1") {
      s.dataset.prevWidth = localStorage.getItem("octo-side-prev") || "190px";
      s.classList.add("collapsed");
      s.style.width = "0px";
      $("splitA").classList.add("hidden");
    }
  } catch (e) {}
  btn.onclick = function () { setCollapsed(!s.classList.contains("collapsed")); };
  tab.onclick = function () { setCollapsed(false); };
  render();
})();

// ---- 预览栏折叠（header 按钮收起 + 常驻把手展开）----
(function initCollapse() {
  var v = $("viewer");
  var btn = $("btnCollapse");
  var tab = $("btnExpand");
  function render() {
    var collapsed = v.classList.contains("collapsed");
    btn.innerHTML = '<span class="icn">' + ICONS[collapsed ? "chevrons-right" : "chevrons-left"] + "</span>";
    tab.classList.toggle("hidden", !collapsed);
  }
  function setCollapsed(collapsed) {
    if (collapsed) {
      v.dataset.prevWidth = v.style.width || "30%";
      v.classList.add("collapsed");
      v.style.width = "0px";
    } else {
      v.classList.remove("collapsed");
      v.style.width = v.dataset.prevWidth || "30%";
    }
    try {
      localStorage.setItem("octo-viewer-collapsed", collapsed ? "1" : "0");
      localStorage.setItem("octo-viewer-prev", v.dataset.prevWidth || "30%");
    } catch (e) {}
    render();
  }
  try {
    if (localStorage.getItem("octo-viewer-collapsed") === "1") {
      v.dataset.prevWidth = localStorage.getItem("octo-viewer-prev") || "30%";
      v.classList.add("collapsed");
      v.style.width = "0px";
    }
  } catch (e) {}
  btn.onclick = function () { setCollapsed(!v.classList.contains("collapsed")); };
  tab.onclick = function () { setCollapsed(false); };
  render();
})();

// ---- 查找 / 替换（全文，含表格块文本映射）----
var SearchHitBlot = null;
(function () {
  var Inline2 = Quill.import("blots/inline");
  class SearchHit extends Inline2 {
    static create(value) {
      var node = super.create();
      node.classList.add("search-hit");
      if (value && value.cur) node.classList.add("search-current");
      return node;
    }
    static formats(node) {
      return { cur: node.classList.contains("search-current") };
    }
  }
  SearchHit.blotName = "search";
  SearchHit.tagName = "span";
  Quill.register({ "formats/search": SearchHit }, true);
  SearchHitBlot = SearchHit;
})();

var findState = { matches: [], idx: -1, query: "" };
function runFind() {
  var q = $("findInput").value;
  clearFindMarks();
  findState = { matches: [], idx: -1, query: q };
  if (!q || !current) { updateFindCount(); return; }
  var tm = deltaTextMap();
  var lower = tm.text.toLowerCase();
  var ql = q.toLowerCase();
  var pos = 0;
  while (pos < lower.length) {
    var i = lower.indexOf(ql, pos);
    if (i < 0) break;
    var ds = tm.map[i];
    var de = (i + q.length) < tm.map.length ? tm.map[i + q.length - 1] + 1 : quill.getLength() - 1;
    findState.matches.push({ ds: ds, de: de });
    pos = i + Math.max(q.length, 1);
  }
  findState.matches.forEach(function (m, i) {
    quill.formatText(m.ds, m.de - m.ds, "search", { cur: i === 0 }, "silent");
  });
  if (findState.matches.length) findState.idx = 0;
  updateFindCount();
}
function clearFindMarks() {
  var nodes = $("editorBox").querySelectorAll(".search-hit");
  nodes.forEach(function (n) {
    var blot = Quill.find(n);
    if (blot) quill.formatText(blot.offset(), blot.length(), "search", false, "silent");
  });
}
function updateFindCount() {
  $("findCount").textContent = findState.matches.length
    ? (findState.idx + 1) + "/" + findState.matches.length
    : "0/0";
}
function setCurrentFind(idx) {
  if (!findState.matches.length) return;
  var old = findState.matches[findState.idx];
  if (old) quill.formatText(old.ds, old.de - old.ds, "search", { cur: false }, "silent");
  findState.idx = idx;
  var m = findState.matches[idx];
  quill.formatText(m.ds, m.de - m.ds, "search", { cur: true }, "silent");
  quill.setSelection(m.ds, m.de - m.ds, "silent");
  updateFindCount();
}
function doReplace(oneOnly) {
  if (!findState.matches.length) { showToast("没有可替换的匹配", "err"); return; }
  var rep = $("replaceInput").value;
  var Delta = Quill.import("delta");
  if (oneOnly) {
    var m = findState.matches[findState.idx];
    quill.updateContents(new Delta().retain(m.ds).delete(m.de - m.ds).insert(rep), "user");
    showToast("已替换当前匹配");
  } else {
    var delta = new Delta();
    var ms = findState.matches.slice().reverse();
    ms.forEach(function (m) {
      delta.retain(m.ds - (delta.length() - 0));
      // 简化：逐次构建完整 delta
    });
    // 直接用循环 updateContents（倒序替换）
    ms.forEach(function (m) {
      quill.updateContents(new Delta().retain(m.ds).delete(m.de - m.ds).insert(rep), "silent");
    });
    quill.updateContents(new Delta(), "user");
    showToast("已全部替换 " + ms.length + " 处", "ok");
  }
  runFind();
}
$("btnFind").onclick = function () {
  if (!current) { showToast("请先导入文件", "err"); return; }
  $("searchBar").classList.toggle("hidden");
  if (!$("searchBar").classList.contains("hidden")) { $("findInput").focus(); runFind(); }
  else clearFindMarks();
};
$("btnReplace").onclick = function () { $("searchBar").classList.remove("hidden"); $("findInput").focus(); };
$("btnFindClose").onclick = function () { $("searchBar").classList.add("hidden"); clearFindMarks(); };
$("findInput").addEventListener("input", runFind);
$("findInput").addEventListener("keydown", function (e) {
  if (e.key === "Enter") {
    e.preventDefault();
    if (!findState.matches.length) return;
    setCurrentFind((findState.idx + (e.shiftKey ? -1 : 1) + findState.matches.length) % findState.matches.length);
  }
});
$("btnFindPrev").onclick = function () {
  if (findState.matches.length) setCurrentFind((findState.idx - 1 + findState.matches.length) % findState.matches.length);
};
$("btnFindNext").onclick = function () {
  if (findState.matches.length) setCurrentFind((findState.idx + 1) % findState.matches.length);
};
$("btnReplaceOne").onclick = function () { doReplace(true); };
$("btnReplaceAll").onclick = function () { doReplace(false); };

// ---- 标注跳过区域 ----
var annotMode = false;
var annotBoxes = [];   // 归一化 {x0,y0,x1,y1}
var annotDrag = null;
function renderPage() {
  if (!current) return;
  var p = current.pages[pageIdx];
  $("pageNo").textContent = (pageIdx + 1) + " / " + current.pages.length;
  $("pageInfo").textContent = "第 " + (pageIdx + 1) + " 页 · 引擎 " + current.engine + " · 置信度 " + (p.conf_avg || "-") + ((p.seals && p.seals.length) ? " · 印章 " + p.seals.length + " 处" : "");
  var wrap = document.createElement("div");
  wrap.className = "img-wrap";
  var img = document.createElement("img");
  img.src = "/api/page_image/" + current.id + "/" + pageIdx + "?v=" + Date.now();
  img.alt = "页面";
  wrap.appendChild(img);
  var wm = document.createElement("div");
  wm.className = "wm-layer";
  wm.style.backgroundImage = "url(" + buildWatermarkSvg(pageIdx + 1) + ")";
  wrap.appendChild(wm);
  var layer = document.createElement("div");
  layer.className = "annot-layer" + (annotMode ? "" : " hidden");
  wrap.appendChild(layer);
  annotLayerEl = layer;
  annotWrapEl = wrap;
  $("imageBox").innerHTML = "";
  $("imageBox").appendChild(wrap);
  initAnnotBoxes();
  applyZoom();
  // 等图片加载完成（尺寸确定）再应用缩放并绘制标注框，避免错位
  img.onload = function () {
    applyZoom();
    if (pendingFit) { pendingFit = false; $("btnZoomFit").onclick(); }
    drawFocusBox();
    renderSealBoxes();
  };
  if (img.complete && img.naturalWidth) { applyZoom(); renderAnnotBoxes(); drawFocusBox(); renderSealBoxes(); }
}
var annotLayerEl = null, annotWrapEl = null;
// ---- 预览页防截图水印：口号 + 时间戳 + 页码，平铺斜纹覆盖整页 ----
function buildWatermarkSvg(pageNum) {
  var d = new Date();
  function p2(n) { return (n < 10 ? "0" : "") + n; }
  var ts = d.getFullYear() + "-" + p2(d.getMonth() + 1) + "-" + p2(d.getDate()) + " " + p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" + p2(d.getSeconds());
  var line = "涉密不上网 · 上网不涉密        " + ts + " · 第 " + pageNum + " 页";
  function escXml(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;"); }
  var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="320"><defs><pattern id="wm" width="480" height="320" patternUnits="userSpaceOnUse"><text transform="rotate(-28 240 160)" x="240" y="160" text-anchor="middle" fill="#8f99a8" fill-opacity="0.30" font-size="15" font-family="PingFang SC, Microsoft YaHei, sans-serif">' + escXml(line) + '</text></pattern></defs><rect width="100%" height="100%" fill="url(#wm)"/></svg>';
  // 注意：encodeURIComponent 不转义 ( ) '，而 url() 中的括号会截断 CSS 声明，必须手工转义
  return "data:image/svg+xml," + encodeURIComponent(svg).replace(/\(/g, "%28").replace(/\)/g, "%29").replace(/'/g, "%27");
}
setInterval(function () {
  var wm = document.querySelector("#imageBox .wm-layer");
  if (wm && current) wm.style.backgroundImage = "url(" + buildWatermarkSvg(pageIdx + 1) + ")";
}, 30000);
function initAnnotBoxes() {
  var regions = current && current.pages[pageIdx] && current.pages[pageIdx].ignore_regions
    ? current.pages[pageIdx].ignore_regions : [];
  annotBoxes = regions.map(function (r) { return { x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1 }; });
}
function renderAnnotBoxes() {
  if (!annotWrapEl) return;
  annotWrapEl.querySelectorAll(".anno-box, .anno-chip").forEach(function (n) { n.remove(); });
  annotBoxes.forEach(function (b) { drawAnnoBox(b, true); });
  renderAnnotChip();
  updateAnnotHint();
}
function updateAnnotHint() {
  var el = $("apHint");
  if (!el) return;
  el.textContent = annotBoxes.length > 0
    ? "已画 " + annotBoxes.length + " 个框 · 点击框可删除"
    : "拖拽框选范围 · 点击框可删除";
}
function drawAnnoBox(b, fixed) {
  var r = annotWrapEl.getBoundingClientRect();
  var w = r.width, h = r.height;
  var div = document.createElement("div");
  div.className = "anno-box" + (fixed ? " fixed" : "") + (fixed && annotMode ? " deletable" : "");
  div.style.left = (b.x0 * w) + "px";
  div.style.top = (b.y0 * h) + "px";
  div.style.width = ((b.x1 - b.x0) * w) + "px";
  div.style.height = ((b.y1 - b.y0) * h) + "px";
  if (fixed && annotMode) {
    div.title = "点击删除该标注框";
    div.addEventListener("click", function (e) {
      e.stopPropagation();
      annotBoxes = annotBoxes.filter(function (x) {
        return !(Math.abs(x.x0 - b.x0) < 0.001 && Math.abs(x.y0 - b.y0) < 0.001 &&
                 Math.abs(x.x1 - b.x1) < 0.001 && Math.abs(x.y1 - b.y1) < 0.001);
      });
      renderAnnotBoxes();
      showToast("已删除该标注框");
    });
  }
  annotWrapEl.appendChild(div);
}
function renderAnnotChip() {
  if (!annotMode || !annotWrapEl || !annotBoxes.length) return;
  var b = annotBoxes[annotBoxes.length - 1];
  var r = annotWrapEl.getBoundingClientRect();
  var chip = document.createElement("button");
  chip.className = "anno-chip";
  chip.title = "识别该区域（表格/公式/文字）";
  chip.innerHTML = '<span class="icn"></span> 识别该区域';
  chip.querySelector(".icn").innerHTML = ICONS["scan-text"];
  annotWrapEl.appendChild(chip);
  chip.style.left = Math.max(4, b.x1 * r.width - chip.offsetWidth - 6) + "px";
  chip.style.top = (b.y0 * r.height + 6) + "px";
  chip.addEventListener("click", function (e) {
    e.stopPropagation();
    recognizeRegion(b);
  });
}
var annotDragBound = false;
function setupAnnotDrag() {
  if (annotDragBound) return;
  annotDragBound = true;
  // 事件委托：mousedown 绑在 document 上，翻页重建图层后依然可用
  document.addEventListener("mousedown", function (e) {
    if (!annotMode || !annotLayerEl || !annotWrapEl) return;
    if (!annotLayerEl.contains(e.target)) return;
    var r = annotWrapEl.getBoundingClientRect();
    annotDrag = { x0: (e.clientX - r.left) / r.width, y0: (e.clientY - r.top) / r.height,
                  x1: (e.clientX - r.left) / r.width, y1: (e.clientY - r.top) / r.height };
    e.preventDefault();
  });
  document.addEventListener("mousemove", function (e) {
    if (!annotDrag || !annotWrapEl) return;
    var r = annotWrapEl.getBoundingClientRect();
    annotDrag.x1 = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    annotDrag.y1 = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
    renderAnnotBoxes();
    if (Math.abs(annotDrag.x1 - annotDrag.x0) > 0.005 || Math.abs(annotDrag.y1 - annotDrag.y0) > 0.005) {
      drawAnnoBox({ x0: Math.min(annotDrag.x0, annotDrag.x1), y0: Math.min(annotDrag.y0, annotDrag.y1),
                    x1: Math.max(annotDrag.x0, annotDrag.x1), y1: Math.max(annotDrag.y0, annotDrag.y1) }, false);
    }
  });
  document.addEventListener("mouseup", function () {
    if (!annotDrag) return;
    var b = { x0: Math.min(annotDrag.x0, annotDrag.x1), y0: Math.min(annotDrag.y0, annotDrag.y1),
              x1: Math.max(annotDrag.x0, annotDrag.x1), y1: Math.max(annotDrag.y0, annotDrag.y1) };
    if ((b.x1 - b.x0) > 0.008 && (b.y1 - b.y0) > 0.008) {
      annotBoxes.push(b);
      renderAnnotBoxes();
    }
    annotDrag = null;
  });
}
var annotRegionMode = "exclude";   // 当前标注策略：跳过选区 / 仅识别选区
function setApMode() {
  $("apModeExclude").classList.toggle("active", annotRegionMode === "exclude");
  $("apModeInclude").classList.toggle("active", annotRegionMode === "include");
}
$("apModeExclude").onclick = function () { annotRegionMode = "exclude"; setApMode(); };
$("apModeInclude").onclick = function () { annotRegionMode = "include"; setApMode(); };
$("btnAnnotate").onclick = function () {
  if (!current) { showToast("请先导入文件", "err"); return; }
  annotMode = !annotMode;
  $("btnAnnotate").classList.toggle("active", annotMode);
  $("annotPanel").classList.toggle("hidden", !annotMode);
  if (annotMode) showToast("标注模式：拖拽框选范围，点击已画框可删除");
  renderPage();
  setupAnnotDrag();
};
$("btnAnnotSave").onclick = function () {
  if (!current) return;
  pushVersion("标注应用前");
  var mode = annotRegionMode;
  fetch("/api/region_mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: current.id, page: pageIdx, mode: mode, boxes: annotBoxes,
                           apply_all: $("annotApplyAll").checked }),
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) throw new Error(d.error);
    var modeName = { exclude: "跳过选区", include: "仅识别选区", full: "恢复全文" }[d.mode] || d.mode;
    showToast(modeName + "已生效，处理 " + d.removed + " 处文本（" + (d.pages > 1 ? "全部页" : "本页") + "）", "ok");
    fetch("/api/project/" + current.id).then(function (r) { return r.json(); }).then(function (proj) {
      openProject(proj, true);
      if (annotMode) { renderPage(); setupAnnotDrag(); }
    });
  }).catch(function (e) { showToast("保存标注失败: " + e.message, "err"); });
};
$("btnAnnotClear").onclick = function () {
  if (!current) return;
  fetch("/api/region_mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: current.id, page: pageIdx, mode: "full", boxes: [], apply_all: $("annotApplyAll").checked }),
  }).then(function (r) { return r.json(); }).then(function () {
    showToast("标注已清除（恢复全文）", "ok");
    fetch("/api/project/" + current.id).then(function (r) { return r.json(); }).then(function (proj) {
      openProject(proj, true);
      if (annotMode) { renderPage(); setupAnnotDrag(); }
    });
  });
};
$("btnAnnotDone").onclick = function () {
  annotMode = false;
  $("annotPanel").classList.add("hidden");
  $("btnAnnotate").classList.remove("active");
  renderPage();
};

// ---- 预览缩放 ----
var zoomScale = 1;
function applyZoom() {
  var img = document.querySelector("#imageBox img");
  if (img && img.naturalWidth) {
    img.style.width = Math.max(20, Math.round(img.naturalWidth * zoomScale)) + "px";
    img.style.height = "auto";
  }
  $("zoomPct").textContent = Math.round(zoomScale * 100) + "%";
  renderAnnotBoxes();
  renderSealBoxes();
  drawFocusBox();
}
function setZoom(s) {
  zoomScale = Math.max(0.3, Math.min(4, s));
  applyZoom();
}
$("btnZoomIn").onclick = function () { setZoom(zoomScale * 1.25); };
$("btnZoomOut").onclick = function () { setZoom(zoomScale / 1.25); };
var pendingFit = false;
$("btnZoomFit").onclick = function () {
  var img = document.querySelector("#imageBox img");
  var box = $("imageBox");
  if (!img || !img.naturalWidth) { pendingFit = true; return; }
  var availW = Math.max(40, box.clientWidth - 28);
  var availH = Math.max(40, box.clientHeight - 28);
  setZoom(Math.min(availW / img.naturalWidth, availH / img.naturalHeight, 1));
};
(function initZoomWheel() {
  $("imageBox").addEventListener("wheel", function (e) {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    setZoom(zoomScale * (e.deltaY < 0 ? 1.1 : 0.9));
  }, { passive: false });
})();


// ---- 局部重新识别（框选区域 → 表格/公式；入口为框角浮钮）----
function recognizeRegion(b) {
  if (!current) { showToast("请先导入文件", "err"); return; }
  showToast("正在识别该区域（表格/公式）…");
  fetch("/api/recognize_region", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: current.id, page: pageIdx, box: [b.x0, b.y0, b.x1, b.y1] }),
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) throw new Error(d.error);
    if (d.tables > 0) showToast("区域识别为表格（" + d.tables + " 个），已加入项目", "ok");
    else if (d.formulas > 0) showToast("区域识别为公式：" + d.latex.slice(0, 40), "ok");
    else if (d.text) showToast("区域识别为文字，已加入文档：" + d.text.slice(0, 30) + (d.text.length > 30 ? "…" : ""), "ok");
    else showToast("该区域未识别出表格、公式或文字");
    pushVersion("区域识别前");
    fetch("/api/project/" + current.id).then(function (r) { return r.json(); }).then(function (proj) {
      openProject(proj, true);
      renderPage();
      setupAnnotDrag();
      if (d.text || d.tables > 0 || d.formulas > 0) showRegionView(d);
    });
  }).catch(function (e) { showToast("区域识别失败: " + e.message, "err"); });
};

// ---- 全文高精度识别（粗识别后升级）----
$("btnReprocess").onclick = function () {
  if (!current) { showToast("请先导入文件", "err"); return; }
  showToast("开始全文高精度识别（含表格/公式）…");
  fetch("/api/reprocess", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: current.id }),
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) throw new Error(d.error);
    $("jobStatus").classList.remove("hidden");
    $("progressBar").classList.remove("hidden");
    pollJob(d.job_id);
  }).catch(function (e) { showToast("全文识别失败: " + e.message, "err"); });
};
