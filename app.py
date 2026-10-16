# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 工厂安全隔离路由网关入口"""

import inspect
import os
import shutil
import streamlit as st
import streamlit_authenticator as stauth

# 1. 导入 r2_storage 模块
import r2_storage

# ============================================================
# 0. 页面外观与基础配置
# ============================================================
st.set_page_config(page_title="设备运行数据分析系统", layout="wide")

st.markdown(
    """
    <style>
    div[data-testid="stToolbar"] {
        visibility: hidden;
        display: none !important;
    }
    footer {
        visibility: hidden;
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
# 3. 侧边栏：极简工厂选择与隔离
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
  selected_factory = st.sidebar.selectbox("选择目标工厂", ALL_FACTORIES)
else:
  selected_factory = st.sidebar.selectbox("选择当前工厂", allowed_factories)

st.sidebar.success(f"已连接工作区：\n**{selected_factory}**")
st.sidebar.markdown("---")

# ============================================================
# 4. 目录挂载魔法：无损桥接 R2 与原版 main_dashboard.py
# ============================================================
# 动态设定 R2 前缀
r2_storage.BASE_PREFIX = f"device-monitor/{selected_factory}/"

# 定义该工厂专属的本地物理仓库目录
factory_vault = f"uploaded_vault_{selected_factory}"
factory_trash = f"file_trash_{selected_factory}"
factory_chart = f"chart_history_{selected_factory}"

os.makedirs(factory_vault, exist_ok=True)
os.makedirs(factory_trash, exist_ok=True)
os.makedirs(factory_chart, exist_ok=True)

# 触发一次 R2 同步，把当前工厂云端文件拉到对应的工厂专属目录中
if r2_storage._get_r2_client() is not None:
  sync_key = f"_r2_synced_{selected_factory}"
  if not st.session_state.get(sync_key, False):
    with st.spinner(f"正在从 Cloudflare R2 同步 [{selected_factory}] 的历史数据..."):
      r2_storage.sync_local_storage_with_r2(
          factory_vault, factory_trash, factory_chart
      )
    st.session_state[sync_key] = True

# 关键魔法：将该工厂的专属目录“镜像映射”给原版 main_dashboard.py 默认读取的文件夹名
standard_vault = "uploaded_vault"

# 安全清理旧的映射或文件夹（已修复 rmtree 不能删符号链接的报错）
if os.path.lexists(standard_vault):
  if os.path.islink(standard_vault) or os.path.isfile(standard_vault):
    os.unlink(standard_vault)
  else:
    shutil.rmtree(standard_vault)

# 建立软链接，若失败则退化为拷贝目录
try:
  os.symlink(factory_vault, standard_vault, target_is_directory=True)
except Exception:
  if os.path.exists(factory_vault):
    shutil.copytree(factory_vault, standard_vault, dirs_exist_ok=True)

# ============================================================
# 5. 直接唤醒并运行你原封未动的业务主脚本
# ============================================================
import main_dashboard
