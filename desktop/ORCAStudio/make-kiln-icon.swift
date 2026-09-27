import AppKit

guard CommandLine.arguments.count == 2 else {
    fputs("usage: make-kiln-icon.swift OUTPUT.iconset\n", stderr)
    exit(2)
}

let output = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)

let variants: [(String, Int)] = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]

for (filename, pixels) in variants {
    let size = NSSize(width: pixels, height: pixels)
    guard let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: pixels,
        pixelsHigh: pixels,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ), let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        fatalError("Could not create bitmap for \(filename)")
    }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context

    let bounds = NSRect(origin: .zero, size: size)
    let inset = CGFloat(pixels) * 0.055
    let tile = bounds.insetBy(dx: inset, dy: inset)
    let radius = CGFloat(pixels) * 0.215
    let path = NSBezierPath(roundedRect: tile, xRadius: radius, yRadius: radius)
    let gradient = NSGradient(colors: [
        NSColor(calibratedRed: 0.07, green: 0.095, blue: 0.105, alpha: 1),
        NSColor(calibratedRed: 0.025, green: 0.035, blue: 0.04, alpha: 1),
    ])!
    gradient.draw(in: path, angle: -90)

    let ring = NSBezierPath(roundedRect: tile.insetBy(dx: inset * 0.55, dy: inset * 0.55),
                            xRadius: radius * 0.78, yRadius: radius * 0.78)
    ring.lineWidth = max(1, CGFloat(pixels) * 0.018)
    NSColor(calibratedRed: 1.0, green: 0.45, blue: 0.12, alpha: 0.72).setStroke()
    ring.stroke()

    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .center
    let font = NSFont.systemFont(ofSize: CGFloat(pixels) * 0.52, weight: .black)
    let shadow = NSShadow()
    shadow.shadowColor = NSColor(calibratedRed: 1.0, green: 0.28, blue: 0.04, alpha: 0.9)
    shadow.shadowBlurRadius = CGFloat(pixels) * 0.065
    let attributes: [NSAttributedString.Key: Any] = [
        .font: font,
        .foregroundColor: NSColor(calibratedRed: 1.0, green: 0.67, blue: 0.28, alpha: 1),
        .paragraphStyle: paragraph,
        .shadow: shadow,
    ]
    let text = NSAttributedString(string: "K", attributes: attributes)
    let textHeight = text.size().height
    text.draw(in: NSRect(x: 0, y: (CGFloat(pixels) - textHeight) / 2 + CGFloat(pixels) * 0.015,
                         width: CGFloat(pixels), height: textHeight))
    context.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()

    guard let png = bitmap.representation(using: .png, properties: [:]) else {
        fatalError("Could not render \(filename)")
    }
    try png.write(to: output.appendingPathComponent(filename))
}
