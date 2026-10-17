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
