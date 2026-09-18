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
import subprocess
import sys
import tempfile
import threading


def detect_language():
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["/usr/bin/defaults", "export", "NSGlobalDomain", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                check=True, timeout=2,
            )
            languages = plistlib.loads(result.stdout).get("AppleLanguages", [])
            if isinstance(languages, list) and languages and isinstance(languages[0], str):
                return "zh" if languages[0].lower().startswith("zh") else "en"
        except (OSError, subprocess.SubprocessError, ValueError, plistlib.InvalidFileException):
            pass
    language = next((os.environ[key] for key in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(key)), "en")
    return "zh" if language.lower().startswith("zh") else "en"


LANGUAGE = detect_language()

MESSAGES = {
    'no_device': ('未发现可连接的设备。首次使用请通过数据线配对一次；已配对的设备请确认已解锁，并检查 Wi-Fi 或 USB 连接。', 'No connectable devices found. For first-time use, pair once via USB. For paired devices, unlock them and check the Wi-Fi or USB connection.'),
    'missing_dependencies': ('缺少依赖，请按 README 用当前 Python 安装 requirements.txt。', 'Missing dependencies. Install requirements.txt with your current Python as described in the README.'),
    'dependency_mismatch': ('依赖版本与本工具不一致，请按 requirements.txt 安装：{packages}', 'Dependency versions do not match requirements.txt. Install: {packages}'),
    'confirm_device': ('请确认要修改定位的设备：', 'Please confirm the device whose location you want to change:'),
    'choose_device': ('发现多台设备，请选择目标：', 'Multiple devices found. Select the target:'),
    'device_number': ('设备编号：', 'Device number: '),
    'interactive_required': ('需要选择目标设备，请在交互终端运行。', 'A target device must be selected. Run this command in an interactive terminal.'),
    'invalid_number': ('请输入 1 到 {count} 之间的编号。', 'Enter a number between 1 and {count}.'),
    'already_running': ('本工具已在修改这台设备的定位，请先在原终端按 Ctrl+C。', "This tool is already simulating this device's location. Press Ctrl+C in the original terminal first."),
    'usbmux_count': ('usbmuxd 返回 {count} 条连接记录。', 'usbmuxd returned {count} connection records.'),
    'device_info_failed': ('读取设备 {udid}（{transport}）失败：{error}', 'Failed to read device {udid} ({transport}): {error}'),
    'device_count': ('已确认 {count} 台 iPhone / iPad 的连接和基本信息。', 'Verified connections and basic information for {count} iPhone / iPad devices.'),
    'device_info_incomplete': ('设备 {udid} 未返回完整的名称和系统版本，跳过该连接。', 'Device {udid} did not return a complete name and OS version. Skipping this connection.'),
    'usb_pairing_needed': ('USB，待配对', 'USB, pairing required'),
    'network_pairing_required': ('无线连接没有有效的配对会话，需要通过 USB 配对。', 'No valid pairing session is available over wireless. USB pairing is required.'),
    'pairing_prompt': ('所选 USB 设备尚无有效配对。请解锁设备，点击“信任”并按提示输入密码（等待 {seconds} 秒）。', 'The selected USB device has no valid pairing. Unlock it, tap Trust, and enter its passcode if prompted (waiting up to {seconds} seconds).'),
    'pairing_failed': ('USB 配对未完成：{error}', 'USB pairing did not complete: {error}'),
    'pairing_invalid': ('设备未通过配对后的会话验证，已停止。', 'The device failed session validation after pairing. Stopped.'),
    'pairing_ready': ('USB 配对会话已验证。', 'USB pairing session verified.'),
    'wifi_checking': ('正在检查所选 USB 设备的 Wi-Fi 连接开关。', 'Checking the Wi-Fi connection setting on the selected USB device.'),
    'wifi_already_enabled': ('Wi-Fi 连接已开启，无需修改。', 'Wi-Fi connections are already enabled. No change needed.'),
    'wifi_enabling': ('Wi-Fi 连接未开启，正在启用。', 'Wi-Fi connections are disabled. Enabling them.'),
    'wifi_enabled': ('Wi-Fi 连接已开启，回读确认成功。', 'Wi-Fi connections enabled and confirmed by reading the setting back.'),
    'wifi_verify_failed': ('设置后回读的 Wi-Fi 连接开关仍未开启。', 'The Wi-Fi connection setting is still disabled after the update.'),
    'wifi_setup_failed': ('自动配置 Wi-Fi 连接失败：{error}；本次继续使用 USB。', 'Automatic Wi-Fi connection setup failed: {error}. Continuing over USB for this session.'),
    'transport_mismatch': ('实际连接与所选设备或连接方式不一致，已停止。', 'The connection does not match the selected device or transport. Stopped.'),
    'downloading': ('正在下载开发者镜像…', 'Downloading the developer disk image…'),
    'empty_image': ('下载的开发者镜像为空，请稍后重试。', 'The downloaded developer disk image is empty. Try again later.'),
    'image_version_changed': ('上游镜像版本已变化，需要更新本工具的兼容版本。', 'The upstream disk image version has changed. Update this tool to a compatible version.'),
    'device_mismatch': ('连接设备与所选设备不一致，已停止。', 'The connected device does not match the selected device. Stopped.'),
    'disconnected': ('设备连接已断开。', 'The device connection was lost.'),
    'connecting': ('尝试{transport}连接所选设备。', 'Trying a {transport} connection to the selected device.'),
    'reusing_connection': ('复用所选设备已验证的{transport}连接。', 'Reusing the verified {transport} connection to the selected device.'),
    'wireless': ('无线', 'wireless'),
    'checking_device': ('连接已建立，检查配对、系统版本和开发者模式。', 'Connection established. Checking pairing, OS version, and Developer Mode.'),
    'not_paired': ('设备尚未信任这台 Mac，或配对已过期。请通过数据线连接、解锁并确认“信任”。', 'The device has not trusted this Mac, or its pairing has expired. Connect via USB, unlock it, and confirm Trust.'),
    'unsupported_os': ('本工具支持 iOS / iPadOS 17.4 及以上版本。', 'This tool requires iOS / iPadOS 17.4 or later.'),
    'developer_mode_disabled': ('设备未开启开发者模式，请先完成设备端设置后重试。', 'Developer Mode is disabled. Enable it on the device and try again.'),
    'mounting': ('正在挂载开发者镜像…', 'Mounting the developer disk image…'),
    'starting_services': ('开发者镜像已就绪，正在建立隧道与定位服务。', 'The developer disk image is ready. Starting the tunnel and location service.'),
    'tunnel_mismatch': ('隧道连接到其他设备，已停止。', 'The tunnel connected to a different device. Stopped.'),
    'connected': ('已连接。', 'Connected.'),
    'location_set': ('定位已修改为 {coordinates}。', 'Location changed to {coordinates}.'),
    'exit_hint': ('按 {shortcut} 还原定位并退出。', 'Press {shortcut} to restore the location and exit.'),
    'session_error': ('定位会话结束时出现错误：{error}', 'The location session ended with an error: {error}'),
    'usb_fallback': ('；回退到同一设备的 USB。', '; falling back to USB for the same device.'),
    'connect_failed': ('无法连接所选设备，请确认已解锁并检查 Wi-Fi 或 USB 连接。', 'Cannot connect to the selected device. Unlock it and check the Wi-Fi or USB connection.'),
    'description': ('修改设备定位；Ctrl+C 还原定位并退出。', 'Change the device location. Press Ctrl+C to restore the location and exit.'),
    'latitude_help': ('纬度（-90 到 90）', 'Latitude (-90 to 90)'),
    'longitude_help': ('经度（-180 到 180）', 'Longitude (-180 to 180)'),
    'latitude': ('纬度', 'Latitude'),
    'longitude': ('经度', 'Longitude'),
    'coordinate_error': ('{label}必须是 {minimum} 到 {maximum} 之间的有限数值', '{label} must be a finite number between {minimum} and {maximum}'),
    'platform_required': ('需要 macOS 和 Python 3.11 或以上版本', 'macOS and Python 3.11 or later are required'),
    'help': ('显示帮助并退出', 'Show this help message and exit'),
    'arguments': ('参数', 'arguments'),
    'options': ('选项', 'options'),
    'discovering_usbmux': ('正在从 macOS usbmuxd 发现设备…', 'Discovering devices through macOS usbmuxd…'),
    'discovering_native': ('正在发现设备…', 'Discovering devices…'),
    'native_count': ('发现 {count} 条设备记录。', 'Found {count} device records.'),
    'discovery_failed': ('{source} 发现失败：{error}；继续使用另一发现来源。', '{source} discovery failed: {error}. Continuing with the other discovery source.'),
    'native_info': ('正在读取设备 {udid} 的信息。', 'Reading information for device {udid}.'),
    'native_connection': ('Apple 原生连接', 'Apple native connection'),
    'native_connecting': ('正在连接所选设备。', 'Connecting to the selected device.'),
    'native_reusing': ('使用所选设备已建立的连接。', 'Using the existing connection to the selected device.'),
    'route_fallback': ('{route}：{error}；继续尝试同一设备的 {next_route}。', '{route}: {error}; trying {next_route} for the same device.'),
    'refreshing_native': ('开发者镜像已挂载，正在刷新服务列表。', 'The developer disk image was mounted. Refreshing services.'),
    'usb_access_setup_failed': ('USB 配对或无线访问配置失败：{error}；继续使用当前连接，后续无线访问尚未确认就绪。', 'USB pairing or Wi-Fi access setup failed: {error}. Continuing with the current connection; future wireless access is not confirmed ready.'),
    'starting_location_service': ('正在连接定位服务。', 'Connecting to the location service.'),
    'checking_image': ('正在检查开发者镜像挂载状态。', 'Checking whether the developer disk image is mounted.'),
}


def tr(key, **values):
    return MESSAGES[key][0 if LANGUAGE == "zh" else 1].format(**values)


PROJECT = Path(__file__).resolve().parent
CONNECT_TIMEOUT = 8
DISCOVERY_SECONDS = 3
PAIR_TIMEOUT = 60
SERVICE_TIMEOUT = 20
CLEAR_TIMEOUT = 8
LOGGER = logging.getLogger("fake_position")


def colored(text: str, color: str, stream=None) -> str:
    stream = sys.stdout if stream is None else stream
    if not stream.isatty() or os.environ.get("TERM") == "dumb" or "NO_COLOR" in os.environ:
        return text
    return f"\033[{color}m{text}\033[0m"


class ConsoleFormatter(logging.Formatter):
    def __init__(self, stream):
        super().__init__()
        self.stream = stream

    def format(self, record):
        color = "31" if record.levelno >= logging.ERROR else "33" if record.levelno >= logging.WARNING else "34"
        label = colored(f"[{record.levelname}]", color, self.stream)
        message = record.getMessage()
        if record.name != LOGGER.name:
            message = f"{record.name}: {message}"
        if record.levelno >= logging.ERROR:
            message = colored(message, color, self.stream)
        result = f"{label} {message}"
        if record.exc_info:
            result += "\n" + self.formatException(record.exc_info)
        return result


def configure_logging():
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(ConsoleFormatter(sys.stderr))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    LOGGER.setLevel(logging.INFO)


class CommandParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        LOGGER.error(message)
        raise SystemExit(2)


class UserError(Exception):
    """An actionable failure shown without an internal traceback."""


@dataclass
class Device:
    udid: str
    name: str
    transports: tuple[str, ...]
    system: str = ""
    requires_pairing: bool = False
    lockdown: object | None = None
    native_tunnel: object | None = None
    routes: tuple[str, ...] = ()


def error_detail(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


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
    expected = {"pymobiledevice3": "11.15.3", "pmd-pytcp": "0.3.7"}
    try:
        mismatch = [f"{name}=={wanted}" for name, wanted in expected.items()
                    if version(name) != wanted]
    except PackageNotFoundError:
        raise UserError(tr("missing_dependencies")) from None
    if mismatch:
        raise UserError(tr("dependency_mismatch", packages=", ".join(mismatch)))


def select_device(devices: list[Device], input_fn=input, output=print) -> Device:
    if not devices:
        raise UserError(tr("no_device"))
    output(tr("confirm_device" if len(devices) == 1 else "choose_device"))
    for index, device in enumerate(devices, 1):
        connections = ", ".join("Wi-Fi" if kind == "Network" else kind for kind in device.transports)
        if not connections:
            connections = tr("native_connection")
        status = f" ({tr('usb_pairing_needed')})" if device.requires_pairing else ""
        output(f"  {index}. {device.name}  {device.system}  [{connections}]  [{device.udid}]{status}")
    while True:
        try:
            answer = input_fn(tr("device_number")).strip()
        except EOFError:
            raise UserError(tr("interactive_required")) from None
        if answer.isascii() and answer.isdecimal() and 1 <= int(answer) <= len(devices):
            return devices[int(answer) - 1]
        output(tr("invalid_number", count=len(devices)))


@contextmanager
def device_lock(state: Path, udid: str):
    locks = state / "locks"
    locks.mkdir(mode=0o700, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9-]", "_", udid)
    with (locks / f"{safe_id}.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UserError(tr("already_running")) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


async def close_device_connections(devices) -> None:
    async with AsyncExitStack() as resources:
        for device in devices:
            if device.lockdown is not None:
                resources.push_async_callback(device.lockdown.close)
                device.lockdown = None
            if device.native_tunnel is not None:
                resources.push_async_callback(device.native_tunnel.aclose)
                device.native_tunnel = None


async def finish_on_cancel(awaitable):
    """Join SDK worker threads before their owning connections can be released."""
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise


async def open_native_tunnel(udid):
    from pymobiledevice3.remote.native_tunnel import NativeRemotedTunnel

    tunnel = NativeRemotedTunnel(serial=udid)
    try:
        # Cancelling asyncio.to_thread does not stop its XPC work. Let SDK open
        # finish before closing, so it cannot create an assertion after cleanup.
        await finish_on_cancel(tunnel.aopen())
    except BaseException:
        await tunnel.aclose()
        raise
    return tunnel


async def discover() -> list[Device]:
    from pymobiledevice3 import usbmux
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.remote.native_tunnel import browse_native_devices

    # Collect native deviceFound events before taking the usbmux snapshot. One
    # source failing must not hide devices reported by the other source.
    LOGGER.info(tr("discovering_native"))
    try:
        native_entries = await finish_on_cancel(browse_native_devices(timeout=DISCOVERY_SECONDS))
    except Exception as exc:
        LOGGER.warning(tr("discovery_failed", source="remotepairingd", error=error_detail(exc)))
        native_entries = []
    native_udids = {entry["udid"] for entry in native_entries
                    if isinstance(entry.get("udid"), str) and entry["udid"]}
    LOGGER.info(tr("native_count", count=len(native_udids)))

    LOGGER.info(tr("discovering_usbmux"))
    try:
        entries = await asyncio.wait_for(usbmux.list_devices(), CONNECT_TIMEOUT)
    except Exception as exc:
        LOGGER.warning(tr("discovery_failed", source="usbmuxd", error=error_detail(exc)))
        entries = []
    LOGGER.info(tr("usbmux_count", count=len(entries)))
    grouped: dict[str, set[str]] = {}
    for entry in entries:
        if entry.connection_type in {"Network", "USB"}:
            grouped.setdefault(entry.serial, set()).add(entry.connection_type)
    for udid in native_udids:
        grouped.setdefault(udid, set())
    devices: list[Device] = []

    async def describe(udid, transports):
        # Let macOS choose the native transport. Explicit Wi-Fi and USB paths
        # remain fallbacks; a USB connection is never required for wireless use.
        routes = ("Native", "Network", "USB")
        for index, kind in enumerate(routes):
            if (kind == "Native" and udid not in native_udids) or (kind != "Native" and kind not in transports):
                continue
            lockdown = None
            native_tunnel = None
            try:
                try:
                    if kind == "Native":
                        LOGGER.info(tr("native_info", udid=udid))
                        native_tunnel = await open_native_tunnel(udid)
                        provider = native_tunnel.rsd
                        if provider.udid != udid:
                            raise UserError(tr("device_mismatch"))
                    else:
                        lockdown = await asyncio.wait_for(
                            create_using_usbmux(serial=udid, connection_type=kind, autopair=False),
                            CONNECT_TIMEOUT,
                        )
                        verify_transport(lockdown, udid, kind)
                        provider = lockdown
                    info = provider.all_values
                    # Unpaired USB devices may expose ProductType but omit DeviceClass.
                    device_type = info.get("DeviceClass")
                    product_type = info.get("ProductType") or provider.product_type or ""
                    if device_type not in ("iPhone", "iPad") and not re.fullmatch(r"(?:iPhone|iPad)\d+,\d+", str(product_type)):
                        return None
                    name = info.get("DeviceName")
                    system = info.get("ProductVersion")
                    if kind == "Native" and not system:
                        system = provider.peer_info["Properties"].get("OSVersion")
                    if not all(isinstance(value, str) and value.strip() for value in (name, system)):
                        raise UserError(tr("device_info_incomplete", udid=udid))
                    if kind == "Native":
                        requires_pairing = False  # Successful native pairing + RSD handshake.
                    elif lockdown.paired:
                        if lockdown.udid != udid:
                            raise UserError(tr("device_mismatch"))
                        requires_pairing = False
                    elif kind != "USB":
                        raise ConnectionError(tr("network_pairing_required"))
                    else:
                        requires_pairing = True
                    device = Device(
                        udid=udid, name=name, system=system,
                        # Advertised transports, not a connectivity check of every path.
                        transports=tuple(kind for kind in ("Network", "USB") if kind in transports),
                        requires_pairing=requires_pairing,
                        lockdown=lockdown,
                        native_tunnel=native_tunnel,
                        routes=routes[index:],
                    )
                    devices.append(device)
                    lockdown = None  # Ownership moves to the candidate until selection.
                    native_tunnel = None
                    return
                finally:
                    if lockdown is not None:
                        await lockdown.close()
                    if native_tunnel is not None:
                        await native_tunnel.aclose()
            except Exception as exc:
                LOGGER.warning(tr("device_info_failed", udid=udid, transport=kind, error=error_detail(exc)))
                continue
        return None

    try:
        async with asyncio.TaskGroup() as tasks:
            for udid, transports in grouped.items():
                tasks.create_task(describe(udid, transports))
    except BaseException:
        await close_device_connections(devices)
        raise
    devices.sort(key=lambda device: device.udid)
    LOGGER.info(tr("device_count", count=len(devices)))
    return devices


def verify_transport(lockdown, udid: str, transport: str) -> None:
    actual = lockdown.service.mux_device
    if actual is None or actual.connection_type != transport or not actual.matches_udid(udid):
        raise UserError(tr("transport_mismatch"))


async def prepare_pairing(lockdown, udid: str, transport: str) -> None:
    """Use the current validated session, never a saved 'first use' flag."""
    if not lockdown.paired:
        if transport != "USB":
            raise ConnectionError(tr("network_pairing_required"))
        LOGGER.info(tr("pairing_prompt", seconds=PAIR_TIMEOUT))
        try:
            await asyncio.wait_for(lockdown.pair(timeout=PAIR_TIMEOUT), PAIR_TIMEOUT + CONNECT_TIMEOUT)
            if not await asyncio.wait_for(lockdown.validate_pairing(), CONNECT_TIMEOUT):
                raise UserError(tr("pairing_invalid"))
        except UserError:
            raise
        except Exception as exc:
            raise UserError(tr("pairing_failed", error=error_detail(exc))) from exc
        LOGGER.info(tr("pairing_ready"))
    # Pairing can reveal the UDID that an unpaired device omitted earlier.
    if lockdown.udid != udid:
        raise UserError(tr("device_mismatch"))


async def enable_wifi_on_usb(lockdown) -> None:
    """Configure the selected, paired USB device; preserve working wired access."""
    LOGGER.info(tr("wifi_checking"))
    try:
        if await asyncio.wait_for(lockdown.get_enable_wifi_connections(), CONNECT_TIMEOUT):
            LOGGER.info(tr("wifi_already_enabled"))
            return
        LOGGER.info(tr("wifi_enabling"))
        await asyncio.wait_for(lockdown.set_enable_wifi_connections(True), CONNECT_TIMEOUT)
        if not await asyncio.wait_for(lockdown.get_enable_wifi_connections(), CONNECT_TIMEOUT):
            raise UserError(tr("wifi_verify_failed"))
        LOGGER.info(tr("wifi_enabled"))
    except Exception as exc:
        LOGGER.warning(tr("wifi_setup_failed", error=error_detail(exc)))


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
    LOGGER.info(tr("downloading"))
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
                    raise UserError(tr("empty_image"))
                downloaded.append((target, local))
            data = plistlib.loads(downloaded[-1][0].read_bytes())
            if data.get("ProductBuildVersion") != LATEST_DDI_BUILD_ID:
                raise UserError(tr("image_version_changed"))
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
            raise UserError(tr("device_mismatch"))
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
        raise UserError(tr("disconnected"))


class Backend:
    def __init__(self, state):
        self.state = state

    async def prepare_developer_services(self, provider):
        from packaging.version import Version
        from pymobiledevice3.services.mobile_image_mounter import PersonalizedImageMounter

        LOGGER.info(tr("checking_device"))
        if Version(provider.product_version) < Version("17.4"):
            raise UserError(tr("unsupported_os"))
        if not await asyncio.wait_for(provider.get_developer_mode_status(), CONNECT_TIMEOUT):
            raise UserError(tr("developer_mode_disabled"))
        LOGGER.info(tr("checking_image"))
        async with PersonalizedImageMounter(provider) as mounter:
            if await asyncio.wait_for(mounter.is_image_mounted("Personalized"), SERVICE_TIMEOUT):
                return False
            assets = await download_ddi(self.state / "pymobiledevice3" / "Xcode_iOS_DDI_Personalized")
            LOGGER.info(tr("mounting"))
            await asyncio.wait_for(mounter.mount(*assets), 120)
            return True

    async def configure_usb_access(self, device):
        """Prepare future wireless use when USB is available, regardless of the active route."""
        if "USB" not in device.transports:
            return
        from pymobiledevice3.lockdown import create_using_usbmux

        try:
            lockdown = await asyncio.wait_for(
                create_using_usbmux(serial=device.udid, connection_type="USB", autopair=False),
                CONNECT_TIMEOUT,
            )
            try:
                verify_transport(lockdown, device.udid, "USB")
                await prepare_pairing(lockdown, device.udid, "USB")
                await enable_wifi_on_usb(lockdown)
            finally:
                await lockdown.close()
        except Exception as exc:
            LOGGER.warning(tr("usb_access_setup_failed", error=error_detail(exc)))

    @asynccontextmanager
    async def connect_native(self, device):
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

        async with AsyncExitStack() as resources:
            if device.native_tunnel is not None:
                tunnel, device.native_tunnel = device.native_tunnel, None
                LOGGER.info(tr("native_reusing"))
            else:
                LOGGER.info(tr("native_connecting"))
                tunnel = await open_native_tunnel(device.udid)
            resources.push_async_callback(tunnel.aclose)
            rsd = tunnel.rsd
            if rsd.udid != device.udid:
                raise UserError(tr("tunnel_mismatch"))
            await self.configure_usb_access(device)
            mounted = await self.prepare_developer_services(rsd)
            if mounted:
                # RSD advertises a snapshot of services. Reopen after mounting so
                # the new developer services appear in that snapshot.
                LOGGER.info(tr("refreshing_native"))
                await tunnel.aclose()
                tunnel = await open_native_tunnel(device.udid)
                resources.push_async_callback(tunnel.aclose)
                rsd = tunnel.rsd
                if rsd.udid != device.udid:
                    raise UserError(tr("tunnel_mismatch"))
            LOGGER.info(tr("starting_location_service"))
            dvt = await asyncio.wait_for(resources.enter_async_context(DvtProvider(rsd)), SERVICE_TIMEOUT)
            location = await asyncio.wait_for(resources.enter_async_context(LocationSimulation(dvt)), SERVICE_TIMEOUT)
            yield Session(location, dvt, "Native")

    @asynccontextmanager
    async def connect(self, device, transport):
        if transport == "Native":
            async with self.connect_native(device) as session:
                yield session
            return

        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

        async with AsyncExitStack() as resources:
            if device.lockdown is not None:
                lockdown, device.lockdown = device.lockdown, None
                LOGGER.info(tr("reusing_connection", transport=tr("wireless") if transport == "Network" else "USB"))
            else:
                LOGGER.info(tr("connecting", transport=tr("wireless") if transport == "Network" else "USB"))
                lockdown = await asyncio.wait_for(
                    create_using_usbmux(serial=device.udid, connection_type=transport, autopair=False),
                    CONNECT_TIMEOUT,
                )
            resources.push_async_callback(lockdown.close)
            verify_transport(lockdown, device.udid, transport)
            await prepare_pairing(lockdown, device.udid, transport)
            if transport == "USB":
                await enable_wifi_on_usb(lockdown)
            else:
                await self.configure_usb_access(device)
            await self.prepare_developer_services(lockdown)

            LOGGER.info(tr("starting_services"))
            with tunnel_uses(lockdown):
                tunnel = UserspaceRsdTunnel(serial=device.udid, autopair=False, remotepairing_fallback=False)
                rsd = await asyncio.wait_for(resources.enter_async_context(tunnel), SERVICE_TIMEOUT)
                if rsd.udid != device.udid:
                    raise UserError(tr("tunnel_mismatch"))
                dvt = await asyncio.wait_for(resources.enter_async_context(DvtProvider(rsd)), SERVICE_TIMEOUT)
                location = await asyncio.wait_for(resources.enter_async_context(LocationSimulation(dvt)), SERVICE_TIMEOUT)
                yield Session(location, dvt, transport)


async def run_device(device, latitude, longitude, backend, output=print):
    failures = []
    last_error = None
    # Discovery keeps its successful connection and the untried fallback routes.
    transports = device.routes
    for index, transport in enumerate(transports):
        entered = False
        try:
            async with backend.connect(device, transport) as session:
                entered = True
                # Once setting starts, do not switch devices/transports on failure.
                try:
                    output(tr("connected"))
                    await session.set(latitude, longitude)
                    output(tr("location_set", coordinates=colored(f"{latitude}, {longitude}", "1;36")))
                    output(tr("exit_hint", shortcut=colored("Ctrl+C", "1;33")))
                    await session.wait()
                finally:
                    await session.clear()
        except UserError:
            raise
        except Exception as exc:
            if entered:
                raise UserError(tr("session_error", error=error_detail(exc))) from exc
            last_error = exc
            failures.append(f"{transport}: {error_detail(exc)}")
            if index + 1 < len(transports):
                LOGGER.warning(tr("route_fallback", route=transport, error=error_detail(exc),
                                  next_route=transports[index + 1]))
    raise UserError(tr("connect_failed") + "\n" + "\n".join(failures)) from last_error


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
        pass
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main():
    configure_logging()
    parser = CommandParser(prog="fake_position.sh", description=tr("description"), add_help=False)
    parser.add_argument("-h", "--help", action="help", help=tr("help"))
    parser._positionals.title = tr("arguments")
    parser._optionals.title = tr("options")
    parser.add_argument("latitude", type=float, help=tr("latitude_help"))
    parser.add_argument("longitude", type=float, help=tr("longitude_help"))
    args = parser.parse_args()
    for value, limit, label in ((args.latitude, 90, tr("latitude")), (args.longitude, 180, tr("longitude"))):
        if not math.isfinite(value) or not -limit <= value <= limit:
            parser.error(tr("coordinate_error", label=label, minimum=-limit, maximum=limit))
    if sys.platform != "darwin" or sys.version_info < (3, 11):
        parser.error(tr("platform_required"))
    try:
        check_dependencies()
        state = runtime_directory()
        configure_storage(state)
        # Keep discovery streams on the same event loop used by the location session.
        with asyncio.Runner() as runner:
            devices = runner.run(discover())
            try:
                device = select_device(devices)
                runner.run(close_device_connections(candidate for candidate in devices if candidate is not device))
                with device_lock(state, device.udid):
                    runner.run(execute(device, args.latitude, args.longitude, state))
            finally:
                runner.run(close_device_connections(devices))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        LOGGER.error(error_detail(exc), exc_info=not isinstance(exc, UserError) or exc.__cause__ is not None)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
