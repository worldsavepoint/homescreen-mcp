"""Browser behavior with a synthetic DOM and intercepted device routes; Node only."""
import json
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "homescreen/web"


class Nodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "parent": self.stack[-1] if self.stack else None}
        self.nodes.append(node)
        if tag not in {"meta", "link", "input", "img", "br", "hr"}:
            self.stack.append(len(self.nodes) - 1)

    def handle_endtag(self, tag):
        for pos in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[pos]]["tag"] == tag:
                self.stack = self.stack[:pos]
                break

    def handle_data(self, data):
        if self.stack:
            node = self.nodes[self.stack[-1]]
            node["text"] = node.get("text", "") + data


HARNESS = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const harnessInput = JSON.parse(fs.readFileSync(0,'utf8'));
class Element {
 constructor(tag, attrs={}) {this.tagName=tag;this.attrs={...attrs};this.children=[];this.events={};this.style={setProperty(){}};
 this.dataset={}; for(const [k,v] of Object.entries(attrs))if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;
 this.hidden='hidden' in attrs;this.disabled='disabled' in attrs;this.checked='checked' in attrs;this.value=attrs.value||'';this._text='';
 this._scrollHeight=1000;this._clientHeight=200;this.scrollTop=0;
 const classes = new Set((attrs.class||'').split(' '));this.classList={add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),contains:x=>classes.has(x),toggle:(x,b)=>{b??=!classes.has(x);b?classes.add(x):classes.delete(x);}};
 }
 get layoutHidden(){for(let n=this;n;n=n.parent)if(n.hidden)return true;return false;}
 get scrollHeight(){return this.layoutHidden?0:this._scrollHeight;}set scrollHeight(v){this._scrollHeight=v;}
 get clientHeight(){return this.layoutHidden?0:this._clientHeight;}set clientHeight(v){this._clientHeight=v;}
 set className(v){this.attrs.class=v;}get className(){return this.attrs.class||'';}
 set textContent(v){this._text=String(v);this.children=[];}get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
 get id(){return this.attrs.id||'';}set id(v){this.attrs.id=v;}
 getAttribute(k){if(k.startsWith('data-'))return this.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]??null;return this.attrs[k]??null;}removeAttribute(k){delete this.attrs[k];if(k.startsWith('data-'))delete this.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())];}
 setAttribute(k,v){this.attrs[k]=String(v);if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=String(v);}
 append(...xs){for(let x of xs){if(typeof x==='string')x=new Element('#text',{value:x});x.parent=this;this.children.push(x);}}
 appendChild(x){this.append(x);return x;}replaceChildren(...xs){this.children=[];this._text='';this.append(...xs);}
 get lastChild(){return this.children.at(-1);}get firstChild(){return this.children[0];}
 remove(){this.parent.children=this.parent.children.filter(n=>n!==this);}
 matches(selector){return selector.split(',').some(s=>{s=s.trim();if(s.includes(' '))return false;
 const attr=s.match(/\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]/);
 if(attr && (this.getAttribute(attr[1])===null || (attr[2]&&this.getAttribute(attr[1])!==attr[2])))return false;
 s=s.replace(/\[[^\]]+\]/g,'');const id=s.match(/#([\w-]+)/);if(id&&this.attrs.id!==id[1])return false;
 const cl=s.match(/\.([\w-]+)/);if(cl&&!this.classList.contains(cl[1])&&!this.className.split(' ').includes(cl[1]))return false;
 const tag=s.match(/^[\w-]+/);return !tag||this.tagName===tag[0];});}
 querySelectorAll(s){const out=[];const parts=s.trim().split(/\s+/);for(const c of this.children){if(c.matches(parts.at(-1))&&(parts.length===1||c.parent?.closest(parts.slice(0,-1).join(' '))))out.push(c);out.push(...c.querySelectorAll(s));}return out;}
 cloneNode(deep){const n=new Element(this.tagName,this.attrs);if(deep)for(const c of this.children)n.append(c.cloneNode(true));return n;}
 querySelector(s){return this.querySelectorAll(s)[0]||null;}
 closest(s){return this.matches(s)?this:this.parent?.closest(s);}contains(n){return n===this||this.children.some(c=>c.contains(n));}
 addEventListener(k,f){(this.events[k]??=[]).push(f);}removeEventListener(k,f){this.events[k]=(this.events[k]||[]).filter(x=>x!==f);}
 dispatchEvent(e){e.target??=this;e.stopPropagation??=()=>{};e.preventDefault??=()=>{e.defaultPrevented=true;};this['on'+e.type]?.(e);for(const f of this.events[e.type]||[])f(e);return true;}
 click(){if(!this.disabled)this.dispatchEvent({type:'click'});}focus(){document.activeElement=this;}select(){}blur(){document.activeElement=null;}
}
const document = new Element('document');document.createElement=t=>new Element(t);document.createTextNode=t=>{const n=new Element('#text');n.textContent=t;return n;};
const nodes=harnessInput.nodes.map(n=>new Element(n.tag,n.attrs));nodes.forEach((n,i)=>{n._text=harnessInput.nodes[i].text||'';(harnessInput.nodes[i].parent==null?document:nodes[harnessInput.nodes[i].parent]).append(n);});
document.documentElement=nodes.find(n=>n.tagName==='html');document.body=nodes.find(n=>n.tagName==='body');
const calls=[], stored=new Map(), bridge=[], copied=[], unhandled=[];
process.on('unhandledRejection',error=>unhandled.push(error.message));
const item={id:'synthetic.app',kind:'app',name:'Synthetic Notes',slots:1};
const fixture={loaded:true,read_only:true,source:'phone',device:{DeviceName:'Synthetic iPhone',ProductVersion:'18.0',ProductType:'iPhone'},
 dock:[],pages:[[{id:'synthetic.folder',kind:'folder',name:'My Folder',pos:[0,0,1,1],pages:[[item]]}]],library:[],bank:[],moved:['synthetic.app'],history:{undo:true,redo:false},
 grid:{cols:4,rows:6,dock:4,folder:9},slots:{page:24},diff:{items_moved:1,pages_before:1,pages_after:1,gaps_changed:0,to_app_library:0,problems:[]},moves:{},usage:null};
const context={document,console,URL,URLSearchParams,Intl,Date,Set,Map,Promise,setTimeout:()=>0,clearTimeout(){},requestAnimationFrame:f=>f(),
 location:{hash:'',pathname:'/',search:''},history:{replaceState(){}},navigator:{languages:['en'],clipboard:{writeText:async t=>copied.push(t)}},
 localStorage:{getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v)},Image:class extends Element{constructor(){super('img');}},
 Event:class{constructor(type){this.type=type;}},CustomEvent:class{constructor(type){this.type=type;}},
 addEventListener:(...a)=>document.addEventListener(...a),dispatchEvent:e=>document.dispatchEvent(e),close:()=>{context.closed=true;},
 fetch:async path=>{calls.push(String(path));if(String(path).includes('/locales/'))return {ok:true,json:async()=>harnessInput.catalogs[String(path).split('/').pop()]};
 if(path==='/api/state')return {ok:true,json:async()=>fixture};if(path==='/api/devices')return {ok:true,json:async()=>({switching:false,current:null,devices:[]})};
 if(path==='/api/read')return {ok:true,json:async()=>fixture};throw Error('Unexpected route '+path);}
};context.window=context;context.globalThis=context;
if(harnessInput.native) {context.screenOrganizerHost={native:true,languagePreference:'de',consentAccepted:true};context.webkit={messageHandlers:{screenOrganizer:{postMessage:m=>bridge.push(m)}}};}
eval(harnessInput.setup || '');
vm.createContext(context);
for(const script of harnessInput.scripts)vm.runInContext(script,context);
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{await eval('(async()=>{'+(harnessInput.before_ready || '')+'})()');await context.ScreenOrganizerI18n.ready;await tick();await tick();
const $=s=>document.querySelector(s);const i18n=context.ScreenOrganizerI18n;
''' 


def browser(body, native=False, setup="", before_ready=""):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    parser = Nodes()
    parser.feed((WEB / "index.html").read_text())
    catalogs = {p.name: json.loads(p.read_text()) for p in (WEB / "locales").glob("*.json")}
    scripts = [(WEB / name).read_text() for name in ("i18n.js", "onboarding.js", "app.js") if (WEB / name).exists()]
    result = subprocess.run([node, "-e", HARNESS + body + "\nassert.deepEqual(unhandled, []);console.log(\"browser assertions complete\");})().catch(e=>{console.error(e);process.exitCode=1;});"],
        input=json.dumps({"nodes": parser.nodes, "scripts": scripts, "catalogs": catalogs, "native": native, "setup": setup, "before_ready": before_ready}),
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "browser assertions complete", "Browser assertions did not finish"


def test_standalone_consent_blocks_routes_until_read_and_agreed():
    browser('''
assert.equal(calls.filter(p=>p.startsWith('/api/')).length,0,'device routes must wait for consent');
assert.equal($('#consent-dialog').hidden,false);
assert.equal($('#consent-continue').disabled,true);
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
assert.equal($('#consent-continue').disabled,true,'checkbox alone cannot pass');
const terms=$('#consent-text');terms.scrollTop=800;terms.dispatchEvent({type:'scroll'});
assert.equal($('#consent-continue').disabled,false);
let accepted=0;document.addEventListener('screen-organizer-consent-accepted',()=>accepted++);
$('#consent-continue').click();await tick();await tick();
assert.equal(accepted,1);assert.equal($('#consent-dialog').hidden,true);
assert.ok(calls.includes('/api/state'));assert.ok(calls.includes('/api/devices'));
''')


def test_decline_keeps_device_routes_blocked():
    browser('''
assert.ok($('#consent-decline'),'decline control is present');$('#consent-decline').click();await tick();
assert.equal(context.closed,true);assert.equal(calls.filter(p=>p.startsWith('/api/')).length,0);
''')


def test_native_language_switch_preserves_draft_search_folder_and_selection():
    browser('''
assert.equal(i18n.locale,'de');assert.equal($('#consent-dialog').hidden,true);
assert.equal($('#reset').textContent,'Zurücksetzen');
$('#pages').querySelector('[data-id="synthetic.folder"]').click();
$('#folder-pages').querySelector('[data-id="synthetic.app"]').click();
$('#search').value='Synthetic';$('#search').dispatchEvent({type:'input'});
const before=calls.length;const draft=vm.runInContext('V',context);
$('#language-select').value='fr';$('#language-select').dispatchEvent({type:'change'});await tick();await tick();
assert.equal($('#reset').textContent,'Réinitialiser');
assert.equal($('#search').value,'Synthetic');assert.equal($('#folder-name').value,'My Folder');assert.equal($('#drawer').hidden,false);
assert.ok($('#folder-pages').querySelector('[data-id="synthetic.app"]').classList.contains('selected'));
assert.equal(vm.runInContext('V',context),draft);assert.equal(calls.length,before+1,'only the selected catalog is fetched');
assert.deepEqual(JSON.parse(JSON.stringify(bridge.at(-1))),{action:'setLanguage',preference:'fr'});
''', native=True)


def test_mcp_entry_uses_native_bridge_and_browser_copyable_setup():
    browser('''
assert.ok($('#mcp-setup'),'toolbar setup entry');$('#mcp-setup').click();
assert.deepEqual(JSON.parse(JSON.stringify(bridge.at(-1))),{action:'openMCPSetup'});
''', native=True)
    browser('''
const terms=$('#consent-text');terms.scrollTop=800;terms.dispatchEvent({type:'scroll'});
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});$('#consent-continue').click();await tick();
$('#mcp-setup').click();assert.equal($('#mcp-dialog').hidden,false);
assert.equal(document.activeElement.id,'mcp-title','setup opens at its instructions');
const text=$('#mcp-dialog').textContent;assert.ok(text.includes('home-screen-mcp'));assert.ok(text.includes('HOMESCREEN_READ_ONLY'));
$('#mcp-copy-json').click();await tick();
const config=JSON.parse(copied[0]);assert.equal(config.mcpServers['ios-homescreen-mcp'].command,'home-screen-mcp');
assert.equal(config.mcpServers['ios-homescreen-mcp'].env.HOMESCREEN_READ_ONLY,'1');
''')


def test_view_adds_name_safe_current_original_locations_and_validation(monkeypatch):
    from types import SimpleNamespace
    from homescreen.model import Layout
    import homescreen.ui as ui
    from fake_phone import app, folder

    name = 'page "dock" -> folder [1] \'quoted\''
    app_name = 'dock -> page [Synthetic]'
    lay = Layout([[], [folder(name, [app('synthetic.app', app_name)])]], library=[])
    old = lay.positions()['synthetic.app']
    lay.move('synthetic.app', 'bank')
    session = SimpleNamespace(layout=lay, source=SimpleNamespace(name='synthetic'), device_id=None,
                              info={}, usage=None, gaps_readable=False, history=lambda: {'undo': True, 'redo': False})
    monkeypatch.setattr(ui, 'session', lambda: session)
    result = ui.view()
    assert result['moves'] == lay.diff()['moves']
    assert result['diff']['problems'] == lay.validate()
    assert result['location_labels'][old] == {'kind': 'folder', 'name': name, 'page': 1, 'index': 1}
    assert result['location_labels']['App Bank'] == {'kind': 'bank'}
    detail = next(iter(result['move_details'].values()))
    assert detail == {'id': 'synthetic.app', 'name': app_name,
                      'from': {'kind': 'folder', 'name': name, 'page': 1, 'index': 1}, 'to': {'kind': 'bank'}}
    assert result['diff']['problem_details'][0] == {'key': 'validation.bank', 'params': {'count': 1}}


def test_view_validation_keeps_quoted_folder_names_as_parameters(monkeypatch):
    from types import SimpleNamespace
    from homescreen.model import Layout
    import homescreen.ui as ui
    from fake_phone import app, folder

    name = 'dock "page" \'folder\' -> [x]'
    apps = [app(f'synthetic.{i}', f'App {i}') for i in range(10)]
    raw_folder = folder(name, [])
    raw_folder['iconLists'] = [apps]
    lay = Layout([[], [raw_folder]], library=[])
    monkeypatch.setattr(ui, 'session', lambda: SimpleNamespace(layout=lay, source=SimpleNamespace(name='synthetic'),
        device_id=None, info={}, usage=None, gaps_readable=False, history=lambda: {}))
    result = ui.view()
    assert result['diff']['problem_details'] == [{'key': 'validation.folderCapacity',
        'params': {'name': name, 'page': 1, 'count': 10, 'capacity': 9}}]


def test_open_prompt_translates_without_changing_typed_folder_name():
    browser('''
$('#pages').querySelector('[data-id="synthetic.folder"]').click();
$('#folder-pages').querySelector('[data-id="synthetic.app"]').click();
$('#sel-folder').click();await tick();
const input=$('#modal-body').querySelector('input');input.value='dock -> page [My Name]';
await i18n.setLocale('fr');await tick();
assert.equal($('#modal-title').textContent,'Nouveau dossier');
assert.equal($('#modal-actions').firstChild.textContent,'Annuler');
assert.equal(input.value,'dock -> page [My Name]');assert.equal($('#modal').hidden,false);
''', native=True)


def test_usage_and_review_translate_structured_locations_and_validation():
    browser('''
fixture.read_only=false;fixture.diff.problems=['the App Bank still holds 1 item(s); place them or send them to the App Library'];
fixture.diff.problem_details=[{key:'validation.bank',params:{count:1}}];
const name='page "dock" -> folder [User]';
fixture.location_labels={'opaque location':{kind:'folder',name,page:2,index:3}};
fixture.move_details={'legacy move':{name,id:'synthetic.app',from:{kind:'page',page:1,index:1},to:{kind:'folder',name,page:2,index:3}}};
fixture.moves={'legacy move':'opaque legacy string'};
fixture.usage={ok:true,days:7,source:'mac',original:1234,now:1230,top:[{id:'synthetic.app',name:'Synthetic Notes',opens:1234,where:'opaque location'}]};
await i18n.setLocale('fr');await tick();
assert.ok($('#usage').textContent.includes('Dossier « '+name+' »'));
$('#review').click();await tick();
assert.ok($('#modal-body').textContent.includes('La réserve contient 1 éléments'));
assert.ok($('#modal-body').textContent.includes(name));assert.ok(!$('#modal-body').textContent.includes('opaque legacy string'));
''', native=True)


def test_known_errors_show_localized_state_and_expandable_original_diagnostic():
    browser('''
context.fetch=async path=>({ok:false,status:400,json:async()=>({error:"widgets can't go in the dock"})});
$('#undo').click();await tick();await tick();
assert.ok($('#toast').textContent.includes('Widgets können nicht im Dock platziert werden.'));
assert.ok($('#toast').querySelector('details'),'original diagnostic is expandable');
assert.ok($('#toast').querySelector('pre').textContent.includes("widgets can't go in the dock"));
''', native=True)


def test_setup_escape_preserves_editor_selection_and_open_folder():
    browser('''
// Browser setup uses the same escape path as a native host's web panel.
const terms=$('#consent-text');terms.scrollTop=800;terms.dispatchEvent({type:'scroll'});
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});$('#consent-continue').click();await tick();await tick();
$('#pages').querySelector('[data-id="synthetic.folder"]').click();
$('#folder-pages').querySelector('[data-id="synthetic.app"]').click();
$('#mcp-setup').click();document.dispatchEvent({type:'keydown',key:'Escape',target:$('#mcp-title')});
assert.equal($('#mcp-dialog').hidden,true);assert.equal($('#drawer').hidden,false);
assert.ok($('#folder-pages').querySelector('[data-id="synthetic.app"]').classList.contains('selected'));
''')


def test_widget_size_and_usage_recovery_instructions_use_selected_language():
    browser('''
fixture.pages[0].push({id:'synthetic.widget',kind:'widget',name:'My medium Widget',size:'medium',slots:8});
fixture.usage={ok:false,error:'No synced Screen Time data on this Mac. Turn on Screen Time > Share Across Devices on both the iPhone and the Mac (same Apple Account).'};
await i18n.setLocale('fr');await tick();
assert.ok($('#pages').querySelector('[data-id="synthetic.widget"]').textContent.includes('Moyen'));
assert.ok($('#pages').querySelector('[data-id="synthetic.widget"]').textContent.includes('My medium Widget'));
assert.ok($('#usage').textContent.includes('Activez Temps d’écran'));
''', native=True)


def test_language_change_requires_reading_translated_agreement():
    browser('''
const text=$('#consent-text');text.scrollTop=800;text.dispatchEvent({type:'scroll'});
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
assert.equal($('#consent-continue').disabled,false);
$('#consent-language-select').value='fr';$('#consent-language-select').dispatchEvent({type:'change'});await tick();await tick();
assert.equal($('#consent-continue').disabled,true);assert.equal(text.scrollTop,0);
assert.equal($('#consent-title').textContent,'Avant de commencer');
assert.equal(calls.filter(p=>p.startsWith('/api/')).length,0);
''')


def test_backup_dates_follow_locale_without_loading_a_new_view():
    browser('''
const originalFetch=context.fetch;
context.fetch=async path=>path==='/api/backups'?{ok:true,json:async()=>({backups:['20261113-162400-synthetic-phone.plist']})}:originalFetch(path);
$('#backups-btn').click();await tick();await tick();
assert.ok($('#modal-body').textContent.includes('13.11.2026'));
await i18n.setLocale('fr');await tick();
assert.ok($('#modal-body').textContent.includes('13/11/2026'));
assert.equal($('#modal-title').textContent,'Sauvegardes');
''', native=True)


def test_view_move_details_keep_original_and_renamed_folder_positions(monkeypatch):
    from types import SimpleNamespace
    from homescreen.model import Layout
    import homescreen.ui as ui
    from fake_phone import app, folder

    old_name = 'old page -> dock [folder]'
    new_name = 'new "folder" -> [page]'
    lay = Layout([[], [app('synthetic.a', 'page -> [A]'), folder(old_name, [app('synthetic.b', 'dock [B]')])],
                  [app('synthetic.c', 'folder C')]], library=[])
    folder_id = next(node.id for node in lay.pages[0] if node.kind == 'folder')
    old_b = lay.positions()['synthetic.b']
    lay.move('synthetic.a', f'{folder_id}:1')
    lay.move('synthetic.b', 'page:2')
    lay.rename_folder(folder_id, new_name)
    monkeypatch.setattr(ui, 'session', lambda: SimpleNamespace(layout=lay, source=SimpleNamespace(name='synthetic'),
        device_id=None, info={}, usage=None, gaps_readable=False, history=lambda: {}))
    result = ui.view()
    details = {detail['id']: detail for detail in result['move_details'].values()}
    assert details['synthetic.a']['name'] == 'page -> [A]'
    assert details['synthetic.a']['from'] == {'kind': 'page', 'page': 1, 'index': 1}
    assert details['synthetic.a']['to'] == {'kind': 'folder', 'name': new_name, 'page': 1, 'index': 1}
    assert details['synthetic.b']['from'] == {'kind': 'folder', 'name': old_name, 'page': 1, 'index': 1}
    assert details['synthetic.b']['to'] == {'kind': 'page', 'page': 2, 'index': 2}
    assert result['location_labels'][old_b]['name'] == old_name
    assert result['moves'] == lay.diff()['moves']


def test_pending_language_immediately_blocks_consent_until_new_terms_are_read():
    browser('''
const text=$('#consent-text');text.scrollTop=800;text.dispatchEvent({type:'scroll'});
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
assert.equal($('#consent-continue').disabled,false);
const originalFetch=context.fetch;let release;
context.fetch=path=>String(path).endsWith('/fr.json')?new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>harnessInput.catalogs['fr.json']});}):originalFetch(path);
const select=$('#consent-language-select');select.value='fr';const changing=select.onchange({target:select});
assert.equal($('#consent-continue').disabled,true,'language selection blocks consent synchronously');
$('#consent-continue').onclick();await tick();
text.scrollTop=800;text.dispatchEvent({type:'scroll'});$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
$('#consent-continue').onclick();await tick();
assert.equal(context.ScreenOrganizerOnboarding.accepted,false);assert.equal(calls.filter(p=>p.startsWith('/api/')).length,0);
text.scrollHeight=1200;release();await changing;await tick();
assert.equal($('#consent-title').textContent,'Avant de commencer');assert.equal($('#consent-agree').checked,false);
assert.equal(text.scrollTop,0);assert.equal($('#consent-continue').disabled,true);
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
assert.equal($('#consent-continue').disabled,true);
text.scrollTop=1000;text.dispatchEvent({type:'scroll'});$('#consent-continue').click();await tick();await tick();
assert.equal(context.ScreenOrganizerOnboarding.accepted,true);assert.ok(calls.includes('/api/devices'));
''')


@pytest.mark.parametrize("failure", ["network", "http"])
def test_failed_language_load_keeps_consent_blocked_until_fallback_terms_are_read(failure):
    browser('''
const text=$('#consent-text');text.scrollTop=800;text.dispatchEvent({type:'scroll'});
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
const originalFetch=context.fetch;let fail;
context.fetch=path=>String(path).endsWith('/fr.json')?new Promise((resolve,reject)=>{fail=()=>FAILURE==='network'?reject(Error('synthetic network failure')):resolve({ok:false});}):originalFetch(path);
const select=$('#consent-language-select');select.value='fr';const changing=select.onchange({target:select});
assert.equal($('#consent-continue').disabled,true);await tick();
$('#consent-continue').onclick();assert.equal(context.ScreenOrganizerOnboarding.accepted,false);
fail();await changing;await tick();
assert.equal($('#consent-title').textContent,'Before you begin');assert.equal($('#consent-agree').checked,false);assert.equal(text.scrollTop,0);
assert.equal(calls.filter(p=>p.startsWith('/api/')).length,0);
text.scrollTop=800;text.dispatchEvent({type:'scroll'});$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
$('#consent-continue').click();await tick();await tick();assert.ok(calls.includes('/api/devices'));
'''.replace('FAILURE', json.dumps(failure)))


@pytest.mark.parametrize("completion_order", ["old_first", "latest_first"])
def test_superseded_language_load_cannot_change_latest_consent_eligibility(completion_order):
    browser('''
const text=$('#consent-text');text.scrollTop=800;text.dispatchEvent({type:'scroll'});
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
const originalFetch=context.fetch;const release={};
context.fetch=path=>['fr.json','de.json'].includes(String(path).split('/').pop())?new Promise(resolve=>{const file=String(path).split('/').pop();release[file]=()=>resolve({ok:true,json:async()=>harnessInput.catalogs[file]});}):originalFetch(path);
const select=$('#consent-language-select');select.value='fr';const old=select.onchange({target:select});await tick();
select.value='de';const latest=select.onchange({target:select});await tick();
assert.equal($('#consent-continue').disabled,true);
if(ORDER==='old_first') {release['fr.json']();await old;assert.equal($('#consent-continue').disabled,true);$('#consent-continue').onclick();}
assert.equal(context.ScreenOrganizerOnboarding.accepted,false);assert.equal(calls.filter(p=>p.startsWith('/api/')).length,0);
release['de.json']();await latest;await tick();assert.equal($('#consent-title').textContent,'Bevor du beginnst');
assert.equal($('#consent-agree').checked,false);text.scrollTop=800;text.dispatchEvent({type:'scroll'});
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});assert.equal($('#consent-continue').disabled,false);
if(ORDER==='latest_first') {release['fr.json']();await old;assert.equal($('#consent-continue').disabled,false);assert.equal($('#consent-agree').checked,true);}
$('#consent-continue').click();await tick();await tick();assert.ok(calls.includes('/api/devices'));
'''.replace('ORDER', json.dumps(completion_order)))


@pytest.mark.parametrize("failure", ["expired", "network"])
def test_bootstrap_auth_failure_is_handled_before_consent_and_localized_after_catalogs(failure):
    browser('''
assert.equal(context.location.hash,'');assert.deepEqual(unhandled,[]);
assert.equal(calls.filter(p=>p.startsWith('/api/')).length,0);
assert.ok(!document.body.textContent.includes('editor.authenticationFailed'));
const text=$('#consent-text');text.scrollTop=800;text.dispatchEvent({type:'scroll'});
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});$('#consent-continue').click();await tick();await tick();
assert.equal($('#toast').hidden,false);
assert.ok($('#toast').textContent.includes('Authentification impossible. Rouvrez Screen Organizer depuis son lanceur.'));
assert.ok(!document.body.textContent.includes('editor.authenticationFailed'));
assert.equal(calls.filter(p=>p.startsWith('/api/')).length,0,'failed authentication blocks device routes');
''', setup='''
stored.set('screenOrganizer.language','fr');context.location.hash='#token=synthetic-expired';
context.history.replaceState=()=>{calls.push('fragment-cleared');context.location.hash='';};
const originalFetch=context.fetch;
context.fetch=(path,options)=>{
 if(path==='/v1/authenticate'){calls.push(path);assert.equal(context.location.hash,'');return FAILURE==='network'?Promise.reject(Error('synthetic authentication network failure')):Promise.resolve({ok:false,status:401});}
 if(String(path).endsWith('/en.json'))return new Promise(resolve=>{context.releaseCatalog=()=>resolve({ok:true,json:async()=>harnessInput.catalogs['en.json']});});
 return originalFetch(path,options);
};
'''.replace('FAILURE', json.dumps(failure)), before_ready='''
await tick();await tick();assert.deepEqual(unhandled,[],'bootstrap failure is handled while catalogs and consent wait');
assert.equal(context.location.hash,'');assert.deepEqual(calls.slice(0,3),['/static/locales/manifest.json','fragment-cleared','/v1/authenticate']);
context.releaseCatalog();
''')


def test_initial_hidden_terms_require_reading_the_visible_scroll_end():
    browser('''
const text=$('#consent-text');assert.equal($('#consent-dialog').hidden,false);assert.equal(text.scrollTop,0);
assert.ok(text.scrollHeight>text.clientHeight);
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
assert.equal($('#consent-continue').disabled,true,'checkbox alone cannot accept initially hidden overflowing terms');
$('#consent-continue').onclick();await tick();assert.equal(context.ScreenOrganizerOnboarding.accepted,false);
assert.equal(calls.filter(p=>p.startsWith('/api/')).length,0);
text.scrollTop=400;text.dispatchEvent({type:'scroll'});assert.equal($('#consent-continue').disabled,true);
text.scrollTop=800;text.dispatchEvent({type:'scroll'});$('#consent-continue').click();await tick();await tick();
assert.ok(calls.includes('/api/devices'));
''', setup='''
const terms=nodes.find(n=>n.id==='consent-text');assert.equal(terms.clientHeight,0);assert.equal(terms.scrollHeight,0);
''')


def test_long_translated_terms_require_the_new_visible_scroll_end():
    browser('''
const text=$('#consent-text');text.scrollTop=800;text.dispatchEvent({type:'scroll'});
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});assert.equal($('#consent-continue').disabled,false);
const originalFetch=context.fetch;
context.fetch=async path=>{
 if(String(path).endsWith('/fr.json')){text.scrollHeight=1800;return {ok:true,json:async()=>({...harnessInput.catalogs['fr.json'],'consent.backups':harnessInput.catalogs['fr.json']['consent.backups'].repeat(5)})};}
 return originalFetch(path);
};
const select=$('#consent-language-select');select.value='fr';await select.onchange({target:select});await tick();
assert.equal(text.scrollTop,0);assert.equal($('#consent-agree').checked,false);assert.equal(text.scrollHeight,1800);
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
assert.equal($('#consent-continue').disabled,true);$('#consent-continue').onclick();assert.equal(context.ScreenOrganizerOnboarding.accepted,false);
text.scrollTop=800;text.dispatchEvent({type:'scroll'});assert.equal($('#consent-continue').disabled,true,'the old text end does not complete longer terms');
assert.equal(calls.filter(p=>p.startsWith('/api/')).length,0);
text.scrollTop=1600;text.dispatchEvent({type:'scroll'});$('#consent-continue').click();await tick();await tick();assert.ok(calls.includes('/api/devices'));
''')


def test_zero_layout_terms_stay_blocked_until_they_are_rendered_and_read():
    browser('''
const text=$('#consent-text');assert.equal($('#consent-dialog').hidden,false);
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
assert.equal($('#consent-continue').disabled,true,'zero layout cannot complete reading');
$('#consent-continue').onclick();assert.equal(context.ScreenOrganizerOnboarding.accepted,false);
text.clientHeight=200;text.scrollHeight=1000;$('#consent-agree').dispatchEvent({type:'change'});
assert.equal($('#consent-continue').disabled,true);
text.scrollTop=800;text.dispatchEvent({type:'scroll'});assert.equal($('#consent-continue').disabled,false);
''', setup='''
const text=nodes.find(n=>n.id==='consent-text');text.clientHeight=0;text.scrollHeight=0;
''')


def test_fully_visible_terms_allow_agreement_without_extra_scrolling():
    browser('''
const text=$('#consent-text');assert.equal(text.clientHeight,200);assert.equal(text.scrollHeight,200);assert.equal(text.scrollTop,0);
$('#consent-agree').checked=true;$('#consent-agree').dispatchEvent({type:'change'});
assert.equal($('#consent-continue').disabled,false);$('#consent-continue').click();await tick();await tick();assert.ok(calls.includes('/api/devices'));
''', setup='''
const text=nodes.find(n=>n.id==='consent-text');text.scrollHeight=200;
''')
