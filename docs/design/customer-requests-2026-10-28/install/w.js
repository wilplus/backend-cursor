/* WillpowerLab customer-requests widget · w.js (prototype)
   The client pastes one tag before </body>:
     <script src="https://willpowerlab.com/w.js" data-key="ws_…" async></script>
   What this file does on the client's page:
     1. reads its data-key;
     2. (production) GET https://willpowerlab.com/v2/public/widget/{key} → the workspace's name, colour,
        answerer and the signed words; the key is only valid from the domains listed on the workspace;
     3. mounts ONE element at the end of <body>, inside a shadow root, so the shop's CSS and ours never touch;
     4. on tap opens the form; (production) the form is an <iframe> to https://willpowerlab.com/w/{key}/ask,
        so the photo, the phone number and the consent never pass through the client's page or scripts;
        this prototype draws the form inline instead, because the demo page cannot embed another site;
     5. Send → (production) POST multipart to https://willpowerlab.com/v2/public/requests: the key, the
        words, the photo, the phone number, the consent tick and its wording version → a guest identity
        for the customer and one request row in the workspace → the request lands in the answerer's chat.
   Nothing is stored on the client's site. The client's page learns only that the widget was opened. */
(function () {
  "use strict";
  var tag = document.currentScript;
  var key = (tag && tag.getAttribute("data-key")) || "ws_demo";
  // Production: fetched from /v2/public/widget/{key}. Here: the demo workspace.
  var cfg = {
    shop: "Mila Hair Studio", answerer: "Marta", role: "trichologist", color: "#1D4F3F",
    cta: "Not sure which one? Ask Marta.",
    sub: "Our trichologist answers you with a short video, within a day.",
    title: "Show Marta your scalp or hair. She answers with a short video and what to use.",
    consent: "Mila Hair Studio may use what I wrote and my photo to advise me about my hair and scalp, and may message me on WhatsApp.",
    policy: "How Mila keeps it",
    key: key
  };
  if (document.getElementById("wpl-widget")) return;
  var host = document.createElement("div");
  host.id = "wpl-widget";
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML =
    '<style>' +
    ':host{all:initial;position:fixed;inset:0 0 auto auto;z-index:2147483000;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#1b1b1b}' +
    '[hidden]{display:none!important}*{box-sizing:border-box}button{font:inherit;cursor:pointer}' +
    '.btn{position:fixed;right:max(16px,env(safe-area-inset-right,0px));bottom:max(16px,env(safe-area-inset-bottom,0px));display:flex;align-items:center;gap:12px;padding:12px 16px 12px 12px;border-radius:18px;background:#fff;border:1px solid #e3ded5;box-shadow:0 8px 28px rgba(20,40,30,.18);text-align:left;max-width:min(360px,calc(100vw - 32px))}' +
    '.btn .av{width:44px;height:44px;border-radius:50%;background:' + cfg.color + ';display:grid;place-items:center;flex:none}' +
    '.btn b{display:block;font-size:15px;font-weight:600;line-height:1.3}.btn small{display:block;font-size:12.5px;color:#666;line-height:1.35}' +
    '.btn:focus-visible,.x:focus-visible,.send:focus-visible{outline:2px solid #1d6fe0;outline-offset:2px}' +
    '.ov{position:fixed;inset:0;background:rgba(27,27,27,.45);display:flex;align-items:flex-end;justify-content:center}' +
    '@media(min-width:640px){.ov{align-items:center}}' +
    '.sheet{background:#fff;width:100%;max-width:440px;max-height:calc(100% - 24px);overflow:auto;border-radius:24px 24px 0 0;padding:18px 20px 22px;display:flex;flex-direction:column;gap:14px}' +
    '@media(min-width:640px){.sheet{border-radius:24px;max-height:calc(100% - 48px)}}' +
    '.who{display:flex;align-items:center;justify-content:space-between}.who .l{display:flex;align-items:center;gap:10px}.who .pv{width:36px;height:36px;border-radius:50%;background:#c9d6cf}' +
    '.who b{display:block;font-size:15px}.who small{display:block;font-size:12px;color:#666}' +
    '.x{width:32px;height:32px;border-radius:50%;border:1px solid #e3ded5;background:#fff;display:grid;place-items:center;color:#666}' +
    'h3{margin:0;font-size:19px;font-weight:600;line-height:1.25}' +
    'label{font-size:13px;font-weight:600;color:#444;display:flex;flex-direction:column;gap:6px}' +
    'textarea,input[type=tel]{width:100%;border:1px solid #ddd6cb;border-radius:12px;padding:10px 12px;font:400 16px inherit;line-height:1.4;resize:none;color:#1b1b1b;background:#fff}' +
    '.photo{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:12px;border:1px dashed #c9c2b6;background:#faf7f2;text-align:left;color:#1b1b1b;width:100%}' +
    '.photo.on{border-style:solid;border-color:' + cfg.color + '}.photo img{width:44px;height:44px;border-radius:8px;object-fit:cover}' +
    '.photo b{display:block;font-size:14px}.photo small{display:block;font-size:12px;color:#666}' +
    '.consent{display:flex;align-items:flex-start;gap:10px;font-size:12.5px;line-height:1.4;color:#444;font-weight:400;flex-direction:row}' +
    '.consent input{width:18px;height:18px;margin:1px 0 0;flex-shrink:0;accent-color:' + cfg.color + '}.consent u{color:' + cfg.color + '}' +
    '.send{display:flex;align-items:center;justify-content:center;height:50px;border-radius:14px;background:' + cfg.color + ';color:#fff;font-size:16px;font-weight:600;border:0;width:100%}.send:disabled{opacity:.4;cursor:default}' +
    '.pby{text-align:center;font-size:11px;color:#999}' +
    '.sent{align-items:center;text-align:center}.sent .ok{width:56px;height:56px;border-radius:50%;background:#e4efe9;display:grid;place-items:center}' +
    '.sent p{margin:0;font-size:15px;line-height:1.45;color:#444;max-width:300px}.box{width:100%;border-radius:12px;background:#faf7f2;padding:12px 14px;text-align:left;font-size:13.5px;line-height:1.45;color:#444}' +
    '@media(prefers-reduced-motion:no-preference){.sheet{animation:rise .25s ease both}@keyframes rise{from{transform:translateY(40px);opacity:0}}}' +
    '</style>' +
    '<button class="btn" type="button" id="open" aria-haspopup="dialog">' +
      '<span class="av"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg></span>' +
      '<span><b>' + cfg.cta + '</b><small>' + cfg.sub + '</small></span>' +
    '</button>' +
    '<div class="ov" id="ov" role="dialog" aria-modal="true" aria-label="Ask ' + cfg.answerer + '" hidden><div class="sheet" id="sheet"></div></div>';
  document.body.appendChild(host);

  var $ = function (s) { return root.querySelector(s); };
  var ov = $("#ov"), sheet = $("#sheet");
  var state = { photo: null, text: "", phone: "", consent: false };
  var esc = function (t) { return String(t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };

  function form() {
    sheet.innerHTML =
      '<div class="who"><span class="l"><span class="pv"></span><span><b>' + cfg.answerer + ', ' + cfg.role + '</b><small>' + cfg.shop + '</small></span></span><button class="x" type="button" id="close" aria-label="Close"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button></div>' +
      '<h3>' + cfg.title + '</h3>' +
      '<label class="photo' + (state.photo ? " on" : "") + '" for="file">' + (state.photo ? '<img src="' + state.photo + '" alt="">' : '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="' + cfg.color + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>') +
        '<span><b>' + (state.photo ? "Photo added. Tap to change" : "Add a photo of your scalp or hair") + '</b><small>Deleted 30 days after the answer.</small></span><input id="file" type="file" accept="image/*" capture="environment" hidden></label>' +
      '<label>Or tell her in a few words (optional)<textarea id="text" rows="2" placeholder="Itchy for two months, I wash every day…">' + esc(state.text) + '</textarea></label>' +
      '<label>Your WhatsApp number, for the answer<input id="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="+48 600 000 000" value="' + esc(state.phone) + '"></label>' +
      '<label class="consent" for="ck"><input id="ck" type="checkbox"' + (state.consent ? " checked" : "") + '><span>' + cfg.consent + ' <u>' + cfg.policy + '</u>.</span></label>' +
      '<button class="send" type="button" id="send" disabled>Send to ' + cfg.answerer + '</button>' +
      '<div class="pby">powered by WillpowerLab</div>';
    var file = $("#file"), text = $("#text"), phone = $("#phone"), ck = $("#ck"), send = $("#send");
    var sync = function () {
      state.text = text.value; state.phone = phone.value; state.consent = ck.checked;
      send.disabled = !(ck.checked && (state.photo || text.value.trim()) && /^\+?[\d\s\-().]{8,}$/.test(phone.value));
    };
    text.oninput = sync; phone.oninput = sync; ck.onchange = sync; sync();
    file.onchange = function () {
      var f = file.files && file.files[0]; if (!f) return;
      var r = new FileReader(); r.onload = function () { state.photo = r.result; form(); }; r.readAsDataURL(f);
    };
    $("#close").onclick = close;
    send.onclick = function () {
      send.disabled = true; send.textContent = "Sending…";
      // Production: POST multipart to https://willpowerlab.com/v2/public/requests with the key, the words,
      // the photo, the phone number and the consent version. The response is the request id; nothing else.
      setTimeout(sent, 700);
    };
  }
  function sent() {
    sheet.innerHTML =
      '<div class="sent" style="display:flex;flex-direction:column;gap:16px">' +
        '<span class="ok"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="' + cfg.color + '" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5"/></svg></span>' +
        '<h3>Sent to ' + cfg.answerer + '.</h3>' +
        '<p>She will watch what you sent, record a short video for you, and you will get it on WhatsApp within a day.</p>' +
        '<div class="box"><b style="display:block;color:#1b1b1b;margin-bottom:4px">What you sent</b>' + (state.text.trim() ? esc(state.text.trim()) : "Your photo") + (state.photo && state.text.trim() ? ' <span style="color:#888">· 1 photo</span>' : "") + '</div>' +
        '<button class="send" type="button" id="back">Back to the shop</button>' +
        '<div class="pby">powered by WillpowerLab</div>' +
      '</div>';
    $("#back").onclick = function () { close(); state = { photo: null, text: "", phone: "", consent: false }; };
    try { window.dispatchEvent(new CustomEvent("wpl:sent", { detail: { key: cfg.key } })); } catch (e) {}
  }
  function open() { ov.hidden = false; form(); document.documentElement.style.overflow = "hidden"; var t = $("#file"); if (t) { var ph = $(".photo"); if (ph) ph.focus(); } }
  function close() { ov.hidden = true; document.documentElement.style.overflow = ""; $("#open").focus(); }
  $("#open").onclick = open;
  ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
  root.addEventListener("keydown", function (e) { if (e.key === "Escape" && !ov.hidden) close(); });
  try { window.dispatchEvent(new CustomEvent("wpl:ready", { detail: { key: cfg.key } })); } catch (e) {}
})();
