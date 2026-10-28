import SwiftUI
import AppKit

@main struct TelegramManagerApp: App {
    @NSApplicationDelegateAdaptor(ApplicationDelegate.self) var delegate
    @StateObject private var model = AppModel()
    @AppStorage("appearance") private var appearance = "system"
    private var fixtureWindowSize: CGSize {
        #if DEBUG
        if ProcessInfo.processInfo.environment["TGM_UI_FIXTURE"] == "1" {
            let size = ProcessInfo.processInfo.environment["TGM_UI_SIZE"]
            if size == "compact" { return CGSize(width: 980, height: 640) }
            if size == "large" { return CGSize(width: 1500, height: 960) }
        }
        #endif
        return CGSize(width: 1260, height: 820)
    }
    var body: some Scene {
        Window("Telegram Manager", id: "workspace") {
            RootView(model: model)
                .frame(minWidth: 980, minHeight: 640)
                .preferredColorScheme(appearance == "light" ? .light : appearance == "dark" ? .dark : nil)
                .onAppear { delegate.model = model; model.start() }
        }
        .defaultSize(width: fixtureWindowSize.width, height: fixtureWindowSize.height)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Discover Groups") { model.discover() }.keyboardShortcut("r", modifiers: [.command, .shift]).disabled(model.busy || !model.connected)
                Button("Compose Message") { model.screen = .composer }.keyboardShortcut("n", modifiers: .command)
            }
        }
        Settings {
            SettingsView(model: model).frame(width: 650, height: 600)
                .preferredColorScheme(appearance == "light" ? .light : appearance == "dark" ? .dark : nil)
        }
    }
}

@MainActor final class ApplicationDelegate: NSObject, NSApplicationDelegate {
    weak var model: AppModel?
    private var terminating = false
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !terminating else { return .terminateLater }
        terminating = true
        Task {
            await model?.shutdown()
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
