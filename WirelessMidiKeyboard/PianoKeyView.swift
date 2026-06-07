import SwiftUI

struct PianoKeyView: View {
    let note: Int
    let isBlack: Bool
    let velocity: Int
    let channel: Int
    let midiManager: MidiManager

    @State private var isPressed = false

    var body: some View {
        Rectangle()
            .fill(fillColor)
            .overlay(
                Rectangle()
                    .stroke(isBlack ? Color.black : Color.gray.opacity(0.45), lineWidth: 1)
            )
            .overlay(alignment: isBlack ? .top : .bottom) {
                Text(MidiNoteName.name(for: note))
                    .font(.caption2)
                    .foregroundStyle(isBlack ? .white.opacity(0.85) : .black.opacity(0.75))
                    .padding(.vertical, 8)
            }
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        startNoteIfNeeded()
                    }
                    .onEnded { _ in
                        stopNoteIfNeeded()
                    }
            )
            .accessibilityLabel(Text("\(MidiNoteName.name(for: note)) key"))
    }

    private var fillColor: Color {
        if isBlack {
            return isPressed ? Color(red: 0.22, green: 0.30, blue: 0.38) : Color.black
        } else {
            return isPressed ? Color(red: 0.74, green: 0.87, blue: 1.0) : Color.white
        }
    }

    private func startNoteIfNeeded() {
        guard !isPressed else { return }
        isPressed = true
        midiManager.sendNoteOn(note: note, velocity: velocity, channel: channel)
    }

    private func stopNoteIfNeeded() {
        guard isPressed else { return }
        isPressed = false
        midiManager.sendNoteOff(note: note, channel: channel)
    }
}

struct PianoKeyboardView: View {
    let startNote: Int
    let endNote: Int
    let velocity: Int
    let channel: Int
    let midiManager: MidiManager

    private var whiteNotes: [Int] {
        (startNote...endNote).filter { !Self.isBlackKey($0) }
    }

    private var blackNotes: [Int] {
        (startNote...endNote).filter(Self.isBlackKey)
    }

    var body: some View {
        GeometryReader { geometry in
            let whiteWidth = geometry.size.width / CGFloat(whiteNotes.count)
            let blackWidth = whiteWidth * 0.62
            let blackHeight = geometry.size.height * 0.62

            ZStack(alignment: .topLeading) {
                HStack(spacing: 0) {
                    ForEach(whiteNotes, id: \.self) { note in
                        PianoKeyView(note: note,
                                     isBlack: false,
                                     velocity: velocity,
                                     channel: channel,
                                     midiManager: midiManager)
                            .frame(width: whiteWidth, height: geometry.size.height)
                    }
                }

                ForEach(blackNotes, id: \.self) { note in
                    if let xPosition = blackKeyXPosition(note: note, whiteWidth: whiteWidth) {
                        PianoKeyView(note: note,
                                     isBlack: true,
                                     velocity: velocity,
                                     channel: channel,
                                     midiManager: midiManager)
                            .frame(width: blackWidth, height: blackHeight)
                            .position(x: xPosition, y: blackHeight / 2)
                            .zIndex(1)
                    }
                }
            }
        }
        .frame(minHeight: 220)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func blackKeyXPosition(note: Int, whiteWidth: CGFloat) -> CGFloat? {
        guard let previousWhiteIndex = whiteNotes.lastIndex(where: { $0 < note }) else {
            return nil
        }
        return CGFloat(previousWhiteIndex + 1) * whiteWidth
    }

    private static func isBlackKey(_ note: Int) -> Bool {
        [1, 3, 6, 8, 10].contains(note % 12)
    }
}
