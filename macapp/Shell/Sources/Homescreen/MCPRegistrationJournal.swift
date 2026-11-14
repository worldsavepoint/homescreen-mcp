import Foundation
import Darwin

enum MCPRegistrationPhase: String, Codable {
    case prepared, bootstrapping, removing, adding, observed, restoring, restoreRemoved, committed
}

struct MCPRegistrationRecord: Codable {
    let client: String
    let scope: String
    let server: String
    let file: String
    let prior: MCPOwnedEntry
    let intended: MCPOwnedEntry
    var phase: MCPRegistrationPhase = .prepared
    var observed: MCPOwnedEntry?
    var bootstrapVersion: String?
}

/// The fixed record and lock names never come from decoded journal data.
class MCPRegistrationJournal {
    let directory: URL
    let client: MCPClient
    private let lockFD: Int32
    private let dirFD: Int32
    private var recordName: String { client.rawValue + ".json" }

    init(directory: URL, client: MCPClient) throws {
        self.directory = directory
        self.client = client
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let dir = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        var st = stat()
        guard dir >= 0, fstat(dir, &st) == 0, st.st_uid == getuid(), st.st_mode & 0o077 == 0 else {
            if dir >= 0 { close(dir) }
            throw MCPClientOperationCode.snapshotReadFailed
        }
        dirFD = dir
        let fd = openat(dir, client.rawValue + ".lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0, fstat(fd, &st) == 0, st.st_uid == getuid(), st.st_mode & S_IFMT == S_IFREG,
              st.st_mode & 0o077 == 0, flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            if fd >= 0 { close(fd) }
            close(dir)
            throw MCPClientOperationCode.operationBusy
        }
        lockFD = fd
    }

    deinit { close(lockFD); close(dirFD) }

    func read() throws -> MCPRegistrationRecord? {
        let fd = openat(dirFD, recordName, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        if fd < 0 && errno == ENOENT { return nil }
        guard fd >= 0 else { throw MCPClientOperationCode.recoveryFailed }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close() }
        var st = stat()
        guard fstat(fd, &st) == 0, st.st_uid == getuid(), st.st_mode & S_IFMT == S_IFREG,
              st.st_mode & 0o077 == 0, st.st_size <= 4 * MCPChildIO.limit, let data = try handle.readToEnd() else {
            throw MCPClientOperationCode.recoveryFailed
        }
        let record = try JSONDecoder().decode(MCPRegistrationRecord.self, from: data)
        guard record.server == MCPClientRegistration.serverID, record.client == client.rawValue, record.scope == "user",
              record.file.hasPrefix("/"), try record.intended.object() != nil else { throw MCPClientOperationCode.recoveryFailed }
        _ = try record.prior.object()
        _ = try record.observed?.object()
        return record
    }

    func save(_ record: MCPRegistrationRecord) throws {
        let name = "." + client.rawValue + "-" + UUID().uuidString
        let fd = openat(dirFD, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw MCPClientOperationCode.snapshotReadFailed }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close(); unlinkat(dirFD, name, 0) }
        try handle.write(contentsOf: JSONEncoder().encode(record))
        guard fsync(fd) == 0, renameat(dirFD, name, dirFD, recordName) == 0, fsync(dirFD) == 0 else {
            throw MCPClientOperationCode.snapshotReadFailed
        }
    }

    func clear() throws {
        guard unlinkat(dirFD, recordName, 0) == 0 || errno == ENOENT, fsync(dirFD) == 0 else { throw MCPClientOperationCode.recoveryFailed }
    }
}
