import XCTest
import AVFoundation
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

final class MediaV4NativeTests: XCTestCase {
    func testSafeSuggestedNamesDoNotPreserveExecutableExtensionsOrPaths() {
        XCTAssertEqual(MediaFilename.suggested("../../photo.app", mime: "image/png"), "photo.png")
        XCTAssertEqual(MediaFilename.suggested("C:\\private\\run.sh", mime: "application/octet-stream"), "run.bin")
        XCTAssertEqual(MediaFilename.suggested(".hidden", mime: "application/pdf"), "Attachment.pdf")
    }
    func testDuplicateNamesChooseAnAvailableAlternative() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        try Data().write(to: folder.appendingPathComponent("photo.png"))
        XCTAssertEqual(MediaFilename.available("photo.png", in: folder), "photo (1).png")
    }
    func testTimedContextNeverInventsExportCapability() {
        let scope = UpdateScope(profileID: "fixture", accountID: 1, generation: 0)
        let context = MediaPreviewContext(scope: scope, token: "once", peerID: 2, messageID: 3, bytes: 100, mimeType: "video/mp4", canSave: false, category: "view_once")
        XCTAssertFalse(context.canSave)
        XCTAssertTrue(context.playbackSupported)
        XCTAssertFalse(context.documentSupported)
    }
    func testBoundedAnimatedGIFValidation() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".gif")
        defer { try? FileManager.default.removeItem(at: url) }
        let bitmap = try XCTUnwrap(CGContext(data: nil, width: 8, height: 8, bitsPerComponent: 8, bytesPerRow: 32, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        let image = try XCTUnwrap(bitmap.makeImage())
        let writer = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, "com.compuserve.gif" as CFString, 2, nil))
        for _ in 0..<2 { CGImageDestinationAddImage(writer, image, nil) }
        XCTAssertTrue(CGImageDestinationFinalize(writer)); XCTAssertEqual(chmod(url.path, 0o600), 0)
        let size = try Data(contentsOf: url).count
        XCTAssertNoThrow(try ImagePreviewReader.validateMedia(path: url.path, expectedBytes: size, mimeType: "image/gif"))
        XCTAssertThrowsError(try ImagePreviewReader.validateMedia(path: url.path, expectedBytes: size + 1, mimeType: "image/gif"))
        XCTAssertEqual(chmod(url.path, 0o644), 0)
        XCTAssertThrowsError(try ImagePreviewReader.validateMedia(path: url.path, expectedBytes: size, mimeType: "image/gif"))
    }
}

extension MediaV4NativeTests {
    func testSyntheticVideoIsValidatedAndPlayableWithNativePlayer() async throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let source = root.appendingPathComponent("tests/fixtures/media/synthetic-video.mp4")
        let target = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".mp4")
        try FileManager.default.copyItem(at: source, to: target)
        defer { try? FileManager.default.removeItem(at: target) }
        XCTAssertEqual(chmod(target.path, 0o600), 0)
        let size = try Data(contentsOf: target).count
        try ImagePreviewReader.validateMedia(path: target.path, expectedBytes: size, mimeType: "video/mp4")
        let asset = AVURLAsset(url: target)
        let playable = try await asset.load(.isPlayable)
        XCTAssertTrue(playable)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        XCTAssertEqual(tracks.count, 1)
    }
}


final class SmartArchiveTests: XCTestCase {
    func testCustomDateIncludesFinalDayAcrossDaylightSaving() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: "America/New_York"))
        let date = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 3, day: 8)))
        var draft = ArchiveDraft(); draft.range = "custom"; draft.start = date; draft.end = date
        let range = draft.bounds(now: date, calendar: calendar)
        XCTAssertEqual(range.1 - range.0, 23 * 3600)
    }
    func testArchiveRequiresMediaFolderAndValidDates() {
        var draft = ArchiveDraft()
        XCTAssertFalse(draft.valid)
        draft.folder = FileManager.default.temporaryDirectory
        XCTAssertTrue(draft.valid)
        draft.types = []; XCTAssertFalse(draft.valid)
        draft.types = ["photo"]; draft.range = "custom"; draft.start = Date().addingTimeInterval(86400 * 2); draft.end = Date()
        XCTAssertFalse(draft.valid)
    }
    func testEveryArchiveStateHasSimpleLanguage() {
        let expected = ["finding": "Finding media", "saving": "Saving", "paused": "Paused", "waiting": "Waiting for Telegram", "attention": "Needs attention", "finished": "Finished", "cancelled": "Cancelled"]
        for (state, title) in expected {
            let job = ArchiveJob(data: .object(["id": .string("fixture"), "state": .string(state)]))
            XCTAssertEqual(job.status, title)
        }
    }
    func testArchiveTargetRetainsConversationAndAccountIdentity() {
        let scope = UpdateScope(profileID: "one", accountID: 11, generation: 3)
        let chat = ChatSummary(data: .object(["id": .integer(22), "kind": .string("private"), "name": .string("Family")]))
        let target = ArchiveTarget(scope: scope, chat: chat)
        XCTAssertEqual(target.scope, scope); XCTAssertEqual(target.chat.id, 22)
        XCTAssertNotEqual(target.id, ArchiveTarget(scope: UpdateScope(profileID: "two", accountID: 12, generation: 4), chat: chat).id)
    }
    func testChannelAccessRequiresExplicitSponsoredCapability() {
        XCTAssertFalse(ChatSummary(data: .object(["kind": .string("channel"), "content_available": .bool(true)])).contentAvailable)
        XCTAssertTrue(ChatSummary(data: .object(["kind": .string("channel"), "content_available": .bool(true), "sponsored_ready": .bool(true)])).contentAvailable)
    }
}
