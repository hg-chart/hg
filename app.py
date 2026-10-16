# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 工厂安全隔离路由网关入口"""

import streamlit as st
import inspect
import os
import shutil
import runpy
import streamlit_authenticator as stauth
import r2_storage

# ============================================================
# 0. 页面外观与宽屏配置（原生支持 wide，不加导致偏移的暴力 CSS）
# ============================================================
st.set_page_config(
    page_title="设备运行数据分析系统", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    /* 隐藏右上角工具栏与页脚 */
    div[data-testid="stToolbar"] { visibility: hidden !important; display: none !important; }
    footer { visibility: hidden !important; }

    /* 优化全屏容器：去掉多余的左右强制偏移，让 Streamlit 原生 wide 布局正常工作，消除右移和偏位 */
    .main .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 3rem !important;
        padding-right: 3rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 1. 多工厂与权限字典配置
# ============================================================
ALL_FACTORIES = ["shanxihg", "太原分厂", "华东一厂", "华东二厂"]

USER_CREDENTIALS = {
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

authenticator = stauth.Authenticate(
    USER_CREDENTIALS["credentials"],
    USER_CREDENTIALS["cookie"]["name"],
    USER_CREDENTIALS["cookie"]["key"],
    USER_CREDENTIALS["cookie"]["expiry_days"],
    auto_hash=True,
)

# ============================================================
# 2. 动态兼容不同版本的 authenticator.login() 签名
# ============================================================
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

if authentication_status is False:
  st.error("❌ 用户名或密码错误")
  st.stop()
elif authentication_status is None:
  st.info("👉 请输入您的登录凭据以访问系统")
  st.stop()
elif (
    authentication_status is not True
    or username not in USER_CREDENTIALS["credentials"]["usernames"]
):
  st.error("登录状态异常，请刷新页面后重新登录。")
  st.stop()

# ============================================================
# 3. 侧边栏：极简工厂选择与隔离（直接内联渲染，100% 确保侧边栏显示）
# ============================================================
current_user = USER_CREDENTIALS["credentials"]["usernames"][username]
user_role = current_user.get("role", "user")
allowed_factories = current_user.get("allowed_factories", [])

st.sidebar.title("🔐 会话信息")
st.sidebar.write(f"当前用户：**{name}**")
authenticator.logout("退出登录", "sidebar")
st.sidebar.markdown("---")

st.sidebar.title("🏭 工厂工作区")

if user_role == "admin" or allowed_factories == "ALL":
  selected_factory = st.sidebar.selectbox("选择目标工厂", ALL_FACTORIES, key="factory_select_main_admin")
else:
  selected_factory = st.sidebar.selectbox("选择当前工厂", allowed_factories, key="factory_select_main_user")

st.sidebar.success(f"已连接工作区：\n**{selected_factory}**")
st.sidebar.markdown("---")

# 动态设置 R2 路径并同步，同时无损桥接本地目录
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
if os.path.lexists(standard_vault):
  if os.path.islink(standard_vault) or os.path.isfile(standard_vault):
    os.unlink(standard_vault)
  else:
    shutil.rmtree(standard_vault)

try:
  os.symlink(factory_vault, standard_vault, target_is_directory=True)
except Exception:
  if os.path.exists(factory_vault):
    shutil.copytree(factory_vault, standard_vault, dirs_exist_ok=True)

# ============================================================
# 4. 安全防御：拦截重复的 set_page_config，并以沙箱隔离方式运行主脚本
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
  # 使用 runpy 独立安全地执行原版 main_dashboard.py
  runpy.run_path("main_dashboard.py", run_name="__main__")
finally:
  st.set_page_config = original_set_page_config
