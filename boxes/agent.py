import base64
import contextlib
import http.client
import json
import ssl
import time
import urllib.request

from .model import BoxError, scheme
from .runtime import inspect, port


def wait_ready(instance, config, timeout=180):
    if not 1 <= timeout <= 900:
        raise BoxError("Readiness timeout must be between 1 and 900 seconds.")
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            result = request(instance, config, "state")
            if isinstance(result, dict) and "state" in result:
                return
        except BoxError as error:
            last = error
        time.sleep(1)
    raise BoxError(f"Desktop API did not become ready within {timeout} seconds. Read box logs. {last or ''}")


def request(instance, config, endpoint, payload=None):
    container = inspect(instance)
    published = port(container, config)
    if not container or not container["State"]["Running"] or not published:
        raise BoxError("The instance has no running viewer listener.")
    address = config["bind"] if config["bind"] != "0.0.0.0" else "127.0.0.1"
    https = scheme(config) == "https"
    url = f"{'https' if https else 'http'}://{address}:{published}/pelorus/api/{endpoint}"
    auth = base64.b64encode(f"{config['user']}:{config['password']}".encode()).decode()
    headers = {"Authorization": "Basic " + auth, "Content-Type": "application/json"}
    data = None if payload is None else json.dumps(payload).encode()
    handlers = [urllib.request.ProxyHandler({})]
    if https:
        context = ssl.create_default_context() if config["tls_verify"] else ssl._create_unverified_context()
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=45) as response:
            result = json.load(response)
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise BoxError(f"Pelorus request failed. {error}") from error
    if isinstance(result, dict) and (result.get("error") or result.get("result") in {"error", "failed"}):
        raise BoxError(f"Pelorus rejected the action. {result}")
    return result


def drag(instance, config, start, end, steps=10, interval=0.02, settle=0.15):
    """Hold the left button and move between two points, then release.

    The computer-use backend has no working one-shot drag for drag-and-drop
    targets: Chromium starts the drag and cancels it before the target sees it.
    Stepped moves with a pause at the destination make the target register the
    pointer before the release.
    """
    if not 1 <= steps <= 200:
        raise BoxError("Drag steps must be between 1 and 200.")
    if not 0 <= interval <= 1:
        raise BoxError("Drag interval must be between 0 and 1 second.")
    if not 0 <= settle <= 5:
        raise BoxError("Drag settle must be between 0 and 5 seconds.")
    (x1, y1), (x2, y2) = start, end
    request(instance, config, "desktop/control", {"action": "mouse_move", "coordinate": [x1, y1]})
    try:
        request(instance, config, "desktop/control", {"action": "left_mouse_down"})
        for step in range(1, steps + 1):
            point = [round(x1 + (x2 - x1) * step / steps), round(y1 + (y2 - y1) * step / steps)]
            request(instance, config, "desktop/control", {"action": "mouse_move", "coordinate": point})
            time.sleep(interval)
        time.sleep(settle)
    except BaseException:
        with contextlib.suppress(BoxError):
            request(instance, config, "desktop/control", {"action": "left_mouse_up"})
        raise
    return request(instance, config, "desktop/control", {"action": "left_mouse_up"})


def screenshot(instance, config, output):
    result = request(instance, config, "desktop/screenshot")
    try:
        data = base64.b64decode(result["data"], validate=True)
    except (ValueError, KeyError) as error:
        raise BoxError("Pelorus did not return a base64 screenshot.") from error
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise BoxError("Pelorus returned an invalid PNG.")
    if output:
        output.write_bytes(data)
        return {"file": str(output.resolve()), "bytes": len(data)}
    return result
