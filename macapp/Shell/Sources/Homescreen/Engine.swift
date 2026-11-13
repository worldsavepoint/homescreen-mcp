import Foundation

/// Runs the bundled engine (Contents/Resources/engine/engine) as a child process serving the
/// editor on a free localhost port, and stops it when the app quits.
@MainActor
final class Engine: ObservableObject {
    enum State: Equatable {
        case starting
        case ready(URL)
        case failed(String)
    }

    @Published private(set) var state: State = .starting
    private var process: Process?
    private var log = Data()

    static var executable: URL {
        Bundle.main.resourceURL!.appendingPathComponent("engine/engine")
    }

    static var dataFolder: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/homescreen-mcp")
    }

    func start() {
        stop()
        state = .starting
        log = Data()
        guard FileManager.default.isExecutableFile(atPath: Self.executable.path) else {
            state = .failed("The engine is missing from the app bundle (\(Self.executable.path)).")
            return
        }
        let port: Int
        let token: String
        let healthSecret: String
        let challenge: String
        do {
            port = try Self.freePort()
            token = try EngineSecurity.makeToken()
            healthSecret = try EngineSecurity.makeToken()
            challenge = try EngineSecurity.makeToken()
        } catch {
            state = .failed("Couldn't prepare the local engine: \(error.localizedDescription)")
            return
        }
        let p = Process()
        p.executableURL = Self.executable
        p.arguments = ["ui", "--port", String(port), "--no-browser"]
        var env = ProcessInfo.processInfo.environment
        env["HOMESCREEN_APP"] = "1"
        env["HOMESCREEN_UI_TOKEN"] = token
        env["HOMESCREEN_HEALTH_SECRET"] = healthSecret
        env["HOMESCREEN_PARENT_PID"] = String(ProcessInfo.processInfo.processIdentifier)
        p.environment = env
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            Task { @MainActor in self?.log.append(d) }
        }
        p.terminationHandler = { [weak self] proc in
            Task { @MainActor in
                guard let self, self.process === proc else { return }
                self.process = nil
                let tail = String(decoding: self.log.suffix(4000), as: UTF8.self)
                self.state = .failed("The engine stopped (exit \(proc.terminationStatus)).\n\n\(tail)")
            }
        }
        do {
            try p.run()
        } catch {
            state = .failed("Couldn't start the engine: \(error.localizedDescription)")
            return
        }
        process = p
        let url = URL(string: "http://127.0.0.1:\(port)/")!
        Task { await waitUntilServing(url, token: token, healthSecret: healthSecret, challenge: challenge, process: p) }
    }

    func stop() {
        guard let p = process else { return }
        process = nil
        p.terminationHandler = nil
        if p.isRunning { p.terminate() }
    }

    private func waitUntilServing(_ url: URL, token: String, healthSecret: String,
                                  challenge: String, process p: Process) async {
        let deadline = Date().addingTimeInterval(60)
        let config = URLSessionConfiguration.ephemeral
        config.connectionProxyDictionary = [:]
        let session = URLSession(configuration: config, delegate: HealthSessionDelegate(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        while Date() < deadline, process === p {
            let req = EngineSecurity.healthRequest(base: url, challenge: challenge)
            if let (data, response) = try? await session.data(for: req) {
                guard process === p else { return }
                if EngineSecurity.isHealthy(data: data, response: response, base: url,
                                             secret: healthSecret, challenge: challenge) {
                    state = .ready(EngineSecurity.pageURL(base: url, token: token))
                    return
                }
                stop()
                state = .failed("The local server failed authentication. Restart iOS Home Screen Organizer to try again.")
                return
            }
            try? await Task.sleep(nanoseconds: 200_000_000)
        }
        if process === p {
            stop()
            state = .failed("The engine didn't start within a minute.\n\n"
                            + String(decoding: log.suffix(4000), as: UTF8.self))
        }
    }

    /// Ask the kernel for a free port, then let it go for the engine to bind.
    private static func freePort() throws -> Int {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { throw POSIXError(.EADDRNOTAVAIL) }
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        addr.sin_port = 0
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        let bound = withUnsafeMutablePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, len) }
        }
        guard bound == 0 else { throw POSIXError(.EADDRNOTAVAIL) }
        let named = withUnsafeMutablePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &len) }
        }
        let port = Int(UInt16(bigEndian: addr.sin_port))
        guard named == 0, port > 0 else { throw POSIXError(.EADDRNOTAVAIL) }
        return port
    }
}
