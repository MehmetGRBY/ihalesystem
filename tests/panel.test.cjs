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

test("announcement contacts stay available before research and keep their authority role", () => {
  const row = {
    authority: "Aydın Gençlik ve Spor İl Müdürlüğü",
    contacts: [
      {
        role: "idare",
        phone: "02562131166",
        address: "Hasanefendi Mah. No:67",
      },
    ],
    enrichment: { eligible: true, state: "not_started", result: null },
  };
  for (const state of ["not_started", "queued", "running", "failed"]) {
    const cards = ui.contactCards({
      ...row,
      enrichment: { ...row.enrichment, state },
    });
    assert.equal(cards.length, 1);
    assert.equal(cards[0].role, "İdare / satınalma birimi");
    assert.equal(cards[0].name, row.authority);
    assert.equal(cards[0].entries[0].values[0].value, "02562131166");
    assert.equal(cards[0].entries[1].field, "address");
    assert.equal(cards[0].entries[0].values[0].status, "announcement");
  }
});

test("researched contractor never borrows authority phone or masks conflicting values", () => {
  const row = {
    contacts: [{ role: "idare", name: "Belediye", phone: "02120000000" }],
    enrichment: {
      eligible: true,
      state: "completed",
      result: {
        winner: {
          company_name: "ABC İnşaat",
          phone: "+902121111111",
          email: "info@abc.test",
          address: "Firma adresi",
          tax_no: "1234567890",
        },
        field_verification: {
          phone: { status: "conflicting" },
          email: { status: "single_source" },
          address: { status: "verified" },
        },
      },
    },
  };
  const cards = ui.contactCards(row);
  assert.equal(cards.length, 2);
  assert.equal(cards[0].role, "Yüklenici · bot araştırması");
  assert.deepEqual(cards[0].entries[0].values, [
    { value: null, status: "conflicting" },
  ]);
  assert.equal(
    cards[0].entries.find((e) => e.field === "address").values[0].status,
    "verified",
  );
  assert.equal(
    cards[0].entries.find((e) => e.field === "tax_no").values[0].value,
    "1234567890",
  );
  assert.equal(cards[1].entries[0].values[0].value, "02120000000");
  const missingPhone = structuredClone(row);
  missingPhone.enrichment.result.winner.phone = null;
  missingPhone.enrichment.result.field_verification.phone.status = "missing";
  assert.equal(
    ui.contactCards(missingPhone)[0].entries[0].values[0].value,
    null,
  );
  assert.equal(
    ui.contactCards({
      ...row,
      enrichment: { ...row.enrichment, state: "stale" },
    })[0].name,
    "ABC İnşaat",
  );
  assert.equal(
    ui.researchStatus({
      ...row,
      enrichment: { ...row.enrichment, state: "stale" },
    }).key,
    "stale",
  );
});

test("duplicate company contacts merge while separate parties and differing values remain visible", () => {
  const contact = {
    role: "yuklenici",
    name: "ABC İnşaat",
    phone: "0212 111 11 11",
    address: "Firma adresi",
    source_url: "https://abc.test/contact",
  };
  const row = {
    contacts: [
      contact,
      { ...contact },
      {
        ...contact,
        email: "info@abc.test",
        acquisition_method: "verified_company_directory",
      },
      { ...contact, name: "Başka Firma" },
    ],
    enrichment: {
      result: {
        winner: {
          company_name: "ABC İnşaat",
          phone: "+902121111111",
          address: "Firma adresi",
        },
        field_verification: { phone: { status: "single_source" } },
      },
    },
  };
  const cards = ui.contactCards(row);
  assert.equal(cards.length, 3);
  assert.equal(cards[1].entries.length, 1);
  assert.equal(cards[1].entries[0].field, "email");
  assert.equal(cards[1].entries[0].values[0].status, "company_site");
  assert.equal(cards[2].name, "Başka Firma");
  const unresearched = ui.contactCards({
    contacts: [
      contact,
      { ...contact },
      { ...contact, phone: "0212 222 22 22" },
    ],
  });
  assert.equal(unresearched.length, 1);
  assert.equal(unresearched[0].entries[0].values.length, 2);
  assert.equal(unresearched[0].sources.length, 1);
  const covered = ui.contactCards({
    ...row,
    contacts: [
      {
        ...contact,
        contact_scope: "şirket merkezi",
        note: "Proje yetkilisi doğrulanmadı.",
      },
    ],
  });
  assert.equal(covered.length, 1);
  assert.deepEqual(covered[0].sources, [contact.source_url]);
  assert.match(covered[0].notes[0], /Proje yetkilisi doğrulanmadı/);
  assert.deepEqual(
    ui.contactCards({ contacts: [], enrichment: { eligible: true } }),
    [],
  );
});

test("contact actions accept ordinary phone/email and reject injected schemes, query headers and markup", () => {
  assert.equal(ui.contactHref("phone", "0212 222 35 44"), "tel:02122223544");
  assert.equal(
    ui.contactHref("phone", "+90 (212) 222-35-44"),
    "tel:+902122223544",
  );
  assert.equal(
    ui.contactHref("email", "sales+hvac@firma.com.tr"),
    "mailto:sales+hvac@firma.com.tr",
  );
  assert.equal(
    ui.contactHref("website", "https://firma.test/contact"),
    "https://firma.test/contact",
  );
  for (const value of [
    "javascript:alert(1)",
    '1234567\" onclick=\"bad()',
    "123\n4567890",
    "+123456789012345678",
  ])
    assert.equal(ui.contactHref("phone", value), null);
  for (const value of [
    "a@b.test?bcc=x@y.test",
    "a@b.test\r\nBcc: x@y.test",
    "<a@b.test>",
  ])
    assert.equal(ui.contactHref("email", value), null);
  assert.equal(ui.contactHref("website", "javascript:alert(1)"), null);
  assert.equal(ui.contactHref("address", "https://firma.test"), null);
});
