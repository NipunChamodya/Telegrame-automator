import SwiftUI
import AppKit

@main struct TelegramManagerApp: App {
    @NSApplicationDelegateAdaptor(ApplicationDelegate.self) var delegate
    @StateObject private var model = AppModel()
    @AppStorage("appearance") private var appearance = "system"
    var body: some Scene {
        WindowGroup {
            RootView(model: model)
                .frame(minWidth: 980, minHeight: 640)
                .preferredColorScheme(appearance == "light" ? .light : appearance == "dark" ? .dark : nil)
                .onAppear { delegate.model = model; model.start() }
        }
        .defaultSize(width: 1260, height: 820)
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
        guard !terminating else { return .terminateNow }
        terminating = true
        Task {
            await model?.shutdown()
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
