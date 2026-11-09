// Myric website: dependency-free interactions. Everything works without it; it only adds Myric's own motion:
// "myriad -> one" (a swarm of tiny hexagons builds the logo), a 3D orbit of the bot's icons, breathing hexagons,
// words that gather into the headline, a honeycomb that glows under the finger, hexagon reveals and page wipes.
(() => {
  const d = document, root = d.documentElement;
  root.classList.add("js");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const $ = (s, el = d) => el.querySelector(s), $$ = (s, el = d) => [...el.querySelectorAll(s)];
  const rnd = (a, b) => a + Math.random() * (b - a);

  // ---------- toast ----------
  const toast = $(".toast"); let toastT;
  const say = (html) => { if (!toast) return; toast.innerHTML = html; toast.classList.add("on"); clearTimeout(toastT); toastT = setTimeout(() => toast.classList.remove("on"), 1900); };

  // ---------- phone menu ----------
  const burger = $(".burger"), sheet = $("#sheet");
  const setMenu = (open) => {
    if (!burger) return;
    burger.setAttribute("aria-expanded", open); sheet.hidden = false;
    requestAnimationFrame(() => sheet.classList.toggle("open", open));
    d.body.classList.toggle("noscroll", open);
    if (!open) setTimeout(() => { if (!sheet.classList.contains("open")) sheet.hidden = true; }, 320);
  };
  burger && burger.addEventListener("click", () => setMenu(burger.getAttribute("aria-expanded") !== "true"));
  sheet && sheet.addEventListener("click", (e) => { if (e.target.closest("a")) setMenu(false); });
  addEventListener("keydown", (e) => { if (e.key === "Escape") setMenu(false); });

  // ---------- documents: contents folded on phones ----------
  if (innerWidth < 980) $$(".toc details").forEach((x) => (x.open = false));

  // ---------- header, progress line, back to top ----------
  const nav = $(".nav"), top = $(".totop"), bar = $(".progress");
  const onScroll = () => {
    const y = scrollY, h = root.scrollHeight - innerHeight;
    nav && nav.classList.toggle("scrolled", y > 8);
    top && top.classList.toggle("on", y > 700);
    bar && (bar.style.transform = `scaleX(${h > 0 ? Math.min(1, y / h) : 0})`);
  };
  addEventListener("scroll", onScroll, { passive: true }); onScroll();

  // ---------- honeycomb glow that follows the finger / mouse ----------
  let gx = innerWidth * 0.7, gy = innerHeight * 0.3, gq = false;
  const glow = (e) => { gx = e.clientX; gy = e.clientY; if (!gq) { gq = true; requestAnimationFrame(() => { root.style.setProperty("--px", gx + "px"); root.style.setProperty("--py", gy + "px"); root.classList.add("glowing"); gq = false; }); } };
  if (!reduce) addEventListener("pointermove", glow, { passive: true }), addEventListener("pointerdown", glow, { passive: true });

  // ---------- words gather into the headline ----------
  const h1 = $("h1.split");
  if (h1 && !reduce) {
    const walk = (node) => {
      [...node.childNodes].forEach((n) => {
        if (n.nodeType === 3) {
          const frag = d.createDocumentFragment();
          n.textContent.split(/(\s+)/).forEach((w) => {
            if (!w) return;
            if (/^\s+$/.test(w)) { frag.appendChild(d.createTextNode(w)); return; }
            const s = d.createElement("span"); s.className = "w"; s.textContent = w; frag.appendChild(s);
          });
          n.replaceWith(frag);
        } else if (n.nodeType === 1 && n.classList.contains("grad")) n.classList.add("w");
        else if (n.nodeType === 1 && n.tagName !== "BR") walk(n);
      });
    };
    walk(h1);
    $$(".w", h1).forEach((w, i) => {
      w.style.setProperty("--tx", rnd(-60, 60).toFixed(0) + "px"); w.style.setProperty("--ty", rnd(-50, 70).toFixed(0) + "px");
      w.style.setProperty("--rz", rnd(-18, 18).toFixed(0) + "deg"); w.style.setProperty("--wd", (180 + i * 110) + "ms");
    });
    requestAnimationFrame(() => requestAnimationFrame(() => h1.classList.add("go")));
  } else if (h1) h1.classList.add("go");

  // ---------- reveal on scroll (hexagon growth), count-up ----------
  const count = (el) => {
    const end = +el.dataset.count, suf = el.dataset.suffix || "";
    if (reduce) { el.textContent = end + suf; return; }
    const t0 = performance.now(), dur = 1600;
    const step = (t) => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 4); el.textContent = Math.round(end * e) + suf; if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  };
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((list) => list.forEach((en) => {
      if (!en.isIntersecting) return;
      en.target.classList.add("in"); io.unobserve(en.target);
      setTimeout(() => en.target.classList.add("done"), 1700);         // drop the reveal clip so shadows and hovers are free
      $$("[data-count]", en.target).forEach(count);
    }), { rootMargin: "0px 0px -10% 0px", threshold: 0 });     // 0: a card clipped to its icon still counts
    $$(".rv").forEach((el) => io.observe(el));
  } else $$(".rv").forEach((el) => el.classList.add("in"));

  // ---------- cards: spotlight + gentle 3D tilt (mouse), spotlight (touch) ----------
  $$(".card, .cat, .band").forEach((c) => {
    c.addEventListener("pointermove", (e) => {
      const r = c.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      c.style.setProperty("--mx", x + "px"); c.style.setProperty("--my", y + "px");
      if (fine && c.classList.contains("card") && !reduce) c.style.setProperty("--tilt", `rotateX(${((y / r.height) - 0.5) * -5}deg) rotateY(${((x / r.width) - 0.5) * 6}deg)`);
    });
    c.addEventListener("pointerleave", () => c.style.removeProperty("--tilt"));
  });

  // ---------- magnetic buttons (mouse only) ----------
  if (fine && !reduce) $$(".btn.big, .nav .btn").forEach((b) => {
    b.addEventListener("pointermove", (e) => { const r = b.getBoundingClientRect(); b.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * 0.18}px, ${(e.clientY - r.top - r.height / 2) * 0.28}px)`; });
    b.addEventListener("pointerleave", () => (b.style.transform = ""));
  });

  // ---------- hero: myriad -> one (a swarm of hexagons builds the logo) + 3D orbit ----------
  const hl = $(".hlogo"), cv = hl && $(".swarm", hl);
  if (hl && cv && cv.getContext && !reduce) {
    const ctx = cv.getContext("2d"), mark = $(".mark", hl);
    const planets = $$(".pl", hl); hl.classList.add("orbit3d");
    let W = 0, H = 0, DPR = 1, R = 100, pts = [], t0 = performance.now(), visible = true, ptr = null, born = 0;
    const HEX = new Path2D(); for (let i = 0; i < 6; i++) { const a = Math.PI / 3 * i - Math.PI / 2; i ? HEX.lineTo(Math.cos(a), Math.sin(a)) : HEX.moveTo(Math.cos(a), Math.sin(a)); } HEX.closePath();
    const size = () => {
      const r = hl.getBoundingClientRect(); DPR = Math.min(devicePixelRatio || 1, 2);
      W = r.width; H = r.height; cv.width = W * DPR; cv.height = H * DPR; R = Math.min(W, H) * 0.31;
    };
    size(); addEventListener("resize", size);
    const pick = (p) => { const a = Math.atan2(p[1], p[0]) + rnd(-1, 1), dist = rnd(1.6, 3.2); return [Math.cos(a) * dist, Math.sin(a) * dist]; };
    fetch("/assets/logo-points.json").then((r) => r.json()).then((raw) => {
      const thin = innerWidth < 760 ? 2 : 1;
      pts = raw.filter((_, i) => i % thin === 0).map((p, i) => {
        const [sx, sy] = pick(p);
        return { tx: p[0], ty: p[1], c: `rgb(${p[2]},${p[3]},${p[4]})`, dx: p[5], dy: p[6], x: sx, y: sy, vx: 0, vy: 0,
                 delay: 120 + (Math.hypot(p[0], p[1]) * 520) + rnd(0, 520), sc: rnd(0.75, 1.15), ph: rnd(0, 6.28), fx: rnd(-1, 1), fy: rnd(-1, 1) };
      });
      born = performance.now(); hl.classList.add("live");
    }).catch(() => {});
    cv.addEventListener("pointermove", (e) => { const r = cv.getBoundingClientRect(); ptr = [(e.clientX - r.left - W / 2) / R, (e.clientY - r.top - H / 2) / R]; });
    cv.addEventListener("pointerleave", () => (ptr = null));
    cv.addEventListener("pointerdown", (e) => {                // a tap scatters the swarm for a moment
      const r = cv.getBoundingClientRect(), px = (e.clientX - r.left - W / 2) / R, py = (e.clientY - r.top - H / 2) / R;
      pts.forEach((p) => { const ddx = p.x - px, ddy = p.y - py, dd = Math.hypot(ddx, ddy) + 0.05; p.vx += (ddx / dd) * 0.09 / dd; p.vy += (ddy / dd) * 0.09 / dd; });
    });
    if ("IntersectionObserver" in window) new IntersectionObserver((l) => (visible = l[0].isIntersecting)).observe(hl);
    const orbit = (t) => {
      const n = planets.length, Rx = W * 0.46, Ry = W * 0.15, tilt = -0.26;
      planets.forEach((pl, i) => {
        const a = t * 0.00022 + (i / n) * Math.PI * 2, cx = Math.cos(a) * Rx, cy = Math.sin(a) * Ry, z = Math.sin(a);
        const x = cx * Math.cos(tilt) - cy * Math.sin(tilt), y = cx * Math.sin(tilt) + cy * Math.cos(tilt);
        const s = 0.72 + (z + 1) * 0.2;
        pl.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) scale(${s.toFixed(3)})`;
        pl.style.opacity = (0.45 + (z + 1) * 0.275).toFixed(2); pl.style.zIndex = z > 0 ? 4 : 1;
      });
    };
    const frame = (now) => {
      requestAnimationFrame(frame);
      if (!visible || d.hidden) return;
      const t = now - t0; orbit(t);
      if (!pts.length) return;
      const life = now - born, breath = (Math.sin(t / 1100) + 1) / 2, spread = 0.02 + breath * 0.075;
      const sc = Math.min(1, scrollY / (innerHeight * 0.9)), scatter = sc * sc * 1.4;
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0); ctx.clearRect(0, 0, W, H);
      if (mark) mark.style.opacity = Math.max(0, Math.min(0.42, (life - 2300) / 1800 * 0.42) - scatter);
      const ps = Math.max(1.8, R * 0.0225);
      for (const p of pts) {
        let gx = p.tx + p.dx * spread + p.fx * scatter, gy = p.ty + p.dy * spread + p.fy * scatter;
        gx += Math.sin(t / 900 + p.ph) * 0.004; gy += Math.cos(t / 1000 + p.ph) * 0.004;
        if (life > p.delay) { p.vx += (gx - p.x) * 0.045; p.vy += (gy - p.y) * 0.045; }
        else { p.vx += Math.sin(t / 400 + p.ph) * 0.0006; p.vy += Math.cos(t / 450 + p.ph) * 0.0006; }
        if (ptr) { const ddx = p.x - ptr[0], ddy = p.y - ptr[1], dd = ddx * ddx + ddy * ddy; if (dd < 0.06) { const f = (0.06 - dd) * 0.5; p.vx += ddx * f; p.vy += ddy * f; } }
        p.vx *= 0.82; p.vy *= 0.82; p.x += p.vx; p.y += p.vy;
        const k = ps * p.sc * (life > p.delay ? 1 : 0.6);
        ctx.setTransform(DPR * k, 0, 0, DPR * k, (W / 2 + p.x * R) * DPR, (H / 2 + p.y * R) * DPR);
        ctx.fillStyle = p.c; ctx.globalAlpha = life > p.delay ? 0.95 : 0.35; ctx.fill(HEX);
      }
      ctx.globalAlpha = 1;
    };
    requestAnimationFrame(frame);
  }

  // ---------- showcase: tabs, "Myric is typing", rotate by themselves until someone taps ----------
  const tabs = $$(".tabs [data-tab]");
  if (tabs.length) {
    let i = 0, auto = !reduce, timer, typeT;
    const show = (k) => {
      tabs.forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === k));
      $$(".panel").forEach((p) => p.classList.toggle("on", p.dataset.panel === k));
      const panel = $(`.panel[data-panel="${k}"]`); if (!panel) return;
      clearTimeout(typeT); panel.classList.add("wait");
      typeT = setTimeout(() => {
        panel.classList.remove("wait");
        const img = $(".shot", panel); if (img && img.src.includes(".gif")) img.src = img.src.split("?")[0] + "?t=" + Date.now();   // GIF from the start
      }, reduce ? 0 : 1050);
    };
    const next = () => { i = (i + 1) % tabs.length; show(tabs[i].dataset.tab); };
    const arm = () => { clearInterval(timer); if (auto) { $(".tabs").classList.add("auto"); timer = setInterval(next, 7000); } };
    tabs.forEach((b, n) => b.addEventListener("click", () => { auto = false; $(".tabs").classList.remove("auto"); clearInterval(timer); i = n; show(b.dataset.tab); }));
    const box = $(".show"); let first = true;
    if ("IntersectionObserver" in window && box) new IntersectionObserver((l) => l.forEach((en) => {
      if (en.isIntersecting) { if (first) { first = false; show(tabs[0].dataset.tab); } arm(); } else clearInterval(timer);
    }), { threshold: 0.3 }).observe(box);
  }

  // ---------- FAQ: smooth open and close ----------
  $$(".faq details").forEach((det) => {
    const sum = $("summary", det), body = $(".ans", det);
    sum.addEventListener("click", (e) => {
      if (reduce || !body.animate) return;
      e.preventDefault();
      if (det.open) {
        const h = body.offsetHeight;
        body.animate([{ height: h + "px", opacity: 1 }, { height: "0px", opacity: 0 }], { duration: 260, easing: "ease-in" }).onfinish = () => (det.open = false);
      } else {
        det.open = true; const h = body.offsetHeight;
        body.animate([{ height: "0px", opacity: 0 }, { height: h + "px", opacity: 1 }], { duration: 340, easing: "cubic-bezier(.2,.75,.2,1)" });
      }
    });
  });

  // ---------- commands: live search, counter, tap to copy (with a little hexagon burst) ----------
  const q = $("#q");
  if (q) {
    const cnt = $(".count"), none = $("#none"), fmt = cnt.dataset.fmt;
    const run = () => {
      const s = q.value.trim().toLowerCase(); let total = 0;
      $$(".cat").forEach((c) => {
        let n = 0;
        $$("li", c).forEach((li) => { const m = !s || li.textContent.toLowerCase().includes(s); li.hidden = !m; if (m) n++; });
        $$(".note", c).forEach((p) => (p.hidden = !!s));
        c.hidden = n === 0; total += n;
      });
      none.hidden = total > 0; cnt.textContent = fmt.replace("{n}", total);
      $$(".chips a").forEach((a) => { const t = d.getElementById(a.getAttribute("href").slice(1)); a.classList.toggle("off", !!(t && t.hidden)); });
    };
    q.addEventListener("input", run);
    addEventListener("keydown", (e) => { if (e.key === "/" && d.activeElement !== q) { e.preventDefault(); q.focus(); } });
    const copied = $(".cats").dataset.copied;
    const copy = async (text) => {
      try { await navigator.clipboard.writeText(text); }
      catch (_) { const t = d.createElement("textarea"); t.value = text; d.body.appendChild(t); t.select(); try { d.execCommand("copy"); } catch (__) {} t.remove(); }
    };
    const burst = (el) => {
      if (reduce) return;
      const r = el.getBoundingClientRect();
      for (let k = 0; k < 9; k++) {
        const s = d.createElement("i"); s.className = "spark"; const a = (k / 9) * Math.PI * 2 + rnd(-0.3, 0.3), dist = rnd(26, 52);
        s.style.left = r.left + r.width / 2 + "px"; s.style.top = r.top + r.height / 2 + "px";
        s.style.setProperty("--sx", Math.cos(a) * dist + "px"); s.style.setProperty("--sy", Math.sin(a) * dist + "px");
        s.style.background = ["#7663f6", "#26c6a6", "#f4b740"][k % 3]; d.body.appendChild(s); setTimeout(() => s.remove(), 700);
      }
    };
    $$(".cc").forEach((b) => b.addEventListener("click", () => {
      copy(b.dataset.copy); b.classList.add("hit"); setTimeout(() => b.classList.remove("hit"), 700); burst(b);
      say(`<img src="/assets/i/v_yes.png" alt="" width="20" height="20"> ${copied}: <code>${b.dataset.copy}</code>`);
    }));
  }
})();
