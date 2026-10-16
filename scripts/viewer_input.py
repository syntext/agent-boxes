#!/usr/bin/env python3
"""Send the exact frames a Selkies web client sends, over the box's websocket.

Used to prove the tap reads real viewer input without a browser in the loop.
"""
import base64
import os
import socket
import ssl
import sys
import time

host = "127.0.0.1"
port = int(sys.argv[1]) if len(sys.argv) > 1 else 3001
user, password = "box", "boxbox"
if len(sys.argv) > 3:
    user, password = sys.argv[2], sys.argv[3]

plain = socket.create_connection((host, port), 10)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE
tls = context.wrap_socket(plain, server_hostname=host)
key = base64.b64encode(os.urandom(16)).decode()
auth = base64.b64encode(f"{user}:{password}".encode()).decode()
tls.sendall((f"GET /api/websockets HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
             f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
             f"Authorization: Basic {auth}\r\n\r\n").encode())
time.sleep(0.6)
try:
    tls.recv(16384)
except OSError:
    pass
print("handshake", tls.version() if hasattr(tls, "version") else "tls")


def frame(text):
    body = text.encode()
    mask = os.urandom(4)
    return bytes([0x81, 0x80 | len(body)]) + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(body))


messages = [
    "m,300,400,0,0,1",          # move
    "m,300,400,1,0,2",          # left button down
    "m,640,480,1,0,3",          # drag
    "m,640,480,0,0,4",          # release at the drag end
    "m,640,480,8,3,5",          # wheel up, three notches
    "m,640,480,16,1,6",         # wheel down, one notch
    "m,640,480,4,0,7",          # right button down
    "m,640,480,0,0,8",          # release
    "kd,104", "ku,104",         # h
    "kd,105", "ku,105",         # i
    "kd,65293", "ku,65293",     # Return
    "kd,65507", "kd,108", "ku,108", "ku,65507",   # Ctrl+L
]
for message in messages:
    tls.sendall(frame(message))
    time.sleep(0.2)
time.sleep(0.5)
tls.close()
print("sent", len(messages))
