#!/usr/bin/env python3
"""Send the exact frames a Selkies web client sends, over the box's websocket.

Used to prove the tap reads real viewer input without a browser in the loop.
"""
import argparse
import base64
import json
import os
import socket
import ssl
import sys
import time

def connect(transport, port, user, password):
    host = "127.0.0.1"
    connection = socket.create_connection((host, port), 10)
    try:
        if transport == "https":
            # The upstream box serves a self-signed certificate on loopback.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            connection = context.wrap_socket(connection, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        connection.sendall((f"GET /api/websockets HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                            f"Authorization: Basic {auth}\r\n\r\n").encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = connection.recv(4096)
            if not chunk or len(response) + len(chunk) > 16384:
                raise RuntimeError("Incomplete websocket upgrade response")
            response += chunk
        status = response.split(b"\r\n", 1)[0].split()
        if len(status) < 2 or status[0] != b"HTTP/1.1" or status[1] != b"101":
            raise RuntimeError("Viewer refused the websocket upgrade")
        return connection
    except BaseException:
        connection.close()
        raise


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
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("https", "http"), default="https")
    parser.add_argument("--port", type=int)
    arguments = parser.parse_args()
    credentials = json.load(sys.stdin)
    port = arguments.port or (3001 if arguments.transport == "https" else 3000)
    with connect(arguments.transport, port, credentials["user"], credentials["password"]) as connection:
        print("handshake", arguments.transport)
        for message in messages:
            connection.sendall(frame(message))
            time.sleep(0.2)
        time.sleep(0.5)
    print("sent", len(messages))


if __name__ == "__main__":
    raise SystemExit(main())
