/* One workspace, a selectable list and a persistent detail inspector. */
"use strict";
const {
  sales,
  stages,
  fields,
  esc,
  number,
  safeURL,
  researchStatus,
  dateParts,
  filterRows,
} = PanelData;
const $ = (id) => document.getElementById(id);
const icon = (name, extra = "") =>
  `<img class="icon ${extra}" src="/assets/${name}.svg" alt="">`;
const filterIds = [
  "search",
  "sales",
  "source",
  "kind",
  "stage",
  "freshness",
  "research",
];
const state = {
  items: [],
  status: {},
  selected: null,
  view: "opportunities",
  limit: 60,
  sort: { key: "priority", direction: -1 },
  loaded: false,
};
const drafts = new Map(),
  disclosures = new Map(),
  pending = new Set();
const narrow = window.matchMedia("(max-width:1279px)");
let saved;
try {
  saved = new Set(
    JSON.parse(localStorage.getItem("ihalesystem:followed") || "[]"),
  );
} catch {
  saved = new Set();
}
let lastList = "",
  lastDetail = "",
  renderedDetailId = null,
  lastSettings = "",
  refreshing = null,
  connectionError = false;
let returnFocus = null;
const tone = (key) =>
  ({
    teklif: "blue",
    yuklenici: "amber",
    proje: "green",
    takip: "purple",
    kontrol: "neutral",
    arsiv: "arsiv",
  })[key] || "neutral";
const badge = (text, style = "neutral") =>
  `<span class="badge ${esc(style)}">${esc(text)}</span>`;
const filters = () =>
  Object.fromEntries(filterIds.map((id) => [id, $(id).value]));
const sourceName = (row) =>
  String(row.source || "Kaynak").startsWith("EKAP")
    ? "EKAP"
    : row.source || "Kaynak";
function dateText(value) {
  const date = new Date(value);
  return value && Number.isFinite(date.getTime())
    ? date.toLocaleString("tr-TR")
    : "Henüz yok";
}
function sourceLink(url, label, symbol = "external-link") {
  const href =
    safeURL(url) || (String(url).startsWith("/api/bulletins/") ? url : null);
  return href
    ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${icon(symbol)}${esc(label)}</a>`
    : "";
}
function notice(message, error = false) {
  $("notice").hidden = false;
  $("notice").classList.toggle("error", error);
  $("notice").innerHTML =
    `${esc(message)}${error ? '<button class="text-button" data-retry>Tekrar dene</button>' : ""}<button class="text-button" data-dismiss>Kapat</button>`;
}
function setDrawer(open, focus = true) {
  const visible = Boolean(
    open && narrow.matches && state.selected && state.view !== "settings",
  );
  document.body.classList.toggle("detail-open", visible);
  $("detail-backdrop").hidden = !visible;
  document
    .querySelectorAll(".sidebar,.page-header,.opportunity-list,.settings-view")
    .forEach((el) => {
      el.inert = visible;
    });
  if (visible) {
    $("detail").setAttribute("role", "dialog");
    $("detail").setAttribute("aria-modal", "true");
    if (focus)
      $("detail")
        .querySelector(".close-detail")
        ?.focus({ preventScroll: true });
  } else {
    $("detail").removeAttribute("role");
    $("detail").removeAttribute("aria-modal");
    if (focus) {
      const target = returnFocus?.isConnected
        ? returnFocus
        : [...$("list").querySelectorAll("[data-select]")].find(
            (button) => button.dataset.select === state.selected,
          );
      target?.focus({ preventScroll: true });
    }
  }
}
function rememberDetail() {
  if (!renderedDetailId) return;
  const values = {};
  $("detail")
    .querySelectorAll("[data-research-input]")
    .forEach((input) => {
      values[input.dataset.researchInput] = input.value;
    });
  drafts.set(renderedDetailId, values);
  disclosures.set(
    renderedDetailId,
    new Set(
      [...$("detail").querySelectorAll("details[open]")].map(
        (el) => el.dataset.disclosure,
      ),
    ),
  );
}
function contactsMarkup(result) {
  return `<dl class="contact-fields">${[
    ["phone", "Telefon"],
    ["email", "E-posta"],
    ["website", "Web sitesi"],
    ["address", "Adres"],
  ]
    .map(([field, label]) => {
      const value = result.winner?.[field];
      const verification =
        result.field_verification?.[field]?.status || "missing";
      const website = field === "website" && safeURL(value);
      const text = website
        ? `<a href="${esc(website)}" target="_blank" rel="noopener noreferrer">Firma sitesi</a>`
        : value
          ? esc(value)
          : '<span class="missing-value">Kaynakta tamamlanmadı</span>';
      return `<div class="contact-field"><dt>${label}</dt><dd>${text}<span class="badge ${esc(verification)}">${esc(fields[verification] || "Eksik")}</span></dd></div>`;
    })
    .join("")}</dl>`;
}
function enrichmentMarkup(row) {
  const e = row.enrichment;
  if (!e?.eligible)
    return `<section class="enrichment"><div class="enrichment-heading"><h3>Firma araştırması</h3></div><p class="research-note">${esc(e?.reason || "Bu kayıt için firma araştırması henüz kullanılabilir değil.")}</p></section>`;
  const r = e.result,
    status = researchStatus(row),
    values = drafts.get(row.id) || {};
  const busy = pending.has(row.id) || ["queued", "running"].includes(e.state);
  const sources = {
    official_award: "Resmî sonuç",
    company_website: "Firma sitesi",
    public_registry: "Resmî sicil",
    news: "Diğer açık kaynak",
  };
  return `<section class="enrichment"><div class="enrichment-heading"><h3>Firma araştırması</h3><button class="button outline" data-enrich ${busy ? "disabled" : ""}>${icon("search")}${busy ? "Bekleniyor…" : "Firmayı araştır"}</button></div>
    ${r?.winner ? `<p class="company-name">${esc(r.winner.company_name || "Firma adı doğrulanamadı")}</p><p class="company-role">${esc(row.opportunity?.target_role || "İşi alan yüklenici / proje satınalma birimi")}</p>${contactsMarkup(r)}` : `<p class="company-name">${esc(row.opportunity?.target_name || "Firma adı henüz belirlenemedi")}</p><p class="company-role">${esc(row.opportunity?.target_role || "")}</p><p class="research-note" style="margin-top:14px">Firma araştırması, kaynaklardaki yüklenici ve kurumsal iletişim bilgilerini kontrol eder.</p>`}
    <p class="research-summary">${badge(status.label, status.tone)}${r ? ` Kanıt skoru: ${Math.round(r.confidence * 100)}/100 · Bilgi tamlığı: %${Math.round(r.completeness * 100)}` : ""}</p>
    ${e.local_only && r ? '<p class="research-note">Resmî PDF kanıtı işlendi. Ek firma bilgileri için araştırmayı başlatabilirsiniz.</p>' : ""}
    ${e.error ? `<p class="detail-error">${esc(e.error)}</p>` : ""}
    <details class="detail-disclosure" data-disclosure="links"><summary>Bağlantı ekle / araştırmayı yenile</summary><form id="research-form" class="research-form"><label>Firma sitesi (isteğe bağlı)<input type="url" data-research-input="company" aria-label="Firma sitesi" placeholder="https://firma.com.tr" value="${esc(values.company || "")}"></label><label>Sonuç ilanı bağlantısı (isteğe bağlı)<input type="url" data-research-input="award" aria-label="Sonuç ilanı bağlantısı" placeholder="https://…" value="${esc(values.award || "")}"></label><button class="button outline" type="submit" ${busy ? "disabled" : ""}>${r ? "Araştırmayı yenile" : "Araştırmayı başlat"}</button></form></details>
    ${r ? `<details class="detail-disclosure" data-disclosure="evidence"><summary>Araştırma kaynakları ve kontrol notları</summary>${r.is_demo ? "<p>SENTETİK DEMO — gerçek firma bilgisi değildir.</p>" : ""}<div class="source-links">${(r.sources || []).map((s) => sourceLink(s.url, sources[s.source_type] || "Kaynak")).join(" ")}</div>${(r.issues || []).map((issue) => `<p>${esc(issue.message)}</p>`).join("")}<p>Kanıt skoru istatistiksel doğruluk veya satış olasılığı değildir. Tek kaynak, bağımsız ikinci yayıncıyla doğrulanmamış bilgidir. Çelişkili değerler boş bırakılır. Ayrıntılı kanıtlar JSON çıktısındadır.</p></details>` : ""}</section>`;
}
function renderDetail(row) {
  const signature = JSON.stringify([
    row,
    row && saved.has(row.id),
    row && pending.has(row.id),
  ]);
  if (signature === lastDetail) return;
  const active = document.activeElement;
  const focusedInput =
    $("detail").contains(active) && active.dataset?.researchInput;
  const caret = focusedInput
    ? [active.selectionStart, active.selectionEnd]
    : null;
  const focusedAction = $("detail").contains(active)
    ? [
        "[data-enrich]",
        "[data-bookmark]",
        "[data-close-detail]",
        "#research-form button",
      ].find((selector) => active.matches(selector))
    : null;
  const focusedDisclosure =
    $("detail").contains(active) && active.tagName === "SUMMARY"
      ? active.parentElement.dataset.disclosure
      : null;
  rememberDetail();
  const scroll = renderedDetailId === row?.id ? $("detail").scrollTop : 0;
  lastDetail = signature;
  const same = renderedDetailId === row?.id;
  renderedDetailId = row?.id || null;
  if (!row) {
    $("detail").innerHTML =
      `<div class="empty-inspector">${icon("file-search", "large")}<h2>Bir fırsat seçin</h2><p>İhale bilgileri, sonraki adım ve firma araştırması burada görünür.</p></div>`;
    setDrawer(false, false);
    return;
  }
  const o = row.opportunity || {},
    ref = row.bulletin_reference,
    contacts = row.contacts || [],
    dates = dateParts(row);
  const scope =
    row.match_evidence ||
    o.reason ||
    "Teknik kapsam kaynak üzerinden doğrulanmalı.";
  const scopeContent =
    scope.length > 240
      ? `<p>${esc(scope.slice(0, 240))}…</p><details class="detail-disclosure" data-disclosure="scope"><summary>Kapsamın tamamı</summary><p>${esc(scope)}</p></details>`
      : `<p>${esc(scope)}</p>`;
  const documents = [
    sourceLink(row.url, "Kaynağı aç", "link"),
    ref
      ? sourceLink(
          `/api/bulletins/${encodeURIComponent(ref.filename)}#page=${Math.max(1, Number(ref.page_start) || 1)}`,
          `Resmî PDF · sayfa ${ref.page_start}`,
          "file-text",
        )
      : "",
    sourceLink(
      row.contact_search_url,
      "Kurumsal iletişimi araştır",
      "file-search",
    ),
  ].join("");
  $("detail").innerHTML =
    `<div class="inspector-top"><span class="source-label" title="${esc(row.source)}">${esc(sourceName(row))}</span><div class="detail-actions"><button class="icon-button" data-bookmark aria-label="${saved.has(row.id) ? "Takipten çıkar" : "Takibe al"}" aria-pressed="${saved.has(row.id)}" title="Bu tarayıcıda takibe al">${icon(saved.has(row.id) ? "bookmark-filled" : "bookmark")}</button><button class="icon-button close-detail" data-close-detail aria-label="Ayrıntıyı kapat">${icon("x")}</button></div></div>
    <h2>${esc(row.title)}</h2><p class="detail-meta">${esc([row.city, row.authority].filter(Boolean).join(" · "))}</p><p class="detail-meta">${row.tender_number ? `İKN: ${esc(row.tender_number)}` : ""}${row.published_date_raw ? ` &nbsp; Yayın: ${esc(row.published_date_raw)}` : ""}</p><p class="detail-meta">İhale tarihi: ${esc(dates.date)}${dates.time ? " · " + esc(dates.time) : ""} · ${esc(stages[row.stage] || row.stage || "")}</p>
    <div class="detail-status">${badge(sales[o.status] || "Kontrol gerekli", tone(o.status))}<div class="priority-score" title="Satış olasılığı değildir; kaydın takip önceliğidir."><span>Öncelik skoru</span><strong>${esc(o.priority || 0)}<small>/100</small></strong></div></div>
    <section class="detail-section"><h3>İş kapsamında</h3>${scopeContent}</section>
    <section class="next-action">${icon("info-circle")}<div><h3>Sonraki adım</h3><p>${esc(o.next_action || "Kaynak bilgilerini ve ilgili satınalma birimini doğrulayın.")}</p></div></section>
    <section class="source-links"><h3>Kaynak dokümanları</h3><div>${documents || '<p class="research-note">Kaynak bağlantısı bulunamadı.</p>'}</div></section>
    ${enrichmentMarkup(row)}
    <details class="detail-disclosure" data-disclosure="contacts"><summary>Kaynakta bulunan iletişimler (${contacts.length})</summary>${contacts.length ? contacts.map((c) => `<p><strong>${esc(c.role === "yuklenici" ? "Yüklenici" : c.role === "idare" ? "İdare" : "Duyurudaki iletişim")}: ${esc(c.name)}</strong>${c.phone ? "<br>Telefon: " + esc(c.phone) : ""}${c.email ? "<br>E-posta: " + esc(c.email) : ""}${c.address ? "<br>Adres: " + esc(c.address) : ""}${c.contact_scope ? "<br>" + esc(c.contact_scope) + " · " + esc(c.checked_at) : ""}${c.acquisition_method === "verified_company_directory" ? "<br>" + sourceLink(c.source_url, "Resmî şirket sitesi") + "<br>" + esc(c.note) : ""}</p>`).join("") : "<p>Keşif kaynağında iletişim bilgisi yok. Firma araştırmasını kullanabilirsiniz.</p>"}${(
      row.contractors || []
    )
      .filter((c) => c.period_end_raw)
      .map(
        (c) =>
          `<p>${esc(c.name)} · Sözleşme bitişi: ${esc(c.period_end_raw)}</p>`,
      )
      .join("")}</details>`;
  const open = disclosures.get(row.id) || new Set();
  $("detail")
    .querySelectorAll("details")
    .forEach((el) => {
      el.open = open.has(el.dataset.disclosure);
    });
  $("detail").scrollTop = scroll;
  if (same && focusedInput) {
    const input = $("detail").querySelector(
      `[data-research-input="${focusedInput}"]`,
    );
    input?.focus({ preventScroll: true });
    // URL inputs do not support selection ranges in every browser.
    if (input && input.type !== "url" && caret)
      input.setSelectionRange(...caret);
  } else if (same && focusedDisclosure) {
    $("detail")
      .querySelector(`[data-disclosure="${focusedDisclosure}"] summary`)
      ?.focus({ preventScroll: true });
  } else if (same && focusedAction) {
    const target = $("detail").querySelector(focusedAction);
    (target && !target.disabled ? target : $("detail")).focus({
      preventScroll: true,
    });
  }
}
function render() {
  const chosen = filters();
  const rows = filterRows(state.items, chosen, state.view, state.sort);
  const visible = rows.slice(0, state.limit);
  // Keep the inspector tied to a row that is actually present in the list.
  if (!visible.some((row) => row.id === state.selected))
    state.selected = visible[0]?.id || null;
  $("total").textContent = number(state.items.length);
  $("direct").textContent = number(
    state.items.filter((row) => row.relevance === "dogrudan").length,
  );
  $("potential").textContent = number(
    state.items.filter((row) => row.relevance === "potansiyel").length,
  );
  $("shown").textContent = state.loaded
    ? `${number(rows.length)} eşleşen fırsat · ${number(visible.length)} gösteriliyor`
    : "Veriler yükleniyor…";
  $("more").hidden = rows.length <= state.limit;
  $("empty-actions").hidden = !state.loaded || Boolean(rows.length);
  const extra = ["kind", "stage", "freshness", "research"].filter(
    (id) => chosen[id],
  ).length;
  $("filter-count").textContent = extra;
  $("filter-count").hidden = !extra;
  $("stage-heading").textContent =
    state.view === "research" ? "Araştırma" : "Aşama";
  document.querySelectorAll("[data-sort]").forEach((button) => {
    const selected = button.dataset.sort === state.sort.key;
    const header = button.closest("th");
    if (selected)
      header.setAttribute(
        "aria-sort",
        state.sort.direction === 1 ? "ascending" : "descending",
      );
    else header.removeAttribute("aria-sort");
    const image = button.querySelector("img");
    image.classList.toggle("sort-indicator", !selected);
    image.src = `/assets/${state.sort.direction === 1 && selected ? "arrow-up" : selected ? "arrow-down" : "chevrons-up"}.svg`;
  });
  const signature = JSON.stringify([
    visible.map((row) => [
      row.id,
      row.title,
      row.city,
      row.authority,
      row.source,
      row.tender_date_raw,
      row.tender_date_iso,
      row.opportunity,
      state.view === "research" ? researchStatus(row) : null,
    ]),
    state.selected,
    state.loaded,
  ]);
  if (signature !== lastList) {
    const focused = document.activeElement?.dataset?.select;
    $("list").innerHTML =
      visible
        .map((row) => {
          const dates = dateParts(row),
            o = row.opportunity || {},
            research = researchStatus(row);
          return `<tr data-record="${esc(row.id)}" class="${row.id === state.selected ? "selected" : ""}"><th scope="row"><button class="row-select" data-select="${esc(row.id)}" aria-pressed="${row.id === state.selected}"><span class="row-title">${esc(row.title)}</span><span class="row-meta">${esc([row.city, row.authority].filter(Boolean).join(" · "))}</span><span class="row-source">${esc(sourceName(row))}</span><span class="mobile-date">${esc(dates.date)} · Öncelik ${esc(o.priority || 0)}/100</span></button></th><td>${state.view === "research" ? badge(research.label, research.tone) : badge(sales[o.status] || "Kontrol gerekli", tone(o.status))}</td><td class="date-column"><span class="row-date">${esc(dates.date)}</span><span class="row-time">${esc(dates.time)}</span></td><td class="priority-column"><span class="priority-value">${esc(o.priority || 0)}/100</span></td><td class="row-tail">${icon("chevron-right", "row-arrow")}</td></tr>`;
        })
        .join("") ||
      `<tr><td colspan="5" class="empty-state">${state.loaded ? "Bu filtrelere uyan fırsat bulunamadı.<br>Aramayı veya filtreleri değiştirebilirsiniz." : "İhaleler yükleniyor…"}</td></tr>`;
    lastList = signature;
    if (focused)
      [...$("list").querySelectorAll("[data-select]")]
        .find((el) => el.dataset.select === focused)
        ?.focus({ preventScroll: true });
  }
  renderDetail(rows.find((row) => row.id === state.selected));
}
function renderSettings() {
  const s = state.status,
    ops = s.operations || {},
    health = s.enrichment?.search_health || [];
  if (JSON.stringify(s) === lastSettings) return;
  lastSettings = JSON.stringify(s);
  $("operations").innerHTML =
    `<section class="settings-section"><h2>Otomatik takip ve yedekleme</h2><div class="settings-grid"><div class="settings-block"><h3>${badge(ops.enabled ? "Otomatik takip açık" : "Otomatik takip kapalı", ops.enabled ? "green" : "neutral")}</h3><p>Sonraki kaynak taraması: ${esc(dateText(ops.scan?.next_at))}</p><p>Sonraki firma araştırması: ${esc(dateText(ops.research?.next_at))}</p>${ops.enabled ? `<p>Araştırma: ${esc(ops.research_batch_size)} kayıt / ${esc(ops.research_interval_minutes)} dakika · Bugün ${number(s.enrichment?.automatic_daily_used)}/${number(s.enrichment?.automatic_daily_limit)}</p>` : ""}</div><div class="settings-block"><h3>Yedekleme</h3><p>${badge(ops.backup_running ? "Hazırlanıyor…" : ops.backup?.status === "ok" ? "Doğrulandı" : ops.backup?.status === "error" ? "Tamamlanamadı; yeniden denenecek" : "Henüz alınmadı", ops.backup?.status === "ok" ? "green" : "neutral")}</p><p>Son başarılı yedek: ${esc(dateText(ops.backup?.last_success_at))}</p></div></div></section><section class="settings-section"><h2>Arama motorları ve firma araştırması</h2><p>${esc($("research-status").textContent)}</p>${health.length ? health.map((engine) => `<div class="source-status-row"><div><h3>${esc(engine.label)}</h3><p>Son deneme: ${esc(dateText(engine.checked_at))}<br>Son başarılı yanıt: ${esc(dateText(engine.last_success_at))} · Son hata: ${esc(dateText(engine.last_error_at))}</p></div><div>${badge({ ok: "Çalışıyor", empty: "Yanıt var; sonuç yok", error: "Son denemede erişilemedi", unknown: "Henüz denenmedi" }[engine.status] || engine.status, engine.status === "ok" ? "green" : engine.status === "error" ? "amber" : "neutral")}</div></div>`).join("") : "<p>Ek arama motoru henüz yapılandırılmadı.</p>"}</section>`;
  const results = s.last_scan?.sources || [];
  const sources = (s.configured_sources || []).map(
    (c) =>
      results.find((result) => result.url === c.url) || {
        ...c,
        status: c.enabled === false ? "disabled" : "pending",
      },
  );
  $("sources").innerHTML =
    `<section class="settings-section"><h2>Kaynaklar ve geçmiş taraması (${sources.length})</h2>${sources.map((source) => `<div class="source-status-row"><div><h3>${sourceLink(source.url, source.name)}</h3><p>${["ok", "partial"].includes(source.status) ? `${number(source.found)} uygun / ${number(source.examined)} incelenen kayıt · ${number(source.pages)} sayfa` : source.status === "disabled" ? "Otomatik tarama kapalı · " + esc(source.reason || "") : source.status === "pending" ? "Henüz taranmadı" : esc(source.error || "Kaynağa erişilemedi")}${source.archive ? `<br>EKAP geçmişi: ${number(source.archive.completed_days)}/${number(source.archive.target_days)} gün tamamlandı · ${number(source.archive.remaining_days)} gün kaldı${source.archive.provisional_days ? " · Bugün geçici kontrol edildi" : ""}` : ""}</p>${(source.warnings || []).map((warning) => `<p class="source-warning">${esc(warning)}</p>`).join("")}</div><div>${badge({ ok: "Güncel", partial: "Kısmi", disabled: "Kapalı", pending: "Bekliyor", error: "Kontrol gerekli" }[source.status] || source.status, source.status === "ok" ? "green" : ["error", "partial"].includes(source.status) ? "amber" : "neutral")}</div></div>`).join("")}</section>`;
  $("footer").textContent =
    "Her kayıt bir satış adayıdır; iklimlendirme ihtiyacı ve satınalma aşaması kaynak üzerinden doğrulanmalıdır. Kaynak kapsamı sınırlıdır; bütün Türkiye’deki satış fırsatlarının tamamı kapsanmaz. " +
    (ops.enabled
      ? `Bilgisayar ve uygulama açıkken ${Number(s.interval_minutes || 360) / 60} saatte bir güncellenir; eksik EKAP geçmişi partiler halinde tamamlanır.`
      : "Otomatik güncelleme kapalı; Kaynakları tara düğmesini kullanabilirsiniz.");
}
function renderStatus() {
  const s = state.status,
    enrichment = s.enrichment || {};
  $("scan").disabled = Boolean(s.scanning || s.is_demo);
  $("scan").querySelector("span").textContent = s.scanning
    ? "Taranıyor…"
    : "Kaynakları tara";
  $("status").textContent = s.scanning
    ? "Kaynaklar taranıyor…"
    : s.last_scan
      ? `Son tarama: ${dateText(s.last_scan.finished_at)}`
      : "Henüz tarama yapılmadı";
  $("research-status").textContent =
    `${number(enrichment.counts?.completed)} tamamlandı · ${number((enrichment.counts?.queued || 0) + (enrichment.counts?.running || 0))} sırada / çalışıyor`;
  $("enrich-all").disabled = pending.has("*");
  $("enrich-all").innerHTML =
    `${icon("file-search")}${pending.has("*") ? "Sıraya alınıyor…" : "Firmaları araştır"}`;
  if (s.is_demo && !connectionError && $("notice").hidden)
    notice(
      "SENTETİK DEMO — çevrimdışı; gerçek ihale ve firma bilgisi değildir.",
    );
  renderSettings();
}
function refresh() {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    try {
      const responses = await Promise.all([
        fetch("/api/tenders?compact=1"),
        fetch("/api/status"),
      ]);
      if (responses.some((response) => !response.ok))
        throw Error("Panel verileri alınamadı.");
      const [data, status] = await Promise.all(
        responses.map((response) => response.json()),
      );
      if (!Array.isArray(data.items)) throw Error("İhale verileri okunamadı.");
      const source = $("source").value;
      const choices = [...new Set(data.items.map((row) => row.source))].sort(
        (a, b) => a.localeCompare(b, "tr"),
      );
      if (JSON.stringify(choices) !== $("source").dataset.choices) {
        $("source").innerHTML =
          '<option value="">Tümü</option>' +
          choices
            .map(
              (value) => `<option value="${esc(value)}">${esc(value)}</option>`,
            )
            .join("");
        $("source").value = choices.includes(source) ? source : "";
        $("source").dataset.choices = JSON.stringify(choices);
      }
      state.items = data.items;
      state.status = status;
      state.loaded = true;
      if (connectionError) {
        $("notice").hidden = true;
        connectionError = false;
      }
      render();
      renderStatus();
    } catch {
      connectionError = true;
      $("status").textContent = "Bağlantı kurulamadı";
      notice(
        "Uygulamaya bağlanılamadı. Görünen veriler son alınan kayıtlardır; tekrar deneyebilirsiniz.",
        true,
      );
      if (!state.loaded)
        $("list").innerHTML =
          '<tr><td colspan="5" class="empty-state">İhale listesi yüklenemedi.<br>Yukarıdaki “Tekrar dene” düğmesini kullanın.</td></tr>';
    }
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}
async function enrichSelected() {
  const row = state.items.find((item) => item.id === state.selected);
  if (
    !row?.enrichment?.eligible ||
    pending.has(row.id) ||
    ["queued", "running"].includes(row.enrichment.state)
  )
    return;
  const form = $("research-form");
  if (form && !form.checkValidity()) {
    form.closest("details").open = true;
    form.reportValidity();
    return;
  }
  rememberDetail();
  const values = drafts.get(row.id) || {};
  const payload = {
    id: row.id,
    force: ["completed", "failed", "stale"].includes(row.enrichment.state),
  };
  if (values.company?.trim()) payload.company_urls = [values.company.trim()];
  if (values.award?.trim()) payload.award_urls = [values.award.trim()];
  pending.add(row.id);
  renderDetail(row);
  try {
    const response = await fetch("/api/enrich", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || "Araştırma başlatılamadı.");
    notice(
      "Firma araştırması sıraya alındı. Sonuçlar hazır olduğunda burada güncellenir.",
    );
    await refresh();
  } catch (error) {
    notice(error.message || "Araştırma başlatılamadı.", true);
  } finally {
    pending.delete(row.id);
    renderDetail(state.items.find((item) => item.id === state.selected));
  }
}
function changeView(view) {
  rememberDetail();
  state.view = view;
  state.limit = 60;
  setDrawer(false, false);
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
    if (button.dataset.view === view)
      button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  const names = {
    opportunities: [
      "Fırsatlar",
      "Klima, ısıtma-soğutma ve montaj için projeler, ihaleler ve yükleniciler.",
    ],
    research: [
      "Araştırmalar",
      "Yüklenicileri, firma iletişimlerini ve doğrulama kaynaklarını birlikte inceleyin.",
    ],
    settings: [
      "Kaynaklar ve ayarlar",
      "Otomatik takip, yedekleme ve arama motorlarının güncel durumu.",
    ],
  };
  $("page-title").textContent = names[view][0];
  $("page-description").textContent = names[view][1];
  $("settings-view").hidden = view !== "settings";
  $("opportunities-view").hidden = view === "settings";
  $("research-toolbar").hidden = view !== "research";
  if (view !== "settings") render();
}
$("today").dateTime = new Date().toISOString().slice(0, 10);
$("today").textContent = new Date().toLocaleDateString("tr-TR", {
  day: "numeric",
  month: "long",
  year: "numeric",
});
$("filters").addEventListener("submit", (event) => event.preventDefault());
filterIds.forEach((id) =>
  $(id).addEventListener("input", () => {
    state.limit = 60;
    render();
  }),
);
document.querySelectorAll(".clear-filters").forEach((button) =>
  button.addEventListener("click", () => {
    $("filters").reset();
    state.limit = 60;
    render();
  }),
);
document
  .querySelectorAll("[data-view]")
  .forEach((button) =>
    button.addEventListener("click", () => changeView(button.dataset.view)),
  );
document.querySelectorAll("[data-sort]").forEach((button) =>
  button.addEventListener("click", () => {
    const key = button.dataset.sort;
    state.sort = {
      key,
      direction:
        state.sort.key === key
          ? -state.sort.direction
          : key === "date"
            ? 1
            : -1,
    };
    render();
  }),
);
$("list").addEventListener("click", (event) => {
  const row = event.target.closest("[data-record]");
  if (!row) return;
  state.selected = row.dataset.record;
  render();
  returnFocus = [...$("list").querySelectorAll("[data-select]")].find(
    (button) => button.dataset.select === state.selected,
  );
  setDrawer(true);
  if (!narrow.matches && event.detail === 0)
    $("detail").focus({ preventScroll: true });
});
$("more").addEventListener("click", () => {
  state.limit += 60;
  render();
});
$("detail").addEventListener("input", rememberDetail);
$("detail").addEventListener("submit", (event) => {
  event.preventDefault();
  enrichSelected();
});
$("detail").addEventListener("click", (event) => {
  if (event.target.closest("[data-close-detail]")) setDrawer(false);
  if (event.target.closest("[data-enrich]")) enrichSelected();
  if (event.target.closest("[data-bookmark]")) {
    if (saved.has(state.selected)) saved.delete(state.selected);
    else saved.add(state.selected);
    try {
      localStorage.setItem("ihalesystem:followed", JSON.stringify([...saved]));
    } catch {
      notice("Takip işareti yalnızca bu oturumda saklanabiliyor.");
    }
    renderDetail(state.items.find((item) => item.id === state.selected));
  }
});
$("detail-backdrop").addEventListener("click", () => setDrawer(false));
narrow.addEventListener("change", () => setDrawer(false, false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (document.body.classList.contains("detail-open")) setDrawer(false);
    else if ($("extra-filters").open) {
      $("extra-filters").open = false;
      $("extra-filters").querySelector("summary").focus();
    }
  }
  if (event.key === "Tab" && document.body.classList.contains("detail-open")) {
    const controls = [
      ...$("detail").querySelectorAll("a[href],button,input,summary"),
    ].filter((el) => !el.disabled && el.getClientRects().length);
    const first = controls[0],
      last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
});
document.addEventListener("click", (event) => {
  if (!$("extra-filters").contains(event.target))
    $("extra-filters").open = false;
  if (event.target.closest("[data-retry]")) refresh();
  if (event.target.closest("[data-dismiss]")) $("notice").hidden = true;
});
$("scan").addEventListener("click", async () => {
  $("scan").disabled = true;
  try {
    const response = await fetch("/api/scan", { method: "POST" });
    if (!response.ok) throw Error("Tarama başlatılamadı.");
    notice(
      "Kaynak taraması başladı. Yeni fırsatlar listeye kademeli olarak eklenecek.",
    );
    await refresh();
  } catch (error) {
    notice(error.message, true);
    $("scan").disabled = false;
  }
});
$("enrich-all").addEventListener("click", async () => {
  if (pending.has("*")) return;
  pending.add("*");
  renderStatus();
  try {
    const response = await fetch("/api/enrich", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const result = await response.json();
    if (!response.ok)
      throw Error(result.error || "Araştırmalar başlatılamadı.");
    notice(`${number(result.queued)} sonuç kaydı araştırma sırasına alındı.`);
    await refresh();
  } catch (error) {
    notice(error.message, true);
  } finally {
    pending.delete("*");
    renderStatus();
  }
});
refresh();
setInterval(refresh, 10000);
