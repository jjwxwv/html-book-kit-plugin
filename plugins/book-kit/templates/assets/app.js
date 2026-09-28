/* Claude HTML Book Kit v9 — base behavior. Depends on markup conventions in
   the shells: #toc, #progress, #theme-toggle, headings with id="sec-*",
   and window.BOOK from assets/book-data.js. */
(function () {
  "use strict";
  var BOOK = window.BOOK || { slug: "book", sections: [], pages: [] };
  var store = { key: "hbk:" + BOOK.slug };

  function lsGet(k, fallback) {
    try { var v = localStorage.getItem(store.key + ":" + k); return v === null ? fallback : JSON.parse(v); }
    catch (e) { return fallback; }
  }
  function lsSet(k, v) {
    try { localStorage.setItem(store.key + ":" + k, JSON.stringify(v)); } catch (e) {}
  }

  /* ---------- theme (light / dark / auto) ---------- */
  var THEMES = ["auto", "light", "dark"];
  var ICONS = { auto: "◐ อัตโนมัติ", light: "☀ สว่าง", dark: "☾ มืด" };
  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function applyTheme(mode) {
    document.documentElement.setAttribute("data-theme", mode === "auto" ? systemTheme() : mode);
  }
  var themeMode = lsGet("theme", "auto");
  applyTheme(themeMode);
  var toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.textContent = ICONS[themeMode];
    toggle.addEventListener("click", function () {
      themeMode = THEMES[(THEMES.indexOf(themeMode) + 1) % THEMES.length];
      lsSet("theme", themeMode);
      applyTheme(themeMode);
      toggle.textContent = ICONS[themeMode];
    });
  }
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var onSystemTheme = function () { if (themeMode === "auto") applyTheme("auto"); };
    /* addListener fallback: on Safari <14 the unguarded addEventListener call
       threw and killed everything below (progress bar, TOC, copy buttons) */
    if (mq.addEventListener) mq.addEventListener("change", onSystemTheme);
    else if (mq.addListener) mq.addListener(onSystemTheme);
  }

  /* ---------- page reading progress bar ---------- */
  var bar = document.getElementById("progress");
  function updateBar() {
    if (!bar) return;
    var doc = document.documentElement;
    var max = doc.scrollHeight - window.innerHeight;
    var pct = max > 0 ? (window.scrollY / max) * 100 : 100;
    pct = Math.min(100, Math.max(0, pct));
    bar.style.width = pct + "%";
    bar.setAttribute("aria-valuenow", String(Math.round(pct)));
  }
  window.addEventListener("scroll", updateBar, { passive: true });
  window.addEventListener("resize", updateBar);
  updateBar();

  /* ---------- mobile TOC drawer ---------- */
  var openBtn = document.getElementById("toc-open");
  if (openBtn) {
    openBtn.addEventListener("click", function () {
      document.body.classList.toggle("toc-visible");
    });
    document.addEventListener("click", function (e) {
      if (document.body.classList.contains("toc-visible") &&
          !e.target.closest("#toc") && !e.target.closest("#toc-open")) {
        document.body.classList.remove("toc-visible");
      }
    });
  }

  /* ---------- TOC: twisties + filter + scrollspy + read marks ---------- */
  var toc = document.getElementById("toc");
  var tocLinks = toc ? Array.prototype.slice.call(toc.querySelectorAll("a")) : [];

  toc && toc.addEventListener("click", function (e) {
    var t = e.target.closest(".twisty");
    if (!t) return;
    var li = t.closest("li");
    var collapsed = li.classList.toggle("collapsed");
    t.setAttribute("aria-expanded", String(!collapsed));
  });

  var filter = document.getElementById("toc-filter");
  if (filter && toc) {
    filter.addEventListener("input", function () {
      var q = filter.value.trim().toLowerCase();
      toc.querySelectorAll(".toc-tree li").forEach(function (li) {
        if (!q) { li.style.display = ""; li.classList.remove("collapsed"); return; }
        var hit = li.textContent.toLowerCase().indexOf(q) !== -1;
        li.style.display = hit ? "" : "none";
        if (hit) {
          li.classList.remove("collapsed");
          var p = li.parentElement.closest("li");
          while (p) { p.style.display = ""; p.classList.remove("collapsed"); p = p.parentElement.closest("li"); }
        }
      });
    });
  }

  function pageName() {
    var p = location.pathname.split("/").pop();
    return p || "index.html";
  }
  function linkFor(anchorId) {
    var suffix = pageName() + "#" + anchorId;
    for (var i = 0; i < tocLinks.length; i++) {
      var href = tocLinks[i].getAttribute("href") || "";
      if (href === "#" + anchorId || href === suffix || href.slice(-suffix.length) === suffix) return tocLinks[i];
    }
    return null;
  }

  var headings = Array.prototype.slice.call(
    document.querySelectorAll('main [id^="sec-"]'));
  var readSet = new Set(lsGet("read", []));

  function refreshBookProgress() {
    var total = (BOOK.sections || []).length;
    var read = 0;
    (BOOK.sections || []).forEach(function (s) { if (readSet.has(s.id)) read++; });
    var box = document.querySelector(".book-progress");
    if (!box || !total) return;
    var pct = Math.round((read / total) * 100);
    var label = box.querySelector(".label");
    var fill = box.querySelector(".bar > span");
    if (label) label.textContent = "อ่านแล้ว " + read + "/" + total + " หัวข้อ (" + pct + "%)";
    if (fill) fill.style.width = pct + "%";
  }
  function markRead(secId) {
    if (readSet.has(secId)) return;
    readSet.add(secId);
    lsSet("read", Array.from(readSet));
    var a = linkFor("sec-" + secId.replace(/\./g, "-"));
    if (a) a.classList.add("read");
    refreshBookProgress();
  }
  tocLinks.forEach(function (a) {
    var m = (a.getAttribute("href") || "").match(/#sec-([\d-]+)$/);
    if (m && readSet.has(m[1].replace(/-/g, "."))) a.classList.add("read");
  });
  refreshBookProgress();

  if ("IntersectionObserver" in window && headings.length) {
    var current = null;
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          if (current) current.classList.remove("current");
          var a = linkFor(en.target.id);
          if (a) { a.classList.add("current"); current = a; }
        }
      });
    }, { rootMargin: "0px 0px -70% 0px", threshold: 0 });
    headings.forEach(function (h) { spy.observe(h); });

    var reader = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.boundingClientRect.bottom < 0 || en.isIntersecting) {
          markRead(en.target.id.replace(/^sec-/, "").replace(/-/g, "."));
        }
      });
    }, { rootMargin: "0px 0px -55% 0px", threshold: 0 });
    headings.forEach(function (h) { reader.observe(h); });
    window.addEventListener("beforeunload", function () {
      // bottom of page counts the last sections as read
      if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 40) {
        headings.forEach(function (h) {
          markRead(h.id.replace(/^sec-/, "").replace(/-/g, "."));
        });
      }
    });
  }

  /* ---------- code copy buttons ---------- */
  /* skip mermaid blocks: mermaid replaces their content with an SVG diagram */
  document.querySelectorAll("pre:not(.mermaid)").forEach(function (pre) {
    var btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.type = "button";
    btn.textContent = "คัดลอก";
    btn.addEventListener("click", function () {
      var src = pre.querySelector("code");
      if (!src) {
        // bare <pre>: clone and strip the copy button so its own label
        // is not included in the copied text
        src = pre.cloneNode(true);
        var b = src.querySelector(".copy-btn");
        if (b) b.remove();
      }
      var text = src.innerText.replace(/\u00a0/g, " ");
      (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
        .then(function () { btn.textContent = "คัดลอกแล้ว ✓"; })
        .catch(function () { btn.textContent = "กด Ctrl+C"; });
      setTimeout(function () { btn.textContent = "คัดลอก"; }, 1600);
    });
    pre.appendChild(btn);
  });
})();
