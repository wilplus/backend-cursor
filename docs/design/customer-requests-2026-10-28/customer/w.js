/* WillpowerLab customer-requests widget · w.js (prototype, Invita Head Spa workspace, minimal)
   One tag before </body>:  <script src="https://willpowerlab.com/w.js" data-key="ws_…" async></script>
   One typeface (the system's), white and grey only. A pill at the bottom right, a popup once per visitor,
   a form of a photo, a few words, an optional first name, a number and a tick. Mounted in one shadow root; the host page's CSS and ours never touch.
   In production the form is an <iframe> to willpowerlab.com/w/<key>/ask; this prototype draws it inline. */
(function () {
  "use strict";
  var tag = document.currentScript;
  var key = (tag && tag.getAttribute("data-key")) || "ws_invita";
  // data-mount="#id": mount inside that element instead of the page (used by prototypes that draw a phone); same script otherwise.
  var mountSel = tag && tag.getAttribute("data-mount");
  var mount = mountSel ? document.querySelector(mountSel) : null;
  var pos = mount ? "absolute" : "fixed";
  var delayAttr = tag && tag.getAttribute("data-popup-delay");
  var cfg = {
    shop: "Invita Head Spa", who: "our trichologist",
    pill: "Ask our trichologist",
    popupTitle: "Not sure which treatment?",
    popupText: "Send a photo of your scalp. Our trichologist answers you within a day.",
    consent: "Invita may use my photo and words to advise me, and text me the answer.",
    popupDelay: delayAttr ? Number(delayAttr) : 2200, popupKey: "wpl-popup-" + key
  };
  if (document.getElementById("wpl-widget")) return;
  var host = document.createElement("div");
  host.id = "wpl-widget";
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML =
    '<style>' +
    ':host{all:initial;position:' + pos + ';inset:0;pointer-events:none;z-index:2147483000;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1a1a1a;font-size:15px;line-height:1.45}' +
    '[hidden]{display:none!important}*{box-sizing:border-box}button{font:inherit;cursor:pointer;color:inherit}.pill,.scrim{pointer-events:auto}' +
    '.pill{position:' + pos + ';right:max(16px,env(safe-area-inset-right,0px));bottom:max(16px,env(safe-area-inset-bottom,0px));height:44px;padding:0 18px;border-radius:999px;background:#fff;border:1px solid #d9d9d9;box-shadow:0 2px 12px rgba(0,0,0,.08);font-size:14px;font-weight:500;white-space:nowrap}' +
    '.pill:hover{border-color:#1a1a1a}' +
    '.pill:focus-visible,.x:focus-visible,.go:focus-visible,.no:focus-visible,.photo:focus-visible{outline:2px solid #1a1a1a;outline-offset:2px}' +
    '.scrim{position:' + pos + ';inset:0;background:rgba(0,0,0,.3);display:flex;align-items:flex-end;justify-content:center}' +
    '@media(min-width:640px){.scrim{align-items:center;padding:24px}}' +
    '.pop{background:#fff;width:100%;max-width:380px;padding:24px 20px 20px;display:flex;flex-direction:column;gap:14px;border-radius:16px 16px 0 0;position:relative}' +
    '@media(min-width:640px){.pop{border-radius:16px;max-height:calc(100% - 48px);overflow:auto}}' +
    'h2{margin:0;font-size:20px;font-weight:600;line-height:1.25;padding-right:36px}' +
    'p{margin:0;color:#6b6b6b}' +
    '.x{position:absolute;top:14px;right:14px;width:32px;height:32px;border-radius:50%;border:0;background:#f2f2f2;display:grid;place-items:center;color:#6b6b6b}' +
    '.go{height:48px;border-radius:12px;background:#1a1a1a;color:#fff;border:0;width:100%;font-size:15px;font-weight:600}' +
    '.go:disabled{background:#e4e4e4;color:#9a9a9a;cursor:default}' +
    '.no{border:0;background:none;color:#6b6b6b;font-size:14px;padding:6px}' +
    '.by{font-size:12px;color:#9a9a9a;text-align:center}' +
    '.photo{display:flex;align-items:center;gap:12px;padding:14px;border:1px dashed #c8c8c8;border-radius:12px;background:#fff;text-align:left;width:100%;color:#1a1a1a}' +
    '.photo.on{border-style:solid;border-color:#1a1a1a}.photo img{width:44px;height:44px;border-radius:8px;object-fit:cover}' +
    '.photo .ic{width:44px;height:44px;border-radius:8px;background:#f2f2f2;display:grid;place-items:center;flex:none}' +
    '.photo b{display:block;font-size:15px;font-weight:600}.photo small{display:block;font-size:13px;color:#6b6b6b}' +
    '.fld{width:100%;height:48px;border:1px solid #d9d9d9;border-radius:12px;padding:0 14px;font:inherit;color:#1a1a1a;background:#fff}' +
    'textarea.fld{height:auto;padding:12px 14px;resize:none}' +
    '.fld::placeholder{color:#9a9a9a}.fld:focus{outline:none;border-color:#1a1a1a}' +
    '.ck{display:flex;align-items:flex-start;gap:10px;font-size:13px;line-height:1.4;color:#6b6b6b}' +
    '.ck input{width:18px;height:18px;margin:1px 0 0;flex-shrink:0;accent-color:#1a1a1a}.ck u{color:#1a1a1a}' +
    '.sent{align-items:center;text-align:center}.ok{width:48px;height:48px;border-radius:50%;background:#f2f2f2;display:grid;place-items:center}' +
    '@media(prefers-reduced-motion:no-preference){.pop{animation:rise .24s ease both}@keyframes rise{from{transform:translateY(20px);opacity:0}}}' +
    '</style>' +
    '<button class="pill" type="button" id="open">' + cfg.pill + '</button>' +
    '<div class="scrim" id="scrim" role="dialog" aria-modal="true" aria-label="Ask ' + cfg.who + '" hidden><div class="pop" id="pop"></div></div>';
  (mount || document.body).appendChild(host);

  var $ = function (s) { return root.querySelector(s); };
  var scrim = $("#scrim"), pop = $("#pop");
  var state = { photo: null, text: "", name: "", phone: "", consent: false };
  var esc = function (t) { return String(t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var xBtn = '<button class="x" type="button" id="close" aria-label="Close"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button>';
  var cam = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6b6b6b" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>';

  function show() { scrim.hidden = false; if (!mount) document.documentElement.style.overflow = "hidden"; }
  function close() { scrim.hidden = true; if (!mount) document.documentElement.style.overflow = ""; $("#open").focus(); }
  var step = function (n) { try { window.dispatchEvent(new CustomEvent("wpl:step", { detail: { step: n } })); } catch (e) {} };
  var done = function () { try { window.dispatchEvent(new CustomEvent("wpl:done", { detail: { key: key } })); } catch (e) {} };
  function remember() { try { localStorage.setItem(cfg.popupKey, String(Date.now())); } catch (e) {} }
  function popupDue() { try { return Date.now() - Number(localStorage.getItem(cfg.popupKey) || 0) > 30 * 864e5; } catch (e) { return true; } }

  function popup() {
    step("popup");
    pop.className = "pop";
    pop.innerHTML = xBtn + '<h2>' + cfg.popupTitle + '</h2><p>' + cfg.popupText + '</p>' +
      '<button class="go" type="button" id="yes">Ask</button><button class="no" type="button" id="no">Not now</button>';
    $("#close").onclick = function () { remember(); close(); };
    $("#no").onclick = function () { remember(); close(); };
    $("#yes").onclick = form;
    show(); $("#yes").focus();
  }
  function form() {
    step("form");
    pop.className = "pop";
    pop.innerHTML = xBtn + '<h2>Ask our trichologist</h2>' +
      '<label class="photo' + (state.photo ? " on" : "") + '" for="file" tabindex="0">' + (state.photo ? '<img src="' + state.photo + '" alt="">' : '<span class="ic">' + cam + '</span>') +
        '<span><b>' + (state.photo ? "Photo added" : "Add a photo") + '</b><small>' + (state.photo ? "Tap to change" : "Your scalp or hair. Only our trichologist sees it.") + '</small></span><input id="file" type="file" accept="image/*" capture="environment" hidden></label>' +
      '<textarea class="fld" id="text" rows="2" placeholder="A few words, optional" aria-label="A few words, optional">' + esc(state.text) + '</textarea>' +
      '<input class="fld" id="name" type="text" autocomplete="given-name" placeholder="Your first name, optional" aria-label="Your first name, optional" value="' + esc(state.name) + '">' +
      '<input class="fld" id="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="Mobile number, for the answer" aria-label="Mobile number, for the answer" value="' + esc(state.phone) + '">' +
      '<label class="ck" for="ck"><input id="ck" type="checkbox"' + (state.consent ? " checked" : "") + '><span>' + cfg.consent + ' <u>Privacy</u></span></label>' +
      '<button class="go" type="button" id="send" disabled>Send</button><span class="by">WillpowerLab</span>';
    var file = $("#file"), text = $("#text"), name = $("#name"), phone = $("#phone"), ck = $("#ck"), send = $("#send");
    var sync = function () { state.text = text.value; state.name = name.value; state.phone = phone.value; state.consent = ck.checked; send.disabled = !(ck.checked && (state.photo || text.value.trim()) && /^\+?[\d\s\-().]{8,}$/.test(phone.value)); };
    text.oninput = sync; name.oninput = sync; phone.oninput = sync; ck.onchange = sync; sync();
    file.onchange = function () { var f = file.files && file.files[0]; if (!f) return; var r = new FileReader(); r.onload = function () { state.photo = r.result; form(); }; r.readAsDataURL(f); };
    $("#close").onclick = close;
    send.onclick = function () { send.disabled = true; send.textContent = "Sending…"; setTimeout(sent, 700); };
    show();
  }
  function sent() {
    step("sent");
    remember();
    pop.className = "pop sent";
    pop.innerHTML = xBtn + '<span class="ok"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1a1a1a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5"/></svg></span>' +
      '<h2 style="padding:0">Sent</h2><p>Our trichologist answers you by text within a day.</p>' +
      '<button class="go" type="button" id="back">Done</button><span class="by">WillpowerLab</span>';
    $("#close").onclick = function () { close(); done(); };
    $("#back").onclick = function () { close(); state = { photo: null, text: "", name: "", phone: "", consent: false }; done(); };
    try { window.dispatchEvent(new CustomEvent("wpl:sent", { detail: { key: key } })); } catch (e) {}
  }
  $("#open").onclick = form;
  scrim.addEventListener("click", function (e) { if (e.target === scrim) close(); });
  root.addEventListener("keydown", function (e) { if (e.key === "Escape" && !scrim.hidden) close(); if (e.key === "Enter" && e.target && e.target.classList && e.target.classList.contains("photo")) { var f = $("#file"); if (f) f.click(); } });
  window.addEventListener("wpl:popup", popup);
  if (popupDue() && cfg.popupDelay >= 0) setTimeout(function () { if (scrim.hidden) popup(); }, cfg.popupDelay);
  try { window.dispatchEvent(new CustomEvent("wpl:ready", { detail: { key: key } })); } catch (e) {}
})();
