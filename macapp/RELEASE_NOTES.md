Arrange Home Screen apps, folders, widgets and the App Library from your Mac.

- Version 1.2.0 adds native Intel support alongside Apple silicon, with separate DMG and ZIP downloads for each architecture.
- Layout support for iOS 16, 17, 18, 26 and 27; iOS 16 uses sequential icon placement.
- Per-device drafts and backups, readback comparison, local editor, CLI and MCP server.
- macOS 14 or later; ad-hoc signed app with the Python engine and dependencies included.

Choose your download in Apple menu → About This Mac: an Apple M-series chip uses `macos-arm64`; an Intel processor uses `macos-x86_64`. Open the matching DMG and drag iOS Home Screen Organizer into Applications, or extract the matching ZIP. Open System Settings → Privacy & Security → Open Anyway when macOS requests approval.

`SHA256SUMS.txt` contains hashes for both DMGs and both ZIPs. Save it in the same directory as your chosen DMG or ZIP, then run `shasum -a 256 --check --ignore-missing SHA256SUMS.txt`.

Native Apple silicon and Intel CI builds validate the functional modules, packaged engine startup, MCP initialization and tools, Mach-O architectures, signatures and checksums before publication. Each new version is released after successful builds of both architectures, with a matching version tag at the built commit.

Original project by [Jonathan Kats](https://github.com/kats1123/homescreen-mcp), distributed under the MIT License.
