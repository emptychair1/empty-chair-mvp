import SwiftUI
import Foundation
import UserNotifications

// MARK: - Models

struct APIUser: Codable, Identifiable {
    let id: String
    let name: String
    let email: String
    let shopId: String
    let shopName: String
    let shopTimezone: String

    enum CodingKeys: String, CodingKey {
        case id, name, email
        case shopId = "shop_id"
        case shopName = "shop_name"
        case shopTimezone = "shop_timezone"
    }
}

struct UserEnvelope: Codable { let user: APIUser }

struct DashboardMetrics: Codable {
    let totalOpenings: Int
    let recoveredRevenue: Double
    let recoveredBookings: Int
    let customers: Int
    let moneyAtRisk: Double
    let activeRecoveries: Int

    enum CodingKeys: String, CodingKey {
        case totalOpenings = "total_openings"
        case recoveredRevenue = "recovered_revenue"
        case recoveredBookings = "recovered_bookings"
        case customers
        case moneyAtRisk = "money_at_risk"
        case activeRecoveries = "active_recoveries"
    }
}

struct Opening: Codable, Identifiable, Hashable {
    let id: String
    let shopId: String
    let artistId: String
    let artistName: String?
    let date: String
    let startTime: String
    let endTime: String?
    let service: String
    let style: String?
    let price: Double
    let status: String
    let createdAt: String
    let expiresAt: String
    let bookingId: String?

    enum CodingKeys: String, CodingKey {
        case id, date, service, style, price, status
        case shopId = "shop_id"
        case artistId = "artist_id"
        case artistName = "artist_name"
        case startTime = "start_time"
        case endTime = "end_time"
        case createdAt = "created_at"
        case expiresAt = "expires_at"
        case bookingId = "booking_id"
    }
}

struct Offer: Codable, Identifiable, Hashable {
    let id: String
    let openingId: String
    let customerId: String
    let customerName: String?
    let customerPhone: String?
    let score: Double
    let rank: Int
    let status: String
    let expiresAt: String

    enum CodingKeys: String, CodingKey {
        case id, score, rank, status
        case openingId = "opening_id"
        case customerId = "customer_id"
        case customerName = "customer_name"
        case customerPhone = "customer_phone"
        case expiresAt = "expires_at"
    }
}

struct DashboardEnvelope: Codable {
    let metrics: DashboardMetrics
    let openings: [Opening]
}

struct OpeningEnvelope: Codable {
    let opening: Opening
    let offers: [Offer]
}

struct Campaign: Codable, Identifiable {
    let opening: Opening
    let offers: [Offer]
    var id: String { opening.id }
}

struct CampaignEnvelope: Codable { let campaigns: [Campaign] }

struct Customer: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let phone: String
    let email: String?
    let communicationConsent: Int
    let preferredArtists: String
    let preferredStyles: String
    let preferredServices: String
    let appointmentCount: Int
    let completedCount: Int
    let cancellationCount: Int
    let noShowCount: Int
    let averageSpend: Double

    enum CodingKeys: String, CodingKey {
        case id, name, phone, email
        case communicationConsent = "communication_consent"
        case preferredArtists = "preferred_artists"
        case preferredStyles = "preferred_styles"
        case preferredServices = "preferred_services"
        case appointmentCount = "appointment_count"
        case completedCount = "completed_count"
        case cancellationCount = "cancellation_count"
        case noShowCount = "no_show_count"
        case averageSpend = "average_spend"
    }
}

struct CustomerEnvelope: Codable { let customers: [Customer] }

struct Booking: Codable, Identifiable, Hashable {
    let id: String
    let openingId: String
    let customerId: String
    let customerName: String?
    let artistName: String?
    let date: String?
    let startTime: String?
    let service: String?
    let style: String?
    let status: String
    let amount: Double

    enum CodingKeys: String, CodingKey {
        case id, status, amount, date, service, style
        case openingId = "opening_id"
        case customerId = "customer_id"
        case customerName = "customer_name"
        case artistName = "artist_name"
        case startTime = "start_time"
    }
}

struct BookingEnvelope: Codable { let bookings: [Booking] }

// MARK: - API

final class APIClient {
    static let shared = APIClient()

    // Change this once if your Render hostname differs.
    var baseURL = URL(string: "https://empty-chair-mvp.onrender.com")!

    private let session: URLSession
    private let decoder: JSONDecoder

    private init() {
        let configuration = URLSessionConfiguration.default
        configuration.httpCookieAcceptPolicy = .always
        configuration.httpShouldSetCookies = true
        configuration.httpCookieStorage = .shared
        configuration.timeoutIntervalForRequest = 30
        session = URLSession(configuration: configuration)
        decoder = JSONDecoder()
    }

    private func request(_ path: String, method: String = "GET", json: [String: Any]? = nil, form: [String: String]? = nil) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        if let json {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: json)
        } else if let form {
            request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
            let body = form.map { key, value in
                "\(key.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? key)=\(value.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? value)"
            }.joined(separator: "&")
            request.httpBody = body.data(using: .utf8)
        }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        if !(200...399).contains(http.statusCode) {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIError.server(detail ?? "Request failed (\(http.statusCode))")
        }
        return data
    }

    func login(email: String, password: String) async throws -> APIUser {
        let data = try await request("api/auth/login", method: "POST", json: ["email": email, "password": password])
        return try decoder.decode(UserEnvelope.self, from: data).user
    }

    func me() async throws -> APIUser {
        let data = try await request("api/me")
        return try decoder.decode(UserEnvelope.self, from: data).user
    }

    func logout() async throws {
        _ = try await request("api/auth/logout", method: "POST")
    }

    func dashboard() async throws -> DashboardEnvelope {
        let data = try await request("api/dashboard")
        return try decoder.decode(DashboardEnvelope.self, from: data)
    }

    func opening(id: String) async throws -> OpeningEnvelope {
        let data = try await request("api/openings/\(id)")
        return try decoder.decode(OpeningEnvelope.self, from: data)
    }

    func recovery() async throws -> [Campaign] {
        let data = try await request("api/recovery")
        return try decoder.decode(CampaignEnvelope.self, from: data).campaigns
    }

    func customers() async throws -> [Customer] {
        let data = try await request("api/customers")
        return try decoder.decode(CustomerEnvelope.self, from: data).customers
    }

    func bookings() async throws -> [Booking] {
        let data = try await request("api/bookings")
        return try decoder.decode(BookingEnvelope.self, from: data).bookings
    }

    // These reuse the existing production web actions to preserve one recovery engine.
    func launchRecovery(openingID: String) async throws {
        _ = try await request("openings/\(openingID)/recover", method: "POST", form: [:])
    }

    func advanceRecovery(openingID: String) async throws {
        _ = try await request("openings/\(openingID)/advance", method: "POST", form: [:])
    }
}

enum APIError: LocalizedError {
    case invalidResponse
    case server(String)
    var errorDescription: String? {
        switch self {
        case .invalidResponse: return "Invalid server response."
        case .server(let message): return message
        }
    }
}

// MARK: - App Store

@MainActor
final class AppStore: ObservableObject {
    @Published var user: APIUser?
    @Published var dashboard: DashboardEnvelope?
    @Published var campaigns: [Campaign] = []
    @Published var customers: [Customer] = []
    @Published var bookings: [Booking] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    var isAuthenticated: Bool { user != nil }

    func restoreSession() async {
        do {
            user = try await APIClient.shared.me()
            await refreshAll()
        } catch {
            user = nil
        }
    }

    func login(email: String, password: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            user = try await APIClient.shared.login(email: email, password: password)
            await refreshAll()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func logout() async {
        try? await APIClient.shared.logout()
        user = nil
        dashboard = nil
        campaigns = []
        customers = []
        bookings = []
    }

    func refreshAll() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let d = APIClient.shared.dashboard()
            async let r = APIClient.shared.recovery()
            async let c = APIClient.shared.customers()
            async let b = APIClient.shared.bookings()
            dashboard = try await d
            campaigns = try await r
            customers = try await c
            bookings = try await b
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func launchRecovery(_ opening: Opening) async throws {
        try await APIClient.shared.launchRecovery(openingID: opening.id)
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        await refreshAll()
    }

    func advanceRecovery(_ opening: Opening) async throws {
        try await APIClient.shared.advanceRecovery(openingID: opening.id)
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        await refreshAll()
    }
}

// MARK: - Notifications

final class NotificationDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        Task {
            let granted = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound])
            if granted == true {
                await MainActor.run { UIApplication.shared.registerForRemoteNotifications() }
            }
        }
        return true
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound, .badge]
    }
}

// MARK: - App

@main
struct EmptyChairApp: App {
    @UIApplicationDelegateAdaptor(NotificationDelegate.self) private var appDelegate
    @StateObject private var store = AppStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(store)
                .preferredColorScheme(.dark)
                .task { await store.restoreSession() }
        }
    }
}
