import SwiftUI
import AppKit

struct ArchiveTarget: Identifiable, Equatable {
    let scope: UpdateScope
    let chat: ChatSummary
    var id: String { "\(scope.profileID):\(chat.id)" }
}
struct ArchiveJob: Identifiable, Equatable {
    let data: JSONValue
    var id: String { data["id"].string }
    var title: String { safeDisplay(data["conversation"].string) }
    var active: Bool { ["finding", "saving"].contains(data["state"].string) }
    var status: String {
        switch data["state"].string {
        case "finding": "Finding media"
        case "saving": "Saving"
        case "waiting": "Waiting for Telegram"
        case "paused": "Paused"
        case "attention": "Needs attention"
        case "cancelled": "Cancelled"
        case "finished": "Finished"
        default: "Ready"
        }
    }
}
struct ArchiveDraft {
    var types: Set<String> = ["photo", "video", "animation", "document", "audio"]
    var range = "all"
    var start = Date()
    var end = Date()
    var folder: URL?
    var organization = "daily"
    func bounds(now: Date = Date(), calendar: Calendar = .current) -> (Int, Int) {
        let lower: Date
        switch range {
        case "month": lower = calendar.date(byAdding: .day, value: -30, to: now) ?? now
        case "year": lower = calendar.date(byAdding: .year, value: -1, to: now) ?? now
        case "custom": lower = calendar.startOfDay(for: start)
        default: lower = Date(timeIntervalSince1970: 0)
        }
        let upper = range == "custom" ? (calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: end)) ?? end) : now.addingTimeInterval(1)
        return (Int(lower.timeIntervalSince1970), Int(upper.timeIntervalSince1970))
    }
    var dateSummary: String {
        switch range {
        case "month": "Last 30 days"
        case "year": "Last year"
        case "custom": start.formatted(date: .abbreviated, time: .omitted) + " through " + end.formatted(date: .abbreviated, time: .omitted)
        default: "All available history"
        }
    }
    var valid: Bool { !types.isEmpty && folder != nil && bounds().0 < bounds().1 }
}

struct ArchiveWizard: View {
    @ObservedObject var model: AppModel
    let target: ArchiveTarget
    @State private var draft = ArchiveDraft()
    @State private var step = 0
    @State private var starting = false
    @State private var failure: String?
    private let titles = ["Choose what to save", "Choose the dates", "Choose a folder", "Organize your files", "Review and start"]
    private let kinds = [("photo","Photos"),("video","Videos"),("animation","GIFs"),("document","Documents"),("audio","Audio & voice messages")]
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            PageHeader(title: "Save Media", subtitle: target.chat.title, symbol: "square.and.arrow.down")
            Text("Step \(step + 1) of 5 · \(titles[step])").font(.headline).accessibilityAddTraits(.isHeader)
            ProgressView(value: Double(step + 1), total: 5).accessibilityLabel("Step \(step + 1) of 5")
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    switch step {
                    case 0:
                        Text("Save ordinary attachments you are allowed to export.").foregroundStyle(.secondary)
                        ForEach(kinds, id: \.0) { key, label in
                            Toggle(label, isOn: Binding(get: { draft.types.contains(key) }, set: { if $0 { draft.types.insert(key) } else { draft.types.remove(key) } }))
                        }
                        Button("Select All") { draft.types = Set(kinds.map(\.0)) }
                    case 1:
                        Picker("Date range", selection: $draft.range) {
                            Text("All available history").tag("all")
                            Text("Last 30 days").tag("month")
                            Text("Last year").tag("year")
                            Text("Custom dates").tag("custom")
                        }
                        if draft.range == "custom" {
                            DatePicker("From", selection: $draft.start, displayedComponents: .date)
                            DatePicker("Through", selection: $draft.end, displayedComponents: .date)
                        }
                        Text("Folders use the original message date in your Mac’s time zone. The final selected day is included.").font(.callout).foregroundStyle(.secondary)
                    case 2:
                        Label(draft.folder?.lastPathComponent ?? "Choose where to keep your archive", systemImage: "folder").textSelection(.enabled).lineLimit(3)
                        Button("Choose Folder…") { chooseFolder() }.buttonStyle(.borderedProminent).accessibilityIdentifier("archiveChooseFolder")
                        Text("Your existing files will never be overwritten.").foregroundStyle(.secondary)
                    case 3:
                        Picker("Folders", selection: $draft.organization) {
                            Text("By day (recommended)").tag("daily")
                            Text("By month").tag("monthly")
                            Text("By media type").tag("type")
                        }.pickerStyle(.radioGroup)
                        Text("Telegram Archives / \(target.chat.title) / date / files").font(.callout).foregroundStyle(.secondary)
                        Text("Conversations with the same name get separate folders.").font(.callout).foregroundStyle(.secondary)
                    default:
                        LabeledContent("Conversation", value: target.chat.title)
                        LabeledContent("Account", value: model.activeProfile?.title ?? "Selected account")
                        LabeledContent("Save", value: kinds.filter { draft.types.contains($0.0) }.map(\.1).joined(separator: ", "))
                        LabeledContent("Dates", value: draft.dateSummary)
                        LabeledContent("Organization", value: draft.organization == "daily" ? "By day" : draft.organization == "monthly" ? "By month" : "By media type")
                        LabeledContent("Folder", value: draft.folder?.lastPathComponent ?? "Choose a folder")
                        LabeledContent("Storage needed", value: "Calculated while finding media")
                        Label("Protected and disappearing media will be skipped.", systemImage: "lock.shield").foregroundStyle(.secondary)
                        Text("You can keep chatting while this runs. Switching accounts pauses the archive; saved files stay in place.").font(.callout)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            if let failure { Label(failure, systemImage: "exclamationmark.triangle").foregroundStyle(.red).fixedSize(horizontal: false, vertical: true) }
            HStack {
                Button("Cancel") { model.archiveTarget = nil }.keyboardShortcut(.cancelAction).disabled(starting)
                Spacer()
                if step > 0 { Button("Back") { step -= 1 }.disabled(starting) }
                if step < 4 {
                    Button("Continue") { step += 1 }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                        .disabled(step == 0 && draft.types.isEmpty || step == 1 && draft.bounds().0 >= draft.bounds().1 || step == 2 && draft.folder == nil)
                } else {
                    Button(starting ? "Starting…" : "Start Saving") {
                        starting = true
                        Task {
                            do { try await model.createArchive(target, draft: draft) }
                            catch { failure = error.localizedDescription; starting = false }
                        }
                    }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction).disabled(!draft.valid || starting)
                }
            }
        }.padding(24).frame(width: 560, height: 540).accessibilityIdentifier("archiveWizard")
    }
    private func chooseFolder() {
        if model.isUIFixture { draft.folder = URL(fileURLWithPath: "/private/tmp/Telegram Archive Demo", isDirectory: true); return }
        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.allowsMultipleSelection = false
        panel.prompt = "Choose Folder"
        if panel.runModal() == .OK { draft.folder = panel.url }
    }
}

struct MediaArchivesView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 20) {
                PageHeader(title: "Media Archives", subtitle: "Saved files stay organized by conversation and date.", symbol: "archivebox")
                if model.archiveJobs.isEmpty {
                    EmptyStateView(title: "Your media, organized", symbol: "folder.badge.plus", description: "Open a conversation and choose Save Media to begin.", actionTitle: "Open Chats", action: { model.navigate(to: .chats) }).frame(minHeight: 260)
                }
                ForEach(model.archiveJobs) { job in
                    SectionCard(title: job.title) {
                        Label(job.status, systemImage: job.active ? "arrow.down.circle" : "folder").font(.headline)
                        if job.active { ProgressView(job.status == "Finding media" ? "Checking messages…" : "Saving the next file…").controlSize(.small) }
                        HStack(spacing: 24) {
                            LabeledContent("Found", value: "\(job.data["discovered"].int)")
                            LabeledContent("Saved", value: "\(job.data["completed"].int)")
                            LabeledContent("Already saved", value: "\(job.data["duplicates"].int)")
                        }
                        Text("\(ByteCountFormatter.string(fromByteCount: Int64(job.data["bytes"].int + job.data["in_progress_bytes"].int), countStyle: .file)) saved · \(job.data["examined"].int) messages checked").foregroundStyle(.secondary)
                        Text("\(job.data["restricted"].int) restricted · \(job.data["unsupported"].int) unsupported · \(job.data["deleted"].int) deleted or expired · \(job.data["failed"].int) failed").font(.callout).foregroundStyle(.secondary)
                        if !job.data["note"].string.isEmpty { Text(safeDisplay(job.data["note"].string)).font(.callout).fixedSize(horizontal: false, vertical: true) }
                        if job.data["wait_until"].doubleValue > Date().timeIntervalSince1970 {
                            TimelineView(.periodic(from: .now, by: 1)) { clock in
                                Text("Try again in \(max(0, Int(ceil(job.data["wait_until"].doubleValue - clock.date.timeIntervalSince1970)))) seconds").monospacedDigit()
                            }
                        }
                        ViewThatFits(in: .horizontal) {
                            HStack { controls(job) }
                            VStack(alignment: .leading) { controls(job) }
                        }
                    }.accessibilityIdentifier("archiveJob_" + job.id)
                }
                if let error = model.archiveError { ErrorStateView(title: "Archive needs attention", message: error, retry: { Task { await model.loadArchives() } }) }
            }.padding(24)
        }.task {
            while !Task.isCancelled {
                await model.loadArchives()
                do { try await Task.sleep(for: .seconds(3)) } catch { return }
            }
        }.accessibilityIdentifier("mediaArchives")
    }
    @ViewBuilder private func controls(_ job: ArchiveJob) -> some View {
        if job.active {
            Button("Pause") { model.archiveControl("archive.pause", job: job) }
        } else if job.data["state"].string != "finished" {
            Button("Resume") { model.archiveControl("archive.resume", job: job) }.disabled(!model.connected || job.data["wait_until"].doubleValue > Date().timeIntervalSince1970)
        } else {
            Button("Check for New Media") { model.archiveControl("archive.incremental", job: job) }.disabled(!model.connected)
        }
        if job.data["failed"].int > 0 { Button("Retry Failed") { model.archiveControl("archive.retry_failed", job: job) }.disabled(job.active || !model.connected || job.data["wait_until"].doubleValue > Date().timeIntervalSince1970) }
        if !["finished", "cancelled"].contains(job.data["state"].string) { Button("Cancel") { model.archiveControl("archive.cancel", job: job) } }
        Button("Open Folder in Finder") { NSWorkspace.shared.open(URL(fileURLWithPath: job.data["folder"].string)) }
    }
}

struct SponsoredFramePreference: PreferenceKey {
    static var defaultValue: [String: CGRect] = [:]
    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) { value.merge(nextValue(), uniquingKeysWith: { _, new in new }) }
}
struct SponsoredCard: View {
    @ObservedObject var model: AppModel
    let ad: JSONValue
    @State private var confirm = false
    @State private var options: JSONValue?
    @State private var information = false
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 8) {
                Text(ad["label"].string).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                Text(safeDisplay(ad["title"].string)).font(.headline)
                Text(ad["text"].string).fixedSize(horizontal: false, vertical: true)
            }.background(GeometryReader { proxy in Color.clear.preference(key: SponsoredFramePreference.self, value: [ad["token"].string: proxy.frame(in: .named("conversationHistoryViewport"))]) })
            HStack {
                Button(ad["button"].string) { confirm = true }
                if !ad["info"].string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { Button("Sponsor Info") { information = true } }
                if ad["can_report"].bool { Button("Report") { report("") } }
            }
        }.padding(14).frame(maxWidth: .infinity, alignment: .leading).background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 10))
        .confirmationDialog("Open this sponsor’s website?", isPresented: $confirm) { Button("Open Website") { model.openSponsor(ad) }; Button("Cancel", role: .cancel) {} }
        .popover(isPresented: $information) { Text(ad["info"].string).padding().frame(width: 320) }
        .sheet(isPresented: Binding(get: { options != nil }, set: { if !$0 { options = nil } })) {
            VStack(spacing: 16) {
                Text(options?["title"].string ?? "Report sponsored message").font(.headline)
                ForEach(Array((options?["options"].array ?? []).enumerated()), id: \.offset) { _, option in Button(option["title"].string) { report(option["id"].string) } }
                Button("Cancel") { options = nil }
            }.padding(24).frame(minWidth: 360)
        }
    }
    private func report(_ option: String) {
        Task {
            do {
                let result = try await model.reportSponsor(ad, option: option)
                options = result["reported"].bool ? nil : result
            } catch { model.errorMessage = error.localizedDescription }
        }
    }
}
