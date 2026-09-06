import SwiftUI
import EventKit
import LocalAuthentication

@main
struct EmptyChairApp: App {
    @StateObject private var model = EmptyChairModel()
    var body: some Scene { WindowGroup { RootView().environmentObject(model) } }
}

@MainActor
final class EmptyChairModel: ObservableObject {
    @Published var unlocked = false
    @Published var calendarAuthorized = false
    @Published var calendars: [EKCalendar] = []
    @Published var selectedCalendarID = UserDefaults.standard.string(forKey: "tattooCalendarID")
    @Published var status = "LOCKED"
    let store = EKEventStore()

    func unlock() async {
        let context = LAContext()
        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil) else { unlocked = true; await loadCalendarState(); return }
        do { unlocked = try await context.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, localizedReason: "Open Empty Chair") }
        catch { status = "LOCKED" }
        if unlocked { await loadCalendarState() }
    }

    func loadCalendarState() async {
        let auth = EKEventStore.authorizationStatus(for: .event)
        calendarAuthorized = auth == .fullAccess || auth == .authorized
        if calendarAuthorized { calendars = store.calendars(for: .event).filter { $0.allowsContentModifications }; status = selectedCalendarID == nil ? "CHOOSE CALENDAR" : "ARMED" }
    }

    func connectAppleCalendar() async {
        do {
            if #available(iOS 17.0, *) { calendarAuthorized = try await store.requestFullAccessToEvents() }
            else { calendarAuthorized = try await store.requestAccess(to: .event) }
            if calendarAuthorized { calendars = store.calendars(for: .event).filter { $0.allowsContentModifications }; status = "CHOOSE CALENDAR" }
        } catch { status = "CHECK CALENDAR" }
    }

    func choose(_ calendar: EKCalendar) {
        selectedCalendarID = calendar.calendarIdentifier
        UserDefaults.standard.set(calendar.calendarIdentifier, forKey: "tattooCalendarID")
        status = "ARMED"
    }
}

struct RootView: View {
    @EnvironmentObject var model: EmptyChairModel
    var body: some View {
        NavigationStack {
            ZStack {
                Color(red: 11/255, green: 9/255, blue: 5/255).ignoresSafeArea()
                VStack(alignment: .leading, spacing: 24) {
                    HStack { Text("EMPTY CHAIR"); Spacer(); Text("2.0") }.font(.system(.headline, design: .monospaced))
                    Divider()
                    if !model.unlocked {
                        Text("EMPTY CHAIR // LOCKED").font(.system(.largeTitle, design: .monospaced))
                        Button("UNLOCK WITH FACE ID") { Task { await model.unlock() } }.buttonStyle(TerminalButton())
                    } else if !model.calendarAuthorized {
                        Text("WHERE DO YOUR APPOINTMENTS LIVE?").font(.system(.title, design: .monospaced))
                        Button("[ A ] APPLE CALENDAR") { Task { await model.connectAppleCalendar() } }.buttonStyle(TerminalButton())
                    } else if model.selectedCalendarID == nil {
                        Text("WHICH ONE HOLDS TATTOOS?").font(.system(.title, design: .monospaced))
                        ForEach(model.calendars, id: \.calendarIdentifier) { cal in Button(cal.title.uppercased()) { model.choose(cal) }.buttonStyle(TerminalButton()) }
                    } else {
                        Spacer()
                        Text("ARMED. ✓").font(.system(size: 44, weight: .medium, design: .monospaced))
                        Text("calendar................[✓]\n\nYOU CAN CLOSE THIS NOW.").font(.system(.body, design: .monospaced))
                        Spacer()
                    }
                    Spacer()
                }.padding(24).foregroundStyle(Color(red: 1, green: 176/255, blue: 0))
            }
        }.task { await model.unlock() }
    }
}

struct TerminalButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(.headline, design: .monospaced)).frame(maxWidth: .infinity).padding().overlay(Rectangle().stroke(lineWidth: 1)).opacity(configuration.isPressed ? 0.6 : 1)
    }
}
