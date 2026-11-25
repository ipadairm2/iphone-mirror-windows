"""Build standalone iPhoneMirror.exe (PyInstaller) and iPhoneMirror-Setup.exe (Inno Setup)."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "packaging"


def run(cmd, env=None):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=str(ROOT), env=env, check=True)


def _rm_tree(path: Path):
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        if sys.platform == "win32":
            # OneDrive Files On-Demand directories carry reparse-point attributes that trip shutil.rmtree
            subprocess.run(["cmd", "/c", "rd", "/s", "/q", str(path)], check=False)
        if path.exists():
            shutil.rmtree(path)


def find_iscc() -> Path | None:
    on_path = shutil.which("iscc") or shutil.which("ISCC")
    if on_path:
        return Path(on_path)
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
        Path("C:/Program Files/Inno Setup 6/ISCC.exe"),
    ]
    return next((p for p in candidates if p.is_file()), None)


def main() -> int:
    # 1. Generate application .ico
    run([sys.executable, PACK / "make_icon.py"])

    # 2. Ensure Rust .pyd extensions exist
    fairplay_pyd = list((ROOT / "rust" / "fairplay-rs" / "python").rglob("*.pyd"))
    stream_pyd = list((ROOT / "rust" / "stream-ops-rs" / "python").rglob("*.pyd"))
    if (not fairplay_pyd or not stream_pyd) and shutil.which("rust-anything"):
        if not fairplay_pyd:
            run(["rust-anything", "build", "rust/fairplay-rs"])
        if not stream_pyd:
            run(["rust-anything", "build", "rust/stream-ops-rs"])

    # 3. Stage PyInstaller build outside OneDrive to avoid reparse-point unlink locks
    stage = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "iPhoneMirror" / "pyi_stage"
    work = stage / "work"
    stage_dist = stage / "dist"
    _rm_tree(work)
    _rm_tree(stage_dist)
    work.mkdir(parents=True, exist_ok=True)
    stage_dist.mkdir(parents=True, exist_ok=True)

    run([
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--workpath",
        str(work),
        "--distpath",
        str(stage_dist),
        PACK / "iPhoneMirror.spec",
    ])
    stage_app = stage_dist / "iPhoneMirror"
    exe = stage_app / "iPhoneMirror.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"Missing built executable: {exe}")
    print(f"Built staged app: {exe}")

    # 4. Build single-file Windows Setup installer if Inno Setup 6 is installed
    iscc = find_iscc()
    if iscc is None:
        print("Inno Setup 6 (ISCC.exe) not found; skipping iPhoneMirror-Setup.exe", file=sys.stderr)
        return 1
    run([
        iscc,
        f"/DAppSourceDir={stage_app}",
        f"/DAppOutputDir={stage_dist}",
        PACK / "iPhoneMirror.iss",
    ])
    staged_setup = stage_dist / "iPhoneMirror-Setup.exe"
    if not staged_setup.is_file():
        raise FileNotFoundError(f"Missing installer: {staged_setup}")

    dist_dir = ROOT / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    setup_exe = dist_dir / "iPhoneMirror-Setup.exe"
    shutil.copy2(staged_setup, setup_exe)
    print(f"Built installer: {setup_exe} ({setup_exe.stat().st_size / (1024 * 1024):.1f} MB)")

    repo_app = dist_dir / "iPhoneMirror"
    try:
        _rm_tree(repo_app)
        shutil.copytree(stage_app, repo_app)
        print(f"Built standalone app: {repo_app / 'iPhoneMirror.exe'}")
    except OSError as exc:
        print(f"Warning: could not mirror standalone folder into {repo_app} ({exc}); use {setup_exe} or {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
