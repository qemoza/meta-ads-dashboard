// Shared by every design in this folder. It loads /api/summary, turns it into the five rows,
// draws the spend chart, and saves your marks. A design only decides how things look.
//
// A design page calls Dash.start(render) and gets the summary each time it changes.
// Rules this file keeps for every design:
//   a number that is not connected comes back as null and is shown as "not wired"
//   a division with nothing to divide by comes back blank, never 0 and never NaN
//   every row carries the source of its number

const Dash = (() => {
  let S = null, render = null;
  const locale = undefined; // the viewer's own number format

  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v, digits) => new Intl.NumberFormat(locale, {
    style: "currency", currency: (S && S.info.currency) || "USD",
    maximumFractionDigits: digits ?? (Math.abs(v) >= 1000 ? 0 : 2), minimumFractionDigits: digits ?? (Math.abs(v) >= 1000 ? 0 : 2),
  }).format(v);
  const int = v => new Intl.NumberFormat(locale).format(v);
  const pct = (a, b) => (b ? `${((100 * a) / b).toFixed(1)}%` : "");
  const day = iso => new Date(iso + "T12:00:00Z").toLocaleDateString(locale, { day: "numeric", month: "short", timeZone: "UTC" });
  const when = iso => new Date(iso).toLocaleString(locale, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

  function calendarName(s) {
    const c = (s.info.calendars || "").split(",").filter(Boolean);
    return c.length ? c.join(" + ") : "your calendar";
  }

  // The five rows, top to bottom. state: "ok" | "off" (not wired) | "blank" (nothing to divide by)
  function rows(s) {
    const cal = calendarName(s);
    const r = [];
    r.push(s.spend === null
      ? { key: "spend", label: "Spend", state: "off", source: "Meta Marketing API",
          note: "Meta is not connected. Put your token and ad account number in .env, then run python3 dash.py pull." }
      : { key: "spend", label: "Spend", state: "ok", value: money(s.spend), source: "Meta Marketing API",
          note: `${int(s.impressions)} impressions, ${int(s.clicks)} link clicks.` });

    if (s.landed === null) r.push({ key: "landed", label: "Landed", state: "off", source: "Meta, landing page views",
      note: s.spend === null ? "Needs Meta first." : "Meta sent no landing page views. Check the Meta pixel is on your landing page." });
    else r.push({ key: "landed", label: "Landed", state: "ok", value: int(s.landed), source: "Meta, landing page views",
      note: s.landed ? `${money(s.spend / s.landed)} per landed visit. ${pct(s.landed, s.clicks)} of link clicks.` : "No landing page views in this window." });

    if (!s.calendar_wired) r.push({ key: "booked", label: "Booked", state: "off", source: "your calendar",
      note: "No calendar connected. Add CAL_API_KEY or CALENDLY_TOKEN to .env, or import a CSV of your bookings." });
    else if (s.booked === null) r.push({ key: "booked", label: "Booked", state: "off", source: `${cal} + ad tags + your marks`,
      note: `${s.booked_unmarked} of ${s.booked_total} bookings carry no ad tag. Mark them in the list below.` });
    else r.push({ key: "booked", label: "Booked", state: "ok", value: int(s.booked), source: `${cal} + ad tags + your marks`,
      note: `${s.booked} of ${s.booked_total} calls booked came from the ads.${s.landed ? ` ${pct(s.booked, s.landed)} of landed.` : ""}` });

    if (s.booked === null) r.push({ key: "showed", label: "Showed", state: "off", source: "your marks",
      note: "Needs booked first." });
    else if (s.showed === null) r.push({ key: "showed", label: "Showed", state: "off", source: "your marks",
      note: `${s.showed_unmarked} past ad ${s.showed_unmarked === 1 ? "call" : "calls"} still to mark below. A calendar cannot tell if a call happened.` });
    else r.push({ key: "showed", label: "Showed", state: "ok", value: int(s.showed), source: "your marks",
      note: s.ad_calls_held
        ? `${s.showed} of ${s.ad_calls_held} past ad calls happened.${s.ad_calls_upcoming ? ` ${s.ad_calls_upcoming} still to come.` : ""}`
        : "No ad calls have happened yet." });

    if (s.cpb_state === "not_wired") r.push({ key: "cpb", label: "Cost per booked call", state: "off", source: "Meta spend ÷ booked",
      note: "Needs spend and booked." });
    else if (s.cpb_state === "blank") r.push({ key: "cpb", label: "Cost per booked call", state: "blank", value: "", source: "Meta spend ÷ booked",
      note: "No booked calls from the ads, so there is nothing to divide by." });
    else r.push({ key: "cpb", label: "Cost per booked call", state: "ok", value: money(s.cpb), source: "Meta spend ÷ booked",
      note: `${money(s.spend)} ÷ ${s.booked} booked.` });
    return r;
  }

  function header(s) {
    const i = s.info;
    const pulled = i.pulled_at ? new Date(i.pulled_at).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" }) : "never";
    return { account: i.account_name || "Meta ads", window: `${day(i.since)} to ${day(i.until)}`, currency: i.currency,
             pulled, sample: s.sample, tagged: i.active_ads === "" || i.active_ads === undefined ? null
               : `${i.active_ads_tagged} of ${i.active_ads} live ads carry utm tags` };
  }

  // Yes / No buttons for one booking. The design styles .q, .q button, .on.y and .on.n
  function markButtons(b) {
    const btn = (field, val, cur, txt) =>
      `<button type="button" class="${cur === val ? `on ${val ? "y" : "n"}` : ""}" aria-pressed="${cur === val}"
        data-uid="${esc(b.uid)}" data-field="${field}" data-val="${cur === val ? "null" : val}">${txt}</button>`;
    let h = `<div class="q"><span>From ads?</span>${btn("from_ads", 1, b.from_ads, "Yes")}${btn("from_ads", 0, b.from_ads, "No")}</div>`;
    if (b.from_ads === 1) h += b.held
      ? `<div class="q"><span>Showed?</span>${btn("showed", 1, b.showed, "Yes")}${btn("showed", 0, b.showed, "No")}</div>`
      : `<div class="q"><span class="soon">Call still to come</span></div>`;
    return h;
  }

  function bookingLine(b) {
    const tag = b.tag ? `tag ${esc(b.tag)}${b.campaign ? ` / ${esc(b.campaign)}` : ""}` : "no ad tag";
    const by = b.from_ads_by === "tag" ? ", read from the tag" : b.from_ads_by === "rule" ? ", untagged so not ads" : "";
    const needs = b.from_ads === null || (b.from_ads === 1 && b.held && b.showed === null);
    return { title: `${esc(b.who || "Someone")} · ${when(b.start)}`,
             meta: `booked ${day(b.created)} · ${esc(b.source)} · ${tag}${by}`, needs };
  }

  // The bookings list. Folded to the most recent few, but a call that still needs a mark is always shown.
  let showAll = false;
  const FOLDED = 6;
  function bookingsList(s, one, emptyText) {
    if (!s.books.length) return emptyText;
    const needs = b => b.from_ads === null || (b.from_ads === 1 && b.held && b.showed === null);
    let room = FOLDED - s.books.filter(needs).length;
    const shown = showAll ? s.books : s.books.filter(b => needs(b) || room-- > 0);
    const hidden = s.books.length - shown.length;
    return shown.map(one).join("") + (hidden || showAll && s.books.length > FOLDED
      ? `<button type="button" class="more" data-more>${showAll ? "Show fewer" : `Show all ${s.books.length} calls`}</button>` : "");
  }

  // By campaign. Each cell carries its column name in data-label, so a design can stack rows on a phone.
  function campaignTable(s, otherLabel) {
    if (!s.campaigns.length) return `<div class="chart-empty" style="height:70px">not wired</div>`;
    const nw = `<span class="nw">not wired</span>`;
    const td = (label, v) => `<td data-label="${label}">${v}</td>`;
    return `<table class="ctable"><thead><tr><th>Campaign</th><th>Spend</th><th>Landed</th><th>Booked</th><th>Per booked</th></tr></thead><tbody>` +
      s.campaigns.map(c => `<tr><td title="${esc(c.name)}">${esc(c.name)}</td>${td("Spend", money(c.spend))}` +
        td("Landed", c.landed === null ? nw : int(c.landed)) + td("Booked", c.booked === null ? nw : c.booked) +
        td("Per booked", c.booked === null ? nw : c.cpb === null ? "" : money(c.cpb)) + `</tr>`).join("") +
      (s.unmatched_booked ? `<tr class="other"><td>${otherLabel || "Booked from ads, no matching campaign tag"}</td><td></td><td></td>${td("Booked", s.unmatched_booked)}<td></td></tr>` : "") +
      `</tbody></table>`;
  }

  // Spend per day as bars. Measures its box, so it stays sharp at any width.
  function drawBars(el, s) {
    if (!el) return;
    const d = s.days || [];
    const max = Math.max(0, ...d.map(x => x.spend));
    if (s.spend === null || !max) {
      el.innerHTML = `<div class="chart-empty">${s.spend === null ? "not wired" : "No spend in this window."}</div>`;
      return;
    }
    const W = Math.max(240, el.clientWidth), H = el.clientHeight || 150, top = 8, base = H - 1;
    const step = W / d.length, gap = step > 8 ? 2 : 1, bw = Math.max(1, step - gap);
    const bars = d.map((x, i) => {
      const h = Math.max(x.spend ? 2 : 0, ((base - top) * x.spend) / max);
      const X = i * step + gap / 2, Y = base - h, r = Math.min(4, bw / 2, h);
      const path = h ? `M${X},${base}V${Y + r}Q${X},${Y} ${X + r},${Y}H${X + bw - r}Q${X + bw},${Y} ${X + bw},${Y + r}V${base}Z` : "";
      const tip = `${day(x.day)}: ${money(x.spend)} spent${x.landed !== null ? `, ${int(x.landed)} landed` : ""}${x.booked !== null ? `, ${x.booked} booked` : ""}`;
      return `<g class="bar" data-tip="${esc(tip)}"><rect x="${i * step}" y="0" width="${step}" height="${H}" fill="transparent"/>${path ? `<path d="${path}"/>` : ""}</g>`;
    }).join("");
    el.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Spend per day, highest ${esc(money(max))}">
      <line class="grid" x1="0" x2="${W}" y1="${top}" y2="${top}"/><line class="axis" x1="0" x2="${W}" y1="${base}" y2="${base}"/>${bars}</svg>`;
    el.dataset.max = money(max);
  }

  // One small tooltip for every [data-tip] on the page. Mouse and touch.
  let tipEl = null;
  function tip(e) {
    const t = e.target.closest && e.target.closest("[data-tip]");
    if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "tip"; tipEl.setAttribute("role", "status"); document.body.appendChild(tipEl); }
    document.querySelectorAll(".bar.hot").forEach(b => b.classList.remove("hot"));
    if (!t) { tipEl.style.opacity = 0; return; }
    t.classList.add("hot");
    tipEl.textContent = t.dataset.tip;
    tipEl.style.opacity = 1;
    const x = Math.min(window.innerWidth - tipEl.offsetWidth - 8, Math.max(8, e.clientX - tipEl.offsetWidth / 2));
    tipEl.style.left = `${x}px`;
    tipEl.style.top = `${Math.max(8, e.clientY - tipEl.offsetHeight - 14)}px`;
  }

  async function load() {
    try {
      const r = await fetch("/api/summary", { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const s = await r.json();
      if (s.empty) return render(null, "No data yet. Run python3 dash.py pull, or python3 dash.py --sample to see fake numbers.");
      S = s; render(S, null);
    } catch (err) {
      render(S, "Cannot reach dash.py. Start it again with python3 dash.py");
    }
  }

  async function mark(button) {
    const all = document.querySelectorAll("button[data-uid]");
    all.forEach(x => (x.disabled = true));
    const was = button.textContent;
    button.textContent = "Saving…"; // shows the press landed, before the server answers
    const status = document.getElementById("mark-status");
    try {
      const r = await fetch("/api/mark", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uid: button.dataset.uid, field: button.dataset.field, value: JSON.parse(button.dataset.val) }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
      S = await r.json();
      if (status) status.textContent = "";
      render(S, null);
    } catch (err) {
      button.textContent = was;
      all.forEach(x => (x.disabled = false));
      if (status) status.textContent = `That mark did not save (${err.message}). Is dash.py still running?`;
    }
  }

  function start(fn) {
    render = fn;
    document.addEventListener("click", e => {
      const b = e.target.closest("button[data-uid]");
      if (b) return mark(b);
      if (e.target.closest("[data-more]")) { showAll = !showAll; return S && render(S, null); }
      tip(e);
    });
    document.addEventListener("mousemove", tip);
    let t = null;
    window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => S && render(S, null), 120); });
    load();
    setInterval(load, 5 * 60 * 1000); // picks up the hourly pull without a reload
  }

  function designLinks(current) {
    return ["clean", "ledger", "night"].map(n => n === current ? `<b>${n}</b>` : `<a href="/d/${n}">${n}</a>`).join(" · ");
  }

  return { start, rows, header, markButtons, bookingLine, bookingsList, campaignTable, drawBars, designLinks, money, int, pct, day, when, esc };
})();
