// KalenderSync – kjøres av launchd på Macen hvert par minutt.
// 1. Sender dagens kalenderhendelser (Bastian, Cadence, William, Fellesplan) til nettsiden.
// 2. Speiler dagens oppgaver i Påminnelser – én liste per barn – og synker avhuking begge veier.
//
// Bruk: KalenderSync <base-url> <token-fil>
import EventKit
import Foundation

let args = CommandLine.arguments
let base = args.count > 1 ? args[1] : "https://oppgaver.coolify.niax.net"
let tokenFile = args.count > 2 ? args[2] : NSString(string: "~/Library/Application Support/FamilieOppgaver/token").expandingTildeInPath
let token = (try? String(contentsOfFile: tokenFile, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
let stateFile = (tokenFile as NSString).deletingLastPathComponent + "/paaminnelser-state.json"
let calendars = ["Bastian", "Cadence", "William", "Fellesplan"]
let scheme = "familieoppgaver"

func log(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }

let store = EKEventStore()

func access(_ type: EKEntityType) -> Bool {
    let sem = DispatchSemaphore(value: 0)
    var ok = false
    if #available(macOS 14.0, *) {
        if type == .event { store.requestFullAccessToEvents { g, _ in ok = g; sem.signal() } }
        else { store.requestFullAccessToReminders { g, _ in ok = g; sem.signal() } }
    } else {
        store.requestAccess(to: type) { g, _ in ok = g; sem.signal() }
    }
    sem.wait()
    return ok
}

func http(_ method: String, _ path: String, _ body: Any? = nil) -> Any? {
    var req = URLRequest(url: URL(string: base + path)!, timeoutInterval: 30)
    req.httpMethod = method
    req.setValue(token, forHTTPHeaderField: "X-Sync-Token")
    if let body = body {
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
    }
    let sem = DispatchSemaphore(value: 0)
    var result: Any?
    URLSession.shared.dataTask(with: req) { data, resp, err in
        if let err = err { log("HTTP-feil \(path): \(err.localizedDescription)") }
        else if let code = (resp as? HTTPURLResponse)?.statusCode, code >= 300 { log("HTTP \(code) \(path)") }
        else if let data = data { result = try? JSONSerialization.jsonObject(with: data) }
        sem.signal()
    }.resume()
    sem.wait()
    return result
}

let iso = ISO8601DateFormatter()
iso.timeZone = TimeZone.current
let dayFmt = DateFormatter()
dayFmt.dateFormat = "yyyy-MM-dd"
let cal = Calendar.current
let today = dayFmt.string(from: Date())

// ---------- 1. Kalender ----------
if access(.event) {
    let cals = store.calendars(for: .event).filter { calendars.contains($0.title) }
    let start = cal.startOfDay(for: Date()).addingTimeInterval(-86400)
    let end = start.addingTimeInterval(86400 * 9)
    var out: [[String: Any]] = []
    for e in store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: cals)) {
        out.append(["cal": e.calendar.title, "title": e.title ?? "", "start": iso.string(from: e.startDate),
                    "end": iso.string(from: e.endDate), "allDay": e.isAllDay, "location": e.location ?? ""])
    }
    let r = http("POST", "/api/calendar", ["events": out, "generated": iso.string(from: Date())])
    log("kalender: \(out.count) hendelser \(r == nil ? "IKKE sendt" : "sendt")")
} else {
    log("ingen kalendertilgang")
}

// ---------- 2. Påminnelser ----------
guard access(.reminder) else { log("ingen tilgang til påminnelser"); exit(0) }
guard let sync = http("GET", "/api/sync?date=\(today)") as? [String: Any],
      let kids = sync["kids"] as? [[String: Any]],
      let tasks = sync["tasks"] as? [[String: Any]] else { log("fikk ikke hentet oppgaver"); exit(1) }
let done = sync["done"] as? [String: [String: Any]] ?? [:]
let away = Set(sync["away"] as? [String] ?? [])
let weekday = (cal.component(.weekday, from: Date()) + 5) % 7  // 0 = mandag

// Bruker de eksisterende, delte listene som heter det samme som barnet («Bastian» osv.).
// Lager aldri nye lister. Andre påminnelser i listene røres ikke – bare de med vår URL.
var lists: [String: EKCalendar] = [:]
let existing = store.calendars(for: .reminder)
for k in kids {
    let id = k["id"] as! String, name = k["name"] as! String
    if let c = existing.first(where: { $0.title == name && $0.allowsContentModifications }) { lists[id] = c }
    else { log("fant ingen skrivbar påminnelsesliste «\(name)»") }
}

// Hent alle påminnelser i listene
let sem = DispatchSemaphore(value: 0)
var reminders: [EKReminder] = []
store.fetchReminders(matching: store.predicateForReminders(in: Array(lists.values))) { r in reminders = r ?? []; sem.signal() }
sem.wait()

// Nøkkel: familieoppgaver://<dato>/<oppgave>/<barn>
func key(_ r: EKReminder) -> (date: String, task: String, kid: String)? {
    guard let u = r.url, u.scheme == scheme, let host = u.host else { return nil }
    let p = u.pathComponents.filter { $0 != "/" }
    return p.count == 2 ? (host, p[0], p[1]) : nil
}
var byKey: [String: EKReminder] = [:]
for r in reminders { if let k = key(r) { byKey["\(k.date)/\(k.task)/\(k.kid)"] = r } }

var prev = (try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: stateFile)))) as? [String: Bool] ?? [:]
var next: [String: Bool] = [:]
var wanted = Set<String>()
var changes = 0

let kidIds = kids.map { $0["id"] as! String }
for t in tasks {
    let tid = t["id"] as! String, owner = t["owner"] as! String
    let days = t["days"] as? [Int] ?? []
    if !days.isEmpty && !days.contains(weekday) { continue }
    let targets = (owner == "felles" ? kidIds : [owner]).filter { !away.contains($0) && lists[$0] != nil }
    if targets.isEmpty { continue }

    let srvDone = done[tid] != nil
    let srvBy = done[tid]?["by"] as? String
    let completers = targets.filter { byKey["\(today)/\(tid)/\($0)"]?.isCompleted == true }
    let remDone = !completers.isEmpty
    let sk = "\(today)/\(tid)"

    var final = srvDone
    var by = srvBy
    if let p = prev[sk] {
        if srvDone != p { final = srvDone }                    // endret på nettsiden
        else if remDone != p { final = remDone; by = completers.first }  // endret i Påminnelser
    } else if remDone && !srvDone { final = true; by = completers.first }
    if final != srvDone {
        let doneAt = completers.compactMap { byKey["\(today)/\(tid)/\($0)"]?.completionDate }.first
        _ = http("POST", "/api/sync/set", ["date": today, "taskId": tid, "done": final, "by": by ?? NSNull(),
                                           "at": doneAt.map { iso.string(from: $0) } ?? NSNull()])
        log("nettside: \(t["title"] as? String ?? "") -> \(final ? "gjort" : "ikke gjort")")
    }
    if final && by == nil { by = completers.first ?? (owner == "felles" ? nil : owner) }
    next[sk] = final

    for kid in targets {
        let k = "\(today)/\(tid)/\(kid)"
        let shouldExist = !final || kid == by || owner != "felles"
        var r = byKey[k]
        if !shouldExist {
            // Felles oppgave tatt av et annet barn – fjern kopien som ikke er huket av
            if let r = r, !r.isCompleted { try? store.remove(r, commit: false); changes += 1 }
            continue
        }
        wanted.insert(k)
        if r == nil {
            let n = EKReminder(eventStore: store)
            n.calendar = lists[kid]
            n.title = "\(t["emoji"] as? String ?? "") \(t["title"] as! String)\(owner == "felles" ? " (felles)" : "")".trimmingCharacters(in: .whitespaces)
            n.url = URL(string: "\(scheme)://\(k)")
            n.dueDateComponents = cal.dateComponents([.year, .month, .day], from: Date())
            r = n
        }
        if r!.isCompleted != final || r!.hasChanges || r!.isNew {
            r!.isCompleted = final
            do { try store.save(r!, commit: false); changes += 1 } catch { log("lagring feilet: \(error.localizedDescription)") }
        }
    }
}

// Rydd: gamle dagers uavhukede og oppgaver som ikke gjelder lenger
for (k, r) in byKey where !wanted.contains(k) && !r.isCompleted {
    try? store.remove(r, commit: false); changes += 1
}
if changes > 0 { try? store.commit() }
if let d = try? JSONSerialization.data(withJSONObject: next) { try? d.write(to: URL(fileURLWithPath: stateFile)) }
log("påminnelser: \(changes) endringer")
