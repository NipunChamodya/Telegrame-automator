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
        let app = launch(["TGM_UI_SCREEN": "Composer", "TGM_UI_SIZE": "compact", "TGM_UI_DESTINATIONS_EMPTY": "1"])
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

    func testConversationListGeometrySearchPaginationAndSelection() {
        continueAfterFailure = false
        let app = launch(["TGM_UI_SCREEN": "Chats", "TGM_UI_NO_SELECTION": "1", "TGM_UI_SIZE": "standard"])
        let list = app.descendants(matching: .any)["conversationList"].firstMatch
        XCTAssertTrue(list.waitForExistence(timeout: 5))
        XCTAssertGreaterThan(list.frame.height, app.windows.firstMatch.frame.height * 0.45, "Conversation list must use available vertical space")
        XCTAssertGreaterThanOrEqual(list.frame.width, 250)
        let search = app.textFields["conversationSearch"]
        XCTAssertTrue(search.exists)
        search.click(); search.typeText("example_198")
        XCTAssertTrue(app.staticTexts["1 cached · Page 1"].waitForExistence(timeout: 5))
        search.typeKey("a", modifierFlags: .command); search.typeKey(XCUIKeyboardKey.delete, modifierFlags: [])
        XCTAssertTrue(app.staticTexts["198 cached · Page 1"].waitForExistence(timeout: 5))
        let pagination = app.descendants(matching: .any)["conversationPagination"].firstMatch
        XCTAssertTrue(pagination.waitForExistence(timeout: 5))
        XCTAssertGreaterThanOrEqual(pagination.frame.minY, list.frame.maxY - 2, "Pagination must remain below the list")
        XCTAssertLessThanOrEqual(pagination.frame.maxY, app.windows.firstMatch.frame.maxY)
        let next = pagination.buttons["Next"]
        XCTAssertTrue(next.exists); XCTAssertTrue(next.isEnabled)
        next.click()
        let row = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "chatRow_")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 5)); row.click()
        let detail = app.descendants(matching: .any)["conversationDetail"].firstMatch
        XCTAssertTrue(detail.waitForExistence(timeout: 5))
        XCTAssertGreaterThan(detail.frame.height, 220)
        capture("conversation-list-filled", app: app)
        app.terminate()
    }
    func testIntegratedEmptyStateActionsAndHistoryFilters() {
        continueAfterFailure = false
        var app = launch(["TGM_UI_SCREEN": "Destinations", "TGM_UI_DESTINATIONS_EMPTY": "1"])
        XCTAssertTrue(app.buttons["Browse Groups"].waitForExistence(timeout: 5))
        app.buttons["Browse Groups"].click()
        XCTAssertTrue(app.descendants(matching: .any)["groupTable"].waitForExistence(timeout: 5))
        app.terminate()
        app = launch(["TGM_UI_SCREEN": "History"])
        XCTAssertTrue(app.descendants(matching: .any)["historyStatusFilter"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["historySort"].exists)
        let table = app.descendants(matching: .any)["deliveryHistoryTable"].firstMatch
        XCTAssertTrue(table.exists)
        let statusFilter = app.popUpButtons["historyStatusFilter"]
        XCTAssertTrue(statusFilter.exists); statusFilter.click()
        let uncertain = app.menuItems["Uncertain"]
        XCTAssertTrue(uncertain.waitForExistence(timeout: 3)); uncertain.click()
        XCTAssertTrue(table.staticTexts["Uncertain"].waitForExistence(timeout: 3))
        XCTAssertFalse(table.staticTexts["Sent"].exists)
        let sorting = app.popUpButtons["historySort"]
        sorting.click(); app.menuItems["Oldest"].click()
        capture("history-filters", app: app)
        app.terminate()
        app = launch(["TGM_UI_SCREEN": "History", "TGM_UI_HISTORY_EMPTY": "1"])
        XCTAssertTrue(app.buttons["Compose a Message"].waitForExistence(timeout: 5))
        app.buttons["Compose a Message"].click()
        XCTAssertTrue(app.textViews["messageEditor"].waitForExistence(timeout: 5))
        app.terminate()
    }

    func testRequiredPresentationScreenshotStates() {
        continueAfterFailure = false
        let states: [(String, String, [String: String])] = [
            ("Dashboard", "dashboard", [:]),
            ("Chats", "chats-populated", ["TGM_UI_NO_SELECTION":"1"]),
            ("Chats", "chats-empty", ["TGM_UI_EMPTY":"1"]),
            ("Chats", "conversation-selected", [:]),
            ("Activity", "activity-populated", [:]),
            ("Activity", "activity-empty", ["TGM_UI_ACTIVITY_EMPTY":"1"]),
            ("History", "history-populated", [:]),
            ("History", "history-empty", ["TGM_UI_HISTORY_EMPTY":"1"]),
            ("Destinations", "destinations-populated", [:]),
            ("Destinations", "destinations-empty", ["TGM_UI_DESTINATIONS_EMPTY":"1"]),
            ("Groups", "groups", [:]), ("Permissions", "permissions", [:]),
            ("Composer", "composer", [:]), ("Drafts", "drafts", [:]),
            ("Accounts", "accounts", [:]), ("Settings", "settings", [:])
        ]
        for (screen, name, flags) in states {
            let app = launch(flags.merging(["TGM_UI_SCREEN":screen]) { _, new in new })
            capture(name, app: app)
            app.terminate()
        }
    }

}
