# -*- coding: utf-8 -*-
"""工厂动态管理与回收站模块（工厂列表以 Cloudflare R2 注册表为准，Streamlit 与 R2 保持同步）

要点：
  - 工厂列表不再写死，也不再只存在页面内存里：启动时从 R2 读取，
    添加 / 移入回收站 / 还原 / 彻底删除 都会先写入 R2 成功，页面才随之更新。
  - 写入 R2 失败时会明确报错，页面不会出现“假成功”。
"""

import os
import shutil

import streamlit as st

import factory_registry as freg

ADMIN_SELECT_KEY = "factory_select_main_admin"
USER_SELECT_KEY = "factory_select_main_user"


# ------------------------------------------------------------
# 状态同步
# ------------------------------------------------------------
def _apply_registry(reg):
  st.session_state["all_factories"] = list(reg["active"])
  st.session_state["factory_trash"] = list(reg["trash"])


def ensure_factories_loaded(force=False):
  """保证 session 里的工厂列表来自 R2。app.py 应在任何要用 all_factories 的模块之前调用。"""
  if force or not st.session_state.get("_factory_registry_loaded"):
    reg, status = freg.load_registry()
    if reg is None:
      st.session_state["_factory_load_error"] = status
      st.session_state.setdefault("all_factories", [])
      st.session_state.setdefault("factory_trash", [])
    else:
      st.session_state.pop("_factory_load_error", None)
      st.session_state["_factory_status"] = status
      _apply_registry(reg)
      st.session_state["_factory_registry_loaded"] = True


def _flash(kind, message):
  st.session_state["_factory_flash"] = (kind, message)


def _show_flash():
  item = st.session_state.pop("_factory_flash", None)
  if item:
    kind, message = item
    getattr(st.sidebar, kind, st.sidebar.info)(message)


def _guard_select(key, options):
  """选项变化后，清掉已失效的旧选中值，避免 selectbox 状态报错。"""
  if key in st.session_state and st.session_state[key] not in options:
    del st.session_state[key]


def _clean_local_dirs(factory):
  for folder_prefix in ["uploaded_vault", "file_trash", "chart_history"]:
    local_dir = f"{folder_prefix}_{factory}"
    if os.path.exists(local_dir):
      shutil.rmtree(local_dir, ignore_errors=True)
  st.session_state.pop(f"_r2_synced_{factory}", None)


# ------------------------------------------------------------
# 彻底删除确认弹窗
# ------------------------------------------------------------
@st.dialog("⚠️ 彻底删除工厂高危操作确认")
def confirm_permanent_delete_dialog(target_factory):
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
    if st.button(
        "🔥 确认彻底删除",
        type="primary",
        use_container_width=True,
        key="dlg_btn_confirm",
    ):
      if typed_name.strip() != target_factory:
        st.error(
            f"输入的工厂名称不匹配！要求输入：{target_factory}，实际输入：{typed_name}"
        )
        return
      ok, msg, reg = freg.purge_factory(target_factory)
      if ok:
        _clean_local_dirs(target_factory)
        _apply_registry(reg)
        _flash("success", msg)
        st.rerun()
      else:
        st.error(msg)


# ------------------------------------------------------------
# 侧边栏：工厂选择 + 管理
# ------------------------------------------------------------
def render_factory_management(user_role, allowed_factories):
  """渲染侧边栏工厂选择与（管理员）工厂管理。返回当前工厂名；没有可用工厂时返回 None。"""
  st.sidebar.title("🏭 工厂工作区")
  _show_flash()
  ensure_factories_loaded()

  load_err = st.session_state.get("_factory_load_error")
  if load_err:
    st.sidebar.warning(f"读取云端工厂列表失败：{load_err}")
  elif st.session_state.get("_factory_status") == "offline":
    st.sidebar.warning("R2 未连接：工厂列表仅保存在本地，重启后会丢失。")

  active_factories = list(st.session_state.get("all_factories", []))
  is_admin = user_role == "admin" or allowed_factories == "ALL"

  # 新增成功后自动选中新工厂（必须在 selectbox 创建之前设置）
  pending = st.session_state.pop("_pending_factory_select", None)
  if pending and pending in active_factories:
    st.session_state[ADMIN_SELECT_KEY] = pending
  if st.session_state.pop("_clear_add_input", False):
    st.session_state["add_fac_input"] = ""

  if is_admin:
    visible_factories = active_factories
    select_key, label = ADMIN_SELECT_KEY, "选择目标工厂"
  else:
    if isinstance(allowed_factories, str):
      allowed_factories = [allowed_factories]
    visible_factories = [f for f in active_factories if f in (allowed_factories or [])]
    select_key, label = USER_SELECT_KEY, "选择当前工厂"

  _guard_select(select_key, visible_factories)

  selected_factory = None
  if visible_factories:
    selected_factory = st.sidebar.selectbox(
        label, visible_factories, key=select_key
    )
    st.session_state["selected_factory_val"] = selected_factory
    st.sidebar.success(f"已连接工作区：\n**{selected_factory}**")
  else:
    st.session_state.pop("selected_factory_val", None)
    if is_admin:
      st.sidebar.info("当前还没有工厂，请在下方「工厂管理与回收站」中添加。")
    else:
      st.sidebar.warning("您还没有可用的工厂，请联系管理员授权。")

  if user_role == "admin":
    st.sidebar.markdown("---")
    with st.sidebar.expander("⚙️ 工厂管理与回收站"):
      if st.button("🔄 从云端刷新工厂列表", key="btn_refresh_fac", use_container_width=True):
        ensure_factories_loaded(force=True)
        st.rerun()

      st.markdown("#### ➕ 增加新工厂")
      new_fac_name = st.text_input(
          "新工厂名称", placeholder="例如：三厂", key="add_fac_input"
      )
      if st.button("确认添加工厂", key="btn_add_fac", use_container_width=True):
        ok, msg, reg = freg.add_factory(new_fac_name)
        if ok:
          _apply_registry(reg)
          st.session_state["_pending_factory_select"] = new_fac_name.strip()
          st.session_state["_clear_add_input"] = True
          _flash("success", msg)
          st.rerun()
        else:
          st.error(msg)

      st.markdown("---")
      st.markdown("#### 🗑️ 软删除（移入回收站）")
      st.caption("提示：移入回收站时保留 R2 云端数据。")
      _guard_select("del_fac_select", active_factories)
      if active_factories:
        del_fac_name = st.selectbox(
            "选择移入回收站的工厂", active_factories, key="del_fac_select"
        )
        if st.button("📥 移入回收站", key="btn_move_trash", use_container_width=True):
          ok, msg, reg = freg.move_to_trash(del_fac_name)
          if ok:
            _apply_registry(reg)
            _flash("success", msg)
            st.rerun()
          else:
            st.error(msg)
      else:
        st.info("没有活跃工厂")

      st.markdown("---")
      st.markdown("#### ♻️ 工厂回收站")
      trash_list = list(st.session_state.get("factory_trash", []))
      if not trash_list:
        st.info("回收站为空")
      else:
        _guard_select("trash_fac_select", trash_list)
        trash_fac_selected = st.selectbox(
            "回收站中的工厂", trash_list, key="trash_fac_select"
        )
        c_res, c_purge = st.columns(2)
        with c_res:
          if st.button("↩️ 还原工厂", key="btn_restore_fac", use_container_width=True):
            ok, msg, reg = freg.restore_factory(trash_fac_selected)
            if ok:
              _apply_registry(reg)
              _flash("success", msg)
              st.rerun()
            else:
              st.error(msg)
        with c_purge:
          if st.button("🔥 彻底删除", key="btn_trigger_dialog", use_container_width=True):
            confirm_permanent_delete_dialog(trash_fac_selected)

  st.sidebar.markdown("---")
  return selected_factory
