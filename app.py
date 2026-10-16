# ============================================================
# 0. 页面外观与基础配置（强制侧边栏常驻展开，绝不收起）
# ============================================================
st.set_page_config(page_title="设备运行数据分析系统", layout="wide")

st.markdown(
    """
    <style>
    /* 隐藏右上角工具栏与页脚 */
    div[data-testid="stToolbar"] {
        visibility: hidden;
        display: none !important;
    }
    footer {
        visibility: hidden;
    }

    /* 核心强制展开：无论何时何地，锁定侧边栏为显示状态且不许收起 */
    section[data-testid="stSidebar"] {
        width: 320px !important;
        transform: none !important;
        visibility: visible !important;
    }

    /* 彻底隐藏原来难看的收起按钮，防止用户点到 */
    button[kind="header"], [data-testid="collapsedControl"] {
        display: none !important;
        visibility: hidden !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
