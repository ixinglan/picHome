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
      if (!confirm("确定删除该图床配置？")) return;
      const id = btn.getAttribute("data-delete");
      const resp = await fetch("/settings/storage/", {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken, "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ action: "delete", id }),
      }).then((r) => r.json());
      if (resp.ok) location.reload();
      else toast(resp.error || "删除失败", "error");
    });
  });

  /* 初始化：有编辑态走 applyEdit，否则（新建）也要渲染默认图床的字段 */
  if (EDIT) applyEdit();
  else renderFields();
})();
