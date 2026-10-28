import SwiftUI
import AppKit
import UserNotifications

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @AppStorage("appearance") private var appearance = "system"
    @AppStorage("connectAtLaunch") private var connectAtLaunch = true
    @AppStorage("notificationsEnabled") private var notificationsEnabled = false
    @State private var basicTTL = 86400
    @State private var permissionTTL = 900
    @State private var membersTTL = 3600
    @State private var metadataTTL = 21600
    var body: some View {
        Form {
            Section("General") {
                Picker("Appearance", selection: $appearance) { Text("System").tag("system"); Text("Light").tag("light"); Text("Dark").tag("dark") }
                Toggle("Restore Telegram session at launch", isOn: $connectAtLaunch)
                Toggle("Show local operation-completion notifications", isOn: $notificationsEnabled)
                    .onChange(of: notificationsEnabled) { _, enabled in
                        if enabled {
                            UNUserNotificationCenter.current().requestAuthorization(options: [.alert]) { allowed, _ in
                                if !allowed { Task { @MainActor in notificationsEnabled = false; model.errorMessage = "Notifications were not enabled. You can review notification permissions in macOS System Settings." } }
                            }
                        }
                    }
                Text("The app never discovers groups, inspects permissions or sends messages automatically.").font(.caption).foregroundStyle(.secondary)
            }
            Section("Telegram") {
                LabeledContent("Connection", value: model.connected ? "Connected" : "Disconnected")
                LabeledContent("Account binding", value: model.accountID == 0 ? "Not bound" : String(model.accountID))
                LabeledContent("Session file", value: model.status["session_present"].bool ? "Present in private storage" : "Not present")
                Button("Restore Existing Session") { model.reconnect() }.disabled(model.busy)
            }
            Section("Discovery") {
                TextField("Basic metadata lifetime (seconds)", value: $basicTTL, format: .number)
                TextField("Permission lifetime (seconds)", value: $permissionTTL, format: .number)
                TextField("Member count lifetime (seconds)", value: $membersTTL, format: .number)
                TextField("Detailed metadata lifetime (seconds)", value: $metadataTTL, format: .number)
                Stepper("Inspection batch limit: \(model.inspectionLimit)", value: $model.inspectionLimit, in: 1...100)
                Button("Save Discovery Preferences") { model.updateSettings(basic: basicTTL, permissions: permissionTTL, members: membersTTL, metadata: metadataTTL) }.disabled(model.busy)
                Text("Lifetimes accept 0–31536000 seconds. Zero disables the cache. Saving preferences does not start an inspection. Sending always verifies permissions freshly.").font(.caption).foregroundStyle(.secondary)
            }
            Section("Storage & Security") {
                Text(model.settings["storage_location"].string).textSelection(.enabled).font(.callout)
                LabeledContent("API credentials", value: model.settings["credential_source"].string.isEmpty ? "Not loaded" : model.settings["credential_source"].string)
                LabeledContent("Keychain", value: model.settings["keychain_supported"].bool ? "Supported" : "Unavailable")
                Text("No credential/session export. Database and session backups must be stored privately. The running app owns an exclusive backend lock.").font(.caption).foregroundStyle(.secondary)
                Button("Create Private Database Backup…") { model.exportMaintenance(diagnostics: false) }.disabled(model.busy)
                Button("Reveal Storage in Finder") { let path = model.settings["storage_location"].string; if !path.isEmpty { NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: path) } }
            }
            Section("Advanced") {
                LabeledContent("App version", value: model.settings["version"].string)
                LabeledContent("Python", value: model.settings["python_version"].string)
                LabeledContent("Backend", value: model.backendOnline ? "Running via local pipes" : "Unavailable")
                Text("This development build uses the project Python runtime. Distribution to another Mac requires an embedded, tested runtime and signing/notarization.").font(.caption).foregroundStyle(.secondary)
                Button("Export Sanitized Diagnostics…") { model.exportMaintenance(diagnostics: true) }.disabled(model.busy)
                Button("Refresh Local Status") { Task { await model.refreshStatus() } }
            }
        }.formStyle(.grouped).padding(12)
            .onAppear { loadPolicy() }
            .onChange(of: model.settings) { _, _ in loadPolicy() }
    }
    private func loadPolicy() {
        if model.settings["cache_policy"] != .null {
            basicTTL = model.settings["cache_policy"]["basic"].int
            permissionTTL = model.settings["cache_policy"]["permissions"].int
            membersTTL = model.settings["cache_policy"]["members"].int
            metadataTTL = model.settings["cache_policy"]["metadata"].int
        }
    }
}
