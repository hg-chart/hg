# -*- coding: utf-8 -*-
"""用户账号与权限管理独立模块（带 JSON 本地持久化保存）"""

import json
import os
import streamlit as st

USER_DB_FILE = "users_db.json"

# 默认内置账号数据（仅在文件不存在时新建）
DEFAULT_USER_DB = {
    "credentials": {
        "usernames": {
            "admin": {
                "name": "超级管理员",
                "password": "123456",
                "role": "admin",
                "allowed_factories": "ALL",
            },
            "shanxi_user": {
                "name": "山西红光厂长",
                "password": "123456",
                "role": "user",
                "allowed_factories": ["shanxihg"],
            },
        }
    },
    "cookie": {
        "expiry_days": 30,
        "key": "factory_gateway_secure_key",
        "name": "factory_gateway_cookie",
    },
}


def load_user_db():
  """从文件加载用户数据库，若文件不存在则创建默认文件"""
  if not os.path.exists(USER_DB_FILE):
    save_user_db(DEFAULT_USER_DB)
    return DEFAULT_USER_DB
  try:
    with open(USER_DB_FILE, "r", encoding="utf-8") as f:
      return json.load(f)
  except Exception:
    return DEFAULT_USER_DB


def save_user_db(db_data=None):
  """保存用户数据库到 JSON 文件中"""
  if db_data is None:
    db_data = st.session_state["user_db"]
  with open(USER_DB_FILE, "w", encoding="utf-8") as f:
    json.dump(db_data, f, ensure_ascii=False, indent=2)


def render_user_management(username, user_role, authenticator):
  """渲染侧边栏用户相关界面（个人密码修改 + 超级管理员用户管理）"""
  current_user = st.session_state["user_db"]["credentials"]["usernames"].get(
      username, {}
  )
  user_disp_name = current_user.get("name", username)

  st.sidebar.title("🔐 会话信息")
  st.sidebar.write(f"当前用户：**{user_disp_name}** (`{username}`)")

  # 1. 个人密码修改
  with st.sidebar.expander("🔑 修改我的密码"):
    new_self_pwd = st.text_input(
        "新密码", type="password", key="reset_self_pwd_input"
    )
    if st.button("确认重置", key="btn_reset_self_pwd"):
      if new_self_pwd:
        st.session_state["user_db"]["credentials"]["usernames"][username][
            "password"
        ] = new_self_pwd
        save_user_db()  # 写入文件持久化
        st.success("✅ 个人密码重置成功，下次登录生效！")
      else:
        st.warning("密码不能为空")

  authenticator.logout("退出登录", "sidebar")
  st.sidebar.markdown("---")

  # 2. 超级管理员：统一用户账号与资料编辑模块
  if user_role == "admin":
    with st.sidebar.expander("👥 用户账号与资料管理"):
      st.markdown("#### ✏️ 编辑现有用户资料")
      all_users = list(
          st.session_state["user_db"]["credentials"]["usernames"].keys()
      )
      target_u = st.selectbox(
          "选择要修改的用户", all_users, key="select_u_to_edit_full"
      )

      u_info = st.session_state["user_db"]["credentials"]["usernames"][target_u]

      # 编辑登录账号名与显示姓名
      edit_uname = st.text_input(
          "登录账号 (Username)", value=target_u, key=f"edit_uname_{target_u}"
      )
      edit_disp_name = st.text_input(
          "人员姓名/显示名 (Name)",
          value=u_info.get("name", ""),
          key=f"edit_disp_{target_u}",
      )
      edit_pwd = st.text_input(
          "重置密码 (留空保持原样)",
          type="password",
          key=f"edit_pwd_{target_u}",
      )

      # 关联工厂权限
      current_allowed = u_info.get("allowed_factories", [])
      if current_allowed == "ALL":
        default_selected_facs = st.session_state.get("all_factories", [])
      else:
        default_selected_facs = [
            f
            for f in current_allowed
            if f in st.session_state.get("all_factories", [])
        ]

      edit_facs = st.multiselect(
          "允许访问的工厂",
          st.session_state.get("all_factories", []),
          default=default_selected_facs,
          key=f"edit_facs_{target_u}",
      )

      if st.button("保存修改", key="btn_save_u_edit", use_container_width=True):
        new_u = edit_uname.strip()
        if not new_u:
          st.error("登录账号不能为空！")
        elif (
            new_u != target_u
            and new_u
            in st.session_state["user_db"]["credentials"]["usernames"]
        ):
          st.error(f"登录账号【{new_u}】已被占用！")
        else:
          updated_user_config = {
              "name": edit_disp_name.strip()
              if edit_disp_name.strip()
              else new_u,
              "password": edit_pwd if edit_pwd else u_info.get("password"),
              "role": u_info.get("role", "user"),
              "allowed_factories": edit_facs
              if u_info.get("role") != "admin"
              else "ALL",
          }

          if new_u != target_u:
            del st.session_state["user_db"]["credentials"]["usernames"][
                target_u
            ]

          st.session_state["user_db"]["credentials"]["usernames"][new_u] = (
              updated_user_config
          )

          # 核心修复：把修改保存到持久化 JSON 文件中
          save_user_db()

          st.success(f"用户【{new_u}】资料已成功更新并已永久保存！")
          st.rerun()

      st.markdown("---")
      st.markdown("#### ➕ 创建新账号")
      new_uname = st.text_input(
          "新账号 (Username)",
          placeholder="例: taiyuan_user",
          key="new_u_name",
      )
      new_disp_name = st.text_input(
          "显示名 (Name)", placeholder="例: 太原厂长", key="new_u_disp"
      )
      new_u_pwd = st.text_input(
          "初始密码", type="password", key="new_u_pwd_input"
      )

      assigned_facs = st.multiselect(
          "授权工厂",
          st.session_state.get("all_factories", []),
          key="select_user_allowed_facs",
      )

      if st.button(
          "确认创建用户", key="btn_create_new_user", use_container_width=True
      ):
        new_uname = new_uname.strip()
        if not new_uname or not new_u_pwd:
          st.error("账号和密码为必填项！")
        elif (
            new_uname
            in st.session_state["user_db"]["credentials"]["usernames"]
        ):
          st.error("该账号已存在！")
        else:
          st.session_state["user_db"]["credentials"]["usernames"][
              new_uname
          ] = {
              "name": new_disp_name.strip()
              if new_disp_name.strip()
              else new_uname,
              "password": new_u_pwd,
              "role": "user",
              "allowed_factories": assigned_facs
              if assigned_facs
              else st.session_state.get("all_factories", []),
          }
          save_user_db()  # 保存新用户到本地文件
          st.success(f"用户账号【{new_uname}】创建成功！")
          st.rerun()

      st.markdown("---")
      st.markdown("#### 🗑️ 删除用户账号")
      user_to_del = st.selectbox(
          "选择要删除的账号",
          [u for u in all_users if u != "admin"],
          key="select_u_del",
      )
      if st.button(
          "确认删除账号", key="btn_del_user_acc", use_container_width=True
      ):
        if user_to_del:
          del st.session_state["user_db"]["credentials"]["usernames"][
              user_to_del
          ]
          save_user_db()  # 删除后保存到文件
          st.success(f"账号【{user_to_del}】已成功删除！")
          st.rerun()
