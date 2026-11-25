"""Frozen EXE launcher for iPhone Mirror.

Internal helper subprocesses (--internal-pmd3, --internal-wifi-wda) are handled
before importing PySide6 so helper tools start cleanly without loading Qt.
"""
import multiprocessing
import sys
import traceback


def _run_helper(fn, *args) -> int:
    """Keep helper subprocess errors in stderr/exit-code instead of showing a GUI crash box."""
    try:
        return int(fn(*args) or 0)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        if sys.stderr:
            print(code, file=sys.stderr)
        return 1
    except BaseException:
        traceback.print_exc()
        return 1


def main() -> int:
    if len(sys.argv) >= 2:
        cmd = sys.argv[1]
        if cmd == "--internal-pmd3":
            def _pmd3():
                from pymobiledevice3.__main__ import main as pmd3_main

                sys.argv = ["pymobiledevice3", *sys.argv[2:]]
                return pmd3_main()

            return _run_helper(_pmd3)
        if cmd == "--internal-wifi-wda":
            def _wifi():
                from iphone_mirror.control.wifi_wda import main as wifi_wda_main

                return wifi_wda_main()

            return _run_helper(_wifi)

    from iphone_mirror.__main__ import main as gui_main

    return int(gui_main() or 0)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
