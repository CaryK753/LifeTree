# 本地数据库加密

- 日期：2026-07-31
- 作者：wwj
- 状态：已完成
- 关联：`docs/specs/2026-07-30-local-storage-foundation.md`、
  `docs/specs/2026-07-31-sqlite-schema-migration.md`

## 背景

本地隐私模式承诺"设备为唯一数据权威"，但当前 SQLite 文件明文存储敏感字段：

- `LLMProvider.api_key`：第三方 LLM 服务 API Key（代码注释明确写 "stored in
  plaintext"）。
- `AppConfig`：`tavily_api_key`、`smtp_password` 等敏感配置值。
- `UserPasskey`、`UserPlugin` 等表中的凭据类字段。

若 SQLite 文件被复制（备份泄露、设备丢失、恶意软件），这些密钥直接暴露。
`SystemSecretStore`（keyring 适配器）已实现但尚未被任何业务代码使用。

本设计为本地模式引入应用层字段加密，保护敏感密钥，使 `database` 适配器从
`alpha` 推向 `ready`。

## 目标

- 本地模式下，敏感字段（API Key、密码、token）在写入 SQLite 前加密，读取时
  解密，业务代码无感知。
- 加密主密钥存操作系统 Keychain / Credential Manager（通过 `SystemSecretStore`），
  首次启动自动生成。
- 服务器模式（PostgreSQL）行为不变，不加密，不引入性能开销。
- 加密对业务代码透明：通过 SQLAlchemy `TypeDecorator` 在 ORM 层自动处理。
- 密钥丢失时优雅报错，不静默返回明文。

## 非目标

- 不做全库加密（SQLCipher）。全库加密需 `pysqlcipher3` 依赖，跨平台编译困难，
  且对 SQLAlchemy 兼容性有风险。留作未来演进。
- 不加密用户内容数据（目标、事件、路径等）。这些是用户自己输入的内容，非
  凭据类密钥；sidecar 已有 token 认证保护网络访问。
- 不实现密钥轮换。首次生成后固定使用，轮换需人工迁移。
- 不加密服务器模式的数据。PG 模式下字段保持明文，由 PG 自身的安全机制保护。

## 设计

### 加密原语

用 `cryptography` 库的 `Fernet`（AES-128-CBC + HMAC-SHA256），提供认证加密
（加密 + 完整性校验）。`cryptography` 已是传递依赖（`python-jose[cryptography]`），
显式加入 `pyproject.toml` 的 `local` extras。

`Fernet` 的密钥是 32 字节，base64 编码后 44 字符。加解密结果是 base64 编码的
token 字符串，可安全存入 `Text` 列。

### 主密钥管理

`app/core/local_encryption.py` 提供 `LocalEncryption` 类：

```python
class LocalEncryption:
    """应用层字段加密，密钥存操作系统凭据库。"""

    KEYRING_KEY = "local-db-encryption-key"

    def __init__(self, secret_store: SystemSecretStore) -> None: ...

    def get_or_create_key(self) -> str:
        """从 keyring 读取主密钥；不存在则生成并存入。"""

    def encrypt(self, plaintext: str) -> str:
        """加密明文，返回 base64 token 字符串。空串原样返回。"""

    def decrypt(self, token: str) -> str:
        """解密 token；若解密失败（密钥不匹配/损坏）抛 RuntimeError。"""
```

密钥生命周期：
- 首次启动：`get_or_create_key()` 生成 32 字节随机密钥，存入 keyring。
- 后续启动：从 keyring 读取。
- 密钥丢失（keyring 被清空）：解密现有数据时抛 `RuntimeError`，应用启动失败
  并提示用户。不静默降级为明文。

### EncryptedText TypeDecorator

`app/db/types.py` 定义 SQLAlchemy 类型装饰器：

```python
class EncryptedText(TypeDecorator):
    """Text 字段透明加解密。

    - local 模式：写入时 Fernet 加密，读取时解密。
    - server 模式：透传，不加密。
    - 空值（None / ""）原样存取。
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not value:
            return value
        if get_settings().lifetree_storage_mode != "local":
            return value
        return _get_encryption().encrypt(value)

    def process_result_value(self, value, dialect):
        if not value:
            return value
        if get_settings().lifetree_storage_mode != "local":
            return value
        return _get_encryption().decrypt(value)
```

`_get_encryption()` 返回进程级单例 `LocalEncryption`，避免每次字段访问都
初始化 keyring。

### 应用范围

首批加密的字段（均为凭据类，非用户内容）：

| 模型 | 字段 | 当前类型 |
|---|---|---|
| `LLMProvider` | `api_key` | `Text` |
| `AppConfig` | `value`（按 key 名判断） | `Text` |

`AppConfig.value` 是通用 key-value 存储，只对 key 名匹配 `*_api_key`、
`*_password`、`*_token`、`*_secret` 的条目加密。判断在 TypeDecorator 的
`process_bind_param` / `process_result_value` 中无法做（装饰器不知道行级 key
名），因此 `AppConfig` 的加密在业务层（`app/llm/registry.py` 等读写处）显式
调用 `LocalEncryption.encrypt/decrypt`，不用 TypeDecorator。

`LLMProvider.api_key` 用 `EncryptedText` 类型装饰器，业务代码无感知。

### 启动初始化

`initialize_local_database()` 在迁移完成后、图重建前，初始化 `LocalEncryption`
单例（调用 `get_or_create_key()` 确保密钥就绪）。若 keyring 不可用（无
`keyring` 包或无后端），抛 `RuntimeError` 中止启动——本地隐私模式不允许无加密
运行。

### 密文格式识别

加密后的值以 `gAAAAA` 开头（Fernet token 的 base64 前缀）。`decrypt` 方法
检查此前缀判断值是否已加密，避免对明文值调用解密（支持从明文库平滑升级：
旧明文值读取时原样返回，下次写入时自动加密）。

## 边界

- 加密只保护 at-rest 的 SQLite 文件；运行时内存中仍是明文。
- 主密钥存 keyring，若 keyring 后端不可用（headless Linux 无 D-Bus 等），
  本地隐私模式不可启动。
- 密钥与数据库文件绑定：复制 SQLite 文件到另一台机器无法解密（keyring 不
  随文件迁移）。这是预期行为（防止文件泄露）。
- 不支持密钥轮换；若需轮换，需导出数据、删旧库、用新密钥重建。
- 加密字段在 SQL 查询中不可索引或 WHERE 匹配（密文不可比）。

## 验证计划

- 单元测试（`tests/test_local_encryption.py`）：
  - 密钥生成与 keyring 往返。
  - 加解密往返：明文 → 加密 → 解密 = 原文。
  - 空值处理：`None` / `""` 不加密。
  - 密钥不匹配解密失败抛异常。
  - 明文值识别：`decrypt` 对非 Fernet token 的明文原样返回（升级兼容）。
  - 模式切换：`server` 模式下 `EncryptedText` 透传。
- 集成测试：`local` 模式下写入 `LLMProvider` 后，直接查 SQLite 文件确认
  `api_key` 列存的是密文而非明文。
- 现有 `test_local_app_boots_without_server_infrastructure` 仍通过。

## 后续演进

- 全库加密：集成 `sqlcipher3-binary` 或 `pysqlcipher3`，替换 SQLite engine
  为加密引擎。届时可移除应用层字段加密（TypeDecorator 改回 `Text`）。
- 密钥轮换：实现 `rotate_key()` 命令，重新加密所有敏感字段。
- 备份恢复：`.lifetree` 归档包含加密数据，恢复时需同一 keyring 或导入密钥。

## 完成结果

- `app/core/local_encryption.py` 实现 `LocalEncryption` 类（Fernet 加解密 +
  keyring 密钥管理 + env var fallback）。
- 密钥解析顺序：`LIFETREE_LOCAL_ENCRYPTION_KEY` env var（测试/headless）→
  OS 凭据库（`SystemSecretStore`，桌面默认）→ 均不可用则拒绝启动。
- `app/models/types.py` 增加 `EncryptedText` TypeDecorator：`local` 模式下
  写入加密、读取解密；`server` 模式透传；空值原样存取。
- `LLMProvider.api_key` 字段改用 `EncryptedText`，业务代码无感知。
- `AppConfig` 敏感 key 的 value 在 `app/llm/registry.py` 业务层显式加解密
  （`_encode_app_config_value` / `_decode_app_config_value`）。覆盖的 key：
  `tavily_api_key`、`mineru_api_key`、`smtp_password`。非敏感 key（`smtp_host`、
  `smtp_port`、`role_assignments` 等）保持明文，便于排查。
- `OAuthProvider.client_secret` 在 `set_oauth_providers` / `get_oauth_providers`
  中按字段加密：只加密每个 provider 的 `client_secret`，其余字段（client_id、
  URLs、scopes）保持明文。`_encrypt_oauth_providers_payload` /
  `_decrypt_oauth_provider_entry` 处理加解密。
- `initialize_local_database()` 启动时调用 `ensure_encryption_available()`
  确保密钥就绪，否则中止启动。
- 密文格式识别（`gAAAAA` 前缀）支持从明文库平滑升级：旧明文值读取时原样
  返回，下次写入时自动加密（`test_registry_plaintext_db_upgrades_on_next_write`
  覆盖此路径）。
- `pyproject.toml` 的 `local`/`desktop` extras 显式声明 `cryptography>=42.0`。
- `database` 适配器状态从 `alpha` 升为 `ready`，`backend` 改为
  `sqlite_migrations_encrypted`。

## 验证

- `tests/test_local_encryption.py` 22 项全过：
  - 基础加解密往返、密钥持久化、env var 优先级、空值处理、幂等性、明文升级
    兼容、密钥不匹配报错、格式错误报错。
  - `EncryptedText` 在 local/server 模式下的行为。
  - `LLMProvider.api_key` 集成测试（直接查 SQLite 文件确认存的是密文）。
  - `AppConfig` 敏感 key 加解密往返、空值跳过、server 模式透传、非敏感 key
    不加密、明文 legacy 行兼容、None 默认值。
  - `OAuthProvider.client_secret` 集成测试：加密后 DB 中是密文、读取时还原
    明文；明文 legacy secret 读取兼容。
  - 端到端：`save_config` + `load_config` 往返 `tavily_api_key` /
    `mineru_api_key` / `smtp_password`；明文库再保存时自动加密。
- 后端全量测试 103 passed，`test_desktop_sidecar` 端到端验证仍通过（子进程
  设置 `LIFETREE_LOCAL_ENCRYPTION_KEY`）。
