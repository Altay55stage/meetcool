// Run against a local server. API calls are mocked: no invitations or e-mails are sent.
// MEETCOOL_TOOLKIT_PACKAGE can point at a package.json providing Playwright.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir} from 'node:fs/promises';
const require = createRequire(process.env.MEETCOOL_TOOLKIT_PACKAGE || import.meta.url);
const {chromium} = require('playwright');
const base = process.env.MEETCOOL_TEST_URL || 'http://127.0.0.1:8011';
const artifacts = process.env.MEETCOOL_TEST_ARTIFACTS || '/tmp/meetcool-ui-check';
await mkdir(artifacts, {recursive:true});
const browser = await chromium.launch({headless:true});
try {
 for (const language of ['fr','en']) {
 const page = await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 await page.addInitScript(language=>localStorage.setItem('meetcool_language',language),language);
 const errors = [];
 page.on('pageerror', e => errors.push(e.message));
 const meeting = {id:'test-invite',name:'Un café ensemble',date:'2026-12-01T17:00:00Z',duration:60,status:'collecting',objective:'earliest',venues:[]};
 const people = [];
 const venues = [{id:'a',name:'Point A',lat:48.86,lng:2.35,description:'Point indicatif'},{id:'b',name:'Point B',lat:48.87,lng:2.36,description:'Point indicatif'}];
 await page.route('**/api/**', async route => {
  const req=route.request(),url=new URL(req.url()),path=url.pathname;
  let data;
  if(path==='/api/config') data={storage:'appwrite',shared:true,email:{configured:true}};
  else if(path==='/api/meetings'&&req.method()==='POST') {Object.assign(meeting,req.postDataJSON(),{status:'collecting'});people.length=0;data={meeting,admin_token:'PRIVATE-TOKEN-DO-NOT-SHARE',email_status:'queued'};}
  else if(path.endsWith('/join')) {people.push({id:'guest',...req.postDataJSON(),status:'accepted'});data={email_status:'queued'};}
  else if(path.endsWith('/analysis')) data={participants:people,venues,matrix:[[10,22]],ranking:venues.map((v,i)=>({...v,times:[10+i*12],spread:0,total:10+i*12,max:10+i*12})),routing:'estimated'};
  else if(path.endsWith('/admin')) {if(req.method()==='PATCH')Object.assign(meeting,req.postDataJSON());data={meeting,participants:people,email_summary:{queued:1}};}
  else if(path==='/api/meetings/test-invite')data={meeting,participants:[]};
  else if(path==='/api/geocode')data={results:[{name:'Paris, France',lat:48.85,lng:2.34}]};
  else if(path==='/api/routes')data={routes:[]};
  else return route.continue();
  await route.fulfill({json:data});
 });
 await page.goto(base);
 assert.equal(await page.locator('html').getAttribute('lang'),language);
 assert.equal(await page.locator('#zoneTitle').textContent(),language==='en'?'When shall we meet?':'On se voit quand ?');
 await page.locator('[data-language]').first().selectOption(language==='en'?'fr':'en');
 assert.equal(await page.locator('html').getAttribute('lang'),language==='en'?'fr':'en');
 await page.locator('[data-language]').first().selectOption(language);
 await page.locator('[data-open-planner="create"]').first().click();
 await page.locator('#meetingName').fill(meeting.name);
 await page.locator('#meetingDate').fill('2026-12-01T18:00');
 assert.equal(await page.locator('.meeting-options').getAttribute('open'),null);
 assert.equal(await page.locator('#map').getAttribute('inert'),'');
 assert.equal(await page.locator('.skip-link').getAttribute('href'),'#zoneTitle');
 await page.locator('#createMeetingSubmit').click();
 await page.waitForFunction(()=>document.querySelector('#planner').dataset.stage==='1');
 const whatsapp = new URL(await page.locator('#whatsappInvite').getAttribute('href'));
 assert.equal(whatsapp.hostname,'wa.me');
 assert.ok(whatsapp.searchParams.get('text').includes('/?join=test-invite'));
 assert.ok(!whatsapp.href.includes('PRIVATE-TOKEN'));
 const email = await page.locator('#emailInvite').getAttribute('href');
 assert.ok(decodeURIComponent(email).includes('Un café ensemble'));
 assert.ok(!email.includes('PRIVATE-TOKEN'));
 assert.ok((await page.locator('#organizerLink').inputValue()).includes('PRIVATE-TOKEN'));
 assert.equal(await page.locator('.organizer-access').getAttribute('open'),null);
 assert.equal(await page.locator('#calculateMeeting').isDisabled(),true);
 await page.screenshot({path:artifacts+`/invite-desktop-${language}.png`});
 await page.locator('#ownerJoin').click();
 await page.locator('#guestName').fill('Camille');
 await page.evaluate(()=>window.meetcoolI18n.setLanguage(document.documentElement.lang==='en'?'fr':'en'));
 assert.equal(await page.locator('#guestName').inputValue(),'Camille');
 await page.evaluate(language=>window.meetcoolI18n.setLanguage(language),language);
 await page.locator('#acceptInvitation button[type=submit]').click();
 await page.locator('#addressQuery').fill('Paris');
 await page.locator('#addressSearch').click();
 await page.getByRole('button',{name:'Paris, France',exact:true}).click();
 await page.locator('#joinSubmit').click();
 await page.locator('#guestClose').click();
 await page.waitForFunction(()=>!document.querySelector('#calculateMeeting').disabled);
 await page.locator('#calculateMeeting').click();
 await page.locator('[data-venue="a"]').waitFor();
 assert.equal(await page.locator('#map').getAttribute('inert'),null);
 assert.equal(await page.locator('.skip-link').getAttribute('href'),'#map');
 assert.ok((await page.locator('#destinationActions a').first().getAttribute('href')).startsWith('https://www.google.com/maps/'));
 await page.locator('.result-explanation summary').click();
 await page.locator('#resultLab').click();
 assert.equal(await page.locator('#labView').isVisible(),true);
 assert.ok((await page.locator('.algorithm-limits').innerText()).includes(language==='en'?'exhaustive comparison':'comparaison exhaustive'));
 await page.locator('.lab-technical summary').click();
 assert.equal(await page.locator('#dijkstraResult').isVisible(),true);
 await page.screenshot({path:artifacts+`/algorithm-desktop-${language}.png`});
 await page.locator('#backFromLab').click();
 await page.locator('#confirmPlan').click();
 await page.waitForFunction(language=>document.querySelector('#confirmationNote').textContent.includes(language==='en'?'Confirmed.':'C’est confirmé.'),language);
 await page.setViewportSize({width:390,height:844});
 await page.locator('#createBtn').click();
 assert.equal(await page.locator('.map-side').isVisible(),false);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.locator('#meetingName').fill('Nouveau moment');
 await page.locator('#meetingDate').fill('2026-12-03T18:00');
 await page.locator('#createMeetingSubmit').click();
 await page.waitForFunction(()=>document.querySelector('#planner').dataset.stage==='1');
 await page.screenshot({path:artifacts+`/invite-mobile-${language}.png`});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 assert.deepEqual(errors,[]);
 console.log(language.toUpperCase(), 'PASS: create → share public links → accept → choose departure → calculate → explain → confirm; mobile fits. No e-mails sent.');
 console.log('Screenshots:',artifacts);
 await page.close();
 }
} finally {await browser.close();}
