"""Native launch and bridge behavior using isolated catalogs and synthetic children."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

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
@MainActor func accepted() -> LaunchConsent {
 let c = LaunchConsent()
 c.observeEnd(CGRect(x:0,y:20,width:20,height:2),viewport:CGSize(width:600,height:300))
 c.setAgreed(true); assert(c.accept())
 return c
}
final class TestEntry {
 var entry = MCPOwnedEntry.absent
 func store(client: MCPClient, path: String, env: [String:String], home: URL, timeout: TimeInterval, runner: @escaping MCPCommandRunner) -> MCPEntryStore {
  MCPEntryStore(client:client,executable:path,environment:env,home:home,timeout:timeout,runner:runner,
    readOverride:{ MCPUserSnapshot(file:home.appendingPathComponent("fixture").path,entry:self.entry) },preflightOverride:{})
 }
}
actor Gate {
 var started = false
 var release: CheckedContinuation<Void,Never>?
 func hold() async { await withCheckedContinuation { release = $0; started = true } }
 func waitForStart() async { while !started { await Task.yield() } }
 func resume() { release?.resume(); release = nil }
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
   for (value, expected) in ["fra":"fr","fre":"fr","spa":"es","zh-TW":"zh-Hant","zh-Hant-HK":"zh-Hant-HK","gsw_CH":"de","de-1901":"de-1901","sh":"sr-Latn"] {
    l.setPreference(value); assert(l.preference == expected, value)
    assert(defaults.string(forKey:"screenOrganizer.language") == expected)
   }
   l.setPreference("zh-Hant-HK"); assert(l.t("common.cancel") == "Regional cancel")
   l.setPreference("zh-TW")
   let reopened = Localization(catalogDirectory:directory,defaults:defaults,preferredLanguages:["en"])
   assert(reopened.locale == "zh-Hant" && reopened.preference == "zh-Hant")
   defaults.set("zh_TW",forKey:"screenOrganizer.language")
   let fromAlias = Localization(catalogDirectory:directory,defaults:defaults,preferredLanguages:["en"])
   assert(fromAlias.preference == "zh-Hant")
   assert(l.recognizedPreference("en-a-foo-a-bar") == nil)
   l.setPreference("fr")
   assert(l.t("common.cancel") == "Annuler")
   assert(l.t("app.name") == "Screen Organizer")
   assert(l.t("test.fallback", ["name":"{count}", "count":"42"]) == "Hello {count}; 42; {missing}")
   assert(l.t("missing.key") == "missing.key")
   assert(defaults.string(forKey: "screenOrganizer.language") == "fr")
   l.setPreference("unapproved")
   assert(l.preference == "system" && l.locale == "zh-Hant")
  case "japanese": assert(l.locale == "ja" && l.t("common.cancel") == "キャンセル")
  case "contributor": assert(l.languages.contains { $0.code == l.locale })
  case "exports":
   let engine = "/Applications/Fixture 引用.app/engine"
   for mode in [MCPAccessMode.readOnly,.applyEnabled] {
    let setup = MCPSetup(executablePath:engine,mode:mode)
    for (format,root,tools) in [("vscode","servers",false),("copilot","mcpServers",true)] {
     let board = NSPasteboard.withUniqueName()
     assert(setup.copy(format:format,to:board))
     let text = board.string(forType:.string)!
     board.releaseGlobally()
     let payload = try JSONSerialization.jsonObject(with:Data(text.utf8)) as! [String:[String:[String:Any]]]
     assert(Array(payload.keys) == [root])
     let entry = payload[root]!["ios-homescreen-mcp"]!
     assert(entry["type"] as? String == "stdio" && entry["command"] as? String == engine)
     assert(entry["args"] as? [String] == ["mcp"])
     assert(tools ? entry["tools"] as? [String] == ["*"] : entry["tools"] == nil)
     let gates = mode == .readOnly ? ["HOMESCREEN_READ_ONLY":"1"] : ["HOMESCREEN_READ_ONLY":"0","HOMESCREEN_ALLOW_APPLY":"1"]
     assert(entry["env"] as? [String:String] == gates)
    }
   }
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
   for (input,want) in [("zh_TW","zh-Hant"),("en-a-foo-a-bar","zh-Hant"),("de","de")] {
    _ = try await web.callAsyncJavaScript("window.webkit.messageHandlers.screenOrganizer.postMessage({action:'setLanguage',preference:value});return true",
        arguments:["value":input],in:nil,in:.page)
    for _ in 0..<100 where l.preference != want { try await Task.sleep(nanoseconds:10_000_000) }
    assert(l.preference == want)
   }
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
  case "refresh":
   let executable = CommandLine.arguments[3]
   var queryFailure: MCPClientOperationCode?
   var addFailure = false
   var calledPaths: [String] = []
   let storage = TestEntry()
   let manager = MCPClientManager(environment: [:], homeDirectory: directory, executableLocator: { _ in executable }, runner: { path, args, _, _, _ in
    calledPaths.append(path)
    if args[1] == "get" {
     if let failure = queryFailure { return MCPCommandResult(exitStatus:1,failure:failure) }
     let response: [String:Any] = ["name":"ios-homescreen-mcp","enabled":true,"transport":["type":"stdio","command":executable,"args":["mcp"],"env":["HOMESCREEN_READ_ONLY":"1"]]]
     return MCPCommandResult(exitStatus:0,stdout:String(decoding:try! JSONSerialization.data(withJSONObject:response),as:UTF8.self))
    }
    if !addFailure {
     storage.entry = try! MCPOwnedEntry(["command":executable,"args":["mcp"],"env":["HOMESCREEN_READ_ONLY":"1"]])
    }
    return MCPCommandResult(exitStatus:addFailure ? 1 : 0)
   },storeFactory:storage.store)
   let model = MCPSetupModel(manager:manager,enginePath:executable)
   let c = LaunchConsent()
   c.observeEnd(CGRect(x:0,y:20,width:20,height:2),viewport:CGSize(width:600,height:300)); c.setAgreed(true); assert(c.accept())
   assert(model.installationKey(for:.codex) == "common.unknown")
   for failure in [MCPClientOperationCode.timedOut, .commandFailed] {
    queryFailure = nil
    await model.register(.codex,consent:c)
    assert(model.registrations[.codex]?.code == .success)
    assert(model.feedback(for:.codex)?.primaryKey == "mcp.registered")
    queryFailure = failure
    await model.refresh(consent:c)
    assert(model.registrations[.codex] == nil, "Refresh must replace the old registration result")
    assert(model.queries[.codex]?.code == failure)
    assert(model.queries[.codex]?.configuration == .unknown && model.queries[.codex]?.connection == .unknown)
    let feedback = model.feedback(for:.codex)!
    assert(feedback.primaryKey == (failure == .timedOut ? "mcp.timeout" : "mcp.operationFailed"))
    assert(feedback.details == failure.rawValue && feedback.recoveryKey == nil)
    assert(l.t(feedback.primaryKey) != feedback.primaryKey)
   }
   queryFailure = nil
   addFailure = true
   await model.register(.codex,consent:c)
   assert(model.registrations[.codex]?.code == .commandFailed)
   assert(model.queries[.codex]?.code == .success)
   assert(model.feedback(for:.codex)?.primaryKey == "mcp.operationFailed")
   assert(model.feedback(for:.codex)?.details == "commandFailed · restored")
   await model.refresh(consent:c)
   assert(model.registrations[.codex] == nil && model.queries[.codex]?.configuration == .configured)
   assert(model.feedback(for:.codex) == nil)
   addFailure = false
   await model.register(.codex,consent:c)
   queryFailure = .timedOut
   let selected = executable + "-selected"
   await model.choose(selected,for:.codex,consent:c)
   assert(calledPaths.contains(selected))
   assert(model.installationKey(for:.codex) == "mcp.installed")
   assert(model.detections[.codex]?.executablePath == selected)
   assert(model.registrations[.codex] == nil && model.queries[.codex]?.code == .timedOut)
   assert(model.feedback(for:.codex)?.primaryKey == "mcp.timeout" && model.feedback(for:.codex)?.details == "timedOut")
   queryFailure = nil
   await model.refresh(consent:c)
   assert(model.queries[.codex]?.configuration == .configured && model.queries[.codex]?.connection == .unknown)
   assert(model.checkResult == nil)
   assert(model.feedback(for:.codex) == nil)
   await model.choose(directory.path,for:.codex,consent:c)
   assert(model.installationKey(for:.codex) == "mcp.notExecutable")
   let missingManager = MCPClientManager(environment:[:],homeDirectory:directory,executableLocator:{_ in nil})
   let missing = MCPSetupModel(manager:missingManager,enginePath:executable)
   await missing.refresh(consent:c)
   assert(missing.installationKey(for:.codex) == "mcp.notInstalled")
  case "recovery":
   let executable = CommandLine.arguments[3]
   for recoverySucceeds in [true, false] {
    var snapshot: String? = #"{"command":"/original/engine","args":["mcp"],"env":{"HOMESCREEN_READ_ONLY":"1"}}"#
    let manager = MCPClientManager(environment:[:],homeDirectory:directory,executableLocator:{ _ in executable },runner:{ _,args,_,_,_ in
     switch args[1] {
     case "get":
      return snapshot == nil ? MCPCommandResult(exitStatus:1,stdout:"No server named ios-homescreen-mcp") :
       MCPCommandResult(exitStatus:0,stdout:"ios-homescreen-mcp:\nScope: User\nCommand: /original/engine\nStatus: disconnected\nHOMESCREEN_READ_ONLY=1")
     case "remove": snapshot = nil; return MCPCommandResult(exitStatus:0)
     case "add-json":
      if recoverySucceeds { snapshot = args.last }
      return MCPCommandResult(exitStatus:recoverySucceeds ? 0 : 1)
     default: return MCPCommandResult(exitStatus:1,failure:.timedOut)
     }
    },storeFactory:{ client,path,env,home,timeout,runner in
     MCPEntryStore(client:client,executable:path,environment:env,home:home,timeout:timeout,runner:runner,readOverride:{
      let entry = try snapshot.map { try JSONSerialization.jsonObject(with:Data($0.utf8)) }
      return try MCPUserSnapshot(file:home.appendingPathComponent("fixture").path,entry:MCPOwnedEntry(entry))
     })
    })
    let model = MCPSetupModel(manager:manager,enginePath:executable)
    let c = LaunchConsent()
    c.observeEnd(CGRect(x:0,y:20,width:20,height:2),viewport:CGSize(width:600,height:300)); c.setAgreed(true); assert(c.accept())
    await model.register(.claudeCode,consent:c)
    let feedback = model.feedback(for:.claudeCode)!
    assert(feedback.primaryKey == "mcp.timeout")
    assert(feedback.recoveryKey == (recoverySucceeds ? "mcp.restored" : "mcp.recoveryFailed"))
    assert(feedback.details == (recoverySucceeds ? "timedOut · restored" : "timedOut · failed"))
    await model.refresh(consent:c)
    if recoverySucceeds { assert(model.registrations[.claudeCode] == nil && model.feedback(for:.claudeCode) == nil) }
    else { assert(model.registrations[.claudeCode]?.recovery == .failed && model.feedback(for:.claudeCode)?.recoveryKey == "mcp.recoveryFailed") }
    assert(model.checkResult == nil)
   }
  case "panel":
   let executable = CommandLine.arguments[3]
   let marker = CommandLine.arguments[4]
   var calls: [[String]] = []
   let gate = Gate()
   let storage = TestEntry()
   let manager = MCPClientManager(environment: [:], homeDirectory: directory, executableLocator: { _ in executable }, runner: { _, args, _, _, _ in
    calls.append(args)
    if args[1] == "add" {
     await gate.hold()
     storage.entry = try! MCPOwnedEntry(["command":executable,"args":["mcp"],"env":["HOMESCREEN_READ_ONLY":"1"]])
    }
    if args[1] == "get" {
     let response: [String:Any] = ["name":"ios-homescreen-mcp","enabled":true,"transport":["type":"stdio","command":executable,"args":["mcp"],"env":["HOMESCREEN_READ_ONLY":"1"]]]
     return MCPCommandResult(exitStatus:0,stdout:String(decoding:try! JSONSerialization.data(withJSONObject:response),as:UTF8.self))
    }
    return MCPCommandResult(exitStatus:0)
   },storeFactory:storage.store)
   let model = MCPSetupModel(manager:manager,serviceCheck:MCPServiceCheck(timeout:10,environment:["MARKER":marker]),enginePath:executable)
   let c = LaunchConsent()
   await model.refresh(consent:c); await model.register(.codex,consent:c); await model.check(consent:c)
   assert(calls.isEmpty && model.checkResult == nil && !FileManager.default.fileExists(atPath:marker))
   c.observeEnd(CGRect(x:0,y:20,width:20,height:2),viewport:CGSize(width:600,height:300))
   c.setAgreed(true); assert(c.accept())
   let first = Task { await model.register(.codex,consent:c) }
   await gate.waitForStart()
   assert(model.busy)
   model.dismissPanel()
   let delegate = AppDelegate()
   delegate.setup = model
   var replies = 0
   delegate.terminationReply = { replies += 1 }
   assert(delegate.applicationShouldTerminate(NSApplication.shared) == .terminateLater)
   assert(delegate.applicationShouldTerminate(NSApplication.shared) == .terminateLater)
   assert(replies == 0)
   await model.register(.codex,consent:c)
   await model.check(consent:c)
   await gate.resume()
   await first.value
   while replies == 0 { await Task.yield() }; assert(replies == 1)
   assert(calls.filter { $0[1] == "add" }.count == 1)
   assert(!model.busy && model.registrations[.codex]?.code == .success)
   assert(model.queries[.codex]?.configuration == .configured && model.queries[.codex]?.connection == .unknown)
   assert(model.checkResult == nil)
   await model.check(consent:c)
   assert(model.checkResult?.code == .passed && FileManager.default.fileExists(atPath:marker), String(describing:model.checkResult?.code))
   assert(model.queries[.codex]?.connection == .unknown)
  case "cancelInspection":
   let executable = CommandLine.arguments[3]
   let marker = CommandLine.arguments[4]
   let manager = MCPClientManager(environment:["MARKER":marker],homeDirectory:directory,timeout:20,executableLocator:{ _ in executable })
   let model = MCPSetupModel(manager:manager,serviceCheck:MCPServiceCheck(timeout:20,environment:["MARKER":marker]),enginePath:executable)
   let c = accepted()
   for action in ["refresh","check"] {
    let job = Task { if action == "refresh" { await model.refresh(consent:c) } else { await model.check(consent:c) } }
    while !FileManager.default.fileExists(atPath:marker) { await Task.yield() }
    model.dismissPanel()
    await job.value
    assert(!model.busy && model.checkResult == nil && model.detections[.claudeCode] == nil)
    let log = try String(contentsOfFile:marker).components(separatedBy:"|")
    assert(kill(Int32(log[0])!,0) < 0 && errno == ESRCH)
    if log.count == 2 { assert(!FileManager.default.fileExists(atPath:log[1])) }
    try FileManager.default.removeItem(atPath:marker)
   }
   let token = MCPChildCancellation()
   token.cancel()
   do { _ = try token.launch(executable,arguments:[], environment:["MARKER":marker],cwd:directory.path,stdin:.nullDevice,stdout:.nullDevice,stderr:.nullDevice); assertionFailure("cancelled child started") } catch MCPClientOperationCode.cancelled {}
   assert(!FileManager.default.fileExists(atPath:marker))
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
    # Locale fallback assumptions belong to this fixed manifest.
    codes = {"en":["en"],"zh-Hans":["zh","zh-CN","zh-SG"],"zh-Hant":["zh-HK","zh-TW"],
             "zh-Hant-HK":["zh-Hant-HK"],"de-1901":["de-1901"],"sr-Latn":["sr-Latn"],"fr":["fr"],"pt":["pt"],"de":["gsw_CH"],"es":["es"]}
    (target/"manifest.json").write_text(json.dumps({"languages":[
        {"code":code,"name":code,"aliases":aliases} for code,aliases in codes.items()]}))
    (target/"zh-Hant-HK.json").write_text(json.dumps({"common.cancel":"Regional cancel"}))
    en = json.loads((target / "en.json").read_text())
    en["test.fallback"] = "Hello {name}; {count}; {missing}"
    (target / "en.json").write_text(json.dumps(en))
    return target


@pytest.mark.parametrize("mode", ["localization", "consent", "bridge", "webkit", "exports"])
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
    if mode == "panel":
        child.write_text(f"#!{sys.executable}\n" + '''import json,os,sys
from pathlib import Path
Path(os.environ["MARKER"]).write_text("started")
for line in sys.stdin:
    message = json.loads(line)
    if message["method"] == "initialize":
        result = {"protocolVersion":"2025-11-25","capabilities":{"tools":{}},"serverInfo":{"name":"ios-homescreen-mcp","version":"1"}}
    elif message["method"] == "tools/list":
        result = {"tools":[{"name":name,"inputSchema":{"type":"object"}} for name in ["read_phone","show_layout","move","diff"]]}
    else: continue
    print(json.dumps({"jsonrpc":"2.0","id":message["id"],"result":result}),flush=True)
''')
    child.chmod(0o755)
    result = subprocess.run([str(native_binary), mode, str(catalogs), str(child), str(tmp_path / "started")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["refresh", "recovery"])
def test_refresh_replaces_registration_results(native_binary, catalogs, tmp_path, mode):
    executable = tmp_path / "synthetic-client"
    executable.write_text("#!/bin/sh\nexit 99\n")
    executable.chmod(0o755)
    shutil.copy(executable, str(executable) + "-selected")
    result = subprocess.run([str(native_binary), mode, str(catalogs), str(executable)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

def test_native_contributor_language_selection(native_binary, catalogs):
    # Fixed baselines keep this experiment independent of future contributions.
    baseline = catalogs.parent / "contribution"
    baseline.mkdir()
    registrations = [{"code":"en","name":"English","aliases":["en"]},
                     {"code":"zh-Hant","name":"繁體中文","aliases":["zh-Hant","zh-HK"]},
                     {"code":"ja","name":"日本語","aliases":["ja"]}]
    (baseline/"manifest.json").write_text(json.dumps({"default":"en","languages":registrations}))
    for code in ("en","zh-Hant"):
        shutil.copy(ROOT/"homescreen/web/locales"/(code+".json"),baseline/(code+".json"))
    japanese = json.loads((baseline/"en.json").read_text())
    japanese["common.cancel"] = "キャンセル"
    (baseline/"ja.json").write_text(json.dumps(japanese, ensure_ascii=False))
    subprocess.run([sys.executable,str(ROOT/"tools/check_translations.py"),"--locales",str(baseline)],check=True)
    subprocess.run([str(native_binary),"japanese",str(baseline)], check=True)
    shutil.copy(ROOT/"homescreen/web/locales/manifest.json", catalogs/"manifest.json")
    subprocess.run([str(native_binary),"contributor",str(catalogs)], check=True)

def test_panel_dismissal_cancels_and_reaps_inspections(native_binary,catalogs,tmp_path):
    child = tmp_path/"inspection"
    child.write_text(f"#!{sys.executable}\n" + '''import os,signal,time
from pathlib import Path
signal.signal(signal.SIGTERM,signal.SIG_IGN)
if os.fork(): time.sleep(6); os._exit(0)
marker = Path(os.environ["MARKER"])
tmp = marker.with_suffix(".tmp")
tmp.write_text(str(os.getpid())+"|"+os.environ.get("HOMESCREEN_DATA","/no-fixture-data"))
tmp.rename(marker)
time.sleep(60)
''')
    child.chmod(0o755)
    result = subprocess.run([str(native_binary),"cancelInspection",str(catalogs),str(child),str(tmp_path/"started")],
                            capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr
