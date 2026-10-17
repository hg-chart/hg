# -*- coding: utf-8 -*-
"""工厂动态管理与回收站独立模块（严格以 Cloudflare R2 云端为唯一准绳）"""

import os
import shutil
import streamlit as st
import r2_storage


def fetch_factories_from_r2():
  """绝对以 R2 云端扫描结果为准，实时同步工厂列表，杜绝任何本地缓存滞后"""
  factories = set(["shanxihg"])  # 默认保底工厂
  
  try:
    r2_client = r2_storage._get_r2_client()
    bucket_name = getattr(r2_storage, "R2_BUCKET_NAME", None)
    
    if r2_client is not None and bucket_name:
      # 1. 扫描 CommonPrefixes 目录
      response = r2_client.list_objects_v2(
          Bucket=bucket_name, Prefix="device-monitor/", Delimiter="/"
      )
      if "CommonPrefixes" in response:
        for p in response["CommonPrefixes"]:
          parts = p["Prefix"].strip("/").split("/")
          if len(parts) >= 2:
            fac_name = parts[1]
            if fac_name:
              factories.add(fac_name)
              
      # 2. 深度扫描 Contents 键名，确保刚添加带文件的工厂能立刻被 R2 抓取
      paginator = r2_client.get_paginator("list_objects_v2")
      for page in paginator.paginate(Bucket=bucket_name, Prefix="device-monitor/"):
        for obj in page.get("Contents", []):
          key_parts = obj["Key"].split("/")
          if len(key_parts) >= 3:
            fac_name = key_parts[1]
            if fac_name:
              factories.add(fac_name)
  except Exception as e:
    print(f"实时同步 R2 工厂列表失败: {e}")

  # 过滤掉处于回收站中的工厂
  trash_list = st.session_state.get("factory_trash", [])
  active_factories = [f for f in sorted(list(factories)) if f not in trash_list]
  
  return active_factories if active_factories else ["shanxihg"]


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

  # 核心：每一次页面刷新或运行，强制直接从 R2 云端拉取最新工厂列表作为唯一标准
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
          # 在本地创建文件夹，并通过 R2 同步上传占位文件，强制在云端 R2 生成该文件夹对象
          vault_d = f"uploaded_vault_{new_fac_name}"
          trash_d = f"file_trash_{new_fac_name}"
          chart_d = f"chart_history_{new_fac_name}"
          os.makedirs(vault_d, exist_ok=True)
          os.makedirs(trash_d, exist_ok=True)
          os.makedirs(chart_d, exist_ok=True)
          
          if r2_storage._get_r2_client() is not None:
            r2_storage.BASE_PREFIX = f"device-monitor/{new_fac_name}/"
            dummy_file = os.path.join(vault_d, ".keep")
            with open(dummy_file, "w") as f:
              f.write("init")
            r2_storage.r2_upload_file(dummy_file)

          st.success(f"已成功添加工厂：{new_fac_name} 并强制同步至 R2 云端！")
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
            if trash_fac_selected in st.session_state["factory_trash"]:
              st.session_state["factory_trash"].remove(trash_fac_selected)
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
