# -*- coding: utf-8 -*-
"""Cloudflare R2 存储桶专用操作模块"""

import os
import logging
from pathlib import Path
import streamlit as st

R2_PREFIX = "device-monitor/"
_R2_CLIENT = None
_R2_READY = False
_R2_ERROR = ""


def _get_r2_client():
    """延迟创建 R2 S3 兼容客户端，避免将凭据写入代码。"""
    global _R2_CLIENT, _R2_READY, _R2_ERROR
    if _R2_CLIENT is not None:
        return _R2_CLIENT
    try:
        account_id = str(st.secrets["R2_ACCOUNT_ID"]).strip()
        access_key = str(st.secrets["R2_ACCESS_KEY_ID"]).strip()
        secret_key = str(st.secrets["R2_SECRET_ACCESS_KEY"]).strip()
        bucket = str(st.secrets["R2_BUCKET_NAME"]).strip()
        endpoint = str(st.secrets.get("R2_ENDPOINT", f"https://{account_id}.r2.cloudflarestorage.com")).strip()
        if not all([account_id, access_key, secret_key, bucket]):
            raise ValueError("R2 配置项不能为空")
        import boto3
        from botocore.config import Config
        _R2_CLIENT = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        )
        _R2_READY = True
        _R2_ERROR = ""
        return _R2_CLIENT
    except Exception as exc:
        _R2_ERROR = str(exc)
        _R2_READY = False
        return None


def get_r2_error():
    return _R2_ERROR


def _r2_bucket():
    return str(st.secrets["R2_BUCKET_NAME"]).strip()


def _r2_key(local_path_or_key):
    value = str(local_path_or_key).replace("\\", "/").lstrip("/")
    # 如果传入的字符串已经包含了前缀，则直接返回，避免重复拼接
    if value.startswith(R2_PREFIX):
        return value
    return R2_PREFIX + value


def r2_upload_file(local_path, key=None):
    client = _get_r2_client()
    if client is None:
        return False
    try:
        key = _r2_key(key or local_path)
        client.upload_file(str(local_path), _r2_bucket(), key)
        return True
    except Exception as exc:
        logging.exception("上传到 Cloudflare R2 失败：%s", exc)
        return False


def r2_delete_key(key):
    client = _get_r2_client()
    if client is None:
        return False
    try:
        full_key = _r2_key(key)
        client.delete_object(Bucket=_r2_bucket(), Key=full_key)
        return True
    except Exception as exc:
        logging.exception("删除 Cloudflare R2 对象失败：%s", exc)
        return False


def r2_list_keys():
    client = _get_r2_client()
    if client is None:
        return None
    try:
        keys = []
        token = None
        while True:
            kwargs = {"Bucket": _r2_bucket(), "Prefix": R2_PREFIX}
            if token:
                kwargs["ContinuationToken"] = token
            response = client.list_objects_v2(**kwargs)
            keys.extend(item["Key"] for item in response.get("Contents", []))
            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")
        return keys
    except Exception as exc:
        logging.exception("列举 Cloudflare R2 对象失败：%s", exc)
        return None


def sync_local_storage_with_r2(vault_dir, file_trash_dir, chart_history_dir):
    """启动时同步：仅当本地没有该文件且不在回收站时，才从云端同步下载。"""
    client = _get_r2_client()
    if client is None:
        return False
    remote_keys = r2_list_keys()
    if remote_keys is None:
        return False
    remote_set = set(remote_keys)
    local_dirs = [vault_dir, file_trash_dir, chart_history_dir]
    
    trash_files = set()
    for d in [file_trash_dir, "chart_trash_vault"]:
        if os.path.exists(d):
            for p in Path(d).rglob("*"):
                if p.is_file():
                    trash_files.add(p.name)

    for remote_key in remote_keys:
        rel = remote_key[len(R2_PREFIX):]
        if not rel or rel.startswith("../") or "/../" in rel:
            continue
        
        filename = Path(rel).name
        if filename in trash_files or "trash" in remote_key:
            continue

        local_path = Path(rel)
        if not local_path.exists():
            try:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                response = client.get_object(Bucket=_r2_bucket(), Key=remote_key)
                local_path.write_bytes(response["Body"].read())
            except Exception:
                logging.exception("恢复 R2 文件失败：%s", rel)
            
    for folder in local_dirs:
        if os.path.exists(folder):
            for path in Path(folder).rglob("*"):
                if path.is_file():
                    key = _r2_key(path.as_posix())
                    if key not in remote_set:
                        r2_upload_file(path, path.as_posix())
    return True
