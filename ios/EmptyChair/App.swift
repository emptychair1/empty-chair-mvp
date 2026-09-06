import SwiftUI
import EventKit
import LocalAuthentication

@main
struct EmptyChairApp: App {
    @StateObject private var model = EmptyChairModel()
    var body: some Scene { WindowGroup { RootView().environmentObject(model) } }
}

struct NativeEvent: Codable { let id:String; let title:String; let start_at:String; let end_at:String }
struct NativeCommand: Codable { let id:String; let kind:String; let payload:CommandPayload }
struct CommandPayload: Codable { let title:String; let start_at:String; let end_at:String; let notes:String? }
struct SyncReply: Codable { let ok:Bool; let commands:[NativeCommand] }

@MainActor
final class EmptyChairModel: ObservableObject {
    @Published var unlocked=false
    @Published var calendarAuthorized=false
    @Published var calendars:[EKCalendar]=[]
    @Published var selectedCalendarID=UserDefaults.standard.string(forKey:"tattooCalendarID")
    @Published var status="LOCKED"
    let store=EKEventStore()
    let api=URL(string:"https://app.tryemptychair.com")!
    private let iso=ISO8601DateFormatter()

    init(){ NotificationCenter.default.addObserver(forName:.EKEventStoreChanged,object:nil,queue:.main){ [weak self] _ in Task { @MainActor in await self?.sync() } } }

    func unlock() async {
        let context=LAContext()
        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics,error:nil) else { unlocked=true; await loadCalendarState(); return }
        do { unlocked=try await context.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics,localizedReason:"Open Empty Chair") } catch { status="LOCKED" }
        if unlocked { await loadCalendarState() }
    }

    func loadCalendarState() async {
        let auth=EKEventStore.authorizationStatus(for:.event)
        calendarAuthorized=auth == .fullAccess || auth == .authorized
        if calendarAuthorized { calendars=store.calendars(for:.event).filter{$0.allowsContentModifications}; status=selectedCalendarID == nil ? "CHOOSE CALENDAR":"ARMED"; await sync() }
    }

    func connectAppleCalendar() async {
        do {
            if #available(iOS 17.0,*) { calendarAuthorized=try await store.requestFullAccessToEvents() } else { calendarAuthorized=try await store.requestAccess(to:.event) }
            if calendarAuthorized { calendars=store.calendars(for:.event).filter{$0.allowsContentModifications}; status="CHOOSE CALENDAR" }
        } catch { status="CHECK CALENDAR" }
    }

    func choose(_ calendar:EKCalendar) {
        selectedCalendarID=calendar.calendarIdentifier; UserDefaults.standard.set(calendar.calendarIdentifier,forKey:"tattooCalendarID"); status="ARMED"
        Task { await registerIfNeeded(); await sync() }
    }

    private func registerIfNeeded() async {
        guard UserDefaults.standard.string(forKey:"deviceToken") == nil, let calendarID=selectedCalendarID else { return }
        // Registration uses the existing authenticated Empty Chair web session. Until the
        // native sign-in handoff is installed, this request will simply remain unregistered.
        var r=URLRequest(url:api.appending(path:"native/device/register")); r.httpMethod="POST"; r.setValue("application/json",forHTTPHeaderField:"Content-Type")
        r.httpBody=try? JSONSerialization.data(withJSONObject:["calendar_id":calendarID])
        guard let (data,response)=try? await URLSession.shared.data(for:r),(response as? HTTPURLResponse)?.statusCode == 200,
              let obj=try? JSONSerialization.jsonObject(with:data) as? [String:Any],let token=obj["device_token"] as? String else { return }
        UserDefaults.standard.set(token,forKey:"deviceToken")
    }

    func sync() async {
        guard calendarAuthorized,let calendarID=selectedCalendarID,let calendar=store.calendar(withIdentifier:calendarID),let token=UserDefaults.standard.string(forKey:"deviceToken") else { return }
        let start=Date().addingTimeInterval(-86400); let end=Date().addingTimeInterval(86400*180)
        let predicate=store.predicateForEvents(withStart:start,end:end,calendars:[calendar])
        let events=store.events(matching:predicate).map{NativeEvent(id:$0.eventIdentifier ?? $0.calendarItemIdentifier,title:$0.title ?? "Tattoo",start_at:iso.string(from:$0.startDate),end_at:iso.string(from:$0.endDate))}
        var r=URLRequest(url:api.appending(path:"native/calendar/sync")); r.httpMethod="POST"; r.setValue("Bearer \(token)",forHTTPHeaderField:"Authorization"); r.setValue("application/json",forHTTPHeaderField:"Content-Type")
        r.httpBody=try? JSONEncoder().encode(["calendar_id":calendarID,"events":events] as SyncPayload)
        guard let (data,response)=try? await URLSession.shared.data(for:r),(response as? HTTPURLResponse)?.statusCode == 200,let reply=try? JSONDecoder().decode(SyncReply.self,from:data) else { return }
        for command in reply.commands where command.kind == "upsert_event" { await apply(command,calendar:calendar,token:token) }
    }

    private func apply(_ command:NativeCommand,calendar:EKCalendar,token:String) async {
        guard let start=iso.date(from:command.payload.start_at),let end=iso.date(from:command.payload.end_at) else { return }
        let event=EKEvent(eventStore:store); event.calendar=calendar; event.title=command.payload.title; event.startDate=start; event.endDate=end; event.notes=command.payload.notes
        do { try store.save(event,span:.thisEvent,commit:true) } catch { status="CHECK CALENDAR"; return }
        var r=URLRequest(url:api.appending(path:"native/calendar/ack/\(command.id)")); r.httpMethod="POST"; r.setValue("Bearer \(token)",forHTTPHeaderField:"Authorization"); _=try? await URLSession.shared.data(for:r)
    }
}

struct SyncPayload:Encodable { let calendar_id:String; let events:[NativeEvent] }

struct RootView:View {
    @EnvironmentObject var model:EmptyChairModel
    var body:some View { NavigationStack { ZStack { Color(red:11/255,green:9/255,blue:5/255).ignoresSafeArea(); VStack(alignment:.leading,spacing:24){ HStack{Text("EMPTY CHAIR");Spacer();Text("2.0")}.font(.system(.headline,design:.monospaced));Divider()
        if !model.unlocked { Text("EMPTY CHAIR // LOCKED").font(.system(.largeTitle,design:.monospaced));Button("UNLOCK WITH FACE ID"){Task{await model.unlock()}}.buttonStyle(TerminalButton()) }
        else if !model.calendarAuthorized { Text("WHERE DO YOUR APPOINTMENTS LIVE?").font(.system(.title,design:.monospaced));Button("[ A ] APPLE CALENDAR"){Task{await model.connectAppleCalendar()}}.buttonStyle(TerminalButton()) }
        else if model.selectedCalendarID == nil { Text("WHICH ONE HOLDS TATTOOS?").font(.system(.title,design:.monospaced));ForEach(model.calendars,id:\.calendarIdentifier){cal in Button(cal.title.uppercased()){model.choose(cal)}.buttonStyle(TerminalButton())} }
        else { Spacer();Text("ARMED. ✓").font(.system(size:44,weight:.medium,design:.monospaced));Text("calendar................[✓]\n\nYOU CAN CLOSE THIS NOW.").font(.system(.body,design:.monospaced));Spacer() }
        Spacer() }.padding(24).foregroundStyle(Color(red:1,green:176/255,blue:0)) } }.task{await model.unlock()} }
}
struct TerminalButton:ButtonStyle { func makeBody(configuration:Configuration)->some View { configuration.label.font(.system(.headline,design:.monospaced)).frame(maxWidth:.infinity).padding().overlay(Rectangle().stroke(lineWidth:1)).opacity(configuration.isPressed ? 0.6:1) } }
