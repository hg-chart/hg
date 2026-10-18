# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 工厂安全隔离路由网关入口（完全去硬编码、以存储为准版本）"""

import inspect
import json
import os
import runpy
import secrets
import shutil
import time
import streamlit as st
import streamlit_authenticator as stauth

import factory_manager
import r2_storage
import user_manager

# ============================================================
# 0. 页面外观与基础配置
# ============================================================
st.set_page_config(
    page_title="设备运行数据分析系统",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    div[data-testid="stToolbar"] { visibility: hidden !important; display: none !important; }
    footer { visibility: hidden !important; }

    .main .block-container,
    [data-testid="stMainBlockContainer"],
    div.block-container {
        max-width: 100% !important;
        width: 100% !important;
        padding-left: 0.8rem !important;
        padding-right: 0.5rem !important;
        padding-top: 1.5rem !important;
        padding-bottom: 40vh !important;
    }
    [data-testid="stMain"],
    [data-testid="stAppViewContainer"] {
        padding-right: 0 !important;
    }

    @media (min-width: 769px) {
        section[data-testid="stSidebar"] {
            display: block !important;
            visibility: visible !important;
            transform: none !important;
            width: 320px !important;
            min-width: 320px !important;
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            height: 100vh !important;
            z-index: 999999 !important;
        }
        .main .block-container,
        [data-testid="stMainBlockContainer"],
        div.block-container {
            padding-left: 335px !important;
        }
    }

    @media (max-width: 768px) {
        body section[data-testid="stSidebar"] {
            display: block !important;
            visibility: visible !important;
            transform: none !important;
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 82vw !important;
            max-width: 300px !important;
            min-width: 0 !important;
            height: 100vh !important;
            z-index: 999999 !important;
            background-color: var(--secondary-background-color, #f8f9fa) !important;
            box-shadow: 8px 0 24px rgba(0, 0, 0, 0.3) !important;
        }
        [data-testid="stSidebarCollapseButton"] { display: none !important; }
    }

    [data-testid="stImage"], [data-testid="stImage"] img {
        width: 100% !important;
        max-width: 100% !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 1. 全局数据源初始化（完全依靠存储发现，无硬编码工厂）
# ============================================================
# 用户库以 R2 为准：未登录时每次运行都重新读取（保证新建 / 改密的账号立刻能登录），
# 登录后沿用会话中的副本，管理员修改时由 user_manager 先写 R2 再更新。
if "user_db" not in st.session_state or st.session_state.get("authentication_status") is not True:
  try:
    st.session_state["user_db"] = user_manager.load_user_db()
  except user_manager.UserDBUnavailable as _exc:
    if "user_db" not in st.session_state:
      st.error(f"无法读取云端用户库，已停止加载以保护现有账号数据：{_exc}")
      st.caption("请检查 R2 的网络与密钥权限后刷新页面重试。")
      st.stop()
    st.warning(f"云端用户库暂时读取失败，沿用本次会话中的副本：{_exc}")

# ============================================================
# 2. 用户登录认证与会话托管
# ============================================================
SESSION_TTL_SECONDS = 12 * 3600  # 令牌有效期（每次刷新自动顺延）


@st.cache_resource
def _session_store():
  return {}


def _issue_token(user):
  token = secrets.token_urlsafe(32)
  _session_store()[token] = {"u": user, "exp": time.time() + SESSION_TTL_SECONDS}
  return token


def _lookup_token(token):
  if not token:
    return None
  store = _session_store()
  rec = store.get(token)
  if not rec or rec["exp"] < time.time():
    store.pop(token, None)
    return None
  rec["exp"] = time.time() + SESSION_TTL_SECONDS
  return rec["u"]


def _revoke_token(token):
  if token:
    _session_store().pop(token, None)


if "_auth_cookie_name" not in st.session_state:
  st.session_state["_auth_cookie_name"] = f"hg_auth_{secrets.token_hex(6)}"

authenticator = stauth.Authenticate(
    st.session_state["user_db"]["credentials"],
    st.session_state["_auth_cookie_name"],
    st.session_state["user_db"]["cookie"]["key"],
    1,
    auto_hash=True,
)

for _legacy in ("auth_status", "logged_username"):
  if _legacy in st.query_params:
    del st.query_params[_legacy]

if st.session_state.get("authentication_status") is not True:
  _url_token = st.query_params.get("s")
  if _url_token:
    _restored_user = _lookup_token(_url_token)
    if _restored_user and _restored_user in st.session_state["user_db"]["credentials"]["usernames"]:
      st.session_state["username"] = _restored_user
      st.session_state["authentication_status"] = True
      st.session_state["name"] = st.session_state["user_db"]["credentials"]["usernames"][_restored_user].get("name", _restored_user)
      st.session_state["_my_token"] = _url_token
    else:
      st.query_params.clear()

is_logged_in = False
if st.session_state.get("authentication_status") is True and st.session_state.get("username"):
  is_logged_in = True

if not is_logged_in:
  login_parameters = inspect.signature(authenticator.login).parameters
  if "form_name" in login_parameters:
    login_result = authenticator.login("请登录设备运行数据分析系统", "main")
  elif "location" in login_parameters:
    login_result = authenticator.login(location="main")
  else:
    login_result = authenticator.login()

  if isinstance(login_result, (tuple, list)) and len(login_result) == 3:
    name, authentication_status, username = login_result
  else:
    name = st.session_state.get("name")
    authentication_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username")

  if authentication_status is True:
    st.session_state["authentication_status"] = True
    st.session_state["username"] = username
    st.session_state["name"] = name
    _new_token = _issue_token(str(username))
    st.session_state["_my_token"] = _new_token
    st.query_params.clear()
    st.query_params["s"] = _new_token
    st.rerun()
  elif authentication_status is False:
    st.error("❌ 用户名或密码错误")
    st.stop()
  else:
    st.info("👉 请输入您的登录凭据以访问系统")
    st.stop()
else:
  username = st.session_state.get("username")
  authentication_status = True

if not username or username not in st.session_state["user_db"]["credentials"]["usernames"]:
  st.error("登录账号不存在或权限不足，请重新登录。")
  _revoke_token(st.session_state.pop("_my_token", None))
  st.session_state.pop("authentication_status", None)
  st.session_state.pop("username", None)
  if len(st.query_params) > 0:
    st.query_params.clear()
  st.stop()

# ============================================================
# 3. 模块化调用侧边栏管理组件与显隐状态控制
# ============================================================
# 工厂列表以 R2 注册表为准：必须在用户管理（要读 all_factories）之前加载
factory_manager.ensure_factories_loaded()

current_user = st.session_state["user_db"]["credentials"]["usernames"][username]
user_role = current_user.get("role", "user")
allowed_factories = current_user.get("allowed_factories", [])

if "sidebar_visible" not in st.session_state:
  try:
    _ua = st.context.headers.get("User-Agent", "")
  except Exception:
    _ua = ""
  _is_mobile = any(k in _ua for k in ("Mobile", "Android", "iPhone", "iPad"))
  st.session_state["sidebar_visible"] = not _is_mobile


def _set_sidebar_visible(flag):
  st.session_state["sidebar_visible"] = flag


if st.session_state["sidebar_visible"]:
  st.markdown(
      """
      <style>
      @media (max-width: 768px) {
          body section[data-testid="stSidebar"] {
              display: block !important;
              visibility: visible !important;
              transform: none !important;
              position: fixed !important;
              top: 0 !important;
              left: 0 !important;
              width: 82vw !important;
              max-width: 300px !important;
              min-width: 0 !important;
              height: 100vh !important;
              z-index: 999999 !important;
              background-color: var(--secondary-background-color, #f8f9fa) !important;
              box-shadow: 8px 0 24px rgba(0, 0, 0, 0.3) !important;
          }
          [data-testid="stSidebarCollapseButton"] { display: none !important; }
      }
      </style>
      """,
      unsafe_allow_html=True,
  )
  st.sidebar.button(
      "◀ 隐藏管理栏",
      key="btn_hide_sidebar",
      on_click=_set_sidebar_visible,
      args=(False,),
      use_container_width=True,
  )
else:
  st.markdown(
      """
      <style>
      body section[data-testid="stSidebar"] { display: none !important; }
      body .main .block-container,
      body [data-testid="stMainBlockContainer"],
      body div.block-container {
          padding-left: 0.5rem !important;
          padding-right: 0.5rem !important;
          padding-top: 3rem !important;
      }
      .st-key-btn_show_sidebar {
          position: fixed !important;
          top: 0.5rem !important;
          left: 0.5rem !important;
          width: auto !important;
          z-index: 1000000 !important;
      }
      </style>
      """,
      unsafe_allow_html=True,
  )
  st.button(
      "☰ 工厂、人员管理",
      key="btn_show_sidebar",
      on_click=_set_sidebar_visible,
      args=(True,),
  )

user_manager.render_user_management(username, user_role, authenticator)

if st.session_state.get("authentication_status") is not True:
  _revoke_token(st.session_state.pop("_my_token", None))
  _revoke_token(st.query_params.get("s"))
  st.query_params.clear()
  st.rerun()

selected_factory = factory_manager.render_factory_management(
    user_role, allowed_factories
)
st.session_state["selected_factory"] = selected_factory

if not selected_factory:
  st.info(
      "👉 当前没有可用的工厂工作区。管理员请在左侧「工厂管理与回收站」中添加工厂；"
      "普通用户请联系管理员授权。"
  )
  st.stop()

# ============================================================
# 4. 工厂隔离说明
# ============================================================
# 当前工厂只保存在本浏览器会话的 st.session_state["selected_factory"] 里。
# 文件库目录、回收站、图表目录以及 R2 前缀，全部由它推导（见 main_dashboard.py / r2_storage.py）。
# 不再使用全局软链接 uploaded_vault 和全局变量 r2_storage.BASE_PREFIX：
# 它们是整个服务器共用的，多人同时使用不同工厂时会互相串数据。

# ============================================================
# 5. 沙箱隔离运行仪表盘主脚本
# ============================================================
original_set_page_config = st.set_page_config


def safe_set_page_config(*args, **kwargs):
  kwargs["layout"] = "wide"
  kwargs["initial_sidebar_state"] = "expanded"
  try:
    original_set_page_config(*args, **kwargs)
  except Exception:
    pass


st.set_page_config = safe_set_page_config

try:
  runpy.run_path("main_dashboard.py", run_name="__main__")
finally:
  st.set_page_config = original_set_page_config
