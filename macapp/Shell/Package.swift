// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "IOSHomeScreenOrganizer",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "IOSHomeScreenOrganizer", path: "Sources/Homescreen")
    ]
)
