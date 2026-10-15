import Foundation
import Testing
@testable import CodexBarCore

struct CodexIdentifiedScanTests {
    @Test(arguments: ["response_item", "future_event", "event_msg"])
    func `nonusage message text cannot create or hide owned requests`(type: String) throws {
        let text = String(repeating: "synthetic text ", count: 1000)
            + #""usage" "token_usage_record" "event_msg" "session_meta" "turn_context""#
        let message = try JSONSerialization.data(withJSONObject: [
            "type": type,
            "timestamp": "2026-08-31T12:00:00Z",
            "payload": ["type": "message", "text": text],
        ])
        var content = Data()
        for _ in 0..<100 {
            content.append(message)
            content.append(0x0A)
        }
        let ledger = try Self.load(content)
        #expect(ledger.records.count == 1)
        #expect(try CodexRequestLedger.merge([ledger]).totalTokens == 110)
        #expect(!ledger.partial)
        #expect(ledger.excludedCount == 0)
    }

    @Test(arguments: [
        #"{"type":"response_item","payload":{"text":"\q"}}"#,
        #"{"type":"response_item","payload":{"text":"\uD800"}}"#,
        #"{"type":"response_item","payload":{"count":01}}"#,
        #"{"type":"response_item","payload":{"count":1e999}}"#,
        #"{"type":"future_event","payload":broken}"#,
        "[]",
        "true",
    ])
    func `nonusage validation preserves Foundation object acceptance`(line: String) throws {
        let malformed = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any] == nil
        let ledger = try Self.load(Data((line + "\n").utf8))
        #expect(ledger.partial == malformed)
        #expect(ledger.records.count == 1)
        #expect(try CodexRequestLedger.merge([ledger]).totalTokens == 110)
    }

    @Test
    func `bare legacy usage remains excluded rather than silently skipped`() throws {
        let line = #"{"timestamp":"2026-08-31T12:00:00Z","model":"gpt-5","usage":{"input_tokens":7,"output_tokens":3}}"#
        let ledger = try Self.load(Data((line + "\n").utf8))
        #expect(ledger.partial)
        #expect(ledger.excludedCount == 1)
        #expect(ledger.records.count == 1)
        #expect(try CodexRequestLedger.merge([ledger]).totalTokens == 110)
    }

    @Test
    func `turn context still supplies model attribution for owned requests`() throws {
        let context = """
        {"type":"turn_context","timestamp":"2026-08-31T12:00:00Z",\
        "payload":{"model":"kimi-coding/k2p5"}}

        """
        let ledger = try Self.load(Data(context.utf8), requestModel: "")
        #expect(ledger.records.isEmpty)
        #expect(ledger.excludedCount == 0)
        #expect(!ledger.partial)
    }

    private static func load(_ message: Data, requestModel: String = "gpt-5") throws -> CodexRequestLedger {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        var content = Data("{\"type\":\"session_meta\",\"payload\":{\"id\":\"fixture-session\"}}\n".utf8)
        content.append(message)
        content.append(Data("""
        {"type":"token_usage_record","timestamp":"2026-08-31T12:00:00Z","payload":{\
        "thread_id":"fixture-session","response_id":"fixture-response","model":"\(requestModel)",\
        "usage":{"input_tokens":100,"cached_input_tokens":20,"output_tokens":10},\
        "thread_token_usage":{"input_tokens":100,"cached_input_tokens":20,"output_tokens":10}}}

        """.utf8))
        try content.write(to: root.appendingPathComponent("fixture.jsonl"))
        var options = CostUsageScanner.Options()
        options.codexSessionsRoot = root
        return try CodexRequestLedger.load(
            startUnixMs: 1_788_134_400_000,
            endUnixMs: 1_788_177_600_000,
            options: options,
            checkCancellation: {})
    }
}
