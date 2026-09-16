"""Explicit online initial acquisition. No private data is sent."""
from .update import add_official, update_manual

def main():
    update_manual(11)
    for url in [
        "https://help.ableton.com/hc/en-us/articles/360006569179-Monitoring-in-Ableton-Live-FAQ",
        "https://help.ableton.com/hc/en-us/articles/209774265-Using-hardware-synthesizers-with-Live",
        "https://help.ableton.com/hc/en-us/articles/211476789-Setting-up-an-Audio-Interface",
        "https://help.ableton.com/hc/en-us/articles/360011853159-MIDI-controllers-FAQ",
    ]:
        try:
            print(add_official(url, "ableton/knowledge-base"), flush=True)
        except Exception as exc:
            print("取得失敗（既存資料を維持）:", url, str(exc), flush=True)
    print(add_official("https://docs.cycling74.com/apiref/lom/", "max_for_live"), flush=True)
    print(add_official("https://docs.cycling74.com/userguide/m4l/live_api/", "max_for_live"), flush=True)

if __name__ == "__main__":
    main()
