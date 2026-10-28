import SwiftUI

struct PageHeader: View {
    let title: String
    var subtitle = ""
    var symbol: String? = nil
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            if let symbol { Image(systemName: symbol).font(.title2).foregroundStyle(.tint).accessibilityHidden(true) }
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(.largeTitle.weight(.semibold)).accessibilityAddTraits(.isHeader)
                if !subtitle.isEmpty { Text(subtitle).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
            }
            Spacer(minLength: 0)
        }.frame(maxWidth: .infinity, alignment: .topLeading)
            .fixedSize(horizontal: false, vertical: true).accessibilityIdentifier("pageHeader")
    }
}

struct SectionCard<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(title).font(.headline).accessibilityAddTraits(.isHeader)
            content
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(.background, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(.quaternary))
    }
}

struct EmptyStateView: View {
    let title: String
    let symbol: String
    let description: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil
    var body: some View {
        ContentUnavailableView {
            Label(title, systemImage: symbol)
        } description: {
            Text(description).frame(maxWidth: 390)
        } actions: {
            if let actionTitle, let action { Button(actionTitle, action: action).buttonStyle(.borderedProminent) }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

enum StatusTone { case neutral, success, warning, failure
    var color: Color { switch self { case .neutral: .secondary; case .success: .green; case .warning: .orange; case .failure: .red } }
}
struct StatusBadge: View {
    let title: String
    let symbol: String
    var tone: StatusTone = .neutral
    var body: some View {
        Label(title, systemImage: symbol).font(.caption.weight(.medium)).foregroundStyle(tone.color)
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(tone.color.opacity(0.08), in: Capsule())
    }
}

struct AccountIdentityView: View {
    let name: String
    let identifier: String
    let status: String
    let connected: Bool
    var compact = false
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "person.crop.circle.fill").font(.system(size: compact ? 28 : 36)).foregroundStyle(.blue)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text(name.isEmpty ? "Personal account" : safeDisplay(name)).font(.headline).lineLimit(2)
                if !identifier.isEmpty { Text(identifier).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                Label(status, systemImage: connected ? "checkmark.circle.fill" : "circle.dotted")
                    .font(.caption).foregroundStyle(connected ? .green : .secondary)
            }
            Spacer(minLength: 0)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SearchToolbar: View {
    @Binding var text: String
    let prompt: String
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary).accessibilityHidden(true)
            TextField(prompt, text: $text).textFieldStyle(.plain).accessibilityLabel(prompt)
            if !text.isEmpty { Button { text = "" } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain).accessibilityLabel("Clear search") }
        }.padding(8).background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
    }
}
struct FilterMenu: View {
    let title: String
    @Binding var selection: String
    let options: [String]
    var body: some View {
        Picker(title, selection: $selection) {
            ForEach(options, id: \.self) { Text($0.replacingOccurrences(of: "_", with: " ").capitalized).tag($0) }
        }.pickerStyle(.menu).fixedSize().accessibilityLabel(title)
    }
}


/// Content controls stay in the content area, never inserted into the window toolbar.
struct PageControls<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        ScrollView(.horizontal, showsIndicators: true) {
            HStack(spacing: 12) { content }.padding(.bottom, 2)
        }.fixedSize(horizontal: false, vertical: true)
    }
}

struct LoadingStateView: View {
    let title: String
    var body: some View {
        VStack(spacing: 12) { ProgressView(); Text(title).foregroundStyle(.secondary) }
            .frame(maxWidth: .infinity, maxHeight: .infinity).accessibilityElement(children: .combine)
    }
}

struct ErrorStateView: View {
    let title: String
    let message: String
    var retry: (() -> Void)? = nil
    var body: some View {
        EmptyStateView(title: title, symbol: "exclamationmark.triangle", description: message,
                       actionTitle: retry == nil ? nil : "Try Again", action: retry)
    }
}


struct CachedReadStatus: View {
    @ObservedObject var model: AppModel
    let screen: Screen
    let retry: () -> Void
    var body: some View {
        Group {
            if model.cachedLoading.contains(screen) {
                HStack(spacing: 10) { ProgressView().controlSize(.small); Text("Loading saved records…").font(.callout).foregroundStyle(.secondary); Spacer() }
            } else if let error = model.cachedErrors[screen] {
                HStack(alignment: .top, spacing: 10) {
                    Label(error, systemImage: "exclamationmark.triangle").font(.callout).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
                    Spacer(); Button("Try Again", action: retry)
                }
            }
        }.fixedSize(horizontal: false, vertical: true).accessibilityIdentifier("cachedStatus_" + screen.rawValue)
    }
}
