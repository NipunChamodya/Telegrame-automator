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
        for screen in ["Chats", "Contacts", "Groups", "Channels", "Saved Messages", "Advanced Workspace", "Accounts", "Settings"] {
            let item = app.outlines.staticTexts[screen].firstMatch
            XCTAssertTrue(item.waitForExistence(timeout: 5), "Sidebar item: \(screen)")
            item.click(); capture(screen.lowercased(), app: app)
        }
        for tool in ["Dashboard", "Group Management", "Permissions", "Composer", "Drafts", "Destinations", "History", "Activity", "Message Actions"] {
            app.outlines.staticTexts["Advanced Workspace"].firstMatch.click()
            let item = app.descendants(matching: .any)["advanced_" + tool].firstMatch
            XCTAssertTrue(item.waitForExistence(timeout: 5)); item.click()
            capture(tool.lowercased(), app: app)
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
        var app = launch(["TGM_UI_SCREEN": "Group Management", "TGM_UI_INSPECTOR": "1"])
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
            ("Group Management", "groups", [:]), ("Permissions", "permissions", [:]),
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

extension ScreenshotTests {
    func testContactsProfileFoldersAndImageViewerScreenshots() {
        continueAfterFailure = false
        let cases: [(String, [String: String])] = [
            ("contacts-populated", ["TGM_UI_SCREEN": "Contacts"]),
            ("contacts-empty", ["TGM_UI_SCREEN": "Contacts", "TGM_UI_EMPTY": "1"]),
            ("peer-profile", ["TGM_UI_PROFILE": "1"]),
            ("telegram-folders", ["TGM_UI_FOLDERS": "1"]),
            ("telegram-folders-empty", ["TGM_UI_FOLDERS": "1", "TGM_UI_EMPTY": "1"]),
            ("synthetic-image-viewer", ["TGM_UI_IMAGE": "1"])
        ]
        for (name, flags) in cases { let app = launch(flags); capture(name, app: app); app.terminate() }
    }
}

extension ScreenshotTests {
    private func assertShell(_ app: XCUIApplication, file: StaticString = #filePath, line: UInt = #line) {
        let sidebar = app.descendants(matching: .any)["applicationSidebar"].firstMatch
        let identity = app.descendants(matching: .any)["workspaceIdentity"].firstMatch
        let content = app.descendants(matching: .any)["workspaceContent"].firstMatch
        XCTAssertTrue(sidebar.waitForExistence(timeout: 5), file: file, line: line)
        XCTAssertTrue(identity.exists, file: file, line: line)
        XCTAssertTrue(content.exists, file: file, line: line)
        XCTAssertGreaterThan(sidebar.frame.height, app.windows.firstMatch.frame.height * 0.5, file: file, line: line)
        XCTAssertGreaterThanOrEqual(sidebar.frame.width, 210, file: file, line: line)
        XCTAssertGreaterThanOrEqual(content.frame.minX, sidebar.frame.maxX - 2, file: file, line: line)
        let close = app.windows.firstMatch.buttons["_XCUI:CloseWindow"]
        XCTAssertTrue(close.exists, "Native close control is required to verify titlebar clearance", file: file, line: line)
        if close.exists {
            XCTAssertGreaterThanOrEqual(identity.frame.minY, close.frame.maxY - 2, "Sidebar identity must clear traffic lights", file: file, line: line)
            let header = app.descendants(matching: .any)["pageHeader"].firstMatch
            if header.exists { XCTAssertGreaterThanOrEqual(header.frame.minY, close.frame.maxY - 2, file: file, line: line) }
        }
    }
    func testSharedShellSurvivesEveryNavigationCycle() {
        continueAfterFailure = false
        let app = launch()
        for _ in 0..<2 {
            for page in ["Chats", "Contacts", "Groups", "Channels", "Saved Messages", "Accounts", "Settings", "Advanced Workspace"] {
                app.outlines.staticTexts[page].firstMatch.click()
                assertShell(app)
            }
            for tool in ["Dashboard", "Group Management", "Permissions", "Composer", "Drafts", "Destinations", "History", "Activity", "Message Actions"] {
                app.outlines.staticTexts["Advanced Workspace"].firstMatch.click()
                app.descendants(matching: .any)["advanced_" + tool].firstMatch.click()
                assertShell(app)
                capture("shell-" + tool, app: app)
            }
        }
        app.terminate()
    }
    func testResizePreservesSidebarAndConversationGeometry() {
        continueAfterFailure = false
        let app = launch(["TGM_UI_SIZE": "large", "TGM_UI_NO_SELECTION": "1"])
        assertShell(app)
        let window = app.windows.firstMatch
        let corner = window.coordinate(withNormalizedOffset: CGVector(dx: 1, dy: 1)).withOffset(CGVector(dx: -2, dy: -2))
        corner.press(forDuration: 0.2, thenDragTo: window.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: 982, dy: 642)))
        assertShell(app)
        XCTAssertGreaterThan(app.descendants(matching: .any)["conversationList"].firstMatch.frame.height, window.frame.height * 0.4)
        capture("resized-compact-shell", app: app)
        app.terminate()
    }
    func testMinimizeAndRestoreRetainsShell() {
        continueAfterFailure = false
        let app = launch()
        let window = app.windows.firstMatch
        let minimize = window.buttons["_XCUI:MinimizeWindow"]
        XCTAssertTrue(minimize.exists); minimize.click()
        app.menuBars.menuBarItems["Window"].click()
        let restore = app.menuItems["Unofficial Telegram Manager"].firstMatch
        XCTAssertTrue(restore.waitForExistence(timeout: 5)); restore.click()
        XCTAssertTrue(window.waitForExistence(timeout: 5)); assertShell(app)
        capture("restored-shell", app: app); app.terminate()
    }
    func testFixtureAccountSwitchPreservesDraftAndClearsOtherAccountContent() {
        continueAfterFailure = false
        let app = launch()
        let editor = app.textViews["chatComposer"]
        XCTAssertTrue(editor.waitForExistence(timeout: 5)); editor.click()
        editor.typeKey("a", modifierFlags: .command); editor.typeText("Fixture draft belongs to account one")
        app.menuButtons["accountSwitcher"].click()
        app.menuItems["Second Example Account"].click()
        XCTAssertTrue(app.staticTexts["Second Example Account"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(app.textViews["chatComposer"].exists)
        assertShell(app)
        app.menuButtons["accountSwitcher"].click(); app.menuItems["Example Account"].click()
        XCTAssertTrue(app.textViews["chatComposer"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.textViews["chatComposer"].value as? String, "Fixture draft belongs to account one")
        capture("restored-account-draft", app: app); app.terminate()
    }
    func testContactsRefreshAndConversationErrorStates() {
        continueAfterFailure = false
        var app = launch(["TGM_UI_SCREEN": "Contacts", "TGM_UI_CONNECTED": "1", "TGM_UI_CONTACTS_EMPTY": "1"])
        let refresh = app.buttons["refreshContacts"]
        XCTAssertTrue(refresh.waitForExistence(timeout: 5)); XCTAssertTrue(refresh.isEnabled); refresh.click()
        XCTAssertTrue(app.staticTexts["தமிழ் Example Contact"].waitForExistence(timeout: 5))
        capture("refreshed-fixture-contacts", app: app); app.terminate()
        for state in ["TGM_UI_MESSAGES_ERROR", "TGM_UI_MESSAGES_LOADING"] {
            app = launch(["TGM_UI_CONNECTED": "1", state: "1"])
            XCTAssertTrue(app.descendants(matching: .any)[state == "TGM_UI_MESSAGES_ERROR" ? "messagesError" : "messagesLoading"].firstMatch.waitForExistence(timeout: 5))
            assertShell(app); capture(state.lowercased(), app: app); app.terminate()
        }
    }
}
