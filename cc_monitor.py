from threading import Thread
import os
from collections import deque
import time

from flask import Flask, send_from_directory
from flask_socketio import SocketIO
import rtmidi

# SETTINGS
MIDI_CLOCK_MESSAGE = 0xF8
MIDI_CC_MESSAGE = 0xB0
MIDI_START_MESSAGE = 0xFA
MIDI_CONTINUE_MESSAGE = 0xFB
MIDI_STOP_MESSAGE = 0xFC
WEBSOCKET_INTERVAL_SECONDS = 0.1

# SETUP
midi_in = rtmidi.MidiIn(rtapi=2)
ports = midi_in.get_ports()
msg_buffer = deque(maxlen=20000)

# Prefer MODEP MIDI output ports if present
preferred = [
    p for p in ports
    if "pisound" in p
]

# # Otherwise fall back to Pisound hardware ports
# if not preferred:
#     preferred = [p for p in ports if p.startswith("system:midi_capture")]

if not preferred:
    raise RuntimeError("No usable JACK MIDI ports found")

index = ports.index(preferred[0])
midi_in.open_port(index)
midi_in.ignore_types(sysex=False, timing=False)
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
            message = msg[0]
            status = message[0]

            if status == MIDI_CLOCK_MESSAGE or status == MIDI_START_MESSAGE or status == MIDI_STOP_MESSAGE or status == MIDI_CONTINUE_MESSAGE or (status & 0xF0) == MIDI_CC_MESSAGE: #bit mask to include all CC channels
                msg_buffer.append(message) 
            #ignore all other midi messages

            msg = midi_in.get_message()

#PROCESSING THREAD (batched websocket messages)
def processing_thread():
    while True:
        time.sleep(WEBSOCKET_INTERVAL_SECONDS)
        #prioritized popping of elements off of queues, never drop a tick.
        if msg_buffer:
            msg_list = [msg_buffer.popleft() for _ in range(len(msg_buffer))]    
            socketio.emit("update", {"midi_buffer": msg_list})

if __name__ == "__main__":
    Thread(target=processing_thread, daemon=True).start()
    Thread(target=midi_thread, daemon=True).start()
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
