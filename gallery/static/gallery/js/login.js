/* 登录页卡通角色交互：眼球追踪 / 倾斜 / 眨眼 / 偷看 / 躲避 / 登录态反馈
 * 纯原生 JS，零依赖，且不依赖 app.js（登录页未加载 app.js）。 */
(function () {
  "use strict";
  var mascot = document.getElementById("mascot");
  if (!mascot) return;

  var reduced = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var inner    = mascot.querySelector(".mascot-inner");
  var eyes     = Array.prototype.slice.call(mascot.querySelectorAll(".m-eye"));
  var pupils   = eyes.map(function (g) { return g.querySelector(".m-pupil"); });
  var EYE_R    = 7;      // 瞳孔可移动的最大半径(px)
  var MAX_TILT = 9;      // 角色朝鼠标倾斜的最大角度

  /* 当前语义状态：idle / peek / hide / peek-visible / loading / success / error
   * 只有 idle / loading 时眼球才跟随鼠标；其余状态锁定方向表达语义。 */
  var state = "idle";
  var PUPIL_R = 8.5;
  function setState(s) {
    if (state === s) return;
    state = s;
    mascot.setAttribute("data-state", s);
    pupils.forEach(function (p) { p.setAttribute("r", PUPIL_R); });   // 离开 loading 自动恢复
    // 锁定方向（不跟随鼠标）
    if (s === "peek")         setPupils(-2, 8);    // 朝左下瞟：偷看用户名框
    else if (s === "hide")    setPupils(9, -8);   // 朝右上：害羞转头不看密码
    else if (s === "peek-visible") setPupils(0, 9); // 朝下：偷看明文
    else if (s === "loading") { setPupils(0, 0); pupils.forEach(function (p) { p.setAttribute("r", 4); }); }
    // success / error 由 CSS 切换眼睛形状
  }

  /* 同时移动两只瞳孔（用 CSS transform 以便平滑过渡）*/
  function setPupils(dx, dy) {
    pupils.forEach(function (p) {
      p.style.transform = "translate(" + dx + "px," + dy + "px)";
    });
  }

  /* 眼球跟随鼠标：算出每只眼中心到鼠标的角度，沿该方向偏移 */
  function followCursor(clientX, clientY) {
    if (state !== "idle" && state !== "loading") return;
    var r = mascot.querySelector(".mascot-svg").getBoundingClientRect();
    // 以角色中心近似两只眼的共同注视方向（足够自然）
    var cx = r.left + r.width / 2;
    var cy = r.top + r.height * 0.46;
    var dx = clientX - cx;
    var dy = clientY - cy;
    var ang = Math.atan2(dy, dx);
    var dist = Math.min(EYE_R, Math.hypot(dx, dy) / 22);
    var ox = Math.cos(ang) * dist;
    var oy = Math.sin(ang) * dist;
    // 角色整体朝鼠标轻微倾斜
    if (!reduced) inner.style.transform = "rotate(" + (dx / window.innerWidth * MAX_TILT).toFixed(2) + "deg)";
    setPupils(ox, oy);
  }

  if (!reduced) {
    window.addEventListener("mousemove", function (e) { followCursor(e.clientX, e.clientY); }, { passive: true });
    window.addEventListener("mouseleave", function () { setPupils(0, 0); });
  }

  /* 眨眼：idle 时随机眨眼，偶尔在鼠标静止后"无聊"眨眼 */
  function blink() {
    if (reduced) return;
    mascot.classList.add("is-blink");
    setTimeout(function () { mascot.classList.remove("is-blink"); }, 260);
  }
  if (!reduced) {
    var blinkTimer = setInterval(function () { if (Math.random() < 0.6) blink(); }, 3200);
    // 鼠标静止超过 2.4s，角色偶尔无聊眨眼（并短暂移开视线）
    var idleTimer;
    function armIdle() {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(function () {
        if (state === "idle") { blink(); setPupils(4, -3); }
      }, 2400);
    }
    window.addEventListener("mousemove", armIdle, { passive: true });
    armIdle();
  }

  /* ---- 输入框聚焦语义 ---- */
  var userInput = document.getElementById("id_username");
  var pwdInput  = document.getElementById("id_password");
  var pwToggle  = document.getElementById("pwToggle");
  var authSub   = document.getElementById("authSub");

  function setSub(t) { if (authSub) authSub.textContent = t; }

  if (userInput) {
    userInput.addEventListener("focus", function () {
      setState("peek");
      setSub("我在偷看你的用户名哦～");
    });
    userInput.addEventListener("blur", function () {
      if (state === "peek") { setState("idle"); setSub("登录后管理你的云端图片"); }
    });
  }

  if (pwdInput) {
    function pwdFocused() {
      // 密文 → 躲避；明文 → 偷看
      if (pwdInput.type === "text") { setState("peek-visible"); setSub("既然你让我看，那我就瞟一眼啦"); }
      else { setState("hide"); setSub("密码？我转过头去，绝对不看"); }
    }
    pwdInput.addEventListener("focus", pwdFocused);
    pwdInput.addEventListener("blur", function () {
      if (state === "hide" || state === "peek-visible") { setState("idle"); setSub("登录后管理你的云端图片"); }
    });
  }

  /* 密码显示/隐藏切换：同步眼睛图标 + 角色语义 */
  if (pwToggle && pwdInput) {
    pwToggle.addEventListener("click", function () {
      var show = pwdInput.type === "password";
      pwdInput.type = show ? "text" : "password";
      pwToggle.setAttribute("aria-pressed", show ? "true" : "false");
      pwToggle.setAttribute("aria-label", show ? "隐藏密码" : "显示密码");
      if (document.activeElement === pwdInput) pwdFocused();
    });
  }

  /* 记住我 → 俏皮挤眼(wink) */
  var remember = document.getElementById("id_remember");
  if (remember) {
    remember.addEventListener("change", function () {
      if (remember.checked) {
        mascot.classList.add("is-wink");
        setSub("记住你啦，下次不用重新输～");
        setTimeout(function () { mascot.classList.remove("is-wink"); }, 700);
      }
    });
  }

  /* 提交：进入 loading（期待），成功/失败由后端跳转或返回 error 决定 */
  var form = document.getElementById("loginForm");
  var btn  = document.getElementById("loginBtn");
  if (form && btn) {
    form.addEventListener("submit", function () {
      setState("loading");
      setSub("正在登录，稍等一下下…");
      btn.disabled = true;
      // 后端校验失败会带着 error 重渲染页面（data-state 回到默认），
      // 这里仅处理「等待中」的视觉；超时兜底恢复可交互。
      setTimeout(function () { btn.disabled = false; }, 6000);
    });
  }

  /* 若模板已带 error（后端校验失败回来），让角色露出「失败」表情 */
  if (document.querySelector(".alert")) {
    setState("error");
    setSub("哎呀，用户名或密码不对～");
    setTimeout(function () {
      if (state === "error") { setState("idle"); setSub("登录后管理你的云端图片"); }
    }, 2600);
  }

  // 初始归位
  setPupils(0, 0);
})();
