(function () {
  "use strict";

  var enrollmentToken = "";
  var form = document.getElementById("bindForm");
  var tokenState = document.getElementById("tokenState");
  var tokenStateText = document.getElementById("tokenStateText");
  var manualCodeField = document.getElementById("manualCodeField");
  var manualCode = document.getElementById("manualCode");
  var barkUrl = document.getElementById("barkUrl");
  var deviceName = document.getElementById("deviceName");
  var submit = document.getElementById("bindSubmit");
  var result = document.getElementById("bindResult");

  function readAndEraseToken() {
    var params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    enrollmentToken = (params.get("token") || "").trim();
    window.history.replaceState(null, document.title, window.location.pathname);
    if (enrollmentToken.length >= 32 && enrollmentToken.length <= 256) {
      tokenState.classList.add("is-ready");
      tokenStateText.textContent = "一次性绑定码已识别 · 5 分钟内有效";
      manualCodeField.hidden = true;
      return;
    }
    enrollmentToken = "";
    tokenState.classList.add("is-manual");
    tokenStateText.textContent = "请输入 Android 显示的 6 位备用码";
    manualCodeField.hidden = false;
  }

  function show(message, state) {
    result.textContent = message;
    result.className = "result" + (state ? " is-" + state : "");
  }

  function setBusy(busy) {
    submit.disabled = busy;
    submit.textContent = busy ? "正在验证并绑定" : "绑定并发送测试";
  }

  function validOfficialBarkUrl(value) {
    try {
      var parsed = new URL(value);
      var segments = parsed.pathname.split("/").filter(Boolean);
      return parsed.protocol === "https:"
        && parsed.hostname.toLowerCase() === "api.day.app"
        && (parsed.port === "" || parsed.port === "443")
        && parsed.username === ""
        && parsed.password === ""
        && segments.length > 0
        && /^[A-Za-z0-9_-]{16,200}$/.test(decodeURIComponent(segments[0]));
    } catch (_error) {
      return false;
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var url = barkUrl.value.trim();
    var code = manualCode.value.replace(/\D/g, "");
    if (!enrollmentToken && code.length !== 6) {
      show("请输入 Android 显示的 6 位备用码", "error");
      manualCode.focus();
      return;
    }
    if (!validOfficialBarkUrl(url)) {
      show("请粘贴 Bark 首页复制的完整 https://api.day.app/ 测试地址", "error");
      barkUrl.focus();
      return;
    }

    setBusy(true);
    show("正在验证 Bark 并发送测试通知", "");
    var controller = new AbortController();
    var timeout = window.setTimeout(function () { controller.abort(); }, 16000);
    fetch("/xxzf/v1/bark/enroll/claim", {
      method: "POST",
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      headers: {"Content-Type": "application/json; charset=utf-8"},
      body: JSON.stringify({
        token: enrollmentToken,
        code: enrollmentToken ? "" : code,
        barkUrl: url,
        deviceName: deviceName.value.trim() || "iPhone"
      }),
      signal: controller.signal
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok || !body.ok) {
          throw new Error(body.error || "绑定失败，请稍后重试");
        }
      });
    }).then(function () {
      enrollmentToken = "";
      barkUrl.value = "";
      tokenState.classList.remove("is-manual");
      tokenState.classList.add("is-ready");
      tokenStateText.textContent = "绑定成功";
      show("绑定成功。iPhone 已收到测试通知，现在可以关闭此页面。", "success");
      submit.hidden = true;
      Array.prototype.forEach.call(form.querySelectorAll("input"), function (input) {
        input.disabled = true;
      });
    }).catch(function (error) {
      show(error && error.name === "AbortError"
        ? "连接超时，请检查网络后重试"
        : (error.message || "绑定失败，请稍后重试"), "error");
    }).finally(function () {
      window.clearTimeout(timeout);
      setBusy(false);
    });
  });

  readAndEraseToken();
}());
