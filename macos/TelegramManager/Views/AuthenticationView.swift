import SwiftUI

struct AuthenticationView: View {
    @ObservedObject var model: AppModel
    @State private var apiID = ""
    @State private var apiHash = ""
    @State private var phone = ""
    @State private var country = "+94"
    @State private var code = ""
    @State private var password = ""
    @State private var saveKeychain = true
    @State private var showPassword = false
    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack { Image(systemName: "lock.shield.fill").font(.largeTitle).foregroundStyle(.blue); VStack(alignment: .leading) { Text("Connect Telegram").font(.title.weight(.semibold)); Text("Your existing session and records remain private.").foregroundStyle(.secondary) } }
            switch model.authStage {
            case "credentials":
                Text("Create your own application at the official Telegram portal. Sign in, open API development tools, and select Desktop if offered. Use a personal API ID and API Hash, not a bot token.").font(.callout)
                Link("Open my.telegram.org", destination: URL(string: "https://my.telegram.org")!)
                TextField("Telegram API ID", text: $apiID).textFieldStyle(.roundedBorder)
                SecureField("Telegram API Hash", text: $apiHash).textFieldStyle(.roundedBorder)
                Toggle("Save API credentials in macOS Keychain", isOn: $saveKeychain)
                Button("Continue") {
                    let hash = apiHash; apiHash = ""
                    model.authenticate("auth.credentials", params: ["api_id": .string(apiID), "api_hash": .string(hash), "save": .bool(saveKeychain)])
                }.buttonStyle(.borderedProminent).disabled(apiID.isEmpty || apiHash.isEmpty || model.busy)
            case "phone":
                Text("Enter your international phone number. For Sri Lanka use +947XXXXXXXX, without the domestic leading zero. Telegram chooses code delivery; check the verified Telegram service chat on an already signed-in device first. SMS is not guaranteed.")
                HStack { Picker("Country", selection: $country) { Text("Sri Lanka (+94)").tag("+94"); Text("India (+91)").tag("+91"); Text("United Kingdom (+44)").tag("+44"); Text("United States (+1)").tag("+1"); Text("Other (enter +country code)").tag("") }.frame(width: 235); SecureField("Phone number", text: $phone).textFieldStyle(.roundedBorder) }
                Button("Request Login Code") { let value = phone.hasPrefix("+") ? phone : country + phone; phone = ""; model.authenticate("auth.phone", params: ["phone": .string(value)]) }.buttonStyle(.borderedProminent).disabled(phone.isEmpty || model.busy)
            case "code":
                Text("Enter the newest login code Telegram delivered for this application. The developer portal login code is separate.")
                SecureField("Telegram login code", text: $code).textFieldStyle(.roundedBorder)
                Button("Verify Code") { let value = code; code = ""; model.authenticate("auth.code", params: ["code": .string(value)]) }.buttonStyle(.borderedProminent).disabled(code.isEmpty || model.busy)
            case "password":
                Text("Two-step verification is enabled. Enter your Telegram account password, not your API Hash or macOS password.")
                Group { if showPassword { TextField("Telegram two-step verification password", text: $password) } else { SecureField("Telegram two-step verification password", text: $password) } }.textFieldStyle(.roundedBorder)
                Toggle("Show password", isOn: $showPassword)
                Button("Verify Password") { let value = password; password = ""; model.authenticate("auth.password", params: ["password": .string(value)]) }.buttonStyle(.borderedProminent).disabled(password.isEmpty || model.busy)
            case "bind_account":
                Text("Telegram verified this account. Confirm its identity before binding this installation. Existing group and delivery records are account-isolated.")
                Text("Account ID: \(model.authAccount)").font(.title3.monospacedDigit()).textSelection(.enabled)
                Button("Bind This Exact Account") { model.authenticate("auth.bind", params: ["account_id": .integer(model.authAccount), "confirm": .bool(true)]) }.buttonStyle(.borderedProminent).disabled(model.authAccount == 0 || model.busy)
            default:
                Text("Authentication is unavailable. Reconnect to restore the existing session.")
                Button("Reconnect") { model.reconnect() }.disabled(model.busy)
            }
            if let error = model.errorMessage { Label(error, systemImage: "exclamationmark.circle").font(.callout).foregroundStyle(.red) }
            if model.busy { ProgressView("Contacting Telegram…").controlSize(.small) }
            Divider()
            HStack { Text("Secrets are never included in responses or diagnostic logs.").font(.caption).foregroundStyle(.secondary); Spacer(); Button("Cancel", role: .cancel) { model.cancelAuthentication() } }
        }.padding(30).frame(width: 540)
        .accessibilityIdentifier("authenticationSheet")
    }
}
