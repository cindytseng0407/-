"""
桃園 AVM 系統 — 實價登錄資料前處理腳本
======================================
執行方式：
  python3 preprocess.py

輸入：
  實價登錄資料夾（Q1~Q4），每季包含：
    H_lvr_land_A.csv      → 主建物交易（main）
    H_lvr_land_A_land.csv → 土地交易（land）

輸出：
  market_data_result.txt  → 計算結果，直接貼回 app.py
"""

import os
import glob
import pandas as pd
import numpy as np
import json
from pathlib import Path

# ══════════════════════════════════════════════
# 設定：修改這裡的路徑
# ══════════════════════════════════════════════

DATA_ROOT = os.path.expanduser(
    "~/Library/CloudStorage/OneDrive-個人/"
    "03_進修與學習/EMBA-長庚/金融科技與投資/期末報告/實價登錄"
)

# 115年桃園公告地價TXT路徑（目前只有中壢所）
# 格式：縣市,行政區,地段,地號,公告地價,公告現值
LAND_ANNOUNCED_PATH = os.path.expanduser(
    "~/Library/CloudStorage/OneDrive-個人/"
    "03_進修與學習/EMBA-長庚/金融科技與投資/期末報告/"
    "115年桃園公告地價/115-中壢所.txt"
)

# 季度資料夾名稱
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]

# 商圈關鍵字對應（地址關鍵字 → 商圈名稱）
DISTRICT_MAPPING_ZHONGLI = {
    "【中壢】體育園區重劃區（青埔）": [
        "青埔", "高鐵", "環北", "領航", "文化三路", "文化四路",
        "文化五路", "文化六路", "青河", "青溪"
    ],
    "【中壢】中壢核心商圈": [
        "中壢區中正", "中壢區元化", "中壢區新生", "中壢區中山",
        "中壢區環西", "中壢區延平", "中壢區忠孝", "中壢區中華"
    ],
    "【中壢】中原大學商圈": [
        "中原", "實踐", "中北", "新仁", "莊敬", "普義"
    ],
    "【中壢】龍岡商圈": [
        "龍岡", "龍東", "龍南", "龍北", "忠貞", "自強"
    ],
    "【中壢】內壢工業區周邊": [
        "內壢", "中園", "工業區", "中華路二段", "環中"
    ],
}

DISTRICT_MAPPING_GUISHAN = {
    "【龜山】A7重劃區（體育大學生活圈）": [
        "文化一路", "文青", "樂善", "文桃", "文信", "南林",
        "體育大學", "牛角坡", "壽山路"
    ],
    "【龜山】長庚醫院商圈（A8周邊）": [
        "長庚", "文化三路", "文化四路", "復興三路", "龜山區復興"
    ],
    "【龜山】華亞科技園區周邊": [
        "華亞", "文德路", "文明路", "幸福", "樂善二路"
    ],
    "【龜山】迴龍捷運站周邊": [
        "迴龍", "萬壽路", "集賢路", "民族路", "三民路"
    ],
    "【龜山】龜山舊市區": [
        "龜山路", "中正路", "中山路", "公西", "大同路", "茶專路",
        "湖山", "銘傳", "文化二路"
    ],
}

ALL_DISTRICT_MAPPING = {**DISTRICT_MAPPING_ZHONGLI, **DISTRICT_MAPPING_GUISHAN}

# 目標行政區
TARGET_DISTRICTS = ["中壢區", "龜山區"]

# ══════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════

def find_csv_files(root: str, quarters: list, suffix: str) -> list:
    """找出所有季度資料夾中符合 suffix 的 CSV 檔案"""
    files = []
    for q in quarters:
        pattern = os.path.join(root, q, f"*{suffix}*.csv")
        matched = glob.glob(pattern)
        # 排除 schema、manifest
        matched = [f for f in matched if "schema" not in f.lower() and "manifest" not in f.lower()]
        files.extend(matched)
    if not files:
        # 也試試直接在 root 底下找
        pattern = os.path.join(root, f"*{suffix}*.csv")
        matched = glob.glob(pattern)
        matched = [f for f in matched if "schema" not in f.lower() and "manifest" not in f.lower()]
        files.extend(matched)
    return files


def load_and_concat(files: list, encoding_list=["utf-8-sig", "big5", "cp950"]) -> pd.DataFrame:
    """讀取並合併多個 CSV，自動嘗試編碼"""
    dfs = []
    for f in files:
        for enc in encoding_list:
            try:
                df = pd.read_csv(f, encoding=enc, low_memory=False)
                dfs.append(df)
                break
            except Exception:
                continue
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def assign_district(address: str) -> str:
    """根據地址關鍵字分配商圈"""
    if not isinstance(address, str):
        return "其他"
    for district_name, keywords in ALL_DISTRICT_MAPPING.items():
        for kw in keywords:
            if kw in address:
                return district_name
    return "其他"


def remove_outliers_zscore(series: pd.Series, threshold: float = 2.0) -> pd.Series:
    """Z-score 去離群值"""
    if len(series) < 5:
        return series
    mean = series.mean()
    std = series.std()
    if std == 0:
        return series
    return series[abs(series - mean) <= threshold * std]


def sqm_to_ping(sqm: float) -> float:
    return sqm / 3.3058

# ══════════════════════════════════════════════
# Step 1：讀取建物交易（main），計算市場均價 + 車位行情
# ══════════════════════════════════════════════

def process_main(files: list) -> tuple:
    """
    回傳：
      district_price: dict {商圈: 單價元/坪}
      district_parking: dict {商圈: {車位類別: 中位數}}
    """
    print(f"\n[Step 1] 讀取建物交易 CSV，共 {len(files)} 個檔案...")
    df = load_and_concat(files)
    if df.empty:
        print("  ❌ 無法讀取任何建物交易資料")
        return {}, {}

    print(f"  原始筆數：{len(df):,}")

    # 篩選行政區
    if "鄉鎮市區" in df.columns:
        df = df[df["鄉鎮市區"].isin(TARGET_DISTRICTS)].copy()
    print(f"  篩選桃園兩區後：{len(df):,} 筆")

    # 篩選住宅用途
    if "主要用途" in df.columns:
        df = df[df["主要用途"].str.contains("住家", na=False)].copy()

    # 篩選電梯大樓/華廈
    if "建物型態" in df.columns:
        df = df[df["建物型態"].str.contains("大樓|華廈", na=False)].copy()
    print(f"  篩選電梯大樓/華廈後：{len(df):,} 筆")

    # 轉換數值
    for col in ["總價元", "建物移轉總面積平方公尺", "車位總價元", "車位移轉總面積平方公尺"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── 車位扣除（還原主建物真實單價）
    if "車位總價元" in df.columns and "車位移轉總面積平方公尺" in df.columns:
        has_parking = (
            df["車位總價元"].notna() & (df["車位總價元"] > 0) &
            df["車位移轉總面積平方公尺"].notna() & (df["車位移轉總面積平方公尺"] > 0)
        )
        n_with_parking = has_parking.sum()
        print(f"  有車位資料筆數：{n_with_parking:,}")

        # 扣除車位
        df.loc[has_parking, "總價元"] = (
            df.loc[has_parking, "總價元"] - df.loc[has_parking, "車位總價元"]
        )
        df.loc[has_parking, "建物移轉總面積平方公尺"] = (
            df.loc[has_parking, "建物移轉總面積平方公尺"] -
            df.loc[has_parking, "車位移轉總面積平方公尺"]
        )

        # ── 車位行情：各商圈各類型中位數
        parking_df = df[has_parking].copy()
        parking_df["商圈"] = parking_df["土地位置建物門牌"].apply(assign_district)
        parking_df = parking_df[parking_df["商圈"] != "其他"]

        district_parking = {}
        if "車位類別" in parking_df.columns:
            for dist in parking_df["商圈"].unique():
                sub = parking_df[parking_df["商圈"] == dist]
                type_median = {}
                for ptype in sub["車位類別"].dropna().unique():
                    prices = sub[sub["車位類別"] == ptype]["車位總價元"].dropna()
                    prices = prices[(prices > 100_000) & (prices < 5_000_000)]
                    if len(prices) >= 3:
                        type_median[str(ptype)] = int(prices.median())
                if type_median:
                    district_parking[dist] = type_median
    else:
        print("  ⚠️  找不到車位欄位，跳過車位扣除")
        district_parking = {}

    # ── 重算單價（車位扣除後重算，否則直接用原始欄位）
    df["單價元平方公尺"] = pd.to_numeric(df.get("單價元平方公尺", np.nan), errors="coerce")

    # 有車位扣除的筆數，用扣除後重算；其他筆數直接用原始單價
    valid_area = df["建物移轉總面積平方公尺"].notna() & (df["建物移轉總面積平方公尺"] > 3)
    valid_price = df["總價元"].notna() & (df["總價元"] > 0)

    # 初始化校正欄位為原始單價
    df["單價元平方公尺_校正"] = df["單價元平方公尺"]

    # 有車位者用重算值取代
    if "車位總價元" in df.columns:
        has_parking_mask = (
            df["車位總價元"].notna() & (df["車位總價元"] > 0) & valid_area & valid_price
        )
        df.loc[has_parking_mask, "單價元平方公尺_校正"] = (
            df.loc[has_parking_mask, "總價元"] /
            df.loc[has_parking_mask, "建物移轉總面積平方公尺"]
        )
        print(f"  重算車位扣除後單價：{has_parking_mask.sum():,} 筆")

    # 指派商圈
    addr_col = "土地位置建物門牌" if "土地位置建物門牌" in df.columns else df.columns[2]
    df["商圈"] = df[addr_col].apply(assign_district)
    df_valid = df[df["商圈"] != "其他"].copy()
    print(f"  成功分配商圈筆數：{len(df_valid):,}")

    # ── 各商圈均價
    district_price = {}
    for dist in ALL_DISTRICT_MAPPING.keys():
        sub = df_valid[df_valid["商圈"] == dist]["單價元平方公尺_校正"].dropna()
        # 合理範圍：10,000~1,500,000 元/平方公尺（對應約3~50萬/坪）
        sub = sub[(sub > 10_000) & (sub < 1_500_000)]
        sub = remove_outliers_zscore(sub)
        if len(sub) >= 5:
            median_sqm = sub.median()
            median_ping = sqm_to_ping(median_sqm)
            district_price[dist] = {
                "unit_price_ping": int(round(median_ping / 1000) * 1000),
                "n": len(sub),
            }
            print(f"  {dist}: {median_ping:,.0f} 元/坪 (n={len(sub)})")
        else:
            print(f"  {dist}: ⚠️  樣本不足 ({len(sub)} 筆)，保留內建值")

    return district_price, district_parking


# ══════════════════════════════════════════════
# Step 2：計算地價修正係數
# 方法：從 main.csv 取純土地交易算市場地價，
#       同時輸出公告地價備用值與修正係數供比較
# ══════════════════════════════════════════════

# 公告地價備用值（元/㎡，來自115年桃園公告地價）
FALLBACK_LAND_PRICE = {
    "【中壢】體育園區重劃區（青埔）": 243000,
    "【中壢】中壢核心商圈":           201000,
    "【中壢】中原大學商圈":           166000,
    "【中壢】龍岡商圈":               127000,
    "【中壢】內壢工業區周邊":          87000,
    "【龜山】A7重劃區（體育大學生活圈）": 185000,
    "【龜山】長庚醫院商圈（A8周邊）":  220000,
    "【龜山】華亞科技園區周邊":        175000,
    "【龜山】迴龍捷運站周邊":          210000,
    "【龜山】龜山舊市區":              130000,
}

def process_land(announced_path: str) -> dict:
    """
    讀取115年桃園公告現值TXT
    格式：縣市,行政區,地段,地號,公告地價,公告現值
    採用第6欄公告現值作為成本法地價基準（較公告地價更接近市場行情）
    支援讀取同一資料夾下所有TXT並合併（中壢所 + 龜山所等）
    """
    print(f"\n[Step 2] 讀取115年公告現值...")

    # 找到資料夾，讀取所有TXT檔案
    base_dir = os.path.dirname(announced_path)
    if not os.path.isdir(base_dir):
        base_dir = os.path.dirname(os.path.dirname(announced_path))

    all_txts = []
    if os.path.isdir(base_dir):
        for f in os.listdir(base_dir):
            if f.endswith(".txt") or f.endswith(".csv"):
                if "schema" not in f.lower() and "manifest" not in f.lower():
                    all_txts.append(os.path.join(base_dir, f))

    if not all_txts:
        # 退回單檔模式
        if os.path.exists(announced_path):
            all_txts = [announced_path]
        else:
            print(f"  ⚠️  找不到公告現值TXT，使用內建備用值")
            return {}

    print(f"  找到 {len(all_txts)} 個TXT檔案：{[os.path.basename(f) for f in all_txts]}")

    dfs = []
    for txt_path in all_txts:
        for enc in ["utf-8-sig", "big5", "cp950"]:
            try:
                df = pd.read_csv(
                    txt_path, header=None,
                    names=["縣市", "行政區", "地段", "地號", "公告地價", "公告現值"],
                    encoding=enc
                )
                dfs.append(df)
                break
            except Exception:
                continue

    if not dfs:
        print(f"  ❌ 無法讀取任何TXT檔案")
        return {}

    df = pd.concat(dfs, ignore_index=True)
    df["公告現值"] = pd.to_numeric(df["公告現值"], errors="coerce")
    df = df.dropna(subset=["公告現值"])
    print(f"  公告現值資料合計：{len(df):,} 筆")

    # 商圈對應：用行政區+地段關鍵字
    # 以下關鍵字對應法定地段名稱（來自115-中壢所.txt實際資料）
    LAND_SEGMENT_MAP = {
        # 青埔重劃區：青埔段、過嶺段、三座屋段（舊社小段）
        "【中壢】體育園區重劃區（青埔）": [
            "青埔段", "過嶺段", "三座屋段舊社", "三座屋段三座屋"
        ],
        # 中壢核心商圈：市中心傳統地段
        "【中壢】中壢核心商圈": [
            "中壢埔頂段", "石頭段", "中寮段", "中興段", "仁和段",
            "仁德段", "仁愛段", "仁祥段", "仁美段", "五權段",
            "啟文段", "富台段", "富強段", "山上段", "山下段",
            "三民段", "中工段", "中運段", "六和段", "大路段",
            "大江段", "大享段", "前寮段", "中北段"
        ],
        # 中原大學商圈
        "【中壢】中原大學商圈": [
            "中原段", "大崙段", "培英段", "健行段", "上嶺段",
            "普義段", "內厝段"
        ],
        # 龍岡商圈
        "【中壢】龍岡商圈": [
            "龍岡段", "忠貞段", "自強段", "后寮段",
            "後寮段", "大華段"
        ],
        # 內壢工業區周邊
        "【中壢】內壢工業區周邊": [
            "內壢段", "水尾段", "興南段"
        ],
    }

    def assign_land_seg(row):
        seg = str(row.get("地段", ""))
        for dist, kws in LAND_SEGMENT_MAP.items():
            if any(kw in seg for kw in kws):
                return dist
        return "其他"

    df["商圈"] = df.apply(assign_land_seg, axis=1)
    df_valid = df[df["商圈"] != "其他"]
    print(f"  成功分配商圈筆數：{len(df_valid):,}")

    result = {}
    for dist in ALL_DISTRICT_MAPPING.keys():
        sub = df_valid[df_valid["商圈"] == dist]["公告現值"]
        sub = sub[(sub > 1_000) & (sub < 5_000_000)]
        if len(sub) >= 3:
            median_val = int(round(sub.median() / 1000) * 1000)
            result[dist] = median_val
            print(f"  {dist}: {median_val:,} 元/㎡ (n={len(sub)})")
        else:
            print(f"  {dist}: ⚠️  樣本不足，保留內建值")

    return result



# ══════════════════════════════════════════════
# Step 3：輸出結果
# ══════════════════════════════════════════════

# 內建備用值（當實價登錄樣本不足時使用）
FALLBACK_VALUES = {
    "【中壢】體育園區重劃區（青埔）": {
        "unit_price_ping": 420000, "land_price_sqm": 243000,
        "far": 2.25, "monthly_rent_ping": 950, "cap_rate": 0.024,
        "description": "青埔高鐵特區，機捷環北站，桃園最熱重劃區", "region": "中壢區",
    },
    "【中壢】中壢核心商圈": {
        "unit_price_ping": 310000, "land_price_sqm": 201000,
        "far": 3.60, "monthly_rent_ping": 720, "cap_rate": 0.025,
        "description": "中壢火車站周邊，生活機能完善，都更潛力", "region": "中壢區",
    },
    "【中壢】中原大學商圈": {
        "unit_price_ping": 270000, "land_price_sqm": 166000,
        "far": 1.60, "monthly_rent_ping": 670, "cap_rate": 0.025,
        "description": "學區房，租賃需求穩定，自住首購首選", "region": "中壢區",
    },
    "【中壢】龍岡商圈": {
        "unit_price_ping": 240000, "land_price_sqm": 127000,
        "far": 1.60, "monthly_rent_ping": 600, "cap_rate": 0.025,
        "description": "自住型社區，東南亞族裔聚集，性價比高", "region": "中壢區",
    },
    "【中壢】內壢工業區周邊": {
        "unit_price_ping": 210000, "land_price_sqm": 87000,
        "far": 1.60, "monthly_rent_ping": 540, "cap_rate": 0.026,
        "description": "工業區勞工剛需市場，總價親民", "region": "中壢區",
    },
    "【龜山】A7重劃區（體育大學生活圈）": {
        "unit_price_ping": 480000, "land_price_sqm": 185000,
        "far": 2.30, "monthly_rent_ping": 1050, "cap_rate": 0.023,
        "description": "機捷A7站，大林口生活圈，北台灣首購熱區", "region": "龜山區",
    },
    "【龜山】長庚醫院商圈（A8周邊）": {
        "unit_price_ping": 600000, "land_price_sqm": 220000,
        "far": 2.40, "monthly_rent_ping": 1300, "cap_rate": 0.023,
        "description": "機捷A8站，長庚醫院生活圈，環球百貨，機能成熟", "region": "龜山區",
    },
    "【龜山】華亞科技園區周邊": {
        "unit_price_ping": 470000, "land_price_sqm": 175000,
        "far": 2.25, "monthly_rent_ping": 1000, "cap_rate": 0.023,
        "description": "廣達、欣興等科技廠就業需求", "region": "龜山區",
    },
    "【龜山】迴龍捷運站周邊": {
        "unit_price_ping": 560000, "land_price_sqm": 210000,
        "far": 2.25, "monthly_rent_ping": 1200, "cap_rate": 0.023,
        "description": "雙北邊界，接近新莊價格帶", "region": "龜山區",
    },
    "【龜山】龜山舊市區": {
        "unit_price_ping": 320000, "land_price_sqm": 130000,
        "far": 1.60, "monthly_rent_ping": 720, "cap_rate": 0.025,
        "description": "傳統市區，銘傳大學周邊低基期", "region": "龜山區",
    },
}

# 各商圈車位備用行情（元/個）
FALLBACK_PARKING = {
    "【中壢】體育園區重劃區（青埔）": {"平面車位": 1_600_000, "坡道平面": 1_300_000, "機械車位": 800_000, "地下室平面（含管理）": 2_000_000},
    "【中壢】中壢核心商圈":           {"平面車位": 1_200_000, "坡道平面": 1_000_000, "機械車位": 600_000, "地下室平面（含管理）": 1_500_000},
    "【中壢】中原大學商圈":           {"平面車位": 1_100_000, "坡道平面": 900_000,   "機械車位": 550_000, "地下室平面（含管理）": 1_400_000},
    "【中壢】龍岡商圈":               {"平面車位": 1_000_000, "坡道平面": 800_000,   "機械車位": 500_000, "地下室平面（含管理）": 1_300_000},
    "【中壢】內壢工業區周邊":         {"平面車位": 900_000,   "坡道平面": 750_000,   "機械車位": 450_000, "地下室平面（含管理）": 1_100_000},
    "【龜山】A7重劃區（體育大學生活圈）": {"平面車位": 1_500_000, "坡道平面": 1_200_000, "機械車位": 700_000, "地下室平面（含管理）": 1_800_000},
    "【龜山】長庚醫院商圈（A8周邊）": {"平面車位": 2_000_000, "坡道平面": 1_600_000, "機械車位": 900_000, "地下室平面（含管理）": 2_500_000},
    "【龜山】華亞科技園區周邊":       {"平面車位": 1_400_000, "坡道平面": 1_100_000, "機械車位": 650_000, "地下室平面（含管理）": 1_700_000},
    "【龜山】迴龍捷運站周邊":         {"平面車位": 1_800_000, "坡道平面": 1_400_000, "機械車位": 800_000, "地下室平面（含管理）": 2_200_000},
    "【龜山】龜山舊市區":             {"平面車位": 1_000_000, "坡道平面": 800_000,   "機械車位": 500_000, "地下室平面（含管理）": 1_200_000},
}


def generate_output(district_price, district_land_announced, district_parking):
    """
    產生 Python 程式碼字串，可直接貼回 app.py
    district_land_announced: {商圈: 公告現值元/㎡}
    """
    lines = []
    lines.append("# ══════════════════════════════════════════════════════")
    lines.append("# preprocess.py 計算結果，貼回 app.py 取代對應區塊")
    lines.append("# 市場均價來源：2025全年實價登錄（已扣除車位）")
    lines.append("# 地價來源：115年桃園公告現值（各商圈中位數）")
    lines.append("# ══════════════════════════════════════════════════════")
    lines.append("")
    lines.append("DEFAULT_MARKET_PRICES = {")

    # 內建備用公告現值（若TXT讀取失敗）
    FALLBACK_ANNOUNCED = {
        "【中壢】體育園區重劃區（青埔）": 243000,
        "【中壢】中壢核心商圈":           201000,
        "【中壢】中原大學商圈":           166000,
        "【中壢】龍岡商圈":               127000,
        "【中壢】內壢工業區周邊":         87000,
        "【龜山】A7重劃區（體育大學生活圈）": 185000,
        "【龜山】長庚醫院商圈（A8周邊）": 220000,
        "【龜山】華亞科技園區周邊":       175000,
        "【龜山】迴龍捷運站周邊":         210000,
        "【龜山】龜山舊市區":             130000,
    }

    for dist, fallback in FALLBACK_VALUES.items():
        price = district_price.get(dist, {}).get("unit_price_ping", fallback["unit_price_ping"])
        price_src = "✅ 實價登錄計算" if dist in district_price else "⚠️  備用內建值"

        # 地價：優先用從TXT計算出的商圈公告現值中位數，否則用備用值
        if dist in district_land_announced:
            land = district_land_announced[dist]
            land_src = "✅ 115年公告現值（商圈中位數）"
        else:
            land = FALLBACK_ANNOUNCED.get(dist, fallback["land_price_sqm"])
            land_src = "⚠️  備用公告現值"

        lines.append(f'    "{dist}": {{')
        lines.append(f'        "unit_price_ping": {price},   # {price_src} ({price//10000:.1f}萬/坪)')
        lines.append(f'        "land_price_sqm": {land},   # {land_src} ({land:,} 元/㎡)')
        lines.append(f'        "far": {fallback["far"]},')
        lines.append(f'        "monthly_rent_ping": {fallback["monthly_rent_ping"]},')
        lines.append(f'        "cap_rate": {fallback["cap_rate"]},')
        lines.append(f'        "description": "{fallback["description"]}",')
        lines.append(f'        "region": "{fallback["region"]}",')
        lines.append(f'    }},')

    lines.append("}")
    lines.append("")
    lines.append("# 各商圈車位行情（元/個）")
    lines.append("PARKING_PRICE_BY_DISTRICT = {")
    for dist in FALLBACK_VALUES.keys():
        computed = district_parking.get(dist, {})
        fallback_p = FALLBACK_PARKING[dist]
        lines.append(f'    "{dist}": {{')
        for ptype in ["平面車位", "坡道平面", "機械車位", "地下室平面（含管理）"]:
            val = computed.get(ptype, fallback_p.get(ptype, 1_000_000))
            src = "✅" if ptype in computed else "⚠️"
            lines.append(f'        "{ptype}": {val:_},  # {src}')
        lines.append(f'    }},')
    lines.append("}")
    return "\n".join(lines)


def main():
    print("=" * 60)
    print("桃園 AVM 系統 — 實價登錄資料前處理")
    print("=" * 60)
    print(f"資料根目錄：{DATA_ROOT}")

    if not os.path.exists(DATA_ROOT):
        print(f"\n❌ 找不到資料夾：{DATA_ROOT}")
        print("請確認路徑是否正確，並修改腳本頂部的 DATA_ROOT 變數")
        return

    # 找主建物 CSV（不含 _land、_park、_build 的檔案）
    main_files = []
    land_files = []
    for q in QUARTERS:
        q_dir = os.path.join(DATA_ROOT, q)
        if not os.path.isdir(q_dir):
            continue
        for f in os.listdir(q_dir):
            f_lower = f.lower()
            if "schema" in f_lower or "manifest" in f_lower:
                continue
            full = os.path.join(q_dir, f)
            if f_lower.endswith(".csv"):
                # 精確比對結尾，避免 H_lvr_land_A.csv 被誤判為土地交易
                if f_lower.endswith("_land.csv"):
                    land_files.append(full)
                elif f_lower.endswith("_build.csv") or f_lower.endswith("_park.csv"):
                    pass  # 跳過
                else:
                    main_files.append(full)

    print(f"\n主建物 CSV：{len(main_files)} 個")
    print(f"土地交易 CSV：{len(land_files)} 個")

    district_price, district_parking = process_main(main_files)
    district_land_announced = process_land(LAND_ANNOUNCED_PATH)

    # 產生輸出
    result = generate_output(district_price, district_land_announced, district_parking)

    output_path = os.path.join(os.path.expanduser("~/Desktop/avm_system"), "market_data_result.txt")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result)

    print("\n" + "=" * 60)
    print(f"✅ 計算完成！結果已儲存到：")
    print(f"   {output_path}")
    print("=" * 60)
    print("\n下一步：")
    print("  1. 開啟 market_data_result.txt")
    print("  2. 把內容貼回 app.py，取代 DEFAULT_MARKET_PRICES 和 PARKING_PRICE_BY_DISTRICT")
    print("  3. 重新執行 streamlit run app.py")


if __name__ == "__main__":
    main()
