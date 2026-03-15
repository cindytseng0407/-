import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from dataclasses import dataclass
from typing import Optional
import os

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="桃園中壢 AVM 房價評估系統",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# 內建預設資料（可被CSV覆蓋）
# ─────────────────────────────────────────────

# 各商圈市場均價（元/坪）
DEFAULT_MARKET_PRICES = {
    # ── 中壢區（2024Q4實價登錄校正值）
    "【中壢】體育園區重劃區（青埔）": {
        "unit_price_ping": 420000,   # 樂居近一年均價39萬/新屋47萬，青埔因高鐵溢價取42萬
        "land_price_sqm": 243000,
        "far": 2.25,
        "monthly_rent_ping": 950,
        "cap_rate": 0.024,
        "description": "青埔高鐵特區，機捷環北站，桃園最熱重劃區",
        "region": "中壢區",
    },
    "【中壢】中壢核心商圈": {
        "unit_price_ping": 310000,   # 中壢市區電梯大樓實際成交約28-33萬
        "land_price_sqm": 201000,
        "far": 3.60,
        "monthly_rent_ping": 720,
        "cap_rate": 0.025,
        "description": "中壢火車站周邊，生活機能完善，都更潛力",
        "region": "中壢區",
    },
    "【中壢】中原大學商圈": {
        "unit_price_ping": 270000,   # 學區穩定，近一年約25-28萬
        "land_price_sqm": 166000,
        "far": 1.60,
        "monthly_rent_ping": 670,
        "cap_rate": 0.025,
        "description": "學區房，租賃需求穩定，自住首購首選",
        "region": "中壢區",
    },
    "【中壢】龍岡商圈": {
        "unit_price_ping": 240000,   # 龍岡約22-26萬
        "land_price_sqm": 127000,
        "far": 1.60,
        "monthly_rent_ping": 600,
        "cap_rate": 0.025,
        "description": "自住型社區，東南亞族裔聚集，性價比高",
        "region": "中壢區",
    },
    "【中壢】內壢工業區周邊": {
        "unit_price_ping": 210000,   # 內壢約20-23萬
        "land_price_sqm": 87000,
        "far": 1.60,
        "monthly_rent_ping": 540,
        "cap_rate": 0.026,
        "description": "工業區勞工剛需市場，總價親民",
        "region": "中壢區",
    },
    # ── 龜山區（2024-2025實價登錄資料）
    "【龜山】A7重劃區（體育大學生活圈）": {
        "unit_price_ping": 480000,   # 樂居2025均價45.74萬，A7均價47-48萬
        "land_price_sqm": 185000,
        "far": 2.30,
        "monthly_rent_ping": 1050,
        "cap_rate": 0.023,
        "description": "機捷A7站，大林口生活圈，北台灣首購熱區",
        "region": "龜山區",
    },
    "【龜山】長庚醫院商圈（A8周邊）": {
        "unit_price_ping": 600000,   # A8周邊約60萬/坪
        "land_price_sqm": 220000,
        "far": 2.40,
        "monthly_rent_ping": 1300,
        "cap_rate": 0.023,
        "description": "機捷A8站，長庚醫院生活圈，環球百貨，機能成熟",
        "region": "龜山區",
    },
    "【龜山】華亞科技園區周邊": {
        "unit_price_ping": 470000,   # 華亞周邊約45-50萬
        "land_price_sqm": 175000,
        "far": 2.25,
        "monthly_rent_ping": 1000,
        "cap_rate": 0.023,
        "description": "廣達、欣興等科技廠區旁，就業人口需求大",
        "region": "龜山區",
    },
    "【龜山】迴龍捷運站周邊": {
        "unit_price_ping": 560000,   # 迴龍接近新莊價，約55-60萬
        "land_price_sqm": 210000,
        "far": 2.25,
        "monthly_rent_ping": 1200,
        "cap_rate": 0.023,
        "description": "捷運迴龍站，雙北邊界，接近新莊價格帶",
        "region": "龜山區",
    },
    "【龜山】龜山舊市區": {
        "unit_price_ping": 320000,   # 舊市區3字頭，約30-35萬
        "land_price_sqm": 130000,
        "far": 1.60,
        "monthly_rent_ping": 720,
        "cap_rate": 0.025,
        "description": "龜山傳統市區，銘傳大學周邊，房價低基期",
        "region": "龜山區",
    },
}

# 建物等級與營造成本
CONSTRUCTION_COST = {
    "標準RC電梯大樓（一般裝潢）": 130000,   # 元/坪
    "精裝修電梯大樓": 165000,
    "豪宅級精裝修": 220000,
}

# 品牌溢價（三派系）
BRAND_PREMIUM = {
    "標竿派 — 中悅、國泰、桃大、京懋、璞園、昇捷": 0.10,
    "實力派 — 昭揚、威均、中麗、長昇、禾林": 0.05,
    "規模派 — 寶佳、興富發": 0.03,
    "其他 / 不知名建商": 0.00,
}

BRAND_LABEL = {
    "標竿派 — 中悅、國泰、桃大、京懋、璞園、昇捷": "標竿派",
    "實力派 — 昭揚、威均、中麗、長昇、禾林": "實力派",
    "規模派 — 寶佳、興富發": "規模派",
    "其他 / 不知名建商": "其他",
}

# 各商圈歷年均價趨勢（元/坪，來源：實價登錄統計+樂居行情資料）
MARKET_TREND = {
    # 中壢區（2024Q4校正）
    "【中壢】體育園區重劃區（青埔）": {
        2020: 270000, 2021: 310000, 2022: 350000, 2023: 390000, 2024: 420000,
    },
    "【中壢】中壢核心商圈": {
        2020: 200000, 2021: 230000, 2022: 260000, 2023: 285000, 2024: 310000,
    },
    "【中壢】中原大學商圈": {
        2020: 180000, 2021: 205000, 2022: 230000, 2023: 252000, 2024: 270000,
    },
    "【中壢】龍岡商圈": {
        2020: 160000, 2021: 183000, 2022: 205000, 2023: 224000, 2024: 240000,
    },
    "【中壢】內壢工業區周邊": {
        2020: 140000, 2021: 160000, 2022: 178000, 2023: 196000, 2024: 210000,
    },
    # 龜山區（來源：樂居、住展、實價登錄統計）
    "【龜山】A7重劃區（體育大學生活圈）": {
        2020: 253000, 2021: 320000, 2022: 349000, 2023: 400000, 2024: 480000,
    },
    "【龜山】長庚醫院商圈（A8周邊）": {
        2020: 420000, 2021: 480000, 2022: 530000, 2023: 570000, 2024: 600000,
    },
    "【龜山】華亞科技園區周邊": {
        2020: 300000, 2021: 350000, 2022: 390000, 2023: 430000, 2024: 470000,
    },
    "【龜山】迴龍捷運站周邊": {
        2020: 380000, 2021: 430000, 2022: 480000, 2023: 520000, 2024: 560000,
    },
    "【龜山】龜山舊市區": {
        2020: 200000, 2021: 230000, 2022: 260000, 2023: 290000, 2024: 320000,
    },
}

# 車位類型與市場價格
PARKING_PRICE = {
    "無車位": 0,
    "平面車位": 1_500_000,
    "坡道平面": 1_200_000,
    "機械車位": 700_000,
    "地下室平面（含管理）": 1_800_000,
}

# ─────────────────────────────────────────────
# 工具函式
# ─────────────────────────────────────────────

def load_csv_data(filepath: str, file_type: str) -> Optional[pd.DataFrame]:
    """嘗試讀取CSV，失敗回傳None"""
    if not os.path.exists(filepath):
        return None
    try:
        df = pd.read_csv(filepath, encoding="utf-8-sig")
        return df
    except Exception as e:
        st.warning(f"讀取 {file_type} 失敗：{e}")
        return None

def clean_transaction_data(df: pd.DataFrame, district: str = "中壢區") -> pd.DataFrame:
    """清洗實價登錄資料"""
    # 篩選中壢區
    if "鄉鎮市區" in df.columns:
        df = df[df["鄉鎮市區"].str.contains(district, na=False)]
    # 篩選住宅用途
    if "主要用途" in df.columns:
        df = df[df["主要用途"].str.contains("住家", na=False)]
    # 篩選電梯大樓/華廈
    if "建物型態" in df.columns:
        df = df[df["建物型態"].str.contains("大樓|華廈", na=False)]
    # 轉換數值欄位
    for col in ["單價元平方公尺", "總價元", "建物移轉總面積"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # 去除空值
    df = df.dropna(subset=["單價元平方公尺"]) if "單價元平方公尺" in df.columns else df
    # Z-score 去離群值（±2σ）
    if "單價元平方公尺" in df.columns and len(df) > 10:
        mean = df["單價元平方公尺"].mean()
        std = df["單價元平方公尺"].std()
        df = df[abs(df["單價元平方公尺"] - mean) <= 2 * std]
    return df

def sqm_to_ping(sqm: float) -> float:
    return sqm / 3.3058

def ping_to_sqm(ping: float) -> float:
    return ping * 3.3058

# ─────────────────────────────────────────────
# 三法計算核心
# ─────────────────────────────────────────────

def calc_market_comparison(
    market_price_ping: float,
    area_ping: float,
    floor_adj: float,
    brand_adj: float,
    public_ratio_adj: float,
    transport_adj: float,
    view_adj: float,
) -> dict:
    """市場比較法"""
    total_adj = 1 + floor_adj + brand_adj + public_ratio_adj + transport_adj + view_adj
    adjusted_price = market_price_ping * total_adj
    total_price = adjusted_price * area_ping
    return {
        "method": "市場比較法",
        "unit_price_ping": adjusted_price,
        "total_price": total_price,
        "adjustment_factor": total_adj,
    }

def calc_cost_approach(
    land_price_sqm: float,
    plot_area_ping: float,
    far: float,
    floors: int,
    construction_cost_ping: float,
    building_age: int,
    area_ping: float,
    public_ratio: float,
) -> dict:
    """成本法（含地價分攤 + 殘值折舊）"""
    # 地價分攤（單位：元/坪）
    land_total = land_price_sqm * ping_to_sqm(plot_area_ping)
    total_building_area_ping = plot_area_ping * far * 1.1  # 含公設估計
    land_per_ping = land_total / max(total_building_area_ping, 1)

    # 建物折舊（殘值10%，耐用年限50年）
    depreciation_rate = max(0.10, 1.0 - (building_age / 50) * 0.9)
    building_cost_ping = construction_cost_ping * depreciation_rate

    # 公設比調整（實坪概念）
    effective_ratio = 1 - public_ratio
    unit_price_ping = (land_per_ping + building_cost_ping)

    total_price = unit_price_ping * area_ping
    return {
        "method": "成本法",
        "unit_price_ping": unit_price_ping,
        "total_price": total_price,
        "land_cost_ping": land_per_ping,
        "building_cost_ping": building_cost_ping,
        "depreciation_rate": depreciation_rate,
    }

def calc_income_approach(
    monthly_rent_ping: float,
    area_ping: float,
    public_ratio: float,
    cap_rate: float,
    vacancy_rate: float = 0.05,
) -> dict:
    """收益法（直接資本化）"""
    effective_area = area_ping * (1 - public_ratio)
    annual_rent = monthly_rent_ping * effective_area * 12 * (1 - vacancy_rate)
    # 扣除費用（管理費、修繕、稅）約15%
    net_income = annual_rent * 0.85
    total_price = net_income / cap_rate
    unit_price_ping = total_price / area_ping if area_ping > 0 else 0
    return {
        "method": "收益法",
        "unit_price_ping": unit_price_ping,
        "total_price": total_price,
        "annual_net_income": net_income,
        "cap_rate": cap_rate,
    }

def weighted_average(results: list, weights: list) -> dict:
    """三法加權平均"""
    total_w = sum(weights)
    w = [x / total_w for x in weights]
    unit_price = sum(r["unit_price_ping"] * w[i] for i, r in enumerate(results))
    total_price = sum(r["total_price"] * w[i] for i, r in enumerate(results))
    return {"unit_price_ping": unit_price, "total_price": total_price}

def risk_signal(asking_price: float, estimated_price: float) -> tuple:
    """計算風險燈號"""
    ratio = asking_price / estimated_price if estimated_price > 0 else 1
    if ratio <= 1.05:
        return "🟢 合理", "green", ratio
    elif ratio <= 1.15:
        return "🟡 偏高", "orange", ratio
    else:
        return "🔴 過高", "red", ratio

# ─────────────────────────────────────────────
# UI 主體
# ─────────────────────────────────────────────

def main():
    # ── 標題
    st.markdown("""
    <div style='background: linear-gradient(135deg, #1a1f2e, #2d3548);
                padding: 24px 32px; border-radius: 12px; margin-bottom: 24px;
                border-left: 4px solid #c8a96e;'>
        <h1 style='color:#c8a96e; margin:0; font-size:1.8rem;'>🏠 桃園 AVM 房價評估系統</h1>
        <p style='color:#9aa0b0; margin:4px 0 0 0;'>三法估價模型 ｜ 市場比較法 + 成本法 + 收益法 ｜ 中壢區・龜山區</p>
    </div>
    """, unsafe_allow_html=True)

    # ── 側邊欄：僅顯示系統資訊
    with st.sidebar:
        st.markdown("### ℹ️ 系統資訊")
        st.info("📋 使用內建預設資料\n（2024Q4實價登錄校正值）")
        st.caption("資料來源：內政部實價登錄、樂居房價統計、住展市調")
        st.divider()
        st.markdown("### 📍 適用區域")
        st.caption("✅ 桃園市中壢區（5個商圈）")
        st.caption("✅ 桃園市龜山區（5個商圈）")
        st.divider()
        st.markdown("### ⚙️ 三法權重（內部設定）")
        st.caption("市場比較法：60%")
        st.caption("成本法：20%")
        st.caption("收益法：20%")

    # 內部固定權重（不提供使用者調整）
    w1, w2, w3 = 60, 20, 20
    total_w = 100

    # 上傳資料（停用，全用內建）
    uploaded_transactions = []
    uploaded_land = None
    tx_folder_path = ""
    land_file_path = ""

    # ── 主面板：兩欄
    col_input, col_result = st.columns([1, 1.2], gap="large")

    with col_input:
        st.markdown("### 📝 物件資訊輸入")

        # 基本資料
        with st.expander("📍 位置與物件類型", expanded=True):
            district = st.selectbox("商圈", list(DEFAULT_MARKET_PRICES.keys()))
            d = DEFAULT_MARKET_PRICES[district]
            st.caption(f"ℹ️ {d['description']}")

            building_type = st.selectbox("建物型態", ["電梯大樓", "電梯華廈"])
            building_age = st.slider("屋齡（年）", 0, 40, 5)
            total_floors = st.number_input("總樓層數", min_value=3, max_value=50, value=15)
            target_floor = st.number_input("物件樓層", min_value=1, max_value=50, value=8)

        with st.expander("📐 面積與格局", expanded=True):
            area_ping = st.number_input("建物主建物坪數（坪）", min_value=5.0, max_value=150.0, value=28.0, step=0.5)
            public_ratio = st.slider("公設比（%）", 20, 45, 33) / 100
            st.markdown("""
            <div style='background:#f0f7ff; border-left:4px solid #5b8cff;
                        border-radius:6px; padding:12px 14px; margin-top:8px;'>
                <div style='font-size:0.8rem; font-weight:600; color:#2E5FA3; margin-bottom:6px;'>
                    🚗 車位市場行情參考（實價登錄獨立登記）
                </div>
                <div style='font-size:0.8rem; color:#374151; line-height:1.8;'>
                    平面車位：<b>120～180萬</b><br>
                    坡道平面：<b>100～150萬</b><br>
                    機械車位：<b>50～80萬</b><br>
                    地下室平面（含管理）：<b>150～200萬</b>
                </div>
                <div style='font-size:0.75rem; color:#6B7280; margin-top:6px;'>
                    ※ 車位價格於實價登錄中獨立登記，本系統估算不含車位，請另行參考上述行情。
                </div>
            </div>
            """, unsafe_allow_html=True)

        with st.expander("🏗️ 建商與成本", expanded=True):
            construction_grade = st.selectbox("建物等級", list(CONSTRUCTION_COST.keys()))
            brand = st.selectbox("建商品牌", list(BRAND_PREMIUM.keys()))
            plot_area_ping = st.number_input("基地面積（坪）", min_value=50.0, max_value=5000.0, value=500.0, step=50.0)

        with st.expander("💰 開價資訊", expanded=True):
            asking_total = st.number_input(
                "建商開價總價（萬元，不含車位）", min_value=100, max_value=10000, value=1200, step=10
            )
            asking_total_yuan = asking_total * 10000

        with st.expander("🔧 加分/扣分項目", expanded=False):
            near_mrt = st.checkbox("捷運站500m內")
            near_venue = st.checkbox("體育園區景觀/機能加分")
            high_floor = st.checkbox("高樓層景觀（前1/3樓）")
            first_row = st.checkbox("首排景觀（海景/公園/河岸）")
            bad_view = st.checkbox("負面因素（工廠/高架/嫌惡）")

    # ── 右側結果
    with col_result:
        st.markdown("### 📊 估價結果")

        # 計算調整因子
        floor_adj = 0.03 if high_floor else 0.0
        brand_adj = BRAND_PREMIUM[brand]
        public_adj = 0.02 if public_ratio < 0.32 else (-0.03 if public_ratio > 0.35 else 0.0)
        transport_adj = 0.05 if near_mrt else 0.0
        venue_adj = 0.03 if near_venue else 0.0
        view_adj = 0.05 if first_row else 0.0
        neg_adj = -0.05 if bad_view else 0.0
        total_transport_adj = transport_adj + venue_adj

        # 地價：優先用上傳資料，否則內建
        land_price_sqm = d["land_price_sqm"]
        if uploaded_land:
            try:
                land_df = pd.read_csv(uploaded_land, header=None,
                                      names=["縣市", "行政區", "地段", "地號", "公告地價", "公告現值"],
                                      encoding="utf-8-sig")
                land_price_sqm = land_df["公告地價"].median()
                st.caption(f"📌 地價中位數（已載入）：{land_price_sqm:,.0f} 元/㎡")
            except:
                pass
        elif land_file_path and os.path.isfile(land_file_path):
            try:
                land_df = pd.read_csv(land_file_path, header=None,
                                      names=["縣市", "行政區", "地段", "地號", "公告地價", "公告現值"],
                                      encoding="utf-8-sig")
                land_price_sqm = land_df["公告地價"].median()
                st.caption(f"📌 地價中位數（資料夾）：{land_price_sqm:,.0f} 元/㎡")
            except:
                pass

        # 市場均價：優先用上傳/資料夾資料
        market_price_ping = d["unit_price_ping"]

        # 合併多個實價登錄CSV
        all_tx_dfs = []
        if len(uploaded_transactions) > 0:
            for f in uploaded_transactions:
                try:
                    df = pd.read_csv(f, encoding="utf-8-sig")
                    all_tx_dfs.append(df)
                except:
                    pass
        elif tx_folder_path and os.path.isdir(tx_folder_path):
            csv_files = [f for f in os.listdir(tx_folder_path) if f.endswith(".csv")]
            for fname in csv_files:
                try:
                    df = pd.read_csv(os.path.join(tx_folder_path, fname), encoding="utf-8-sig")
                    all_tx_dfs.append(df)
                except:
                    pass

        if all_tx_dfs:
            try:
                tx_df = pd.concat(all_tx_dfs, ignore_index=True)
                tx_df = clean_transaction_data(tx_df)
                if len(tx_df) > 5 and "單價元平方公尺" in tx_df.columns:
                    median_sqm = tx_df["單價元平方公尺"].median()
                    market_price_ping = sqm_to_ping(median_sqm)
                    st.caption(f"📌 市場均價（真實資料）：{market_price_ping:,.0f} 元/坪（n={len(tx_df)} 筆）")
            except:
                pass

        # 三法計算
        r1 = calc_market_comparison(
            market_price_ping, area_ping,
            floor_adj + view_adj, brand_adj, public_adj, total_transport_adj, neg_adj
        )
        r2 = calc_cost_approach(
            land_price_sqm, plot_area_ping, d["far"], total_floors,
            CONSTRUCTION_COST[construction_grade], building_age, area_ping, public_ratio
        )
        r3 = calc_income_approach(
            d["monthly_rent_ping"], area_ping, public_ratio, d["cap_rate"]
        )

        weighted = weighted_average([r1, r2, r3], [w1, w2, w3])

        # 開價比較（主建物，不含車位）
        signal, color, ratio = risk_signal(asking_total_yuan, weighted["total_price"])

        # ── 風險燈號
        st.markdown(f"""
        <div style='background:#1a1f2e; border:2px solid {"#2ecc71" if color=="green" else ("#f39c12" if color=="orange" else "#e74c3c")};
                    border-radius:12px; padding:20px; text-align:center; margin-bottom:16px;'>
            <div style='font-size:2rem;'>{signal}</div>
            <div style='color:#9aa0b0; font-size:0.9rem; margin-top:4px;'>
                開價 / 估值 = {ratio:.1%}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── 核心數字
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("估算單價", f"{weighted['unit_price_ping']:,.0f}", "元/坪")
        with c2:
            low = weighted["total_price"] * 0.95 / 10000
            high = weighted["total_price"] * 1.05 / 10000
            st.metric("合理總價區間", f"{low:,.0f}～{high:,.0f}", "萬元")
        with c3:
            st.metric("建商開價", f"{asking_total:,}", "萬元")

        # ── 三法明細
        st.markdown("#### 三法估價明細")
        method_data = {
            "方法": ["市場比較法（60%）", "成本法（20%）", "收益法（20%）", "**加權平均**"],
            "單價（元/坪）": [
                f"{r1['unit_price_ping']:,.0f}",
                f"{r2['unit_price_ping']:,.0f}",
                f"{r3['unit_price_ping']:,.0f}",
                f"**{weighted['unit_price_ping']:,.0f}**",
            ],
            "估算總價（萬）": [
                f"{r1['total_price']/10000:,.0f}",
                f"{r2['total_price']/10000:,.0f}",
                f"{r3['total_price']/10000:,.0f}",
                f"**{weighted['total_price']/10000:,.0f}**",
            ],
        }
        st.dataframe(pd.DataFrame(method_data), hide_index=True, use_container_width=True)

        # ── 調整因子明細
        with st.expander("🔍 調整因子明細（市場比較法）"):
            adj_items = {
                "項目": ["商圈市場均價", "高樓層景觀", "品牌溢價", "公設比調整",
                         "交通/機能", "首排景觀", "負面因素"],
                "調整幅度": [
                    f"{market_price_ping:,.0f} 元/坪（基準）",
                    f"+{floor_adj:.0%}" if floor_adj > 0 else "無",
                    f"+{brand_adj:.0%}" if brand_adj > 0 else "無",
                    (f"+{public_adj:.0%}" if public_adj > 0 else (f"{public_adj:.0%}" if public_adj < 0 else "無")),
                    f"+{total_transport_adj:.0%}" if total_transport_adj > 0 else "無",
                    f"+{view_adj:.0%}" if view_adj > 0 else "無",
                    f"{neg_adj:.0%}" if neg_adj < 0 else "無",
                ],
            }
            st.dataframe(pd.DataFrame(adj_items), hide_index=True, use_container_width=True)

        # ── 成本法明細
        with st.expander("🏗️ 成本法明細"):
            st.write(f"- 地價分攤：{r2['land_cost_ping']:,.0f} 元/坪")
            st.write(f"- 建物重置成本：{CONSTRUCTION_COST[construction_grade]:,.0f} 元/坪")
            st.write(f"- 折舊後建物成本：{r2['building_cost_ping']:,.0f} 元/坪（殘值 {r2['depreciation_rate']:.0%}）")

        # ── 收益法明細
        with st.expander("💵 收益法明細"):
            st.write(f"- 區域月租行情：{d['monthly_rent_ping']:,.0f} 元/坪/月")
            st.write(f"- 年淨收益（扣費損）：{r3['annual_net_income']:,.0f} 元")
            st.write(f"- 資本化率：{r3['cap_rate']:.1%}")
            st.write(f"- 估算總價：{r3['total_price']/10000:,.0f} 萬元")

        # ── 區域行情趨勢圖
        st.markdown("#### 📈 區域行情趨勢與估值位置")
        trend_data = MARKET_TREND[district]
        years = list(trend_data.keys())
        prices_trend = list(trend_data.values())

        # 估值單價
        est_unit = weighted["unit_price_ping"]
        low_unit = est_unit * 0.95
        high_unit = est_unit * 1.05

        fig2 = go.Figure()

        # 合理區間色塊
        fig2.add_hrect(
            y0=low_unit, y1=high_unit,
            fillcolor="#c8a96e", opacity=0.15,
            line_width=0,
            annotation_text="合理區間",
            annotation_position="right",
            annotation_font_color="#c8a96e",
        )

        # 趨勢曲線
        fig2.add_trace(go.Scatter(
            x=years, y=prices_trend,
            mode="lines+markers",
            name="商圈均價",
            line=dict(color="#5b8cff", width=3),
            marker=dict(size=8),
        ))

        # 估值水平線
        fig2.add_hline(
            y=est_unit,
            line_dash="dash",
            line_color="#c8a96e",
            line_width=2,
            annotation_text=f"本件估值 {est_unit:,.0f}",
            annotation_position="left",
            annotation_font_color="#c8a96e",
        )

        # 開價水平線
        asking_unit = asking_total_yuan / area_ping if area_ping > 0 else 0
        fig2.add_hline(
            y=asking_unit,
            line_dash="dot",
            line_color="#e74c3c" if color == "red" else ("#f39c12" if color == "orange" else "#2ecc71"),
            line_width=2,
            annotation_text=f"建商開價 {asking_unit:,.0f}",
            annotation_position="right",
            annotation_font_color="#e74c3c" if color == "red" else ("#f39c12" if color == "orange" else "#2ecc71"),
        )

        fig2.update_layout(
            paper_bgcolor="#1a1f2e",
            plot_bgcolor="#1a1f2e",
            font_color="#c8d0e0",
            yaxis_title="元/坪",
            xaxis_title="年度",
            xaxis=dict(tickvals=years, ticktext=[str(y) for y in years]),
            height=360,
            margin=dict(t=20, b=20, l=80, r=120),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
        )
        st.plotly_chart(fig2, use_container_width=True)
        st.caption("灰金色塊 = 合理估值區間（±5%）｜虛線 = 本件估值｜點線 = 建商開價")

        # ── 三法長條比較
        st.markdown("#### 📊 三法與開價比較")
        fig = go.Figure()
        methods = ["市場比較法", "成本法", "收益法", "加權估值", "建商開價"]
        prices = [
            r1["total_price"] / 10000,
            r2["total_price"] / 10000,
            r3["total_price"] / 10000,
            weighted["total_price"] / 10000,
            asking_total,
        ]
        bar_colors = ["#5b8cff", "#5b8cff", "#5b8cff", "#c8a96e",
                      "#2ecc71" if color == "green" else ("#f39c12" if color == "orange" else "#e74c3c")]
        fig.add_trace(go.Bar(
            x=methods, y=prices,
            marker_color=bar_colors,
            text=[f"{p:,.0f}萬" for p in prices],
            textposition="outside",
        ))
        fig.update_layout(
            paper_bgcolor="#1a1f2e",
            plot_bgcolor="#1a1f2e",
            font_color="#c8d0e0",
            yaxis_title="萬元",
            showlegend=False,
            height=300,
            margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── 頁尾
    st.divider()
    st.caption("⚠️ 本系統為輔助評估工具，估算結果僅供參考，不構成投資建議。資料來源：內建2024Q4市場基準值。")


if __name__ == "__main__":
    main()
