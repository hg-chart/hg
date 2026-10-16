# -*- coding: utf-8 -*-
"""模块五：图表绘制与预览"""
import io
import matplotlib.pyplot as plt
from matplotlib import ticker
import pandas as pd
import streamlit as st

COLUMN_ALIASES = {
    "压差": "W3.FW.AHTE10CP201F",
    "负荷": "W3.UNIT1.10DEHDCSAI03",
}

def render_chart_generator(df_raw, time_col, load_col, pressure_col, threshold, threshold_valid):
    """渲染生成趋势图的触发按钮及预览界面"""
    if st.button("🚀 开始生成多时段对比趋势图", type="primary"):
        if not threshold_valid:
            st.error("请先把负荷下限阈值修改为有效数字。")
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
                    rename_map = {
                        col: COLUMN_ALIASES[col]
                        for col in df.columns
                        if col in COLUMN_ALIASES
                    }
                    df = df.rename(columns=COLUMN_ALIASES)
                    actual_time_col = rename_map.get(time_col, time_col)
                    actual_load_col = rename_map.get(load_col, load_col)
                    actual_pressure_col = rename_map.get(pressure_col, pressure_col)

                    required = [actual_time_col, actual_load_col, actual_pressure_col]
                    missing = [col for col in required if col not in df.columns]
                    if missing:
                        raise KeyError("找不到所选数据列：" + "、".join(missing))

                    df[actual_time_col] = pd.to_datetime(
                        df[actual_time_col].astype(str).str.strip(),
                        format="mixed",
                        errors="coerce",
                    )
                    df[actual_load_col] = pd.to_numeric(df[actual_load_col], errors="coerce")
                    df[actual_pressure_col] = pd.to_numeric(df[actual_pressure_col], errors="coerce")
                    df = df.dropna(subset=[actual_time_col, actual_load_col])
                    df = df.sort_values(actual_time_col).reset_index(drop=True)
                    df = df[df[actual_load_col] != 0].copy()

                    if threshold is not None:
                        df = df[df[actual_load_col] >= threshold].copy()

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
                        part = df[
                            (df[actual_time_col] >= start_dt)
                            & (df[actual_time_col] <= end_dt)
                        ].copy()
                        diagnostics.append(f"时段 {index + 1}：匹配到 {len(part)} 行")

                        if part.empty:
                            continue

                        part = part.sort_values(actual_time_col).reset_index(drop=True)
                        fill_color, line_color = palette[index % len(palette)]
                        actual_start = part[actual_time_col].min().strftime("%Y-%m-%d %H:%M:%S")
                        actual_end = part[actual_time_col].max().strftime("%Y-%m-%d %H:%M:%S")
                        run_value = interval.get("run_sec", "0")
                        stop_value = interval.get("stop_sec", "-")
                        
                        if run_value in ("0", "0.0"):
                            config_str = "多频集速没有运行"
                        else:
                            config_str = f"多频集速运行{run_value}s/停止{stop_value}s"

                        if threshold is not None:
                            threshold_int = int(threshold)
                            time_prefix = f"负荷≥{threshold_int}，机组实际运行时间"
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

                    st.info("🔍 各时段数据检索诊断：" + " | ".join(diagnostics))

                    if not plotted_periods:
                        st.warning("指定时间段和负荷阈值下均未检索到有效数据。")
                        st.session_state.plotted_fig_bytes = None
                        st.session_state.plotted_title = ""
                        st.session_state.plotted_periods_info = []
                    else:
                        fig, ax1 = plt.subplots(figsize=(16, 8))
                        ax2 = ax1.twinx()

                        all_x_labels = []
                        cursor = 0

                        for period in plotted_periods:
                            part = period["data"]
                            count = len(part)
                            x_values = list(range(cursor, cursor + count))
                            cursor += count
                            all_x_labels.extend(
                                part[actual_time_col].dt.strftime("%m-%d %H:%M:%S").tolist()
                            )

                            ax1.fill_between(
                                x_values,
                                part[actual_load_col].to_numpy(),
                                color=period["fill_color"],
                                alpha=0.50,
                                label=f"负荷 {period['description']}",
                            )
                            ax1.plot(
                                x_values,
                                part[actual_load_col].to_numpy(),
                                color=period["fill_color"],
                                linewidth=0.8,
                                alpha=0.9,
                            )
                            ax2.plot(
                                x_values,
                                part[actual_pressure_col].to_numpy(),
                                color=period["line_color"],
                                linewidth=1.5,
                                label=f"压差 {period['description']}",
                            )

                        ax1.set_xlabel("运行时间段", fontsize=12)
                        ax1.set_ylabel(f"负荷（{actual_load_col}）", fontsize=12, color="black")
                        ax2.set_ylabel(f"压差（{actual_pressure_col}）", fontsize=12, color="black")

                        ax1.grid(False)
                        ax2.yaxis.set_major_locator(ticker.MultipleLocator(200))
                        ax2.grid(True, linestyle="--", alpha=0.5, color="gray")

                        max_xticks = 12
                        step = max(1, len(all_x_labels) // max_xticks)
                        tick_positions = list(range(0, len(all_x_labels), step))
                        tick_labels = [all_x_labels[i] for i in tick_positions]

                        ax1.set_xticks(tick_positions)
                        ax1.set_xticklabels(tick_labels, rotation=30, ha="right")
                        ax1.tick_params(axis="x", labelsize=10)

                        lines1, labels1 = ax1.get_legend_handles_labels()
                        lines2, labels2 = ax2.get_legend_handles_labels()
                        
                        combined_lines = lines1 + lines2
                        combined_labels = labels1 + labels2

                        legend_rows = (len(combined_labels) + 1) // 2
                        legend_h_in = legend_rows * 0.24 + 0.3
                        base_h_in = 8.0
                        fig_h_in = base_h_in + legend_h_in
                        fig.set_size_inches(16, fig_h_in)

                        fig.tight_layout(rect=[0, legend_h_in / fig_h_in, 1, 1])
                        fig.legend(
                            combined_lines,
                            combined_labels,
                            loc="lower center",
                            bbox_to_anchor=(0.5, 0.1 / fig_h_in),
                            ncol=2,
                            fontsize=9.5,
                            frameon=True,
                        )

                        if threshold is not None:
                            chart_title_threshold = f"≥ {int(threshold)}"
                        else:
                            chart_title_threshold = "全部"
                        chart_title = f"机组负荷/压差对比趋势图（最低负荷 {chart_title_threshold}）"
                        plt.title(chart_title, fontsize=14, pad=20)

                        buf = io.BytesIO()
                        fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", pad_inches=0.05)
                        buf.seek(0)
                        st.session_state.plotted_fig_bytes = buf.getvalue()
                        st.session_state.plotted_title = chart_title
                        st.session_state.plotted_periods_info = periods_detailed_info
                        plt.close(fig)
                        st.success("多时段对比趋势图生成成功！")

                except Exception as e:
                    if fig is not None:
                        plt.close(fig)
                    st.error(f"绘图过程中发生错误：{e}")

    # 渲染预览与下载区域
    if st.session_state.get("plotted_fig_bytes"):
        st.markdown("---")
        st.subheader("📊 生成的对比趋势图预览")
        st.image(st.session_state.plotted_fig_bytes, use_container_width=True)

        with st.container(border=True):
            if threshold is not None:
                current_threshold_str = f"负荷≥{int(threshold)}"
            else:
                current_threshold_str = "全部负荷"
            st.markdown(f"📋 **各时段详细起止与配置说明（{current_threshold_str}）**", unsafe_allow_html=True)
            
            st.markdown(
                "<div style='background-color: #f0f2f6; padding: 10px; border-radius: 5px; margin-bottom: 12px; text-align: center;'>"
                "<span style='color: #d93838; font-weight: bold; font-size: 16px;'>💡 提示：</span>"
                "<span style='font-weight: bold; font-size: 15px; color: #1f1f1f;'>面积图代表负荷，折线图代表压差</span>"
                "</div>",
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
                        
                        load_tag_str = f"负荷_{int(threshold)}" if threshold is not None else "负荷_全部"
                        time_str = datetime.now().strftime('%Y%m%d_%H%M%S')
                        chart_filename = f"{load_tag_str}_{time_str}.png"
                        
                        chart_local_path = os.path.join("chart_history", chart_filename)
                        with open(chart_local_path, "wb") as img_file:
                            img_file.write(st.session_state.plotted_fig_bytes)
                        
                        success = r2_storage.r2_upload_file(chart_local_path, key=f"chart_history/{scheme_name}/{chart_filename}")
                        if success:
                            st.success(f"图片已成功归类保存至 R2！\n📁 分类目录：`{scheme_name}`\n🏷️ 负荷标签：`{load_tag_str}`")
                        else:
                            st.error("同步到 Cloudflare R2 失败，请检查网络或配置。")
                    except Exception as e:
                        st.error(f"保存图片时出错：{e}")
