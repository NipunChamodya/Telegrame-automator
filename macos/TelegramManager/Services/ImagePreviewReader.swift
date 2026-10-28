import Foundation
import Darwin
import ImageIO

struct DecodedPreviewImage: @unchecked Sendable { let image: CGImage }

enum ImagePreviewReader {
    static let byteLimit = 8 * 1024 * 1024
    static func decode(path: String, expectedBytes: Int, mimeType: String) throws -> DecodedPreviewImage {
        try Task.checkCancellation()
        guard ["image/jpeg", "image/png"].contains(mimeType), expectedBytes > 0, expectedBytes <= byteLimit else { throw invalid() }
        let fd = Darwin.open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard fd >= 0 else { throw invalid() }
        defer { Darwin.close(fd) }
        var info = stat()
        guard fstat(fd, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG, info.st_uid == geteuid(), info.st_nlink == 1,
              info.st_mode & 0o077 == 0, info.st_size == expectedBytes, info.st_size <= byteLimit else { throw invalid() }
        var data = Data(), buffer = [UInt8](repeating: 0, count: 32_768)
        while true {
            try Task.checkCancellation()
            let count = Darwin.read(fd, &buffer, buffer.count)
            if count < 0 { if errno == EINTR { continue }; throw invalid() }
            if count == 0 { break }
            data.append(contentsOf: buffer.prefix(count))
            guard data.count <= byteLimit else { throw invalid() }
        }
        guard data.count == expectedBytes, let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary), CGImageSourceGetCount(source) == 1,
              let type = CGImageSourceGetType(source) as String?, type == (mimeType == "image/png" ? "public.png" : "public.jpeg"),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? NSNumber, let height = properties[kCGImagePropertyPixelHeight] as? NSNumber else { throw invalid() }
        let w = width.intValue, h = height.intValue
        guard w > 0, h > 0, w <= 16_000_000 / h else { throw invalid() }
        try Task.checkCancellation()
        let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: 1600, kCGImageSourceShouldCacheImmediately: true, kCGImageSourceShouldAllowFloat: false]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary), image.width <= 1600, image.height <= 1600 else { throw invalid() }
        try Task.checkCancellation()
        return DecodedPreviewImage(image: image)
    }
    private static func invalid() -> BackendFailure { BackendFailure(code: "preview_invalid", message: "This private preview could not be opened safely. Only regular owned JPEG or PNG images up to 8 MiB and 16 megapixels are supported.") }
}
