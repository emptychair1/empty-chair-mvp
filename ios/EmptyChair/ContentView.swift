import SwiftUI
import Charts

private let blood = Color(red: 0.78, green: 0.08, blue: 0.08)
private let brightRed = Color(red: 0.93, green: 0.12, blue: 0.12)
private let cream = Color(red: 0.95, green: 0.90, blue: 0.82)
private let gold = Color(red: 0.82, green: 0.67, blue: 0.44)
private let green = Color(red: 0.45, green: 0.80, blue: 0.26)

struct RootView: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        Group {
            if store.isAuthenticated {
                AppShellView()
            } else {
                LoginView()
            }
        }
        .background(Color.black.ignoresSafeArea())
        .alert("Empty Chair", isPresented: Binding(
            get: { store.errorMessage != nil },
            set: { if !$0 { store.errorMessage = nil } }
        )) {
            Button("OK", role: .cancel) { store.errorMessage = nil }
        } message: {
            Text(store.errorMessage ?? "")
        }
    }
}

struct LoginView: View {
    @EnvironmentObject private var store: AppStore
    @State private var email = ""
    @State private var password = ""

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color.black, blood.opacity(0.35), Color.black], startPoint: .topLeading, endPoint: .bottomTrailing)
                .ignoresSafeArea()
            VStack(spacing: 26) {
                Spacer()
                VStack(spacing: 4) {
                    Image(systemName: "chair.lounge.fill")
                        .font(.system(size: 52, weight: .black))
                        .foregroundStyle(brightRed)
                        .shadow(color: brightRed.opacity(0.5), radius: 20)
                    Text("EMPTY CHAIR")
                        .font(.system(size: 34, weight: .black, design: .serif))
                        .tracking(2)
                        .foregroundStyle(cream)
                    Text("FILL MORE CHAIRS")
                        .font(.caption.weight(.bold))
                        .tracking(4)
                        .foregroundStyle(gold)
                }

                VStack(spacing: 14) {
                    TextField("Email", text: $email)
                        .textContentType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.emailAddress)
                        .textFieldStyle(ECTextFieldStyle())
                    SecureField("Password", text: $password)
                        .textContentType(.password)
                        .textFieldStyle(ECTextFieldStyle())
                    Button {
                        Task { await store.login(email: email, password: password) }
                    } label: {
                        HStack {
                            if store.isLoading { ProgressView().tint(.white) }
                            Text(store.isLoading ? "ENTERING…" : "ENTER THE WAR ROOM")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(ECPrimaryButtonStyle())
                    .disabled(store.isLoading || email.isEmpty || password.isEmpty)
                }
                .frame(maxWidth: 430)
                .padding(22)
                .background(.black.opacity(0.72), in: RoundedRectangle(cornerRadius: 18))
                .overlay(RoundedRectangle(cornerRadius: 18).stroke(blood.opacity(0.7)))
                .shadow(color: blood.opacity(0.25), radius: 30)
                Spacer()
            }
            .padding()
        }
    }
}

struct AppShellView: View {
    @EnvironmentObject private var store: AppStore
    @State private var selection: AppSection? = .dashboard

    var body: some View {
        NavigationSplitView {
            List(AppSection.allCases, selection: $selection) { section in
                Label(section.title, systemImage: section.icon)
                    .tag(section)
            }
            .navigationTitle("Empty Chair")
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(store.user?.shopName ?? "Studio")
                        .font(.caption.weight(.bold))
                    Text("● STUDIO ONLINE")
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(green)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
                .background(.black.opacity(0.8))
            }
        } detail: {
            NavigationStack {
                switch selection ?? .dashboard {
                case .dashboard: DashboardView()
                case .recovery: RecoveryView()
                case .openings: OpeningsView()
                case .bookings: BookingsView()
                case .customers: CustomersView()
                case .settings: SettingsView()
                }
            }
        }
        .tint(brightRed)
    }
}

enum AppSection: String, CaseIterable, Identifiable {
    case dashboard, recovery, openings, bookings, customers, settings
    var id: String { rawValue }
    var title: String {
        switch self {
        case .dashboard: "Command Center"
        case .recovery: "Recovery"
        case .openings: "Openings"
        case .bookings: "Bookings"
        case .customers: "Customers"
        case .settings: "Settings"
        }
    }
    var icon: String {
        switch self {
        case .dashboard: "scope"
        case .recovery: "bolt.circle.fill"
        case .openings: "calendar.badge.exclamationmark"
        case .bookings: "checkmark.seal.fill"
        case .customers: "person.2.fill"
        case .settings: "gearshape.fill"
        }
    }
}

struct DashboardView: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                WarRoomHero(metrics: store.dashboard?.metrics)
                RevenueChart(openings: store.dashboard?.openings ?? [])
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 180))], spacing: 12) {
                    MetricCard(title: "Openings", value: "\(store.dashboard?.metrics.totalOpenings ?? 0)", icon: "chair.lounge.fill")
                    MetricCard(title: "Recovered", value: currency(store.dashboard?.metrics.recoveredRevenue ?? 0), icon: "dollarsign.circle.fill", tone: green)
                    MetricCard(title: "Bookings", value: "\(store.dashboard?.metrics.recoveredBookings ?? 0)", icon: "checkmark.seal.fill")
                    MetricCard(title: "Customers", value: "\(store.dashboard?.metrics.customers ?? 0)", icon: "person.2.fill")
                }
                SectionHeader(title: "Recent Openings", subtitle: "Tap a chair to open Match Intelligence")
                ForEach((store.dashboard?.openings ?? []).prefix(8)) { opening in
                    NavigationLink(value: opening) { OpeningRow(opening: opening) }
                        .buttonStyle(.plain)
                }
            }
            .padding()
        }
        .navigationTitle("Command Center")
        .navigationDestination(for: Opening.self) { OpeningDetailView(opening: $0) }
        .refreshable { await store.refreshAll() }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button { Task { await store.refreshAll() } } label: { Image(systemName: "arrow.clockwise") }
            }
        }
    }
}

struct WarRoomHero: View {
    let metrics: DashboardMetrics?
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 24) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Circle().fill(brightRed).frame(width: 8, height: 8)
                        .scaleEffect(pulse ? 1.6 : 0.8)
                        .shadow(color: brightRed, radius: pulse ? 10 : 2)
                    Text("EMPTY CHAIR RECOVERY NETWORK")
                        .font(.caption2.weight(.black)).tracking(2).foregroundStyle(brightRed)
                }
                Text("The War Room")
                    .font(.system(size: 42, weight: .black, design: .serif))
                    .foregroundStyle(cream)
                Text("Every open chair is revenue in motion.")
                    .foregroundStyle(.secondary)
                HStack(spacing: 18) {
                    WarStat(label: "MONEY AT RISK", value: currency(metrics?.moneyAtRisk ?? 0), color: brightRed)
                    WarStat(label: "RECOVERY ACTIVE", value: "\(metrics?.activeRecoveries ?? 0)", color: cream)
                    WarStat(label: "RECOVERED", value: currency(metrics?.recoveredRevenue ?? 0), color: green)
                }
            }
            Spacer(minLength: 0)
            ZStack {
                ForEach([170.0, 120.0, 70.0], id: \.self) { size in
                    Circle().stroke(brightRed.opacity(0.22), lineWidth: 1).frame(width: size, height: size)
                }
                Circle().fill(brightRed).frame(width: 9, height: 9).shadow(color: brightRed, radius: 14)
                RadarSweep().stroke(LinearGradient(colors: [brightRed, .clear], startPoint: .center, endPoint: .trailing), lineWidth: 2)
                    .frame(width: 170, height: 170)
                    .rotationEffect(.degrees(pulse ? 360 : 0))
            }
            .frame(width: 190, height: 190)
            .accessibilityHidden(true)
        }
        .padding(26)
        .background(LinearGradient(colors: [blood.opacity(0.35), .black, .black], startPoint: .topLeading, endPoint: .bottomTrailing), in: RoundedRectangle(cornerRadius: 20))
        .overlay(RoundedRectangle(cornerRadius: 20).stroke(brightRed.opacity(0.5)))
        .shadow(color: blood.opacity(0.22), radius: 30)
        .onAppear {
            withAnimation(.linear(duration: 4).repeatForever(autoreverses: false)) { pulse = true }
        }
    }
}

struct RadarSweep: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let center = CGPoint(x: rect.midX, y: rect.midY)
        path.move(to: center)
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
        return path
    }
}

struct WarStat: View {
    let label: String
    let value: String
    let color: Color
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption2.weight(.bold)).foregroundStyle(gold)
            Text(value).font(.title3.bold()).foregroundStyle(color)
        }
    }
}

struct RevenueChart: View {
    let openings: [Opening]

    private var points: [RevenuePoint] {
        var recovered = 0.0
        return openings.sorted { $0.date < $1.date }.map { opening in
            if ["BOOKED", "COMPLETED", "CLAIMED", "CONFIRMED"].contains(opening.status) { recovered += opening.price }
            let risk = ["OPEN", "RECOVERY_ACTIVE"].contains(opening.status) ? opening.price : 0
            return RevenuePoint(date: opening.date, recovered: recovered, risk: risk)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "Revenue Recovery Pulse", subtitle: "Recovered revenue versus exposed chair value")
            Chart(points) { point in
                AreaMark(x: .value("Date", point.date), y: .value("Recovered", point.recovered))
                    .foregroundStyle(LinearGradient(colors: [green.opacity(0.25), .clear], startPoint: .top, endPoint: .bottom))
                LineMark(x: .value("Date", point.date), y: .value("Recovered", point.recovered))
                    .foregroundStyle(green).lineStyle(StrokeStyle(lineWidth: 3))
                LineMark(x: .value("Date", point.date), y: .value("At Risk", point.risk))
                    .foregroundStyle(brightRed).lineStyle(StrokeStyle(lineWidth: 2, dash: [8, 6]))
            }
            .chartYAxis { AxisMarks(position: .leading) { value in AxisGridLine().foregroundStyle(gold.opacity(0.15)); AxisValueLabel() } }
            .chartXAxis(.hidden)
            .frame(height: 260)
        }
        .padding(20)
        .background(Color.white.opacity(0.035), in: RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(gold.opacity(0.22)))
    }
}

struct RevenuePoint: Identifiable {
    let id = UUID()
    let date: String
    let recovered: Double
    let risk: Double
}

struct OpeningsView: View {
    @EnvironmentObject private var store: AppStore
    var body: some View {
        List(store.dashboard?.openings ?? []) { opening in
            NavigationLink(value: opening) { OpeningRow(opening: opening) }
        }
        .navigationTitle("Openings")
        .navigationDestination(for: Opening.self) { OpeningDetailView(opening: $0) }
        .refreshable { await store.refreshAll() }
    }
}

struct OpeningRow: View {
    let opening: Opening
    var body: some View {
        HStack(spacing: 14) {
            VStack {
                Text(String(opening.date.suffix(2))).font(.title2.bold())
                Text(String(opening.date.dropLast(3).suffix(2))).font(.caption2).foregroundStyle(gold)
            }
            .frame(width: 50, height: 58)
            .background(blood.opacity(0.22), in: RoundedRectangle(cornerRadius: 10))
            VStack(alignment: .leading, spacing: 4) {
                Text("\(opening.startTime) · \(opening.artistName ?? "Artist")").font(.headline)
                Text("\(opening.style ?? opening.service) · \(currency(opening.price))").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            StatusPill(status: opening.status)
        }
        .padding(.vertical, 5)
    }
}

struct OpeningDetailView: View {
    @EnvironmentObject private var store: AppStore
    let opening: Opening
    @State private var detail: OpeningEnvelope?
    @State private var loading = true
    @State private var showLaunch = false

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("OPENING INTELLIGENCE").font(.caption2.bold()).tracking(2).foregroundStyle(gold)
                    Text("\(opening.artistName ?? "Artist") · \(opening.date)")
                        .font(.system(size: 34, weight: .black, design: .serif)).foregroundStyle(cream)
                    Text("\(opening.startTime) · \(opening.style ?? opening.service)").foregroundStyle(.secondary)
                    HStack {
                        StatusPill(status: opening.status)
                        Spacer()
                        Text(currency(opening.price)).font(.title.bold()).foregroundStyle(brightRed)
                    }
                    if opening.status == "OPEN" {
                        Button("⚡ LAUNCH AUTOPILOT") { showLaunch = true }
                            .buttonStyle(ECPrimaryButtonStyle())
                    } else if opening.status == "RECOVERY_ACTIVE" {
                        Button("ADVANCE QUEUE") {
                            Task { try? await store.advanceRecovery(opening) }
                        }.buttonStyle(ECPrimaryButtonStyle())
                    }
                }
                .padding(22)
                .background(blood.opacity(0.14), in: RoundedRectangle(cornerRadius: 18))
                .overlay(RoundedRectangle(cornerRadius: 18).stroke(brightRed.opacity(0.4)))

                SectionHeader(title: "Who Should Get This Chair?", subtitle: "Ranked from the existing Empty Chair recovery score")
                if loading { ProgressView().padding() }
                ForEach(detail?.offers ?? []) { offer in MatchCard(offer: offer) }
                if !loading && (detail?.offers.isEmpty ?? true) {
                    ContentUnavailableView("No Match Queue Yet", systemImage: "scope", description: Text("Launch Autopilot to score eligible customers."))
                }
            }
            .padding()
        }
        .navigationTitle("Match Intelligence")
        .task {
            do { detail = try await APIClient.shared.opening(id: opening.id) } catch { store.errorMessage = error.localizedDescription }
            loading = false
        }
        .fullScreenCover(isPresented: $showLaunch) {
            RecoveryLaunchView(opening: opening, existingOffers: detail?.offers ?? [], isPresented: $showLaunch)
        }
    }
}

struct MatchCard: View {
    let offer: Offer
    @State private var expanded = false
    private var score: Double { min(100, max(0, offer.score)) }

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Text(String(format: "%02d", offer.rank)).font(.title2.bold()).foregroundStyle(.secondary)
                VStack(alignment: .leading) {
                    Text(offer.customerName ?? "Customer").font(.headline)
                    Text(offer.customerPhone ?? "").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Text(String(format: "%.0f", offer.score)).font(.title.bold()).foregroundStyle(score >= 80 ? green : score >= 60 ? gold : brightRed)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.white.opacity(0.06))
                    Capsule().fill(LinearGradient(colors: [blood, brightRed, gold, green], startPoint: .leading, endPoint: .trailing))
                        .frame(width: geo.size.width * score / 100)
                }
            }.frame(height: 8)
            Button(expanded ? "Hide Match DNA ↑" : "View Match DNA ↓") { withAnimation { expanded.toggle() } }
                .font(.caption.bold()).foregroundStyle(gold).frame(maxWidth: .infinity, alignment: .leading)
            if expanded {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150))], spacing: 8) {
                    DNAChip(title: "Artist", text: "Artist affinity contributes when present.")
                    DNAChip(title: "Style", text: "Preference fit strengthens ranking.")
                    DNAChip(title: "History", text: "Past activity informs reliability.")
                    DNAChip(title: "Recency", text: "Recent offers reduce over-contacting.")
                }
            }
        }
        .padding(18)
        .background(Color.white.opacity(0.035), in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.white.opacity(0.08)))
    }
}

struct DNAChip: View {
    let title: String
    let text: String
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased()).font(.caption2.bold()).foregroundStyle(gold)
            Text(text).font(.caption).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(10).background(.black.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
    }
}

struct RecoveryLaunchView: View {
    @EnvironmentObject private var store: AppStore
    let opening: Opening
    let existingOffers: [Offer]
    @Binding var isPresented: Bool
    @State private var phase = 0
    @State private var progress = 0.0
    @State private var spinning = false
    @State private var failed = false

    private let phases = ["SCANNING CUSTOMER POOL", "FILTERING ELIGIBILITY", "RANKING MATCHES", "LOCKING TARGETS", "LAUNCHING FIRST OFFER"]

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            RadialGradient(colors: [blood.opacity(0.33), .black], center: .center, startRadius: 20, endRadius: 500).ignoresSafeArea()
            VStack(spacing: 24) {
                Text("EMPTY CHAIR").font(.caption.bold()).tracking(6).foregroundStyle(gold)
                Text(phases[min(phase, phases.count - 1)])
                    .font(.system(size: 28, weight: .black, design: .serif)).foregroundStyle(cream).multilineTextAlignment(.center)
                ZStack {
                    ForEach([240.0, 180.0, 120.0], id: \.self) { size in Circle().stroke(brightRed.opacity(0.22)).frame(width: size, height: size) }
                    Image(systemName: phase >= 3 ? "scope" : "bolt.fill").font(.system(size: 54, weight: .black)).foregroundStyle(brightRed).shadow(color: brightRed, radius: 20)
                    RadarSweep().stroke(LinearGradient(colors: [brightRed, .clear], startPoint: .center, endPoint: .trailing), lineWidth: 3)
                        .frame(width: 240, height: 240).rotationEffect(.degrees(spinning ? 360 : 0))
                }
                .frame(height: 260)
                VStack(spacing: 10) {
                    HStack { Text("TARGETS").foregroundStyle(.secondary); Spacer(); Text("\(max(5, existingOffers.count))").foregroundStyle(gold).bold() }
                    ForEach(existingOffers.prefix(5)) { offer in
                        HStack {
                            Text(String(format: "%02d", offer.rank)).foregroundStyle(.secondary)
                            Text(offer.customerName ?? "Candidate").bold()
                            Spacer()
                            Text(String(format: "%.0f%%", min(100, offer.score))).foregroundStyle(green).bold()
                        }
                        .opacity(phase >= 3 ? 1 : 0.18)
                    }
                }
                .frame(maxWidth: 520)
                ProgressView(value: progress).tint(brightRed).frame(maxWidth: 520)
                if failed {
                    Text("Launch failed. The recovery engine did not accept the request.").foregroundStyle(brightRed)
                    Button("CLOSE") { isPresented = false }.buttonStyle(ECPrimaryButtonStyle())
                }
            }
            .padding(30)
        }
        .interactiveDismissDisabled()
        .onAppear {
            withAnimation(.linear(duration: 3).repeatForever(autoreverses: false)) { spinning = true }
            runSequence()
        }
    }

    private func runSequence() {
        Task {
            for index in phases.indices {
                await MainActor.run {
                    phase = index
                    withAnimation(.easeInOut(duration: 0.45)) { progress = Double(index + 1) / Double(phases.count) }
                    UIImpactFeedbackGenerator(style: index >= 3 ? .heavy : .light).impactOccurred()
                }
                try? await Task.sleep(for: .milliseconds(650))
            }
            do {
                try await store.launchRecovery(opening)
                await MainActor.run { UINotificationFeedbackGenerator().notificationOccurred(.success) }
                try? await Task.sleep(for: .milliseconds(400))
                await MainActor.run { isPresented = false }
            } catch {
                await MainActor.run { failed = true; store.errorMessage = error.localizedDescription }
            }
        }
    }
}

struct RecoveryView: View {
    @EnvironmentObject private var store: AppStore
    var body: some View {
        ScrollView {
            LazyVStack(spacing: 14) {
                SectionHeader(title: "Recovery Command Center", subtitle: "Live campaigns and customer queues")
                ForEach(store.campaigns) { campaign in
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            VStack(alignment: .leading) {
                                Text("\(campaign.opening.artistName ?? "Artist") · \(campaign.opening.date)").font(.headline)
                                Text("\(campaign.opening.startTime) · \(currency(campaign.opening.price))").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer(); StatusPill(status: campaign.opening.status)
                        }
                        ForEach(campaign.offers.prefix(5)) { offer in
                            HStack { Text("#\(offer.rank)").foregroundStyle(.secondary); Text(offer.customerName ?? "Customer"); Spacer(); Text(String(format: "%.0f", offer.score)).foregroundStyle(gold); Text(offer.status).font(.caption2).foregroundStyle(.secondary) }
                        }
                        if campaign.opening.status == "RECOVERY_ACTIVE" {
                            Button("ADVANCE QUEUE") { Task { try? await store.advanceRecovery(campaign.opening) } }.buttonStyle(ECSecondaryButtonStyle())
                        }
                    }
                    .padding(18)
                    .background(Color.white.opacity(0.035), in: RoundedRectangle(cornerRadius: 16))
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(campaign.opening.status == "RECOVERY_ACTIVE" ? brightRed.opacity(0.45) : Color.white.opacity(0.08)))
                }
            }.padding()
        }
        .navigationTitle("Recovery")
        .refreshable { await store.refreshAll() }
    }
}

struct BookingsView: View {
    @EnvironmentObject private var store: AppStore
    var body: some View {
        List(store.bookings) { booking in
            HStack {
                VStack(alignment: .leading) {
                    Text(booking.customerName ?? "Customer").font(.headline)
                    Text("\(booking.artistName ?? "Artist") · \(booking.date ?? "") \(booking.startTime ?? "")").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                VStack(alignment: .trailing) { Text(currency(booking.amount)).bold(); StatusPill(status: booking.status) }
            }
        }
        .navigationTitle("Bookings")
        .refreshable { await store.refreshAll() }
    }
}

struct CustomersView: View {
    @EnvironmentObject private var store: AppStore
    @State private var search = ""
    private var filtered: [Customer] {
        search.isEmpty ? store.customers : store.customers.filter { $0.name.localizedCaseInsensitiveContains(search) || $0.phone.contains(search) }
    }
    var body: some View {
        List(filtered) { customer in
            VStack(alignment: .leading, spacing: 4) {
                HStack { Text(customer.name).font(.headline); Spacer(); Text(currency(customer.averageSpend)).foregroundStyle(gold).bold() }
                Text("\(customer.completedCount) completed · \(customer.preferredStyles.isEmpty ? "No style preference" : customer.preferredStyles)").font(.caption).foregroundStyle(.secondary)
            }
        }
        .searchable(text: $search)
        .navigationTitle("Customers")
        .refreshable { await store.refreshAll() }
    }
}

struct SettingsView: View {
    @EnvironmentObject private var store: AppStore
    var body: some View {
        Form {
            Section("Studio") {
                LabeledContent("Shop", value: store.user?.shopName ?? "")
                LabeledContent("Owner", value: store.user?.name ?? "")
                LabeledContent("Email", value: store.user?.email ?? "")
                LabeledContent("Timezone", value: store.user?.shopTimezone ?? "")
            }
            Section("Native Features") {
                Label("iPhone + iPad adaptive layout", systemImage: "iphone.and.arrow.forward")
                Label("Push notification permission", systemImage: "bell.badge.fill")
                Label("Haptic recovery feedback", systemImage: "waveform")
                Label("Native Swift Charts", systemImage: "chart.xyaxis.line")
            }
            Section {
                Button("Log Out", role: .destructive) { Task { await store.logout() } }
            }
        }
        .navigationTitle("Settings")
    }
}

struct MetricCard: View {
    let title: String
    let value: String
    let icon: String
    var tone: Color = cream
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: icon).foregroundStyle(gold)
            Text(title.uppercased()).font(.caption2.bold()).tracking(1).foregroundStyle(.secondary)
            Text(value).font(.title.bold()).foregroundStyle(tone)
        }
        .frame(maxWidth: .infinity, alignment: .leading).padding(18)
        .background(Color.white.opacity(0.035), in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.white.opacity(0.08)))
    }
}

struct StatusPill: View {
    let status: String
    var color: Color {
        if ["BOOKED", "COMPLETED", "CLAIMED", "CONFIRMED"].contains(status) { return green }
        if ["RECOVERY_ACTIVE", "SENT"].contains(status) { return brightRed }
        return gold
    }
    var body: some View {
        Text(status.replacingOccurrences(of: "_", with: " "))
            .font(.caption2.weight(.black)).padding(.horizontal, 9).padding(.vertical, 5)
            .foregroundStyle(color).background(color.opacity(0.12), in: Capsule()).overlay(Capsule().stroke(color.opacity(0.35)))
    }
}

struct SectionHeader: View {
    let title: String
    let subtitle: String
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.title2.bold()).foregroundStyle(cream)
            Text(subtitle).font(.caption).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct ECTextFieldStyle: TextFieldStyle {
    func _body(configuration: TextField<Self._Label>) -> some View {
        configuration.padding(14).background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 10)).overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.1)))
    }
}

struct ECPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.caption.weight(.black)).tracking(1).foregroundStyle(.white).padding(.vertical, 14).padding(.horizontal, 18).background(LinearGradient(colors: [blood, brightRed], startPoint: .leading, endPoint: .trailing), in: RoundedRectangle(cornerRadius: 10)).scaleEffect(configuration.isPressed ? 0.97 : 1).shadow(color: brightRed.opacity(0.24), radius: 12)
    }
}

struct ECSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.caption.weight(.black)).foregroundStyle(gold).padding(.vertical, 11).padding(.horizontal, 16).background(Color.white.opacity(0.04), in: RoundedRectangle(cornerRadius: 9)).overlay(RoundedRectangle(cornerRadius: 9).stroke(gold.opacity(0.35))).scaleEffect(configuration.isPressed ? 0.97 : 1)
    }
}

private func currency(_ value: Double) -> String {
    value.formatted(.currency(code: "USD").precision(.fractionLength(0)))
}
