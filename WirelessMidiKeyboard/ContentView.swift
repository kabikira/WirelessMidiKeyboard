import SwiftUI

struct ContentView: View {
    @StateObject private var midiManager = MidiManager()

    @State private var channel = 0
    @State private var velocity = 100.0
    @State private var pitchBend = 8_192.0
    @State private var programNumber = 0
    @State private var aftertouch = 0.0
    @State private var ccControls = [
        CCControl(name: "Modulation", controller: 1, value: 0),
        CCControl(name: "Volume", controller: 7, value: 100),
        CCControl(name: "Pan", controller: 10, value: 64),
        CCControl(name: "Filter Cutoff", controller: 74, value: 64)
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    statusSection
                    keyboardSection
                    pitchBendSection
                    ccSection
                    programAndAftertouchSection
                }
                .padding(20)
            }
            .background(Color(red: 0.94, green: 0.95, blue: 0.96))
            .navigationTitle("Wireless MIDI Keyboard")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private var statusSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 14) {
                Text(midiManager.statusText)
                    .font(.headline)
                Spacer()
                Button("Refresh") {
                    midiManager.refreshDestinations()
                }
                .buttonStyle(.bordered)
            }

            Text(midiManager.lastSentText)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            HStack(spacing: 20) {
                Picker("MIDI Channel", selection: $channel) {
                    ForEach(0..<16, id: \.self) { index in
                        Text("Channel \(index + 1)").tag(index)
                    }
                }
                .pickerStyle(.menu)

                VStack(alignment: .leading) {
                    Text("Velocity \(Int(velocity))")
                        .font(.subheadline)
                    Slider(value: $velocity, in: 1...127, step: 1)
                        .frame(maxWidth: 360)
                }
            }
        }
        .padding(16)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var keyboardSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("C3 - C5")
                .font(.headline)
            PianoKeyboardView(startNote: 60,
                              endNote: 84,
                              velocity: Int(velocity),
                              channel: channel,
                              midiManager: midiManager)
                .frame(height: 250)
                .shadow(color: .black.opacity(0.12), radius: 6, y: 3)
        }
    }

    private var pitchBendSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Pitch Bend \(Int(pitchBend))")
                .font(.headline)
            Slider(value: $pitchBend, in: 0...16_383, step: 1) { editing in
                if !editing {
                    pitchBend = 8_192
                    midiManager.sendPitchBend(value: 8_192, channel: channel)
                }
            }
            .onChange(of: pitchBend) { _, newValue in
                midiManager.sendPitchBend(value: Int(newValue), channel: channel)
            }
        }
        .padding(16)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var ccSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Control Change")
                .font(.headline)

            ForEach($ccControls) { $control in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("\(control.name)  CC\(control.controller)")
                            .font(.subheadline)
                        Spacer()
                        Picker("CC", selection: $control.controller) {
                            ForEach(0..<128, id: \.self) { number in
                                Text("CC \(number)").tag(number)
                            }
                        }
                        .pickerStyle(.menu)
                    }

                    Slider(value: $control.value, in: 0...127, step: 1)
                        .onChange(of: control.value) { _, newValue in
                            midiManager.sendControlChange(controller: control.controller,
                                                          value: Int(newValue),
                                                          channel: channel)
                        }
                }
            }
        }
        .padding(16)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var programAndAftertouchSection: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Program Change")
                    .font(.headline)
                Stepper("Program \(programNumber)", value: $programNumber, in: 0...127)
                Button("Send Program Change") {
                    midiManager.sendProgramChange(program: programNumber, channel: channel)
                }
                .buttonStyle(.borderedProminent)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            VStack(alignment: .leading, spacing: 12) {
                Text("Aftertouch \(Int(aftertouch))")
                    .font(.headline)
                Slider(value: $aftertouch, in: 0...127, step: 1)
                    .onChange(of: aftertouch) { _, newValue in
                        midiManager.sendChannelPressure(value: Int(newValue), channel: channel)
                    }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(16)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

struct CCControl: Identifiable {
    let id = UUID()
    var name: String
    var controller: Int
    var value: Double
}
