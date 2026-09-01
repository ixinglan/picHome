/* ===== 七牛云图库 · 前端交互（Django 模板 + 原生 JS，不分前后端） ===== */
(function () {
  "use strict";

  const csrftoken = document.querySelector('meta[name="csrf-token"]').content;

  /* ---------- 工具函数 ---------- */
  let toastTimer;
  function toast(msg, type) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.className = "toast show" + (type ? " " + type : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.className = "toast"), 2600);
  }

  function formatBytes(b) {
    if (!b) return "0 B";
    const u = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(b) / Math.log(1024));
    return (b / Math.pow(1024, i)).toFixed(i ? 1 : 0) + " " + u[i];
  }

  function post(url, data) {
    return fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrftoken },
      body: data,
    })
      .then((r) => {
        const ct = r.headers.get("content-type") || "";
        // 未登录时 Django 会重定向到登录页（HTML），这里给出人话提示
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

  /* 回收站角标增减 */
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

  /* ---------- 通用弹窗：确认 / 输入（替代 confirm / prompt） ---------- */
  const modal = document.getElementById("modal");
  const modalTitle = document.getElementById("modalTitle");
  const modalBody = document.getElementById("modalBody");
  const modalInputWrap = document.getElementById("modalInputWrap");
  const modalInput = document.getElementById("modalInput");
  const modalOk = document.getElementById("modalOk");
  const modalCancel = document.getElementById("modalCancel");
  const modalMask = document.getElementById("modalMask");
  let modalResolver = null;

  function closeModal(result) {
    modal.hidden = true;
    const r = modalResolver;
    modalResolver = null;
    if (r) r(result);
  }

  // 返回：确认 = true，取消 = null
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

  // 返回：输入的字符串（可能为空串），取消 = null
  function promptDialog(title, message, value) {
    modalTitle.textContent = title || "请输入";
    modalBody.textContent = message || "";
    modalInputWrap.hidden = false;
    modalInput.value = value || "";
    modalOk.textContent = "保存";
    modalOk.className = "btn btn-primary";
    modal.hidden = false;
    setTimeout(() => modalInput.focus(), 40);
    return new Promise((res) => { modalResolver = res; });
  }

  if (modal) {
    modalOk.addEventListener("click", () => {
      closeModal(modalInputWrap.hidden ? true : modalInput.value);
    });
    modalCancel.addEventListener("click", () => closeModal(null));
    modalMask.addEventListener("click", () => closeModal(null));
    modalInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") closeModal(modalInput.value);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.hidden) closeModal(null);
    });
  }

  /* ---------- 批量选择 ---------- */
  const bulkBar = document.getElementById("bulkBar");
  const selectAll = document.getElementById("selectAll");
  const pickCount = document.getElementById("pickCount");

  function boxes() {
    return Array.from(document.querySelectorAll(".pick-box"));
  }
  function checkedBoxes() {
    return boxes().filter((b) => b.checked);
  }
  function refreshBulk() {
    if (!bulkBar) return;
    const total = boxes().length;
    const n = checkedBoxes().length;
    if (pickCount) pickCount.textContent = "已选 " + n + " 张";
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
        b.checked = on;
        const card = b.closest(".card");
        if (card) card.classList.toggle("picked", on);
      });
      refreshBulk();
    }
  });

  /* 列表里一张卡片都不剩时，刷新以显示空状态 */
  function maybeEmpty() {
    const g = document.getElementById("gallery");
    if (g && !g.querySelector(".card")) location.reload();
  }

  function removeCards(nodes) {
    nodes.forEach((c) => c.remove());
  }

  /* 重新渲染某张卡片的标签 chips */
  function renderChips(card, tagsStr) {
    const box = card.querySelector(".card-tags");
    if (!box) return;
    const names = String(tagsStr || "")
      .split(/[,，、\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
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

  /* ---------- 上传：预览 + 提交 ---------- */
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const preview = document.getElementById("preview");
  const uploadBtn = document.getElementById("uploadBtn");
  const clearBtn = document.getElementById("clearBtn");
  const uploadStatus = document.getElementById("uploadStatus");
  const tagInput = document.getElementById("tagInput");

  let selected = []; // { file, url, el, name }

  function addPreview(file) {
    const url = URL.createObjectURL(file);
    const item = document.createElement("div");
    item.className = "preview-item";
    item.innerHTML =
      '<img src="' + url + '" alt="">' +
      '<button class="rm" type="button" title="移除">×</button>' +
      '<div class="pv-name">' + escapeHtml(file.name) + "</div>" +
      '<div class="pv-status" hidden></div>';
    preview.appendChild(item);
    const entry = { file, url, el: item, name: file.name };
    selected.push(entry);

    item.querySelector(".rm").addEventListener("click", () => removePreview(entry));
    refreshUploadBtn();
  }

  function removePreview(entry) {
    URL.revokeObjectURL(entry.url);
    entry.el.remove();
    selected = selected.filter((e) => e !== entry);
    refreshUploadBtn();
  }

  function refreshUploadBtn() {
    if (!uploadBtn) return;
    const n = selected.length;
    uploadBtn.disabled = n === 0;
    uploadBtn.textContent = n ? "上传到七牛云（" + n + "）" : "上传到七牛云";
    if (clearBtn) clearBtn.hidden = n === 0;
  }

  if (dropzone) {
    dropzone.addEventListener("click", () => fileInput.click());
    dropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      Array.from(e.dataTransfer.files).forEach(addPreview);
    });
    fileInput.addEventListener("change", () => {
      Array.from(fileInput.files).forEach(addPreview);
      fileInput.value = "";
    });
  }

  if (uploadBtn) {
    uploadBtn.addEventListener("click", async () => {
      if (!selected.length) return;
      uploadBtn.disabled = true;
      const tags = tagInput ? tagInput.value : "";
      let done = 0, ok = 0, fail = 0;
      for (const entry of selected.slice()) {
        const fd = new FormData();
        fd.append("file", entry.file);
        if (tags) fd.append("tags", tags);
        const status = entry.el.querySelector(".pv-status");
        status.hidden = false;
        status.textContent = "上传中…";
        try {
          const resp = await post("/upload", fd);
          if (resp.ok) {
            ok++;
            entry.el.remove();
            URL.revokeObjectURL(entry.url);
            selected = selected.filter((e) => e !== entry);
            prependCard(resp);
          } else {
            fail++;
            entry.el.classList.add("failed");
            status.textContent = "✕ " + (resp.error || "失败");
          }
        } catch (e) {
          fail++;
          entry.el.classList.add("failed");
          status.textContent = "✕ 网络错误";
        }
        done++;
        uploadStatus.textContent = "进度 " + done + "/" + (ok + fail + selected.length);
      }
      if (ok) toast("成功上传 " + ok + " 张", "success");
      if (fail) toast(fail + " 张上传失败，请查看预览区提示", "error");
      uploadStatus.textContent = "";
      refreshUploadBtn();
      if (ok && tags) {
        // 有新标签时刷新一次，让上方的标签筛选栏同步
        setTimeout(() => location.reload(), 1200);
      }
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", () => selected.slice().forEach(removePreview));
  }

  /* 根据上传返回数据，拼一张与模板一致的卡片并插到列表最前 */
  function prependCard(d) {
    const gallery = document.getElementById("gallery");
    if (!gallery) return;
    const empty = gallery.querySelector(".empty");
    if (empty) empty.remove();
    const tags = (d.tags || []).length
      ? (d.tags || []).map((n) => '<span class="chip">' + escapeHtml(n) + "</span>").join("")
      : '<span class="chip chip-empty">未分类</span>';
    const card = document.createElement("article");
    card.className = "card";
    card.dataset.id = d.id;
    card.dataset.key = d.qiniu_key;
    card.innerHTML =
      '<label class="pick" title="选择这张"><input type="checkbox" class="pick-box" value="' + d.id + '"></label>' +
      '<div class="thumb"><img src="' + escapeHtml(d.thumb_url || d.cdn_url) + '" alt="' + escapeHtml(d.original_name) + '" loading="lazy"></div>' +
      '<div class="card-body">' +
      '<div class="card-name" title="' + escapeHtml(d.original_name) + '">' + escapeHtml(d.original_name) + "</div>" +
      '<div class="card-key" title="' + escapeHtml(d.qiniu_key) + '">' + escapeHtml(d.qiniu_key) + "</div>" +
      '<div class="card-tags">' + tags + "</div>" +
      '<div class="card-meta"><span>' + formatBytes(d.size) + "</span><span>" + escapeHtml(d.uploaded_at) + "</span></div>" +
      '<div class="card-url"><input class="url-input" readonly value="' + escapeHtml(d.cdn_url) + '">' +
      '<button class="btn btn-sm copy-btn" type="button">复制</button></div>' +
      '<div class="card-actions">' +
      '<button class="btn btn-sm tag-btn" type="button">标签</button>' +
      '<a class="btn btn-sm" href="' + escapeHtml(d.cdn_url) + '" target="_blank" rel="noopener">查看</a>' +
      '<button class="btn btn-sm btn-danger delete-btn" type="button">删除</button></div>' +
      "</div>";
    gallery.prepend(card);
    refreshBulk();
  }

  /* ---------- 图库 / 回收站：卡片操作（事件委托） ---------- */
  const gallery = document.getElementById("gallery");

  if (gallery) {
    gallery.addEventListener("click", async (e) => {
      const copyBtn = e.target.closest(".copy-btn");
      const delBtn = e.target.closest(".delete-btn");
      const tagBtn = e.target.closest(".tag-btn");
      const restoreBtn = e.target.closest(".restore-btn");
      const purgeBtn = e.target.closest(".purge-btn");

      if (copyBtn) {
        const input = copyBtn.parentElement.querySelector(".url-input");
        try {
          await navigator.clipboard.writeText(input.value);
          toast("已复制 CDN 链接", "success");
        } catch (_) {
          input.select();
          document.execCommand("copy");
          toast("已复制 CDN 链接", "success");
        }
        return;
      }

      if (delBtn) {
        const card = delBtn.closest(".card");
        const name = card.querySelector(".card-name").textContent;
        const go = await confirmDialog(
          "删除图片",
          "确定删除「" + name + "」？\n将从七牛云移除对象，本地文件转入回收站（可在回收站恢复）。",
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
        if (resp.ok) {
          renderChips(card, val);
          toast("标签已更新", "success");
        } else {
          toast(resp.error || "更新失败", "error");
        }
        return;
      }

      if (restoreBtn) {
        const card = restoreBtn.closest(".card");
        const name = card.querySelector(".card-name").textContent;
        const go = await confirmDialog(
          "恢复图片",
          "恢复「" + name + "」？\n会把本地文件重新上传到七牛云，并生成新的访问链接。",
          { confirmText: "恢复" }
        );
        if (!go) return;
        const resp = await post("/recycle/restore", new URLSearchParams({ key: card.dataset.key }));
        if (resp.ok) {
          card.remove();
          toast("已恢复并重新上传到七牛云", "success");
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
        picked.forEach((b) => {
          const card = b.closest(".card");
          if (card) renderChips(card, val);
        });
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
        "确定删除选中的 " + picked.length + " 张图片？\n会从七牛云移除对象，本地文件转入回收站（可在回收站恢复）。",
        { confirmText: "删除", danger: true }
      );
      if (!go) return;
      const params = new URLSearchParams();
      picked.forEach((b) => params.append("id", b.value));
      const resp = await post("/delete_batch", params);
      if (resp.ok) {
        const cards = picked.map((b) => b.closest(".card")).filter(Boolean);
        removeCards(cards);
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
        "恢复选中的 " + picked.length + " 张图片？\n会把本地文件重新上传到七牛云。",
        { confirmText: "恢复" }
      );
      if (!go) return;
      const params = new URLSearchParams();
      picked.forEach((b) => params.append("id", b.value));
      const resp = await post("/recycle/restore_batch", params);
      if (resp.ok) {
        removeCards(picked.map((b) => b.closest(".card")).filter(Boolean));
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
        removeCards(picked.map((b) => b.closest(".card")).filter(Boolean));
        toast("已彻底删除 " + resp.purged + " 张", "success");
        refreshBulk();
        maybeEmpty();
      } else {
        toast(resp.error || "彻底删除失败", "error");
      }
    });
  }

  /* ---------- 按对象名直接删除 ---------- */
  const deleteByName = document.getElementById("deleteByName");
  if (deleteByName) {
    deleteByName.addEventListener("submit", async (e) => {
      e.preventDefault();
      const key = deleteByName.key.value.trim();
      if (!key) return;
      const go = await confirmDialog(
        "按对象名删除",
        "即将删除七牛云对象：\n" + key + "\n会从七牛云移除，本地文件转入回收站。",
        { confirmText: "删除", danger: true }
      );
      if (!go) return;
      const resp = await post("/delete", new URLSearchParams({ key }));
      if (resp.ok) {
        toast("已删除并移入回收站", "success");
        deleteByName.reset();
        const card = gallery && gallery.querySelector('.card[data-key="' + CSS.escape(key) + '"]');
        if (card) {
          card.remove();
          adjustBadge(1);
          refreshBulk();
        }
      } else {
        toast(resp.error || "删除失败", "error");
      }
    });
  }

  refreshBulk();
})();
