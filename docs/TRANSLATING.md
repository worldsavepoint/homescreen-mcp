# Translating Screen Organizer

Shared catalogs live in `homescreen/web/locales/`. The web editor and native app use the same messages. `en.json` is the source reference; `manifest.json` registers language codes, display names and matching aliases.

## Update a translation

Edit the matching locale JSON file. Keep every English message key and translate its string value. Keys use the `app`, `common`, `editor`, `mcp`, `consent` and `native` domains. Use concise wording that fits buttons, menus and dialogs.

Preserve named placeholders such as `{name}` and `{count}` exactly. Their position can change to suit the language. Parameters supply app names, folder names, paths and other runtime data. Keep JSON values as plain text; the interface inserts text into controls and dialogs.

Use **Screen Organizer** as the Latin-script brand, **屏幕整理** in Simplified Chinese and **螢幕整理** in Traditional Chinese. The compatibility subtitle is **for iOS**. Preserve command names, protocol fields, configuration keys, shortcuts and the upstream attribution. Translate the consent terms with the same meaning as the English source.

## Add a language

1. Add a `languages` entry in `manifest.json` with a canonical locale `code`, native-language `name` and `aliases`. Choose aliases that resolve regional requests to the new catalog.
2. Copy `en.json` to `<code>.json` and translate every value, preserving keys and placeholders.
3. Run the catalog check from the repository root:

   ```sh
   python tools/check_translations.py
   ```

4. Preview the editor and native app in the language, including dialogs, accessibility labels, long strings and light/dark presentation.
5. Submit a focused pull request describing the language and wording changes.

The runtime language menus read the manifest. Packaging includes the locale JSON files. Regional requests fall back to the registered base language; Chinese script and region aliases select the matching Simplified or Traditional catalog. System mode uses preferred languages in order. Missing translated messages display the English source value.

## Add a message

Add a stable domain key to `en.json`, then add its translation to each registered catalog. Use named placeholders for variable values and format numbers or dates through the shared locale helpers. Run the catalog check and preview the affected controls.
