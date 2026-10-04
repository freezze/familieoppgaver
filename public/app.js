const DAGER = ['mandag', 'tirsdag', 'onsdag', 'torsdag', 'fredag', 'lørdag', 'søndag'];
const FELLES_FARGE = '#8A6BB8';
const $ = id => document.getElementById(id);

let valgt = startOfDay(new Date());
let state = null;

function startOfDay(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
function iso(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
function ukedag(d) { return (d.getDay() + 6) % 7; }
function erIdag() { return iso(valgt) === iso(new Date()); }
function klokke(d) { return d.toLocaleTimeString('no-NO', { hour: '2-digit', minute: '2-digit' }); }
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]); }
function barn(id) { return state.kids.find(k => k.id === id); }
function farge(owner) { return owner === 'felles' ? FELLES_FARGE : barn(owner)?.color; }

async function hent() {
  const r = await fetch(`/api/state?date=${iso(valgt)}&today=${iso(new Date())}`, { cache: 'no-store' });
  if (r.status === 401) return location.reload();
  state = await r.json();
  tegn();
}

async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.json();
}

function gjelderIdag(t) { return !t.days.length || t.days.includes(ukedag(valgt)); }

function tegn() {
  const dag = ukedag(valgt);
  const meg = state.me === 'foreldre' ? 'mamma/pappa' : barn(state.me)?.name;
  $('meg').textContent = meg ? `Logget inn som ${meg}` : '';
  $('ukedag').textContent = erIdag() ? `I dag – ${DAGER[dag]}` : DAGER[dag][0].toUpperCase() + DAGER[dag].slice(1);
  $('datotekst').textContent = valgt.toLocaleDateString('no-NO', { day: 'numeric', month: 'long', year: 'numeric' });
  $('idag').hidden = erIdag();
  $('dagnavn').textContent = DAGER[dag];
  $('kal-overskrift').textContent = erIdag() ? 'Dette skjer i dag' : `Dette skjer ${DAGER[dag]}`;

  const md = iso(valgt).slice(5);
  const bursdagsbarn = state.kids.filter(k => k.birthday === md);
  $('bursdag').hidden = !bursdagsbarn.length;
  $('bursdag').textContent = bursdagsbarn.map(k => `🎂 Gratulerer med ${valgt.getFullYear() - k.born}-årsdagen, ${k.name}! 🎉`).join(' ');

  tegnKalender();
  tegnBarn();
  tegnBunn();
}

function tegnKalender() {
  const fra = valgt, til = new Date(valgt.getTime() + 864e5);
  const navnFor = cal => state.kids.find(k => k.cal === cal);
  const ev = state.events
    .map(e => ({ ...e, s: new Date(e.start), e: new Date(e.end) }))
    .filter(e => e.s < til && e.e > fra)
    .sort((a, b) => a.s - b.s);

  const heldag = ev.filter(e => e.allDay);
  $('heldag').innerHTML = heldag.map(e => {
    const k = navnFor(e.cal);
    return `<span style="background:${k ? k.color : FELLES_FARGE}">${esc(e.title)}${k ? ' · ' + esc(k.name) : ''}</span>`;
  }).join('');

  const naa = new Date();
  const timer = ev.filter(e => !e.allDay);
  $('avtaler').innerHTML = timer.length ? timer.map(e => {
    const k = navnFor(e.cal);
    const c = k ? k.color : FELLES_FARGE;
    const kl = e.s < fra ? 'før' : klokke(e.s);
    const status = e.e < naa ? 'ferdig' : (e.s <= naa ? 'naa' : '');
    return `<li class="avtale ${status}" style="--farge:${c}">
      <span class="tid">${kl}<br><span class="liten">${e.e > til ? '' : '–' + klokke(e.e)}</span></span>
      <span><span class="hva">${esc(e.title)}</span><span class="hvem">${k ? esc(k.name) : 'Alle'}</span>
      ${e.location ? `<span class="sted">📍 ${esc(e.location.split('\n')[0])}</span>` : ''}</span></li>`;
  }).join('') : (heldag.length ? '' : '<li class="tomt">Ingen avtaler i kalenderen 🌿</li>');

  if (state.calendarUpdated) {
    const min = Math.round((Date.now() - new Date(state.calendarUpdated)) / 60000);
    $('kal-oppdatert').textContent = min < 2 ? 'oppdatert nå' : min < 120 ? `oppdatert for ${min} min siden` : `oppdatert ${new Date(state.calendarUpdated).toLocaleString('no-NO', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}`;
  } else {
    $('kal-oppdatert').textContent = 'venter på kalender';
  }
}

function oppgaveKnapp(t, merke) {
  const gjort = state.done[t.id];
  const tok = gjort && gjort.by ? barn(gjort.by) : null;
  const c = tok ? tok.color : farge(t.owner);
  let m = '';
  if (tok && t.owner === 'felles') m = `<span class="merke" style="--farge:${tok.color}">✓ ${esc(tok.name)}</span>`;
  else if (merke) m = `<span class="merke" style="--farge:${c}">${esc(merke)}</span>`;
  return `<li><button class="oppgave ${gjort ? 'gjort' : ''}" style="--farge:${c}" data-id="${t.id}" aria-pressed="${!!gjort}">
    <span class="boks">${gjort ? '✓' : ''}</span>
    <span class="emoji">${esc(t.emoji)}</span>
    <span class="tittel">${esc(t.title)}</span>${m}</button></li>`;
}

function tegnBarn() {
  $('barn').innerHTML = state.kids.map(k => {
    const egne = state.tasks.filter(t => t.owner === k.id && !t.days.length);
    const alle = state.tasks.filter(t => t.owner === k.id && gjelderIdag(t));
    const ferdige = alle.filter(t => state.done[t.id]).length;
    const borte = state.away.includes(k.id);
    const altFerdig = alle.length && ferdige === alle.length;
    return `<section class="kort kolonne ${borte ? 'borte' : ''} ${altFerdig && !borte ? 'alt-ferdig' : ''}" style="--farge:${k.color}">
      <div class="kolonne-hode"><span class="navn">${esc(k.name)}</span>
        <button class="borte-knapp" data-borte="${k.id}">${borte ? 'Hjemme likevel' : 'Ikke hjemme'}</button></div>
      <div class="fremdrift"><div style="width:${alle.length ? 100 * ferdige / alle.length : 0}%"></div></div>
      <div class="teller">${altFerdig ? 'Alt er gjort!' : `${ferdige} av ${alle.length} gjort`}</div>
      <div class="borte-tekst">Ikke hjemme ${erIdag() ? 'i dag' : 'denne dagen'} 👋${state.awayReason?.[k.id] ? `<br><span class="liten">${esc(state.awayReason[k.id])}</span>` : ''}</div>
      <ul class="liste">${egne.map(t => oppgaveKnapp(t)).join('')}</ul>
      ${alle.length > egne.length ? `<div class="teller" style="margin:10px 0 0">+ ${alle.length - egne.length} i «Bare i dag» nederst</div>` : ''}
      <div class="ferdig-melding">Bra jobba, ${esc(k.name)}! ⭐</div>
    </section>`;
  }).join('');
}

function tegnBunn() {
  const felles = state.tasks.filter(t => t.owner === 'felles' && !t.days.length);
  const dagens = state.tasks.filter(t => t.days.length && t.days.includes(ukedag(valgt)) && !state.away.includes(t.owner));
  $('felles').innerHTML = felles.map(t => oppgaveKnapp(t)).join('') || '<li class="tomt">Ingen felles oppgaver</li>';
  $('dagens').innerHTML = dagens.map(t => oppgaveKnapp(t, t.owner === 'felles' ? 'Hvem som helst' : barn(t.owner)?.name)).join('') || '<li class="tomt">Ingenting ekstra i dag 😎</li>';
  const teller = l => `${l.filter(t => state.done[t.id]).length} av ${l.length}`;
  $('felles-teller').textContent = felles.length ? teller(felles) : '';
  $('dag-teller').textContent = dagens.length ? teller(dagens) : '';
}

async function trykk(id) {
  const t = state.tasks.find(x => x.id === id);
  if (!t) return;
  const meg = state.kids.some(k => k.id === state.me) ? state.me : null;
  if (!state.done[id] && t.owner === 'felles' && meg) return lokal(id, meg);
  if (state.done[id] || t.owner !== 'felles') {
    lokal(id, t.owner === 'felles' ? null : t.owner);
    return;
  }
  velgHvem(t);
}

async function lokal(id, by) {
  if (state.done[id]) delete state.done[id]; else state.done[id] = { by };
  tegn();
  const r = await post('/api/toggle', { date: iso(valgt), taskId: id, by });
  state.done = r.done;
  tegn();
}

function velgHvem(t) {
  $('velger-oppgave').textContent = `${t.emoji} ${t.title}`;
  $('velger-knapper').innerHTML = state.kids.filter(k => !state.away.includes(k.id))
    .map(k => `<button style="--farge:${k.color}" data-hvem="${k.id}">${esc(k.name)}</button>`).join('');
  $('velger').hidden = false;
  $('velger').dataset.id = t.id;
}

document.addEventListener('click', async e => {
  const o = e.target.closest('.oppgave');
  if (o) return trykk(o.dataset.id);
  const b = e.target.closest('[data-borte]');
  if (b) {
    const r = await post('/api/away', { date: iso(valgt), kid: b.dataset.borte });
    state.away = r.away; state.awayReason = r.awayReason; return tegn();
  }
  const h = e.target.closest('[data-hvem]');
  if (h) { $('velger').hidden = true; return lokal($('velger').dataset.id, h.dataset.hvem); }
  if (e.target.id === 'velger' || e.target.id === 'velger-avbryt') $('velger').hidden = true;
});

// ---------- Vær fra Yr ----------
const IKON = s => `https://cdn.jsdelivr.net/gh/metno/weathericons@main/weather/svg/${s}.svg`;
function vaerTekst(sym = '') {
  const s = sym.replace(/_(day|night|polartwilight)$/, '');
  const t = { clearsky: 'Klarvær', fair: 'Lettskyet', partlycloudy: 'Delvis skyet', cloudy: 'Skyet', fog: 'Tåke',
    lightrain: 'Lett regn', rain: 'Regn', heavyrain: 'Kraftig regn', lightrainshowers: 'Lette regnbyger',
    rainshowers: 'Regnbyger', heavyrainshowers: 'Kraftige regnbyger' }[s];
  if (t) return t;
  if (s.includes('thunder')) return 'Torden';
  if (s.includes('snow')) return 'Snø';
  if (s.includes('sleet')) return 'Sludd';
  return 'Regn';
}
const tempKlasse = t => t <= 0 ? 'kald' : t >= 20 ? 'varm' : '';
const grad = t => `${Math.round(t)}°`;

async function hentVaer() {
  try {
    const r = await fetch('/api/weather', { cache: 'no-store' });
    if (!r.ok) return;
    const { series = [] } = await r.json();
    tegnVaer(series.map(x => ({ ...x, d: new Date(x.t) })));
  } catch (e) { /* prøver igjen senere */ }
}

function tegnVaer(s) {
  const naa = Date.now();
  const kommende = s.filter(x => x.d.getTime() > naa - 36e5);
  if (!kommende.length) return;
  const n = kommende[0];
  $('vaer-naa').innerHTML = `${n.sym ? `<img src="${IKON(n.sym)}" alt="">` : ''}
    <div><div class="grader ${tempKlasse(n.temp)}">${grad(n.temp)}</div>
    <div class="vaer-detalj">${vaerTekst(n.sym)} · vind ${Math.round(n.wind)} m/s</div></div>`;

  // Resten av dagen (til kl. 22) – grunnlag for tips til barna
  const kveld = new Date(); kveld.setHours(22, 0, 0, 0);
  const iDag = kommende.filter(x => x.d <= kveld && x.h === 1);
  const regn = iDag.reduce((a, x) => a + (x.pr || 0), 0);
  const min = Math.min(...iDag.map(x => x.temp), n.temp), maks = Math.max(...iDag.map(x => x.temp), n.temp);
  const vind = Math.max(...iDag.map(x => x.wind), n.wind);
  const tips = [];
  if (iDag.some(x => (x.sym || '').includes('snow'))) tips.push('⛄ Snø i dag – vinterklær på!');
  else if (regn >= 1) tips.push('☔ Regn i dag – ta med regnjakke');
  else if (regn > 0.2) tips.push('🌂 Kan komme litt regn');
  if (min < 0) tips.push('🧤 Kaldt – lue og votter');
  else if (min < 8) tips.push('🧥 Kjølig – ta på jakke');
  if (vind >= 10) tips.push('💨 Mye vind i dag');
  if (maks >= 22 && regn < 0.2) tips.push('😎 Varmt – husk vannflaske');
  $('vaer-tips').hidden = !tips.length;
  $('vaer-tips').textContent = tips.slice(0, 2).join('  ·  ');

  $('vaer-timer').innerHTML = kommende.filter(x => x.h === 1).slice(1, 13).map(x => `<li>
    <div class="kl">${String(x.d.getHours()).padStart(2, '0')}</div>
    ${x.sym ? `<img src="${IKON(x.sym)}" alt="${vaerTekst(x.sym)}">` : ''}
    <div class="${tempKlasse(x.temp)}">${grad(x.temp)}</div>
    <div class="regn">${x.pr ? x.pr.toFixed(1) : ''}</div></li>`).join('');

  const dager = [];
  for (let i = 0; i < 3; i++) {
    const fra = startOfDay(new Date(naa + i * 864e5)), til = new Date(fra.getTime() + 864e5);
    const del = s.filter(x => x.d >= fra && x.d < til);
    if (!del.length) continue;
    const midt = del.reduce((a, x) => Math.abs(x.d.getHours() - 13) < Math.abs(a.d.getHours() - 13) ? x : a);
    dager.push({
      navn: i === 0 ? 'I dag' : i === 1 ? 'I morgen' : DAGER[ukedag(fra)].replace(/^./, c => c.toUpperCase()),
      sym: midt.sym, min: Math.min(...del.map(x => x.temp)), maks: Math.max(...del.map(x => x.temp)),
      pr: del.reduce((a, x) => a + (x.pr || 0), 0),
    });
  }
  $('vaer-dager').innerHTML = dager.map(d => `<li><span>${d.navn}</span>
    ${d.sym ? `<img src="${IKON(d.sym)}" alt="${vaerTekst(d.sym)}">` : '<span></span>'}
    <span><span class="${tempKlasse(d.maks)}">${grad(d.maks)}</span> / <span class="${tempKlasse(d.min)}">${grad(d.min)}</span></span>
    <span class="mm">${d.pr >= 0.1 ? d.pr.toFixed(1) + ' mm' : ''}</span></li>`).join('');
}
hentVaer();
setInterval(hentVaer, 15 * 60000);

function flytt(n) { valgt = startOfDay(new Date(valgt.getTime() + n * 864e5 + 36e5 * 3)); hent(); }
$('loggut').onclick = async e => {
  e.preventDefault();
  await fetch('/api/logout', { method: 'POST' });
  location.reload();
};
$('forrige').onclick = () => flytt(-1);
$('neste').onclick = () => flytt(1);
$('idag').onclick = () => { valgt = startOfDay(new Date()); hent(); };

// Hold flere skjermer i sync, og bytt til ny dag etter midnatt.
let sistIdag = iso(new Date());
setInterval(() => {
  const naa = iso(new Date());
  if (naa !== sistIdag) { if (iso(valgt) === sistIdag) valgt = startOfDay(new Date()); sistIdag = naa; }
  if ($('velger').hidden) hent();
}, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) hent(); });

hent();
