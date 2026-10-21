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
  const scopeLabels = {
    klima: "Klima / iklimlendirme",
    havalandirma: "Havalandırma",
    isitma: "Isıtma",
    sogutma: "Soğutma",
    mekanik: "Mekanik tesisat",
  };
  const isEfaRelated = (row) => row.efa_scope?.matched === true;
  const scopeText = (row) =>
    (row.efa_scope?.categories || [])
      .map((key) => scopeLabels[key])
      .filter(Boolean)
      .join(" · ");
  function tenderStatus(row) {
    if (row.stage === "iptal") return { label: "İptal edildi", tone: "red" };
    if (row.stage === "kapandi") return { label: "Kapalı", tone: "neutral" };
    if (row.stage === "sonuc") return { label: "Sonuçlandı", tone: "green" };
    if (row.stage === "proje") {
      if (row.source_presence === "missing")
        return { label: "Proje durumu belirsiz", tone: "amber" };
      if (row.source_status === "Hemen teslim proje")
        return { label: "Teslime hazır proje", tone: "neutral" };
      return row.source_status === "Devam eden proje"
        ? { label: "Proje devam ediyor", tone: "blue" }
        : { label: "Yatırım duyurusu", tone: "neutral" };
    }
    if (row.stage === "degerlendirme")
      return { label: "Değerlendirmede", tone: "amber" };
    if (row.freshness === "tarih_gecmis")
      return { label: "Teklif tarihi geçti", tone: "amber" };
    if (row.stage === "duzeltme")
      return { label: "Düzeltme yayımlandı", tone: "blue" };
    if (row.freshness === "yaklasan")
      return { label: "Teklif bekleniyor", tone: "blue" };
    return { label: "Tarih doğrulanmalı", tone: "neutral" };
  }
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
  const contactLabels = {
    phone: "Telefon",
    email: "E-posta",
    address: "Adres",
    website: "Web sitesi",
    city: "İl",
    district: "İlçe",
    mersis_no: "MERSİS no",
    trade_registry_no: "Sicil no",
    trade_registry_office: "Sicil müdürlüğü",
    tax_no: "Vergi no",
    tax_office: "Vergi dairesi",
  };
  function contactHref(field, value) {
    const text = String(value || "").trim();
    if (field === "website") return safeURL(text);
    if (field === "phone" && /^\+?[\d ()-]{7,24}$/.test(text)) {
      const phone = text.replace(/[ ()-]/g, "");
      return /^\+?\d{7,15}$/.test(phone) ? `tel:${phone}` : null;
    }
    if (field === "email" && /^[\w.+-]+@[\w.-]+\.[a-z]{2,}$/i.test(text))
      return `mailto:${text}`;
    return null;
  }
  function contactCards(row) {
    const result = row.enrichment?.result;
    const winner = result?.winner;
    const identity = (value) =>
      tr(value)
        .normalize("NFKD")
        .replace(/\p{M}/gu, "")
        .replace(/ı/g, "i")
        .replace(/[^\p{L}\p{N}]/gu, "");
    const comparable = (field, value) =>
      field === "phone"
        ? String(value || "")
            .replace(/\D/g, "")
            .replace(/^90(?=\d{10}$)/, "0")
        : tr(value).trim();
    const cards = [];
    if (winner) {
      cards.push({
        kind: "research",
        role: "Yüklenici · bot araştırması",
        name: winner.company_name || "Firma adı doğrulanamadı",
        entries: Object.entries(contactLabels)
          .filter(
            ([field]) =>
              ["phone", "email", "address", "website"].includes(field) ||
              winner[field],
          )
          .map(([field, label]) => {
            const status =
              result.field_verification?.[field]?.status ||
              (winner[field] ? "single_source" : "missing");
            return {
              field,
              label,
              values: [
                {
                  value:
                    status === "conflicting" ? null : winner[field] || null,
                  status,
                },
              ],
            };
          }),
        sources: [],
        notes: [],
      });
    }
    const groups = new Map();
    for (const contact of row.contacts || []) {
      const name =
        contact.name ||
        (contact.role === "idare" ? row.authority : "") ||
        "Adı belirtilmemiş";
      const key = `${contact.role}:${identity(name)}`;
      if (!groups.has(key))
        groups.set(key, {
          kind: "source",
          role:
            {
              idare: "İdare / satınalma birimi",
              yuklenici: "İlandaki yüklenici",
              duyuru: "Duyurudaki iletişim",
            }[contact.role] || "Duyurudaki iletişim",
          name,
          entries: [],
          sources: [],
          notes: [],
        });
      const card = groups.get(key);
      const sameWinner =
        contact.role === "yuklenici" &&
        winner?.company_name &&
        identity(name) === identity(winner.company_name);
      for (const field of ["phone", "email", "address", "website"]) {
        const value = contact[field];
        if (!value) continue;
        // A source contact is never used to fill a researched or conflicting field.
        // Suppress only an identical, already visible value for the same contractor.
        if (
          sameWinner &&
          result.field_verification?.[field]?.status !== "conflicting" &&
          comparable(field, value) === comparable(field, winner[field])
        )
          continue;
        let entry = card.entries.find((item) => item.field === field);
        if (!entry) {
          entry = { field, label: contactLabels[field], values: [] };
          card.entries.push(entry);
        }
        if (
          !entry.values.some(
            (item) =>
              comparable(field, item.value) === comparable(field, value),
          )
        )
          entry.values.push({
            value,
            status:
              contact.acquisition_method === "verified_company_directory"
                ? "company_site"
                : "announcement",
          });
      }
      if (contact.source_url && !card.sources.includes(contact.source_url))
        card.sources.push(contact.source_url);
      const note = [contact.contact_scope, contact.checked_at, contact.note]
        .filter(Boolean)
        .join(" · ");
      if (note && !card.notes.includes(note)) card.notes.push(note);
      // Empty duplicate cards add no information; named source-only parties still matter.
      card.coveredByWinner = Boolean(sameWinner);
    }
    for (const card of groups.values()) {
      if (!card.coveredByWinner || card.entries.length) {
        card.entries.sort(
          (a, b) =>
            Object.keys(contactLabels).indexOf(a.field) -
            Object.keys(contactLabels).indexOf(b.field),
        );
        cards.push(card);
      } else {
        // Keep provenance and general-office caveats when duplicate values are hidden.
        cards[0].sources.push(
          ...card.sources.filter((url) => !cards[0].sources.includes(url)),
        );
        cards[0].notes.push(
          ...card.notes.filter((note) => !cards[0].notes.includes(note)),
        );
      }
    }
    return cards;
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
      if (!isEfaRelated(row)) return false;
      if (view === "research" && !row.enrichment?.eligible) return false;
      if (
        filters.kind &&
        (scopeLabels[filters.kind]
          ? !row.efa_scope.categories.includes(filters.kind)
          : row.relevance !== filters.kind)
      )
        return false;
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
    scopeLabels,
    isEfaRelated,
    scopeText,
    tenderStatus,
    fields,
    esc,
    number,
    safeURL,
    contactHref,
    contactCards,
    researchStatus,
    dateParts,
    filterRows,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PanelData = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
