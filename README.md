# fake_position

English | [简体中文](README.zh-CN.md)

Simulate the location of an iPhone or iPad from a Mac. Wireless connections are preferred, with automatic USB fallback for the same device. Press Ctrl+C to clear the simulated location and exit.

Supports macOS (Apple Silicon / Intel), Python 3.11+, and iOS / iPadOS 17.4+. Powered by [pymobiledevice3](https://github.com/doronz88/pymobiledevice3), with dependency versions pinned in `requirements.txt`.

## Installation

Install Python and dependencies yourself. The tool does not install Python, create environments, or update dependencies automatically.

Install the dependencies in your own Python environment:

```sh
pip install -r requirements.txt
```

The script uses Python from your current shell environment.

## Usage

```sh
./fake_position.sh <latitude> <longitude>
```

To run from another directory, specify the path to the script. Pass latitude first, then longitude. Negative coordinates are accepted directly.

- A single device is selected automatically. When multiple devices are found, their names, OS versions, and device IDs are listed so you can choose the target.
- Wireless and wired connections to the same device appear as one device. If the wireless connection fails, the tool automatically falls back to a wired connection.
- The device must be paired, unlocked, and have Developer Mode enabled. The tool prompts you to pair it on first use. Wireless access also requires Wi-Fi connections to be enabled on the device and a network connection that can reach the Mac.
- Keep the command running while using the simulated location. Press **Ctrl+C** to clear it; once the clear request is acknowledged, the tool closes the connection and tunnel, then exits.

## Cache and temporary files

The tool stores its disk image cache, temporary files, and runtime locks under `.fake_position/`.
