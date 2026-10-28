import SwiftUI
import AppKit

struct ImagePreviewView: View {
    @ObservedObject var model: AppModel
    let context: MediaPreviewContext
    var body: some View {
        VStack(spacing: 16) {
            HStack { Label("Image Preview", systemImage: "photo").font(.title2.weight(.semibold)); Spacer(); Button("Close") { model.closeMediaPreview() } }
            if let image = model.previewImage { NativeImagePreview(image: image).frame(maxWidth: .infinity, maxHeight: .infinity) }
            else { ContentUnavailableView("Preview unavailable", systemImage: "photo", description: Text("The private preview was closed or expired.")) }
            HStack { Text("\(context.mimeType) · \(ByteCountFormatter.string(fromByteCount: Int64(context.bytes), countStyle: .file))").font(.caption).foregroundStyle(.secondary); Spacer(); Button("Save As…") { model.savePreviewAttachment() }.disabled(model.busy || !model.connected) }
            Text("Explicitly downloaded static image. Closing, account changes, or removal of the message clears this viewer.").font(.caption).foregroundStyle(.secondary)
        }.padding(22).frame(width: 720, height: 600).accessibilityIdentifier("imagePreviewSheet")
    }
}
private struct NativeImagePreview: NSViewRepresentable {
    let image: NSImage
    func makeNSView(context: Context) -> NSImageView {
        let view = NSImageView(); view.imageScaling = .scaleProportionallyUpOrDown; view.imageAlignment = .alignCenter; view.animates = false; return view
    }
    func updateNSView(_ view: NSImageView, context: Context) { view.image = image }
}
