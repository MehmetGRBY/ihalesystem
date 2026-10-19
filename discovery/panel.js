let items=[],limit=60,previousItems='';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stages={ilan:'İlan',degerlendirme:'Değerlendirme',duzeltme:'Düzeltme',iptal:'İptal',sonuc:'Sonuç',kapandi:'Kapalı',proje:'Yatırım / proje'};
const sales={teklif:'Teklif değerlendir',yuklenici:'Yükleniciye ulaş',proje:'Devam eden proje',takip:'Sonucu takip et',kontrol:'Araştırma gerekli',arsiv:'Arşiv / iptal / bitmiş iş'};

function render(){
 const q=$('search').value.toLocaleLowerCase('tr'),date=$('freshness').value,sale=$('sales').value;
 const filtered=items.filter(x=>(!$('kind').value||x.relevance===$('kind').value)&&(!$('source').value||x.source===$('source').value)&&(!$('stage').value||x.stage===$('stage').value)&&(!date||x.freshness===date)&&(!sale||(sale==='actionable'?x.opportunity?.status!=='arsiv':x.opportunity?.status===sale))&&(!q||[x.title,x.source,x.authority,x.city,x.opportunity?.target_name,x.match_evidence].join(' ').toLocaleLowerCase('tr').includes(q)));
 filtered.sort((a,b)=>(b.opportunity?.priority||0)-(a.opportunity?.priority||0)||(a.tender_date_iso||'9999').localeCompare(b.tender_date_iso||'9999'));
 $('total').textContent=items.length;
 $('direct').textContent=items.filter(x=>x.relevance==='dogrudan').length;
 $('potential').textContent=items.filter(x=>x.relevance==='potansiyel').length;
 $('shown').textContent=`${filtered.length} eşleşen fırsat · ${Math.min(limit,filtered.length)} gösteriliyor. Sayaçlar arşiv kayıtlarını da içerir.`;
 const open=new Set([...$('list').querySelectorAll('details[open]')].map(x=>x.dataset.id));
 $('list').innerHTML=filtered.slice(0,limit).map(x=>{
  const o=x.opportunity||{},c=x.contractors||[],contacts=x.contacts||[],ref=x.bulletin_reference;
  return `<article class="card"><span class="badge">${esc(sales[o.status]||'Kontrol gerekli')}</span> <span class="badge potential">${x.relevance==='dogrudan'?'HVAC ifadesi bulundu':'Potansiyel ihtiyaç'}</span><h2>${esc(x.title)}</h2><div class="meta"><span>${esc(x.source)}</span><span>${esc(stages[x.stage]||x.stage)}</span>${x.city?`<span>${esc(x.city)}</span>`:''}<span>Öncelik: ${o.priority??0}/100</span></div><p>${esc(o.reason)}</p><p><strong>Ulaşılacak taraf:</strong> ${esc(o.target_name||'Kaynakta belirlenemedi')}<br>${esc(o.target_role)}</p><p><strong>Sonraki adım:</strong> ${esc(o.next_action)}</p><div class="meta">${x.tender_number?`<span>İKN / No: ${esc(x.tender_number)}</span>`:''}<span>İhale tarihi: ${esc(x.tender_date_raw||'Kaynakta okunamadı')}</span>${x.published_date_raw?`<span>Yayın: ${esc(x.published_date_raw)}</span>`:''}</div>${c.length?`<p>${c.map(v=>`${esc(v.name)}${v.period_end_raw?' · Sözleşme bitişi: '+esc(v.period_end_raw):''}`).join('<br>')}</p>`:''}${x.match_basis==='scope'?`<p><strong>İş kapsamından eşleşme:</strong> ${esc(x.match_evidence?.slice(0,400))}</p>`:''}${contacts.length?`<details data-id="${esc(x.id)}" ${open.has(x.id)?'open':''}><summary>Kaynakta bulunan iletişimler (${contacts.length})</summary>${contacts.map(v=>`<p><strong>${esc(v.role==='yuklenici'?'Yüklenici':v.role==='idare'?'İdare':'Duyurudaki iletişim')}: ${esc(v.name)}</strong><br>${v.phone?'Telefon: '+esc(v.phone)+'<br>':''}${v.email?'E-posta: '+esc(v.email)+'<br>':''}${v.address?'Adres: '+esc(v.address):''}${v.contact_scope?'<br>'+esc(v.contact_scope)+' · '+esc(v.checked_at):''}${v.acquisition_method==='verified_company_directory'?`<br><a href="${esc(v.source_url)}" target="_blank" rel="noopener noreferrer">Resmî şirket sitesi ↗</a><br>${esc(v.note)}`:''}</p>`).join('')}</details>`:'<p>İlgili tarafa ait telefon/e-posta henüz bulunmadı.</p>'}<p><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">Kaynağı aç ↗</a>${ref?` · <a href="/api/bulletins/${encodeURIComponent(ref.filename)}#page=${ref.page_start}" target="_blank" rel="noopener noreferrer">Resmî PDF · sayfa ${ref.page_start} ↗</a>`:''}${x.contact_search_url?` · <a href="${esc(x.contact_search_url)}" target="_blank" rel="noopener noreferrer">Kurumsal iletişimi araştır ↗</a>`:''}</p></article>`;
 }).join('')||'<p>Bu filtrelere uyan fırsat yok. Satış takibi filtresini değiştirin.</p>';
 $('more').hidden=filtered.length<=limit;
}

async function refresh(){try{
 const [r,s]=await Promise.all([fetch('/api/tenders?compact=1'),fetch('/api/status')]);
 if(!r.ok||!s.ok)throw Error('Panel yanıt vermiyor');
 const data=(await r.json()).items,state=await s.json(),signature=JSON.stringify(data);
 if(signature!==previousItems){
  items=data;previousItems=signature;
  const chosen=$('source').value;
  $('source').innerHTML='<option value="">Tüm kaynaklar</option>'+[...new Set(items.map(x=>x.source))].sort().map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');$('source').value=chosen;
  render();
 }
 $('scan').disabled=state.scanning;$('scan').textContent=state.scanning?'Taranıyor…':'Şimdi tara';
 $('status').textContent=state.scanning?'Kaynaklar taranıyor; geçmiş bültenler okunurken yeni fırsatlar kademeli eklenir.':state.last_scan?`Son tarama: ${new Date(state.last_scan.finished_at).toLocaleString('tr-TR')} · ${state.last_scan.new} yeni, ${state.last_scan.changed} güncelleme`:'Henüz tarama yapılmadı.';
 const results=state.last_scan?.sources||[];
 const sources=(state.configured_sources||[]).map(c=>results.find(x=>x.url===c.url)||{...c,status:c.enabled===false?'disabled':'pending'});
 const wasOpen=$('sources').querySelector('details')?.open;
 $('sources').innerHTML='<details'+(wasOpen?' open':'')+'><summary>Kaynaklar ve geçmiş taraması ('+sources.length+')</summary>'+sources.map(x=>`<div class="source ${x.status==='error'||x.status==='partial'?'error':'muted'}"><a style="color:inherit" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.name)}</a>: ${['ok','partial'].includes(x.status)?`${x.found} uygun / ${x.examined} incelenen kayıt · ${x.pages} sayfa${x.status==='partial'?' · Kısmi':''}`:x.status==='disabled'?'Otomatik tarama kapalı · '+esc(x.reason):x.status==='pending'?'Henüz taranmadı':esc(x.error)}${x.archive?`<div>EKAP geçmişi: ${x.archive.completed_days}/${x.archive.target_days} gün tamamlandı · ${x.archive.remaining_days} gün kaldı${x.archive.provisional_days?' · Bugün geçici kontrol edildi':''}</div>`:''}${(x.warnings||[]).map(w=>'<div>'+esc(w)+'</div>').join('')}</div>`).join('')+'</details>';
 $('footer').textContent='Kaynak kapsamı sınırlıdır; bütün Türkiye’deki satış fırsatlarının tamamı kapsanmaz. Bot çalıştığı sürece '+(state.interval_minutes/60)+' saatte bir güncellenir; geçmiş EKAP eksikse partiler arasında '+(state.archive_interval_minutes||1)+' dakika bekleyerek kaldığı yerden ilerler.';
 }catch(e){$('status').textContent='Bağlantı hatası: '+e.message;}}

$('scan').onclick=async()=>{try{$('scan').disabled=true;const r=await fetch('/api/scan',{method:'POST'});if(!r.ok)throw Error('Tarama başlatılamadı');setTimeout(refresh,400);}catch(e){$('status').textContent=e.message;$('scan').disabled=false;}};
['search','sales','kind','source','stage','freshness'].forEach(id=>$(id).addEventListener('input',()=>{limit=60;render();}));
$('more').onclick=()=>{limit+=60;render();};
refresh();setInterval(refresh,10000);
