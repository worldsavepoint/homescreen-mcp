// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "HomeScreenOrganizer",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "HomeScreenOrganizer", path: "Sources/Homescreen")
    ]
)
