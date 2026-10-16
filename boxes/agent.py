import base64
import json
import ssl
import time
import urllib.error
import urllib.request

from .model import BoxError
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
    if not container or not container["State"]["Running"] or not port(container):
        raise BoxError("The instance has no running HTTPS listener.")
    address = config["bind"] if config["bind"] != "0.0.0.0" else "127.0.0.1"
    url = f"https://{address}:{port(container)}/pelorus/api/{endpoint}"
    auth = base64.b64encode(f"{config['user']}:{config['password']}".encode()).decode()
    headers = {"Authorization": "Basic " + auth, "Content-Type": "application/json"}
    data = None if payload is None else json.dumps(payload).encode()
    context = ssl.create_default_context() if config["tls_verify"] else ssl._create_unverified_context()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    try:
        with opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=45) as response:
            result = json.load(response)
    except (urllib.error.URLError, ValueError, TimeoutError) as error:
        raise BoxError(f"Pelorus request failed. {error}") from error
    if isinstance(result, dict) and (result.get("error") or result.get("result") in {"error", "failed"}):
        raise BoxError(f"Pelorus rejected the action. {result}")
    return result


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
