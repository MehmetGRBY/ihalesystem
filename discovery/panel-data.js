/* Shared, side-effect-free presentation rules. Also used by Node's regression tests. */
(function (root) {
  const sales = {
    teklif: "Teklif değerlendir",
    yuklenici: "Yükleniciye ulaş",
    proje: "Devam eden proje",
    takip: "Sonucu takip et",
    kontrol: "Araştırma gerekli",
    arsiv: "Arşiv / iptal / bitmiş iş",
  };
  const stages = {
    ilan: "İlan",
    degerlendirme: "Değerlendirme",
    duzeltme: "Düzeltme",
    iptal: "İptal",
    sonuc: "Sonuç",
    kapandi: "Kapalı",
    proje: "Yatırım / proje",
  };
  const fields = {
    verified: "Doğrulandı",
    single_source: "Tek kaynak",
    conflicting: "Çelişkili",
    missing: "Eksik",
  };
  const researchLabels = {
    resolved: "Bilgiler doğrulandı",
    partial: "Kısmen tamamlandı",
    review_required: "Elle kontrol gerekli",
    unresolved: "Kazanan bulunamadı",
    failed: "Araştırma tamamlanamadı",
  };
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const tr = (value) => String(value ?? "").toLocaleLowerCase("tr-TR");
  const number = (value) =>
    new Intl.NumberFormat("tr-TR").format(Number(value) || 0);
  function safeURL(value) {
    try {
      const url = new URL(String(value));
      return ["https:", "http:"].includes(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  }
  function researchStatus(row) {
    const e = row.enrichment;
    if (!e?.eligible)
      return {
        label: "Araştırmaya uygun değil",
        tone: "neutral",
        key: "ineligible",
      };
    if (["queued", "running"].includes(e.state))
      return {
        label: e.state === "queued" ? "Araştırma sırada" : "Araştırılıyor…",
        tone: "blue",
        key: e.state,
      };
    if (e.state === "stale")
      return { label: "Yeniden araştırılmalı", tone: "amber", key: "stale" };
    if (e.state === "failed")
      return { label: "Araştırma tamamlanamadı", tone: "red", key: "failed" };
    const result = e.result;
    if (!result)
      return { label: "Henüz araştırılmadı", tone: "neutral", key: "idle" };
    return {
      label: researchLabels[result.status] || "Kontrol gerekli",
      tone:
        result.status === "resolved"
          ? "green"
          : result.status === "failed"
            ? "red"
            : "amber",
      key: result.status,
    };
  }
  function dateParts(row) {
    const raw = String(row.tender_date_raw || "");
    const match = raw.match(
      /(\d{1,2}\.\d{1,2}\.\d{4})(?:\s*[-–]?\s*(\d{1,2}:\d{2}))?/,
    );
    if (match) return { date: match[1], time: match[2] || "" };
    if (
      row.tender_date_iso &&
      Number.isFinite(Date.parse(row.tender_date_iso))
    ) {
      return {
        date: new Intl.DateTimeFormat("tr-TR").format(
          new Date(row.tender_date_iso),
        ),
        time: "",
      };
    }
    return { date: raw || "Tarih belirtilmemiş", time: "" };
  }
  function filterRows(
    items,
    filters,
    view = "opportunities",
    sorting = { key: "priority", direction: -1 },
  ) {
    const query = tr(filters.search).trim();
    const result = items.filter((row) => {
      if (view === "research" && !row.enrichment?.eligible) return false;
      if (filters.kind && row.relevance !== filters.kind) return false;
      if (filters.source && row.source !== filters.source) return false;
      if (filters.stage && row.stage !== filters.stage) return false;
      if (filters.freshness && row.freshness !== filters.freshness)
        return false;
      if (filters.sales === "actionable" && row.opportunity?.status === "arsiv")
        return false;
      if (
        filters.sales &&
        filters.sales !== "actionable" &&
        row.opportunity?.status !== filters.sales
      )
        return false;
      if (filters.research && researchStatus(row).key !== filters.research)
        return false;
      if (!query) return true;
      const winner = row.enrichment?.result?.winner || {};
      return tr(
        [
          row.title,
          row.source,
          row.authority,
          row.city,
          row.tender_number,
          row.opportunity?.target_name,
          row.match_evidence,
          winner.company_name,
          winner.phone,
          winner.email,
          ...(row.contractors || []).map((c) => c.name),
        ].join(" "),
      ).includes(query);
    });
    const date = (row) =>
      row.tender_date_iso && Number.isFinite(Date.parse(row.tender_date_iso))
        ? Date.parse(row.tender_date_iso)
        : null;
    return result.sort((a, b) => {
      if (sorting.key === "date") {
        const left = date(a),
          right = date(b);
        if (left === null && right !== null) return 1;
        if (right === null && left !== null) return -1;
        if (left !== right)
          return ((left || 0) - (right || 0)) * sorting.direction;
      }
      const priority =
        (a.opportunity?.priority || 0) - (b.opportunity?.priority || 0);
      if (priority)
        return priority * (sorting.key === "priority" ? sorting.direction : -1);
      return (
        (date(a) ?? Infinity) - (date(b) ?? Infinity) ||
        String(a.id).localeCompare(String(b.id))
      );
    });
  }
  const api = {
    sales,
    stages,
    fields,
    esc,
    number,
    safeURL,
    researchStatus,
    dateParts,
    filterRows,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PanelData = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
