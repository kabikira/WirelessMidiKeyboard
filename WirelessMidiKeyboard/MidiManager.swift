import CoreMIDI
import Foundation

@MainActor
final class MidiManager: ObservableObject {
    @Published private(set) var statusText = "MIDI Initializing"
    @Published private(set) var lastSentText = "Last Sent: -"

    private var client = MIDIClientRef()
    private var outputPort = MIDIPortRef()
    private var destinations: [MIDIEndpointRef] = []
    private let parameterError = OSStatus(-50)

    init() {
        setupCoreMIDI()
    }

    deinit {
        if outputPort != 0 {
            MIDIPortDispose(outputPort)
        }
        if client != 0 {
            MIDIClientDispose(client)
        }
    }

    func refreshDestinations() {
        var foundDestinations: [MIDIEndpointRef] = []

        for index in 0..<MIDIGetNumberOfDestinations() {
            let destination = MIDIGetDestination(index)
            if destination != 0 {
                foundDestinations.append(destination)
            }
        }

        let networkDestination = MIDINetworkSession.default().destinationEndpoint()
        if networkDestination != 0 && !foundDestinations.contains(networkDestination) {
            foundDestinations.append(networkDestination)
        }

        destinations = foundDestinations
        if destinations.isEmpty {
            statusText = "MIDI Ready: No destination found"
        } else {
            statusText = "MIDI Ready: \(destinations.count) destination(s)"
        }
    }

    func sendNoteOn(note: Int, velocity: Int, channel: Int) {
        let noteNumber = UInt8(clamp(note, min: 0, max: 127))
        let noteVelocity = UInt8(clamp(velocity, min: 1, max: 127))
        let status = UInt8(0x90 + clamp(channel, min: 0, max: 15))
        send(bytes: [status, noteNumber, noteVelocity],
             log: "Note On \(MidiNoteName.name(for: Int(noteNumber))) Velocity \(noteVelocity)")
    }

    func sendNoteOff(note: Int, channel: Int) {
        let noteNumber = UInt8(clamp(note, min: 0, max: 127))
        let status = UInt8(0x80 + clamp(channel, min: 0, max: 15))
        send(bytes: [status, noteNumber, 0],
             log: "Note Off \(MidiNoteName.name(for: Int(noteNumber)))")
    }

    func sendControlChange(controller: Int, value: Int, channel: Int) {
        let controllerNumber = UInt8(clamp(controller, min: 0, max: 127))
        let controllerValue = UInt8(clamp(value, min: 0, max: 127))
        let status = UInt8(0xB0 + clamp(channel, min: 0, max: 15))
        send(bytes: [status, controllerNumber, controllerValue],
             log: "CC \(controllerNumber) Value \(controllerValue)")
    }

    func sendProgramChange(program: Int, channel: Int) {
        let programNumber = UInt8(clamp(program, min: 0, max: 127))
        let status = UInt8(0xC0 + clamp(channel, min: 0, max: 15))
        send(bytes: [status, programNumber],
             log: "Program Change \(programNumber)")
    }

    func sendChannelPressure(value: Int, channel: Int) {
        let pressure = UInt8(clamp(value, min: 0, max: 127))
        let status = UInt8(0xD0 + clamp(channel, min: 0, max: 15))
        send(bytes: [status, pressure],
             log: "Channel Pressure \(pressure)")
    }

    func sendPitchBend(value: Int, channel: Int) {
        let pitchValue = clamp(value, min: 0, max: 16_383)
        let lsb = UInt8(pitchValue & 0x7F)
        let msb = UInt8((pitchValue >> 7) & 0x7F)
        let status = UInt8(0xE0 + clamp(channel, min: 0, max: 15))
        send(bytes: [status, lsb, msb],
             log: "Pitch Bend \(pitchValue)")
    }

    private func setupCoreMIDI() {
        let clientStatus = MIDIClientCreateWithBlock("Wireless MIDI Keyboard Client" as CFString, &client) { [weak self] _ in
            Task { @MainActor in
                self?.refreshDestinations()
            }
        }

        guard clientStatus == noErr else {
            statusText = "MIDI Client Error: \(clientStatus)"
            return
        }

        let portStatus = MIDIOutputPortCreate(client, "Wireless MIDI Keyboard Output" as CFString, &outputPort)
        guard portStatus == noErr else {
            statusText = "MIDI Output Port Error: \(portStatus)"
            return
        }

        // iPadをNetwork MIDIセッション参加者として有効化します。
        let session = MIDINetworkSession.default()
        session.isEnabled = true
        session.connectionPolicy = .anyone

        refreshDestinations()
    }

    private func send(bytes: [UInt8], log: String) {
        if destinations.isEmpty {
            refreshDestinations()
        }

        guard !destinations.isEmpty else {
            lastSentText = "Last Sent: \(log)"
            statusText = "MIDI Ready: No destination found"
            return
        }

        var packetList = MIDIPacketList()
        let sendStatus = bytes.withUnsafeBufferPointer { bufferPointer -> OSStatus in
            guard let baseAddress = bufferPointer.baseAddress else {
                return parameterError
            }

            return withUnsafeMutablePointer(to: &packetList) { packetListPointer in
                let packet = MIDIPacketListInit(packetListPointer)
                MIDIPacketListAdd(packetListPointer,
                                  MemoryLayout<MIDIPacketList>.size,
                                  packet,
                                  0,
                                  bytes.count,
                                  baseAddress)

                var result: OSStatus = noErr
                for destination in destinations {
                    result = MIDISend(outputPort, destination, packetListPointer)
                    if result != noErr {
                        break
                    }
                }
                return result
            }
        }

        lastSentText = "Last Sent: \(log)"
        if sendStatus == noErr {
            statusText = "MIDI Ready: Sent"
        } else {
            statusText = "MIDI Send Error: \(sendStatus)"
        }
    }

    private func clamp(_ value: Int, min lowerBound: Int, max upperBound: Int) -> Int {
        Swift.max(lowerBound, Swift.min(value, upperBound))
    }
}

enum MidiNoteName {
    private static let names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    static func name(for noteNumber: Int) -> String {
        let noteIndex = ((noteNumber % 12) + 12) % 12
        let octave = ((noteNumber - 60) / 12) + 3
        return "\(names[noteIndex])\(octave)"
    }
}
