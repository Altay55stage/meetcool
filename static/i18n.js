/* Local dictionaries only: no translation service receives meeting or location data. */
(() => {
  const supported = ['fr', 'en'];
  let saved;
  try { saved = localStorage.getItem('meetcool_language'); } catch {}
  const requested = new URLSearchParams(location.search).get('lang');
  let language = supported.includes(requested) ? requested : supported.includes(saved) ? saved : 'fr';
  const originals = new WeakMap();
  const attributes = new WeakMap();
  const patterns = [
    [/^(\d+) lieux comparés$/, '$1 places compared'],
    [/^Calculé pour (\d+) participants? ayant accepté\.$/, 'Calculated for $1 accepted participants.'],
    [/^(\d+) participants? ayant accepté$/, '$1 accepted participants'],
    [/^Écart (.+) min · (.+)$/, 'Difference $1 min · $2'],
    [/^Durée : (.+)$/, 'Duration: $1'],
    [/^Heure locale : (.+)$/, 'Local time: $1'],
    [/^Départ prévu : (.+)$/, 'Planned departure: $1'],
    [/^(\d+) minutes · heure affichée dans ton fuseau$/, '$1 minutes · shown in your time zone'],
    [/^(.+), choisis ton départ pour (.+)\.$/, '$1, choose your departure for $2.'],
    [/^Ton départ est enregistré pour « (.+) »\.$/, 'Your departure has been saved for “$1”.'],
    [/^Distances depuis A : (.+)$/, 'Distances from A: $1'],
    [/^(.+) · coût (.+)$/, '$1 · cost $2'],
    [/^(\d+) e-mails? envoyés?$/, '$1 emails sent'],
    [/^(\d+) en cours d’envoi$/, '$1 sending'],
    [/^(\d+) échecs? d’envoi$/, '$1 delivery failures'],
    [/^(\d+) éléments cartographiés dans un rayon de 1,5 km\. Feux : positions uniquement, sans état ni durée en direct\.$/, '$1 mapped features within 1.5 km. Traffic lights: locations only, no live status or timing.'],
  ];
  function english(source) {
    if (Object.hasOwn(window.MEETCOOL_EN, source)) return window.MEETCOOL_EN[source];
    for (const [expression, replacement] of patterns) if (expression.test(source)) {
      return source.replace(expression, replacement).replace('Point indicatif', 'Indicative point').replace('Votre lieu', 'Your place');
    }
    return source;
  }
  function translate(value) {
    if (language !== 'en' || !value) return value;
    const trimmed = value.trim();
    return value.replace(trimmed, english(trimmed));
  }
  function translateText(node) {
    if (node.parentElement?.closest('script,style,[data-no-translate],.leaflet-control-attribution')) return;
    const record = originals.get(node);
    const source = record && node.nodeValue === record.rendered ? record.source : node.nodeValue;
    const rendered = translate(source);
    originals.set(node, {source, rendered});
    if (node.nodeValue !== rendered) node.nodeValue = rendered;
  }
  function translateElement(element) {
    if (element.closest('[data-no-translate]')) return;
    let records = attributes.get(element);
    if (!records) { records = {}; attributes.set(element, records); }
    for (const name of ['placeholder', 'title', 'aria-label', 'alt']) {
      if (!element.hasAttribute(name)) continue;
      const current = element.getAttribute(name), previous = records[name];
      const source = previous && current === previous.rendered ? previous.source : current;
      const rendered = translate(source);
      records[name] = {source, rendered};
      if (current !== rendered) element.setAttribute(name, rendered);
    }
  }
  function walk(root) {
    if (root.nodeType === Node.TEXT_NODE) { translateText(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    translateElement(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      if (walker.currentNode.nodeType === Node.TEXT_NODE) translateText(walker.currentNode);
      else translateElement(walker.currentNode);
    }
  }
  const observer = new MutationObserver(records => {
    observer.disconnect();
    for (const record of records) {
      if (record.type === 'childList') record.addedNodes.forEach(walk);
      else if (record.type === 'characterData') translateText(record.target);
      else translateElement(record.target);
    }
    observe();
  });
  function observe() {
    observer.observe(document.body, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['placeholder','title','aria-label','alt']});
  }
  function setLanguage(next, notify = true) {
    if (!supported.includes(next)) return;
    language = next;
    try { localStorage.setItem('meetcool_language', next); } catch {}
    document.documentElement.lang = next;
    document.title = next === 'en' ? 'meet’cool — Where shall we meet?' : 'meet’cool — On se retrouve où ?';
    document.querySelectorAll('[data-language]').forEach(select => { select.value = next; });
    observer.disconnect();
    walk(document.body);
    observe();
    if (notify) document.dispatchEvent(new CustomEvent('language:change', {detail:{language:next}}));
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  }
  window.meetcoolI18n = {
    get language() { return language; },
    get locale() { return language === 'en' ? 'en-GB' : 'fr-FR'; },
    text: (fr, en) => language === 'en' ? en : fr,
    translate,
    setLanguage,
  };
  document.querySelectorAll('[data-language]').forEach(select => select.addEventListener('change', () => setLanguage(select.value)));
  setLanguage(language, false);
})();
