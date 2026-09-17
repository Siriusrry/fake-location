# fake_position

通过 Mac 为 iPhone / iPad 模拟定位。无线优先，连接失败时自动尝试同一设备的 USB；Ctrl+C 清除模拟定位并退出。

支持 macOS（Apple Silicon / Intel）、Python 3.11+、iOS / iPadOS 17.4+。底层使用 [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)，依赖版本固定在 `requirements.txt`。

## 安装

Python 和依赖由用户自行安装。工具不会安装 Python、创建环境或自动更新依赖。

在自己的 Python 环境中安装依赖：

```sh
pip install -r requirements.txt
```

脚本直接使用当前命令行环境中的 Python。

## 使用

```sh
./fake_position.sh <latitude> <longitude>
```

从其他目录使用时，指定该脚本的路径即可。坐标顺序为纬度、经度，负数坐标可直接传入。

- 只有一台设备时自动选择；多台设备时列出名称、系统版本和设备 ID，让用户选择。
- 同一设备的无线和 USB 连接只列为一台；无线失败后尝试该设备的 USB，不切换到其他设备。
- 设备已配对、已解锁并开启开发者模式后可使用；无线连接还需已启用设备的 Wi-Fi 连接，并与 Mac 在可互通的网络中。
- 信任关系及开发者模式由用户管理，本工具仅检查并提示，不修改这些设置。
- 开发者镜像未挂载时自动下载并挂载，已挂载则直接使用。首次下载和需要 Apple 签名时需能访问互联网。
- 定位期间保持终端命令运行。按 **Ctrl+C**，收到“已清除模拟定位”后，工具关闭连接与隧道并退出。
- 同一设备不允许同时运行两个本工具会话；不同设备可分别在两个终端运行。

未发现设备时会提示：

> 未发现可连接的设备。首次使用请通过数据线配对一次；已配对的设备请确认已解锁，并检查 Wi-Fi 或 USB 连接。

## 文件与退出

使用虚拟环境时，工具的镜像缓存、临时文件和运行锁放在该环境的 `.fake_position/` 下。不用虚拟环境时，放在项目的 `.fake_position/` 下。工具不往 `~/.pymobiledevice3` 写入缓存。

使用虚拟环境时，删除该环境即可删除其中的依赖和本工具运行文件。Python 由用户管理，项目源码单独保留。

工具作为前台进程运行，不启动常驻服务，也不修改 macOS 的系统配置。退出时主动清除模拟定位并等待设备应答，随后释放本会话资源。

## 验证

不连接设备的自动测试：

```sh
python -B -m unittest discover -s tests -v
```

