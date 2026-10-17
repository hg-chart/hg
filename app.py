# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 工厂安全隔离路由网关入口（专为解决 F5 刷新掉线打造的强持久化版本）"""

import inspect
import os
import runpy
import shutil
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
# 1. 全局数据源初始化
# ============================================================
if "user_db" not in st.session_state:
  st.session_state["user_db"] = user_manager.load_user_db()

if "all_factories" not in st.session_state:
  if hasattr(factory_manager, "load_factory_list"):
    st.session_state["all_factories"] = factory_manager.load_factory_list()
  else:
    collected_factories = set()
    users_dict = st.session_state["user_db"].get("credentials", {}).get("usernames", {})
    for u_data in users_dict.values():
      factories = u_data.get("allowed_factories", [])
      if isinstance(factories, list):
        collected_factories.update(factories)
    
    if collected_factories:
      st.session_state["all_factories"] = list(collected_factories)
    else:
      st.session_state["all_factories"] = [
          "shanxihg",
          "太原分厂",
          "华东一厂",
          "华东二厂",
      ]

if "factory_trash" not in st.session_state:
  st.session_state["factory_trash"] = []

# ============================================================
# 2. 用户登录认证与强 URL 状态托管（绝对防 F5 刷新掉线）
# ============================================================
authenticator = stauth.Authenticate(
    st.session_state["user_db"]["credentials"],
    st.session_state["user_db"]["cookie"]["name"],
    st.session_state["user_db"]["cookie"]["key"],
    st.session_state["user_db"]["cookie"]["expiry_days"],
    auto_hash=True,
)

# 🔴 核心保障：在脚本刚启动、未做任何组件渲染前，优先通过 URL 查询参数强行恢复会话
if "auth_status" in st.query_params and st.query_params["auth_status"] == "success":
  q_user = st.query_params.get("logged_username")
  if q_user and q_user in st.session_state["user_db"]["credentials"]["usernames"]:
    st.session_state["username"] = q_user
    st.session_state["authentication_status"] = True
    if "name" not in st.session_state:
      st.session_state["name"] = st.session_state["user_db"]["credentials"]["usernames"][q_user].get("name", q_user)

# 检查当前内存中是否已处于登录状态
is_logged_in = False
if st.session_state.get("authentication_status") is True and st.session_state.get("username"):
  is_logged_in = True

if not is_logged_in:
  # 未登录状态：渲染登录界面
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
    # 🔴 登录成功的一瞬间，立刻把用户名和成功标识写入网址 URL。这样即使后续按 F5 刷新，网址自带参数也能让系统瞬间恢复状态！
    st.query_params["auth_status"] = "success"
    st.query_params["logged_username"] = str(username)
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

# 检查当前用户名合法性
if not username or username not in st.session_state["user_db"]["credentials"]["usernames"]:
  st.error("登录账号不存在或权限不足，请重新登录。")
  st.session_state.pop("authentication_status", None)
  st.session_state.pop("username", None)
  if len(st.query_params) > 0:
    st.query_params.clear()
  st.stop()

# ============================================================
# 3. 模块化调用侧边栏管理组件与显隐状态控制
# ============================================================
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

# 模块二：工厂选择与增删回收站模块
selected_factory = factory_manager.render_factory_management(
    user_role, allowed_factories
)
st.session_state["selected_factory"] = selected_factory

# ============================================================
# 4. R2 存储与工厂隔离桥接
# ============================================================
r2_prefix = f"device-monitor/{selected_factory}/"
r2_storage.BASE_PREFIX = r2_prefix

factory_vault = f"uploaded_vault_{selected_factory}"
factory_trash = f"file_trash_{selected_factory}"
factory_chart = f"chart_history_{selected_factory}"

os.makedirs(factory_vault, exist_ok=True)
os.makedirs(factory_trash, exist_ok=True)
os.makedirs(factory_chart, exist_ok=True)

if r2_storage._get_r2_client() is not None:
  sync_key = f"_r2_synced_{selected_factory}"
  if not st.session_state.get(sync_key, False):
    with st.spinner(f"正在加载 [{selected_factory}] 的云端数据..."):
      r2_storage.sync_local_storage_with_r2(
          factory_vault, factory_trash, factory_chart
      )
    st.session_state[sync_key] = True

standard_vault = "uploaded_vault"

try:
  if os.path.lexists(standard_vault):
    if os.path.islink(standard_vault) or os.path.isfile(standard_vault):
      os.unlink(standard_vault)
    else:
      shutil.rmtree(standard_vault, ignore_errors=True)
except Exception:
  pass

try:
  if not os.path.exists(standard_vault):
    os.symlink(factory_vault, standard_vault, target_is_directory=True)
except Exception:
  pass

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
