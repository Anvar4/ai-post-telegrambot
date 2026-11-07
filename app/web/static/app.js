/* IT Dunyosi — boshqaruv paneli (Telegram Mini App). */
"use strict";

const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) { tg.ready(); tg.expand(); }

const state = { days: 7, postsTab: "published", settings: null, charts: [] };

// ------------------------------------------------------------------ yordamchilar

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c);
  return node;
}

function toast(text) {
  const t = document.getElementById("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 2600);
}

function haptic(kind = "light") {
  try { tg && tg.HapticFeedback.impactOccurred(kind); } catch (_) { /* eski klient */ }
}

async function api(path, options = {}) {
  const headers = { "Authorization": "tma " + (tg ? tg.initData : ""), "Content-Type": "application/json" };
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) throw new Error("Panelni Telegram ichidan, bot menyusidan oching");
  if (res.status === 403) throw new Error("Bu panel faqat adminlar uchun");
  if (!res.ok) throw new Error("Server xatosi (" + res.status + ")");
  return options.raw ? res : res.json();
}

const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });

function confirmAsk(text) {
  return new Promise((resolve) => {
    if (tg && tg.showConfirm) tg.showConfirm(text, resolve);
    else resolve(window.confirm(text));
  });
}

function fmt(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("ru-RU");
}

function empty(icon, text) {
  return el("div", { class: "empty" }, el("div", { text: icon }), text);
}

function errorBox(section, err) {
  section.replaceChildren(empty("⚠️", err.message));
}

function openLink(url) {
  if (!url) return;
  if (tg && url.startsWith("https://t.me/")) tg.openTelegramLink(url);
  else if (tg) tg.openLink(url);
  else window.open(url, "_blank");
}

// ------------------------------------------------------------------ analitika

async function renderStats() {
  const section = document.getElementById("tab-stats");
  section.replaceChildren(el("div", { class: "skeleton" }), el("div", { class: "skeleton" }));
  let d;
  try { d = await api("/api/overview?days=" + state.days); } catch (e) { return errorBox(section, e); }

  updateHeader(d);

  const seg = el("div", { class: "segment" },
    [7, 30].map((n) => el("button", {
      class: state.days === n ? "on" : "", text: n + " kun",
      onclick: () => { state.days = n; haptic(); renderStats(); },
    })));

  const s = d.subscribers;
  const deltaClass = s.change >= 0 ? "up" : "down";
  const kpis = el("div", { class: "kpis" },
    kpi("Obunachilar", fmt(s.now), (s.change >= 0 ? "+" : "") + s.change + " davrda", deltaClass),
    kpi("Qoʻshildi / chiqdi", "+" + s.joins + " / −" + s.leaves, "sof: " + (s.joins - s.leaves), s.joins >= s.leaves ? "up" : "down"),
    kpi("Koʻrishlar", d.views_available ? fmt(d.totals.views) : "—", d.views_available ? d.totals.posts + " ta post" : "Telethon ulanmagan", ""),
    kpi("Reaksiya · izoh", fmt(d.totals.reactions) + " · " + fmt(d.totals.comments), d.totals.posts + " ta post", ""),
  );

  const canvas = el("canvas");
  const chartCard = el("div", { class: "card" }, el("div", { class: "chart-box" }, canvas));

  const top = el("div", { class: "card list" },
    d.top_posts.length ? d.top_posts.map(postRow) : empty("📭", "Bu davrda chiqqan post yoʻq"));

  const queue = el("div", { class: "card list" },
    el("div", { class: "row" }, el("div", { class: "grow" }, "⏳ Tasdiq kutmoqda"), el("b", { text: d.queue.pending })),
    el("div", { class: "row" }, el("div", { class: "grow" }, "🕒 Rejada"), el("b", { text: d.queue.scheduled })),
    el("div", { class: "row" }, el("div", { class: "grow" }, "💰 AI xarajati (bugun)"),
      el("b", { text: "$" + d.spent_today.toFixed(2) + " / $" + d.budget_usd.toFixed(2) })),
  );

  const invites = d.invite_links.length ? [
    el("h2", { text: "Taklif havolalari" }),
    el("div", { class: "card list" }, d.invite_links.map((l) => el("div", { class: "row" },
      el("div", { class: "grow" }, el("div", { class: "name", text: "🔗 " + l.name })),
      el("span", { class: "muted", text: "+" + l.joins + " / −" + l.leaves })))),
  ] : [];

  section.replaceChildren(seg, kpis, el("h2", { text: "Obunachilar oqimi" }), chartCard,
    el("h2", { text: "Eng yaxshi postlar" }), top, el("h2", { text: "Holat" }), queue, ...invites);
  drawFlowChart(canvas, d.series);
}

function updateHeader(d) {
  document.getElementById("status-line").textContent =
    (d.live ? "🔴 Kanal: " : "🧪 Test: ") + (d.channel || "—") + " · " + modeLabel(d.mode) + (d.paused ? " · ⏸ pauza" : "");
  const badge = document.getElementById("queue-badge");
  badge.hidden = !d.queue.pending;
  badge.textContent = d.queue.pending;
}

function kpi(label, value, delta, cls) {
  return el("div", { class: "kpi" },
    el("div", { class: "label", text: label }),
    el("div", { class: "value", text: value }),
    el("div", { class: "delta " + cls, text: delta }));
}

function drawFlowChart(canvas, series) {
  state.charts.forEach((c) => c.destroy());
  state.charts = [];
  if (!window.Chart) return;
  const css = getComputedStyle(document.documentElement);
  const hint = css.getPropertyValue("--hint").trim() || "#8a94a6";
  const accent = css.getPropertyValue("--accent").trim() || "#2f80ed";
  state.charts.push(new Chart(canvas, {
    data: {
      labels: series.days,
      datasets: [
        { type: "bar", label: "Qoʻshildi", data: series.joins, backgroundColor: "#22a06b", borderRadius: 4, yAxisID: "y" },
        { type: "bar", label: "Chiqdi", data: series.leaves.map((v) => -v), backgroundColor: "#e5484d", borderRadius: 4, yAxisID: "y" },
        { type: "line", label: "Obunachilar", data: series.subscribers, borderColor: accent, backgroundColor: accent,
          tension: .35, pointRadius: 0, spanGaps: true, yAxisID: "y1" },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: hint, boxWidth: 10 } },
        tooltip: { callbacks: { label: (c) => c.dataset.label + ": " + Math.abs(c.raw ?? 0) } },
      },
      scales: {
        x: { stacked: true, ticks: { color: hint, maxRotation: 0, autoSkip: true }, grid: { display: false } },
        y: { stacked: true, ticks: { color: hint, precision: 0, callback: (v) => Math.abs(v) },
             grid: { color: "rgba(127,127,127,.12)" } },
        y1: { position: "right", ticks: { color: hint, precision: 0 }, grid: { display: false } },
      },
    },
  }));
}

function postRow(p) {
  return el("div", { class: "row" },
    el("div", { class: "grow" },
      el("div", { class: "name", text: p.title || "(sarlavhasiz)" }),
      el("div", { class: "stats" },
        p.views != null ? el("span", { text: "👁 " + fmt(p.views) }) : null,
        el("span", { text: "❤️ " + fmt(p.reactions) }),
        el("span", { text: "💬 " + fmt(p.comments) }),
        p.when ? el("span", { text: p.when }) : null)),
    p.link ? el("button", { class: "link-btn", text: "Ochish", onclick: () => openLink(p.link) }) : null);
}

function modeLabel(mode) {
  return { auto: "⚡ avtomatik", semi_auto: "✋ tasdiq bilan", manual: "🖐 qoʻlda" }[mode] || mode;
}

// ------------------------------------------------------------------ postlar

async function renderPosts() {
  const section = document.getElementById("tab-posts");
  const seg = el("div", { class: "segment" },
    [["published", "Chiqqanlar"], ["failed", "Xatolar"]].map(([key, label]) => el("button", {
      class: state.postsTab === key ? "on" : "", text: label,
      onclick: () => { state.postsTab = key; haptic(); renderPosts(); },
    })));
  section.replaceChildren(seg, el("div", { class: "skeleton" }));
  let data;
  try { data = await api("/api/posts?tab=" + state.postsTab); } catch (e) { return errorBox(section, e); }
  const items = data.items;
  section.replaceChildren(seg, items.length
    ? el("div", {}, items.map((p) => postCard(p, false)))
    : empty("📭", state.postsTab === "published" ? "Hali chiqqan post yoʻq" : "Xato bilan tugagan post yoʻq"));
}

// ------------------------------------------------------------------ navbat

async function renderQueue() {
  const section = document.getElementById("tab-queue");
  section.replaceChildren(el("div", { class: "skeleton" }), el("div", { class: "skeleton" }));
  let data;
  try { data = await api("/api/posts?tab=queue"); } catch (e) { return errorBox(section, e); }
  const items = data.items;
  const badge = document.getElementById("queue-badge");
  const pending = items.filter((p) => p.status === "PENDING_APPROVAL").length;
  badge.hidden = !pending;
  badge.textContent = pending;
  section.replaceChildren(items.length
    ? el("div", {}, items.map((p) => postCard(p, true)))
    : empty("✅", "Navbat boʻsh. Yangi postlar slot vaqtidan 45 daqiqa oldin tayyorlanadi."));
}

function statusChip(p) {
  const cls = p.status === "PENDING_APPROVAL" ? "chip warn" : p.status === "FAILED" ? "chip bad" : "chip";
  return el("span", { class: cls, text: p.status_uz });
}

function postCard(p, withActions) {
  const text = el("div", { class: "text", text: p.text || "" });
  const more = el("button", { class: "more", text: "Toʻliq oʻqish",
    onclick: () => { text.classList.toggle("open"); more.textContent = text.classList.contains("open") ? "Yigʻish" : "Toʻliq oʻqish"; } });
  const card = el("div", { class: "card post" },
    el("div", { class: "head" },
      el("div", {}, el("span", { class: "chip", text: p.kind_uz }), " ", statusChip(p)),
      el("span", { class: "muted", text: p.when ? "🕒 " + p.when : "vaqt tanlanmagan" })),
    el("div", { class: "name", style: "margin-top:8px;font-weight:600", text: p.title || "(sarlavhasiz)" }),
    p.reason ? el("div", { class: "reason", text: "❗️ " + p.reason }) : null,
    text, (p.text || "").length > 220 ? more : null);
  if (p.image) loadImage(p.id, card);
  if (!withActions) {
    card.append(el("div", { class: "stats" },
      p.views != null ? el("span", { text: "👁 " + fmt(p.views) }) : null,
      el("span", { text: "❤️ " + fmt(p.reactions) }), el("span", { text: "💬 " + fmt(p.comments) })));
    if (p.link) card.append(el("div", { class: "actions" }, el("button", { class: "btn", text: "Kanalda ochish", onclick: () => openLink(p.link) })));
    return card;
  }
  const buttons = [
    el("button", { class: "btn primary", text: "✅ Chiqarish", onclick: (e) => act(p, "publish", e.target) }),
  ];
  if (p.status === "PENDING_APPROVAL") {
    buttons.push(el("button", { class: "btn", text: "🕒 Vaqtga", onclick: (e) => act(p, "schedule", e.target) }));
  }
  buttons.push(el("button", { class: "btn danger", text: "❌ Rad etish", onclick: (e) => act(p, "reject", e.target) }));
  card.append(el("div", { class: "actions" }, buttons));
  return card;
}

async function loadImage(id, card) {
  try {
    const res = await api("/api/posts/" + id + "/image", { raw: true });
    const url = URL.createObjectURL(await res.blob());
    const img = el("img", { src: url, alt: "" });
    card.insertBefore(img, card.children[2] || null);
  } catch (_) { /* rasm yoʻq */ }
}

async function act(p, action, button) {
  const ask = { publish: "Post hozir kanalga chiqsinmi?", reject: "Post rad etilsinmi?" }[action];
  if (ask && !(await confirmAsk(ask))) return;
  button.disabled = true;
  try {
    const r = await post("/api/posts/" + p.id, { action });
    haptic(r.ok ? "medium" : "heavy");
    toast(r.message);
    renderQueue();
  } catch (e) {
    toast(e.message);
    button.disabled = false;
  }
}

// ------------------------------------------------------------------ sozlamalar

async function renderSettings() {
  const section = document.getElementById("tab-settings");
  if (!state.settings) {
    section.replaceChildren(el("div", { class: "skeleton" }));
    try { state.settings = await api("/api/settings"); } catch (e) { return errorBox(section, e); }
  }
  const { values: v, choices: c } = state.settings;

  const modes = el("div", { class: "card" }, Object.entries(c.publish_modes).map(([key, label]) =>
    option(label, v.publish_mode === key, () => save("publish_mode", key))));
  const pause = el("div", { class: "card" },
    toggleRow("⏸ Avtomatik nashrni toʻxtatish", "Yoqilsa hech qanday post chiqmaydi", v.paused, (on) => save("paused", on)));

  const selected = v.slot_times;
  const allTimes = [...new Set([...c.times, ...selected])].sort();
  const times = el("div", { class: "card" },
    el("div", { class: "muted", style: "margin-bottom:10px",
      text: "Kuniga " + selected.length + " ta avtomatik post (eng koʻpi " + c.max_slots + "). Belgilangan vaqtda chiqadi, qoralama 45 daqiqa oldin tayyorlanadi." }),
    el("div", { class: "times" }, allTimes.map((t) => el("button", {
      class: "time" + (selected.includes(t) ? " on" : ""), text: t,
      onclick: () => {
        const next = selected.includes(t) ? selected.filter((x) => x !== t) : [...selected, t];
        if (next.length > c.max_slots) return toast("Kuniga eng koʻpi " + c.max_slots + " ta post");
        save("slot_times", next.sort());
      },
    }))));

  const cats = el("div", { class: "card" }, Object.entries(c.categories).map(([key, label]) =>
    toggleRow(label, null, v.categories.includes(key), (on) => {
      const next = on ? [...v.categories, key] : v.categories.filter((x) => x !== key);
      if (!next.length) { toast("Kamida bitta turkum qolishi kerak"); renderSettings(); return; }
      save("categories", next);
    })));

  const weekly = el("div", { class: "card list" },
    stepperRow("📊 Soʻrovnoma, haftasiga", v.polls_per_week, (n) => save("polls_per_week", n)),
    stepperRow("❓ Test, haftasiga", v.quizzes_per_week, (n) => save("quizzes_per_week", n)));

  const images = el("div", { class: "card" }, Object.entries(c.image_modes).map(([key, label]) =>
    option(label, v.image_mode === key, () => save("image_mode", key))));

  const extra = el("div", { class: "card" },
    toggleRow("📤 Ulashish tugmasi", "Har post ostida", v.share_button, (on) => save("share_button", on)));

  section.replaceChildren(
    el("h2", { text: "Nashr rejimi" }), modes, pause,
    el("h2", { text: "Kunlik postlar va vaqtlar" }), times,
    el("h2", { text: "Turkumlar" }), cats,
    el("h2", { text: "Soʻrovnoma va testlar" }), weekly,
    el("h2", { text: "Post rasmlari" }), images,
    el("h2", { text: "Qoʻshimcha" }), extra);
}

function option(label, on, onPick) {
  return el("div", { class: "opt" + (on ? " on" : ""), onclick: () => { if (!on) { haptic(); onPick(); } } },
    el("div", { class: "radio" }), el("div", { class: "grow", text: label }));
}

function toggleRow(label, hint, on, onChange) {
  return el("div", { class: "opt", onclick: () => { haptic(); onChange(!on); } },
    el("div", { class: "grow" }, el("div", { text: label }), hint ? el("div", { class: "muted", text: hint }) : null),
    el("div", { class: "switch" + (on ? " on" : "") }));
}

function stepperRow(label, value, onChange) {
  return el("div", { class: "row" },
    el("div", { class: "grow", text: label }),
    el("div", { class: "stepper" },
      el("button", { text: "−", onclick: () => value > 0 && (haptic(), onChange(value - 1)) }),
      el("b", { text: value }),
      el("button", { text: "+", onclick: () => value < 7 && (haptic(), onChange(value + 1)) })));
}

async function save(key, value) {
  try {
    const r = await post("/api/settings", { key, value });
    if (!r.ok) { toast("⚠️ " + r.error); return; }
    state.settings = { values: r.values, choices: r.choices };
    toast("✅ Saqlandi");
    if (key === "publish_mode" || key === "paused") api("/api/overview?days=7").then(updateHeader).catch(() => {});
    renderSettings();
  } catch (e) {
    toast(e.message);
  }
}

// ------------------------------------------------------------------ tablar

const renderers = { stats: renderStats, posts: renderPosts, queue: renderQueue, settings: renderSettings };

document.querySelectorAll(".tabbar button").forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + tab));
    haptic();
    renderers[tab]();
  });
});

const startTab = new URLSearchParams(location.search).get("tab");
const startButton = document.querySelector('.tabbar button[data-tab="' + startTab + '"]');
if (startButton && startTab !== "stats") {
  startButton.click();
  api("/api/overview?days=7").then(updateHeader).catch(() => {
    document.getElementById("status-line").textContent = "Ulanib boʻlmadi";
  });
} else {
  renderStats();
}
