import XCTest

final class ScreenshotTests: XCTestCase {
    private func launch(_ extra: [String: String] = [:]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment = ["TGM_TEST_MODE": "1", "TGM_UI_FIXTURE": "1", "TGM_NO_AUTO_CONNECT": "1", "TGM_DATA_DIR": NSTemporaryDirectory() + "tgm-ui-fixture-" + UUID().uuidString, "TGM_UI_SIZE": ProcessInfo.processInfo.environment["TGM_SCREENSHOT_SIZE"] ?? "standard"]
        app.launchEnvironment.merge(extra) { _, new in new }
        let style = ProcessInfo.processInfo.environment["TGM_SCREENSHOT_APPEARANCE"] ?? "light"
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US", "-appearance", style == "dark" ? "dark" : "light"]
        app.launch()
        XCTAssertTrue(app.windows.firstMatch.waitForExistence(timeout: 15))
        return app
    }
    private func capture(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.windows.firstMatch.screenshot())
        attachment.name = "fixture-" + name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
    func testNativeScreenshotsWithSyntheticData() throws {
        continueAfterFailure = false
        let app = launch()
        for screen in ["Dashboard", "Chats", "Groups", "Permissions", "Composer", "Drafts", "Destinations", "History", "Activity", "Accounts", "Settings"] {
            let item = app.outlines.staticTexts[screen].firstMatch
            XCTAssertTrue(item.waitForExistence(timeout: 5), "Sidebar item: \(screen)")
            item.click(); capture(screen.lowercased(), app: app)
        }
        app.terminate()
    }
    func testOnboardingAuthenticationStates() {
        continueAfterFailure = false
        for (stage, name) in [("credentials", "welcome-api-setup"), ("phone", "phone-entry"), ("code", "verification-code"), ("password", "two-step-verification"), ("bind_account", "account-binding")] {
            let app = launch(["TGM_UI_AUTH_STAGE": stage])
            XCTAssertTrue(app.descendants(matching: .any)["authenticationSheet"].waitForExistence(timeout: 5))
            capture(name, app: app); app.terminate()
        }
    }
    func testInspectorEmptyErrorAndSwitcherStates() {
        continueAfterFailure = false
        var app = launch(["TGM_UI_SCREEN": "Groups", "TGM_UI_INSPECTOR": "1"])
        capture("group-inspector", app: app); app.terminate()
        app = launch(["TGM_UI_SCREEN": "Chats", "TGM_UI_EMPTY": "1"])
        capture("empty-conversations", app: app); app.terminate()
        app = launch(["TGM_UI_ERROR": "1"])
        XCTAssertTrue(app.alerts.firstMatch.waitForExistence(timeout: 5))
        capture("backend-error", app: app); app.terminate()
        app = launch()
        let switcher = app.menuButtons["accountSwitcher"]
        XCTAssertTrue(switcher.waitForExistence(timeout: 5)); switcher.click()
        capture("account-switcher", app: app); app.terminate()
    }
    func testDisconnectedRecoveryAndDiagnostics() {
        continueAfterFailure = false
        let app = launch()
        XCTAssertTrue(app.buttons["retryConnection"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["recoveryManageAccounts"].exists)
        let diagnostics = app.buttons["openConnectionDiagnostics"]
        XCTAssertTrue(diagnostics.exists)
        diagnostics.click()
        XCTAssertTrue(app.descendants(matching: .any)["connectionDiagnosticsSheet"].waitForExistence(timeout: 5))
        capture("connection-diagnostics", app: app)
        app.buttons["Close"].firstMatch.click()
        app.buttons["recoveryManageAccounts"].click()
        XCTAssertTrue(app.descendants(matching: .any)["accountList"].waitForExistence(timeout: 5))
        app.terminate()
    }
    func testCompactComposerValidationNeverSends() {
        continueAfterFailure = false
        let app = launch(["TGM_UI_SCREEN": "Composer", "TGM_UI_SIZE": "compact"])
        let editor = app.textViews["messageEditor"]
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        editor.click()
        editor.typeKey("a", modifierFlags: .command)
        editor.typeText("A safe synthetic draft")
        let preview = app.buttons["previewMessage"]
        XCTAssertTrue(preview.exists)
        XCTAssertFalse(preview.isEnabled, "No destination is approved in the fixture")
        XCTAssertFalse(app.buttons["sendOnce"].exists, "Composition must not create a send approval")
        capture("compact-composer-validation", app: app)
        app.terminate()
    }

}
