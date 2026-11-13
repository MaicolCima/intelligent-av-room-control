import time

from av_control.beam.atnd1061 import ATND1061Listener
from av_control.beam.calibration import BeamPanMap
from av_control.beam.zones import BeamZoneFilter
from av_control.camera.visca import MinrrayVISCA
from av_control.core.config import load_settings, load_commands
from av_control.core.controller import Controller
from av_control.core.events import log
from av_control.tracking.speaker_tracker import SpeakerTracker
from av_control.voice.matcher import CommandMatcher
from av_control.voice.wakeword import VoiceListener
from av_control.core.metrics import M


def main():
    cfg = load_settings()
    cmds = load_commands(cfg["paths"]["voice_commands_json"])

    cam = MinrrayVISCA(cfg["camera"]["ip"], cfg["camera"]["visca_port"], cfg["camera"]["presets"],
                       cfg["tracking"]["max_visca_speed"])

    for c in cmds["commands"]:
        if c.get("action") == "preset" and str(c["preset"]).lower() not in cam.presets and not str(c["preset"]).isdigit():
            log("CONFIG", f"ATTENZIONE: '{c['name']}' usa il preset '{c['preset']}' non definito in settings.camera.presets")

    beam_cfg = cfg.get("beam", {})
    beam_filter = BeamZoneFilter(beam_cfg) if beam_cfg.get("enabled") else None

    holder = {}
    tracker = SpeakerTracker(cfg, cfg["paths"], cam, beam_provider=lambda: holder["ctrl"].beam_hint_ts(),
                           beam_mover=lambda r: holder["ctrl"].goto_rotation(r),
                           on_locked=lambda: holder["ctrl"].on_tracker_locked())
    ctrl = holder["ctrl"] = Controller(cam, tracker, beam_filter, beam_cfg, cfg["camera"].get("settle_time_s", 2.0), BeamPanMap())

    if beam_filter:
        ATND1061Listener(beam_cfg, ctrl.on_beam_sample).start()

    matcher = CommandMatcher(cmds["commands"], cfg["voice"].get("default_fuzzy_threshold", 80))
    voice = VoiceListener(cfg["paths"]["vosk_model"], cmds.get("wake_word", "piero"), matcher,
                          ctrl.on_voice_command, cfg["voice"]["wake_timeout_s"], cfg["voice"].get("sample_rate", 16000))
    voice.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("MAIN", "chiusura...")
        voice.stop()
        tracker.stop()
        cam.stop()
        M.close()


if __name__ == "__main__":
    main()