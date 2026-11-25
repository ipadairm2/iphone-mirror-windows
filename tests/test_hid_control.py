"""Tests for zero-app CoreDevice USB HID control and Controller integration."""
import contextlib
import http.server
import importlib.util
import json
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iphone_mirror import __main__ as app_main, control  # noqa: E402
from iphone_mirror.control import ERROR, OFF, READY, Controller, usb, wifi_wda  # noqa: E402
from iphone_mirror.control.hid import (  # noqa: E402
    CoreDeviceHidClient,
    NativeHidUnavailable,
    StreamServerHidClient,
    bring_up_native_hid,
)
from tests.test_wda import FakeUsb, MockWDA, wait_for  # noqa: E402


class _MockStreamServer:
    def __init__(self):
        self.calls = []
        self.clipboard = ""
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/clipboard":
                    outer.calls.append(("GET", self.path, None))
                    data = json.dumps({"text": outer.clipboard}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                outer.calls.append(("POST", self.path, body))
                if self.path == "/clipboard":
                    outer.clipboard = (body or {}).get("text", "")
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class StreamServerHidClientTests(unittest.TestCase):
    def setUp(self):
        self.srv = _MockStreamServer()
        self.client = StreamServerHidClient(self.srv.port)

    def tearDown(self):
        self.client.close()
        self.srv.close()

    def test_touch_buttons_keyboard_pasteboard_and_rotate(self):
        self.assertTrue(self.client.is_alive())
        self.assertEqual(self.client.window_size(), (390.0, 844.0))
        self.client.set_aspect(16 / 9)
        self.assertEqual(self.client.window_size(), (844.0, 390.0))
        self.client.set_aspect(9 / 19.5)
        self.assertEqual(self.client.window_size(), (390.0, 844.0))

        self.client.touch_contact(195.0, 422.0)
        self.client.touch_release(195.0, 422.0)
        self.client.tap(0.0, 844.0)
        self.client.swipe(10.0, 20.0, 300.0, 400.0, duration_ms=40, hold_end_ms=10)
        self.client.home()
        self.client.press_button("volumeUp")
        self.client.lock()
        self.client.unlock()
        self.client.set_pasteboard("copied")
        self.assertEqual(self.client.get_pasteboard(), "copied")
        self.client.rotate("left")
        self.client.type_text("A\n\u2764")

        touches = [c[2] for c in self.srv.calls if c[1] == "/touch"]
        self.assertEqual(touches[0], {"type": "contact", "x": 32768, "y": 32768})
        self.assertEqual(touches[1], {"type": "release", "x": 32768, "y": 32768})
        self.assertEqual(touches[2], {"type": "tap", "x": 0, "y": 65535})
        buttons = [c[2] for c in self.srv.calls if c[1] == "/button"]
        self.assertEqual(buttons[0]["name"], "home")
        self.assertEqual(buttons[1]["name"], "volume-up")
        self.assertEqual(buttons[2]["name"], "lock")
        rotates = [c[2] for c in self.srv.calls if c[1] == "/rotate"]
        self.assertEqual(rotates, [{"direction": "left"}])
        keys = [c[2]["usages"] for c in self.srv.calls if c[1] == "/key"]
        # Shift + A -> Enter -> Cmd+V for heart emoji
        self.assertIn([0xE1, 0x04], keys)
        self.assertIn([0x28], keys)
        self.assertIn([0xE3, 0x19], keys)
        self.assertEqual(self.srv.clipboard, "\u2764")


class CoreDeviceHidClientTests(unittest.TestCase):
    def _build_fake_coredevice(self, services: dict, start_video_exc=None):
        events = []

        class _FakeRsd:
            peer_info = {"Services": services}
            service = types.SimpleNamespace(address=("fd00::1", 50000))

        class _FakeRsdTunnel:
            def __init__(self, serial=None, autopair=True):
                self.serial = serial

            async def __aenter__(self):
                events.append(("tunnel_enter", self.serial))
                return _FakeRsd()

            async def __aexit__(self, *exc):
                events.append(("tunnel_exit", self.serial))

        class _FakeDeviceInfoService:
            def __init__(self, rsd):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                pass

            async def get_display_info(self):
                return {"displays": [{"currentMode": {"size": [1179, 2556]}}]}

        class _FakeDisplayService:
            SERVICE_NAME = "com.apple.coredevice.displayservice"

            def __init__(self, rsd):
                self.rsd = rsd

            async def __aenter__(self):
                events.append(("display_enter",))
                return self

            async def __aexit__(self, *exc):
                events.append(("display_exit",))

            async def start_video_stream(self, **kw):
                events.append(("start_video_stream", kw["receiver_ip"]))
                if start_video_exc is not None:
                    raise start_video_exc
                return {"connection": {}}

            async def stop_media_stream(self, stop_all=True):
                events.append(("stop_media_stream", stop_all))
                return {"stopped": True}

        class _FakeTransport:
            port = 55555

            async def recv(self):
                await _asyncio_sleep(0.05)
                return b""

            def close(self):
                events.append(("transport_close",))

        class _FakeUniversalHid:
            SERVICE_NAME = "com.apple.coredevice.hid.universalhidservice"

            def __init__(self, rsd):
                pass

            async def __aenter__(self):
                events.append(("uhs_enter",))
                return self

            async def __aexit__(self, *exc):
                events.append(("uhs_exit",))

            async def send_touchscreen(self, state, x, y):
                events.append(("touchscreen", state, x, y))

            async def create_keyboard_service(self):
                events.append(("create_keyboard",))
                return 0x100002001

            async def send_keyboard(self, sid, usages):
                events.append(("send_keyboard", sid, tuple(usages)))

        class _FakeIndigo:
            SERVICE_NAME = "com.apple.coredevice.hid.indigo"

            def __init__(self, rsd):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                pass

            async def send_button(self, page, usage, state):
                events.append(("button", page, usage, state))

        class _FakePasteboard:
            SERVICE_NAME = "com.apple.coredevice.pasteboardservice"

            def __init__(self, rsd):
                self.text = ""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                pass

            async def set_text(self, text):
                self.text = text
                events.append(("pb_set", text))

            async def get_text(self):
                events.append(("pb_get", self.text))
                return self.text

        class _FakeOrientation:
            SERVICE_NAME = "com.apple.coredevice.devicecontrol"

            def __init__(self, rsd):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                pass

            async def rotate(self, direction):
                events.append(("rotate", direction))
                return {"currentDeviceOrientation": "landscapeRight"}

        async def _asyncio_sleep(s):
            import asyncio

            await asyncio.sleep(s)

        patches = [
            mock.patch("pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel", _FakeRsdTunnel),
            mock.patch("pymobiledevice3.remote.core_device.device_info.DeviceInfoService", _FakeDeviceInfoService),
            mock.patch("pymobiledevice3.remote.core_device.display_service.DisplayService", _FakeDisplayService),
            mock.patch("pymobiledevice3.remote.core_device.hid_service.UniversalHIDServiceService", _FakeUniversalHid),
            mock.patch("pymobiledevice3.remote.core_device.hid_service.IndigoHIDService", _FakeIndigo),
            mock.patch("pymobiledevice3.remote.core_device.hid_service.TOUCH_AUTH_SETTLE_SECONDS", 0.01),
            mock.patch("pymobiledevice3.remote.core_device.pasteboard_service.PasteboardService", _FakePasteboard),
            mock.patch("pymobiledevice3.remote.core_device.orientation_service.OrientationService", _FakeOrientation),
            mock.patch(
                "pymobiledevice3.remote.core_device.screen_stream.open_media_receiver",
                lambda *_a: (_FakeTransport(), "fd00::2"),
            ),
        ]
        return events, patches

    def test_ios27_hid_live_touch_keyboard_and_clean_stop(self):
        services = {
            "com.apple.coredevice.hid.universalhidservice": {},
            "com.apple.coredevice.displayservice": {},
            "com.apple.coredevice.hid.indigo": {},
            "com.apple.coredevice.pasteboardservice": {},
            "com.apple.coredevice.devicecontrol": {},
        }
        events, patches = self._build_fake_coredevice(services)
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            client = CoreDeviceHidClient("UDID-27")
            client.open(timeout=5.0)
            try:
                self.assertTrue(client.is_alive())
                self.assertEqual(client.window_size(), (390.0, 845.5))
                client.touch_contact(195.0, 422.75)
                client.touch_release(195.0, 422.75)
                client.type_text("hi\u00e9")
                client.rotate("right")
                self.assertEqual(client.get_pasteboard(), "\u00e9")
                client.press_button("home")
            finally:
                client.close()

        self.assertIn(("start_video_stream", "fd00::2"), events)
        self.assertIn(("create_keyboard",), events)
        self.assertIn(("pb_set", "\u00e9"), events)
        self.assertIn(("rotate", "right"), events)
        self.assertIn(("stop_media_stream", True), events)
        self.assertIn(("tunnel_exit", "UDID-27"), events)

    def test_pre_ios27_and_code_9021_raise_native_unavailable(self):
        from pymobiledevice3.exceptions import CoreDeviceError, DeviceVersionNotSupportedError

        services = {
            "com.apple.coredevice.hid.universalhidservice": {},
            "com.apple.coredevice.displayservice": {},
        }
        for label, exc in (
            ("version_gate", DeviceVersionNotSupportedError("Screen streaming needs iOS 27.0")),
            ("code_9021", CoreDeviceError("Remote control requires iOS 27.0 or later", code=9021)),
        ):
            events, patches = self._build_fake_coredevice(services, start_video_exc=exc)
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                client = CoreDeviceHidClient(f"UDID-{label}")
                with self.assertRaises(NativeHidUnavailable) as ctx:
                    client.open(timeout=5.0)
                self.assertIn("27.0", str(ctx.exception))
            self.assertIn(("tunnel_exit", f"UDID-{label}"), events)

        devs = [{"Identifier": "IPAD-26", "DeviceName": "Test iPad", "ProductVersion": "26.6.1"}]
        with mock.patch("iphone_mirror.control.hid._stream_server_alive", return_value=False), \
                mock.patch("iphone_mirror.control.hid.usbmuxd_reachable", return_value=True), \
                mock.patch("iphone_mirror.control.hid.list_devices", return_value=devs):
            with self.assertRaises(NativeHidUnavailable) as ctx:
                bring_up_native_hid()
            self.assertIn("27.0", str(ctx.exception))
            self.assertEqual(ctx.exception.devices, devs)

    def test_missing_hid_service_raises_native_unavailable(self):
        events, patches = self._build_fake_coredevice({"com.apple.coredevice.displayservice": {}})
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            client = CoreDeviceHidClient("UDID-17")
            with self.assertRaises(NativeHidUnavailable):
                client.open(timeout=5.0)
        self.assertIn(("tunnel_exit", "UDID-17"), events)


class ControllerHidIntegrationTests(unittest.TestCase):
    def setUp(self):
        FakeUsb.instances, FakeUsb.error, FakeUsb.block = [], None, False

    def test_controller_native_hid_live_touch_coalescing_and_fallback(self):
        events = []

        class _FakeHidClient:
            live_touch = True
            backend_name = "Native USB"

            def __init__(self):
                self.closed = False

            def window_size(self, refresh=False):
                return (390.0, 844.0)

            def is_alive(self):
                return not self.closed

            def touch_contact(self, x, y):
                events.append(("contact", round(x), round(y)))

            def touch_release(self, x, y):
                events.append(("release", round(x), round(y)))

            def close(self):
                self.closed = True
                events.append(("closed",))

        states = []
        first_entered = threading.Event()
        gate = threading.Event()

        class _SlowHidClient(_FakeHidClient):
            def touch_contact(self, x, y):
                super().touch_contact(x, y)
                if not first_entered.is_set():
                    first_entered.set()
                    gate.wait(timeout=1.0)

        slow = _SlowHidClient()
        ctrl = Controller(on_state=lambda s, m: states.append((s, m)))
        ctrl.IDLE_CHECK = 60.0
        with mock.patch("iphone_mirror.control.hid.bring_up_native_hid", return_value=slow):
            ctrl.start()
            self.assertTrue(wait_for(lambda: ctrl.state == READY))
            self.assertTrue(ctrl.supports_live_touch)
            self.assertEqual(ctrl.backend_name, "Native USB")

            ctrl.touch_contact(0.1, 0.1)
            self.assertTrue(first_entered.wait(timeout=1.0))
            ctrl.touch_contact(0.2, 0.2)
            ctrl.touch_contact(0.9, 0.9)
            ctrl.touch_release(0.9, 0.9)
            gate.set()
            self.assertTrue(wait_for(lambda: any(e[0] == "release" for e in events)))
            ctrl.stop()
            self.assertTrue(wait_for(lambda: ctrl.state == OFF))

        contacts = [e for e in events if e[0] == "contact"]
        self.assertEqual(contacts, [("contact", 39, 84), ("contact", 351, 760)])
        self.assertIn(("release", 351, 760), events)
        self.assertIn(("closed",), events)

    def test_controller_falls_back_to_wda_and_honors_native_only_error(self):
        mock_wda = MockWDA()
        try:
            seen_devices = []
            devs = [{"Identifier": "U-26", "ProductVersion": "26.6.1"}]

            class _FakeWdaUsb(FakeUsb):
                def bring_up(self, progress=lambda m: None, wait=90, devices=None):
                    seen_devices.append(devices)
                    progress("fake wda bring-up")
                    return mock_wda.url

            ctrl = Controller()
            ctrl.control_mode = "auto"
            with mock.patch.object(Controller, "_find_running", return_value=None), \
                    mock.patch(
                        "iphone_mirror.control.hid.bring_up_native_hid",
                        side_effect=NativeHidUnavailable("needs iOS 27+", devices=devs),
                    ), \
                    mock.patch.object(control, "UsbSession", _FakeWdaUsb), \
                    mock.patch.object(control, "_REAL_USB_SESSION", _FakeWdaUsb):
                ctrl.start()
                self.assertTrue(wait_for(lambda: ctrl.state == READY))
                self.assertFalse(ctrl.supports_live_touch)
                self.assertEqual(ctrl.backend_name, "WebDriverAgent")
                self.assertEqual(seen_devices, [devs])
                ctrl.stop()

            ctrl2 = Controller()
            ctrl2.control_mode = "native"
            with mock.patch.object(Controller, "_find_running", return_value=None), \
                    mock.patch("iphone_mirror.control.hid.bring_up_native_hid", side_effect=NativeHidUnavailable("needs iOS 27+")), \
                    mock.patch.object(control, "_REAL_USB_SESSION", _FakeWdaUsb), \
                    mock.patch.object(control, "UsbSession", _FakeWdaUsb):
                ctrl2.start()
                self.assertTrue(wait_for(lambda: ctrl2.state == ERROR))
                self.assertIn("needs iOS 27+", ctrl2.message)
        finally:
            mock_wda.close()

    def test_wifi_wda_dispatch_unplugged_caching_and_hint(self):
        launcher_path = Path(__file__).resolve().parent.parent / "packaging" / "launcher.py"
        spec = importlib.util.spec_from_file_location("test_launcher_mod", launcher_path)
        launcher_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher_mod)

        def _fake_asyncio_run(coro):
            coro.close()
            return None

        with mock.patch("asyncio.run", side_effect=_fake_asyncio_run):
            self.assertEqual(wifi_wda.main(), 0)
            self.assertEqual(wifi_wda.main([]), 0)

        called = []

        def _spy_main(*args):
            called.append(args)
            return 0

        with mock.patch("iphone_mirror.control.wifi_wda.main", side_effect=_spy_main):
            with mock.patch.object(sys, "argv", ["iPhoneMirror.exe", "--internal-wifi-wda"]):
                self.assertEqual(launcher_mod.main(), 0)
            with mock.patch.object(sys, "argv", ["iphone_mirror", "--internal-wifi-wda"]):
                self.assertEqual(app_main._maybe_run_internal_helper(), 0)
        self.assertEqual(called, [(), ()])

        with mock.patch("iphone_mirror.control.hid._stream_server_alive", return_value=False), \
                mock.patch("iphone_mirror.control.hid.usbmuxd_reachable", return_value=True), \
                mock.patch("iphone_mirror.control.hid.list_devices", return_value=[]):
            with self.assertRaises(NativeHidUnavailable) as ctx:
                bring_up_native_hid()
            self.assertEqual(ctx.exception.devices, [])

        self.assertEqual(usb.explain("WebDriverAgent is not installed on the iPhone."), usb.MSG_NO_WDA)


if __name__ == "__main__":
    unittest.main(verbosity=2)
