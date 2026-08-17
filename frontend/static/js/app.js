async function api(url, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (options.body && typeof options.body !== "string") {
    opts.body = JSON.stringify(options.body);
    opts.headers["Content-Type"] = "application/json";
  }
  try {
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, error: data.error || `Request failed (${res.status})`, ...data };
    return data;
  } catch (err) {
    return { ok: false, error: "Could not connect to SellerPilot. Is the Flask server running?" };
  }
}

function formatINR(value) {
  const n = Number(value || 0);
  return new Intl.NumberFormat("en-IN", {
    style: "currency", currency: "INR", maximumFractionDigits: 0
  }).format(n);
}

function formatPct(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function toast(message, type = "success") {
  const stack = document.querySelector(".toast-stack") || (() => {
    const el = document.createElement("div");
    el.className = "toast-stack";
    document.body.appendChild(el);
    return el;
  })();
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function openModal(id) { document.getElementById(id)?.classList.add("open"); }
function closeModal(id) { document.getElementById(id)?.classList.remove("open"); }

function toggleSidebar() {
  document.getElementById("sidebar")?.classList.toggle("open");
}

function togglePresentation() {
  document.body.classList.toggle("presentation-mode");
  if (document.body.classList.contains("presentation-mode")) {
    const btn = document.createElement("button");
    btn.id = "presentationExit";
    btn.className = "btn btn-danger exit-presentation";
    btn.textContent = "Exit Presentation";
    btn.onclick = () => { document.body.classList.remove("presentation-mode"); btn.remove(); };
    document.body.appendChild(btn);
  } else {
    document.getElementById("presentationExit")?.remove();
  }
}

async function logout() {
  const res = await api("/api/logout", { method: "POST" });
  if (res.ok) window.location.href = res.redirect;
}

function initAssistant() {
  const fab = document.getElementById("assistantFab");
  const panel = document.getElementById("assistantPanel");
  const input = document.getElementById("assistantInput");
  const send = document.getElementById("assistantSendBtn");
  const body = document.getElementById("assistantBody");
  const suggestions = document.getElementById("assistantSuggestions");
  if (!fab || !panel || !input || !send || !body) return;

  const chips = ["What is my total profit?", "Which product has the highest margin?",
    "Which products are loss-making?", "How much did I spend on shipping?"];
  suggestions.innerHTML = chips.map(q => `<button class="suggestion-chip">${q}</button>`).join("");
  suggestions.querySelectorAll("button").forEach(b => b.onclick = () => {
    input.value = b.textContent; ask();
  });

  fab.onclick = () => panel.classList.toggle("open");
  send.onclick = ask;
  input.addEventListener("keydown", e => { if (e.key === "Enter") ask(); });

  body.innerHTML = `<div class="chat-bubble bot">Hi! I'm Seller Assistant. Ask me about revenue, profit, margins, products or shipping.</div>`;

  async function ask() {
    const question = input.value.trim();
    if (!question) return;
    body.insertAdjacentHTML("beforeend", `<div class="chat-bubble user"></div>`);
    body.lastElementChild.textContent = question;
    input.value = "";
    body.insertAdjacentHTML("beforeend", `<div class="chat-bubble bot">Thinking...</div>`);
    const thinking = body.lastElementChild;
    const res = await api("/api/assistant/ask", {
      method: "POST", body: JSON.stringify({ question })
    });
    thinking.textContent = res.ok ? res.answer : (res.error || "I couldn't answer that.");
    body.scrollTop = body.scrollHeight;
  }
}
document.addEventListener("DOMContentLoaded", initAssistant);
