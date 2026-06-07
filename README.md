# Wireless MIDI Keyboard

iPadをMac上のAbleton Liveで使うための無線MIDIキーボード / MIDIコントローラーMVPです。iPad側では音を鳴らさず、CoreMIDIでNetwork MIDIセッションへMIDI信号だけを送信します。

## 機能

- C3からC5までのピアノ鍵盤
- Note On / Note Off送信
- Velocity指定: 1から127、初期値100
- MIDI Channel指定: UIは1から16、内部値は0から15
- Pitch Bend: 0から16383、中央8192、操作終了時に中央へ戻る
- Control Changeスライダー4本
  - CC1 Modulation
  - CC7 Volume
  - CC10 Pan
  - CC74 Filter Cutoff
- Program Change送信
- Channel Pressure / Aftertouch送信
- 送信状態と最後に送信したMIDIメッセージの表示

## ビルド方法

1. `WirelessMidiKeyboard.xcodeproj` をXcodeで開く
2. Signing & Capabilitiesで自分のTeamを選ぶ
3. 実機iPadを選ぶ
4. Runする

ローカル利用向けMVPなので、App Store公開用のアイコンや配布設定は入れていません。

## Mac / Ableton Live側の設定手順

1. iPadとMacを同じWi-Fiに接続する
2. Macで「Audio MIDI設定」を開く
3. メニューから「MIDIスタジオ」を開く
4. 「ネットワーク」を開く
5. セッションを有効化する
6. iPadアプリからネットワークMIDIを送信する
7. Ableton Liveを開く
8. Settings / Preferences > Link, Tempo & MIDI を開く
9. iPadまたはNetwork Session由来のMIDI InputのTrackをONにする
10. AbletonでMIDIトラックを作る
11. Drift、Wavetable、Analog、SimplerなどのInstrumentを挿す
12. MIDI Fromに該当ポートを選ぶ
13. MonitorをIn、またはArm録音ボタンをONにする
14. iPadの鍵盤を押して音が出るか確認する

## 使い方

1. アプリ起動後、上部の表示が `MIDI Ready` になることを確認する
2. 必要に応じてMIDI Channelを選ぶ
3. Velocityスライダーで強さを決める
4. 鍵盤を押すとNote On、離すとNote Offが送信される
5. Ableton側のInstrumentが音源として鳴る

## 実装メモ

- `MidiManager` がCoreMIDIのClient、Output Port、Network MIDI Session、送信処理を担当します。
- Note Offは `0x80 + channel`、velocity 0で送信します。
- Pitch Bendは14bit値をLSB / MSBに分けて `0xE0 + channel` で送信します。
- iPad側で音声出力、シンセ、サンプラー処理は行いません。

## トラブルシューティング

### Abletonで音が鳴らない場合

- AbletonのMIDI InputでTrackがONになっているか確認する
- MIDIトラックにInstrumentが入っているか確認する
- MonitorがIn、またはトラックArmがONになっているか確認する
- iPadとMacが同じWi-Fiにいるか確認する
- MacのAudio MIDI設定でネットワークセッションが有効か確認する
- アプリ上部の `Refresh` を押してMIDI Destinationを再検出する
- 初回起動時にローカルネットワーク許可ダイアログが出たら許可する

### ノブやフェーダーでAbletonのパラメータを動かしたい場合

- AbletonのMIDI InputでRemoteをONにする
- MIDI Map Modeを開く
- 操作したいパラメータをクリックする
- iPad側のCCスライダーを動かす
- MIDI Map Modeを閉じる

### 音の遅延が大きい場合

- Wi-Fi環境を変える
- MacとiPadを同じ5GHz Wi-Fiにする
- 可能なら有線接続やBluetooth MIDIも検討する
- Ableton側のBuffer Sizeも確認する
