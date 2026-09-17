# fake_position

[English](README.md) | 简体中文

通过 Mac 为 iPhone / iPad 模拟定位。无线优先，连接失败时自动尝试同一设备的 USB；Ctrl+C 清除模拟定位并退出。

支持 macOS（Apple Silicon / Intel）、Python 3.11+、iOS / iPadOS 17.4+。底层使用 [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)，依赖版本固定在 `requirements.txt`。

## 安装依赖

```sh
pip install -r requirements.txt
```

如需使用虚拟环境：

```sh
"/path/to/your-venv/bin/python" -m pip install --cache-dir venv/.cache/pip -r requirements.txt
```

使用虚拟环境时，可执行一次以下命令，之后运行本工具无需再手动激活环境：

```sh
"/path/to/your-venv/bin/python" venv_init.py
```

## 使用

```sh
./fake_position.sh <纬度> <经度>
```

- 只有一台设备时自动选择；多台设备时列出名称、系统版本和设备 ID，选择要修改定位的设备。
- 同一设备的无线和有线连接只列为一台；无线失败会自动回退到有线连接。
- 需要设备已配对、已解锁并开启开发者模式，首次使用会提示配对；无线连接还需已启用设备的 Wi-Fi 连接，并与 Mac 在可互通的网络中。

## 缓存与临时文件

工具的镜像缓存、临时文件和运行锁在 `.fake_position/` 下。
