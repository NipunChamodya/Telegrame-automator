import SwiftUI
import AppKit
import AVKit
import Quartz

struct ImagePreviewView: View {
    @ObservedObject var model: AppModel
    let context: MediaPreviewContext
    @State private var zoom: CGFloat = 1
    @State private var player: AVPlayer?
    @State private var playbackError: String?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        VStack(spacing: 16) {
            HStack {
                Label(context.kind.capitalized, systemImage: "paperclip").font(.title2.weight(.semibold)).accessibilityAddTraits(.isHeader)
                Spacer()
                if context.kind == "photo" || context.mimeType == "image/gif" {
                    Button("Zoom Out", systemImage: "minus.magnifyingglass") { zoom = max(0.25, zoom / 1.5) }.labelStyle(.iconOnly).keyboardShortcut("-", modifiers: .command)
                    Button("Actual Size") { zoom = 1 }.keyboardShortcut("0", modifiers: .command)
                    Button("Zoom In", systemImage: "plus.magnifyingglass") { zoom = min(8, zoom * 1.5) }.labelStyle(.iconOnly).keyboardShortcut("+", modifiers: .command)
                }
                Button("Full Screen", systemImage: "arrow.up.left.and.arrow.down.right") { NSApp.mainWindow?.toggleFullScreen(nil) }.help("Toggle full screen")
                Button("Close") { model.closeMediaPreview() }.keyboardShortcut(.cancelAction)
            }
            if context.category == "view_once" {
                Label("View once · closes permanently when dismissed", systemImage: "1.circle").font(.callout)
            } else if context.category != "ordinary" {
                TimelineView(.periodic(from: .now, by: 1)) { clock in
                    Label("\(max(0, Int(ceil(context.expiresAt - clock.date.timeIntervalSince1970)))) seconds remaining", systemImage: "timer")
                        .monospacedDigit().accessibilityLabel("Time remaining before media expires")
                }
            }
            Group {
                if let image = model.previewImage { NativeImagePreview(image: image, animated: false, zoom: zoom) }
                else if context.mimeType == "image/gif" {
                    AnimatedMediaImage(path: context.path, animated: !reduceMotion, zoom: zoom)
                } else if context.playbackSupported {
                    if let player { NativeMediaPlayer(player: player).accessibilityLabel(context.kind == "voice" ? "Voice message player" : "Media player") }
                    else { ProgressView("Preparing playback…") }
                } else if context.documentSupported {
                    DocumentMediaPreview(path: context.path)
                } else {
                    ContentUnavailableView("Preview unavailable", systemImage: "doc", description: Text("You can save this attachment and open it with a compatible application."))
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            if let playbackError { Label(playbackError, systemImage: "exclamationmark.triangle").foregroundStyle(.red) }
            HStack {
                Text("\(context.mimeType) · \(ByteCountFormatter.string(fromByteCount: Int64(context.bytes), countStyle: .file))").font(.caption).foregroundStyle(.secondary)
                Spacer()
                if context.canSave { Button("Save As…") { model.savePreviewAttachment() }.keyboardShortcut("s", modifiers: .command).disabled(model.busy || !model.connected) }
            }
        }.padding(22).frame(minWidth: 520, idealWidth: 800, minHeight: 420, idealHeight: 620)
            .accessibilityIdentifier("imagePreviewSheet")
            .task(id: context.token) {
                guard context.playbackSupported else { return }
                let asset = AVURLAsset(url: URL(fileURLWithPath: context.path))
                do {
                    guard try await asset.load(.isPlayable) else { playbackError = "This format cannot play on this Mac. Save it to use another application."; return }
                    try Task.checkCancellation()
                    player = AVPlayer(playerItem: AVPlayerItem(asset: asset))
                } catch is CancellationError { } catch { playbackError = "Playback could not be prepared. Close and try again." }
            }
            .onDisappear { player?.pause(); player?.replaceCurrentItem(with: nil); player = nil }
    }
}
private final class CenteredMediaScrollView: NSScrollView {
    override func layout() {
        super.layout()
        documentView?.frame = NSRect(origin: .zero, size: contentSize)
    }
}
private struct NativeImagePreview: NSViewRepresentable {
    let image: NSImage
    let animated: Bool
    var zoom: CGFloat = 1
    func makeNSView(context: Context) -> NSScrollView {
        let scroll = CenteredMediaScrollView()
        scroll.hasVerticalScroller = true; scroll.hasHorizontalScroller = true
        scroll.allowsMagnification = true; scroll.minMagnification = 0.25; scroll.maxMagnification = 8
        let view = NSImageView(frame: NSRect(origin: .zero, size: NSSize(width: min(image.size.width, 760), height: min(image.size.height, 500))))
        view.imageScaling = .scaleProportionallyUpOrDown; view.image = image; view.animates = animated
        view.setAccessibilityLabel("Photo. Pinch to zoom; use scroll bars to pan.")
        scroll.documentView = view
        return scroll
    }
    func updateNSView(_ scroll: NSScrollView, context: Context) {
        if scroll.magnification != zoom { scroll.magnification = zoom }
        if let view = scroll.documentView as? NSImageView { view.image = image; view.animates = animated }
    }
}
private struct AnimatedMediaImage: View {
    let path: String
    let animated: Bool
    let zoom: CGFloat
    @State private var image: NSImage?
    var body: some View {
        Group { if let image { NativeImagePreview(image: image, animated: animated, zoom: zoom) } else { ProgressView("Opening animation…") } }
            .task(id: path) {
                // Validation bounds decoded frames before AppKit receives this file.
                image = NSImage(contentsOfFile: path)
            }
    }
}
private struct DocumentMediaPreview: NSViewRepresentable {
    let path: String
    func makeNSView(context: Context) -> QLPreviewView {
        let view = QLPreviewView(frame: .zero, style: .normal)!
        view.autostarts = false
        view.previewItem = URL(fileURLWithPath: path) as NSURL
        return view
    }
    func updateNSView(_ view: QLPreviewView, context: Context) { view.previewItem = URL(fileURLWithPath: path) as NSURL }
    static func dismantleNSView(_ view: QLPreviewView, coordinator: ()) { view.close() }
}

private struct NativeMediaPlayer: NSViewRepresentable {
    let player: AVPlayer
    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.controlsStyle = .inline
        view.showsSharingServiceButton = false
        view.showsFullScreenToggleButton = true
        view.player = player
        view.setAccessibilityLabel("Media player")
        return view
    }
    func updateNSView(_ view: AVPlayerView, context: Context) { view.player = player }
    static func dismantleNSView(_ view: AVPlayerView, coordinator: ()) { view.player?.pause(); view.player = nil }
}
