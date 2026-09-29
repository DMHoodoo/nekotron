// nekobar — Nekotron's floating fleet pill.
// A borderless always-on-top panel under the menu bar: collapsed it shows
// ᓚᘏᗢ + the count that matters; hover expands the session list; click a
// row to jump to that kitty tab. Data comes from the SwiftBar plugin's
// --json mode (single source of truth). Build: nekobar/build.sh
import AppKit

let INK = NSColor(red: 0.91, green: 0.93, blue: 1.0, alpha: 1)
let DIMC = NSColor(red: 0.54, green: 0.58, blue: 0.72, alpha: 1)
let BLUE = NSColor(red: 0.31, green: 0.56, blue: 0.97, alpha: 1)
let GREEN = NSColor(red: 0.30, green: 0.76, blue: 0.54, alpha: 1)
let ORANGE = NSColor(red: 0.94, green: 0.50, blue: 0.24, alpha: 1)
let AMBER = NSColor(red: 1.0, green: 0.71, blue: 0.36, alpha: 1)

struct Sess {
    let wid: Int
    let title: String
    let state: String
    let ctx: String
    let cost: String
}

func stateColor(_ s: String) -> NSColor {
    switch s {
    case "working": return BLUE
    case "done": return GREEN
    case "attention": return ORANGE
    default: return DIMC
    }
}

final class HoverView: NSView {
    var onEnter: (() -> Void)?
    var onExit: (() -> Void)?
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(
            rect: bounds, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
            owner: self, userInfo: nil))
    }
    override func mouseEntered(with event: NSEvent) { onEnter?() }
    override func mouseExited(with event: NSEvent) { onExit?() }
}

final class App: NSObject, NSApplicationDelegate {
    var panel: NSPanel!
    var root: HoverView!
    var sessions: [Sess] = []
    var kittyUp = false
    var expanded = false
    var collapseTimer: Timer?
    let pillH: CGFloat = 26
    let expW: CGFloat = 380

    func applicationDidFinishLaunching(_ n: Notification) {
        panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 120, height: pillH),
                        styleMask: [.borderless, .nonactivatingPanel],
                        backing: .buffered, defer: false)
        panel.level = .statusBar
        panel.isFloatingPanel = true
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.isMovableByWindowBackground = false
        root = HoverView()
        root.wantsLayer = true
        root.layer?.backgroundColor = NSColor(white: 0.05, alpha: 0.94).cgColor
        root.layer?.cornerRadius = pillH / 2
        root.onEnter = { [weak self] in self?.expand() }
        root.onExit = { [weak self] in self?.scheduleCollapse() }
        panel.contentView = root
        panel.orderFrontRegardless()
        rebuild()
        refresh()
        Timer.scheduledTimer(withTimeInterval: 4.0, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    func plistPath() -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return home + "/Documents/GlowDevelopment/nekotron/swiftbar/nekotron.5s.py"
    }

    func refresh() {
        DispatchQueue.global().async { [weak self] in
            guard let self = self else { return }
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            p.arguments = ["python3", self.plistPath(), "--json"]
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = FileHandle.nullDevice
            var ses: [Sess] = []
            var up = false
            do {
                try p.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                p.waitUntilExit()
                if let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    up = (obj["kitty"] as? Bool) ?? false
                    for d in (obj["sessions"] as? [[String: Any]]) ?? [] {
                        ses.append(Sess(
                            wid: (d["wid"] as? Int) ?? 0,
                            title: (d["title"] as? String) ?? "?",
                            state: (d["state"] as? String) ?? "neutral",
                            ctx: (d["ctx"] as? String) ?? "",
                            cost: (d["cost"] as? String) ?? ""))
                    }
                }
            } catch {}
            DispatchQueue.main.async {
                self.sessions = ses
                self.kittyUp = up
                self.rebuild()
            }
        }
    }

    func pillText() -> (String, NSColor) {
        let att = sessions.filter { $0.state == "attention" }.count
        let wrk = sessions.filter { $0.state == "working" }.count
        if !kittyUp { return ("ᓚᘏᗢ 𝘻", DIMC) }
        if att > 0 { return ("ᓚᘏᗢ ●\(att)", ORANGE) }
        if wrk > 0 { return ("ᓚᘏᗢ ●\(wrk)", BLUE) }
        return ("ᓚᘏᗢ ✓", GREEN)
    }

    func label(_ text: String, _ color: NSColor, size: CGFloat, bold: Bool = false) -> NSTextField {
        let l = NSTextField(labelWithString: text)
        l.font = bold ? NSFont.monospacedSystemFont(ofSize: size, weight: .bold)
                      : NSFont.monospacedSystemFont(ofSize: size, weight: .regular)
        l.textColor = color
        l.backgroundColor = .clear
        l.isBezeled = false
        l.sizeToFit()
        return l
    }

    @objc func rowClicked(_ sender: NSButton) {
        run(["\(sender.tag)"])
        collapse()
    }
    @objc func boardClicked(_ s: NSButton) { run(["board"]); collapse() }
    @objc func newClicked(_ s: NSButton) { run(["new"]); collapse() }

    func run(_ args: [String]) {
        let p = Process()
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        p.executableURL = URL(fileURLWithPath: home + "/bin/fleet-jump")
        p.arguments = args
        try? p.run()
    }

    func place(width: CGFloat, height: CGFloat) {
        guard let screen = NSScreen.main else { return }
        let vf = screen.visibleFrame
        let x = vf.midX - width / 2
        let y = vf.maxY - height
        panel.setFrame(NSRect(x: x, y: y, width: width, height: height),
                       display: true, animate: true)
        root.layer?.cornerRadius = expanded ? 14 : pillH / 2
    }

    func rebuild() {
        root.subviews.forEach { $0.removeFromSuperview() }
        if expanded { buildExpanded() } else { buildPill() }
    }

    func buildPill() {
        let (text, color) = pillText()
        let l = label(text, color, size: 13, bold: true)
        let w = l.frame.width + 28
        place(width: max(90, w), height: pillH)
        l.frame.origin = NSPoint(x: 14, y: (pillH - l.frame.height) / 2)
        root.addSubview(l)
    }

    func buildExpanded() {
        let rows = sessions
        let rowH: CGFloat = 22
        let headH: CGFloat = 30
        let footH: CGFloat = 32
        let h = headH + CGFloat(max(1, rows.count)) * rowH + footH + 12
        place(width: expW, height: h)

        let att = rows.filter { $0.state == "attention" }.count
        let wrk = rows.filter { $0.state == "working" }.count
        var hdr: [String] = []
        if att > 0 { hdr.append("NEEDS YOU · \(att)") }
        if wrk > 0 { hdr.append("WORKING · \(wrk)") }
        if hdr.isEmpty { hdr.append("ALL QUIET") }
        let hl = label(hdr.joined(separator: "   "), att > 0 ? ORANGE : DIMC, size: 11, bold: true)
        hl.frame.origin = NSPoint(x: 16, y: h - 24)
        root.addSubview(hl)

        var y = h - headH - rowH
        for s in rows {
            let b = NSButton(frame: NSRect(x: 8, y: y, width: expW - 16, height: rowH))
            b.isBordered = false
            b.tag = s.wid
            b.target = self
            b.action = #selector(rowClicked(_:))
            var bits = s.title
            if !s.ctx.isEmpty { bits += "   \(s.ctx)%" }
            if let c = Double(s.cost) { bits += "  $\(Int(c))" }
            let a = NSMutableAttributedString(
                string: "● ", attributes: [.foregroundColor: stateColor(s.state),
                                           .font: NSFont.monospacedSystemFont(ofSize: 12, weight: .bold)])
            a.append(NSAttributedString(
                string: bits, attributes: [.foregroundColor: s.state == "neutral" ? DIMC : INK,
                                           .font: NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)]))
            b.attributedTitle = a
            b.alignment = .left
            root.addSubview(b)
            y -= rowH
        }

        let bb = NSButton(frame: NSRect(x: 12, y: 8, width: 150, height: 20))
        bb.isBordered = false
        bb.target = self
        bb.action = #selector(boardClicked(_:))
        bb.attributedTitle = NSAttributedString(
            string: "◫ Fleet Board", attributes: [.foregroundColor: AMBER,
                .font: NSFont.monospacedSystemFont(ofSize: 12, weight: .semibold)])
        bb.alignment = .left
        root.addSubview(bb)
        let nb = NSButton(frame: NSRect(x: expW - 160, y: 8, width: 148, height: 20))
        nb.isBordered = false
        nb.target = self
        nb.action = #selector(newClicked(_:))
        nb.attributedTitle = NSAttributedString(
            string: "+ New Session", attributes: [.foregroundColor: INK,
                .font: NSFont.monospacedSystemFont(ofSize: 12, weight: .semibold)])
        nb.alignment = .right
        root.addSubview(nb)
    }

    func expand() {
        collapseTimer?.invalidate()
        if expanded { return }
        expanded = true
        rebuild()
    }
    func scheduleCollapse() {
        collapseTimer?.invalidate()
        collapseTimer = Timer.scheduledTimer(withTimeInterval: 0.35, repeats: false) { [weak self] _ in
            self?.collapse()
        }
    }
    func collapse() {
        if !expanded { return }
        expanded = false
        rebuild()
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = App()
app.delegate = delegate
app.run()
