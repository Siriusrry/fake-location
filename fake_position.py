"""Foreground location simulation for macOS and iOS/iPadOS 17.4+."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
import fcntl
from importlib.metadata import PackageNotFoundError, version
import logging
import math
import os
from pathlib import Path
import plistlib
import re
import signal
import sys
import tempfile
import threading

PROJECT = Path(__file__).resolve().parent
CONNECT_TIMEOUT = 8
SERVICE_TIMEOUT = 20
CLEAR_TIMEOUT = 8
NO_DEVICE = (
    "未发现可连接的设备。首次使用请通过数据线配对一次；"
    "已配对的设备请确认已解锁，并检查 Wi-Fi 或 USB 连接。"
)


class UserError(Exception):
    """An actionable failure shown without an internal traceback."""


@dataclass
class Device:
    udid: str
    name: str
    system: str = ""


def runtime_directory(project: Path = PROJECT, prefix: str | None = None,
                      base_prefix: str | None = None) -> Path:
    prefix = sys.prefix if prefix is None else prefix
    base_prefix = sys.base_prefix if base_prefix is None else base_prefix
    return (Path(prefix) if prefix != base_prefix else project) / ".fake_position"


def configure_storage(state: Path) -> None:
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = state / "tmp"
    temporary.mkdir(mode=0o700, exist_ok=True)
    # Set this before importing SDK modules that resolve their cache directory.
    import pymobiledevice3.common as common
    common._HOMEFOLDER = state / "pymobiledevice3"
    tempfile.tempdir = str(temporary)


def check_dependencies() -> None:
    expected = {"pymobiledevice3": "10.10.3", "pmd-pytcp": "0.3.7"}
    try:
        mismatch = [f"{name}=={wanted}" for name, wanted in expected.items()
                    if version(name) != wanted]
    except PackageNotFoundError:
        raise UserError("缺少依赖，请按 README 用当前 Python 安装 requirements.txt。") from None
    if mismatch:
        raise UserError("依赖版本与本工具不一致，请按 requirements.txt 安装：" + ", ".join(mismatch))


def select_device(devices: list[Device], input_fn=input, output=print) -> Device:
    if not devices:
        raise UserError(NO_DEVICE)
    if len(devices) == 1:
        return devices[0]
    output("发现多台设备，请选择目标：")
    for index, device in enumerate(devices, 1):
        output(f"  {index}. {device.name}  {device.system}  [{device.udid}]")
    while True:
        try:
            answer = input_fn("设备编号：").strip()
        except EOFError:
            raise UserError("需要选择目标设备，请在交互终端运行。") from None
        if answer.isascii() and answer.isdecimal() and 1 <= int(answer) <= len(devices):
            return devices[int(answer) - 1]
        output(f"请输入 1 到 {len(devices)} 之间的编号。")


@contextmanager
def device_lock(state: Path, udid: str):
    locks = state / "locks"
    locks.mkdir(mode=0o700, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9-]", "_", udid)
    with (locks / f"{safe_id}.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UserError("本工具已在修改这台设备的定位，请先在原终端按 Ctrl+C。") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


async def discover() -> list[Device]:
    from pymobiledevice3 import usbmux
    from pymobiledevice3.lockdown import create_using_usbmux

    entries = await asyncio.wait_for(usbmux.list_devices(), CONNECT_TIMEOUT)
    grouped: dict[str, set[str]] = {}
    for entry in entries:
        if entry.connection_type in {"Network", "USB"}:
            grouped.setdefault(entry.serial, set()).add(entry.connection_type)

    async def describe(udid, transports):
        for kind in ("Network", "USB"):
            if kind not in transports:
                continue
            try:
                lockdown = await asyncio.wait_for(
                    create_using_usbmux(serial=udid, connection_type=kind, autopair=False),
                    CONNECT_TIMEOUT,
                )
                try:
                    info = lockdown.all_values
                    if info.get("DeviceClass") not in ("iPhone", "iPad"):
                        return None
                    return Device(udid, info.get("DeviceName") or info["DeviceClass"],
                                  info.get("ProductVersion", ""))
                finally:
                    await lockdown.close()
            except Exception:
                continue
        # Keep an undisclosed/locked device selectable so errors concern that device.
        return Device(udid, "Apple 设备（信息暂不可读）")

    devices = await asyncio.gather(*(describe(k, v) for k, v in sorted(grouped.items())))
    return [device for device in devices if device is not None]


async def download_ddi(folder: Path) -> tuple[Path, Path, Path]:
    """Download only when mounting is necessary; all partial files stay in state."""
    from pymobiledevice3.services.mobile_image_mounter import LATEST_DDI_BUILD_ID
    from developer_disk_image.repo import DEVELOPER_DISK_IMAGE_REPO_RAW_URL_FORMAT
    import requests

    folder.mkdir(parents=True, exist_ok=True)
    image, manifest, trust = (folder / name for name in ("Image.dmg", "BuildManifest.plist", "Image.trustcache"))
    if all(p.is_file() and p.stat().st_size for p in (image, manifest, trust)):
        try:
            if plistlib.loads(manifest.read_bytes()).get("ProductBuildVersion") == LATEST_DDI_BUILD_ID:
                return image, manifest, trust
        except (ValueError, plistlib.InvalidFileException):
            pass
    print("正在下载开发者镜像…", flush=True)
    cancelled = threading.Event()

    def fetch():
        # An interrupted worker is joined below; it never outlives this command.
        with requests.Session() as client, tempfile.TemporaryDirectory(dir=folder) as temporary:
            downloaded = []
            for local, remote in ((image, "Image.dmg"), (trust, "Image.dmg.trustcache"),
                                  (manifest, "BuildManifest.plist")):
                if cancelled.is_set():
                    return
                url = DEVELOPER_DISK_IMAGE_REPO_RAW_URL_FORMAT.format(
                    ref="main", path=f"PersonalizedImages/Xcode_iOS_DDI_Personalized/{remote}")
                target = Path(temporary) / local.name
                with client.get(url, stream=True, timeout=(8, 15)) as response:
                    response.raise_for_status()
                    with target.open("wb") as handle:
                        for chunk in response.iter_content(256 * 1024):
                            if cancelled.is_set():
                                return
                            handle.write(chunk)
                if not target.stat().st_size:
                    raise UserError("下载的开发者镜像为空，请稍后重试。")
                downloaded.append((target, local))
            data = plistlib.loads(downloaded[-1][0].read_bytes())
            if data.get("ProductBuildVersion") != LATEST_DDI_BUILD_ID:
                raise UserError("上游镜像版本已变化，需要更新本工具的兼容版本。")
            for temporary_file, destination in downloaded:
                os.replace(temporary_file, destination)

    worker = asyncio.create_task(asyncio.to_thread(fetch))
    try:
        await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancelled.set()
        try:
            await worker
        except Exception:
            pass
        raise
    return image, manifest, trust


@contextmanager
def tunnel_uses(lockdown):
    """The pinned SDK lacks transport injection; reuse the verified connection."""
    from pymobiledevice3.remote import userspace_tunnel
    original = userspace_tunnel.create_using_usbmux

    async def existing_connection(serial=None, **_):
        if serial != lockdown.udid:
            raise UserError("连接设备与所选设备不一致，已停止。")
        return lockdown

    userspace_tunnel.create_using_usbmux = existing_connection
    try:
        yield
    finally:
        userspace_tunnel.create_using_usbmux = original


class Session:
    def __init__(self, location, dvt, transport):
        self.location, self.dvt, self.transport = location, dvt, transport

    async def set(self, latitude, longitude):
        await asyncio.wait_for(self.location.set(latitude, longitude), SERVICE_TIMEOUT)

    async def clear(self):
        # The SDK's clear() uses expects_reply=False. Request a reply so the
        # userspace relay is not torn down before the device processes the clear.
        await asyncio.wait_for(
            self.location.service.invoke("stopLocationSimulation", expects_reply=True), CLEAR_TIMEOUT)

    async def wait(self):
        # Unlike signal.sigwait(), this keeps the userspace tunnel's loop running.
        await asyncio.shield(self.dvt.dtx._reader_task)
        raise UserError("设备连接已断开。")


class Backend:
    def __init__(self, state):
        self.state = state

    @asynccontextmanager
    async def connect(self, device, transport):
        from packaging.version import Version
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.services.mobile_image_mounter import PersonalizedImageMounter
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

        async with AsyncExitStack() as resources:
            lockdown = await asyncio.wait_for(
                create_using_usbmux(serial=device.udid, connection_type=transport, autopair=False),
                CONNECT_TIMEOUT,
            )
            resources.push_async_callback(lockdown.close)
            actual = lockdown.service.mux_device
            if actual is None or actual.connection_type != transport or not actual.matches_udid(device.udid):
                raise UserError("实际连接与所选设备或连接方式不一致，已停止。")
            if not lockdown.paired:
                raise UserError("设备尚未信任这台 Mac，或配对已过期。请通过数据线连接、解锁并确认“信任”。")
            if Version(lockdown.product_version) < Version("17.4"):
                raise UserError("本工具支持 iOS / iPadOS 17.4 及以上版本。")
            if not await asyncio.wait_for(lockdown.get_developer_mode_status(), CONNECT_TIMEOUT):
                raise UserError("设备未开启开发者模式，请先完成设备端设置后重试。")

            async with PersonalizedImageMounter(lockdown) as mounter:
                if not await asyncio.wait_for(mounter.is_image_mounted("Personalized"), SERVICE_TIMEOUT):
                    assets = await download_ddi(self.state / "pymobiledevice3" / "Xcode_iOS_DDI_Personalized")
                    print("正在挂载开发者镜像…", flush=True)
                    # mount expects image, manifest, trust cache in this order.
                    await asyncio.wait_for(mounter.mount(*assets), 120)

            with tunnel_uses(lockdown):
                tunnel = UserspaceRsdTunnel(serial=device.udid, autopair=False, remotepairing_fallback=False)
                rsd = await asyncio.wait_for(resources.enter_async_context(tunnel), SERVICE_TIMEOUT)
                if rsd.udid != device.udid:
                    raise UserError("隧道连接到其他设备，已停止。")
                dvt = await asyncio.wait_for(resources.enter_async_context(DvtProvider(rsd)), SERVICE_TIMEOUT)
                location = await asyncio.wait_for(resources.enter_async_context(LocationSimulation(dvt)), SERVICE_TIMEOUT)
                yield Session(location, dvt, transport)


async def run_device(device, latitude, longitude, backend, output=print):
    failures = []
    for transport in ("Network", "USB"):
        entered = False
        try:
            async with backend.connect(device, transport) as session:
                entered = True
                # Once setting starts, do not switch devices/transports on failure.
                try:
                    await session.set(latitude, longitude)
                    label = "无线" if transport == "Network" else "USB"
                    output(f"已连接 {device.name}（{label}），定位设为 {latitude}, {longitude}。")
                    output("保持运行；按 Ctrl+C 还原定位并退出。")
                    await session.wait()
                finally:
                    await session.clear()
                    output("已清除模拟定位。")
        except UserError:
            raise
        except Exception as exc:
            if entered:
                raise UserError(f"定位会话结束时出现错误：{exc or type(exc).__name__}") from exc
            failures.append(f"{transport}: {exc or type(exc).__name__}")
    raise UserError("无法连接所选设备，请确认已解锁并检查 Wi-Fi 或 USB 连接。\n" + "\n".join(failures))


async def execute(device, latitude, longitude, state):
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    stopping = False

    def stop():
        nonlocal stopping
        if not stopping:
            stopping = True
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)
    try:
        await run_device(device, latitude, longitude, Backend(state))
    except asyncio.CancelledError:
        print("已退出。", flush=True)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main():
    parser = argparse.ArgumentParser(prog="fake_position", description="无线优先，自动回退 USB；Ctrl+C 还原定位。")
    parser.add_argument("latitude", type=float, help="纬度（-90 到 90）")
    parser.add_argument("longitude", type=float, help="经度（-180 到 180）")
    args = parser.parse_args()
    for value, limit, label in ((args.latitude, 90, "纬度"), (args.longitude, 180, "经度")):
        if not math.isfinite(value) or not -limit <= value <= limit:
            parser.error(f"{label}必须是 {-limit} 到 {limit} 之间的有限数值")
    if sys.platform != "darwin" or sys.version_info < (3, 11):
        parser.error("需要 macOS 和 Python 3.11 或以上版本")
    try:
        check_dependencies()
        state = runtime_directory()
        configure_storage(state)
        logging.basicConfig(level=logging.ERROR, format="%(name)s: %(message)s")
        device = select_device(asyncio.run(discover()))
        with device_lock(state, device.udid):
            asyncio.run(execute(device, args.latitude, args.longitude, state))
        return 0
    except KeyboardInterrupt:
        print("已退出。")
        return 0
    except Exception as exc:
        print(f"错误：{exc or type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
