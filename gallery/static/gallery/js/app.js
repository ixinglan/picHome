/* ==========================================================================
   picHome · 前端交互
   · 上传：顶栏按钮 / 整页拖拽 / 剪贴板粘贴 → 底部浮动队列（不占主区）
   · 卡片：复制名称 / 复制 CDN / Markdown / HTML
   · 云端删除：独立入口，直接删图床对象，不校验本地
   · 弹窗 / Toast / 批量 / 标签
   ========================================================================== */
(function () {
  "use strict";

  const meta = document.querySelector('meta[name="csrf-token"]');
  if (!meta) return;                       // 登录页没有 csrf meta，直接跳过
  const csrftoken = meta.content;
  const isIndex = document.body.dataset.page === "index";

  /* ---------- 图标 ---------- */
  const svg = (paths, extra) =>
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
    'stroke-linecap="round" stroke-linejoin="round"' + (extra || "") + ">" + paths + "</svg>";

  const ICON_EYE = svg('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>');
  const ICON_TAG = svg('<path d="M3 11V5a2 2 0 0 1 2-2h6l9 9-8 8-9-9Z"/><circle cx="7.5" cy="7.5" r="1.3"/>');
  const ICON_TRASH = svg('<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/>');
  const ICON_COPY = svg('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>');

  /* ---------- 工具 ---------- */
  let toastTimer;
  function toast(msg, type) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.className = "toast show" + (type ? " " + type : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.className = "toast"), 2800);
  }

  function formatBytes(b) {
    if (!b) return "0 B";
    const u = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(b) / Math.log(1024));
    return (b / Math.pow(1024, i)).toFixed(i ? 1 : 0) + " " + u[i];
  }

  function formatWhen(s) {
    const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})/);
    if (!m) return s || "";
    return `${+m[2]}月${+m[3]}日 ${m[4]}:${m[5]}`;
  }

  function post(url, data) {
    return fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrftoken },
      body: data,
    })
      .then((r) => {
        const ct = r.headers.get("content-type") || "";
        if (!ct.includes("application/json")) {
          return { ok: false, error: "登录状态已失效，请刷新页面重新登录" };
        }
        return r.json();
      })
      .catch(() => ({ ok: false, error: "网络错误，请重试" }));
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function adjustBadge(delta) {
    const nav = document.querySelector('.nav a[href="/recycle/"]');
    if (!nav) return;
    let b = nav.querySelector(".badge");
    if (!b) {
      b = document.createElement("span");
      b.className = "badge";
      b.textContent = "0";
      nav.appendChild(b);
    }
    const n = parseInt(b.textContent, 10) + delta;
    if (n <= 0) b.remove();
    else b.textContent = n;
  }

  /* ---------- 通用弹窗：确认 / 输入 ---------- */
  const modal = document.getElementById("modal");
  const modalTitle = document.getElementById("modalTitle");
  const modalBody = document.getElementById("modalBody");
  const modalInputWrap = document.getElementById("modalInputWrap");
  const modalInput = document.getElementById("modalInput");
  const modalOk = document.getElementById("modalOk");
  let modalResolver = null;

  function closeModal(result) {
    modal.hidden = true;
    const r = modalResolver;
    modalResolver = null;
    if (r) r(result);
  }

  function confirmDialog(title, message, opts) {
    opts = opts || {};
    modalTitle.textContent = title || "确认操作";
    modalBody.textContent = message || "";
    modalInputWrap.hidden = true;
    modalOk.textContent = opts.confirmText || "确定";
    modalOk.className = "btn " + (opts.danger ? "btn-danger-solid" : "btn-primary");
    modal.hidden = false;
    return new Promise((res) => { modalResolver = res; });
  }

  function promptDialog(title, message, value) {
    modalTitle.textContent = title || "请输入";
    modalBody.textContent = message || "";
    modalInputWrap.hidden = false;
    modalInput.value = value || "";
    modalOk.textContent = "保存";
    modalOk.className = "btn btn-primary";
    modal.hidden = false;
    setTimeout(() => modalInput.focus(), 60);
    return new Promise((res) => { modalResolver = res; });
  }

  modalOk.addEventListener("click", () => closeModal(modalInputWrap.hidden ? true : modalInput.value));
  document.getElementById("modalCancel").addEventListener("click", () => closeModal(null));
  document.getElementById("modalMask").addEventListener("click", () => closeModal(null));
  modalInput.addEventListener("keydown", (e) => { if (e.key === "Enter") closeModal(modalInput.value); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!modal.hidden) closeModal(null);
      if (!cloudModal.hidden) closeCloudModal();
    }
  });

  /* ---------- 云端删除（独立入口） ---------- */
  const cloudBtn = document.getElementById("cloudDeleteBtn");
  const cloudModal = document.getElementById("cloudModal");
  const cloudKey = document.getElementById("cloudKey");
  const cloudSubmit = document.getElementById("cloudDeleteSubmit");

  function openCloudModal() {
    cloudKey.value = "";
    cloudModal.hidden = false;
    setTimeout(() => cloudKey.focus(), 60);
  }
  function closeCloudModal() { cloudModal.hidden = true; }

  if (cloudBtn) {
    cloudBtn.addEventListener("click", openCloudModal);
    cloudModal.querySelectorAll("[data-close-cloud]").forEach((el) => {
      el.addEventListener("click", closeCloudModal);
    });
    cloudKey.addEventListener("keydown", (e) => { if (e.key === "Enter") cloudSubmit.click(); });

    cloudSubmit.addEventListener("click", async () => {
      const key = cloudKey.value.trim();
      if (!key) { toast("请填写图床对象名", "error"); cloudKey.focus(); return; }

      const go = await confirmDialog(
        "删除图床文件",
        "即将从图床删除：\n" + key + "\n此操作不可撤销，云端文件将立即消失。",
        { confirmText: "删除", danger: true }
      );
      if (!go) return;

      cloudSubmit.disabled = true;
      cloudSubmit.textContent = "删除中…";
      const resp = await post("/delete_remote", new URLSearchParams({ key }));
      cloudSubmit.disabled = false;
      cloudSubmit.textContent = "删除";

      if (resp.ok) {
        toast("已从图床删除：" + key, "success");
        closeCloudModal();
        const card = document.querySelector('#gallery .card[data-key="' + CSS.escape(key) + '"]');
        if (card) { card.remove(); if (resp.synced) adjustBadge(1); refreshBulk(); maybeEmpty(); }
        else if (resp.synced) { adjustBadge(1); }
      } else {
        toast(resp.error || "删除失败", "error");
      }
    });
  }

  /* ---------- 批量选择 ---------- */
  const bulkBar = document.getElementById("bulkBar");
  const selectAll = document.getElementById("selectAll");
  const pickCount = document.getElementById("pickCount");

  function boxes() { return Array.from(document.querySelectorAll(".pick-box")); }
  function checkedBoxes() { return boxes().filter((b) => b.checked); }

  function _visible(boxesArr) {
    return boxesArr.filter((b) => {
      const card = b.closest(".card");
      return !card || card.style.display !== "none";
    });
  }
  function refreshBulk() {
    if (!bulkBar) return;
    const total = _visible(boxes()).length;
    const n = _visible(checkedBoxes()).length;
    if (pickCount) pickCount.textContent = "已选 " + n + " 张";
    bulkBar.hidden = n === 0;
    if (selectAll) {
      selectAll.checked = total > 0 && n === total;
      selectAll.indeterminate = n > 0 && n < total;
    }
  }

  document.addEventListener("change", (e) => {
    if (e.target.classList && e.target.classList.contains("pick-box")) {
      const card = e.target.closest(".card");
      if (card) card.classList.toggle("picked", e.target.checked);
      refreshBulk();
    }
    if (e.target.id === "selectAll") {
      const on = e.target.checked;
      boxes().forEach((b) => {
        const card = b.closest(".card");
        if (card && card.style.display === "none") return;
        b.checked = on;
        if (card) card.classList.toggle("picked", on);
      });
      refreshBulk();
    }
  });

  function maybeEmpty() {
    const g = document.getElementById("gallery");
    if (g && !g.querySelector(".card")) location.reload();
  }

  function renderChips(card, tagsStr) {
    const box = card.querySelector(".card-tags");
    if (!box) return;
    const names = String(tagsStr || "").split(/[,，、\s]+/).map((s) => s.trim()).filter(Boolean);
    box.innerHTML = names.length
      ? names.map((n) => '<span class="chip">' + escapeHtml(n) + "</span>").join("")
      : '<span class="chip chip-empty">未分类</span>';
  }

  function currentTagsOf(card) {
    return Array.from(card.querySelectorAll(".card-tags .chip"))
      .filter((c) => !c.classList.contains("chip-empty"))
      .map((c) => c.textContent.trim())
      .join(", ");
  }

  /* ---------- 上传：整页拖拽 + 剪贴板粘贴 + 底部队列 ---------- */
  const dock = document.getElementById("uploadDock");
  const dockList = document.getElementById("dockList");
  const dockCount = document.getElementById("dockCount");
  const uploadBtn = document.getElementById("uploadBtn");
  const clearBtn = document.getElementById("clearBtn");
  const uploadStatus = document.getElementById("uploadStatus");
  const tagInput = document.getElementById("tagInput");
  const dropOverlay = document.getElementById("dropOverlay");
  const uploadTrigger = document.getElementById("uploadTrigger");
  const pasteBtn = document.getElementById("pasteBtn");

  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "image/*";
  fileInput.multiple = true;
  fileInput.hidden = true;
  document.body.appendChild(fileInput);

  let queue = [];

  function addToQueue(file) {
    if (!file.type.startsWith("image/")) return;
    const url = URL.createObjectURL(file);
    const item = document.createElement("div");
    item.className = "dock-item";
    item.innerHTML =
      '<div class="dock-thumb"><img src="' + url + '" alt=""></div>' +
      '<button class="dock-rm" type="button" title="移除" aria-label="移除">×</button>' +
      '<div class="dock-status" hidden></div>' +
      '<div class="dock-name" title="' + escapeHtml(file.name) + '">' + escapeHtml(file.name) + "</div>";
    dockList.appendChild(item);

    const entry = { file, url, el: item, name: file.name };
    queue.push(entry);
    item.querySelector(".dock-rm").addEventListener("click", () => removeFromQueue(entry));
    refreshDock();
  }

  function removeFromQueue(entry) {
    URL.revokeObjectURL(entry.url);
    entry.el.remove();
    queue = queue.filter((e) => e !== entry);
    refreshDock();
  }

  function refreshDock() {
    if (!dock) return;
    const n = queue.length;
    dockCount.textContent = n;
    dock.hidden = n === 0;
    if (uploadBtn) uploadBtn.disabled = n === 0;
  }

  if (uploadTrigger) uploadTrigger.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    Array.from(fileInput.files).forEach(addToQueue);
    fileInput.value = "";
  });

  document.getElementById("dockClose")?.addEventListener("click", () => {
    queue.slice().forEach(removeFromQueue);
  });

  // 整页拖拽（仅在拖入文件时出现遮罩）
  let dragDepth = 0;
  function hasFiles(e) {
    return e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  }
  window.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth++;
    dropOverlay.hidden = false;
  });
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("dragleave", (e) => {
    if (!hasFiles(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dropOverlay.hidden = true;
  });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    dropOverlay.hidden = true;
    Array.from(e.dataTransfer.files).forEach(addToQueue);
  });

  // 2.8 剪贴板粘贴上传：监听 paste 事件 + 顶栏「粘贴」按钮
  async function readClipboardImages() {
    if (!navigator.clipboard || !navigator.clipboard.read) {
      toast("当前浏览器不支持剪贴板读取，请用拖拽或点击上传", "error");
      return;
    }
    try {
      const items = await navigator.clipboard.read();
      let added = 0;
      for (const item of items) {
        const type = item.types.find((t) => t.startsWith("image/"));
        if (!type) continue;
        const blob = await item.getType(type);
        const name = "clipboard-" + Date.now() + "." + (type.split("/")[1] || "png");
        addToQueue(new File([blob], name, { type }));
        added++;
      }
      if (added === 0) toast("剪贴板里没有图片", "error");
    } catch (err) {
      toast("无法读取剪贴板（需授权）：" + (err && err.message ? err.message : err), "error");
    }
  }
  if (pasteBtn) pasteBtn.addEventListener("click", readClipboardImages);
  document.addEventListener("paste", (e) => {
    if (!e.clipboardData) return;
    const files = Array.from(e.clipboardData.items || [])
      .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
      .map((it) => it.getAsFile())
      .filter(Boolean);
    if (files.length) {
      e.preventDefault();
      files.forEach(addToQueue);
    }
  });

  if (uploadBtn) {
    uploadBtn.addEventListener("click", async () => {
      if (!queue.length) return;
      uploadBtn.disabled = true;
      const tags = tagInput ? tagInput.value : "";
      let ok = 0, fail = 0;

      for (const entry of queue.slice()) {
        const fd = new FormData();
        fd.append("file", entry.file);
        if (tags) fd.append("tags", tags);
        const status = entry.el.querySelector(".dock-status");
        status.hidden = false;
        status.textContent = "上传中…";
        try {
          const resp = await post("/upload", fd);
          if (resp.ok) {
            ok++;
            URL.revokeObjectURL(entry.url);
            entry.el.remove();
            queue = queue.filter((e) => e !== entry);
            if (isIndex) prependCard(resp);
          } else {
            fail++;
            entry.el.classList.add("failed");
            status.textContent = "✕ " + (resp.error || "失败");
          }
        } catch (err) {
          fail++;
          entry.el.classList.add("failed");
          status.textContent = "✕ 网络错误";
        }
        uploadStatus.textContent = `已处理 ${ok + fail} / ${ok + fail + queue.length}`;
      }

      if (ok) toast("成功上传 " + ok + " 张", "success");
      if (fail) toast(fail + " 张上传失败，请查看队列中的提示", "error");
      uploadStatus.textContent = "";
      refreshDock();
      if (ok && tags) setTimeout(() => location.reload(), 1200);
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", () => queue.slice().forEach(removeFromQueue));
  }

  /* 新上传的卡片插到列表最前，结构与模板保持一致 */
  function prependCard(d) {
    const gallery = document.getElementById("gallery");
    if (!gallery) return;
    const empty = gallery.querySelector(".empty");
    if (empty) empty.remove();

    const tags = (d.tags && d.tags.length)
      ? d.tags.map((n) => '<span class="chip">' + escapeHtml(n) + "</span>").join("")
      : '<span class="chip chip-empty">未分类</span>';

    const prov = d.provider_display || d.provider || "";
    const card = document.createElement("article");
    card.className = "card";
    card.dataset.id = d.id;
    card.dataset.key = d.object_key;
    card.style.setProperty("--i", "0");
    card.innerHTML =
      '<div class="card-media">' +
        '<img src="' + escapeHtml(d.thumb_url || d.cdn_url) + '" alt="' + escapeHtml(d.original_name) + '" loading="lazy">' +
        '<label class="card-pick" title="选择这张"><input type="checkbox" class="pick-box" value="' + d.id + '"></label>' +
        (prov ? '<span class="provider-badge" title="图床：' + escapeHtml(prov) + '">' + escapeHtml(prov) + '</span>' : '') +
        '<div class="card-hover">' +
          '<a class="btn btn-sm" href="' + escapeHtml(d.cdn_url) + '" target="_blank" rel="noopener" title="查看原图" aria-label="查看原图">' + ICON_EYE + '</a>' +
          '<button class="btn btn-sm tag-btn" type="button" title="改标签" aria-label="改标签">' + ICON_TAG + '</button>' +
          '<button class="btn btn-sm btn-danger delete-btn" type="button" title="删除" aria-label="删除">' + ICON_TRASH + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="card-info">' +
        '<div class="card-name-row">' +
          '<div class="card-name" title="' + escapeHtml(d.original_name) + '" data-full="' + escapeHtml(d.original_name) + '">' + escapeHtml(d.original_name) + '</div>' +
          '<button class="icon-btn copy-name-btn" type="button" title="复制图片名" aria-label="复制图片名">' + ICON_COPY + '</button>' +
        '</div>' +
        '<div class="card-key" title="' + escapeHtml(d.object_key) + '">' + escapeHtml(d.object_key) + '</div>' +
        '<div class="card-links">' +
          cardUrlRow("CDN", d.cdn_url) +
          cardUrlRow("MD", d.markdown) +
          cardUrlRow("HTML", d.html) +
        '</div>' +
        '<div class="card-meta"><span>' + formatBytes(d.size) + '</span><span class="sep">·</span><span>' + formatWhen(d.uploaded_at) + '</span></div>' +
        '<div class="card-tags">' + tags + '</div>' +
      '</div>';

    gallery.prepend(card);
    refreshBulk();
  }

  function cardUrlRow(label, value) {
    const v = (value || "").replace(/"/g, "&quot;");
    return '<div class="card-url">' +
      '<span class="url-label">' + label + '</span>' +
      '<input readonly value="' + v + '" title="' + v + '">' +
      '<button class="btn btn-sm copy-btn" type="button" title="复制" aria-label="复制">' + ICON_COPY + '</button>' +
    '</div>';
  }

  /* ---------- 卡片操作（事件委托） ---------- */
  const gallery = document.getElementById("gallery");

  if (gallery) {
    gallery.addEventListener("click", async (e) => {
      const copyBtn = e.target.closest(".copy-btn");
      const copyNameBtn = e.target.closest(".copy-name-btn");
      const delBtn = e.target.closest(".delete-btn");
      const tagBtn = e.target.closest(".tag-btn");
      const restoreBtn = e.target.closest(".restore-btn");
      const purgeBtn = e.target.closest(".purge-btn");

      if (copyNameBtn) {
        const name = copyNameBtn.closest(".card-name-row").querySelector(".card-name").textContent;
        try { await navigator.clipboard.writeText(name); toast("已复制图片名", "success"); }
        catch (_) { toast("复制失败", "error"); }
        return;
      }

      if (copyBtn) {
        const input = copyBtn.closest(".card-url").querySelector("input");
        try {
          await navigator.clipboard.writeText(input.value);
          toast("已复制链接", "success");
        } catch (_) {
          input.select();
          document.execCommand("copy");
          toast("已复制链接", "success");
        }
        return;
      }

      if (delBtn) {
        const card = delBtn.closest(".card");
        const name = card.querySelector(".card-name").textContent;
        const go = await confirmDialog(
          "删除图片",
          "确定删除「" + name + "」？\n将从图床移除对象，本地文件转入回收站（可在回收站恢复）。",
          { confirmText: "删除", danger: true }
        );
        if (!go) return;
        const resp = await post("/delete", new URLSearchParams({ key: card.dataset.key }));
        if (resp.ok) {
          card.remove();
          adjustBadge(1);
          toast("已删除并移入回收站", "success");
          refreshBulk();
          maybeEmpty();
        } else {
          toast(resp.error || "删除失败", "error");
        }
        return;
      }

      if (tagBtn) {
        const card = tagBtn.closest(".card");
        const name = card.querySelector(".card-name").textContent;
        const val = await promptDialog("设置标签", "为「" + name + "」设置标签：", currentTagsOf(card));
        if (val === null) return;
        const params = new URLSearchParams();
        params.append("id", card.dataset.id);
        params.append("tags", val);
        const resp = await post("/set_tags", params);
        if (resp.ok) { renderChips(card, val); toast("标签已更新", "success"); }
        else toast(resp.error || "更新失败", "error");
        return;
      }

      if (restoreBtn) {
        const card = restoreBtn.closest(".card");
        const name = card.querySelector(".card-name").textContent;
        const go = await confirmDialog(
          "恢复图片",
          "恢复「" + name + "」？\n会把本地文件重新上传到图床，并生成新的访问链接。",
          { confirmText: "恢复" }
        );
        if (!go) return;
        const resp = await post("/recycle/restore", new URLSearchParams({ key: card.dataset.key }));
        if (resp.ok) {
          card.remove();
          toast("已恢复并重新上传到图床", "success");
          refreshBulk();
          maybeEmpty();
        } else {
          toast(resp.error || "恢复失败", "error");
        }
        return;
      }

      if (purgeBtn) {
        const card = purgeBtn.closest(".card");
        const name = card.querySelector(".card-name").textContent;
        const go = await confirmDialog(
          "彻底删除",
          "彻底删除「" + name + "」？\n本地文件与数据库记录将永久移除，无法恢复。",
          { confirmText: "彻底删除", danger: true }
        );
        if (!go) return;
        const resp = await post("/recycle/purge", new URLSearchParams({ key: card.dataset.key }));
        if (resp.ok) {
          card.remove();
          toast("已彻底删除", "success");
          refreshBulk();
          maybeEmpty();
        } else {
          toast(resp.error || "删除失败", "error");
        }
        return;
      }
    });
  }

  /* ---------- 图库：批量改标签 / 批量删除 ---------- */
  const bulkTagBtn = document.getElementById("bulkTagBtn");
  const bulkDeleteBtn = document.getElementById("bulkDeleteBtn");

  if (bulkTagBtn) {
    bulkTagBtn.addEventListener("click", async () => {
      const picked = checkedBoxes();
      if (!picked.length) return;
      const val = await promptDialog(
        "批量设置标签",
        "为选中的 " + picked.length + " 张图片设置标签（会覆盖原有标签）：",
        ""
      );
      if (val === null) return;
      const params = new URLSearchParams();
      picked.forEach((b) => params.append("id", b.value));
      params.append("tags", val);
      const resp = await post("/set_tags", params);
      if (resp.ok) {
        picked.forEach((b) => { const c = b.closest(".card"); if (c) renderChips(c, val); });
        toast("已更新 " + resp.updated + " 张图片的标签", "success");
      } else {
        toast(resp.error || "更新失败", "error");
      }
    });
  }

  if (bulkDeleteBtn) {
    bulkDeleteBtn.addEventListener("click", async () => {
      const picked = checkedBoxes();
      if (!picked.length) return;
      const go = await confirmDialog(
        "批量删除",
        "确定删除选中的 " + picked.length + " 张图片？\n会从图床移除对象，本地文件转入回收站（可在回收站恢复）。",
        { confirmText: "删除", danger: true }
      );
      if (!go) return;
      const params = new URLSearchParams();
      picked.forEach((b) => params.append("id", b.value));
      const resp = await post("/delete_batch", params);
      if (resp.ok) {
        picked.map((b) => b.closest(".card")).filter(Boolean).forEach((c) => c.remove());
        adjustBadge(resp.deleted);
        let msg = "已删除 " + resp.deleted + " 张并移入回收站";
        if (resp.failed && resp.failed.length) {
          msg += "；" + resp.failed.length + " 张失败：" + resp.failed[0].error;
        }
        toast(msg, "success");
        refreshBulk();
        maybeEmpty();
      } else {
        toast(resp.error || "批量删除失败", "error");
      }
    });
  }

  /* ---------- 回收站：批量恢复 / 批量彻底删除 ---------- */
  const bulkRestoreBtn = document.getElementById("bulkRestoreBtn");
  const bulkPurgeBtn = document.getElementById("bulkPurgeBtn");

  if (bulkRestoreBtn) {
    bulkRestoreBtn.addEventListener("click", async () => {
      const picked = checkedBoxes();
      if (!picked.length) return;
      const go = await confirmDialog(
        "批量恢复",
        "恢复选中的 " + picked.length + " 张图片？\n会把本地文件重新上传到图床。",
        { confirmText: "恢复" }
      );
      if (!go) return;
      const params = new URLSearchParams();
      picked.forEach((b) => params.append("id", b.value));
      const resp = await post("/recycle/restore_batch", params);
      if (resp.ok) {
        picked.map((b) => b.closest(".card")).filter(Boolean).forEach((c) => c.remove());
        let msg = "已恢复 " + resp.restored + " 张";
        if (resp.failed && resp.failed.length) {
          msg += "；" + resp.failed.length + " 张失败：" + resp.failed[0].error;
        }
        toast(msg, "success");
        refreshBulk();
        maybeEmpty();
      } else {
        toast(resp.error || "恢复失败", "error");
      }
    });
  }

  if (bulkPurgeBtn) {
    bulkPurgeBtn.addEventListener("click", async () => {
      const picked = checkedBoxes();
      if (!picked.length) return;
      const go = await confirmDialog(
        "批量彻底删除",
        "彻底删除选中的 " + picked.length + " 张？\n本地文件与数据库记录将永久移除，无法恢复。",
        { confirmText: "彻底删除", danger: true }
      );
      if (!go) return;
      const params = new URLSearchParams();
      picked.forEach((b) => params.append("id", b.value));
      const resp = await post("/recycle/purge_batch", params);
      if (resp.ok) {
        picked.map((b) => b.closest(".card")).filter(Boolean).forEach((c) => c.remove());
        toast("已彻底删除 " + resp.purged + " 张", "success");
        refreshBulk();
        maybeEmpty();
      } else {
        toast(resp.error || "彻底删除失败", "error");
      }
    });
  }

  refreshBulk();

  /* ---------- 实时搜索过滤（前端即时筛选已渲染卡片） ---------- */
  const searchInput = document.querySelector(".search input");
  const noMatch = document.getElementById("noMatch");
  function applyFilter() {
    if (!gallery) return;
    const q = (searchInput ? searchInput.value : "").trim().toLowerCase();
    let visible = 0;
    gallery.querySelectorAll(".card").forEach((card) => {
      const name = (card.querySelector(".card-name")?.textContent || "").toLowerCase();
      const key = (card.querySelector(".card-key")?.textContent || "").toLowerCase();
      const hit = !q || name.includes(q) || key.includes(q);
      card.style.display = hit ? "" : "none";
      if (hit) visible++;
    });
    if (noMatch) noMatch.hidden = !(q && visible === 0);
    refreshBulk();
  }
  if (searchInput) {
    searchInput.addEventListener("input", applyFilter);
    if (searchInput.value) applyFilter();
  }
})();
