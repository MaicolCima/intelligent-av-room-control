# PIERO – Intelligent AV Room Control

Voice-controlled, microphone-aware PTZ camera automation for meeting rooms, lecture halls and event spaces.

Say **"Piero"** followed by a command and the camera reacts: it recalls presets, follows you with face tracking, or automatically turns toward whoever is speaking, using the direction-of-arrival data of a beamforming ceiling microphone.

> Voice commands are in **Italian** by default (Vosk Italian model), but phrases are fully configurable in `voice_commands.json`, and you can swap in any other Vosk language model.

---

## Features

- **Wake word + voice commands**: offline speech recognition with [Vosk](https://alphacephei.com/vosk/); a single recognizer handles both the wake word and the command. Works with "Piero, follow me" in one breath or with a pause in between.
- **Fuzzy command matching**: tolerant to recognition errors and to commands embedded in longer sentences.
- **Camera presets**: recall stored camera positions by voice (`home`, `products`, `speaker`, `audience`, ...).
- **Speaker tracking ("follow me")**: YuNet face detection, CSRT body tracking and YOLOv8n person detection as a fallback, driving the camera with a PID controller (with dead-zone hysteresis) over VISCA.
- **Beamforming microphone integration**: reads direction-of-arrival notifications from an **Audio-Technica ATND1061** and turns the camera toward whoever is talking.
- **Anti "crazy camera" filtering**: zone hysteresis, windowed voting, minimum dwell ratio and a minimum interval between camera moves.
- **Automatic calibration**: learns the mapping *mic rotation → camera pan* from the tracker itself (zero-effort) or via voice commands.
- **Latency metrics**: every run logs timings (speech endpointing, decoding, matching, dispatch, detector times, stream FPS) to CSV, with an offline report tool that produces stats, histograms and CDFs.

---

## How it works

```
                 ┌──────────────┐   "piero ..."   ┌──────────────────┐
   Microphone ──►│ VoiceListener│────────────────►│  CommandMatcher  │
                 │   (Vosk)     │                 │ (fuzzy matching) │
                 └──────────────┘                 └────────┬─────────┘
                                                           │ command
 ┌────────────────┐   samples   ┌──────────────┐           ▼
 │ ATND1061 mic   │────────────►│BeamZoneFilter│──►┌──────────────────┐
 │ (TCP + UDP mc) │             │ (zones/votes)│   │    Controller    │
 └────────────────┘             └──────────────┘   │ IDLE / PRESET /  │
                                                   │ TRACK / SPEAKER  │
 ┌────────────────┐  frames     ┌──────────────┐   └───┬──────────┬───┘
 │ RTSP stream    │────────────►│SpeakerTracker│◄──────┘          │
 └────────────────┘             │ YuNet/CSRT/  │                  │
                                │ YOLO + PID   │                  ▼
                                └──────┬───────┘          ┌──────────────┐
                                       └─────────────────►│ MinrrayVISCA │──► PTZ camera
                                                          │ (VISCA/UDP)  │
                                                          └──────────────┘
```

### Operating modes

| Mode      | Description |
|-----------|-------------|
| `IDLE`    | Camera is stationary. |
| `PRESET`  | Camera is on a fixed shot recalled by voice. |
| `TRACK`   | "Follow me": the camera first turns toward the microphone beam, then the face/body tracker takes over (the beam is ignored while the target is visible). If the target is lost, it falls back to the beam, and finally to the `home` preset. |
| `SPEAKER` | "Follow whoever speaks": the camera is driven by the microphone beam only, with all anti-jitter filters applied. |

---

## Project structure

```
Intelligent-AV-Room-Control/
│
├── main.py                  # Single entry point
├── settings.yaml            # Hardware & tuning parameters
├── voice_commands.json      # Wake word, phrases and actions
├── requirements.txt
├── tests_offline.py         # Offline tests
├── test_atnd1061_beam.py    # Helper to read raw beam data (zone tuning)
│
└── av_control/
    ├── core/                # config, controller, events (logger), metrics, state_store
    ├── voice/               # wakeword (Vosk listener), matcher (fuzzy matching)
    ├── camera/              # visca (Minrray VISCA-over-UDP driver)
    ├── tracking/            # speaker_tracker, detectors, pid, video (RTSP reader)
    └── beam/                # atnd1061 (mic listener), zones (filtering), calibration
```

---

## Requirements

### Hardware

- A PTZ camera with **VISCA over UDP** and an **RTSP** stream (developed with a Minrray camera).
- *(Optional)* an **Audio-Technica ATND1061** beamforming microphone on the same network, for speaker-aware camera control.
- A USB/system microphone for voice commands.

### Software

- Python 3.10+
- Python packages (see `requirements.txt`), typically:
  - `opencv-contrib-python` (the CSRT tracker requires the contrib build)
  - `numpy`
  - `PyYAML`
  - `vosk`
  - `sounddevice`
  - `ultralytics` *(optional, YOLO person fallback)*
  - `matplotlib` *(optional, metrics report plots)*

### Models

Download these and point to them in `settings.yaml`:

| Model | Purpose | Source |
|-------|---------|--------|
| `face_detection_yunet_2023mar.onnx` | Face detection | [OpenCV Zoo – YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) |
| `yolov8n.pt` | Person detection fallback | [Ultralytics](https://github.com/ultralytics/ultralytics) |
| `vosk-model-it-0.22` | Italian speech recognition | [Vosk models](https://alphacephei.com/vosk/models) |

---

## Installation

```bash
git clone https://github.com/<your-username>/Intelligent-AV-Room-Control.git
cd Intelligent-AV-Room-Control

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Then download the models (see above) and edit `settings.yaml`.

---

## Configuration

All hardware and tuning values live in **`settings.yaml`**; all spoken phrases live in **`voice_commands.json`**.

### `settings.yaml` highlights

```yaml
paths:                          # absolute, or relative to the project root
  yunet_model: "av_control/models/face_detection_yunet_2023mar.onnx"
  yolo_model:  "av_control/models/yolov8n.pt"
  vosk_model:  "av_control/models/vosk-model-it-0.22"
  voice_commands_json: "voice_commands.json"

camera:
  ip: "192.168.1.164"
  visca_port: 1259
  rtsp_url: "rtsp://<user>:<password>@192.168.1.164:554/live/av0"
  presets:                      # name -> preset number stored in the camera
    home: 0
    prodotti: 1
    relatore: 2
    platea: 3
  settle_time_s: 2.0            # wait after a preset before looking for faces again

voice:
  wake_timeout_s: 8.0           # seconds to say the command after the wake word
  default_fuzzy_threshold: 80   # 0-100

tracking:
  max_visca_speed: 24
  min_visca_speed: 4
  enable_yolo_fallback: true
  search_timeout_s: 3.0
  search_to_home_timeout_s: 8.0 # target lost for too long -> go back to "home"
  beam_grace_s: 2.5             # target lost this long before listening to the mic again
  center_target_y: 0.30         # keep the face in the upper 30% of the frame

beam:
  enabled: true
  mic_ip: "192.168.1.94"
  tcp_port: 17300
  multicast_group: "239.0.0.100"
  udp_port: 17000
  local_ip: "192.168.1.60"      # this PC's IP on the microphone network
  rotation_offset_deg: 180      # align mic orientation with the room
  window_s: 1.5
  dwell_ratio: 0.6
  min_samples: 5
  hysteresis_deg: 10
  min_switch_interval_s: 4.0
  hint_max_age_s: 5.0
  priority_only: false
  zones:
    - name: prodotti
      rotation: [100, 148]
      preset: prodotti
      priority: true
    - name: relatore
      rotation: [148, 195]
      elevation: [28, 75]
      preset: relatore
      priority: true
    - name: platea
      rotation: [195, 265]
      preset: platea
      priority: true
```

> **Security note:** don't commit real camera credentials or personal absolute paths. Keep a `settings.example.yaml` in the repo and add your real `settings.yaml` to `.gitignore`.

### Tuning the beam zones

Zones are defined in **degrees of microphone rotation** (and optionally elevation). If `min > max`, the zone wraps around 0° (e.g. `[340, 20]`).

1. Run `python test_atnd1061_beam.py`.
2. Speak from each position in the room and note the reported rotation/elevation.
3. Write the ranges in `settings.yaml`.

### Voice commands

Commands are defined in `voice_commands.json`:

```json
{
  "name": "PRESET PLATEA",
  "phrases": ["inquadra la platea", "vai in platea", "telecamera platea"],
  "action": "preset",
  "preset": "platea"
}
```

Available actions:

| Action | Effect |
|--------|--------|
| `track_start` | Start "follow me" (beam first, then face/body tracking). |
| `track_stop` | Stop tracking and halt the camera. |
| `follow_speaker` | Follow whoever is speaking, using the microphone only. |
| `preset` | Recall a camera preset (`"preset": "<name or number>"`). |
| `beam_calibrate` | Store the current *(mic rotation, camera pan)* pair. |
| `beam_clear` | Delete the stored calibration. |

Default Italian phrases (each prefixed by the wake word **"piero"**):

| Command | Example phrases |
|---------|-----------------|
| Follow me | "seguimi", "inizia a seguirmi", "attiva tracking" |
| Stop tracking | "fermati", "smetti di seguirmi", "stop tracking" |
| Follow the speaker | "segui chi parla", "modalita dibattito" |
| Audience preset | "inquadra la platea", "vai in platea" |
| Speaker preset | "inquadra il relatore", "telecamera principale" |
| Products preset | "inquadra i prodotti", "telecamera prodotti" |
| Home preset | "torna alla posizione iniziale", "inquadratura generale" |
| Calibrate | "calibra", "salva posizione" |
| Clear calibration | "cancella calibrazione", "azzera calibrazione" |

At startup, PIERO warns you if a command references a preset that is not defined in `settings.yaml`.

---

## Usage

```bash
python main.py
```

Say *"Piero, seguimi"* (or any phrase from `voice_commands.json`). Press **Ctrl+C** to quit; a latency summary is printed on exit.

### Microphone → camera calibration

The beam gives an angle, the camera needs a pan value, so PIERO learns a linear map between the two:

- **Automatic:** while in *follow me* mode, whenever a single face is centered and still for ≥ 3 s **and** the mic hears someone talking, a calibration sample is saved for free. Samples inconsistent with the current map are discarded.
- **Manual:**
  1. Say *"Piero, seguimi"*, so the camera centers you.
  2. Say *"Piero, calibra"*.
  3. Move to a different spot, let the camera center you, and say *"Piero, calibra"* again.

At least two points spanning ≥ 10° are needed. Points are stored in `beam_calibration.json`, so calibration is done only once. Until calibrated, `follow_speaker` falls back to zone presets.

> Absolute pan movement requires the camera to answer the VISCA *pan/tilt position inquiry* (`81 09 06 12 FF`). If it doesn't, PIERO will tell you in the log.

---

## Metrics & performance analysis

Each run writes `metrics/run_YYYYmmdd_HHMMSS.csv` (override the folder with the `PIERO_METRICS_DIR` environment variable). Recorded metrics include:

| Metric | Meaning |
|--------|---------|
| `voce_endpoint_ms` | Last partial-text update → final Vosk result (end-of-sentence silence) |
| `voce_decode_ms` | Duration of the final `AcceptWaveform` call |
| `matcher_ms` | Fuzzy matcher time |
| `cmd_dispatch_ms` | Controller + VISCA dispatch time |
| `voce_fine_frase_azione_ms` | Total: end of sentence → command executed |
| `yunet_ms`, `csrt_ms`, `yolo_ms` | Per-detector inference times |
| `loop_ms` | Tracker loop time |
| `stream_fps` | Real FPS of the RTSP stream |
| `track_err` | Tracking error (`ex`, `ey`) and issued pan/tilt speeds |

Generate statistics and plots (histogram + CDF per metric):

```bash
python -m av_control.core.metrics metrics/run_XXXX.csv
```

---

## Troubleshooting

| Problem | Things to check |
|---------|-----------------|
| `YuNet non trovato` / models not loading | Check the `paths` in `settings.yaml`. |
| No beam data | Verify `mic_ip`, `local_ip` (must be the PC's IP on the mic's network), firewall rules for UDP `17000` / TCP `17300`, and multicast support on your switch. |
| Camera doesn't move to an absolute position | The camera may not answer the VISCA position inquiry; use presets instead. |
| `cv2.TrackerCSRT_create` missing | Install `opencv-contrib-python` (and uninstall plain `opencv-python`). |
| Camera jitters between zones | Increase `hysteresis_deg`, `min_switch_interval_s`, or `dwell_ratio`. |
| Commands not recognized | Lower `default_fuzzy_threshold`, add more phrase variants, or use a larger Vosk model. |
| RTSP stream freezes | The reader auto-reconnects after 8 s of stall; check network/camera load. |

---

## Roadmap ideas

- Multi-language voice command sets
- Web dashboard for live state (`state.json`) and metrics
- Support for additional PTZ camera brands
- Multi-speaker / multi-camera scenarios

---

## License

Add your license here (e.g. MIT) and include a `LICENSE` file in the repository.

## Acknowledgements

- [Vosk](https://alphacephei.com/vosk/) – offline speech recognition
- [OpenCV](https://opencv.org/) & [OpenCV Zoo](https://github.com/opencv/opencv_zoo) – YuNet face detection, CSRT tracker
- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) – person detection