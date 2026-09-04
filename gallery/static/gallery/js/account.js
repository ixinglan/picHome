/* ==========================================================================
   picHome · 用户菜单（头像 + 昵称下拉）与用户管理弹窗
   · 顶栏用户名 → 下拉（用户管理 / 退出登录）
   · 用户管理：修改头像（本地预览）、昵称、密码
   · 仅在所有已登录页面加载（base.html 内 {% if user.is_authenticated %}）
   ========================================================================== */
(function () {
  "use strict";

  const trigger = document.getElementById("userTrigger");
  if (!trigger) return;                       // 未登录页不初始化
  const dropdown = document.getElementById("userDropdown");
  const csrf = document.querySelector('meta[name="csrf-token"]').content;

  /* ---------- 下拉开关 ---------- */
  function setOpen(open) {
    dropdown.hidden = !open;
    trigger.setAttribute("aria-expanded", open ? "true" : "false");
  }
  trigger.addEventListener("click", function (e) {
    e.stopPropagation();
    setOpen(dropdown.hidden);                 // 切换
  });
  document.addEventListener("click", function (e) {
    if (
      !dropdown.hidden &&
      !dropdown.contains(e.target) &&
      e.target !== trigger &&
      !trigger.contains(e.target)
    ) {
      setOpen(false);
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !dropdown.hidden) setOpen(false);
  });

  /* ---------- 用户管理弹窗 ---------- */
  const accountModal = document.getElementById("accountModal");
  const openAccountBtn = document.getElementById("openAccountBtn");
  const avatarInput = document.getElementById("avatarInput");
  const acctAvatar = document.getElementById("acctAvatar");
  const nicknameInput = document.getElementById("nicknameInput");
  const oldPwd = document.getElementById("oldPwd");
  const newPwd = document.getElementById("newPwd");
  const newPwd2 = document.getElementById("newPwd2");
  const saveBtn = document.getElementById("saveAccountBtn");
  const acctError = document.getElementById("acctError");

  let avatarFile = null;

  function closeAccount() { accountModal.hidden = true; }
  function showError(msg) { acctError.textContent = msg; acctError.hidden = false; }
  function clearError() { acctError.hidden = true; acctError.textContent = ""; }

  openAccountBtn.addEventListener("click", function () {
    setOpen(false);
    clearError();
    oldPwd.value = "";
    newPwd.value = "";
    newPwd2.value = "";
    avatarFile = null;
    accountModal.hidden = false;
  });

  accountModal.querySelectorAll("[data-close-account]").forEach(function (el) {
    el.addEventListener("click", closeAccount);
  });

  // 头像本地预览（FileReader，无需上传即可看到效果）
  avatarInput.addEventListener("change", function () {
    const f = avatarInput.files && avatarInput.files[0];
    if (!f) return;
    avatarFile = f;
    const reader = new FileReader();
    reader.onload = function (ev) {
      acctAvatar.innerHTML = '<img src="' + ev.target.result + '" alt="头像">';
    };
    reader.readAsDataURL(f);
  });

  saveBtn.addEventListener("click", function () {
    clearError();
    const fd = new FormData();
    fd.append("nickname", nicknameInput.value.trim());
    if (avatarFile) fd.append("avatar", avatarFile);
    fd.append("old_password", oldPwd.value);
    fd.append("new_password", newPwd.value);
    fd.append("new_password2", newPwd2.value);

    saveBtn.disabled = true;
    saveBtn.textContent = "保存中…";
    fetch("/settings/account/", {
      method: "POST",
      headers: { "X-CSRFToken": csrf },
      body: fd,
    })
      .then(function (r) {
        const ct = r.headers.get("content-type") || "";
        if (!ct.includes("application/json")) {
          return { ok: false, error: "登录状态已失效，请刷新页面重新登录" };
        }
        return r.json();
      })
      .then(function (resp) {
        if (resp.ok) {
          // 顶栏昵称同步
          const nameEl = document.querySelector(".user-name");
          if (nameEl) {
            nameEl.textContent = resp.nickname;
            nameEl.title = resp.nickname;
          }
          // 顶栏头像同步（若有新头像）
          if (resp.avatar_url) {
            const old = document.querySelector(".user-avatar");
            if (old) {
              const img = document.createElement("img");
              img.className = "user-avatar";
              img.src = resp.avatar_url + "?t=" + Date.now();
              img.alt = "";
              old.replaceWith(img);
            }
          }
          closeAccount();
          toast("已保存");
        } else {
          showError(resp.error || "保存失败");
        }
      })
      .catch(function () {
        showError("网络错误，请重试");
      })
      .finally(function () {
        saveBtn.disabled = false;
        saveBtn.textContent = "保存";
      });
  });

  function toast(msg) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.className = "toast show";
    setTimeout(function () { el.className = "toast"; }, 2400);
  }
})();
