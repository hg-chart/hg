# -*- coding: utf-8 -*-
"""模块五：图表绘制与预览"""
import io
import os
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib import ticker
import pandas as pd
import streamlit as st
import r2_storage
import data_processor

def format_num(val):
    """辅助函数：如果是整数则不带小数点，保持输入原貌"""
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)

def select_period_rows(df, time_col, start_dt, end_dt, date_only):
    """取出落在某个时间段内的行。

    数据只有“日期”没有具体时刻时（时间都是 00:00:00），按“天”匹配：
    只要数据日期落在 开始日期 ~ 结束日期（含两端）之内就算命中，
    避免 08-01 00:00 因为早于 08-01 18:07 而被误排除。
    """
    if date_only:
        lo, hi = start_dt.normalize(), end_dt.normalize()
    else:
        lo, hi = start_dt, end_dt
    return df[(df[time_col] >= lo) & (df[time_col] <= hi)].copy()


LINE_STYLES = ["-", "--", "-.", ":"]
MARKERS = [None, None, None, None, "o", "s", "^", "D", "v", "P"]


def _series_style(i):
    """第 i 条折线的线型与标记：前 4 条只靠线型区分，之后再加标记。"""
    return LINE_STYLES[i % len(LINE_STYLES)], (MARKERS[i] if i < len(MARKERS) else None)


def _as_cols(value):
    """None / 单个列名 / 列名列表 -> 列表。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _safe_tag(text):
    """文件名/R2 路径里用到的片段：去掉会破坏路径或命名解析的字符。"""
    return str(text).replace("/", "-").replace("\\", "-").replace("_", "-")


def _source_tag(cols):
    """历史图表命名里的“数据来源”：只有一列时沿用列名；多列时用 + 连接。"""
    cols = _as_cols(cols)
    if len(cols) == 1:
        return cols[0].replace("/", "-").replace("\\", "-")
    return "+".join(_safe_tag(c) for c in cols)


def _cond_str(min_threshold, max_threshold):
    if min_threshold is not None and max_threshold is not None:
        return f"{format_num(min_threshold)}-{format_num(max_threshold)}"
    if min_threshold is not None:
        return f"≥{format_num(min_threshold)}"
    if max_threshold is not None:
        return f"≤{format_num(max_threshold)}"
    return "全部"


def draw_trend_chart(
    plotted_periods, time_col, left_cols, right_cols, left_names, right_names,
    final_time_label, final_left_label, final_right_label, label_fmt, unify_axes,
):
    """绘制多时段对比趋势图，返回 (fig, 刻度说明文字, 图例说明文字)。

    - 左、右纵轴都可以选 0 个或多个数据列；只有一侧有数据时，图里只有横轴和这一侧的纵轴。
    - 左轴只选一列：面积图（与以前一致）；选多列：折线。右轴一律折线。
    - 颜色区分时间段；同一侧多个数据列用不同线型区分。
    """
    n_left, n_right = len(left_cols), len(right_cols)
    both = n_left > 0 and n_right > 0
    area_mode = n_left == 1
    multi = n_left > 1 or n_right > 1

    fig, ax1 = plt.subplots(figsize=(16, 8))
    ax_l = ax1 if n_left else None
    if both:
        ax_r = ax1.twinx()
    elif n_right:
        ax_r = ax1
        ax1.yaxis.tick_right()
        ax1.yaxis.set_label_position("right")
    else:
        ax_r = None

    series = [("left", c) for c in left_cols] + [("right", c) for c in right_cols]
    styles, k = {}, 0
    for s_idx, (side, _col) in enumerate(series):
        if side == "left" and area_mode:
            continue
        styles[s_idx] = _series_style(k)
        k += 1

    handles = {}
    all_x_labels = []
    cursor = 0
    for p_idx, period in enumerate(plotted_periods):
        part = period["data"]
        count = len(part)
        x_values = list(range(cursor, cursor + count))
        cursor += count
        all_x_labels.extend(part[time_col].dt.strftime(label_fmt).tolist())

        for s_idx, (side, col) in enumerate(series):
            ax = ax_l if side == "left" else ax_r
            name = (left_names if side == "left" else right_names).get(col, col)
            label_name = f"[{'左' if side == 'left' else '右'}] {name}" if multi else name
            label = f"{label_name} {period['description']}"
            y = part[col].to_numpy()
            if side == "left" and area_mode:
                artist = ax.fill_between(
                    x_values, y, color=period["fill_color"], alpha=0.50, label=label,
                )
                ax.plot(x_values, y, color=period["fill_color"], linewidth=0.8, alpha=0.9)
            else:
                linestyle, marker = styles[s_idx]
                (artist,) = ax.plot(
                    x_values, y, color=period["line_color"], linewidth=1.5,
                    linestyle=linestyle, marker=marker, markersize=3,
                    markevery=max(1, count // 15) if marker else None, label=label,
                )
            handles[(s_idx, p_idx)] = (artist, label)

    ax1.set_xlabel(final_time_label, fontsize=12)
    if ax_l is not None:
        ax_l.set_ylabel(final_left_label, fontsize=12, color="black")
    if ax_r is not None:
        ax_r.set_ylabel(final_right_label, fontsize=12, color="black")

    def _values(cols):
        frames = [p_["data"][c] for p_ in plotted_periods for c in cols]
        return pd.concat(frames).dropna() if frames else pd.Series(dtype=float)

    # 两侧都有数据且同类（如都是压差）时：统一刻度范围和刻度线，便于直接对比
    scale_note = ""
    if both:
        ax1.grid(False)
        grid_ax = ax_r
    else:
        grid_ax = ax1
    if unify_axes and both:
        all_values = _values(left_cols + right_cols)
        if not all_values.empty:
            axis_lo = float(all_values.min())
            axis_hi = float(all_values.max())
            if area_mode:  # 左侧面积图以 0 为底，下限不高于 0
                axis_lo = min(0.0, axis_lo)
            axis_hi += max((axis_hi - axis_lo) * 0.03, 1e-9)
            shared_ticks = ticker.MaxNLocator(nbins=10, steps=[1, 2, 2.5, 5, 10]).tick_values(axis_lo, axis_hi)
            for axis_obj in (ax_l, ax_r):
                axis_obj.set_ylim(shared_ticks[0], shared_ticks[-1])
                axis_obj.set_yticks(shared_ticks)
            scale_note = (
                f"（两个纵轴已统一刻度：{format_num(float(shared_ticks[0]))} ~ "
                f"{format_num(float(shared_ticks[-1]))}）"
            )
    elif ax_r is not None:
        right_values = _values(right_cols)
        if not right_values.empty:
            span = float(right_values.max() - right_values.min())
            if 600 <= span <= 6000:  # 数值范围合适时沿用原来的 200 一格；范围差太多则交给自动刻度
                ax_r.yaxis.set_major_locator(ticker.MultipleLocator(200))
    grid_ax.grid(True, linestyle="--", alpha=0.5, color="gray")

    max_xticks = 12
    step = max(1, len(all_x_labels) // max_xticks)
    tick_positions = list(range(0, len(all_x_labels), step))
    tick_labels = [all_x_labels[i] for i in tick_positions]
    ax1.set_xticks(tick_positions)
    ax1.set_xticklabels(tick_labels, rotation=30, ha="right")
    ax1.tick_params(axis="x", labelsize=10)

    # 图例：每一列对应一条数据序列、每一行对应一个时间段（序列多于 2 个时分两列排布）
    n_series, n_periods = len(series), len(plotted_periods)
    ordered = [handles[(s, p)] for s in range(n_series) for p in range(n_periods)]
    legend_handles = [h for h, _ in ordered]
    legend_labels = [l for _, l in ordered]
    legend_ncol = max(1, min(2, n_series))
    legend_rows = (len(legend_labels) + legend_ncol - 1) // legend_ncol
    legend_h_in = legend_rows * 0.24 + 0.3
    base_h_in = 8.0
    fig_h_in = base_h_in + legend_h_in
    fig.set_size_inches(16, fig_h_in)
    fig.tight_layout(rect=[0, legend_h_in / fig_h_in, 1, 1])
    fig.legend(
        legend_handles, legend_labels, loc="lower center",
        bbox_to_anchor=(0.5, 0.1 / fig_h_in), ncol=legend_ncol, fontsize=9.5, frameon=True,
    )
    return fig, scale_note, all_x_labels


def render_chart_generator(
    df_raw, time_col, left_cols, right_cols,
    min_threshold, max_threshold, filter_valid,
    final_time_label="时间", final_left_label="", final_right_label="",
    filter_target_col=None, filter_metric_name="",
    axis_info=None,
):
    """渲染生成趋势图的触发按钮及预览界面。左、右纵轴都可以选 0 个或多个数据列。"""
    left_cols, right_cols = _as_cols(left_cols), _as_cols(right_cols)
    axis_info = axis_info or {}
    left_names = axis_info.get("left_names") or {c: c for c in left_cols}
    right_names = axis_info.get("right_names") or {c: c for c in right_cols}
    left_short = axis_info.get("left_short") or "、".join(left_cols)
    right_short = axis_info.get("right_short") or "、".join(right_cols)
    cond_str_clean = _cond_str(min_threshold, max_threshold)

    if st.button("🚀 开始生成多时段对比趋势图", type="primary"):
        if not filter_valid:
            st.error("请先修正过滤条件的输入错误。")
        elif not left_cols and not right_cols:
            st.error("请至少为左纵轴或右纵轴选择一个数据列。")
        elif not st.session_state.get("intervals"):
            st.session_state.plotted_fig_bytes = None
            st.session_state.plotted_title = ""
            st.session_state.plotted_periods_info = []
            st.warning("请至少添加一个对比时间段！")
        else:
            with st.spinner("正在处理多时段数据并绘图……"):
                fig = None
                try:
                    df = df_raw.copy()

                    actual_time_col = time_col
                    value_cols = list(dict.fromkeys(left_cols + right_cols))
                    actual_filter_col = filter_target_col if filter_target_col else value_cols[0]

                    required = list(dict.fromkeys([actual_time_col] + value_cols + [actual_filter_col]))
                    missing = [col for col in required if col not in df.columns]
                    if missing:
                        raise KeyError("找不到所选数据列：" + "、".join(missing))

                    # 确保时间列为 datetime 格式（兼容“2026年5月21日”“2026.9.13”等写法）
                    raw_time_samples = df[actual_time_col].dropna().astype(str).head(3).tolist()
                    df[actual_time_col] = data_processor.parse_datetime_series(df[actual_time_col])
                    valid_time_rows = int(df[actual_time_col].notna().sum())
                    if valid_time_rows == 0:
                        raise ValueError(
                            f"所选横坐标列【{actual_time_col}】无法识别为日期时间，示例内容：{raw_time_samples}。"
                            "请确认横坐标选择的是时间/日期列。"
                        )

                    for c in dict.fromkeys(value_cols + [actual_filter_col]):
                        df[c] = pd.to_numeric(df[c], errors="coerce")

                    # 过滤目标列必须有值；所有已选数据列都为空的行没有可画的内容，一并去掉
                    df = df.dropna(subset=[actual_time_col, actual_filter_col])
                    df = df.dropna(subset=value_cols, how="all")
                    # 稳定排序：同一时刻（例如同一天的多条记录）保持文件中的原有先后顺序
                    df = df.sort_values(actual_time_col, kind="stable").reset_index(drop=True)
                    df = df[df[actual_filter_col] != 0].copy()
                    date_only = data_processor.is_date_only(df[actual_time_col])
                    label_fmt = "%m-%d" if date_only else "%m-%d %H:%M:%S"
                    range_fmt = "%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M:%S"

                    # 动态过滤逻辑
                    if min_threshold is not None and max_threshold is not None:
                        df = df[(df[actual_filter_col] >= min_threshold) & (df[actual_filter_col] <= max_threshold)].copy()
                    elif min_threshold is not None:
                        df = df[df[actual_filter_col] >= min_threshold].copy()
                    elif max_threshold is not None:
                        df = df[df[actual_filter_col] <= max_threshold].copy()

                    if df.empty:
                        data_range_text = "（过滤后没有剩余数据，请检查数据列选择与过滤阈值）"
                    else:
                        data_range_text = (
                            f"数据有效时间范围：{df[actual_time_col].min().strftime(range_fmt)} ~ "
                            f"{df[actual_time_col].max().strftime(range_fmt)}，共 {len(df)} 行"
                        )

                    palette = [
                        ("#85B2FF", "#1E3F66"),
                        ("#52C41A", "#135200"),
                        ("#FF7875", "#820014"),
                        ("#B37FEB", "#391085"),
                        ("#FF9C6E", "#873800"),
                        ("#36CBCB", "#00474F"),
                        ("#FF85C0", "#990033"),
                        ("#D3F261", "#5B8C00"),
                    ]

                    plotted_periods = []
                    diagnostics = []
                    periods_detailed_info = []

                    for index, interval in enumerate(st.session_state.intervals):
                        start_dt = pd.to_datetime(interval["start"])
                        end_dt = pd.to_datetime(interval["end"])
                        part = select_period_rows(df, actual_time_col, start_dt, end_dt, date_only)
                        diagnostics.append(f"时段 {index + 1}：匹配到 {len(part)} 行")

                        if part.empty:
                            continue

                        part = part.sort_values(actual_time_col, kind="stable").reset_index(drop=True)
                        fill_color, line_color = palette[index % len(palette)]
                        actual_start = part[actual_time_col].min().strftime(range_fmt)
                        actual_end = part[actual_time_col].max().strftime(range_fmt)
                        run_value = interval.get("run_sec", "0")
                        stop_value = interval.get("stop_sec", "-")

                        if run_value in ("0", "0.0"):
                            config_str = "多频集速没有运行"
                        else:
                            config_str = f"多频集速运行{run_value}s/停止{stop_value}s"

                        if min_threshold is not None and max_threshold is not None:
                            time_prefix = f"{filter_metric_name} {format_num(min_threshold)}-{format_num(max_threshold)}，机组实际运行时间"
                        elif min_threshold is not None:
                            time_prefix = f"{filter_metric_name}≥{format_num(min_threshold)}，机组实际运行时间"
                        elif max_threshold is not None:
                            time_prefix = f"{filter_metric_name}≤{format_num(max_threshold)}，机组实际运行时间"
                        else:
                            time_prefix = "机组实际运行时间"

                        description = f"{config_str} ({time_prefix} {actual_start} ~ {actual_end})"

                        plotted_periods.append({
                            "data": part,
                            "fill_color": fill_color,
                            "line_color": line_color,
                            "description": description,
                        })
                        periods_detailed_info.append({
                            "text": f"监测数据时间段 {index + 1}：{description}",
                            "color": fill_color
                        })

                    diag_text = "🔍 各时段数据检索诊断：" + " | ".join(diagnostics)
                    if date_only:
                        diag_text += "\n\n📅 数据只有日期、没有具体时刻，已按“天”匹配时间段。"
                    st.info(diag_text)

                    if not plotted_periods:
                        st.warning("指定时间段和过滤条件下均未检索到有效数据。" + data_range_text)
                        st.session_state.plotted_fig_bytes = None
                        st.session_state.plotted_title = ""
                        st.session_state.plotted_periods_info = []
                    else:
                        unify_axes, _unify_reason = data_processor.should_unify_axes(
                            st.session_state.get("axis_scale_mode"),
                            axis_info.get("left_custom", ""), left_cols,
                            axis_info.get("right_custom", ""), right_cols,
                        )
                        fig, scale_note, _x_labels = draw_trend_chart(
                            plotted_periods, actual_time_col, left_cols, right_cols,
                            left_names, right_names,
                            final_time_label, final_left_label, final_right_label,
                            label_fmt, unify_axes,
                        )

                        title_names = "/".join(n for n in (left_short, right_short) if n)
                        chart_title = f"{title_names}对比趋势图（{filter_metric_name}区间：{cond_str_clean}）"
                        fig.axes[0].set_title(chart_title, fontsize=14, pad=20)

                        # 预览区的“图例说明”：面积图/折线图分别代表什么
                        n_left, n_right = len(left_cols), len(right_cols)
                        tip_parts = []
                        if n_left:
                            tip_parts.append(
                                f"面积图代表{left_short}" if n_left == 1
                                else "左轴折线：" + "、".join(left_names.get(c, c) for c in left_cols)
                            )
                        if n_right:
                            tip_parts.append(
                                f"折线图代表{right_short}" if n_right == 1
                                else "右轴折线：" + "、".join(right_names.get(c, c) for c in right_cols)
                            )
                        if n_left > 1 or n_right > 1:
                            plotted_tip = "；".join(tip_parts) + "；颜色区分时间段，线型区分数据列"
                        else:
                            plotted_tip = "，".join(tip_parts)

                        buf = io.BytesIO()
                        fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", pad_inches=0.05)
                        buf.seek(0)
                        st.session_state.plotted_fig_bytes = buf.getvalue()
                        st.session_state.plotted_title = chart_title
                        st.session_state.plotted_periods_info = periods_detailed_info
                        st.session_state["plotted_tip"] = plotted_tip
                        st.session_state["current_pressure_col"] = _source_tag(right_cols or left_cols)
                        st.session_state["current_filter_metric"] = filter_metric_name
                        plt.close(fig)
                        st.success("多时段对比趋势图生成成功！" + scale_note)

                except Exception as e:
                    if fig is not None:
                        plt.close(fig)
                    st.error(f"绘图过程中发生错误：{e}")

    if st.session_state.get("plotted_fig_bytes"):
        st.markdown("---")
        st.subheader("📊 生成的对比趋势图预览")
        st.image(st.session_state.plotted_fig_bytes, use_container_width=True)

        with st.container(border=True):
            active_metric = st.session_state.get("current_filter_metric", filter_metric_name)

            st.markdown(f"📋 **各时段详细起止与配置说明（{active_metric}区间 {cond_str_clean}）**", unsafe_allow_html=True)

            plotted_tip = st.session_state.get("plotted_tip", "")
            if plotted_tip:
                st.markdown(
                    f"<div style='background-color: #f0f2f6; padding: 10px; border-radius: 5px; margin-bottom: 12px; text-align: center;'>"
                    f"<span style='color: #d93838; font-weight: bold; font-size: 16px;'>💡 提示：</span>"
                    f"<span style='font-weight: bold; font-size: 15px; color: #1f1f1f;'>{plotted_tip}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )

            for item in st.session_state.get("plotted_periods_info", []):
                color = item.get("color", "#31333F")
                text = item.get("text", "")
                st.markdown(
                    f"<div style='display: flex; align-items: center; margin-bottom: 6px;'>"
                    f"<span style='display: inline-block; width: 14px; height: 14px; background-color: {color}; margin-right: 8px; border-radius: 2px;'></span>"
                    f"<span style='font-size: 15px; color: #31333F;'>{text}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                label="⬇️ 下载趋势图 PNG",
                data=st.session_state.plotted_fig_bytes,
                file_name="unit_load_pressure_comparison.png",
                mime="image/png",
                type="primary",
                use_container_width=True
            )
        with dl_col2:
            if st.button("☁️ 保存图片到 Cloudflare R2", use_container_width=True):
                if r2_storage._get_r2_client() is None:
                    st.error("Cloudflare R2 尚未连接，无法保存。")
                else:
                    try:
                        scheme_name = st.session_state.get("current_scheme_name", "")
                        if not scheme_name and st.session_state.get("intervals"):
                            f_date = str(st.session_state.intervals[0].get("start", "")).split()[0]
                            l_date = str(st.session_state.intervals[-1].get("end", "")).split()[0]
                            scheme_name = f"监测数据时间段 ({f_date} ~ {l_date})"
                        elif not scheme_name:
                            scheme_name = "未命名时间段方案"
                        
                        p_col_current = st.session_state.get("current_pressure_col") or _source_tag(right_cols or left_cols)
                        active_metric_save = _safe_tag(st.session_state.get("current_filter_metric", filter_metric_name))
                        
                        if min_threshold is not None and max_threshold is not None:
                            load_tag_str = f"{active_metric_save}_{format_num(min_threshold)}_{format_num(max_threshold)}"
                        elif min_threshold is not None:
                            load_tag_str = f"{active_metric_save}_≥{format_num(min_threshold)}"
                        elif max_threshold is not None:
                            load_tag_str = f"{active_metric_save}_≤{format_num(max_threshold)}"
                        else:
                            load_tag_str = f"{active_metric_save}_全部"

                        time_str = datetime.now().strftime('%Y%m%d_%H%M%S')
                        chart_filename = f"{p_col_current}_{load_tag_str}_{time_str}.png"
                        
                        _factory = st.session_state.get("selected_factory")
                        if not _factory:
                            raise RuntimeError("尚未选择工厂，无法保存图片。")
                        _chart_dir = f"chart_history_{_factory}"
                        os.makedirs(_chart_dir, exist_ok=True)
                        chart_local_path = os.path.join(_chart_dir, chart_filename)
                        with open(chart_local_path, "wb") as img_file:
                            img_file.write(st.session_state.plotted_fig_bytes)
                        
                        success = r2_storage.r2_upload_file(chart_local_path, key=f"chart_history/{scheme_name}/{chart_filename}")
                        if success:
                            st.success(f"图片已成功归类保存至 R2！\n📁 分类目录：`{scheme_name}`\n🏷️ 命名规范：`{chart_filename}`")
                        else:
                            st.error("同步到 Cloudflare R2 失败，请检查网络或配置。")
                    except Exception as e:
                        st.error(f"保存图片时出错：{e}")
