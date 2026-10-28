import SwiftUI

struct ActivityTimeline: View {
    let events: [ActivityEvent]
    @State private var search = ""
    @State private var kind: ActivityKind?
    @State private var status: ActivityStatus?
    private var filtered: [ActivityEvent] {
        ActivityHistory.filter(events, query: search, kind: kind, status: status)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                PageHeader(title: "Activity", subtitle: "Recent operations in this app session. Message contents are never included.", symbol: "waveform.path.ecg")
                PageControls {
                    SearchToolbar(text: $search, prompt: "Search activity or account")
                        .frame(width: 240).accessibilityIdentifier("activitySearch")
                    Picker("Type", selection: $kind) {
                        Text("All types").tag(nil as ActivityKind?)
                        ForEach(ActivityKind.allCases) { Text($0.title).tag(Optional($0)) }
                    }.frame(width: 180)
                    Picker("Status", selection: $status) {
                        Text("All statuses").tag(nil as ActivityStatus?)
                        ForEach(ActivityStatus.allCases) { Text($0.title).tag(Optional($0)) }
                    }.frame(width: 160)
                }
            }.padding(24)
            Divider()
            List(filtered) { event in
                DisclosureGroup {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(event.description).foregroundStyle(.secondary)
                        if let account = event.accountName, !account.isEmpty { LabeledContent("Account", value: account) }
                        if let accountID = event.accountID { LabeledContent("Account ID", value: accountID) }
                        if let profile = event.profileID { LabeledContent("Profile", value: profile) }
                        LabeledContent("Started", value: event.date.formatted(date: .abbreviated, time: .standard))
                        if event.updatedAt != event.date { LabeledContent("Updated", value: event.updatedAt.formatted(date: .abbreviated, time: .standard)) }
                        if let completed = event.completed {
                            LabeledContent("Processed", value: event.total.map { "\(completed) of \($0)" } ?? String(completed))
                        }
                    }.font(.callout).padding(.vertical, 10).textSelection(.enabled)
                } label: {
                    HStack(alignment: .top, spacing: 12) {
                        if event.status == .running { ProgressView().controlSize(.small).frame(width: 26) }
                        else { Image(systemName: event.kind.symbol).font(.title3).foregroundStyle(.secondary).frame(width: 26) }
                        VStack(alignment: .leading, spacing: 5) {
                            Text(event.title).font(.headline)
                            Text(event.accountName ?? "Application").font(.caption).foregroundStyle(.secondary)
                            if let completed = event.completed { Text("\(completed) processed").font(.caption).foregroundStyle(.secondary) }
                        }
                        Spacer(minLength: 12)
                        VStack(alignment: .trailing, spacing: 5) {
                            Label(event.status.title, systemImage: symbol(event.status))
                                .font(.caption.weight(.medium)).foregroundStyle(color(event.status))
                            Text(event.date, style: .time).font(.caption).foregroundStyle(.secondary)
                        }
                    }.padding(.vertical, 9)
                }
                .frame(maxWidth: 880, alignment: .leading)
                .accessibilityIdentifier("activity_\(event.id.uuidString)")
            }
            .listStyle(.inset)
            .overlay {
                if filtered.isEmpty {
                    ContentUnavailableView(events.isEmpty ? "No activity yet" : "No matching activity",
                        systemImage: "clock", description: Text(events.isEmpty
                            ? "Discover groups, inspect permissions, or manage a draft to see activity here."
                            : "Try another search, operation type, or status."))
                }
            }
            Divider()
            Text("\(filtered.count) of \(events.count) events · Latest \(ActivityHistory.limit) retained until app exits")
                .font(.caption).foregroundStyle(.secondary).padding(12)
        }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .accessibilityIdentifier("activityTimeline")
    }
    private func symbol(_ status: ActivityStatus) -> String {
        switch status {
        case .running: "clock"
        case .succeeded: "checkmark.circle"
        case .failed: "exclamationmark.triangle"
        case .cancelled: "stop.circle"
        case .warning: "exclamationmark.circle"
        case .info: "info.circle"
        }
    }
    private func color(_ status: ActivityStatus) -> Color {
        switch status {
        case .running: .blue
        case .succeeded: .green
        case .failed: .red
        case .cancelled: .orange
        case .warning: .orange
        case .info: .secondary
        }
    }
}
