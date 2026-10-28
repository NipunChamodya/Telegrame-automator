import XCTest
import CoreGraphics
import ImageIO
import Darwin
@testable import TelegramManager

final class ClientFeaturesTests: XCTestCase {
    private func imageFile(width: Int = 64, height: Int = 32) throws -> (URL, Int) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("tgm-image-test-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let file = directory.appendingPathComponent("preview.png")
        let context = try XCTUnwrap(CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        let image = try XCTUnwrap(context.makeImage())
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(file as CFURL, "public.png" as CFString, 1, nil))
        CGImageDestinationAddImage(destination, image, nil)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        XCTAssertEqual(chmod(file.path, 0o600), 0)
        return (file, try Data(contentsOf: file).count)
    }
    func testOwnedStaticImageDecodesAndDownsamplesToSixteenHundred() async throws {
        let (file, size) = try imageFile(width: 2000, height: 1000)
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let decoded = try await Task.detached { try ImagePreviewReader.decode(path: file.path, expectedBytes: size, mimeType: "image/png") }.value
        XCTAssertEqual(decoded.image.width, 1600); XCTAssertEqual(decoded.image.height, 800)
    }
    func testImagePreviewRejectsLinksAndNonprivateFiles() throws {
        let (file, size) = try imageFile()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let symlink = file.deletingLastPathComponent().appendingPathComponent("symlink.png")
        try FileManager.default.createSymbolicLink(at: symlink, withDestinationURL: file)
        XCTAssertThrowsError(try ImagePreviewReader.decode(path: symlink.path, expectedBytes: size, mimeType: "image/png"))
        let hardlink = file.deletingLastPathComponent().appendingPathComponent("hardlink.png")
        try FileManager.default.linkItem(at: file, to: hardlink)
        XCTAssertThrowsError(try ImagePreviewReader.decode(path: file.path, expectedBytes: size, mimeType: "image/png"))
        try FileManager.default.removeItem(at: hardlink)
        XCTAssertEqual(chmod(file.path, 0o644), 0)
        XCTAssertThrowsError(try ImagePreviewReader.decode(path: file.path, expectedBytes: size, mimeType: "image/png"))
    }
    func testImagePreviewRejectsOversizeUnexpectedMimeAndPixelBombs() throws {
        let (file, size) = try imageFile()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        XCTAssertThrowsError(try ImagePreviewReader.decode(path: file.path, expectedBytes: ImagePreviewReader.byteLimit + 1, mimeType: "image/png"))
        XCTAssertThrowsError(try ImagePreviewReader.decode(path: file.path, expectedBytes: size, mimeType: "image/jpeg"))
        XCTAssertThrowsError(try ImagePreviewReader.decode(path: file.path, expectedBytes: size, mimeType: "image/gif"))
        let (large, largeSize) = try imageFile(width: 4001, height: 4001)
        defer { try? FileManager.default.removeItem(at: large.deletingLastPathComponent()) }
        XCTAssertThrowsError(try ImagePreviewReader.decode(path: large.path, expectedBytes: largeSize, mimeType: "image/png"))
    }
    func testContactIdentityPreservesUnicodeWithoutInventingAvailability() {
        let contact = TelegramContact(data: .object(["id": .integer(202), "name": .string("தமிழ் 👩🏽‍💻"), "username": .string("example")]))
        XCTAssertEqual(contact.name, "தமிழ் 👩🏽‍💻"); XCTAssertEqual(contact.id, 202); XCTAssertFalse(contact.available)
        XCTAssertEqual(PeerProfile(data: .object(["id": .integer(203), "name": .string("ශ්‍රී ලංකා")])).name, "ශ්‍රී ලංකා")
    }
}
