from threading import Thread
from queue import Queue
import os
import time

from flask import Flask, send_from_directory
from flask_socketio import SocketIO
import rtmidi

# SETTINGS
TICKS_PER_BEAT = 24
MIDI_CLOCK_MESSAGE = 0xF8
MIDI_CC_MESSAGE = 0xB0
MIDI_START_MESSAGE = 0xFA
MIDI_CONTINUE_MESSAGE = 0xFB
MIDI_STOP_MESSAGE = 0xFC

# STATE
tick_count = 0 #current MIDI clock tick

# SETUP
midi_in = rtmidi.MidiIn(rtapi=3)
ports = midi_in.get_ports()
midi_queue = Queue()

# Prefer MODEP MIDI output ports if present
preferred = [
    p for p in ports
    if "mod-midi-merger:out" in p or "mod-midi-broadcaster:out" in p
]

# Otherwise fall back to Pisound hardware ports
if not preferred:
    preferred = [p for p in ports if p.startswith("system:midi_capture")]

if not preferred:
    raise RuntimeError("No usable JACK MIDI ports found")

index = ports.index(preferred[0])
midi_in.open_port(index)
print("Opened JACK port:", preferred[0])

# WEB SERVER
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route("/")
def root():
    return send_from_directory(os.path.join(os.getcwd(), "static"), "index.html")

@app.route("/status")
def status():
    return {"midi_port_open": midi_in.is_port_open()}

#MIDI LISTENER THREAD (fast, to avoid bottlenecks on buffer)
def midi_thread():
    while True:
        msg = midi_in.get_message()
        while msg:
            midi_queue.put(msg)
            msg = midi_in.get_message()
        time.sleep(0.001)

#PROCESSING THREAD (slow websocket)
def processing_thread():
    global tick_count

    while True:
        msg = midi_queue.get()
        if not msg:
            continue
        message, delta = msg
        status = message[0]
        print("msg received")

        if status == MIDI_START_MESSAGE:
            tick_count = 0
            socketio.emit("start")
            continue

        if status == MIDI_STOP_MESSAGE:
            tick_count = 0
            socketio.emit("stop")
            continue

        if status == MIDI_CONTINUE_MESSAGE:
            socketio.emit("continue")
            continue

        if status == MIDI_CLOCK_MESSAGE:
            tick_count += 1
            if tick_count >= TICKS_PER_BEAT:
                tick_count = 0
            socketio.emit("update_tick", {"tick": tick_count})
            continue

        if (status & 0xF0) == MIDI_CC_MESSAGE: #bit mask to include all CC channels
            cc = message[1]
            val = message[2]
            socketio.emit("update_cc", {
                "cc": cc,
                "val": val
            })
            continue

if __name__ == "__main__":
    Thread(target=processing_thread, daemon=True).start()
    Thread(target=midi_thread, daemon=True).start()
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
