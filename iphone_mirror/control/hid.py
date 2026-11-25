"""Zero-app iPhone control over USB via Apple's built-in CoreDevice HID services.

On iOS/iPadOS 27+, Developer Mode + Developer Disk Image exposes RemoteXPC HID
(`com.apple.coredevice.hid.universalhidservice` + `hid.indigo`) gated by an active
`DisplayService` media stream (Apple rejects `startmediastream` with code 9021 on
iOS/iPadOS 26.x and earlier), allowing touch control with no third-party app
sideloaded on the device.

Two interchangeable paths are provided behind the same client interface:
- `StreamServerHidClient`: talks to `pymobiledevice3` `ScreenStreamServer` when
  the USB HEVC display stream (`usbvideo`) is already holding an RSD tunnel and
  authenticated DisplayService stream.
- `CoreDeviceHidClient`: opens its own `PreferredRsdTunnel`, holds open the
  `DisplayService` media-stream auth gate (`dtuhidd` drops touch reports
  unless a media stream is active), and sends real-time touch, hardware
  buttons, virtual HID keyboard input, orientation rotation, and clipboard sync.
"""
import asyncio
import http.client
import json
import logging
import threading
import time

from .usb import (
    MSG_DEV_MODE,
    UsbError,
    com_mta,
    developer_mode_enabled,
    failure_text,
    list_devices,
    parse_version,
    pmd3,
    usbmuxd_reachable,
)
from .wda import WDAError

log = logging.getLogger(__name__)


class NativeHidUnavailable(Exception):
    """Raised when zero-app CoreDevice HID cannot be used (e.g. iOS < 27 or no USB iPhone)."""

    def __init__(self, message: str = "", devices=None):
        super().__init__(message)
        self.devices = devices


def _primary_display_size(info) -> tuple[float, float] | None:
    displays = info if isinstance(info, list) else (info or {}).get("displays") or []
    if not displays or not isinstance(displays[0], dict):
        return None
    size = (displays[0].get("currentMode") or {}).get("size") or ()
    if len(size) >= 2 and float(size[0]) > 0 and float(size[1]) > 0:
        return float(size[0]), float(size[1])
    return None


def _hid_coord(val: float, span: float) -> int:
    frac = 0.0 if val <= 0 else 1.0 if val >= span else float(val) / max(1.0, float(span))
    return max(0, min(65535, int(round(frac * 65535))))


def _stream_server_alive(port: int = 8091) -> bool:
    conn = None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.35)
        conn.request("GET", "/clipboard")
        resp = conn.getresponse()
        resp.read()
        return resp.status == 200
    except OSError:
        return False
    except http.client.HTTPException:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _button_map(name: str) -> str:
    return {
        "volumeUp": "volume-up",
        "volumeDown": "volume-down",
        "home": "home",
        "lock": "lock",
        "mute": "mute",
        "siri": "siri",
    }.get(name, name)


def _named_button_hid(name: str) -> tuple[int, int, float]:
    table = {
        "home": (0x0C, 0x40, 0.05),
        "lock": (0x0C, 0x30, 0.5),
        "volumeUp": (0x0C, 0xE9, 0.05),
        "volume-up": (0x0C, 0xE9, 0.05),
        "volumeDown": (0x0C, 0xEA, 0.05),
        "volume-down": (0x0C, 0xEA, 0.05),
        "mute": (0x0C, 0xE2, 0.05),
        "siri": (0x0C, 0xCF, 1.0),
    }
    if name not in table:
        raise WDAError(f"Unsupported hardware button: {name!r}")
    return table[name]


class StreamServerHidClient:
    """Native HID client talking to an active ScreenStreamServer HTTP port."""

    live_touch = True
    backend_name = "USB Cable"

    def __init__(self, port: int = 8091):
        self.port = port
        self.size = (390.0, 844.0)
        self._conn = None
        self._lock = threading.Lock()
        self._closed = False

    def new_session(self):
        return f"stream-hid-{self.port}"

    def set_aspect(self, aspect: float | None):
        if aspect and (self.size[0] > self.size[1]) != (aspect > 1):
            self.size = (self.size[1], self.size[0])

    def window_size(self, refresh=False):
        _ = refresh
        return self.size

    def is_alive(self) -> bool:
        return not self._closed and _stream_server_alive(self.port)

    def close(self):
        self._closed = True
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def _http(self, method: str, path: str, payload=None, timeout: float = 2.0):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        with self._lock:
            if self._closed:
                raise WDAError("HID client closed")
            last_err = None
            for _attempt in range(2):
                try:
                    if self._conn is None:
                        self._conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
                    self._conn.timeout = timeout
                    self._conn.request(method, path, body=body, headers=headers)
                    resp = self._conn.getresponse()
                    raw = resp.read()
                    if resp.status >= 400:
                        raise WDAError(f"{method} {path} -> HTTP {resp.status}: {raw.decode('utf-8', 'replace')}", resp.status)
                    return raw
                except (http.client.HTTPException, OSError) as exc:
                    last_err = exc
                    if self._conn is not None:
                        try:
                            self._conn.close()
                        except Exception:
                            pass
                        self._conn = None
            raise WDAError(f"USB stream HID error: {last_err}")

    def touch_contact(self, x: float, y: float):
        w, h = self.size
        self._http("POST", "/touch", {"type": "contact", "x": _hid_coord(x, w), "y": _hid_coord(y, h)})

    def touch_release(self, x: float, y: float):
        w, h = self.size
        self._http("POST", "/touch", {"type": "release", "x": _hid_coord(x, w), "y": _hid_coord(y, h)})

    def tap(self, x: float, y: float, hold_ms: int = 40):
        w, h = self.size
        hx, hy = _hid_coord(x, w), _hid_coord(y, h)
        if hold_ms <= 60:
            self._http("POST", "/touch", {"type": "tap", "x": hx, "y": hy})
        else:
            self._http("POST", "/touch", {"type": "contact", "x": hx, "y": hy})
            time.sleep(hold_ms / 1000.0)
            self._http("POST", "/touch", {"type": "release", "x": hx, "y": hy})

    def double_tap(self, x: float, y: float, hold_ms: int = 40, gap_ms: int = 80):
        self.tap(x, y, hold_ms)
        time.sleep(gap_ms / 1000.0)
        self.tap(x, y, hold_ms)

    def long_press(self, x: float, y: float, hold_ms: int = 700):
        self.tap(x, y, hold_ms=hold_ms)

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 250, hold_end_ms: int = 0):
        steps = max(4, min(40, int(round(max(20, duration_ms) / 16.0))))
        w, h = self.size
        hx1, hy1 = _hid_coord(x1, w), _hid_coord(y1, h)
        hx2, hy2 = _hid_coord(x2, w), _hid_coord(y2, h)
        dt = max(0.02, duration_ms / 1000.0) / steps
        for i in range(steps + 1):
            t = i / steps
            self._http("POST", "/touch", {
                "type": "contact",
                "x": round(hx1 + (hx2 - hx1) * t),
                "y": round(hy1 + (hy2 - hy1) * t),
            })
            if i < steps:
                time.sleep(dt)
        if hold_end_ms:
            time.sleep(hold_end_ms / 1000.0)
        self._http("POST", "/touch", {"type": "release", "x": hx2, "y": hy2})

    def home(self):
        self._http("POST", "/button", {"name": "home", "state": "press"})

    def app_switcher(self):
        w, h = self.size
        self.swipe(w / 2.0, h * 0.99, w / 2.0, h * 0.62, duration_ms=280, hold_end_ms=450)

    def press_button(self, name: str):
        self._http("POST", "/button", {"name": _button_map(name), "state": "press"}, timeout=5.0)

    def lock(self):
        self._http("POST", "/button", {"name": "lock", "state": "press"}, timeout=5.0)

    def unlock(self):
        w, h = self.size
        self.home()
        time.sleep(0.25)
        self.swipe(w / 2.0, h * 0.97, w / 2.0, h * 0.35, duration_ms=220)

    def shake(self):
        log.info("shake is unavailable over native USB HID (requires WDA)")

    def get_pasteboard(self) -> str:
        raw = self._http("GET", "/clipboard", timeout=5.0)
        try:
            data = json.loads(raw)
            return str(data.get("text") or "")
        except Exception:
            return ""

    def set_pasteboard(self, text: str):
        self._http("POST", "/clipboard", {"text": text}, timeout=5.0)

    def rotate(self, direction: str = "left"):
        self._http("POST", "/rotate", {"direction": direction}, timeout=5.0)

    def type_text(self, text: str):
        if not text:
            return
        from pymobiledevice3.remote.core_device.hid_service import (
            ASCII_TO_HID,
            KEY_BACKSPACE,
            KEY_ENTER,
            KEY_LEFT_GUI,
            KEY_LEFT_SHIFT,
            KEY_TAB,
            KEY_V,
        )

        non_ascii: list[str] = []

        def flush_non_ascii():
            if not non_ascii:
                return
            chunk = "".join(non_ascii)
            non_ascii.clear()
            self.set_pasteboard(chunk)
            self._http("POST", "/key", {"usages": [KEY_LEFT_GUI, KEY_V]})
            time.sleep(0.03)
            self._http("POST", "/key", {"usages": []})

        for ch in text:
            if ch == "\b":
                flush_non_ascii()
                self._send_key_usage(KEY_BACKSPACE, False)
            elif ch == "\n":
                flush_non_ascii()
                self._send_key_usage(KEY_ENTER, False)
            elif ch == "\t":
                flush_non_ascii()
                self._send_key_usage(KEY_TAB, False)
            elif ch in ASCII_TO_HID:
                flush_non_ascii()
                usage, shifted = ASCII_TO_HID[ch]
                self._send_key_usage(usage, shifted)
            else:
                non_ascii.append(ch)
        flush_non_ascii()

    def _send_key_usage(self, usage: int, shifted: bool):
        from pymobiledevice3.remote.core_device.hid_service import KEY_LEFT_SHIFT

        if shifted:
            self._http("POST", "/key", {"usages": [KEY_LEFT_SHIFT]})
            time.sleep(0.02)
            self._http("POST", "/key", {"usages": [KEY_LEFT_SHIFT, usage]})
        else:
            self._http("POST", "/key", {"usages": [usage]})
        time.sleep(0.025)
        self._http("POST", "/key", {"usages": []})
        time.sleep(0.015)


class CoreDeviceHidClient:
    """Zero-app USB HID client backed directly by Apple's CoreDevice services."""

    live_touch = True
    backend_name = "Native USB"

    def __init__(self, udid: str, cancel: threading.Event | None = None):
        self.udid = udid
        self._cancel = cancel
        self.size = (390.0, 844.0)
        self._closed = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._open_error: BaseException | None = None

        self._rsd_cm = None
        self._rsd = None
        self._display = None
        self._transport = None
        self._drain_task = None
        self._uhs = None
        self._indigo = None
        self._pasteboard = None
        self._orientation = None
        self._kb_service_id: int | None = None

    def open(self, timeout: float = 30.0):
        self._ready.clear()
        self._open_error = None
        self._thread = threading.Thread(target=self._run, name="coredevice-hid", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._ready.wait(timeout=0.15):
            if self._cancel is not None and self._cancel.is_set():
                self.close()
                raise NativeHidUnavailable("cancelled")
            if self._closed.is_set() or time.monotonic() >= deadline:
                break
        if self._open_error is not None:
            err = self._open_error
            self.close()
            raise err
        if not self._ready.is_set():
            self.close()
            raise UsbError("Timed out opening CoreDevice USB control.")

    def new_session(self):
        return f"coredevice-hid-{self.udid}"

    def set_aspect(self, aspect: float | None):
        if aspect and (self.size[0] > self.size[1]) != (aspect > 1):
            self.size = (self.size[1], self.size[0])

    def window_size(self, refresh=False):
        _ = refresh
        return self.size

    def is_alive(self) -> bool:
        return (
            not self._closed.is_set()
            and self._thread is not None
            and self._thread.is_alive()
            and self._uhs is not None
        )

    def _run(self):
        com_mta()
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._setup())
            self._ready.set()
            loop.run_forever()
        except BaseException as exc:
            self._open_error = exc
            self._ready.set()
        finally:
            try:
                loop.run_until_complete(self._teardown())
            except Exception:
                log.debug("coredevice hid teardown error", exc_info=True)
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            asyncio.set_event_loop(None)
            loop.close()

    async def _setup(self):
        from pymobiledevice3.exceptions import CoreDeviceError, DeviceVersionNotSupportedError
        from pymobiledevice3.remote.core_device.device_info import DeviceInfoService
        from pymobiledevice3.remote.core_device.display_service import DisplayService, is_media_in_use_error
        from pymobiledevice3.remote.core_device.hid_service import (
            TOUCH_AUTH_SETTLE_SECONDS,
            IndigoHIDService,
            UniversalHIDServiceService,
        )
        from pymobiledevice3.remote.core_device.orientation_service import OrientationService
        from pymobiledevice3.remote.core_device.pasteboard_service import PasteboardService
        from pymobiledevice3.remote.core_device.screen_stream import open_media_receiver
        from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel

        rsd_cm = PreferredRsdTunnel(serial=self.udid, autopair=True)
        rsd = await rsd_cm.__aenter__()
        self._rsd_cm = rsd_cm
        self._rsd = rsd

        services = (getattr(rsd, "peer_info", None) or {}).get("Services") or {}
        if UniversalHIDServiceService.SERVICE_NAME not in services or DisplayService.SERVICE_NAME not in services:
            raise NativeHidUnavailable("iOS/iPadOS 27+ CoreDevice HID services are unavailable on this device.")

        try:
            async with DeviceInfoService(rsd) as info:
                mode = _primary_display_size(await info.get_display_info())
            if mode is not None:
                short = min(mode[0], mode[1])
                scale = 390.0 / short if short > 0 else 1.0
                self.size = (round(mode[0] * scale, 1), round(mode[1] * scale, 1))
        except Exception:
            log.debug("could not query CoreDevice display size", exc_info=True)

        display = DisplayService(rsd)
        await display.__aenter__()
        self._display = display

        transport, receiver_ip = open_media_receiver(display, (1024 * 1024,))
        self._transport = transport
        sender_ip = rsd.service.address[0]

        async def _drain():
            try:
                while True:
                    await transport.recv()
            except (asyncio.CancelledError, OSError):
                pass

        self._drain_task = asyncio.create_task(_drain(), name="hid-auth-drain")

        try:
            await asyncio.wait_for(
                display.start_video_stream(
                    receiver_ip=receiver_ip,
                    receiver_port=transport.port,
                    sender_ip=sender_ip,
                    display_id=1,
                ),
                timeout=12.0,
            )
        except DeviceVersionNotSupportedError as exc:
            raise NativeHidUnavailable("Zero-app USB touch control requires iOS/iPadOS 27.0 or later on this device.") from exc
        except CoreDeviceError as exc:
            if is_media_in_use_error(exc):
                raise UsbError("Quit Camera or Voice Memos on the iPhone, then enable control again.") from None
            if getattr(exc, "code", None) == 9021:
                raise NativeHidUnavailable(
                    "Zero-app USB touch control requires iOS/iPadOS 27.0 or later on this device."
                ) from exc
            raise NativeHidUnavailable(f"CoreDevice display stream error: {exc}") from exc

        await asyncio.sleep(max(0.6, TOUCH_AUTH_SETTLE_SECONDS))

        uhs = UniversalHIDServiceService(rsd)
        await uhs.__aenter__()
        self._uhs = uhs

        if IndigoHIDService.SERVICE_NAME in services:
            try:
                indigo = IndigoHIDService(rsd)
                await indigo.__aenter__()
                self._indigo = indigo
            except Exception:
                log.debug("IndigoHIDService unavailable", exc_info=True)

        if PasteboardService.SERVICE_NAME in services:
            try:
                pb = PasteboardService(rsd)
                await pb.__aenter__()
                self._pasteboard = pb
            except Exception:
                log.debug("PasteboardService unavailable", exc_info=True)

        if OrientationService.SERVICE_NAME in services:
            try:
                orient = OrientationService(rsd)
                await orient.__aenter__()
                self._orientation = orient
            except Exception:
                log.debug("OrientationService unavailable", exc_info=True)

        log.info("native USB CoreDevice HID ready (%s, %sx%s pt)", self.udid, self.size[0], self.size[1])

    async def _teardown(self):
        for attr in ("_orientation", "_pasteboard", "_indigo", "_uhs"):
            svc = getattr(self, attr, None)
            setattr(self, attr, None)
            if svc is not None:
                try:
                    await asyncio.wait_for(svc.__aexit__(None, None, None), timeout=2.0)
                except Exception:
                    pass
        if self._drain_task is not None:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except (asyncio.CancelledError, Exception):
                pass
            self._drain_task = None
        if self._display is not None:
            try:
                await asyncio.wait_for(self._display.stop_media_stream(stop_all=True), timeout=3.0)
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._display.__aexit__(None, None, None), timeout=2.0)
            except Exception:
                pass
            self._display = None
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
        if self._rsd_cm is not None:
            try:
                await asyncio.wait_for(self._rsd_cm.__aexit__(None, None, None), timeout=3.0)
            except Exception:
                pass
            self._rsd_cm = None
            self._rsd = None

    def _submit(self, coro, timeout: float = 10.0):
        if self._closed.is_set() or self._loop is None or not self._loop.is_running():
            raise WDAError("USB control session closed")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout)
        except Exception as exc:
            if isinstance(exc, WDAError):
                raise
            raise WDAError(f"USB HID command failed: {exc}") from exc

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        loop = self._loop
        if loop is not None and loop.is_running():
            async def _stop():
                try:
                    await self._teardown()
                finally:
                    loop.stop()

            try:
                asyncio.run_coroutine_threadsafe(_stop(), loop).result(timeout=5.0)
            except Exception:
                try:
                    loop.call_soon_threadsafe(loop.stop)
                except Exception:
                    pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=6.0)

    def touch_contact(self, x: float, y: float):
        from pymobiledevice3.remote.core_device.hid_service import TOUCHSCREEN_STATE_CONTACT

        w, h = self.size
        hx, hy = _hid_coord(x, w), _hid_coord(y, h)
        self._submit(self._uhs.send_touchscreen(TOUCHSCREEN_STATE_CONTACT, hx, hy))

    def touch_release(self, x: float, y: float):
        from pymobiledevice3.remote.core_device.hid_service import TOUCHSCREEN_STATE_RELEASE

        w, h = self.size
        hx, hy = _hid_coord(x, w), _hid_coord(y, h)
        self._submit(self._uhs.send_touchscreen(TOUCHSCREEN_STATE_RELEASE, hx, hy))

    def tap(self, x: float, y: float, hold_ms: int = 40):
        from pymobiledevice3.remote.core_device.hid_service import TOUCHSCREEN_STATE_CONTACT, TOUCHSCREEN_STATE_RELEASE

        w, h = self.size
        hx, hy = _hid_coord(x, w), _hid_coord(y, h)

        async def _op():
            await self._uhs.send_touchscreen(TOUCHSCREEN_STATE_CONTACT, hx, hy)
            await asyncio.sleep(max(0.02, hold_ms / 1000.0))
            await self._uhs.send_touchscreen(TOUCHSCREEN_STATE_RELEASE, hx, hy)

        self._submit(_op(), timeout=5.0 + hold_ms / 1000.0)

    def double_tap(self, x: float, y: float, hold_ms: int = 40, gap_ms: int = 80):
        from pymobiledevice3.remote.core_device.hid_service import TOUCHSCREEN_STATE_CONTACT, TOUCHSCREEN_STATE_RELEASE

        w, h = self.size
        hx, hy = _hid_coord(x, w), _hid_coord(y, h)

        async def _op():
            for idx in range(2):
                await self._uhs.send_touchscreen(TOUCHSCREEN_STATE_CONTACT, hx, hy)
                await asyncio.sleep(max(0.02, hold_ms / 1000.0))
                await self._uhs.send_touchscreen(TOUCHSCREEN_STATE_RELEASE, hx, hy)
                if idx == 0:
                    await asyncio.sleep(gap_ms / 1000.0)

        self._submit(_op())

    def long_press(self, x: float, y: float, hold_ms: int = 700):
        self.tap(x, y, hold_ms=hold_ms)

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 250, hold_end_ms: int = 0):
        from pymobiledevice3.remote.core_device.hid_service import TOUCHSCREEN_STATE_CONTACT, TOUCHSCREEN_STATE_RELEASE

        w, h = self.size
        hx1, hy1 = _hid_coord(x1, w), _hid_coord(y1, h)
        hx2, hy2 = _hid_coord(x2, w), _hid_coord(y2, h)
        steps = max(4, min(40, int(round(max(20, duration_ms) / 16.0))))
        dt = max(0.02, duration_ms / 1000.0) / steps

        async def _op():
            for i in range(steps + 1):
                t = i / steps
                await self._uhs.send_touchscreen(
                    TOUCHSCREEN_STATE_CONTACT,
                    round(hx1 + (hx2 - hx1) * t),
                    round(hy1 + (hy2 - hy1) * t),
                )
                if i < steps:
                    await asyncio.sleep(dt)
            if hold_end_ms:
                await asyncio.sleep(hold_end_ms / 1000.0)
            await self._uhs.send_touchscreen(TOUCHSCREEN_STATE_RELEASE, hx2, hy2)

        self._submit(_op(), timeout=10.0 + (duration_ms + hold_end_ms) / 1000.0)

    def press_button(self, name: str):
        if self._indigo is None:
            raise WDAError("Hardware buttons unavailable on this CoreDevice connection")
        from pymobiledevice3.remote.core_device.hid_service import HID_BUTTON_STATE_DOWN, HID_BUTTON_STATE_UP

        page, usage, hold_s = _named_button_hid(name)

        async def _op():
            await self._indigo.send_button(page, usage, HID_BUTTON_STATE_DOWN)
            await asyncio.sleep(hold_s)
            await self._indigo.send_button(page, usage, HID_BUTTON_STATE_UP)

        self._submit(_op())

    def home(self):
        self.press_button("home")

    def app_switcher(self):
        w, h = self.size
        self.swipe(w / 2.0, h * 0.99, w / 2.0, h * 0.62, duration_ms=280, hold_end_ms=450)

    def lock(self):
        self.press_button("lock")

    def unlock(self):
        w, h = self.size
        if self._indigo is not None:
            self.home()
            time.sleep(0.25)
        self.swipe(w / 2.0, h * 0.97, w / 2.0, h * 0.35, duration_ms=220)

    def shake(self):
        log.info("shake is unavailable over native USB HID (requires WDA)")

    def get_pasteboard(self) -> str:
        if self._pasteboard is None:
            raise WDAError("CoreDevice PasteboardService is unavailable on this device")
        return self._submit(self._pasteboard.get_text(), timeout=15.0) or ""

    def set_pasteboard(self, text: str):
        if self._pasteboard is None:
            raise WDAError("CoreDevice PasteboardService is unavailable on this device")
        self._submit(self._pasteboard.set_text(text), timeout=10.0)

    def rotate(self, direction: str = "left"):
        if self._orientation is None:
            raise WDAError("OrientationService is unavailable on this device")
        self._submit(self._orientation.rotate(direction), timeout=5.0)

    def type_text(self, text: str):
        if not text:
            return
        from pymobiledevice3.remote.core_device.hid_service import (
            ASCII_TO_HID,
            KEY_BACKSPACE,
            KEY_ENTER,
            KEY_LEFT_GUI,
            KEY_LEFT_SHIFT,
            KEY_TAB,
            KEY_V,
        )

        async def _op():
            if self._kb_service_id is None:
                self._kb_service_id = await self._uhs.create_keyboard_service()
            kb = self._kb_service_id
            non_ascii: list[str] = []

            async def send_key(usage: int, shifted: bool):
                if shifted:
                    await self._uhs.send_keyboard(kb, (KEY_LEFT_SHIFT,))
                    await asyncio.sleep(0.02)
                    await self._uhs.send_keyboard(kb, (KEY_LEFT_SHIFT, usage))
                else:
                    await self._uhs.send_keyboard(kb, (usage,))
                await asyncio.sleep(0.025)
                await self._uhs.send_keyboard(kb, ())
                await asyncio.sleep(0.015)

            async def flush_non_ascii():
                if not non_ascii or self._pasteboard is None:
                    non_ascii.clear()
                    return
                chunk = "".join(non_ascii)
                non_ascii.clear()
                await self._pasteboard.set_text(chunk)
                await self._uhs.send_keyboard(kb, (KEY_LEFT_GUI, KEY_V))
                await asyncio.sleep(0.03)
                await self._uhs.send_keyboard(kb, ())

            for ch in text:
                if ch == "\b":
                    await flush_non_ascii()
                    await send_key(KEY_BACKSPACE, False)
                elif ch == "\n":
                    await flush_non_ascii()
                    await send_key(KEY_ENTER, False)
                elif ch == "\t":
                    await flush_non_ascii()
                    await send_key(KEY_TAB, False)
                elif ch in ASCII_TO_HID:
                    await flush_non_ascii()
                    usage, shifted = ASCII_TO_HID[ch]
                    await send_key(usage, shifted)
                else:
                    non_ascii.append(ch)
            await flush_non_ascii()

        self._submit(_op(), timeout=max(10.0, len(text) * 0.1 + 5.0))


def bring_up_native_hid(progress=lambda msg: None, cancel: threading.Event | None = None, stream_port: int = 8091):
    """Connect zero-app CoreDevice USB control if a compatible USB iPhone is plugged in."""
    if _stream_server_alive(stream_port):
        progress("Reusing active USB cable control...")
        return StreamServerHidClient(stream_port)

    if not usbmuxd_reachable():
        raise NativeHidUnavailable("usbmuxd not running")
    devices = list_devices(cancel=cancel)
    if not devices:
        raise NativeHidUnavailable("No iPhone found on USB", devices=devices)

    dev = devices[0]
    udid = dev.get("Identifier") or dev.get("UniqueDeviceID")
    if not udid:
        raise NativeHidUnavailable("USB iPhone has no UDID")
    version = str(dev.get("ProductVersion") or "0")
    ios = parse_version(version)
    name = dev.get("DeviceName") or "iPhone"
    if ios < (27, 0):
        raise NativeHidUnavailable(
            f"Zero-app USB touch control requires iOS/iPadOS 27.0 or later ({name} runs {version}).",
            devices=devices,
        )

    progress(f"{name} (iOS {version}): checking Developer Mode...")
    if not developer_mode_enabled(udid, cancel=cancel):
        raise UsbError(MSG_DEV_MODE)

    progress("Mounting Developer Disk Image...")
    code, out, err = pmd3("mounter", "auto-mount", "--udid", udid, timeout=600, cancel=cancel)
    if code:
        raise UsbError(failure_text(err or out, "Could not mount the Developer Disk Image"))

    progress("Connecting native USB control (no app needed)...")
    client = CoreDeviceHidClient(udid, cancel=cancel)
    try:
        client.open()
    except NativeHidUnavailable as exc:
        if exc.devices is None:
            exc.devices = devices
        raise
    return client
