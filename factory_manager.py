# -*- coding: utf-8 -*-
"""工厂动态管理与回收站独立模块（基于 R2 集中式配置文件同步）"""

import os
import json
import shutil
import streamlit as st
import r2_storage

CONFIG_FILE_NAME = "factories_config.json"


def fetch_factories_from_r2():
  """直接从 R2 云端下载 factories.json 配置文件，实现 100% 以 R2 为准的绝对同步"""
  default_factories = ["shanxihg"]
  
  r2_client = r2_storage._get_r2_client()
  bucket_name = getattr(r2_storage, "R2_BUCKET_NAME", None)

  if r2_client is not None and bucket_name:
    try:
      # 尝试直接从 R2 根目录下载配置文件
      obj = r2_client.get_object(Bucket=bucket_name, Key="device-monitor/factories_config.json")
      data = json.loads(obj['Body'].read().decode('utf-8'))
      if isinstance(data, list) and data:
        default_factories = data
    except Exception:
      # 如果 R2 上还没有该文件，说明是首次运行，自动上传并初始化默认配置
      sync_factories_to_r2(default_factories)

  # 过滤掉处于回收站中的工厂
  trash_list = st.session_state.get("factory_trash", [])
  active_factories = [f for f in sorted(list(default_factories)) if f not in trash_list]
  
  return active_factories if active_factories else ["shanxihg"]


def sync_factories_to_r2(factories_list):
  """将最新的工厂列表保存并强制上传到 R2 云端"""
  local_path = "factories_config.json"
  try:
    with open(local_path, "w", encoding="utf-8") as f:
      json.dump(factories_list, f, ensure_ascii=False, indent=4)
    
    r2_client = r2_storage._get_r2_client()
    bucket_name = getattr(r2_storage, "R2_BUCKET_NAME", None)
    if r2_client is not None and bucket_name:
      r2_client.upload_file(local_path, bucket_name, "device-monitor/factories_config.json")
  except Exception as e:
    print(f"同步工厂列表至 R2 失败: {e}")


def purge_factory_r2_data(target_factory):
  """彻底删除工厂时清理 Cloudflare R2 数据"""
  try:
    r2_client = r2_storage._get_r2_client()
    bucket_name = getattr(r2_storage, "R2_BUCKET_NAME", None)

    if r2_client is not None and bucket_name:
      target_prefix = f"device-monitor/{target_factory}/"
      paginator = r2_client.get_paginator("list_objects_v2")
      pages = paginator.paginate(Bucket=bucket_name, Prefix=target_prefix)

      objects_to_delete = []
      for page in pages:
        if "Contents" in page:
          for obj in page["Contents"]:
            objects_to_delete.append({"Key": obj["Key"]})

      if objects_to_delete:
        for i in range(0, len(objects_to_delete), 1000):
          r2_client.delete_objects(
              Bucket=bucket_name,
              Delete={"Objects": objects_to_delete[i : i + 1000]},
          )
  except Exception as e:
    print(f"清理 R2 云端数据提示: {e}")


@st.dialog("⚠️ 彻底删除工厂高危操作确认")
def confirm_permanent_delete_dialog(target_factory):
  """彻底删除二次确认互动弹窗"""
  st.warning(
      f"您正在彻底删除工厂：**【{target_factory}】**！\n\n此操作将**不可逆地永久删除**该工厂在"
      " Cloudflare R2 云端及本地的所有隔离数据。"
  )
  st.write("为了防止误操作，请输入要删除的工厂完整名称进行确认：")

  typed_name = st.text_input(
      f"请精准输入：{target_factory}", key="dialog_confirm_input"
  )

  col1, col2 = st.columns(2)
  with col1:
    if st.button("❌ 取消操作", use_container_width=True, key="dlg_btn_cancel"):
      st.rerun()

  with col2:
    if (
        st.button(
            "🔥 确认彻底删除",
            type="primary",
            use_container_width=True,
            key="dlg_btn_confirm",
        )
    ):
      if typed_name.strip() == target_factory:
        purge_factory_r2_data(target_factory)

        if "factory_trash" in st.session_state and target_factory in st.session_state["factory_trash"]:
          st.session_state["factory_trash"].remove(target_factory)

        # 从 R2 配置文件中移除并同步
        current_facs = fetch_factories_from_r2()
        if target_factory in current_facs:
          current_facs.remove(target_factory)
          sync_factories_to_r2(current_facs)

        for folder_suffix in ["uploaded_vault", "file_trash", "chart_history"]:
          local_dir = f"{folder_suffix}_{target_factory}"
          if os.path.exists(local_dir):
            shutil.rmtree(local_dir, ignore_errors=True)

        st.success(f"工厂【{target_factory}】及其 R2 云端数据已彻底永久销毁！")
        st.rerun()
      else:
        st.error(
            f"输入的工厂名称不匹配！要求输入：{target_factory}，实际输入：{typed_name}"
        )


def render_factory_management(user_role, allowed_factories):
  """渲染侧边栏工厂工作区选择与工厂管理回收站模块"""
  st.sidebar.title("🏭 工厂工作区")

  if "factory_trash" not in st.session_state:
    st.session_state["factory_trash"] = []

  # 核心：每次刷新严格向 R2 请求最新的工厂列表
  current_all_factories = fetch_factories_from_r2()
  st.session_state["all_factories"] = current_all_factories

  if st.session_state.get("selected_factory_val") not in current_all_factories:
    if current_all_factories:
      st.session_state["selected_factory_val"] = current_all_factories[0]

  if user_role == "admin" or allowed_factories == "ALL":
    selected_factory = st.sidebar.selectbox(
        "选择目标工厂",
        current_all_factories,
        key="factory_select_main_admin",
    )
  else:
    user_fac_list = [
        f for f in current_all_factories if f in allowed_factories
    ]
    if not user_fac_list:
      user_fac_list = (
          allowed_factories
          if isinstance(allowed_factories, list)
          else [allowed_factories]
      )
    selected_factory = st.sidebar.selectbox(
        "选择当前工厂", user_fac_list, key="factory_select_main_user"
    )

  st.session_state["selected_factory_val"] = selected_factory
  st.sidebar.success(f"已连接工作区：\n**{selected_factory}**")

  # 超级管理员：工厂及回收站增删模块
  if user_role == "admin":
    st.sidebar.markdown("---")
    with st.sidebar.expander("⚙️ 工厂管理与回收站"):
      st.markdown("#### ➕ 增加新工厂")
      new_fac_name = st.text_input(
          "新工厂名称", placeholder="例如：广西百矿三厂", key="add_fac_input"
      )
      if st.button(
          "确认添加工厂", key="btn_add_fac", use_container_width=True
      ):
        new_fac_name = new_fac_name.strip()
        if not new_fac_name:
          st.error("工厂名称不能为空！")
        elif (
            new_fac_name in current_all_factories
            or new_fac_name in st.session_state["factory_trash"]
        ):
          st.warning("该工厂已存在或已在回收站中！")
        else:
          # 1. 将新工厂追加到列表中
          current_all_factories.append(new_fac_name)
          # 2. 立即将最新列表强制同步并写入 R2 云端
          sync_factories_to_r2(current_all_factories)
          
          # 3. 在本地创建对应的隔离文件夹
          os.makedirs(f"uploaded_vault_{new_fac_name}", exist_ok=True)
          os.makedirs(f"file_trash_{new_fac_name}", exist_ok=True)
          os.makedirs(f"chart_history_{new_fac_name}", exist_ok=True)

          st.success(f"已成功添加工厂：{new_fac_name} 并已强力同步至 R2 云端！")
          st.rerun()

      st.markdown("---")
      st.markdown("#### 🗑️ 软删除（移入回收站）")
      st.caption("提示：移入回收站时保留 R2 云端数据。")
      del_fac_name = st.selectbox(
          "选择移入回收站的工厂",
          current_all_factories,
          key="del_fac_select",
      )
      if st.button(
          "📥 移入回收站", key="btn_move_trash", use_container_width=True
      ):
        if len(current_all_factories) <= 1:
          st.error("至少需要保留一个活跃工厂！")
        else:
          current_all_factories.remove(del_fac_name)
          sync_factories_to_r2(current_all_factories)
          st.session_state["factory_trash"].append(del_fac_name)
          st.success(
              f"工厂【{del_fac_name}】已移入回收站（R2 云端数据完整保留）"
          )
          st.rerun()

      st.markdown("---")
      st.markdown("#### ♻️ 工厂回收站")
      if not st.session_state["factory_trash"]:
        st.info("回收站为空")
      else:
        trash_fac_selected = st.selectbox(
            "回收站中的工厂",
            st.session_state["factory_trash"],
            key="trash_fac_select",
        )

        c_res, c_purge = st.columns(2)
        with c_res:
          if st.button(
              "↩️ 还原工厂", key="btn_restore_fac", use_container_width=True
          ):
            st.session_state["factory_trash"].remove(trash_fac_selected)
            current_all_factories.append(trash_fac_selected)
            sync_factories_to_r2(current_all_factories)
            st.success(f"工厂【{trash_fac_selected}】已恢复！")
            st.rerun()

        with c_purge:
          if st.button(
              "🔥 彻底删除",
              key="btn_trigger_dialog",
              use_container_width=True,
          ):
            confirm_permanent_delete_dialog(trash_fac_selected)

  st.sidebar.markdown("---")
  return selected_factory
