import Foundation
import Security

let service = "com.fryrocket.orca-studio"
let account = "fry"
let input = FileHandle.standardInput.readDataToEndOfFile()
guard let raw = String(data: input, encoding: .utf8) else { exit(2) }
let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
guard (32...512).contains(token.utf8.count), let data = token.data(using: .utf8) else { exit(2) }

let query: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: service,
    kSecAttrAccount as String: account,
]
let attributes: [String: Any] = [
    kSecValueData as String: data,
    kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
]
let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
if status == errSecItemNotFound {
    var item = query
    attributes.forEach { item[$0.key] = $0.value }
    guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { exit(3) }
} else if status != errSecSuccess {
    exit(3)
}
print("ORCA Studio credential stored in Mac Keychain")
