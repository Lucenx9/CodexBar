import Foundation
import Testing
@testable import CodexBarCore

struct CostUsageAsciiSearchTests {
    private static let inputs: [[UInt8]] = [
        [],
        Array("a".utf8),
        Array("needle".utf8),
        Array("prefix needle suffix needle".utf8),
        Array("é🦞é".utf8),
        [0, 255, 34, 0, 92, 127, 128],
        Array(repeating: 97, count: 4096) + [98],
    ]
    private static let needles = [
        "", "a", "b", "needle", "needle suffix", "needle suffix needle", "needle suffix needles",
        "é", "é", "🦞", "\0", "\0\\", "\"", "\\", "aaaaab", "aaaaac",
    ]

    @Test(arguments: Self.inputs, Self.needles)
    func `bounded byte searches match Foundation for owned data and slices`(bytes: [UInt8], needle: String) {
        let padding = Data("needle".utf8)
        let padded = padding + Data(bytes) + padding
        let view = padded.dropFirst(padding.count).dropLast(padding.count)
        for haystack in [Data(bytes), view] {
            let expected = haystack.range(of: Data(needle.utf8)) != nil
            #expect(haystack.containsAscii(needle) == expected)
        }
    }

    @Test
    func `binary haystacks and varied UTF8 needles match Foundation deterministically`() {
        var state: UInt64 = 0xC0DE
        func next() -> UInt8 {
            state = state &* 6_364_136_223_846_793_005 &+ 1
            return UInt8(truncatingIfNeeded: state >> 32)
        }
        let alphabet = ["a", "b", "\"", "\\", "\0", "é", "🦞"]
        for length in 0...256 {
            let haystack = Data((0..<length).map { _ in next() })
            let needle = (0..<(length % 17)).map { _ in alphabet[Int(next()) % alphabet.count] }.joined()
            let expected = haystack.range(of: Data(needle.utf8)) != nil
            #expect(haystack.containsAscii(needle) == expected)
        }
    }
}
