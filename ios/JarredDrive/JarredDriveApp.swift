import Charts
import SwiftUI
import UIKit

@main
struct JarredDriveApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup { ContentView().environmentObject(model) }
    }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var manifests: [SessionManifest] = []
    @Published var device: DeviceInfo?
    @Published var status: DeviceStatus?
    @Published var message = "Ready"
    @Published var isSyncing = false
    @Published var loggerAddress: String {
        didSet { UserDefaults.standard.set(loggerAddress, forKey: "loggerAddress") }
    }
    let store = SessionStore()

    init() {
        loggerAddress = UserDefaults.standard.string(forKey: "loggerAddress")
            ?? "http://127.0.0.1:8765"
        Task { await reload() }
    }

    func reload() async {
        do { manifests = try await store.localManifests() }
        catch { message = error.localizedDescription }
    }

    func sync() async {
        isSyncing = true
        defer { isSyncing = false }
        do {
            let client = try LoggerClient(address: loggerAddress)
            async let fetchedDevice = client.device()
            async let fetchedStatus = client.status()
            device = try await fetchedDevice
            status = try await fetchedStatus
            let remote = try await client.sessions()
            let known = Set(manifests.map(\.sessionID))
            let missing = remote.filter { !known.contains($0.sessionID) }
            for (index, session) in missing.enumerated() {
                message = "Copying \(index + 1) of \(missing.count)…"
                let manifest = try await client.manifest(session.sessionID)
                try await store.sync(manifest: manifest, client: client)
            }
            await reload()
            message = missing.isEmpty ? "Everything is in sync" : "Imported \(missing.count) session(s)"
        } catch {
            message = error.localizedDescription
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @State private var scrollIdentity = UUID()

    var body: some View {
        NavigationStack {
            ZStack {
                JD.deepWater.ignoresSafeArea()
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 22) {
                        brandHeader
                        connectionCard
                        if let device = model.device, let status = model.status {
                            loggerCard(device: device, status: status)
                        }
                        sectionTitle("RECENT SESSIONS", detail: "Tap a ride for the field debrief")
                        if model.manifests.isEmpty {
                            JDCard {
                                VStack(spacing: 12) {
                                    Image(systemName: "waveform.path.ecg")
                                        .font(.system(size: 34)).foregroundStyle(JD.cyan)
                                    Text("No sessions yet").font(.headline)
                                    Text("Connect to the logger to bring a ride onto this phone.")
                                        .font(.subheadline).foregroundStyle(JD.muted)
                                }
                                .frame(maxWidth: .infinity).padding(.vertical, 20)
                            }
                        }
                        ForEach(model.manifests) { manifest in
                            NavigationLink(value: manifest) { sessionCard(manifest) }
                                .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 18).padding(.bottom, 32)
                }
                .id(scrollIdentity)
            }
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(for: SessionManifest.self) { SessionView(manifest: $0) }
        }
        .tint(JD.cyan)
        .preferredColorScheme(.dark)
    }

    private var brandHeader: some View {
        HStack(spacing: 15) {
            BundledImage(name: "jarred-drive-mark", contentMode: .fit)
                .frame(width: 72, height: 72)
                .clipShape(RoundedRectangle(cornerRadius: 18))
            VStack(alignment: .leading, spacing: 3) {
                Text("JARRED DRIVE").font(.caption.bold()).tracking(2.2).foregroundStyle(JD.cyan)
                Text("Field Deck").font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Launch. Ride. Learn.").font(.subheadline).foregroundStyle(JD.muted)
            }
        }
        .padding(.top, 12)
    }

    private var connectionCard: some View {
        JDCard(accent: JD.cyan) {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Label("DIRECT SYNC", systemImage: "antenna.radiowaves.left.and.right")
                        .font(.caption.bold()).foregroundStyle(JD.cyan)
                    Spacer()
                    Circle().fill(model.isSyncing ? JD.amber : JD.green).frame(width: 8, height: 8)
                    Text(model.isSyncing ? "SYNCING" : "READY")
                        .font(.caption2.bold()).foregroundStyle(JD.muted)
                }
                TextField("Logger address", text: $model.loggerAddress)
                    .textInputAutocapitalization(.never).keyboardType(.URL).autocorrectionDisabled()
                    .font(.system(.subheadline, design: .monospaced))
                    .padding(12).background(JD.deepWater.opacity(0.75), in: RoundedRectangle(cornerRadius: 12))
                Button { Task { await model.sync() } } label: {
                    HStack {
                        Image(systemName: "arrow.down.circle.fill")
                        Text(model.isSyncing ? "Syncing sessions…" : "Sync from logger").fontWeight(.semibold)
                        Spacer()
                        if model.isSyncing { ProgressView().tint(JD.deepWater) }
                    }
                    .foregroundStyle(JD.deepWater).padding(13)
                    .background(JD.cyan, in: RoundedRectangle(cornerRadius: 13))
                }
                .disabled(model.isSyncing)
                Text(model.message).font(.caption).foregroundStyle(JD.muted)
            }
        }
    }

    private func loggerCard(device: DeviceInfo, status: DeviceStatus) -> some View {
        JDCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("LOGGER").font(.caption.bold()).tracking(1.4).foregroundStyle(JD.muted)
                        Text(device.name).font(.headline)
                    }
                    Spacer()
                    Text(status.mode.uppercased()).font(.caption.bold()).foregroundStyle(JD.green)
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(JD.green.opacity(0.12), in: Capsule())
                }
                HStack(spacing: 12) {
                    compactGauge("Battery", value: status.batteryPercent / 100, label: String(format: "%.0f%%", status.batteryPercent), color: JD.green)
                    compactGauge("Storage", value: status.sdFreePercent / 100, label: String(format: "%.0f%%", status.sdFreePercent), color: JD.cyan)
                    VStack(alignment: .leading, spacing: 7) {
                        Image(systemName: device.dataKind == "synthetic" ? "testtube.2" : "checkmark.shield.fill")
                            .font(.title2).foregroundStyle(device.dataKind == "synthetic" ? JD.amber : JD.green)
                        Text(device.dataKind == "synthetic" ? "Synthetic" : "Recorded").font(.subheadline.bold())
                        Text("source").font(.caption).foregroundStyle(JD.muted)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }

    private func compactGauge(_ title: String, value: Double, label: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(label).font(.title2.bold()).foregroundStyle(color)
            ProgressView(value: value).tint(color)
            Text(title).font(.caption).foregroundStyle(JD.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func sessionCard(_ manifest: SessionManifest) -> some View {
        JDCard(accent: scenarioColor(manifest)) {
            HStack(spacing: 14) {
                ZStack {
                    RoundedRectangle(cornerRadius: 16).fill(scenarioColor(manifest).opacity(0.13))
                    Image(systemName: scenarioIcon(manifest)).font(.title2).foregroundStyle(scenarioColor(manifest))
                }
                .frame(width: 56, height: 66)
                VStack(alignment: .leading, spacing: 7) {
                    Text(manifest.scenario ?? manifest.sessionID).font(.headline).foregroundStyle(JD.ice)
                    HStack(spacing: 7) {
                        Text(String(manifest.startTimeUTC.prefix(10)))
                        Text("•")
                        Text(manifest.vescConfigID)
                        Text("•")
                        Text(shortDuration(manifest.durationS))
                    }
                    .font(.caption).foregroundStyle(JD.muted).lineLimit(1).minimumScaleFactor(0.7)
                    if manifest.isSynthetic {
                        Text("SYNTHETIC FIXTURE").font(.caption2.bold()).tracking(0.7).foregroundStyle(JD.amber)
                    }
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(JD.muted)
            }
        }
    }

    private func sectionTitle(_ title: String, detail: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption.bold()).tracking(1.5).foregroundStyle(JD.cyan)
            Text(detail).font(.caption).foregroundStyle(JD.muted)
        }
    }

    private func scenarioColor(_ manifest: SessionManifest) -> Color {
        let name = (manifest.scenario ?? "").lowercased()
        if name.contains("thermal") || name.contains("ingress") { return JD.coral }
        if name.contains("repeat") { return JD.green }
        return JD.amber
    }

    private func scenarioIcon(_ manifest: SessionManifest) -> String {
        let name = (manifest.scenario ?? "").lowercased()
        if name.contains("thermal") { return "thermometer.high" }
        if name.contains("ingress") { return "drop.triangle.fill" }
        if name.contains("repeat") { return "arrow.triangle.2.circlepath" }
        return "figure.surfing"
    }

    private func shortDuration(_ seconds: Double) -> String {
        String(format: "%.1f min", seconds / 60)
    }
}

struct SessionView: View {
    @EnvironmentObject private var model: AppModel
    let manifest: SessionManifest
    @State private var summary: RideSummary?
    @State private var config: String?
    @State private var error: String?

    var body: some View {
        ZStack {
            JD.deepWater.ignoresSafeArea()
            ScrollView {
                LazyVStack(spacing: 18) {
                    if let summary {
                        sessionHero(summary)
                        if !summary.issues.isEmpty { issueOverview(summary) }
                        if summary.attempts > 0 {
                            fieldDebrief(summary)
                            launchLab(summary)
                            rideDynamics(summary)
                        }
                        systemHealth(summary)
                        analysisCard(summary)
                        configurationCard
                    } else if let error {
                        JDCard { ContentUnavailableView("Could not analyze session", systemImage: "exclamationmark.triangle", description: Text(error)) }
                    } else {
                        ProgressView("Analyzing local copy…").tint(JD.cyan).padding(.top, 100)
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 36)
            }
        }
        .navigationTitle("Field Debrief")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(JD.panel, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .task { await load() }
    }

    private func sessionHero(_ summary: RideSummary) -> some View {
        GeometryReader { geometry in
            ZStack(alignment: .bottomLeading) {
                BundledImage(name: "jarred-drive-hero", contentMode: .fill)
                    .frame(width: geometry.size.width, height: 250).clipped()
                LinearGradient(colors: [.clear, JD.deepWater.opacity(0.97)], startPoint: .top, endPoint: .bottom)
                VStack(alignment: .leading, spacing: 9) {
                    HStack(spacing: 8) {
                        statusBadge(summary)
                        if manifest.isSynthetic {
                            Label("SYNTHETIC", systemImage: "testtube.2").font(.caption2.bold())
                                .foregroundStyle(JD.amber).padding(.horizontal, 9).padding(.vertical, 6)
                                .background(JD.amber.opacity(0.15), in: Capsule())
                        }
                    }
                    Text(manifest.scenario ?? manifest.sessionID)
                        .font(.system(size: 30, weight: .bold, design: .rounded))
                        .lineLimit(2).minimumScaleFactor(0.8)
                    Text("\(String(manifest.startTimeUTC.prefix(10)))  •  \(manifest.vescConfigID)")
                        .font(.caption).foregroundStyle(JD.muted).lineLimit(1)
                }
                .padding(18)
            }
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .overlay(RoundedRectangle(cornerRadius: 24).stroke(JD.cyan.opacity(0.16)))
        }
        .frame(maxWidth: .infinity).frame(height: 250)
    }

    private func statusBadge(_ summary: RideSummary) -> some View {
        let needsReview = !summary.issues.isEmpty
        let label = needsReview ? "\(summary.issues.count) ISSUE\(summary.issues.count == 1 ? "" : "S")" : "CLEAR"
        return Label(label, systemImage: needsReview ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
            .font(.caption2.bold()).foregroundStyle(needsReview ? JD.amber : JD.green)
            .padding(.horizontal, 9).padding(.vertical, 6)
            .background((needsReview ? JD.amber : JD.green).opacity(0.15), in: Capsule())
    }

    private func issueOverview(_ summary: RideSummary) -> some View {
        JDCard(accent: JD.coral) {
            VStack(alignment: .leading, spacing: 16) {
                cardTitle("INVESTIGATION NEEDED", "This run captured evidence worth explaining", "exclamationmark.triangle.fill", JD.coral)
                Text("Do not reduce this run to an overall score. Each finding below identifies the evidence we have and the information to collect next.")
                    .font(.subheadline).foregroundStyle(JD.ice)
                ForEach(summary.issues) { issue in
                    VStack(alignment: .leading, spacing: 11) {
                        HStack(spacing: 9) {
                            Image(systemName: issue.icon).foregroundStyle(JD.coral)
                            Text(issue.title).font(.headline)
                        }
                        Text(issue.headline).font(.subheadline).foregroundStyle(JD.muted)
                        VStack(alignment: .leading, spacing: 7) {
                            ForEach(issue.evidence, id: \.self) { item in
                                Label(item, systemImage: "waveform.path.ecg")
                                    .font(.caption.bold()).foregroundStyle(JD.ice)
                                    .padding(.horizontal, 9).padding(.vertical, 6)
                                    .background(JD.coral.opacity(0.11), in: Capsule())
                            }
                        }
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "magnifyingglass").foregroundStyle(JD.amber)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("WHAT WE NEED NEXT").font(.caption2.bold()).tracking(0.8).foregroundStyle(JD.amber)
                                Text(issue.nextCheck).font(.caption).foregroundStyle(JD.muted)
                            }
                        }
                        .padding(10).background(JD.deepWater.opacity(0.65), in: RoundedRectangle(cornerRadius: 11))
                    }
                    .padding(13)
                    .background(JD.deepWater.opacity(0.4), in: RoundedRectangle(cornerRadius: 15))
                }
                if manifest.isSynthetic {
                    Label("Synthetic finding—use this to test the investigation workflow, not to validate hardware.", systemImage: "testtube.2")
                        .font(.caption).foregroundStyle(JD.amber)
                }
            }
        }
    }

    private func fieldDebrief(_ summary: RideSummary) -> some View {
        JDCard(accent: JD.cyan) {
            VStack(alignment: .leading, spacing: 18) {
                cardTitle("FIELD DEBRIEF", "The answer before the details", "speedometer", JD.cyan)
                HStack(spacing: 20) {
                    ProgressRing(value: summary.launchSuccess, color: JD.green, valueText: String(format: "%.0f%%", summary.launchSuccess * 100), label: "Launches")
                    ProgressRing(value: summary.foilUtilization, color: JD.cyan, valueText: String(format: "%.0f%%", summary.foilUtilization * 100), label: "On foil")
                }
                LazyVGrid(columns: gridColumns, spacing: 10) {
                    MetricTile("Longest ride", duration(summary.longestRideS), "timer", JD.cyan)
                    MetricTile("Takeoff", String(format: "%.1f s", summary.medianTakeoffS), "arrow.up.forward", JD.amber)
                    MetricTile("Recovery", recoveryRate(summary), "arrow.uturn.up.circle", JD.green)
                    MetricTile("Falls", "\(summary.rideFalls) ride · \(summary.launchCrashes) launch", "figure.fall", JD.coral)
                }
                if manifest.isSynthetic {
                    Label("Simulator truth—not a validated field classifier", systemImage: "info.circle")
                        .font(.caption).foregroundStyle(JD.amber)
                }
            }
        }
    }

    private func launchLab(_ summary: RideSummary) -> some View {
        JDCard(accent: JD.amber) {
            VStack(alignment: .leading, spacing: 17) {
                cardTitle("LAUNCH LAB", "Compare every power ramp", "bolt.fill", JD.amber)
                launchChart(summary)
                outcomeStrip(summary)
                LazyVGrid(columns: gridColumns, spacing: 10) {
                    MetricTile("Takeoff energy", String(format: "%.2f Wh", summary.medianLaunchEnergyWh), "bolt.circle", JD.amber)
                    MetricTile("Worst sag", String(format: "%.2f V", summary.worstVoltageSagV), "battery.25", JD.coral)
                }
            }
        }
    }

    private func outcomeStrip(_ summary: RideSummary) -> some View {
        HStack(spacing: 8) {
            outcomePill("\(summary.successfulAttempts)", "Success", JD.green)
            outcomePill("\(summary.failedAttempts)", "Aborted", JD.amber)
            outcomePill("\(summary.launchCrashes)", "Crash", JD.coral)
        }
    }

    private func outcomePill(_ value: String, _ label: String, _ color: Color) -> some View {
        VStack(spacing: 3) {
            Text(value).font(.title2.bold()).foregroundStyle(color)
            Text(label).font(.caption2).foregroundStyle(JD.muted)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 10)
        .background(color.opacity(0.09), in: RoundedRectangle(cornerRadius: 12))
    }

    private func rideDynamics(_ summary: RideSummary) -> some View {
        VStack(spacing: 18) {
            JDCard(accent: JD.cyan) {
                VStack(alignment: .leading, spacing: 17) {
                    cardTitle("RIDE DYNAMICS", "Flight time, stability, and recovery", "waveform.path.ecg", JD.cyan)
                    rideChart(summary)
                    LazyVGrid(columns: gridColumns, spacing: 10) {
                        MetricTile("Median ride", duration(summary.medianRideS), "timer", JD.cyan)
                        MetricTile("Foil vibration p95", String(format: "%.2f g", summary.foilVibrationP95G), "waveform", JD.amber)
                        MetricTile("Peak angular rate", String(format: "%.0f °/s", summary.peakFoilGyroDPS), "gyroscope", JD.cyan)
                        MetricTile("Fall transient", String(format: "%.2f g", summary.peakFallAccelDeltaG), "exclamationmark.triangle", JD.coral)
                    }
                }
            }
            if !summary.trackPoints.isEmpty {
                JDCard {
                    VStack(alignment: .leading, spacing: 14) {
                        cardTitle("COURSE TRACE", "Speed painted onto the ride", "location.north.line.fill", JD.green)
                        trackChart(summary)
                        HStack {
                            visualStat("Distance", distance(summary.distanceM), JD.ice)
                            visualStat("Avg foil", String(format: "%.1f mph", summary.meanFoilSpeedMPS * 2.23694), JD.cyan)
                            visualStat("Energy", summary.energyPerMile.map { String(format: "%.1f Wh/mi", $0) } ?? "—", JD.amber)
                        }
                    }
                }
            }
        }
    }

    private func systemHealth(_ summary: RideSummary) -> some View {
        JDCard {
            VStack(alignment: .leading, spacing: 16) {
                cardTitle("SYSTEM HEALTH", "Thermal and electrical snapshot", "heart.text.square", JD.green)
                HStack(spacing: 12) {
                    visualStat("Peak temp", String(format: "%.1f °C", summary.peakPackC), summary.peakPackC > 40 ? JD.coral : JD.green)
                    visualStat("Pack spread", String(format: "%.1f °C", summary.peakPackDeltaC), summary.peakPackDeltaC > 5 ? JD.coral : JD.green)
                    visualStat("Energy", String(format: "%.1f Wh", summary.energyWh), JD.amber)
                }
                Gauge(value: min(summary.peakPackC, 60), in: 0...60) { Text("Pack temperature") }
                    .tint(Gradient(colors: [JD.green, JD.amber, JD.coral]))
            }
        }
    }

    private func analysisCard(_ summary: RideSummary) -> some View {
        JDCard(accent: JD.cyan) {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("ANALYSIS HANDOFF", "Take the evidence into ChatGPT", "sparkles", JD.cyan)
                ShareLink(item: AnalysisHandoff.markdown(manifest: manifest, summary: summary, config: config)) {
                    HStack {
                        Image(systemName: "square.and.arrow.up.fill")
                        Text("Share ride analysis").fontWeight(.semibold)
                        Spacer()
                        Image(systemName: "arrow.up.right")
                    }
                    .foregroundStyle(JD.deepWater).padding(14)
                    .background(JD.cyan, in: RoundedRectangle(cornerRadius: 14))
                }
                Text("Read-only interpretation and conservative test suggestions; no control commands.")
                    .font(.caption).foregroundStyle(JD.muted)
            }
        }
    }

    private var configurationCard: some View {
        JDCard {
            DisclosureGroup {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Read-only snapshot. Apply deliberate changes with VESC Tool while safely ashore.")
                        .font(.caption).foregroundStyle(JD.muted)
                    if let config { Text(config).font(.system(.caption2, design: .monospaced)).foregroundStyle(JD.muted) }
                }
                .padding(.top, 10)
            } label: {
                HStack {
                    Image(systemName: "slider.horizontal.3").foregroundStyle(JD.amber)
                    Text("VESC snapshot").font(.headline)
                    Spacer()
                    Text(manifest.vescConfigID).font(.caption.bold()).foregroundStyle(JD.muted)
                }
            }
        }
    }

    private var gridColumns: [GridItem] {
        [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
    }

    private func cardTitle(_ title: String, _ subtitle: String, _ icon: String, _ color: Color) -> some View {
        HStack(spacing: 11) {
            Image(systemName: icon).font(.headline).foregroundStyle(color)
                .frame(width: 38, height: 38).background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 11))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.caption.bold()).tracking(1.35).foregroundStyle(color)
                Text(subtitle).font(.caption).foregroundStyle(JD.muted)
            }
        }
    }

    private func visualStat(_ label: String, _ value: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(value).font(.subheadline.bold()).foregroundStyle(color).lineLimit(1).minimumScaleFactor(0.7)
            Text(label).font(.caption2).foregroundStyle(JD.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func launchChart(_ summary: RideSummary) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Chart(summary.launchPoints) { point in
                LineMark(
                    x: .value("Seconds", point.seconds),
                    y: .value("Power", point.powerKW),
                    series: .value("Attempt", point.attemptID)
                )
                .foregroundStyle(by: .value("Outcome", point.outcome))
                .lineStyle(StrokeStyle(lineWidth: 1.5))
            }
            .chartForegroundStyleScale([
                "Success": Color.cyan,
                "Aborted": Color.orange,
                "Launch crash": Color.red,
            ])
            .chartXAxisLabel("Seconds from launch")
            .chartYAxisLabel("kW")
            .chartLegend(position: .bottom, alignment: .leading, spacing: 12)
            .frame(height: 210)
        }
    }

    private func rideChart(_ summary: RideSummary) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Chart {
                ForEach(summary.rideDurations) { ride in
                    BarMark(
                        x: .value("Ride", "#\(ride.rideID)"),
                        y: .value("Seconds", ride.durationS)
                    )
                    .foregroundStyle(Color.secondary.opacity(0.45))
                    BarMark(
                        x: .value("Ride", "#\(ride.rideID)"),
                        y: .value("Seconds", ride.foilS)
                    )
                    .foregroundStyle(Color.cyan)
                }
            }
            .chartYAxisLabel("Seconds")
            .frame(height: 190)
            HStack(spacing: 16) {
                Label("Ride", systemImage: "square.fill").foregroundStyle(.secondary)
                Label("On foil", systemImage: "square.fill").foregroundStyle(.cyan)
            }
            .font(.caption)
        }
    }

    private func trackChart(_ summary: RideSummary) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Chart(summary.trackPoints) { point in
                PointMark(
                    x: .value("East", point.eastM),
                    y: .value("North", point.northM)
                )
                .foregroundStyle(by: .value("Speed mph", point.speedMPH))
                .symbolSize(10)
            }
            .chartXAxisLabel("East (m)")
            .chartYAxisLabel("North (m)")
            .chartLegend(position: .bottom)
            .frame(height: 250)
        }
    }

    private func recoveryRate(_ summary: RideSummary) -> String {
        guard summary.touchdowns > 0 else { return "No touchdowns" }
        return String(format: "%.0f%% · %d of %d", Double(summary.recoveries) / Double(summary.touchdowns) * 100, summary.recoveries, summary.touchdowns)
    }

    private func duration(_ seconds: Double) -> String {
        let rounded = max(0, Int(seconds.rounded()))
        if rounded < 60 { return "\(rounded) s" }
        return "\(rounded / 60)m \(rounded % 60)s"
    }

    private func distance(_ meters: Double) -> String {
        String(format: "%.2f mi", meters / 1609.344)
    }

    private func load() async {
        do {
            let telemetry = try await model.store.telemetryURL(for: manifest)
            summary = try await Task.detached { try RideSummary.analyze(telemetry) }.value
            let configURL = await model.store.configURL(for: manifest)
            config = try? String(contentsOf: configURL, encoding: .utf8)
        } catch { self.error = error.localizedDescription }
    }
}

private enum JD {
    static let deepWater = Color(red: 5 / 255, green: 12 / 255, blue: 21 / 255)
    static let panel = Color(red: 11 / 255, green: 25 / 255, blue: 39 / 255)
    static let panelLift = Color(red: 17 / 255, green: 38 / 255, blue: 56 / 255)
    static let cyan = Color(red: 77 / 255, green: 228 / 255, blue: 255 / 255)
    static let amber = Color(red: 255 / 255, green: 181 / 255, blue: 71 / 255)
    static let green = Color(red: 94 / 255, green: 229 / 255, blue: 174 / 255)
    static let coral = Color(red: 255 / 255, green: 102 / 255, blue: 125 / 255)
    static let ice = Color(red: 243 / 255, green: 251 / 255, blue: 255 / 255)
    static let muted = Color(red: 143 / 255, green: 168 / 255, blue: 185 / 255)
}

private struct JDCard<Content: View>: View {
    var accent: Color? = nil
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(17)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                LinearGradient(colors: [JD.panelLift, JD.panel], startPoint: .topLeading, endPoint: .bottomTrailing),
                in: RoundedRectangle(cornerRadius: 21)
            )
            .overlay(alignment: .leading) {
                if let accent {
                    Capsule().fill(accent).frame(width: 3).padding(.vertical, 20)
                }
            }
            .overlay(RoundedRectangle(cornerRadius: 21).stroke(Color.white.opacity(0.055)))
    }
}

private struct ProgressRing: View {
    let value: Double
    let color: Color
    let valueText: String
    let label: String

    var body: some View {
        ZStack {
            Circle().stroke(Color.white.opacity(0.08), lineWidth: 11)
            Circle().trim(from: 0, to: min(max(value, 0), 1))
                .stroke(color, style: StrokeStyle(lineWidth: 11, lineCap: .round))
                .rotationEffect(.degrees(-90))
            VStack(spacing: 2) {
                Text(valueText).font(.title2.bold()).foregroundStyle(JD.ice)
                Text(label).font(.caption2).foregroundStyle(JD.muted)
            }
        }
        .frame(maxWidth: .infinity).aspectRatio(1, contentMode: .fit)
    }
}

private struct MetricTile: View {
    let title: String
    let value: String
    let icon: String
    let color: Color

    init(_ title: String, _ value: String, _ icon: String, _ color: Color) {
        self.title = title; self.value = value; self.icon = icon; self.color = color
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: icon).foregroundStyle(color)
            Text(value).font(.headline).foregroundStyle(JD.ice).lineLimit(1).minimumScaleFactor(0.68)
            Text(title).font(.caption2).foregroundStyle(JD.muted)
        }
        .frame(maxWidth: .infinity, minHeight: 82, alignment: .leading)
        .padding(12).background(JD.deepWater.opacity(0.52), in: RoundedRectangle(cornerRadius: 14))
    }
}

private struct BundledImage: View {
    let name: String
    let contentMode: ContentMode

    var body: some View {
        if let url = Bundle.main.url(forResource: name, withExtension: "png"),
           let image = UIImage(contentsOfFile: url.path) {
            Image(uiImage: image).resizable().aspectRatio(contentMode: contentMode)
        } else {
            Color.clear
        }
    }
}
