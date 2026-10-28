# Graphical validation evidence ledger

No screenshots or recordings were captured. No illustrative artwork is submitted as UI evidence.

- Original Debug artifact: strict codesign verification failed (`code has no resources but signature indicates they must be present`).
- Corrected Xcode ad-hoc signing: application identifier, Info.plist binding and resource seal verify.
- Actual signed Debug/Release graphical launch: macOS application-registration abort before application/Python initialization; Launch Services returned -10827.
- Control experiment: separately compiled/signed minimal SwiftUI `WindowGroup` APPL bundle reproduced the registration abort. A command-line `NSApplication.shared` probe initialized.
- Actual XCUITest attempt: test-manager service rejected execution with error 159; no screen assertion or screenshot capture is reported as passed.
- Direct XCTest: native model/transport tests execute independently of graphical registration; final counts are in [VALIDATION.md](../VALIDATION.md).

Use the executable procedures in [UI_VALIDATION.md](../UI_VALIDATION.md) from an unlocked macOS login session. Save genuine screenshots only after reviewing them for secrets. Finder interaction, fullscreen, VoiceOver, high contrast, reduced motion and screenshot visual inspection remain unverified here.
