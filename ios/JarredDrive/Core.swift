import CryptoKit
import Foundation

struct ManifestFile: Codable, Hashable {
    let name: String
    let size: Int
    let sha256: String
}

struct SessionManifest: Codable, Identifiable, Hashable {
    let schemaVersion: String
    let telemetrySchemaVersion: String
    let deviceID: String
    let sessionID: String
    let startTimeUTC: String
    let endTimeUTC: String
    let durationS: Double
    let firmwareVersion: String
    let hardwareRevision: String
    let vescConfigID: String
    let vescConfigHash: String
    let files: [ManifestFile]
    let dataKind: String?
    let scenario: String?

    var id: String { sessionID }
    var isSynthetic: Bool { dataKind == "synthetic" }

    enum CodingKeys: String, CodingKey {
        case files, scenario
        case schemaVersion = "schema_version"
        case telemetrySchemaVersion = "telemetry_schema_version"
        case deviceID = "device_id"
        case sessionID = "session_id"
        case startTimeUTC = "start_time_utc"
        case endTimeUTC = "end_time_utc"
        case durationS = "duration_s"
        case firmwareVersion = "firmware_version"
        case hardwareRevision = "hardware_revision"
        case vescConfigID = "vesc_config_id"
        case vescConfigHash = "vesc_config_hash"
        case dataKind = "data_kind"
    }
}

struct DeviceInfo: Codable {
    let deviceID: String
    let name: String
    let hardwareRevision: String
    let firmwareVersion: String
    let dataKind: String?
    let capabilities: [String: Bool]?

    enum CodingKeys: String, CodingKey {
        case name, capabilities
        case deviceID = "device_id"
        case hardwareRevision = "hardware_revision"
        case firmwareVersion = "firmware_version"
        case dataKind = "data_kind"
    }
}

struct DeviceStatus: Codable {
    let mode: String
    let batteryPercent: Double
    let sdFreePercent: Double

    enum CodingKeys: String, CodingKey {
        case mode
        case batteryPercent = "battery_percent"
        case sdFreePercent = "sd_free_percent"
    }
}

struct RemoteSession: Codable {
    let sessionID: String
    enum CodingKeys: String, CodingKey { case sessionID = "session_id" }
}

enum SyncFailure: LocalizedError {
    case invalidAddress
    case badResponse(Int)
    case unsafeName(String)
    case sizeMismatch(String)
    case checksumMismatch(String)
    case rawCollision(String)
    case missingTelemetry

    var errorDescription: String? {
        switch self {
        case .invalidAddress: return "Enter a complete http:// address."
        case .badResponse(let code): return "Logger returned HTTP \(code)."
        case .unsafeName(let name): return "The logger supplied an unsafe filename: \(name)."
        case .sizeMismatch(let name): return "Downloaded size did not match for \(name)."
        case .checksumMismatch(let name): return "Checksum verification failed for \(name)."
        case .rawCollision(let id): return "A different raw session already exists for \(id)."
        case .missingTelemetry: return "The session does not contain telemetry.csv."
        }
    }
}

actor LoggerClient {
    let baseURL: URL
    private let decoder = JSONDecoder()

    init(address: String) throws {
        guard let url = URL(string: address), url.scheme == "http", url.host != nil else {
            throw SyncFailure.invalidAddress
        }
        baseURL = url
    }

    private func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        let url = baseURL.appending(path: path)
        let (data, response) = try await URLSession.shared.data(from: url)
        try Self.requireSuccess(response)
        return try decoder.decode(type, from: data)
    }

    func device() async throws -> DeviceInfo { try await get("api/device", as: DeviceInfo.self) }
    func status() async throws -> DeviceStatus { try await get("api/status", as: DeviceStatus.self) }
    func sessions() async throws -> [RemoteSession] {
        try await get("api/sessions", as: [RemoteSession].self)
    }
    func manifest(_ id: String) async throws -> SessionManifest {
        try Self.requireSafe(id)
        return try await get("api/sessions/\(id)/manifest", as: SessionManifest.self)
    }

    func download(sessionID: String, file: ManifestFile, to partialURL: URL) async throws {
        try Self.requireSafe(sessionID)
        try Self.requireSafe(file.name)
        let existing = (try? partialURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        var request = URLRequest(
            url: baseURL.appending(path: "api/sessions/\(sessionID)/files/\(file.name)")
        )
        if existing > 0 { request.setValue("bytes=\(existing)-", forHTTPHeaderField: "Range") }
        let (temporary, response) = try await URLSession.shared.download(for: request)
        try Self.requireSuccess(response)
        let resumed = existing > 0 && (response as? HTTPURLResponse)?.statusCode == 206
        if resumed {
            let reader = try FileHandle(forReadingFrom: temporary)
            let writer = try FileHandle(forWritingTo: partialURL)
            try writer.seekToEnd()
            while let chunk = try reader.read(upToCount: 1024 * 1024), !chunk.isEmpty {
                try writer.write(contentsOf: chunk)
            }
            try reader.close()
            try writer.close()
        } else {
            if FileManager.default.fileExists(atPath: partialURL.path) {
                try FileManager.default.removeItem(at: partialURL)
            }
            try FileManager.default.moveItem(at: temporary, to: partialURL)
        }
    }

    private static func requireSuccess(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw SyncFailure.badResponse((response as? HTTPURLResponse)?.statusCode ?? -1)
        }
    }

    static func requireSafe(_ component: String) throws {
        guard !component.isEmpty,
              component != ".", component != "..",
              !component.contains("/"), !component.contains("\\") else {
            throw SyncFailure.unsafeName(component)
        }
    }
}

actor SessionStore {
    private let manager = FileManager.default
    let root: URL

    init(root: URL? = nil) {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        self.root = root ?? support.appending(path: "JarredDrive/raw", directoryHint: .isDirectory)
    }

    func localManifests() throws -> [SessionManifest] {
        guard manager.fileExists(atPath: root.path) else { return [] }
        let deviceDirectories = try manager.contentsOfDirectory(
            at: root, includingPropertiesForKeys: [.isDirectoryKey]
        )
        var manifests: [SessionManifest] = []
        for device in deviceDirectories {
            let sessions = (try? manager.contentsOfDirectory(at: device, includingPropertiesForKeys: nil)) ?? []
            for session in sessions where !session.lastPathComponent.hasPrefix(".") {
                let url = session.appending(path: "manifest.json")
                if let data = try? Data(contentsOf: url),
                   let manifest = try? JSONDecoder().decode(SessionManifest.self, from: data) {
                    manifests.append(manifest)
                }
            }
        }
        return manifests.sorted { $0.startTimeUTC > $1.startTimeUTC }
    }

    func sync(manifest: SessionManifest, client: LoggerClient) async throws {
        try LoggerClient.requireSafe(manifest.deviceID)
        try LoggerClient.requireSafe(manifest.sessionID)
        let deviceRoot = root.appending(path: manifest.deviceID, directoryHint: .isDirectory)
        let destination = deviceRoot.appending(path: manifest.sessionID, directoryHint: .isDirectory)
        let existingManifest = destination.appending(path: "manifest.json")
        let encoded = try JSONEncoder.sorted.encode(manifest)
        if manager.fileExists(atPath: existingManifest.path) {
            guard try Data(contentsOf: existingManifest) == encoded else {
                throw SyncFailure.rawCollision(manifest.sessionID)
            }
            return
        }

        let staging = deviceRoot.appending(path: ".\(manifest.sessionID).staging", directoryHint: .isDirectory)
        try manager.createDirectory(at: staging, withIntermediateDirectories: true)
        for file in manifest.files {
            try LoggerClient.requireSafe(file.name)
            let completed = staging.appending(path: file.name)
            if manager.fileExists(atPath: completed.path) {
                let values = try completed.resourceValues(forKeys: [.fileSizeKey])
                guard values.fileSize == file.size, try Self.sha256(completed) == file.sha256.lowercased() else {
                    throw SyncFailure.checksumMismatch(file.name)
                }
                continue
            }
            let partial = staging.appending(path: file.name + ".part")
            try await client.download(sessionID: manifest.sessionID, file: file, to: partial)
            let values = try partial.resourceValues(forKeys: [.fileSizeKey])
            guard values.fileSize == file.size else { throw SyncFailure.sizeMismatch(file.name) }
            guard try Self.sha256(partial) == file.sha256.lowercased() else {
                throw SyncFailure.checksumMismatch(file.name)
            }
            try manager.moveItem(at: partial, to: completed)
        }
        try encoded.write(to: staging.appending(path: "manifest.json"), options: .atomic)
        try manager.createDirectory(at: deviceRoot, withIntermediateDirectories: true)
        try manager.moveItem(at: staging, to: destination)
    }

    func telemetryURL(for manifest: SessionManifest) throws -> URL {
        guard manifest.files.contains(where: { $0.name == "telemetry.csv" }) else {
            throw SyncFailure.missingTelemetry
        }
        return root
            .appending(path: manifest.deviceID)
            .appending(path: manifest.sessionID)
            .appending(path: "telemetry.csv")
    }

    func configURL(for manifest: SessionManifest) -> URL {
        root.appending(path: manifest.deviceID)
            .appending(path: manifest.sessionID)
            .appending(path: "config.json")
    }

    private static func sha256(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            hasher.update(data: chunk)
        }
        try handle.close()
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

private extension JSONEncoder {
    static var sorted: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }
}

struct RideSummary {
    struct Issue: Identifiable {
        let id: String
        let title: String
        let icon: String
        let headline: String
        let evidence: [String]
        let nextCheck: String
    }

    struct LaunchPoint: Identifiable {
        let id: Int
        let attemptID: Int
        let seconds: Double
        let powerKW: Double
        let outcome: String
    }

    struct RideDuration: Identifiable {
        let rideID: Int
        let durationS: Double
        let foilS: Double
        var id: Int { rideID }
    }

    struct TrackPoint: Identifiable {
        let id: Int
        let eastM: Double
        let northM: Double
        let speedMPH: Double
    }

    let durationS: Double
    let energyWh: Double
    let peakSpeedMPS: Double
    let peakPackC: Double
    let peakPackDeltaC: Double
    let attempts: Int
    let successfulAttempts: Int
    let launchCrashes: Int
    let rideFalls: Int
    let foilTimeS: Double
    let longestRideS: Double
    let medianTakeoffS: Double
    let touchdowns: Int
    let recoveries: Int
    let distanceM: Double
    let meanFoilSpeedMPS: Double
    let failedAttempts: Int
    let medianLaunchEnergyWh: Double
    let worstVoltageSagV: Double
    let medianRideS: Double
    let foilVibrationP95G: Double
    let peakFoilGyroDPS: Double
    let peakFallAccelDeltaG: Double
    let peakFallGyroDPS: Double
    let launchPoints: [LaunchPoint]
    let rideDurations: [RideDuration]
    let trackPoints: [TrackPoint]
    let waterAlarm: Bool
    let waterAlarmSamples: Int
    let minimumWaterADC: Double
    let faultSamples: Int
    let faultCodes: [Int]
    let storageFaultSamples: Int

    var reviewLabel: String {
        issues.isEmpty ? "No issues detected" : "Needs investigation"
    }

    var issues: [Issue] {
        var findings: [Issue] = []
        if waterAlarm {
            findings.append(Issue(
                id: "water",
                title: "Water alarm asserted",
                icon: "drop.triangle.fill",
                headline: "The enclosure water channel crossed its alarm condition during this run.",
                evidence: ["\(waterAlarmSamples) alarmed samples", String(format: "Minimum water ADC %.0f", minimumWaterADC)],
                nextCheck: "Inspect the enclosure and connector path, then review the raw water trace around the first alarm."
            ))
        }
        if storageFaultSamples > 0 {
            findings.append(Issue(
                id: "storage",
                title: "Logger storage degraded",
                icon: "sdcard.fill",
                headline: "The logger reported that storage was not healthy during part of the session.",
                evidence: ["\(storageFaultSamples) unhealthy samples"],
                nextCheck: "Check SD status and free space, then inspect timestamp gaps before trusting session completeness."
            ))
        }
        if faultSamples > 0 {
            let codes = faultCodes.map(String.init).joined(separator: ", ")
            findings.append(Issue(
                id: "vesc",
                title: "VESC fault observed",
                icon: "bolt.trianglebadge.exclamationmark.fill",
                headline: "One or more non-zero VESC fault codes were recorded.",
                evidence: ["\(faultSamples) fault samples", "Codes: \(codes.isEmpty ? "unknown" : codes)"],
                nextCheck: "Inspect the fault window alongside voltage, current, temperature, and the VESC Tool fault history."
            ))
        }
        if peakPackC >= 40 || peakPackDeltaC >= 5 {
            findings.append(Issue(
                id: "thermal",
                title: "Pack thermal anomaly",
                icon: "thermometer.high",
                headline: "Pack temperature or sensor spread was unusually elevated and deserves investigation.",
                evidence: [String(format: "Peak %.1f °C", peakPackC), String(format: "Maximum spread %.1f °C", peakPackDeltaC)],
                nextCheck: "Compare all pack-sensor traces, verify sensor attachment, and inspect the electrical load around the rise."
            ))
        }
        if launchCrashes > 0 {
            findings.append(Issue(
                id: "launch-crash",
                title: "Launch crash recorded",
                icon: "figure.fall",
                headline: "A fall occurred before takeoff during at least one launch attempt.",
                evidence: ["\(launchCrashes) launch crash\(launchCrashes == 1 ? "" : "es")"],
                nextCheck: "Compare the failed power ramp with successful launches and inspect the fall window before changing tuning."
            ))
        }
        return findings
    }

    var launchSuccess: Double {
        attempts > 0 ? Double(successfulAttempts) / Double(attempts) : 0
    }

    var foilUtilization: Double {
        durationS > 0 ? foilTimeS / durationS : 0
    }

    var energyPerMile: Double? {
        let miles = distanceM / 1609.344
        return miles > 0 ? energyWh / miles : nil
    }

    static func analyze(_ url: URL) throws -> RideSummary {
        let text = try String(contentsOf: url, encoding: .utf8)
        var lines = text.split(whereSeparator: \.isNewline)
        guard !lines.isEmpty else { throw SyncFailure.missingTelemetry }
        let headers = lines.removeFirst().split(separator: ",", omittingEmptySubsequences: false).map(String.init)
        let indexes = Dictionary(uniqueKeysWithValues: headers.enumerated().map { ($1, $0) })
        func number(_ row: [Substring], _ name: String) -> Double? {
            guard let index = indexes[name], row.indices.contains(index) else { return nil }
            return Double(row[index])
        }
        func cell(_ row: [Substring], _ name: String) -> String? {
            guard let index = indexes[name], row.indices.contains(index), !row[index].isEmpty else {
                return nil
            }
            return String(row[index])
        }
        var firstMS: Double?, lastMS: Double?, firstWh: Double?, lastWh: Double?
        var peakSpeed = 0.0, peakPack = -Double.infinity, peakDelta = 0.0
        var water = false, waterSamples = 0, minimumWaterADC = Double.infinity
        var faults = 0, faultCodes = Set<Int>(), storageFaults = 0
        var attempts = Set<Int>(), successes = Set<Int>(), crashes = Set<Int>()
        var attemptStarts: [Int: Double] = [:]
        var takeoffs: [Int: Double] = [:]
        var rideEnds: [Int: Double] = [:]
        var launchEnergy: [Int: Double] = [:]
        var launchStartVoltage: [Int: Double] = [:]
        var launchMinVoltage: [Int: Double] = [:]
        var rideFoilTime: [Int: Double] = [:]
        var rawLaunchPoints: [(Int, Double, Double)] = []
        var rawTrackPoints: [(Double, Double, Double)] = []
        var foilTime = 0.0, distance = 0.0, foilSpeedTotal = 0.0
        var foilSpeedSamples = 0, rideFalls = 0, touchdowns = 0, recoveries = 0
        var visualSampleIndex = 0
        var foilVibration: [Double] = []
        var peakFoilGyro = 0.0, peakFallAccel = 0.0, peakFallGyro = 0.0
        var previousTimestamp: Double?
        var previousState: String?
        for line in lines {
            let row = line.split(separator: ",", omittingEmptySubsequences: false)
            let timestamp = number(row, "timestamp_ms") ?? 0
            let dt = max(0, (previousTimestamp.map { timestamp - $0 } ?? 0) / 1000)
            let state = cell(row, "sim_state")
                ?? cell(row, "state_inferred")
                ?? cell(row, "ride_state")
                ?? ""
            let outcome = cell(row, "sim_outcome") ?? ""
            let attemptID = number(row, "sim_attempt_id").map(Int.init) ?? -1
            let accelMagnitude = sqrt(
                pow(number(row, "accel_x_g") ?? 0, 2)
                    + pow(number(row, "accel_y_g") ?? 0, 2)
                    + pow(number(row, "accel_z_g") ?? 0, 2)
            )
            let gyroMagnitude = sqrt(
                pow(number(row, "gyro_x_dps") ?? 0, 2)
                    + pow(number(row, "gyro_y_dps") ?? 0, 2)
                    + pow(number(row, "gyro_z_dps") ?? 0, 2)
            )
            firstMS = firstMS ?? timestamp; lastMS = timestamp
            if let wh = number(row, "watt_hours") { firstWh = firstWh ?? wh; lastWh = wh }
            let speed = number(row, "gps_speed_mps") ?? 0
            peakSpeed = max(peakSpeed, speed)
            distance += max(0, speed) * dt
            if state == "FOILING" {
                foilTime += dt
                foilVibration.append(abs(accelMagnitude - 1))
                peakFoilGyro = max(peakFoilGyro, gyroMagnitude)
                if attemptID > 0 { rideFoilTime[attemptID, default: 0] += dt }
                if speed > 0 {
                    foilSpeedTotal += speed
                    foilSpeedSamples += 1
                }
            }
            if state == "FALL" {
                peakFallAccel = max(peakFallAccel, abs(accelMagnitude - 1))
                peakFallGyro = max(peakFallGyro, gyroMagnitude)
            }
            let packs = (1...6).compactMap { number(row, "pack\($0)_C") }
            if let hottest = packs.max(), let coldest = packs.min() {
                peakPack = max(peakPack, hottest); peakDelta = max(peakDelta, hottest - coldest)
            }
            if let index = indexes["water_alarm"], row.indices.contains(index) {
                let alarmed = ["true", "1"].contains(row[index].lowercased())
                water = water || alarmed
                if alarmed { waterSamples += 1 }
            }
            if let waterADC = number(row, "water_adc") { minimumWaterADC = min(minimumWaterADC, waterADC) }
            let faultCode = Int(number(row, "fault_code") ?? 0)
            if faultCode != 0 { faults += 1; faultCodes.insert(faultCode) }
            if let index = indexes["sd_ok"], row.indices.contains(index),
               ["false", "0"].contains(row[index].lowercased()) { storageFaults += 1 }
            if attemptID > 0 {
                attempts.insert(attemptID)
                if outcome == "SUCCESS" { successes.insert(attemptID) }
                if outcome == "LAUNCH_CRASH" { crashes.insert(attemptID) }
                if state == "ACCELERATING", attemptStarts[attemptID] == nil {
                    attemptStarts[attemptID] = timestamp
                }
                if state == "ACCELERATING" {
                    let voltage = number(row, "vesc_vin_V") ?? 0
                    let power = max(0, voltage * (number(row, "vesc_battery_A") ?? 0))
                    launchEnergy[attemptID, default: 0] += power * dt / 3600
                    launchStartVoltage[attemptID] = launchStartVoltage[attemptID] ?? voltage
                    launchMinVoltage[attemptID] = min(launchMinVoltage[attemptID] ?? voltage, voltage)
                    if visualSampleIndex.isMultiple(of: 4),
                       let start = attemptStarts[attemptID] {
                        rawLaunchPoints.append((attemptID, (timestamp - start) / 1000, power / 1000))
                    }
                }
                if state == "FOILING", takeoffs[attemptID] == nil {
                    takeoffs[attemptID] = timestamp
                }
                if state == "FALL", rideEnds[attemptID] == nil {
                    rideEnds[attemptID] = timestamp
                }
            }
            if visualSampleIndex.isMultiple(of: 20),
               let latitude = number(row, "gps_lat"),
               let longitude = number(row, "gps_lon"),
               (number(row, "gps_fix_quality") ?? 0) > 0 {
                rawTrackPoints.append((latitude, longitude, speed * 2.23694))
            }
            visualSampleIndex += 1
            if state != previousState {
                if state == "TOUCHDOWN" { touchdowns += 1 }
                if state == "FOILING", previousState == "TOUCHDOWN" { recoveries += 1 }
                if state == "FALL", outcome == "SUCCESS" { rideFalls += 1 }
            }
            previousTimestamp = timestamp
            previousState = state
        }
        let takeoffTimes = successes.compactMap { id -> Double? in
            guard let start = attemptStarts[id], let takeoff = takeoffs[id] else { return nil }
            return max(0, (takeoff - start) / 1000)
        }.sorted()
        let medianTakeoff: Double
        if takeoffTimes.isEmpty {
            medianTakeoff = 0
        } else if takeoffTimes.count.isMultiple(of: 2) {
            let upper = takeoffTimes.count / 2
            medianTakeoff = (takeoffTimes[upper - 1] + takeoffTimes[upper]) / 2
        } else {
            medianTakeoff = takeoffTimes[takeoffTimes.count / 2]
        }
        let longestRide = successes.compactMap { id -> Double? in
            guard let takeoff = takeoffs[id] else { return nil }
            return max(0, ((rideEnds[id] ?? lastMS ?? takeoff) - takeoff) / 1000)
        }.max() ?? 0
        let rideDurations = successes.sorted().compactMap { id -> RideDuration? in
            guard let takeoff = takeoffs[id] else { return nil }
            let duration = max(0, ((rideEnds[id] ?? lastMS ?? takeoff) - takeoff) / 1000)
            return RideDuration(rideID: id, durationS: duration, foilS: rideFoilTime[id] ?? 0)
        }
        let sortedRideDurations = rideDurations.map(\.durationS).sorted()
        let medianRide: Double
        if sortedRideDurations.isEmpty {
            medianRide = 0
        } else if sortedRideDurations.count.isMultiple(of: 2) {
            let upper = sortedRideDurations.count / 2
            medianRide = (sortedRideDurations[upper - 1] + sortedRideDurations[upper]) / 2
        } else {
            medianRide = sortedRideDurations[sortedRideDurations.count / 2]
        }
        let launchEnergies = attempts.compactMap { launchEnergy[$0] }.sorted()
        let sortedVibration = foilVibration.sorted()
        let vibrationP95 = sortedVibration.isEmpty
            ? 0
            : sortedVibration[min(sortedVibration.count - 1, Int(Double(sortedVibration.count - 1) * 0.95))]
        let medianLaunchEnergy: Double
        if launchEnergies.isEmpty {
            medianLaunchEnergy = 0
        } else if launchEnergies.count.isMultiple(of: 2) {
            let upper = launchEnergies.count / 2
            medianLaunchEnergy = (launchEnergies[upper - 1] + launchEnergies[upper]) / 2
        } else {
            medianLaunchEnergy = launchEnergies[launchEnergies.count / 2]
        }
        let outcomes = Dictionary(uniqueKeysWithValues: attempts.map { id in
            (id, crashes.contains(id) ? "Launch crash" : successes.contains(id) ? "Success" : "Aborted")
        })
        let launchPoints = rawLaunchPoints.enumerated().map { index, point in
            LaunchPoint(
                id: index,
                attemptID: point.0,
                seconds: point.1,
                powerKW: point.2,
                outcome: outcomes[point.0] ?? "Aborted"
            )
        }
        let trackPoints: [TrackPoint]
        if let origin = rawTrackPoints.first {
            let latitudeScale = 111_320.0
            let longitudeScale = latitudeScale * cos(origin.0 * .pi / 180)
            trackPoints = rawTrackPoints.enumerated().map { index, point in
                TrackPoint(
                    id: index,
                    eastM: (point.1 - origin.1) * longitudeScale,
                    northM: (point.0 - origin.0) * latitudeScale,
                    speedMPH: point.2
                )
            }
        } else {
            trackPoints = []
        }
        return RideSummary(
            durationS: ((lastMS ?? 0) - (firstMS ?? 0)) / 1000,
            energyWh: (lastWh ?? 0) - (firstWh ?? 0),
            peakSpeedMPS: peakSpeed,
            peakPackC: peakPack.isFinite ? peakPack : 0,
            peakPackDeltaC: peakDelta,
            attempts: attempts.count,
            successfulAttempts: successes.count,
            launchCrashes: crashes.count,
            rideFalls: rideFalls,
            foilTimeS: foilTime,
            longestRideS: longestRide,
            medianTakeoffS: medianTakeoff,
            touchdowns: touchdowns,
            recoveries: recoveries,
            distanceM: distance,
            meanFoilSpeedMPS: foilSpeedSamples > 0 ? foilSpeedTotal / Double(foilSpeedSamples) : 0,
            failedAttempts: max(0, attempts.count - successes.count - crashes.count),
            medianLaunchEnergyWh: medianLaunchEnergy,
            worstVoltageSagV: attempts.map {
                max(0, (launchStartVoltage[$0] ?? 0) - (launchMinVoltage[$0] ?? 0))
            }.max() ?? 0,
            medianRideS: medianRide,
            foilVibrationP95G: vibrationP95,
            peakFoilGyroDPS: peakFoilGyro,
            peakFallAccelDeltaG: peakFallAccel,
            peakFallGyroDPS: peakFallGyro,
            launchPoints: launchPoints,
            rideDurations: rideDurations,
            trackPoints: trackPoints,
            waterAlarm: water,
            waterAlarmSamples: waterSamples,
            minimumWaterADC: minimumWaterADC.isFinite ? minimumWaterADC : 0,
            faultSamples: faults,
            faultCodes: faultCodes.sorted(),
            storageFaultSamples: storageFaults
        )
    }
}

struct AnalysisHandoff {
    static func markdown(manifest: SessionManifest, summary: RideSummary, config: String?) -> String {
        let provenance = manifest.isSynthetic ? "SYNTHETIC TEST DATA — not a hardware observation" : "Recorded logger data"
        let findings = summary.issues.isEmpty
            ? "No issue triggers were detected by the current app rules."
            : summary.issues.map { issue in
                "### \(issue.title)\n\(issue.headline)\nEvidence: \(issue.evidence.joined(separator: "; "))\nInformation needed next: \(issue.nextCheck)"
            }.joined(separator: "\n\n")
        return """
        # Jarred Drive analysis handoff

        \(provenance)

        Session: \(manifest.sessionID)  
        Configuration snapshot: \(manifest.vescConfigID)  
        Duration: \(String(format: "%.1f", summary.durationS)) s  
        Energy: \(String(format: "%.1f", summary.energyWh)) Wh  
        Peak GPS speed: \(String(format: "%.2f", summary.peakSpeedMPS)) m/s  
        Peak pack temperature: \(String(format: "%.1f", summary.peakPackC)) C  
        Peak pack spread: \(String(format: "%.1f", summary.peakPackDeltaC)) C  
        Launch success: \(String(format: "%.0f", summary.launchSuccess * 100))% (\(summary.successfulAttempts)/\(summary.attempts))  
        Foil time: \(String(format: "%.1f", summary.foilTimeS)) s (\(String(format: "%.0f", summary.foilUtilization * 100))%)  
        Longest ride: \(String(format: "%.1f", summary.longestRideS)) s  
        Median time to takeoff: \(String(format: "%.1f", summary.medianTakeoffS)) s  
        Ride falls: \(summary.rideFalls)  
        Touchdown recoveries: \(summary.recoveries)/\(summary.touchdowns)  
        Distance: \(String(format: "%.0f", summary.distanceM)) m  
        Mean foil speed: \(String(format: "%.2f", summary.meanFoilSpeedMPS)) m/s  
        Median launch energy: \(String(format: "%.2f", summary.medianLaunchEnergyWh)) Wh  
        Worst launch voltage sag: \(String(format: "%.2f", summary.worstVoltageSagV)) V  
        Foil vibration p95: \(String(format: "%.2f", summary.foilVibrationP95G)) g  
        Peak foil angular rate: \(String(format: "%.0f", summary.peakFoilGyroDPS)) deg/s  
        Worst fall transient: \(String(format: "%.2f", summary.peakFallAccelDeltaG)) g / \(String(format: "%.0f", summary.peakFallGyroDPS)) deg/s  
        Water alarm observed: \(summary.waterAlarm)  
        VESC fault samples: \(summary.faultSamples)  
        Storage-fault samples: \(summary.storageFaultSamples)

        ## Findings requiring investigation

        \(findings)

        ## Read-only configuration snapshot

        ```json
        \(config ?? "Unavailable")
        ```

        Please analyze this observational summary, identify questions or anomalies worth investigating, and suggest a conservative next test. Do not issue commands or assume simulated results establish hardware safety or performance.
        """
    }
}
