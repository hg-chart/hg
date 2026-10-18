# -*- coding: utf-8 -*-
"""工厂注册表：以 Cloudflare R2 为唯一权威来源，Streamlit 页面只是它的镜像。

R2 目录约定（与原有数据位置完全兼容）：
  device-monitor/_system/factories.json     工厂注册表 {"active": [...], "trash": [...]}
  device-monitor/<工厂名>/factory_info.json  新增工厂时写入的目录标记（让 R2 控制台里能看到该工厂）
  device-monitor/<工厂名>/...               该工厂自己的全部数据（原有位置，不变）

本模块自己创建 R2 客户端，并且所有读写都使用完整、明确的 Key，
不依赖 r2_storage.BASE_PREFIX 这个全局变量，因此不会受“当前选中哪个工厂”的影响。
"""

import json
import logging
import os
import re
import time

import streamlit as st

ROOT_PREFIX = "device-monitor/"
SYSTEM_DIR = "_system"
REGISTRY_KEY = f"{ROOT_PREFIX}{SYSTEM_DIR}/factories.json"
LOCAL_REGISTRY_FILE = "factory_registry.json"  # R2 不可用时的本地后备
FACTORY_INFO_NAME = "factory_info.json"

_NAME_RE = re.compile(r"^(?!_)[\w\-\.\(\)（） ]{1,50}$")


# ------------------------------------------------------------
# R2 客户端
# ------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _build_client():
  """返回 (client, bucket, error)。未配置或失败时 client 为 None。"""
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
    return client, bucket, ""
  except Exception as exc:  # noqa: BLE001
    return None, None, str(exc)


def r2_available():
  client, _bucket, _err = _build_client()
  return client is not None


def _err_code(exc):
  try:
    return str(exc.response.get("Error", {}).get("Code", ""))
  except Exception:  # noqa: BLE001
    return ""


# ------------------------------------------------------------
# 通用读写（完整 Key，不经过任何全局前缀）
# ------------------------------------------------------------
def factory_prefix(factory):
  return f"{ROOT_PREFIX}{factory}/"


def put_text(key, text):
  """写入文本对象。返回 (ok, err)。R2 未连接时返回 (True, "offline")。"""
  client, bucket, _err = _build_client()
  if client is None:
    return True, "offline"
  try:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    return True, ""
  except Exception as exc:  # noqa: BLE001
    logging.exception("写入 R2 失败：%s", key)
    return False, str(exc)


def get_text(key):
  """读取文本对象。返回 (status, text)，status: ok / missing / error / offline。"""
  client, bucket, _err = _build_client()
  if client is None:
    return "offline", None
  try:
    obj = client.get_object(Bucket=bucket, Key=key)
    return "ok", obj["Body"].read().decode("utf-8")
  except Exception as exc:  # noqa: BLE001
    if _err_code(exc) in ("NoSuchKey", "404", "NotFound"):
      return "missing", None
    logging.exception("读取 R2 失败：%s", key)
    return "error", str(exc)


def delete_prefix(prefix):
  """删除某个前缀下的全部对象。返回 (ok, 删除数量, err)。"""
  client, bucket, _err = _build_client()
  if client is None:
    return True, 0, "offline"
  if not prefix.startswith(ROOT_PREFIX) or not prefix.endswith("/"):
    return False, 0, f"拒绝删除不安全的前缀：{prefix}"
  try:
    paginator = client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
      for obj in page.get("Contents", []):
        keys.append({"Key": obj["Key"]})
    deleted = 0
    for i in range(0, len(keys), 1000):
      batch = keys[i : i + 1000]
      resp = client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
      errors = resp.get("Errors") or []
      if errors:
        return False, deleted, f"{len(errors)} 个对象删除失败：{errors[0]}"
      deleted += len(batch)
    return True, deleted, ""
  except Exception as exc:  # noqa: BLE001
    logging.exception("删除 R2 前缀失败：%s", prefix)
    return False, 0, str(exc)


# ------------------------------------------------------------
# 工厂名校验
# ------------------------------------------------------------
def validate_factory_name(name):
  name = (name or "").strip()
  if not name:
    return False, "工厂名称不能为空！"
  if ".." in name or not _NAME_RE.match(name):
    return False, (
        "工厂名称只能包含文字、数字、空格和 - _ . ( )，长度不超过 50，"
        "且不能以下划线开头、不能包含 / 或 \\。"
    )
  return True, ""


# ------------------------------------------------------------
# 注册表
# ------------------------------------------------------------
def _norm_list(value):
  out = []
  if isinstance(value, list):
    for item in value:
      if isinstance(item, str):
        item = item.strip()
        if item and item not in out:
          out.append(item)
  return out


def _normalize(data):
  if not isinstance(data, dict):
    return {"active": [], "trash": []}
  active = _norm_list(data.get("active"))
  trash = [t for t in _norm_list(data.get("trash")) if t not in active]
  return {"active": active, "trash": trash}


def _load_local():
  if os.path.exists(LOCAL_REGISTRY_FILE):
    try:
      with open(LOCAL_REGISTRY_FILE, "r", encoding="utf-8") as f:
        return _normalize(json.load(f))
    except Exception:  # noqa: BLE001
      pass
  return {"active": [], "trash": []}


def _save_local(reg):
  try:
    with open(LOCAL_REGISTRY_FILE, "w", encoding="utf-8") as f:
      json.dump(reg, f, ensure_ascii=False, indent=2)
  except Exception:  # noqa: BLE001
    pass


def _discover(client, bucket):
  """首次启用时：从 R2 现有目录发现工厂（只在注册表不存在时执行一次）。失败返回 None。"""
  try:
    names = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=bucket, Prefix=ROOT_PREFIX, Delimiter="/"
    ):
      for cp in page.get("CommonPrefixes", []):
        name = cp["Prefix"][len(ROOT_PREFIX):].strip("/")
        if name and not name.startswith("_") and name not in names:
          names.append(name)
    return {"active": names, "trash": []}
  except Exception:  # noqa: BLE001
    logging.exception("从 R2 发现工厂目录失败")
    return None


def save_registry(reg):
  """保存注册表到 R2（并留本地副本）。返回 (ok, err)；R2 未连接时 (True, "offline")。"""
  reg = _normalize(reg)
  payload = dict(reg)
  payload["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
  _save_local(reg)
  return put_text(REGISTRY_KEY, json.dumps(payload, ensure_ascii=False, indent=2))


def load_registry():
  """读取最新注册表。返回 (registry 或 None, 状态)。
  状态：ok / bootstrap（首次，从 R2 目录发现）/ offline（R2 未连接，用本地后备）/ error:xxx
  """
  client, bucket, _err = _build_client()
  if client is None:
    return _load_local(), "offline"
  status, text = get_text(REGISTRY_KEY)
  if status == "ok":
    try:
      reg = _normalize(json.loads(text))
      _save_local(reg)
      return reg, "ok"
    except Exception as exc:  # noqa: BLE001
      return None, f"error:注册表内容损坏：{exc}"
  if status == "missing":
    reg = _discover(client, bucket)
    if reg is None:
      return None, "error:无法列出 R2 目录"
    ok, err = save_registry(reg)
    if not ok:
      return None, f"error:{err}"
    return reg, "bootstrap"
  return None, f"error:{text}"


def _mutate(op):
  """读最新 -> 修改 -> 写回，避免覆盖其他管理员的改动。返回 (ok, msg, registry)。"""
  reg, status = load_registry()
  if reg is None:
    return False, f"无法读取云端工厂列表（{status}）", None
  ok, msg = op(reg)
  if not ok:
    return False, msg, reg
  sok, serr = save_registry(reg)
  if not sok:
    return False, f"写入云端工厂列表失败：{serr}", reg
  if serr == "offline":
    msg += "（R2 未连接，仅保存在本地，重启后会丢失）"
  return True, msg, reg


def add_factory(name):
  name = (name or "").strip()
  ok, msg = validate_factory_name(name)
  if not ok:
    return False, msg, None

  def op(reg):
    if name in reg["active"] or name in reg["trash"]:
      return False, "该工厂已存在或已在回收站中！"
    reg["active"].append(name)
    return True, f"已成功添加工厂：{name}"

  ok, msg, reg = _mutate(op)
  if ok:
    info = json.dumps(
        {"factory": name, "created": time.strftime("%Y-%m-%d %H:%M:%S")},
        ensure_ascii=False,
    )
    mok, merr = put_text(f"{factory_prefix(name)}{FACTORY_INFO_NAME}", info)
    if not mok:
      msg += f"（注意：R2 目录标记写入失败：{merr}）"
  return ok, msg, reg


def move_to_trash(name):
  def op(reg):
    if name not in reg["active"]:
      return False, f"工厂【{name}】不在活跃列表中。"
    if len(reg["active"]) <= 1:
      return False, "至少需要保留一个活跃工厂！"
    reg["active"].remove(name)
    reg["trash"].append(name)
    return True, f"工厂【{name}】已移入回收站（R2 云端数据完整保留）"

  return _mutate(op)


def restore_factory(name):
  def op(reg):
    if name not in reg["trash"]:
      return False, f"工厂【{name}】不在回收站中。"
    reg["trash"].remove(name)
    reg["active"].append(name)
    return True, f"工厂【{name}】已恢复！"

  return _mutate(op)


def purge_factory(name):
  """彻底删除：先清空 R2 上该工厂的全部数据，成功后才从注册表移除。"""
  reg, status = load_registry()
  if reg is None:
    return False, f"无法读取云端工厂列表（{status}）", None
  if name not in reg["trash"] and name not in reg["active"]:
    return False, f"工厂【{name}】不存在。", reg
  ok, count, err = delete_prefix(factory_prefix(name))
  if not ok:
    return False, f"删除 R2 数据失败，工厂已保留：{err}", reg
  if name in reg["trash"]:
    reg["trash"].remove(name)
  if name in reg["active"]:
    reg["active"].remove(name)
  sok, serr = save_registry(reg)
  if not sok:
    return False, f"R2 数据已删除，但更新工厂列表失败：{serr}", reg
  note = "（R2 未连接，未删除云端数据）" if err == "offline" else f"（已删除 {count} 个 R2 对象）"
  return True, f"工厂【{name}】已彻底删除{note}", reg


# ------------------------------------------------------------
# 数据隔离检查（管理员用）：看各工厂 R2 目录里有哪些文件，以及哪些文件同时出现在多个工厂
# ------------------------------------------------------------
def scan_factory_files():
  """返回 (结果, 错误)。结果：{"factories": {工厂: {"vault": [...], "trash": [...], "charts": 数量}},
  "duplicates": {文件名: [工厂, ...]}}。R2 未连接或失败时结果为 None。"""
  client, bucket, _err = _build_client()
  if client is None:
    return None, "R2 未连接"
  try:
    paginator = client.get_paginator("list_objects_v2")
    factories = {}
    for page in paginator.paginate(Bucket=bucket, Prefix=ROOT_PREFIX):
      for obj in page.get("Contents", []):
        rel = obj["Key"][len(ROOT_PREFIX):]
        factory, _, sub = rel.partition("/")
        if not factory or factory.startswith("_") or not sub:
          continue
        parts = sub.split("/")
        name = parts[-1]
        entry = factories.setdefault(factory, {"vault": [], "trash": [], "charts": 0})
        if "chart_history" in parts[:-1]:
          entry["charts"] += 1
        elif name.lower().endswith((".csv", ".xlsx", ".xls")):
          kind = "trash" if any("trash" in p.lower() for p in parts[:-1]) else "vault"
          if name not in entry[kind]:
            entry[kind].append(name)
    owners = {}
    for factory, entry in factories.items():
      for name in set(entry["vault"]) | set(entry["trash"]):
        owners.setdefault(name, []).append(factory)
    duplicates = {n: sorted(f) for n, f in owners.items() if len(f) > 1}
    return {"factories": factories, "duplicates": duplicates}, ""
  except Exception as exc:  # noqa: BLE001
    logging.exception("扫描 R2 工厂目录失败")
    return None, str(exc)
