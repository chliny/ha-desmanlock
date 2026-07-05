# Desman Lock

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5?logo=home-assistant-community-store&logoColor=white)](https://hacs.xyz/)
[![GitHub Release](https://img.shields.io/github/v/release/chliny/ha-desmanlock)](https://github.com/chliny/ha-desmanlock/releases)

将德施曼智能锁接入 Home Assistant。集成通过德施曼云端接口获取门锁状态、开门记录、设备信息及抓拍图片，并提供动态密码和数字密码管理服务。

## 功能

- 通过 Home Assistant 界面完成账号登录和门锁选择
- 每 30 秒从云端更新一次设备数据
- 展示门锁状态和最近开门信息
- 展示门锁、猫眼电量及网络状态
- 展示指纹、门卡、人脸和临时授权等统计信息
- 展示最近开门抓拍及最多 5 张安防告警抓拍
- 获取动态密码
- 查询、添加和更新数字密码

### 实体

| 类型 | 实体 |
| --- | --- |
| 门锁 | 门锁状态、最近开门用户及开门记录等属性 |
| 图像 | 最近开门抓拍、最多 5 张安防告警抓拍 |
| 传感器 | 门锁电量、猫眼电量、电池状态、最近开门用户、开门方式、开门时间、开门日志、网络信号 |
| 诊断传感器 | Wi-Fi、网络模式、软件版本、家庭成员、临时授权、指纹、门卡、人脸及门铃音量等信息 |

部分实体是否有值取决于门锁型号、硬件能力和云端返回的数据。

> [!NOTE]
> 门锁实体当前仅用于展示云端推断的状态。远程上锁和远程开锁均未实现。

## 安装

### 通过 HACS 安装（推荐）

1. 确保 Home Assistant 已安装 [HACS](https://hacs.xyz/docs/use/download/download/)。
2. 打开 HACS，进入 **集成**。
3. 打开右上角菜单，选择 **自定义存储库**。
4. 添加存储库地址 `https://github.com/chliny/ha-desmanlock`，类别选择 **集成**。
5. 搜索并安装 **Desman Lock**。
6. 重启 Home Assistant。

后续版本可直接通过 HACS 更新。

### 手动安装

1. 下载本项目的最新 Release，或克隆本仓库。
2. 将 `custom_components/desmanlock` 目录复制到 Home Assistant 配置目录下的 `custom_components`：

   ```text
   <config>/custom_components/desmanlock/
   ```

3. 确认目录中包含 `manifest.json`、`config_flow.py` 等文件。
4. 重启 Home Assistant。

最终目录结构应类似：

```text
config/
└── custom_components/
    └── desmanlock/
        ├── __init__.py
        ├── manifest.json
        └── ...
```

## 配置

1. 进入 **设置 → 设备与服务**。
2. 点击 **添加集成**。
3. 搜索 **Desman Lock** 或 **德施曼智能锁**。
4. 输入德施曼账号手机号、密码和区域 ID。中国大陆账号通常保持默认区域 ID `1`。
5. 如果账号绑定了多把门锁，选择需要接入的门锁。再次添加集成并选择其他门锁，即可将同一账号下的多把门锁全部接入。

## 服务

集成提供以下服务，可在 **开发者工具 → 操作** 中调用。所有服务都会返回响应数据；在自动化或脚本中调用时，请使用 `response_variable` 接收结果。

| 服务 | 说明 | 主要参数 |
| --- | --- | --- |
| `desmanlock.get_dynamic_password` | 获取动态密码 | `lock_id`（可选） |
| `desmanlock.get_digit_passwords` | 获取数字密码列表 | `lock_id`（可选） |
| `desmanlock.add_digit_password` | 添加数字密码 | `real_time_switch`、`range_time`、`remarks`、`alarm_switch` |
| `desmanlock.update_digit_password` | 更新数字密码 | `id`、`real_time_switch`、`range_time`、`state`、`remarks` |

未指定 `lock_id` 时，服务默认操作当前配置项所选择的门锁。

获取动态密码示例：

```yaml
action: desmanlock.get_dynamic_password
data: {}
response_variable: desman_password
```

密码管理会直接修改云端数据。调用添加或更新服务前，请确认参数含义及有效时间格式与德施曼 App 当前使用的格式一致。

## 已知限制

- 依赖德施曼云端和网络连接，无法离线工作。
- 使用未公开的云端接口；德施曼更新服务后，集成可能需要同步适配。
- 门锁状态根据最近一条开门/自动上锁记录推断，可能与门锁实时物理状态存在延迟或差异。
- 当前不支持通过 Home Assistant 远程上锁或开锁。

## 故障排查

- 添加集成失败时，先确认手机号、密码、区域 ID 正确，并确认德施曼 App 可正常登录。
- 实体暂时不可用时，检查 Home Assistant 是否可以访问 `nyuwa.dsmxp.com`。
- 某些传感器或图像无数据通常表示当前门锁型号或云端响应未提供相应字段。
- 如需提交问题，请附上 Home Assistant 版本、集成版本、门锁型号和已脱敏的相关日志。请勿公开账号、密码、动态密码、数字密码、Token 或门锁 ID。

### 开启 Debug 日志

在 Home Assistant 中进入“设置 → 设备与服务 → 集成”，打开“德施曼智能锁”集成页面，在右上角菜单中选择“启用调试日志记录”。重新操作以复现问题后，再次打开菜单并选择“禁用调试日志记录”，Home Assistant 会自动下载调试日志文件。

也可以在 `configuration.yaml` 中添加以下配置并重启 Home Assistant：

```yaml
logger:
  logs:
    custom_components.desmanlock: debug
```

问题排查结束后，建议删除以上配置或将日志级别恢复为 `info`，避免产生过多日志。

## 免责声明

使用本集成产生的风险由使用者自行承担。请妥善保护 Home Assistant 实例及德施曼账号，尤其是在使用密码管理服务时。