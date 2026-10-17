# -*- coding: utf-8 -*-
"""工厂动态管理与回收站独立模块（纯净、无自动扫描、绝不诈尸版本）"""

import os
import shutil
import streamlit as st
import r2_storage


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

        if "all_factories" in st.session_state and target_factory in st.session_state["all_factories"]:
          st.session_state["all_factories"].remove(target_factory)

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

  # 纯净初始化：如果没有则赋予最基础的默认工厂，绝不自动扫描磁盘杂物
  if "all_factories" not in st.session_state:
    st.session_state["all_factories"] = ["shanxihg", "二厂"]
  if "factory_trash" not in st.session_state:
    st.session_state["factory_trash"] = []

  active_factories = st.session_state["all_factories"]

  if st.session_state.get("selected_factory_val") not in active_factories:
    if active_factories:
      st.session_state["selected_factory_val"] = active_factories[0]

  if user_role == "admin" or allowed_factories == "ALL":
    selected_factory = st.sidebar.selectbox(
        "选择目标工厂",
        active_factories,
        key="factory_select_main_admin",
    )
  else:
    user_fac_list = [
        f for f in active_factories if f in allowed_factories
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
          "新工厂名称", placeholder="例如：三厂", key="add_fac_input"
      )
      if st.button(
          "确认添加工厂", key="btn_add_fac", use_container_width=True
      ):
        new_fac_name = new_fac_name.strip()
        if not new_fac_name:
          st.error("工厂名称不能为空！")
        elif (
            new_fac_name in st.session_state["all_factories"]
            or new_fac_name in st.session_state["factory_trash"]
        ):
          st.warning("该工厂已存在或已在回收站中！")
        else:
          st.session_state["all_factories"].append(new_fac_name)
          st.success(f"已成功添加工厂：{new_fac_name}")
          st.rerun()

      st.markdown("---")
      st.markdown("#### 🗑️ 软删除（移入回收站）")
      st.caption("提示：移入回收站时保留 R2 云端数据。")
      del_fac_name = st.selectbox(
          "选择移入回收站的工厂",
          active_factories,
          key="del_fac_select",
      )
      if st.button(
          "📥 移入回收站", key="btn_move_trash", use_container_width=True
      ):
        if len(active_factories) <= 1:
          st.error("至少需要保留一个活跃工厂！")
        else:
          st.session_state["all_factories"].remove(del_fac_name)
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
            st.session_state["all_factories"].append(trash_fac_selected)
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
