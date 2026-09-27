import AppKit
import WebKit

private let studioURL = URL(string: "http://127.0.0.1:8788/")!

final class StudioController: NSWindowController, WKNavigationDelegate {
    private let webView: WKWebView

    init() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.userContentController.addUserScript(WKUserScript(
            source: "window.ORCA_DESKTOP_APP=true;",
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
        window.title = "ORCA Studio"
        window.titlebarAppearsTransparent = true
        window.minSize = NSSize(width: 980, height: 680)
        window.center()
        window.contentView = webView
        super.init(window: window)

        webView.navigationDelegate = self
        webView.allowsMagnification = true
        webView.load(URLRequest(url: studioURL, cachePolicy: .reloadIgnoringLocalCacheData))
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.host == "127.0.0.1" && url.port == 8788 {
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
        </style><main><h1>ORCA is waking up</h1><p>The Studio gateway is not ready yet.</p>
        <p>\(escaped)</p><button onclick="location.href='http://127.0.0.1:8788/'">Try again</button></main>
        """, baseURL: studioURL)
    }

    @objc func reloadStudio() { webView.load(URLRequest(url: studioURL, cachePolicy: .reloadIgnoringLocalCacheData)) }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var studio: StudioController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        studio = StudioController()
        studio?.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
        installMenu()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    private func installMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About ORCA Studio", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit ORCA Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
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
