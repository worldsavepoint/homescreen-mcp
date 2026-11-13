import AppKit
import SwiftUI
import WebKit

@main
struct HomeScreenOrganizerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var engine = Engine()

    var body: some Scene {
        Window("Home Screen Organizer", id: "main") {
            RootView()
                .environmentObject(engine)
                .frame(minWidth: 1000, minHeight: 680)
                .onAppear {
                    delegate.engine = engine
                    if case .starting = engine.state { engine.start() }
                }
        }
        .defaultSize(width: 1360, height: 860)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(after: .toolbar) {
                Button("Reload") { WebStore.shared.webView?.reload() }
                    .keyboardShortcut("r")
                Button("Restart Engine") { engine.start() }
                    .keyboardShortcut("r", modifiers: [.command, .shift])
            }
            CommandMenu("Device") {
                Button("Open Data Folder") {
                    try? FileManager.default.createDirectory(at: Engine.dataFolder, withIntermediateDirectories: true)
                    NSWorkspace.shared.open(Engine.dataFolder)
                }
                Menu("MCP") {
                    let setup = MCPSetup(executablePath: Engine.executable.path)
                    Button("Copy Launch Command") { copy(setup.launchCommand) }
                    Button("Copy Cursor / Claude JSON") { copy(setup.cursorClaudeJSON) }
                    Button("Copy Codex TOML") { copy(setup.codexTOML) }
                    Button("Copy VS Code JSON") { copy(setup.vscodeJSON) }
                }
            }
            CommandGroup(replacing: .help) {
                Button("Home Screen Organizer on GitHub") {
                    NSWorkspace.shared.open(URL(string: "https://github.com/worldsavepoint/ios-homescreen-organizer")!)
                }
                Button("Original Homescreen by Jonathan Kats") {
                    NSWorkspace.shared.open(URL(string: "https://github.com/kats1123/homescreen-mcp")!)
                }
            }
        }
    }

    private func copy(_ value: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var engine: Engine?

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated { engine?.stop() }
    }
}

struct RootView: View {
    @EnvironmentObject private var engine: Engine

    var body: some View {
        switch engine.state {
        case .starting:
            VStack(spacing: 14) {
                AppMark().frame(width: 56, height: 56)
                ProgressView().controlSize(.small)
                Text("Starting Home Screen Organizer…").foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .ready(let url):
            WebView(url: url).ignoresSafeArea()
        case .failed(let message):
            VStack(alignment: .leading, spacing: 12) {
                Text("Home Screen Organizer couldn't start").font(.title2.bold())
                ScrollView {
                    Text(message).font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 320)
                Button("Try Again") { engine.start() }.keyboardShortcut(.defaultAction)
            }
            .padding(32)
            .frame(maxWidth: 640, maxHeight: .infinity)
        }
    }
}

/// The four colored squares, as in the web app's logo.
struct AppMark: View {
    var body: some View {
        GeometryReader { g in
            let s = g.size.width, cell = s * 0.4, r = s * 0.1
            ZStack(alignment: .topLeading) {
                ForEach(0..<4) { i in
                    RoundedRectangle(cornerRadius: r)
                        .fill([Color.orange, .green, .blue, .purple][i])
                        .frame(width: cell, height: cell)
                        .offset(x: i % 2 == 0 ? s * 0.07 : s * 0.53, y: i < 2 ? s * 0.07 : s * 0.53)
                }
            }
        }
    }
}

@MainActor
final class WebStore {
    static let shared = WebStore()
    weak var webView: WKWebView?
}

struct WebView: NSViewRepresentable {
    let url: URL

    func makeCoordinator() -> Coordinator { Coordinator(origin: url) }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        web.uiDelegate = context.coordinator
        web.allowsMagnification = true
        web.setValue(false, forKey: "drawsBackground")
        web.load(URLRequest(url: url))
        WebStore.shared.webView = web
        return web
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        let origin: URL
        init(origin: URL) { self.origin = origin }

        // links to anything but the engine open in the default browser
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { decisionHandler(.cancel); return }
            switch NavigationPolicy.destination(url, origin: origin) {
            case .browser:
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
            case .embedded:
                decisionHandler(.allow)
            case .blocked:
                decisionHandler(.cancel)
            }
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = action.request.url,
               NavigationPolicy.destination(url, origin: origin) != .blocked {
                NSWorkspace.shared.open(url)
            }
            return nil
        }

        func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
            let a = NSAlert()
            a.messageText = message
            a.runModal()
            completionHandler()
        }

        func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
            let a = NSAlert()
            a.messageText = message
            a.addButton(withTitle: "OK")
            a.addButton(withTitle: "Cancel")
            completionHandler(a.runModal() == .alertFirstButtonReturn)
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            webView.reload()
        }
    }
}
