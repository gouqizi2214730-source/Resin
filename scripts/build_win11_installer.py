"""构建 Resin Windows 11 Fluent Dark 全中文现代安装包 (Resin-Setup-win64.exe)."""

from __future__ import annotations

import shutil
import struct
import zipfile
from pathlib import Path


MAGIC_FOOTER = b"RESINW11"


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    stub_exe = root / "build" / "Win11SetupStub.exe"
    onedir_root = root / "dist" / "Resin"
    out_dir = root / "dist_installer"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_installer = out_dir / "Resin-Setup-win64.exe"

    if not stub_exe.exists():
        raise FileNotFoundError(f"Missing compiled Win11SetupStub.exe at {stub_exe}")
    if not onedir_root.exists():
        raise FileNotFoundError(f"Missing PyInstaller --onedir distribution at {onedir_root}")

    # 1. 将全中文图形化卸载程序写入 --onedir 目录
    uninstall_target = onedir_root / "Uninstall-Resin.exe"
    shutil.copy2(stub_exe, uninstall_target)
    print(f"[1/3] Bundled Win11 graphical Chinese uninstaller: {uninstall_target}")

    # 2. 将 --onedir 完整目录压缩为 payload.zip
    payload_zip = root / "build" / "resin_onedir_payload.zip"
    file_count = 0
    with zipfile.ZipFile(payload_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for fp in sorted(onedir_root.rglob("*")):
            if fp.is_file():
                rel = fp.relative_to(onedir_root).as_posix()
                zf.write(fp, rel)
                file_count += 1
    zip_size = payload_zip.stat().st_size
    print(f"[2/3] Packed {file_count} files from --onedir into payload.zip ({zip_size / (1024*1024):.2f} MB)")

    # 3. 合成自包含 Windows 11 Fluent Dark 安装器: [Stub.exe][payload.zip][int64 offset][int64 length][RESINW11]
    stub_bytes = stub_exe.read_bytes()
    zip_offset = len(stub_bytes)

    with open(out_installer, "wb") as out_f:
        out_f.write(stub_bytes)
        with open(payload_zip, "rb") as z_in:
            shutil.copyfileobj(z_in, out_f, length=1024 * 1024)
        footer = struct.pack("<qq8s", zip_offset, zip_size, MAGIC_FOOTER)
        out_f.write(footer)

    total_mb = out_installer.stat().st_size / (1024 * 1024)
    print(f"[3/3] Built modern Windows 11 Chinese installer: {out_installer} ({total_mb:.2f} MB)")


if __name__ == "__main__":
    main()
