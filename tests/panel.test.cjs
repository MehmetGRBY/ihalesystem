const { test } = require("node:test");
const assert = require("node:assert/strict");
const ui = require("../discovery/panel-data.js");
const rows = [
  {
    id: "a",
    title: "İstanbul Isıtma Tesisatı",
    city: "İstanbul",
    source: "EKAP",
    relevance: "dogrudan",
    stage: "sonuc",
    freshness: "kapali",
    tender_date_iso: "2026-10-24",
    tender_date_raw: "24.10.2026 - 10:30",
    opportunity: { status: "yuklenici", priority: 85 },
    enrichment: {
      eligible: true,
      state: "completed",
      result: {
        status: "partial",
        winner: {
          company_name: "Mikrotek Havalandırma",
          phone: "+902122223544",
        },
      },
    },
  },
  {
    id: "b",
    title: "Hastane mekanik tesisatı",
    city: "Van",
    source: "TOKİ",
    relevance: "potansiyel",
    stage: "ilan",
    freshness: "yaklasan",
    tender_date_iso: "2026-10-23",
    opportunity: { status: "teklif", priority: 90 },
    enrichment: { eligible: false },
  },
  {
    id: "c",
    title: "İptal edilmiş iş",
    source: "EKAP",
    relevance: "dogrudan",
    stage: "iptal",
    opportunity: { status: "arsiv", priority: 20 },
    enrichment: { eligible: false },
  },
  {
    id: "d",
    title: "Tarihsiz okul havalandırması",
    source: "EKAP",
    relevance: "dogrudan",
    opportunity: { status: "kontrol", priority: 50 },
    enrichment: { eligible: true, state: "queued" },
  },
];
test("Turkish search matches city, number and researched contractor without ignoring archive filter", () => {
  assert.deepEqual(
    ui
      .filterRows(rows, { search: "İSTANBUL", sales: "actionable" })
      .map((r) => r.id),
    ["a"],
  );
  assert.deepEqual(
    ui.filterRows(rows, { search: "MİKROTEK" }).map((r) => r.id),
    ["a"],
  );
  assert.deepEqual(
    ui.filterRows(rows, { search: "+902122223544" }).map((r) => r.id),
    ["a"],
  );
  assert.deepEqual(
    ui.filterRows(rows, { sales: "actionable" }).map((r) => r.id),
    ["b", "a", "d"],
  );
  assert.equal(ui.filterRows(rows, { sales: "" }).length, 4);
  assert.deepEqual(
    ui.filterRows(rows, { sales: "arsiv" }).map((r) => r.id),
    ["c"],
  );
});
test("all filters compose; research view never offers ineligible entries", () => {
  assert.deepEqual(
    ui
      .filterRows(rows, {
        source: "EKAP",
        kind: "dogrudan",
        stage: "sonuc",
        freshness: "kapali",
        research: "partial",
      })
      .map((r) => r.id),
    ["a"],
  );
  assert.deepEqual(
    ui.filterRows(rows, { research: "queued" }, "research").map((r) => r.id),
    ["d"],
  );
  assert.deepEqual(
    ui.filterRows(rows, {}, "research").map((r) => r.id),
    ["a", "d"],
  );
  assert.deepEqual(ui.filterRows(rows, { source: "TOKİ", stage: "sonuc" }), []);
});
test("date ordering keeps unknown dates last in both directions and never mutates inputs", () => {
  assert.deepEqual(
    ui
      .filterRows(rows, {}, "opportunities", { key: "date", direction: 1 })
      .map((r) => r.id),
    ["b", "a", "d", "c"],
  );
  assert.deepEqual(
    ui
      .filterRows(rows, {}, "opportunities", { key: "date", direction: -1 })
      .map((r) => r.id),
    ["a", "b", "d", "c"],
  );
  assert.deepEqual(
    rows.map((r) => r.id),
    ["a", "b", "c", "d"],
  );
});
test("raw Turkish tender time is preserved, absent and invalid dates stay understandable", () => {
  assert.deepEqual(ui.dateParts(rows[0]), {
    date: "24.10.2026",
    time: "10:30",
  });
  assert.equal(ui.dateParts(rows[3]).date, "Tarih belirtilmemiş");
  assert.equal(
    ui.dateParts({ tender_date_iso: "invalid" }).date,
    "Tarih belirtilmemiş",
  );
});
test("stale results do not present old company verification as current success", () => {
  assert.equal(
    ui.researchStatus({
      ...rows[0],
      enrichment: { ...rows[0].enrichment, state: "stale" },
    }).key,
    "stale",
  );
  assert.equal(ui.researchStatus(rows[0]).tone, "amber");
  assert.equal(ui.researchStatus(rows[3]).label, "Araştırma sırada");
});
test("untrusted external text and URLs cannot become active HTML or script links", () => {
  assert.equal(ui.safeURL("javascript:alert(1)"), null);
  assert.equal(ui.safeURL("data:text/html,<script>bad()</script>"), null);
  assert.equal(ui.safeURL("//example.com"), null);
  assert.equal(
    ui.safeURL("https://example.com/contact"),
    "https://example.com/contact",
  );
  assert.equal(
    ui.esc('<img src=x onerror="bad()">'),
    "&lt;img src=x onerror=&quot;bad()&quot;&gt;",
  );
});
