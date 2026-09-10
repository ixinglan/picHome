/* ==========================================================================
   picHome · 图床设置页 / 历史页 交互
   - 图床配置表单：按所选图床的 specs 自动渲染字段 + 必填校验 + 启用
   - 历史页：复制 CDN / Markdown / HTML
   ========================================================================== */
(function () {
  "use strict";

  const meta = document.querySelector('meta[name="csrf-token"]');
  const csrftoken = meta ? meta.content : "";
  const isStorage = document.body.dataset.page === "storage";
  const isHistory = document.body.dataset.page === "history";

  /* ---------- 通用：复制文本 ---------- */
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
      try {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
        resolve();
      } catch (e) {
        reject(e);
      }
    });
  }

  function toast(msg, type) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.className = "toast show" + (type ? " " + type : "");
    setTimeout(() => (el.className = "toast"), 2600);
  }

  /* ====================== 历史页：复制 ====================== */
  if (isHistory) {
    document.getElementById("histList")?.addEventListener("click", async (e) => {
      const btn = e.target.closest(".copy-btn");
      if (!btn || btn.disabled) return;
      const text = btn.getAttribute("data-copy");
      if (!text) return;
      try {
        await copyText(text);
        toast("已复制", "success");
      } catch (_) {
        toast("复制失败", "error");
      }
    });
  }

  /* ====================== 图床设置页 ====================== */
  if (!isStorage) return;

  const SPECS = JSON.parse(document.getElementById("specsData").textContent);
  let EDIT = null;
  const editEl = document.getElementById("editData");
  if (editEl) {
    try { EDIT = JSON.parse(editEl.textContent); } catch (_) { EDIT = null; }
  }

  const form = document.getElementById("storageForm");
  const providerSelect = document.getElementById("providerSelect");
  const fieldsBox = document.getElementById("fieldsBox");
  const displayName = document.getElementById("displayName");
  const isActive = document.getElementById("isActive");
  const cfgId = document.getElementById("cfgId");
  const saveBtn = document.getElementById("saveBtn");
  const formError = document.getElementById("formError");
  const formTitle = document.getElementById("formTitle");

  function specOf(name) {
    return SPECS.find((s) => s.name === name) || null;
  }

  function renderFields() {
    const spec = specOf(providerSelect.value);
    fieldsBox.innerHTML = "";
    if (!spec) return;
    // 配置名称占位提示随所选图床变化（如：我的阿里云 OSS / 我的腾讯云 COS）
    displayName.placeholder = "例如：我的" + spec.display_name;
    const prefill = (EDIT && EDIT.provider === spec.name && EDIT.config) || {};
    spec.fields.forEach((f) => {
      const wrap = document.createElement("label");
      wrap.className = "field";
      const lab = document.createElement("span");
      lab.className = "field-label";
      lab.textContent = f.label + (f.required ? "" : "（可选）");
      const input = document.createElement("input");
      input.type = f.secret ? "password" : "text";
      input.name = f.name;
      input.placeholder = f.placeholder || "";
      input.autocomplete = "off";
      input.spellcheck = false;
      if (prefill[f.name]) input.value = prefill[f.name];
      wrap.appendChild(lab);
      wrap.appendChild(input);
      if (f.help_text) {
        const hint = document.createElement("p");
        hint.className = "modal-hint";
        hint.textContent = f.help_text;
        wrap.appendChild(hint);
      }
      fieldsBox.appendChild(wrap);
    });
  }

  function applyEdit() {
    if (!EDIT) return;
    formTitle.textContent = "编辑图床配置";
    cfgId.value = EDIT.id;
    providerSelect.value = EDIT.provider;
    displayName.value = EDIT.display_name || "";
    isActive.checked = !!EDIT.is_active;
    renderFields();
  }

  function resetForm() {
    EDIT = null;
    formTitle.textContent = "新建图床配置";
    cfgId.value = "";
    displayName.value = "";
    isActive.checked = false;
    formError.hidden = true;
    formError.textContent = "";
    renderFields();
  }

  providerSelect.addEventListener("change", () => {
    // 切换图床类型时清空编辑态（字段不同）
    EDIT = null;
    formTitle.textContent = "新建图床配置";
    cfgId.value = "";
    renderFields();
  });

  document.getElementById("resetBtn").addEventListener("click", resetForm);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    formError.hidden = true;
    formError.textContent = "";

    const fd = new FormData(form);
    // 清除上次的字段错误样式
    fieldsBox.querySelectorAll(".field.invalid").forEach((el) =>
      el.classList.remove("invalid")
    );

    const resp = await fetch("/settings/storage/", {
      method: "POST",
      headers: { "X-CSRFToken": csrftoken },
      body: fd,
    }).then((r) => r.json());

    if (resp.ok) {
      toast("已保存", "success");
      setTimeout(() => location.reload(), 600);
      return;
    }

    // 必填项缺失：标红对应字段 + 顶部提示
    if (resp.fields) {
      Object.keys(resp.fields).forEach((k) => {
        const input = fieldsBox.querySelector(`[name="${k}"]`);
        if (input) {
          const wrap = input.closest(".field");
          if (wrap) wrap.classList.add("invalid");
        }
      });
    }
    formError.textContent = resp.error || "保存失败";
    formError.hidden = false;
    toast(resp.error || "保存失败", "error");
  });

  /* ---------- 确认弹窗（复用 base.html 的通用 #modal） ----------
     不能用 window.confirm()：macOS 的 Tauri/WKWebView 里它静默返回 false 且不弹窗，
     会让「if (!confirm(...)) return」永远直接 return、删除请求发不出去（Web 浏览器
     confirm 正常，所以只有桌面 App 复现）。本页未加载 app.js（其 confirmDialog 在
     app.js 的 IIFE 内、不可跨文件访问），故在此自行驱动全局 #modal。 */
  function confirmDialog(title, message, confirmText, variant) {
    const modal = document.getElementById("modal");
    const modalTitle = document.getElementById("modalTitle");
    const modalBody = document.getElementById("modalBody");
    const modalInputWrap = document.getElementById("modalInputWrap");
    const modalOk = document.getElementById("modalOk");
    const modalCancel = document.getElementById("modalCancel");
    const modalMask = document.getElementById("modalMask");

    modalTitle.textContent = title || "确认操作";
    modalBody.textContent = message || "";
    if (modalInputWrap) modalInputWrap.hidden = true;
    modalOk.textContent = confirmText || "确定";
    // 默认危险色（删除类）；非破坏性操作传 "primary" 用主色，避免误导
    modalOk.className = variant === "primary" ? "btn btn-primary" : "btn btn-danger-solid";
    modal.hidden = false;

    return new Promise((resolve) => {
      const onOk = () => done(true);
      const onCancel = () => done(false);
      function done(v) {
        modal.hidden = true;
        modalOk.removeEventListener("click", onOk);
        modalCancel.removeEventListener("click", onCancel);
        modalMask.removeEventListener("click", onCancel);
        resolve(v);
      }
      modalOk.addEventListener("click", onOk);
      modalCancel.addEventListener("click", onCancel);
      modalMask.addEventListener("click", onCancel);
    });
  }

  /* 列表里的「启用 / 删除」 */
  document.querySelectorAll("[data-activate]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-activate");
      const resp = await fetch("/settings/storage/", {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken, "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ action: "activate", id }),
      }).then((r) => r.json());
      if (resp.ok) location.reload();
      else toast(resp.error || "启用失败", "error");
    });
  });

  document.querySelectorAll("[data-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-delete");
      const go = await confirmDialog("删除图床配置", "确定删除该图床配置？此操作不可撤销。", "删除");
      if (!go) return;
      const resp = await fetch("/settings/storage/", {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken, "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ action: "delete", id }),
      }).then((r) => r.json());
      if (resp.ok) location.reload();
      else toast(resp.error || "删除失败", "error");
    });
  });

  /* ====================== 数据迁移：导出 / 导入 ====================== */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  const exportMigrateBtn = document.getElementById("exportMigrateBtn");
  const importFile = document.getElementById("importFile");
  const importFileName = document.getElementById("importFileName");
  const importResult = document.getElementById("importResult");

  if (exportMigrateBtn) {
    exportMigrateBtn.addEventListener("click", () => {
      // embed=1：把本地未上云图片的数据一并内嵌进 JSON，保证迁移完整
      window.location.href = "/export/?all=1&fmt=json&embed=1";
    });
  }

  function renderImportResult(resp) {
    if (!importResult) return;
    let html =
      '<p class="migrate-line">导入完成：总计 ' + resp.total +
      " 条，成功 <b>" + resp.imported + "</b>、跳过 <b>" + resp.skipped +
      "</b>、失败 <b>" + resp.failed + "</b></p>";
    if (resp.errors && resp.errors.length) {
      html +=
        '<details class="migrate-errors"><summary>失败详情（' + resp.errors.length +
        "）</summary><ul>" +
        resp.errors.map((e) => "<li>" + esc(e) + "</li>").join("") +
        "</ul></details>";
    }
    importResult.innerHTML = html;
    importResult.hidden = false;
  }

  if (importFile) {
    importFile.addEventListener("change", async () => {
      const file = importFile.files && importFile.files[0];
      if (!file) return;
      if (importFileName) importFileName.textContent = file.name;
      const go = await confirmDialog(
        "导入图库数据",
        "将从「" + file.name + "」导入图库记录。\n已存在的条目会自动跳过，不会覆盖现有数据。",
        "开始导入",
        "primary"
      );
      if (!go) {
        importFile.value = "";
        if (importFileName) importFileName.textContent = "";
        return;
      }
      if (importResult) {
        importResult.hidden = true;
        importResult.innerHTML = "";
      }
      const fd = new FormData();
      fd.append("file", file);
      try {
        const resp = await fetch("/import/", {
          method: "POST",
          headers: { "X-CSRFToken": csrftoken },
          body: fd,
        }).then((r) => r.json());
        if (!resp.ok) {
          toast(resp.error || "导入失败", "error");
          return;
        }
        renderImportResult(resp);
        toast(
          "导入完成：成功 " + resp.imported + "、跳过 " + resp.skipped + "、失败 " + resp.failed,
          "success"
        );
      } catch (e) {
        toast("导入失败：" + (e.message || e), "error");
      } finally {
        importFile.value = "";
      }
    });
  }

  /* 初始化：有编辑态走 applyEdit，否则（新建）也要渲染默认图床的字段 */
  if (EDIT) applyEdit();
  else renderFields();
})();
