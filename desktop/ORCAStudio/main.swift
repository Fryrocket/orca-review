import AppKit
import WebKit

private let appInfo = Bundle.main.infoDictionary ?? [:]
private let studioName = appInfo["StudioName"] as? String ?? "ORCA Studio"
private let studioNodeID = appInfo["StudioNodeID"] as? String ?? "ANVIL"
private let studioURL = URL(string: appInfo["StudioURL"] as? String ?? "http://127.0.0.1:8788/")!
private let tunnelHost = appInfo["StudioSSHTunnelHost"] as? String
private let tunnelLocalPort = appInfo["StudioSSHTunnelLocalPort"] as? Int
private let tunnelRemotePort = appInfo["StudioSSHTunnelRemotePort"] as? Int

private func isStudioURL(_ url: URL) -> Bool {
    url.scheme == studioURL.scheme &&
        url.host == studioURL.host &&
        url.port == studioURL.port
}

final class StudioController: NSWindowController, WKNavigationDelegate {
    private let webView: WKWebView

    init() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.userContentController.addUserScript(WKUserScript(
            source: "window.ORCA_DESKTOP_APP=true;window.ORCA_STUDIO_NODE='\(studioNodeID)';",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))

        webView = WKWebView(frame: .zero, configuration: configuration)
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1440, height: 920),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = studioName
        window.titlebarAppearsTransparent = true
        window.minSize = NSSize(width: 980, height: 680)
        window.center()
        window.contentView = webView
        super.init(window: window)

        webView.navigationDelegate = self
        webView.allowsMagnification = true
        let startupDelay = tunnelHost == nil ? 0.0 : 0.8
        DispatchQueue.main.asyncAfter(deadline: .now() + startupDelay) { [weak self] in
            self?.reloadStudio()
        }
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if isStudioURL(url) {
            decisionHandler(.allow)
        } else if navigationAction.navigationType == .linkActivated {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        } else {
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        showOffline(error.localizedDescription)
    }

    private func showOffline(_ detail: String) {
        let escaped = detail.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
        webView.loadHTMLString("""
        <!doctype html><meta charset="utf-8"><style>
        body{margin:0;background:#081012;color:#e8f3ef;font:16px -apple-system;display:grid;place-items:center;height:100vh}
        main{max-width:520px;text-align:center;padding:44px}h1{font-size:42px;margin:0 0 12px}p{color:#9bb0a9;line-height:1.55}
        button{background:#9ef0c6;border:0;border-radius:12px;padding:12px 20px;font-weight:700;cursor:pointer}
        </style><main><h1>\(studioNodeID) is waking up</h1><p>\(studioName) is not ready yet.</p>
        <p>\(escaped)</p><button onclick="location.href='\(studioURL.absoluteString)'">Try again</button></main>
        """, baseURL: studioURL)
    }

    @objc func reloadStudio() { webView.load(URLRequest(url: studioURL, cachePolicy: .reloadIgnoringLocalCacheData)) }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var studio: StudioController?
    private var tunnel: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        startTunnelIfNeeded()
        studio = StudioController()
        studio?.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
        installMenu()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        tunnel?.terminate()
        tunnel = nil
    }

    private func startTunnelIfNeeded() {
        guard let host = tunnelHost,
              let localPort = tunnelLocalPort,
              let remotePort = tunnelRemotePort else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/ssh")
        process.arguments = [
            "-N", "-L", "127.0.0.1:\(localPort):127.0.0.1:\(remotePort)",
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            host,
        ]
        do {
            try process.run()
            tunnel = process
        } catch {
            tunnel = nil
        }
    }

    private func installMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About \(studioName)", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit \(studioName)", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu

        let viewItem = NSMenuItem()
        menu.addItem(viewItem)
        let viewMenu = NSMenu(title: "View")
        let reload = NSMenuItem(title: "Reload Studio", action: #selector(StudioController.reloadStudio), keyEquivalent: "r")
        reload.target = studio
        viewMenu.addItem(reload)
        viewItem.submenu = viewMenu
        NSApp.mainMenu = menu
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
