import asyncio, re, subprocess, wave, os, tempfile, json
import urllib.request, urllib.parse
from winsdk.windows.foundation import Uri
from winsdk.windows.storage.streams import RandomAccessStreamReference
from winsdk.windows.media.playback import MediaPlayer
from winsdk.windows.media import (SystemMediaTransportControlsButton as Btn,
                                  MediaPlaybackStatus, MediaPlaybackType)
from winsdk.windows.media.core import MediaSource
from winsdk.windows.storage import StorageFile

ADB = r"C:\Users\Resul\Downloads\LDPlayer Opti V2\emudata\adb.exe"
NO_WINDOW = 0x08000000

# Tuş -> Android keyevent (85 = play/pause toggle)
KEYS = {Btn.PLAY: 85, Btn.PAUSE: 85, Btn.NEXT: 87, Btn.PREVIOUS: 88}

SERIAL = None


def run_adb(*args):
    try:
        return subprocess.run([ADB, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=5, creationflags=NO_WINDOW).stdout
    except Exception:
        return ""


def find_serial():
    out = run_adb("devices")
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            return parts[0]
    return None


def adb(*args):
    global SERIAL
    if SERIAL is None:
        SERIAL = find_serial()
    if SERIAL is None:
        return ""
    return run_adb("-s", SERIAL, *args)


def get_state():
    out = adb("shell", "dumpsys", "media_session")
    for m in re.finditer(r"metadata:size=(\d+), description=([^\r\n]*)", out):
        if m.group(1) == "0":
            continue  # boş oturumları atla (telecom vb.)
        parts = [p.strip() for p in m.group(2).split(", ")]
        title = parts[0]
        artist = ", ".join(p for p in parts[1:] if p and p != "null")
        states = re.findall(r"state=PlaybackState \{state=(\d+)", out[:m.start()])
        playing = bool(states) and states[-1] == "3"
        return (title, artist), playing
    return None, None


def get_art_url(title, artist):
    try:
        term = urllib.parse.quote(f"{title} {artist}")
        url = f"https://itunes.apple.com/search?term={term}&media=music&entity=song&limit=1"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.load(r)
        if data.get("resultCount"):
            return data["results"][0]["artworkUrl100"].replace("100x100", "600x600")
    except Exception:
        pass
    return None


async def main():
    loop = asyncio.get_running_loop()

    # Sessiz wav: Windows'un oturumu aktif saymasi icin
    wav = os.path.join(tempfile.gettempdir(), "silence.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)

    player = MediaPlayer()
    player.command_manager.is_enabled = False
    player.is_looping_enabled = True
    f = await StorageFile.get_file_from_path_async(wav)
    player.source = MediaSource.create_from_storage_file(f)
    player.play()

    smtc = player.system_media_transport_controls
    smtc.is_enabled = True
    smtc.is_play_enabled = True
    smtc.is_pause_enabled = True
    smtc.is_next_enabled = True
    smtc.is_previous_enabled = True

    def on_button(sender, args):
        key = KEYS.get(args.button)
        if key:
            adb("shell", "input", "keyevent", str(key))

    smtc.add_button_pressed(on_button)

    last = None
    art = None
    while True:
        info, playing = await loop.run_in_executor(None, get_state)
        if info and (info, playing) != last:
            if not last or last[0] != info:  # sarki degisti -> kapak ara
                art = await loop.run_in_executor(None, get_art_url, *info)
            du = smtc.display_updater
            du.type = MediaPlaybackType.MUSIC
            du.music_properties.title = info[0]
            du.music_properties.artist = info[1]
            try:
                du.thumbnail = (RandomAccessStreamReference.create_from_uri(Uri(art))
                                if art else None)
            except Exception:
                pass
            du.update()
            smtc.playback_status = (MediaPlaybackStatus.PLAYING if playing
                                    else MediaPlaybackStatus.PAUSED)
            last = (info, playing)
        await asyncio.sleep(1)


asyncio.run(main())
