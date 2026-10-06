/* Claude HTML Book Kit — behaviour. No dependencies.
   Needs: window.BOOK (assets/book-data.js, written by build_book.py), #toc, #progress,
   #theme-toggle and section anchors id="sec-*" inside <main>. All UI strings come from BOOK.t. */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement, body = doc.body;
  var BOOK = window.BOOK || { slug: "book", sections: [], pages: [], palettes: [], t: {} };
  var T = BOOK.t || {};
  var KEY = "hbk:" + BOOK.slug + ":";

  function get(k, d) {
    try { var v = localStorage.getItem(KEY + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; }
  }
  function set(k, v) { try { localStorage.setItem(KEY + k, JSON.stringify(v)); } catch (e) {} }
  function del(k) { try { localStorage.removeItem(KEY + k); } catch (e) {} }
  function $(s, c) { return (c || doc).querySelector(s); }
  function $$(s, c) { return Array.prototype.slice.call((c || doc).querySelectorAll(s)); }
  function fmt(s, o) {
    return String(s || "").replace(/\{(\w+)\}/g, function (m, k) { return o && k in o ? o[k] : m; });
  }
  function mq(q) {
    return window.matchMedia ? window.matchMedia(q) : { matches: false };
  }
  function onChange(m, fn) {
    if (m.addEventListener) m.addEventListener("change", fn);
    else if (m.addListener) m.addListener(fn); /* Safari < 14 */
  }
  var mobile = mq("(max-width: 60rem)");
  var sysDark = mq("(prefers-color-scheme: dark)");

  /* ---------- theme: auto / light / dark ---------- */
  var mode = get("theme", "auto");
  if (mode !== "light" && mode !== "dark") mode = "auto";
  var themeBtn = doc.getElementById("theme-toggle");
  function applyTheme() {
    root.setAttribute("data-theme", mode === "auto" ? (sysDark.matches ? "dark" : "light") : mode);
    if (themeBtn) {
      var label = T["theme_" + mode] || mode;
      themeBtn.setAttribute("data-mode", mode);
      themeBtn.setAttribute("aria-label", label);
      themeBtn.title = label;
    }
  }
  applyTheme();
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      /* the first click always changes what you see: auto -> the opposite of the system theme */
      var order = sysDark.matches ? ["auto", "light", "dark"] : ["auto", "dark", "light"];
      mode = order[(order.indexOf(mode) + 1) % order.length];
      set("theme", mode);
      applyTheme();
    });
  }
  onChange(sysDark, function () { if (mode === "auto") applyTheme(); });
  var themeBeforePrint = null;
  window.addEventListener("beforeprint", function () {
    themeBeforePrint = root.getAttribute("data-theme");
    root.setAttribute("data-theme", "light");
  });
  window.addEventListener("afterprint", function () {
    if (themeBeforePrint) root.setAttribute("data-theme", themeBeforePrint);
  });

  /* ---------- palette + text size (appearance popover) ---------- */
  var paletteNames = (BOOK.palettes || []).map(function (p) { return p.name; });
  function applyPalette(name, persist) {
    if (paletteNames.indexOf(name) < 0) return;
    root.setAttribute("data-palette", name);
    if (persist) set("palette", name);
    $$(".swatch").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-palette") === name));
    });
  }
  var storedPalette = get("palette", null);
  applyPalette(paletteNames.indexOf(storedPalette) >= 0 ? storedPalette : root.getAttribute("data-palette"), false);
  $$(".swatch").forEach(function (b) {
    b.addEventListener("click", function () { applyPalette(b.getAttribute("data-palette"), true); });
  });

  var fs = get("fs", 0);
  function applyFs(v, persist) {
    fs = Math.max(-1, Math.min(2, parseInt(v, 10) || 0));
    if (fs) root.setAttribute("data-fs", String(fs)); else root.removeAttribute("data-fs");
    if (persist) set("fs", fs);
    remeasure();
  }
  $$("[data-fs-step]").forEach(function (b) {
    b.addEventListener("click", function () {
      var step = parseInt(b.getAttribute("data-fs-step"), 10) || 0;
      applyFs(step === 0 ? 0 : fs + step, true);
    });
  });

  var pop = doc.getElementById("appearance"), popBtn = doc.getElementById("appearance-open");
  function setPop(open) {
    if (!pop || !popBtn) return;
    pop.hidden = !open;
    popBtn.setAttribute("aria-expanded", String(open));
  }
  if (pop && popBtn) {
    popBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      setPop(pop.hidden);
      if (!pop.hidden) { var first = $("button", pop); if (first) first.focus(); }
    });
    doc.addEventListener("click", function (e) {
      if (!pop.hidden && !e.target.closest("#appearance")) setPop(false);
    });
  }

  /* ---------- sidebar: drawer on small screens, collapsible on large ones ---------- */
  var toc = doc.getElementById("toc"), tocBtn = doc.getElementById("toc-open"), scrim = $(".scrim");
  function syncTocBtn() {
    if (!tocBtn) return;
    var open = mobile.matches ? body.classList.contains("toc-open") : !root.classList.contains("toc-hidden");
    tocBtn.setAttribute("aria-expanded", String(open));
  }
  function setDrawer(open) {
    body.classList.toggle("toc-open", open);
    if (scrim) scrim.hidden = !open;
    syncTocBtn();
  }
  if (tocBtn) {
    tocBtn.addEventListener("click", function () {
      if (mobile.matches) { setDrawer(!body.classList.contains("toc-open")); return; }
      var hide = !root.classList.contains("toc-hidden");
      root.classList.toggle("toc-hidden", hide);
      set("tocHidden", hide);
      syncTocBtn();
      remeasure();
    });
  }
  if (scrim) scrim.addEventListener("click", function () { setDrawer(false); });
  onChange(mobile, function () { setDrawer(false); remeasure(); });
  doc.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (pop && !pop.hidden) { setPop(false); if (popBtn) popBtn.focus(); }
    if (body.classList.contains("toc-open")) { setDrawer(false); if (tocBtn) tocBtn.focus(); }
  });
  syncTocBtn();

  /* ---------- TOC tree: chapters expand/collapse, filter ---------- */
  var chapters = toc ? $$(".toc-ch", toc) : [];
  var linkById = {};
  if (toc) {
    $$('a[href*="#sec-"]', toc).forEach(function (a) {
      var m = /#sec-([\d-]+)$/.exec(a.getAttribute("href") || "");
      if (m) linkById[m[1].replace(/-/g, ".")] = a;
    });
  }
  function setCollapsed(li, collapsed) {
    var t = $(".twisty", li);
    if (!t) return;
    li.classList.toggle("collapsed", collapsed);
    t.setAttribute("aria-expanded", String(!collapsed));
    t.setAttribute("aria-label", collapsed ? (T.expand || "Expand") : (T.collapse || "Collapse"));
  }
  chapters.forEach(function (li) { setCollapsed(li, li.classList.contains("collapsed")); });
  if (toc) {
    toc.addEventListener("click", function (e) {
      var t = e.target.closest(".twisty");
      if (t) { var li = t.closest(".toc-ch"); setCollapsed(li, !li.classList.contains("collapsed")); return; }
      if (e.target.closest("a") && mobile.matches) setDrawer(false);
    });
  }
  var filter = doc.getElementById("toc-filter"), emptyMsg = toc ? $(".toc-empty", toc) : null;
  if (filter && toc) {
    filter.addEventListener("input", function () {
      var q = filter.value.trim().toLowerCase(), any = false;
      chapters.forEach(function (ch) {
        var items = $$("li", ch);
        if (!q) {
          ch.hidden = false;
          items.forEach(function (li) { li.hidden = false; });
          setCollapsed(ch, !ch.classList.contains("active"));
          any = true;
          return;
        }
        var link = $(".toc-ch-link", ch);
        var chHit = !!link && link.textContent.toLowerCase().indexOf(q) >= 0, sub = false;
        items.forEach(function (li) {
          var hit = chHit || li.textContent.toLowerCase().indexOf(q) >= 0;
          li.hidden = !hit;
          if (hit) sub = true;
        });
        ch.hidden = !(chHit || sub);
        if (!ch.hidden) { any = true; setCollapsed(ch, false); }
      });
      if (emptyMsg) emptyMsg.hidden = any;
    });
  }

  /* ---------- reading state ---------- */
  var sections = BOOK.sections || [];
  var titleById = {}, hrefById = {};
  sections.forEach(function (s) { titleById[s.id] = s.title; hrefById[s.id] = s.href; });
  /* Chapters or sections were renumbered since this reader's progress was stored (BOOK.idHistory,
     oldest first): move the marks to the new ids instead of leaving them on whatever took the
     old number. */
  (function () {
    var history = BOOK.idHistory || [], epoch = get("idEpoch", 0);
    if (typeof epoch !== "number" || epoch < 0) epoch = 0;
    if (epoch >= history.length) { if (epoch > history.length) set("idEpoch", history.length); return; }
    function remap(id, map) {
      var best = null, k;
      for (k in map) {
        if (Object.prototype.hasOwnProperty.call(map, k) && (id === k || id.indexOf(k + ".") === 0) &&
            (best === null || k.length > best.length)) best = k;
      }
      return best === null ? id : map[best] + id.slice(best.length);
    }
    var stored = get("read", []) || [], last = get("last", null), i;
    function step(id) { return remap(String(id), history[i]); }
    for (i = epoch; i < history.length; i++) {
      stored = stored.map(step);
      if (last && last.id) last.id = step(last.id);
    }
    if (stored.length) set("read", stored);
    if (last && last.id) {
      if (hrefById[last.id]) { last.href = hrefById[last.id]; last.title = titleById[last.id] || ""; set("last", last); }
      else del("last");
    }
    set("idEpoch", history.length);
  })();
  var read = {};
  (get("read", []) || []).forEach(function (id) { read[id] = 1; });

  function paintRead() {
    var total = sections.length, done = 0, per = {};
    sections.forEach(function (s) {
      var c = s.id.split(".")[0];
      per[c] = per[c] || [0, 0];
      per[c][1]++;
      if (read[s.id]) { done++; per[c][0]++; }
    });
    Object.keys(linkById).forEach(function (id) { linkById[id].classList.toggle("read", !!read[id]); });
    chapters.forEach(function (ch) {
      var p = per[ch.getAttribute("data-id")] || [0, 0], el = $(".toc-count", ch);
      if (el) el.textContent = !p[0] ? "" : (p[0] === p[1] ? "\u2713" : p[0] + "/" + p[1]);
    });
    $$(".book-progress .seg").forEach(function (seg) {
      var p = per[seg.getAttribute("data-id")] || [0, 0], fill = seg.firstElementChild;
      if (fill) fill.style.width = (p[1] ? (p[0] / p[1]) * 100 : 0) + "%";
    });
    var label = $(".book-progress .label");
    if (label && total) {
      label.textContent = fmt(T.read_label, { r: done, t: total, p: Math.round((done / total) * 100) });
    }
    $$(".agenda-ch").forEach(function (ch) {
      var p = per[ch.getAttribute("data-id")] || [0, 0];
      var fill = $(".agenda-bar i", ch), txt = $(".agenda-progress", ch);
      if (fill) fill.style.width = (p[1] ? (p[0] / p[1]) * 100 : 0) + "%";
      if (txt) txt.textContent = p[0] ? fmt(T.read_short, { r: p[0], t: p[1] }) : "";
    });
    $$(".agenda-secs a").forEach(function (a) {
      var m = /#sec-([\d-]+)$/.exec(a.getAttribute("href") || "");
      if (m) a.classList.toggle("read", !!read[m[1].replace(/-/g, ".")]);
    });
  }

  /* ---------- scroll: page progress, current section, read marks ---------- */
  var heads = $$('main [id^="sec-"]');
  var headIds = heads.map(function (h) { return h.id.slice(4).replace(/-/g, "."); });
  var article = $("main .content-inner");
  var bar = doc.getElementById("progress");
  var tops = [], endY = 0, spyOffset = 96, dirty = true, ticking = false, current = null;
  /* a section counts as read once its end has been scrolled past — and only after the reader
     has scrolled or stayed a few seconds, so merely opening a page marks nothing */
  var armed = false;
  var pageName = location.pathname.split("/").pop() || "index.html";

  function measure() {
    var sy = window.pageYOffset;
    tops = heads.map(function (h) { return h.getBoundingClientRect().top + sy; });
    endY = article ? article.getBoundingClientRect().bottom + sy : 0;
    /* a heading becomes "current" once it reaches the position anchors scroll to */
    spyOffset = (parseFloat(window.getComputedStyle(root).scrollPaddingTop) || 76) + 20;
    dirty = false;
  }
  function keepVisible(a) {
    var box = toc ? $(".toc-tree", toc) : null;
    if (!box) return;
    var r = a.getBoundingClientRect(), b = box.getBoundingClientRect();
    if (r.top < b.top + 8 || r.bottom > b.bottom - 8) box.scrollTop += r.top - b.top - b.height / 3;
  }
  function setCurrent(id) {
    if (id === current) return;
    var old = current && linkById[current];
    if (old) { old.classList.remove("current"); old.removeAttribute("aria-current"); }
    current = id;
    var a = id && linkById[id];
    if (a) { a.classList.add("current"); a.setAttribute("aria-current", "location"); keepVisible(a); }
    if (id) set("last", { href: pageName + "#sec-" + id.replace(/\./g, "-"), id: id, title: titleById[id] || "" });
  }
  function onScroll() {
    ticking = false;
    if (dirty) measure();
    var sy = window.pageYOffset, vh = window.innerHeight, max = root.scrollHeight - vh;
    var pct = max > 0 ? Math.min(100, Math.max(0, (sy / max) * 100)) : 100;
    if (bar) { bar.style.width = pct + "%"; bar.setAttribute("aria-valuenow", String(Math.round(pct))); }
    if (!heads.length) return;
    var line = sy + spyOffset, idx = -1;
    for (var i = 0; i < tops.length; i++) { if (tops[i] <= line) idx = i; else break; }
    var atEnd = sy + vh >= root.scrollHeight - 8;
    if (atEnd && max > 0) idx = tops.length - 1;      /* the last section can never reach the top */
    else if (idx < 0 && heads[0].tagName === "H1") idx = 0;   /* a chapter without subsections */
    setCurrent(idx >= 0 ? headIds[idx] : null);
    if (!armed) return;
    var mark = sy + vh * 0.6, changed = false;
    for (var j = 0; j < heads.length; j++) {
      var end = j + 1 < tops.length ? tops[j + 1] : endY;
      if ((atEnd || end <= mark) && !read[headIds[j]]) { read[headIds[j]] = 1; changed = true; }
    }
    if (changed) { set("read", Object.keys(read)); paintRead(); }
  }
  function schedule() {
    if (ticking) return;
    ticking = true;
    if (window.requestAnimationFrame) window.requestAnimationFrame(onScroll); else setTimeout(onScroll, 16);
  }
  function remeasure() { dirty = true; schedule(); }
  window.addEventListener("scroll", function () { armed = true; schedule(); }, { passive: true });
  window.addEventListener("resize", remeasure);
  window.addEventListener("load", remeasure);
  if (doc.fonts && doc.fonts.ready && doc.fonts.ready.then) doc.fonts.ready.then(remeasure);
  setTimeout(function () { armed = true; schedule(); }, 5000);

  /* ---------- index page: continue where you stopped ---------- */
  var resume = doc.getElementById("resume-link"), last = get("last", null);
  if (resume && last && last.href && /^[\w.-]+\.html#sec-[\d-]+$/.test(last.href)) {
    resume.href = last.href;
    resume.textContent = fmt(T.resume, { s: (last.id + " " + (last.title || "")).trim() });
    resume.hidden = false;
  }

  /* ---------- reset reading state ---------- */
  var reset = doc.getElementById("reset-progress");
  if (reset) {
    reset.addEventListener("click", function () {
      if (!window.confirm(T.reset_confirm || "Reset reading progress?")) return;
      read = {};
      del("read");
      del("last");
      if (resume) resume.hidden = true;
      paintRead();
    });
  }

  /* ---------- content helpers: scrollable tables, copy buttons ---------- */
  $$("main table").forEach(function (t) {
    if (t.parentNode.classList && t.parentNode.classList.contains("table-wrap")) return;
    var w = doc.createElement("div");
    w.className = "table-wrap";
    t.parentNode.insertBefore(w, t);
    w.appendChild(t);
  });
  $$("main pre:not(.mermaid)").forEach(function (pre) { /* mermaid replaces its own <pre> */
    var btn = doc.createElement("button");
    btn.className = "copy-btn";
    btn.type = "button";
    btn.textContent = T.copy || "Copy";
    btn.addEventListener("click", function () {
      var src = pre.querySelector("code");
      if (!src) { /* bare <pre>: copy without the button's own label */
        src = pre.cloneNode(true);
        var b = src.querySelector(".copy-btn");
        if (b) b.parentNode.removeChild(b);
      }
      var text = (src.innerText || src.textContent || "").replace(/\u00a0/g, " ");
      var p = navigator.clipboard && navigator.clipboard.writeText
        ? navigator.clipboard.writeText(text) : Promise.reject(new Error("no clipboard"));
      p.then(function () { btn.textContent = T.copied || "Copied"; })
        .catch(function () { btn.textContent = T.copy_fail || "Press Ctrl+C"; });
      setTimeout(function () { btn.textContent = T.copy || "Copy"; }, 1800);
    });
    pre.appendChild(btn);
  });

  applyFs(fs, false);
  paintRead();
  schedule();
})();
