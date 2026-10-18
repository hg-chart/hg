# -*- coding: utf-8 -*-
"""Cloudflare R2 存储桶专用操作模块（按“当前会话选中的工厂”隔离）

隔离原则（重要）：
  - 本模块不再使用任何全局变量保存“当前工厂”。每次读写 R2，都从
    st.session_state["selected_factory"] 取当前浏览器会话自己的工厂，
    因此多人同时使用不同工厂、或同一人开多个窗口，都不会互相串数据。
  - 没有选中工厂时，一律拒绝访问 R2（宁可报错，也不写到别的工厂里）。
  - 任何指向其他工厂或系统目录（device-monitor/ 开头但不是当前工厂）的 Key 都会被拒绝。

R2 内的存放约定（与已有数据兼容）：
  device-monitor/<工厂>/uploaded_vault/<文件名>       数据文件
  device-monitor/<工厂>/file_trash_vault/<文件名>     文件回收站
  device-monitor/<工厂>/chart_history/<方案>/<图片>   历史图表
"""

import logging
import os
import shutil
from pathlib import Path

import streamlit as st

ROOT_PREFIX = "device-monitor/"
DATA_EXTS = (".csv", ".xlsx", ".xls")
VAULT_KEY_DIR = "uploaded_vault"
TRASH_KEY_DIR = "file_trash_vault"

# 仅为兼容旧代码保留；已不再起任何作用（赋值给它不会改变访问的工厂）。
BASE_PREFIX = ROOT_PREFIX

_R2_CLIENT = None
_R2_READY = False
_R2_ERROR = ""


# ------------------------------------------------------------
# 当前工厂 / 前缀（来自会话，不是全局）
# ------------------------------------------------------------
def current_factory():
  return st.session_state.get("selected_factory")


def _get_active_prefix():
  factory = current_factory()
  if not factory or "/" in str(factory) or str(factory).startswith("_"):
    raise RuntimeError("当前没有选中有效的工厂，已拒绝访问 R2，防止数据串到其他工厂。")
  return f"{ROOT_PREFIX}{factory}/"


def vault_key(name):
  return f"{VAULT_KEY_DIR}/{name}"


def trash_key(name):
  return f"{TRASH_KEY_DIR}/{name}"


# ------------------------------------------------------------
# 客户端
# ------------------------------------------------------------
def _get_r2_client():
  global _R2_CLIENT, _R2_READY, _R2_ERROR
  if _R2_CLIENT is not None:
    return _R2_CLIENT
  try:
    account_id = str(st.secrets["R2_ACCOUNT_ID"]).strip()
    access_key = str(st.secrets["R2_ACCESS_KEY_ID"]).strip()
    secret_key = str(st.secrets["R2_SECRET_ACCESS_KEY"]).strip()
    bucket = str(st.secrets["R2_BUCKET_NAME"]).strip()
    endpoint = str(
        st.secrets.get(
            "R2_ENDPOINT", f"https://{account_id}.r2.cloudflarestorage.com"
        )
    ).strip()
    if not all([account_id, access_key, secret_key, bucket]):
      raise ValueError("R2 配置项不能为空")
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )

    # get_object / delete_object 的 Key 统一经过 _r2_key 清洗并加上“当前会话工厂”的前缀，
    # 同时拒绝指向其他工厂的 Key。
    orig_get_object = client.get_object

    def safe_get_object(*args, **kwargs):
      if "Key" in kwargs:
        kwargs["Key"] = _r2_key(kwargs["Key"])
      return orig_get_object(*args, **kwargs)

    client.get_object = safe_get_object

    orig_delete_object = client.delete_object

    def safe_delete_object(*args, **kwargs):
      if "Key" in kwargs:
        kwargs["Key"] = _r2_key(kwargs["Key"])
      return orig_delete_object(*args, **kwargs)

    client.delete_object = safe_delete_object

    _R2_CLIENT = client
    _R2_READY = True
    _R2_ERROR = ""
    return _R2_CLIENT
  except Exception as exc:  # noqa: BLE001
    _R2_ERROR = str(exc)
    _R2_READY = False
    return None


def get_r2_error():
  return _R2_ERROR


def _r2_bucket():
  return str(st.secrets["R2_BUCKET_NAME"]).strip()


def _r2_key(local_path_or_key):
  """把本地路径或相对 Key 变成真实 R2 Key：一律落在“当前会话工厂”的目录下。"""
  value = str(local_path_or_key).replace("\\", "/").lstrip("/")
  current_prefix = _get_active_prefix()
  if value.startswith(current_prefix):
    return value
  if value.startswith(ROOT_PREFIX):
    raise ValueError(f"拒绝访问其他工厂或系统目录的对象：{value}")
  for legacy in ("x/", "dummy/"):
    if value.startswith(legacy) and value != legacy:
      value = value[len(legacy):]
  return current_prefix + value.lstrip("/")


# ------------------------------------------------------------
# 基本读写
# ------------------------------------------------------------
def r2_upload_file(local_path, key=None):
  client = _get_r2_client()
  if client is None:
    return False
  try:
    full_key = _r2_key(key or local_path)
    client.upload_file(str(local_path), _r2_bucket(), full_key)
    return True
  except Exception as exc:  # noqa: BLE001
    logging.exception("上传到 Cloudflare R2 失败：%s", exc)
    return False


def r2_delete_key(key):
  client = _get_r2_client()
  if client is None:
    return False
  try:
    client.delete_object(Bucket=_r2_bucket(), Key=key)
    return True
  except Exception as exc:  # noqa: BLE001
    logging.exception("删除 Cloudflare R2 对象失败：%s", exc)
    return False


def _list_all_keys(client, prefix):
  keys, token = [], None
  while True:
    kwargs = {"Bucket": _r2_bucket(), "Prefix": prefix}
    if token:
      kwargs["ContinuationToken"] = token
    response = client.list_objects_v2(**kwargs)
    keys.extend(item["Key"] for item in response.get("Contents", []))
    if not response.get("IsTruncated"):
      return keys
    token = response.get("NextContinuationToken")


def _classify(rel):
  """按相对路径把对象分为 chart / trash / vault；其他（如 json 元数据）返回 None。"""
  parts = rel.split("/")
  name = parts[-1]
  if not name:
    return None
  if "chart_history" in parts[:-1]:
    return "chart"
  if not name.lower().endswith(DATA_EXTS):
    return None
  if any("trash" in p.lower() for p in parts[:-1]):
    return "trash"
  return "vault"


def r2_delete_files_by_name(name, trash=False):
  """在“当前工厂”目录内，删除所有同名数据文件（不管历史上以哪种路径存放）。返回删除个数。"""
  client = _get_r2_client()
  if client is None:
    return 0
  try:
    prefix = _get_active_prefix()
    wanted = "trash" if trash else "vault"
    deleted = 0
    for key in _list_all_keys(client, prefix):
      rel = key[len(prefix):]
      if rel.split("/")[-1] == name and _classify(rel) == wanted:
        client.delete_object(Bucket=_r2_bucket(), Key=key)
        deleted += 1
    return deleted
  except Exception as exc:  # noqa: BLE001
    logging.exception("按文件名删除 R2 对象失败：%s", exc)
    return 0


def r2_list_keys():
  """列出“当前工厂”目录下的对象（图表 Key 以 x/ 开头，配合 cloud_chart_manager 的解析）。"""
  client = _get_r2_client()
  if client is None:
    return None
  try:
    prefix = _get_active_prefix()
    keys = []
    for k in _list_all_keys(client, prefix):
      rel = k[len(prefix):]
      keys.append("x/" + rel if "chart_history/" in rel else rel)
    return keys
  except Exception as exc:  # noqa: BLE001
    logging.exception("列举 Cloudflare R2 对象失败：%s", exc)
    return None


# ------------------------------------------------------------
# 同步：本地目录 = 当前工厂在 R2 里的数据
# ------------------------------------------------------------
def sync_local_storage_with_r2(vault_dir, file_trash_dir, chart_history_dir):
  """让本地文件库与“当前工厂”的 R2 目录一致。

  - R2 有、本地没有的数据文件：下载。
  - 本地有、R2 里没有的数据文件：不属于当前工厂的云端数据（可能是历史上串进来的），
    不会被删除，而是移入 _quarantine_<工厂>/ 隔离区，并记录到
    st.session_state["_sync_quarantined"]，由页面提示。
  - 历史图表不再下载到本地（页面直接从 R2 读取），避免多个工厂的图表混在同一目录。
  """
  client = _get_r2_client()
  if client is None:
    return False
  try:
    prefix = _get_active_prefix()
    factory = current_factory()
    all_keys = _list_all_keys(client, prefix)
  except Exception:  # noqa: BLE001
    logging.exception("同步前列举 R2 对象失败")
    return False

  for d in (vault_dir, file_trash_dir, chart_history_dir):
    os.makedirs(d, exist_ok=True)

  want = {"vault": {}, "trash": {}}
  for key in all_keys:
    rel = key[len(prefix):]
    kind = _classify(rel)
    if kind in want:
      want[kind].setdefault(rel.split("/")[-1], key)

  for kind, local_dir in (("vault", vault_dir), ("trash", file_trash_dir)):
    for name, key in want[kind].items():
      target = Path(local_dir) / name
      if target.exists():
        continue
      try:
        data = client.get_object(Bucket=_r2_bucket(), Key=key)["Body"].read()
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
      except Exception:  # noqa: BLE001
        logging.exception("从 R2 下载失败：%s", key)

  quarantine_root = Path(f"_quarantine_{factory}")
  moved = []
  for kind, local_dir in (("vault", vault_dir), ("trash", file_trash_dir)):
    for item in Path(local_dir).iterdir():
      if (
          item.is_file()
          and item.name.lower().endswith(DATA_EXTS)
          and item.name not in want[kind]
      ):
        dest_dir = quarantine_root / Path(local_dir).name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / item.name
        if dest.exists():
          dest.unlink()
        shutil.move(str(item), str(dest))
        moved.append(item.name)

  st.session_state[f"_sync_quarantined_{factory}"] = moved
  return True
