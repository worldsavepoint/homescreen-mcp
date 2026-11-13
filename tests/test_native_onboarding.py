"""Native launch and bridge behavior using isolated catalogs and synthetic children."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "macapp/Shell/Sources/Homescreen"


@pytest.fixture(scope="module")
def native_binary(tmp_path_factory):
    if shutil.which("swiftc") is None:
        pytest.skip("Swift compiler unavailable")
    for name in ("Localization.swift", "ConsentView.swift", "MCPSetupView.swift"):
        assert (SOURCES / name).is_file(), f"Native onboarding requires {name}"
    folder = tmp_path_factory.mktemp("native-onboarding")
    # App.swift supplies AppMark and WebView. Rename only its entry-point annotation.
    app = folder / "App.swift"
    app.write_text((SOURCES / "App.swift").read_text().replace("@main\n", ""))
    harness = folder / "Harness.swift"
    harness.write_text(r'''
import AppKit
import SwiftUI
import WebKit
final class TemporaryPreferences: LanguagePreferences {
 let path: URL
 init(_ path: URL) { self.path = path }
 func string(forKey key: String) -> String? {
  guard let data = try? Data(contentsOf:path), let values = try? JSONDecoder().decode([String:String].self,from:data) else { return nil }
  return values[key]
 }
 func set(_ value: Any?, forKey key: String) {
  try! JSONEncoder().encode([key:value as! String]).write(to:path)
 }
}
@main struct Harness {
 @MainActor static func main() async throws {
  let directory = URL(fileURLWithPath: CommandLine.arguments[2])
  let defaults = TemporaryPreferences(directory.appendingPathComponent("preferences.json"))
  let l = Localization(catalogDirectory: directory, defaults: defaults, preferredLanguages: ["ja-JP", "zh-HK"])
  switch CommandLine.arguments[1] {
  case "localization":
   assert(l.locale == "zh-Hant")
   assert(l.t("app.name") == "螢幕整理")
   let cases = ["zh_Hant_CN":"zh-Hant", "zh-Hans-TW":"zh-Hans", "zh-SG":"zh-Hans", "zh-x-hant":"zh-Hans", "fr-CA":"fr", "pt-BR":"pt", "xx":"en", "bad--code":"en"]
   for (input, expected) in cases { assert(l.resolveLocale(input) == expected, input) }
   l.setPreference("fr")
   assert(l.t("common.cancel") == "Annuler")
   assert(l.t("app.name") == "Screen Organizer")
   assert(l.t("test.fallback", ["name":"{count}", "count":"42"]) == "Hello {count}; 42; {missing}")
   assert(l.t("missing.key") == "missing.key")
   assert(defaults.string(forKey: "screenOrganizer.language") == "fr")
   l.setPreference("unapproved")
   assert(l.preference == "system" && l.locale == "zh-Hant")
  case "fallback":
   l.setPreference("fr")
   assert(l.locale == "fr" && l.t("common.cancel") == "Cancel")
  case "consent":
   let c = LaunchConsent()
   assert(!c.accepted && !c.canContinue)
   c.setAgreed(true); assert(!c.accept())
   c.observeEnd(CGRect(x: 0,y: 800,width: 20,height: 2), viewport: CGSize(width: 600,height: 300))
   assert(!c.hasReadToEnd)
   c.observeEnd(.zero, viewport: .zero); assert(!c.hasReadToEnd)
   c.observeEnd(CGRect(x: 0,y: -10,width: 20,height: 2), viewport: CGSize(width: 600,height: 300))
   assert(!c.hasReadToEnd)
   c.observeEnd(CGRect(x: 0,y: 298,width: 600,height: 2), viewport: CGSize(width: 600,height: 300))
   assert(c.hasReadToEnd && !c.canContinue)
   c.setAgreed(true); assert(c.canContinue)
   c.languageChanged(); assert(!c.hasReadToEnd && !c.agreed && !c.accept())
   c.observeEnd(CGRect(x: 0,y: 298,width: 600,height: 2), viewport: CGSize(width: 600,height: 300))
   c.setAgreed(true); assert(c.accept() && c.accepted)
   assert(!c.accept())
   c.languageChanged(); assert(c.accepted)
   assert(!LaunchConsent().accepted)
   let declined = LaunchConsent(); declined.decline()
   declined.observeEnd(CGRect(x: 0,y: 20,width: 20,height: 2), viewport: CGSize(width: 600,height: 300))
   declined.setAgreed(true); assert(!declined.accept())
  case "bridge":
   let origin = URL(string: "http://127.0.0.1:8765/#token=secret")!
   let message: [String:Any] = ["action":"openMCPSetup"]
   assert(NativeBridge.action(message, frameURL: origin, isMainFrame: true, origin: origin) == .openMCPSetup)
   for bad in ["http://127.0.0.1:8766/", "http://localhost:8765/", "https://127.0.0.1:8765/", "http://user@127.0.0.1:8765/", "file:///tmp/editor"] {
    assert(NativeBridge.action(message, frameURL: URL(string:bad), isMainFrame:true, origin:origin) == nil)
   }
   assert(NativeBridge.action(message, frameURL:origin,isMainFrame:false,origin:origin) == nil)
   assert(NativeBridge.action(["action":"run","command":"anything"],frameURL:origin,isMainFrame:true,origin:origin) == nil)
   assert(NativeBridge.action(["action":"setLanguage","preference":"fr"],frameURL:origin,isMainFrame:true,origin:origin) == .setLanguage("fr"))
   assert(NativeBridge.action(["action":"setLanguage","preference":5],frameURL:origin,isMainFrame:true,origin:origin) == nil)
  case "webkit":
   NSApplication.shared.setActivationPolicy(.accessory)
   l.setPreference("en")
   let c = LaunchConsent()
   c.observeEnd(CGRect(x:0,y:20,width:20,height:2),viewport:CGSize(width:600,height:300))
   c.setAgreed(true); assert(c.accept())
   let origin = URL(string:"http://127.0.0.1:47985/")!
   var opens = 0
   let coordinator = WebView.Coordinator(origin:origin,localization:l,consent:c,openSetup:{opens += 1})
   let config = WKWebViewConfiguration()
   config.websiteDataStore = .nonPersistent()
   config.userContentController.add(coordinator,name:"screenOrganizer")
   coordinator.installBootstrap(config.userContentController)
   let web = WKWebView(frame:CGRect(x:0,y:0,width:600,height:400),configuration:config)
   web.navigationDelegate = coordinator
   // An in-memory page with no source routes or network resources.
   web.loadHTMLString("""
   <button id="setup" onclick="window.webkit.messageHandlers.screenOrganizer.postMessage({action:'openMCPSetup'})">MCP</button>
   <script>
   window.boot=JSON.parse(JSON.stringify(window.screenOrganizerHost));window.draft={name:'Kept draft'};window.calls=[];
   window.ScreenOrganizerI18n={setLocale:async preference=>{
     calls.push(preference);if(preference==='fr')await new Promise(resolve=>window.releaseFrench=resolve);
   }};
   </script>
   """,baseURL:origin)
   for _ in 0..<100 {
    if (try? await web.evaluateJavaScript("typeof window.boot === 'object' && calls.length > 0")) as? Bool == true { break }
    try await Task.sleep(nanoseconds:50_000_000)
   }
   let bootJSON = try await web.evaluateJavaScript("JSON.stringify(window.boot)") as! String
   let boot = try JSONSerialization.jsonObject(with:Data(bootJSON.utf8)) as! [String:Any]
   assert(boot["native"] as? Bool == true && boot["consentAccepted"] as? Bool == true && boot["languagePreference"] as? String == "en")
   _ = try await web.evaluateJavaScript("document.getElementById('setup').click(); true")
   try await Task.sleep(nanoseconds:100_000_000)
   assert(opens == 1)
   _ = try await web.evaluateJavaScript("window.webkit.messageHandlers.screenOrganizer.postMessage({action:'setLanguage',preference:'de'}); true")
   try await Task.sleep(nanoseconds:100_000_000)
   assert(l.preference == "de")
   l.setPreference("fr"); coordinator.synchronizeLanguage(web)
   try await Task.sleep(nanoseconds:100_000_000)
   l.setPreference("en"); coordinator.synchronizeLanguage(web)
   try await Task.sleep(nanoseconds:100_000_000)
   _ = try await web.evaluateJavaScript("window.releaseFrench(); true")
   let calls = try await web.evaluateJavaScript("JSON.stringify(calls)") as? String
   assert(calls == "[\"en\",\"fr\",\"en\"]")
   let draft = try await web.evaluateJavaScript("window.draft.name") as? String
   assert(draft == "Kept draft")
   config.userContentController.removeScriptMessageHandler(forName:"screenOrganizer")
  case "panel":
   let executable = CommandLine.arguments[3]
   let marker = CommandLine.arguments[4]
   var calls: [[String]] = []
   let manager = MCPClientManager(environment: [:], homeDirectory: directory, executableLocator: { _ in executable }, runner: { _, args, _, _ in
    calls.append(args)
    try? await Task.sleep(nanoseconds:100_000_000)
    if args[1] == "get" {
     let response: [String:Any] = ["name":"ios-homescreen-mcp","transport":["command":executable,"args":["mcp"],"env":["HOMESCREEN_READ_ONLY":"1"]]]
     return MCPCommandResult(exitStatus:0,stdout:String(decoding:try! JSONSerialization.data(withJSONObject:response),as:UTF8.self))
    }
    return MCPCommandResult(exitStatus:0)
   })
   let model = MCPSetupModel(manager:manager,serviceCheck:MCPServiceCheck(timeout:1,environment:["MARKER":marker]),enginePath:executable)
   let c = LaunchConsent()
   await model.refresh(consent:c); await model.register(.codex,consent:c); await model.check(consent:c)
   assert(calls.isEmpty && model.checkResult == nil && !FileManager.default.fileExists(atPath:marker))
   c.observeEnd(CGRect(x:0,y:20,width:20,height:2),viewport:CGSize(width:600,height:300))
   c.setAgreed(true); assert(c.accept())
   let first = Task { await model.register(.codex,consent:c) }
   try await Task.sleep(nanoseconds:20_000_000)
   assert(model.busy)
   await model.register(.codex,consent:c)
   await model.check(consent:c)
   await first.value
   assert(calls.filter { $0[1] == "add" }.count == 1)
   assert(!model.busy && model.registrations[.codex]?.code == .success)
   assert(model.queries[.codex]?.configuration == .configured && model.queries[.codex]?.connection == .unknown)
   assert(model.checkResult == nil)
   await model.check(consent:c)
   assert(model.checkResult != nil && FileManager.default.fileExists(atPath:marker))
   assert(model.queries[.codex]?.connection == .unknown)
  case "engine":
   let executable = URL(fileURLWithPath: CommandLine.arguments[3])
   let marker = CommandLine.arguments[4]
   let c = LaunchConsent()
   let e = Engine(executableURL: executable, environment: ["MARKER":marker,"HOMESCREEN_DATA":directory.appendingPathComponent("data").path])
   e.start(consent:c)
   try await Task.sleep(nanoseconds:100_000_000)
   assert(!FileManager.default.fileExists(atPath:marker))
   c.observeEnd(CGRect(x:0,y:20,width:20,height:2),viewport:CGSize(width:600,height:300))
   c.setAgreed(true); assert(c.accept())
   e.start(consent:c)
   for _ in 0..<100 {
    if FileManager.default.fileExists(atPath:marker) { break }
    try await Task.sleep(nanoseconds:20_000_000)
   }
   e.stop()
   assert(FileManager.default.fileExists(atPath:marker), String(describing:e.state))
  default: fatalError("unknown harness mode")
  }
  print("passed")
 }
}
''')
    binary = folder / "native-tests"
    compiled = subprocess.run(["swiftc", "-module-cache-path", str(folder / "modules"),
                               *[str(p) for p in SOURCES.glob("*.swift") if p.name != "App.swift"],
                               str(app), str(harness), "-o", str(binary)], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    return binary


@pytest.fixture
def catalogs(tmp_path):
    target = tmp_path / "catalogs"
    shutil.copytree(ROOT / "homescreen/web/locales", target)
    en = json.loads((target / "en.json").read_text())
    en["test.fallback"] = "Hello {name}; {count}; {missing}"
    (target / "en.json").write_text(json.dumps(en))
    return target


@pytest.mark.parametrize("mode", ["localization", "consent", "bridge", "webkit"])
def test_native_contracts(native_binary, catalogs, mode):
    result = subprocess.run([str(native_binary), mode, str(catalogs)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_native_catalog_falls_back_to_english(native_binary, catalogs):
    (catalogs / "fr.json").unlink()
    result = subprocess.run([str(native_binary), "fallback", str(catalogs)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["engine", "panel"])
def test_child_start_order_and_serialized_panel(native_binary, catalogs, tmp_path, mode):
    child = tmp_path / "engine"
    child.write_text('#!/bin/sh\nprintf accepted > "$MARKER"\n')
    child.chmod(0o755)
    result = subprocess.run([str(native_binary), mode, str(catalogs), str(child), str(tmp_path / "started")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
