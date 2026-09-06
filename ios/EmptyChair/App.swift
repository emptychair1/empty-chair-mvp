import SwiftUI
import EventKit
import LocalAuthentication
import Security
import BackgroundTasks
import UIKit

final class BackgroundSyncCoordinator {
    static let shared=BackgroundSyncCoordinator()
    weak var model:EmptyChairModel?
    let identifier="com.tryemptychair.calendar-sync"
    func register(){
        BGTaskScheduler.shared.register(forTaskWithIdentifier:identifier,using:nil){ task in
            guard let refresh=task as? BGAppRefreshTask else{task.setTaskCompleted(success:false);return}
            self.schedule()
            let work=Task { @MainActor in await self.model?.sync(); refresh.setTaskCompleted(success:true) }
            refresh.expirationHandler={work.cancel()}
        }
    }
    func schedule(){
        let request=BGAppRefreshTaskRequest(identifier:identifier)
        request.earliestBeginDate=Date(timeIntervalSinceNow:15*60)
        try? BGTaskScheduler.shared.submit(request)
    }
}

final class AppDelegate:NSObject,UIApplicationDelegate {
    func application(_ application:UIApplication,didFinishLaunchingWithOptions launchOptions:[UIApplication.LaunchOptionsKey:Any]?=nil)->Bool {
        BackgroundSyncCoordinator.shared.register();BackgroundSyncCoordinator.shared.schedule();return true
    }
    func applicationDidEnterBackground(_ application:UIApplication){BackgroundSyncCoordinator.shared.schedule()}
}

@main
struct EmptyChairApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var model:EmptyChairModel
    init(){let m=EmptyChairModel();_model=StateObject(wrappedValue:m);BackgroundSyncCoordinator.shared.model=m}
    var body: some Scene { WindowGroup { RootView().environmentObject(model) } }
}

struct NativeEvent: Codable { let id:String; let title:String; let start_at:String; let end_at:String }
struct NativeCommand: Codable { let id:String; let kind:String; let payload:CommandPayload }
struct CommandPayload: Codable { let title:String; let start_at:String; let end_at:String; let notes:String? }
struct SyncReply: Codable { let ok:Bool; let commands:[NativeCommand] }
struct SyncPayload: Codable { let calendar_id:String; let events:[NativeEvent] }
struct AuthStartReply: Codable { let challenge_id:String; let last4:String }
struct AuthVerifyReply: Codable { let device_token:String; let artist_id:String; let artist_name:String }

struct Keychain {
    static let service="com.tryemptychair.EmptyChair"
    static func set(_ value:String,key:String){
        let data=Data(value.utf8)
        SecItemDelete([kSecClass:kSecClassGenericPassword,kSecAttrService:service,kSecAttrAccount:key] as CFDictionary)
        SecItemAdd([kSecClass:kSecClassGenericPassword,kSecAttrService:service,kSecAttrAccount:key,kSecValueData:data,kSecAttrAccessible:kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly] as CFDictionary,nil)
    }
    static func get(_ key:String)->String?{
        var item:CFTypeRef?
        let status=SecItemCopyMatching([kSecClass:kSecClassGenericPassword,kSecAttrService:service,kSecAttrAccount:key,kSecReturnData:true,kSecMatchLimit:kSecMatchLimitOne] as CFDictionary,&item)
        guard status==errSecSuccess,let data=item as? Data else{return nil}
        return String(data:data,encoding:.utf8)
    }
}

@MainActor
final class EmptyChairModel: ObservableObject {
    @Published var unlocked=false
    @Published var linked=Keychain.get("deviceToken") != nil
    @Published var phone=""
    @Published var code=""
    @Published var challengeID:String?
    @Published var authMessage=""
    @Published var calendarAuthorized=false
    @Published var calendars:[EKCalendar]=[]
    @Published var selectedCalendarID=UserDefaults.standard.string(forKey:"tattooCalendarID")
    @Published var status="LOCKED"

    let store=EKEventStore()
    let api=URL(string:"https://app.tryemptychair.com")!
    private let iso=ISO8601DateFormatter()

    init(){
        NotificationCenter.default.addObserver(forName:.EKEventStoreChanged,object:nil,queue:.main){ [weak self] _ in
            Task { @MainActor in await self?.sync() }
        }
    }

    func unlock() async {
        let context=LAContext()
        if context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics,error:nil){
            do { unlocked=try await context.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics,localizedReason:"Open Empty Chair") }
            catch { status="LOCKED"; return }
        } else { unlocked=true }
        await loadCalendarState()
    }

    func startPhoneLink() async {
        let payload=["phone":phone]
        guard let body=try? JSONSerialization.data(withJSONObject:payload) else{return}
        var r=URLRequest(url:api.appending(path:"native/auth/start"));r.httpMethod="POST";r.setValue("application/json",forHTTPHeaderField:"Content-Type");r.httpBody=body
        do {
            let (data,response)=try await URLSession.shared.data(for:r)
            guard (response as? HTTPURLResponse)?.statusCode==200 else { authMessage="CHECK THAT MOBILE NUMBER";return }
            let reply=try JSONDecoder().decode(AuthStartReply.self,from:data)
            challengeID=reply.challenge_id;authMessage="CODE SENT TO ***\(reply.last4)"
        } catch { authMessage="CHECK CONNECTION" }
    }

    func verifyPhoneLink() async {
        guard let challengeID else{return}
        let payload=["challenge_id":challengeID,"code":code,"calendar_id":selectedCalendarID ?? ""]
        guard let body=try? JSONSerialization.data(withJSONObject:payload) else{return}
        var r=URLRequest(url:api.appending(path:"native/auth/verify"));r.httpMethod="POST";r.setValue("application/json",forHTTPHeaderField:"Content-Type");r.httpBody=body
        do {
            let (data,response)=try await URLSession.shared.data(for:r)
            guard (response as? HTTPURLResponse)?.statusCode==200 else { authMessage="THAT CODE DIDN'T WORK";return }
            let reply=try JSONDecoder().decode(AuthVerifyReply.self,from:data)
            Keychain.set(reply.device_token,key:"deviceToken");linked=true;authMessage="LINKED [✓]"
            await loadCalendarState()
        } catch { authMessage="CHECK CONNECTION" }
    }

    func loadCalendarState() async {
        guard linked else{return}
        let auth=EKEventStore.authorizationStatus(for:.event)
        calendarAuthorized=auth == .fullAccess || auth == .authorized
        if calendarAuthorized {
            calendars=store.calendars(for:.event).filter{$0.allowsContentModifications}
            status=selectedCalendarID == nil ? "CHOOSE CALENDAR":"ARMED"
            await sync()
        }
    }

    func connectAppleCalendar() async {
        do {
            if #available(iOS 17.0,*) { calendarAuthorized=try await store.requestFullAccessToEvents() }
            else { calendarAuthorized=try await store.requestAccess(to:.event) }
            if calendarAuthorized { calendars=store.calendars(for:.event).filter{$0.allowsContentModifications};status="CHOOSE CALENDAR" }
        } catch { status="CHECK CALENDAR" }
    }

    func choose(_ calendar:EKCalendar) {
        selectedCalendarID=calendar.calendarIdentifier
        UserDefaults.standard.set(calendar.calendarIdentifier,forKey:"tattooCalendarID")
        status="ARMED"
        Task { await sync() }
    }

    func sync() async {
        guard linked,calendarAuthorized,let calendarID=selectedCalendarID,let calendar=store.calendar(withIdentifier:calendarID),let token=Keychain.get("deviceToken") else{return}
        let start=Date().addingTimeInterval(-86400);let end=Date().addingTimeInterval(86400*180)
        let predicate=store.predicateForEvents(withStart:start,end:end,calendars:[calendar])
        let events=store.events(matching:predicate).map{NativeEvent(id:$0.eventIdentifier ?? $0.calendarItemIdentifier,title:$0.title ?? "Tattoo",start_at:iso.string(from:$0.startDate),end_at:iso.string(from:$0.endDate))}
        var r=URLRequest(url:api.appending(path:"native/calendar/sync"));r.httpMethod="POST";r.setValue("Bearer \(token)",forHTTPHeaderField:"Authorization");r.setValue("application/json",forHTTPHeaderField:"Content-Type");r.httpBody=try? JSONEncoder().encode(SyncPayload(calendar_id:calendarID,events:events))
        guard let (data,response)=try? await URLSession.shared.data(for:r),(response as? HTTPURLResponse)?.statusCode==200,let reply=try? JSONDecoder().decode(SyncReply.self,from:data) else{return}
        for command in reply.commands where command.kind=="upsert_event" { await apply(command,calendar:calendar,token:token) }
        BackgroundSyncCoordinator.shared.schedule()
    }

    private func apply(_ command:NativeCommand,calendar:EKCalendar,token:String) async {
        guard let start=iso.date(from:command.payload.start_at),let end=iso.date(from:command.payload.end_at) else{return}
        let event=EKEvent(eventStore:store);event.calendar=calendar;event.title=command.payload.title;event.startDate=start;event.endDate=end;event.notes=command.payload.notes
        do { try store.save(event,span:.thisEvent,commit:true) } catch { status="CHECK CALENDAR";return }
        var r=URLRequest(url:api.appending(path:"native/calendar/ack/\(command.id)"));r.httpMethod="POST";r.setValue("Bearer \(token)",forHTTPHeaderField:"Authorization");_=try? await URLSession.shared.data(for:r)
    }
}

struct RootView:View {
    @EnvironmentObject var model:EmptyChairModel
    var body:some View {
        NavigationStack {
            ZStack {
                Color(red:11/255,green:9/255,blue:5/255).ignoresSafeArea()
                VStack(alignment:.leading,spacing:24){
                    HStack{Text("EMPTY CHAIR");Spacer();Text("2.0")}.font(.system(.headline,design:.monospaced));Divider()
                    if !model.unlocked {
                        Text("EMPTY CHAIR // LOCKED").font(.system(.largeTitle,design:.monospaced))
                        Button("UNLOCK WITH FACE ID"){Task{await model.unlock()}}.buttonStyle(TerminalButton())
                    } else if !model.linked {
                        Text("LINK THIS IPHONE").font(.system(.title,design:.monospaced))
                        if model.challengeID == nil {
                            TextField("MOBILE",text:$model.phone).keyboardType(.phonePad).textInputAutocapitalization(.never).padding().overlay(Rectangle().stroke())
                            Button("TEXT ME A CODE"){Task{await model.startPhoneLink()}}.buttonStyle(TerminalButton())
                        } else {
                            Text(model.authMessage).font(.system(.caption,design:.monospaced))
                            TextField("6-DIGIT CODE",text:$model.code).keyboardType(.numberPad).padding().overlay(Rectangle().stroke())
                            Button("VERIFY THIS IPHONE"){Task{await model.verifyPhoneLink()}}.buttonStyle(TerminalButton())
                        }
                    } else if !model.calendarAuthorized {
                        Text("WHERE DO YOUR APPOINTMENTS LIVE?").font(.system(.title,design:.monospaced))
                        Button("[ A ] APPLE CALENDAR"){Task{await model.connectAppleCalendar()}}.buttonStyle(TerminalButton())
                    } else if model.selectedCalendarID == nil {
                        Text("WHICH ONE HOLDS TATTOOS?").font(.system(.title,design:.monospaced))
                        ForEach(model.calendars,id:\.calendarIdentifier){cal in Button(cal.title.uppercased()){model.choose(cal)}.buttonStyle(TerminalButton())}
                    } else {
                        Spacer();Text("ARMED. ✓").font(.system(size:44,weight:.medium,design:.monospaced));Text("calendar................[✓]\n\nYOU CAN CLOSE THIS NOW.").font(.system(.body,design:.monospaced));Spacer()
                    }
                    Spacer()
                }.padding(24).foregroundStyle(Color(red:1,green:176/255,blue:0))
            }
        }.task{await model.unlock()}
    }
}

struct TerminalButton:ButtonStyle {
    func makeBody(configuration:Configuration)->some View { configuration.label.font(.system(.headline,design:.monospaced)).frame(maxWidth:.infinity).padding().overlay(Rectangle().stroke(lineWidth:1)).opacity(configuration.isPressed ? 0.6:1) }
}
