import Foundation
import SwiftUI

protocol LanguagePreferences {
    func string(forKey key: String) -> String?
    func set(_ value: Any?, forKey key: String)
}
extension UserDefaults: LanguagePreferences {}

@MainActor
final class Localization: ObservableObject {
    struct Language: Decodable, Identifiable {
        let code: String
        let name: String
        let aliases: [String]
        var id: String { code }
    }
    private struct Manifest: Decodable {
        let languages: [Language]
    }

    @Published private(set) var preference: String
    @Published private(set) var locale = "en"
    let languages: [Language]
    private let directory: URL
    private let defaults: LanguagePreferences
    private let preferredLanguages: [String]
    private let english: [String: String]
    private var catalog: [String: String] = [:]

    init(catalogDirectory: URL = Bundle.main.resourceURL!.appendingPathComponent("Localization"),
         defaults: LanguagePreferences = UserDefaults.standard, preferredLanguages: [String] = Locale.preferredLanguages) {
        directory = catalogDirectory
        self.defaults = defaults
        self.preferredLanguages = preferredLanguages
        let manifest = try? JSONDecoder().decode(Manifest.self, from: Data(contentsOf: directory.appendingPathComponent("manifest.json")))
        languages = manifest?.languages ?? [Language(code: "en", name: "English", aliases: ["en"])]
        english = Self.load("en", from: directory)
        preference = "system"
        setPreference(defaults.string(forKey: "screenOrganizer.language") ?? "system")
    }

    func setPreference(_ value: String) {
        preference = value == "system" || languages.contains(where: { $0.code == value }) ? value : "system"
        locale = resolveLocale(preference)
        catalog = Self.load(locale, from: directory)
        defaults.set(preference, forKey: "screenOrganizer.language")
    }

    func resolveLocale(_ value: String) -> String {
        if value != "system" { return match(value) ?? "en" }
        return preferredLanguages.compactMap(match).first ?? "en"
    }

    private func match(_ value: String) -> String? {
        let normalized = value.replacingOccurrences(of: "_", with: "-").lowercased()
        guard normalized.range(of: "^[a-z]{2,8}(-[a-z0-9]{1,8})*$", options: .regularExpression) != nil else { return nil }
        let parts = normalized.split(separator: "-").map(String.init)
        var candidates: [String] = []
        if parts.count > 1, parts[1] == "hans" || parts[1] == "hant" { candidates.append(parts[0] + "-" + parts[1]) }
        candidates += stride(from: parts.count, through: 1, by: -1).map { parts.prefix($0).joined(separator: "-") }
        for candidate in candidates {
            if let language = languages.first(where: { ($0.aliases + [$0.code]).contains(where: { $0.lowercased() == candidate }) }) {
                return language.code
            }
        }
        return nil
    }

    func t(_ key: String, _ parameters: [String: String] = [:]) -> String {
        let text = catalog[key] ?? english[key] ?? key
        let pattern = try! NSRegularExpression(pattern: "\\{([A-Za-z_][A-Za-z0-9_]*)\\}")
        let source = text as NSString
        var result = text
        for match in pattern.matches(in: text, range: NSRange(location: 0, length: source.length)).reversed() {
            guard let value = parameters[source.substring(with: match.range(at: 1))],
                  let range = Range(match.range, in: result) else { continue }
            result.replaceSubrange(range, with: value)
        }
        return result
    }

    private static func load(_ code: String, from directory: URL) -> [String: String] {
        (try? JSONDecoder().decode([String: String].self, from: Data(contentsOf: directory.appendingPathComponent(code + ".json")))) ?? [:]
    }
}

struct LanguagePicker: View {
    @EnvironmentObject private var localization: Localization
    var body: some View {
        Picker(localization.t("common.language"), selection: Binding(get: { localization.preference }, set: localization.setPreference)) {
            Text(localization.t("common.system")).tag("system")
            ForEach(localization.languages) { language in Text(language.name).tag(language.code) }
        }
        .fixedSize(horizontal: false, vertical: true)
    }
}
