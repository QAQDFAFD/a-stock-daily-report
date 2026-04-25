import json
import os
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

BASE_DIR = os.path.dirname(__file__)
CACHE_DIR = os.path.join(BASE_DIR, "cache")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


def _cache_path(ds): return os.path.join(CACHE_DIR, f"{ds}.json")


def _read_cache(ds):
    p = _cache_path(ds)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _write_cache(ds, data):
    with open(_cache_path(ds), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)


def _si(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _sf(v):
    try:
        return round(float(v), 2)
    except (ValueError, TypeError):
        return 0.0


def _recs(df):
    if df is None or df.empty:
        return []
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].apply(lambda x: str(x) if not isinstance(x, (int, float, str, bool, type(None))) else x)
    return df.fillna("").to_dict(orient="records")


def _prev_trade_date(ds):
    d = datetime.strptime(ds, "%Y%m%d")
    for _ in range(10):
        d -= timedelta(days=1)
        if d.weekday() < 5:
            return d.strftime("%Y%m%d")
    return ""


def _retry_fetch(fn, retries=2, delay=2, **kwargs):
    for i in range(retries + 1):
        try:
            if i > 0:
                time.sleep(delay * i)
            return fn(**kwargs)
        except Exception:
            if i == retries:
                return None
    return None


# ========== fetch_report ==========

def fetch_report(date_str, force=False):
    cached = _read_cache(date_str)
    if cached and not force:
        return cached

    r = {"date": date_str, "error": None}
    prev_ds = _prev_trade_date(date_str)
    prev_report = _read_cache(prev_ds) if prev_ds else None
    if not prev_report and prev_ds:
        prev_report = fetch_report(prev_ds)

    try:
        zt_df = ak.stock_zt_pool_em(date=date_str)
        r["zt_pool"] = _recs(zt_df); r["zt_count"] = len(zt_df)
    except Exception:
        r["zt_pool"] = []; r["zt_count"] = 0

    try:
        dt_df = ak.stock_zt_pool_dtgc_em(date=date_str)
        r["dt_pool"] = _recs(dt_df); r["dt_count"] = len(dt_df)
    except Exception:
        r["dt_pool"] = []; r["dt_count"] = 0

    try:
        zb_df = ak.stock_zt_pool_zbgc_em(date=date_str)
        r["zb_pool"] = _recs(zb_df); r["zb_count"] = len(zb_df)
    except Exception:
        r["zb_pool"] = []; r["zb_count"] = 0

    try:
        prev_df = ak.stock_zt_pool_previous_em(date=date_str)
        r["previous_zt_pool"] = _recs(prev_df)
    except Exception:
        r["previous_zt_pool"] = []

    try:
        strong_df = ak.stock_zt_pool_strong_em(date=date_str)
        r["strong_pool"] = _recs(strong_df)
    except Exception:
        r["strong_pool"] = []

    # 上涨/下跌家数（此API仅返回当日实时数据，非历史）
    time.sleep(1)
    today_str = datetime.now().strftime("%Y%m%d")
    try:
        act_df = ak.stock_market_activity_legu()
        act_list = _recs(act_df)
        r["market_activity"] = act_list
        act_map = {x["item"]: x["value"] for x in act_list}
        r["up_count"] = _si(act_map.get("上涨", 0))
        r["down_count"] = _si(act_map.get("下跌", 0))
        r["up_down_realtime"] = (date_str == today_str)
    except Exception:
        r["market_activity"] = []; r["up_count"] = 0; r["down_count"] = 0
        r["up_down_realtime"] = False

    try:
        hsgt_df = ak.stock_hsgt_fund_flow_summary_em()
        if hsgt_df is not None and not hsgt_df.empty:
            fmt_d = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            north = hsgt_df[(hsgt_df["交易日"].astype(str) == fmt_d) & (hsgt_df["资金方向"] == "北向")]
            r["north_flow"] = round(sum(_sf(x.get("成交净买额", 0)) for _, x in north.iterrows()), 2) if not north.empty else None
        else:
            r["north_flow"] = None
    except Exception:
        r["north_flow"] = None

    zt_count = r["zt_count"]; zb_count = r["zb_count"]
    zb_rate = round(zb_count / (zt_count + zb_count) * 100, 2) if (zt_count + zb_count) > 0 else 0
    r["zb_rate"] = zb_rate

    all_zt = []
    for item in r["zt_pool"]:
        lb = _si(item.get("连板数", item.get("连板天数", 0)))
        if lb < 1: lb = 1
        all_zt.append({
            "代码": item.get("代码", ""), "名称": item.get("名称", ""),
            "连板数": lb, "最新价": item.get("最新价", ""),
            "涨跌幅": item.get("涨跌幅", ""), "成交额": item.get("成交额", ""),
            "封板资金": item.get("封板资金", ""), "换手率": item.get("换手率", ""),
            "首次封板时间": item.get("首次封板时间", ""),
            "最后封板时间": item.get("最后封板时间", ""),
            "炸板次数": item.get("炸板次数", ""),
            "所属行业": item.get("所属行业", ""),
            "流通市值": item.get("流通市值", ""),
        })
    all_zt.sort(key=lambda x: x["连板数"], reverse=True)

    lianban_list = [x for x in all_zt if x["连板数"] >= 2]
    shouban_list = [x for x in all_zt if x["连板数"] == 1]
    r["lianban"] = lianban_list; r["shouban"] = shouban_list
    r["lianban_count"] = len(lianban_list); r["shouban_count"] = len(shouban_list)
    max_lb = max((x["连板数"] for x in lianban_list), default=0)
    r["max_lianban"] = max_lb

    tiers_raw = defaultdict(list)
    for item in all_zt:
        tiers_raw[item["连板数"]].append(item)
    tiers_complete = {}
    top = max_lb if max_lb >= 1 else (1 if shouban_list else 0)
    for n in range(top, 0, -1):
        tiers_complete[str(n)] = tiers_raw.get(n, [])
    r["lianban_tiers"] = tiers_complete

    prev_zt_analysis = None
    if r.get("previous_zt_pool"):
        pool = r["previous_zt_pool"]
        up_c = sum(1 for i in pool if _sf(i.get("涨跌幅", 0)) > 0)
        dn_c = sum(1 for i in pool if _sf(i.get("涨跌幅", 0)) < 0)
        zt_again = sum(1 for i in pool if _sf(i.get("涨跌幅", 0)) >= 9.5)
        avg = round(sum(_sf(i.get("涨跌幅", 0)) for i in pool) / len(pool), 2)
        promo = round(zt_again / len(pool) * 100, 1) if pool else 0
        prev_zt_analysis = {"total": len(pool), "up_count": up_c, "down_count": dn_c,
            "flat_count": len(pool) - up_c - dn_c, "zt_again": zt_again,
            "premium_rate": avg, "promotion_rate": promo}
    r["prev_zt_analysis"] = prev_zt_analysis
    r["promotion_count"] = prev_zt_analysis["zt_again"] if prev_zt_analysis else 0

    theme_map = defaultdict(list)
    for item in r["zt_pool"]:
        ind = item.get("所属行业", "") or "其他"
        lb = _si(item.get("连板数", item.get("连板天数", 0)))
        theme_map[ind].append({"代码": item.get("代码", ""), "名称": item.get("名称", ""),
            "连板数": lb if lb >= 1 else 1, "首次封板时间": item.get("首次封板时间", ""), "所属行业": ind})
    for v in theme_map.values():
        v.sort(key=lambda x: x["连板数"], reverse=True)
    r["zt_themes"] = [{"theme": k, "stocks": v, "count": len(v)} for k, v in sorted(theme_map.items(), key=lambda x: len(x[1]), reverse=True)]

    industry_dist = {}
    for item in r["zt_pool"]:
        ind = item.get("所属行业", "未知") or "未知"
        industry_dist[ind] = industry_dist.get(ind, 0) + 1
    r["zt_industry_dist"] = [{"行业": k, "涨停家数": v} for k, v in sorted(industry_dist.items(), key=lambda x: x[1], reverse=True)]

    if prev_report:
        r["yesterday"] = {k: prev_report.get(k, "?") for k in
            ["zt_count","dt_count","zb_count","zb_rate","lianban_count","shouban_count","up_count","down_count","max_lianban","north_flow"]}
        r["yesterday_lianban_tiers"] = prev_report.get("lianban_tiers", {})
    else:
        r["yesterday"] = None; r["yesterday_lianban_tiers"] = {}

    r["tier_analysis"] = analyze_tiers(r)
    r["sentiment"] = judge_sentiment(r)

    board_df = _retry_fetch(ak.stock_board_industry_name_em, retries=2, delay=3)
    if board_df is not None and not board_df.empty:
        board_df = board_df.sort_values("涨跌幅", ascending=False)
        r["board_top"] = _recs(board_df.head(10))
        r["board_bottom"] = _recs(board_df.tail(10).sort_values("涨跌幅"))
    else:
        r["board_top"] = []; r["board_bottom"] = []

    time.sleep(2)
    concept_df = _retry_fetch(ak.stock_board_concept_name_em, retries=2, delay=3)
    if concept_df is not None and not concept_df.empty:
        concept_df = concept_df.sort_values("涨跌幅", ascending=False)
        r["concept_top"] = _recs(concept_df.head(10))
        r["concept_bottom"] = _recs(concept_df.tail(10).sort_values("涨跌幅"))
    else:
        r["concept_top"] = []; r["concept_bottom"] = []

    r["board_rotation"] = analyze_board_rotation(r, prev_report)
    r["strong_boards"] = build_strong_boards(r)

    try:
        news_df = ak.stock_info_global_cls()
        raw_news = _recs(news_df.head(20)) if news_df is not None and not news_df.empty else []
    except Exception:
        raw_news = []
    r["news"] = analyze_news(raw_news, r)

    r["ai_analysis"] = None
    if DEEPSEEK_API_KEY:
        try:
            r["ai_analysis"] = call_deepseek_analysis(r)
        except Exception as e:
            r["ai_analysis"] = f"AI分析调用失败: {str(e)}"

    # 19. 板块趋势（多周期）+ AI趋势分析
    r["trend_industry"] = []
    r["trend_concept"] = []
    r["trend_ai"] = None
    try:
        trend = fetch_board_trend(date_str)
        r["trend_industry"] = trend.get("industry", [])
        r["trend_concept"] = trend.get("concept", [])
        if DEEPSEEK_API_KEY:
            try:
                r["trend_ai"] = call_trend_ai(trend, r)
            except Exception as e:
                r["trend_ai"] = f"趋势AI分析失败: {str(e)}"
    except Exception as e:
        r["trend_ai"] = f"趋势数据拉取失败: {str(e)}"

    _write_cache(date_str, r)
    return r


# ========== Analysis ==========

def judge_sentiment(r):
    zt = r["zt_count"]; dt = r["dt_count"]; zb_rate = r["zb_rate"]
    max_lb = r["max_lianban"]; lb_count = r["lianban_count"]
    pa = r.get("prev_zt_analysis")
    score = 0; reasons = []

    if zt >= 80: score += 3; reasons.append(f"涨停 {zt} 家，多头极强")
    elif zt >= 40: score += 2; reasons.append(f"涨停 {zt} 家，多头偏强")
    elif zt >= 15: score += 1; reasons.append(f"涨停 {zt} 家，市场一般")
    else: score -= 1; reasons.append(f"涨停仅 {zt} 家，市场冷清")

    if dt >= 50: score -= 3; reasons.append(f"跌停 {dt} 家，恐慌蔓延")
    elif dt >= 20: score -= 2; reasons.append(f"跌停 {dt} 家，空头施压")
    elif dt >= 5: score -= 1; reasons.append(f"跌停 {dt} 家，空头偏弱")
    else: score += 1; reasons.append(f"跌停仅 {dt} 家，市场平稳")

    if zb_rate >= 50: score -= 2; reasons.append(f"炸板率 {zb_rate}%，封板意愿极差")
    elif zb_rate >= 30: score -= 1; reasons.append(f"炸板率 {zb_rate}%，封板意愿一般")
    else: score += 1; reasons.append(f"炸板率 {zb_rate}%，封板意愿强")

    if max_lb >= 7: score += 3; reasons.append(f"最高 {max_lb} 板，赚钱效应极强")
    elif max_lb >= 5: score += 2; reasons.append(f"最高 {max_lb} 板，赚钱效应显著")
    elif max_lb >= 3: score += 1; reasons.append(f"最高 {max_lb} 板，接力氛围尚可")
    else: reasons.append(f"最高仅 {max_lb} 板，高度受限")

    if lb_count >= 10: score += 1; reasons.append(f"连板 {lb_count} 只，梯队完整")

    promotion_rate = pa.get("promotion_rate", 0) if pa else 0
    if promotion_rate >= 30: score += 1; reasons.append(f"晋级率 {promotion_rate}%，接力强")
    elif promotion_rate > 0: reasons.append(f"晋级率 {promotion_rate}%")

    if pa:
        pr = pa["premium_rate"]
        if pr >= 3: score += 1; reasons.append(f"昨涨停溢价 +{pr}%，盈利效应好")
        elif pr <= -2: score -= 1; reasons.append(f"昨涨停溢价 {pr}%，亏钱效应")

    high_board_feedback = ""
    if max_lb >= 3 and r["lianban"]:
        leader = r["lianban"][0]
        zb_times = _si(leader.get("炸板次数", 0))
        if zb_times == 0:
            high_board_feedback = f"{leader['名称']}{max_lb}板一封到底，辨识度高"; score += 1
        else:
            high_board_feedback = f"{leader['名称']}{max_lb}板炸{zb_times}次，分歧较大"

    if score >= 6: level="极度亢奋";color="#e74c3c";cycle="亢奋期（高潮）";tmr="注意过热回调风险，高位股可能分歧"
    elif score >= 4: level="偏多乐观";color="#2ecc71";cycle="上升期";tmr="情绪延续概率大，可积极参与主线"
    elif score >= 2: level="中性偏暖";color="#f39c12";cycle="修复期";tmr="市场有所修复，关注主线能否持续"
    elif score >= 0: level="中性偏冷";color="#95a5a6";cycle="震荡期";tmr="情绪一般，建议观望或轻仓试错"
    elif score >= -2: level="偏空谨慎";color="#3498db";cycle="退潮期";tmr="亏钱效应蔓延，建议减仓防守"
    else: level="极度恐慌";color="#8e44ad";cycle="冰点期";tmr="冰点往往孕育转机，关注超跌反弹龙头"

    return {"score": score, "level": level, "color": color, "cycle": cycle, "tomorrow_prediction": tmr,
        "reasons": reasons, "emotion_metrics": {
            "最高板高度": max_lb, "连板晋级率": f"{promotion_rate}%",
            "昨日涨停溢价": f"{pa['premium_rate']}%" if pa else "-",
            "跌停家数": dt, "炸板率": f"{zb_rate}%", "高标反馈": high_board_feedback or "-"}}


def analyze_tiers(r):
    max_lb = r["max_lianban"]; lianban = r.get("lianban", [])
    tiers = r.get("lianban_tiers", {})
    if max_lb < 2:
        return {"complete": False, "desc": "当日无连板股，梯队缺失", "max_recognition": "-",
                "gap_position": "-", "core_leader": "-", "leader_tomorrow": "-"}
    tier_keys = sorted([int(k) for k in tiers if int(k) >= 2], reverse=True)
    has_gap = False; gap_pos = "-"
    for i in range(len(tier_keys) - 1):
        if tier_keys[i] - tier_keys[i+1] > 1:
            has_gap = True; gap_pos = f"{tier_keys[i]}板→{tier_keys[i+1]}板断层"; break
    complete = not has_gap and len(tier_keys) >= 2
    leader = lianban[0] if lianban else None
    ln = f"{leader['名称']}({leader['代码']})" if leader else "-"
    lr = "高" if leader and max_lb >= 4 else "中" if leader else "低"
    if leader and max_lb >= 5: lt = f"高位博弈，关注{max_lb+1}板能否晋级"
    elif leader and max_lb >= 3: lt = f"中位加速，{leader['名称']}打出空间是关键"
    elif leader: lt = "低位试错，关注封板质量"
    else: lt = "-"
    return {"complete": complete, "desc": "梯队完整" if complete else ("存在断层" if has_gap else "梯队偏薄"),
            "max_recognition": lr, "gap_position": gap_pos, "core_leader": ln, "leader_tomorrow": lt}


def analyze_news(raw_news, report):
    board_names = {b.get("板块名称","") for b in report.get("board_top",[]) + report.get("concept_top",[]) if b.get("板块名称")}
    industries = {item.get("所属行业","") for item in report.get("zt_pool",[]) if item.get("所属行业")}
    KW = {"石油":["石油","能源","中石油","中石化"],"军工":["军工","国防","军事","导弹"],
        "半导体":["芯片","半导体","光刻","晶圆"],"新能源":["锂电","光伏","储能","新能源","风电"],
        "AI/科技":["AI","人工智能","算力","大模型","机器人","数据中心"],"医药":["医药","生物","疫苗","创新药","医疗"],
        "地产":["房地产","地产","楼市","住房"],"金融":["银行","券商","保险","降息","降准"],
        "汽车":["汽车","新能源车","智驾","特斯拉"],"消费":["白酒","消费","免税","旅游"],
        "基建":["基建","水利","铁路","建材"],"农业":["农业","粮食","种业","猪肉"]}
    result = []
    for n in raw_news:
        title = n.get("标题","") or ""; content = n.get("内容","") or ""; text = title + content
        affected = []
        for sector, kws in KW.items():
            if any(kw in text for kw in kws): affected.append(sector)
        for bname in board_names:
            if bname in text and bname not in affected: affected.append(bname)
        for ind in industries:
            if ind in text and ind not in affected: affected.append(ind)
        hint = "可能影响：" + "、".join(affected[:4]) if affected else ""
        result.append({"标题": title, "内容": content, "发布时间": n.get("发布时间", n.get("发布日期","")),
            "affected_sectors": affected[:4], "impact_hint": hint})
    return result


def analyze_board_rotation(r, prev_report):
    result = {"relation":"","yesterday_strong_today":"","new_boards":"","retreat_warning":""}
    bt = r.get("board_top",[])
    if not bt: result["relation"]="板块数据未获取到"; return result
    top_n = [b.get("板块名称","") for b in bt[:5]]
    bot_n = [b.get("板块名称","") for b in r.get("board_bottom",[])[:5]]
    if prev_report:
        pt = [b.get("板块名称","") for b in prev_report.get("board_top",[])[:5]]
        ov = set(top_n) & set(pt)
        if len(ov)>=3: result["relation"]=f"共振延续（{', '.join(ov)}）"
        elif len(ov)>=1: result["relation"]=f"部分轮动（延续{', '.join(ov)}）"
        else: result["relation"]="全面轮动"
        ss=[n for n in pt if n in top_n]; ret=[n for n in pt if n in bot_n]
        result["yesterday_strong_today"]=(f"延续:{', '.join(ss)}" if ss else "均未延续")+(f"；退潮:{', '.join(ret)}" if ret else "")
        result["new_boards"]=", ".join([n for n in top_n if n not in pt]) or "无"
        result["retreat_warning"]=", ".join(ret)+" 注意退潮" if ret else "暂无"
    else:
        result["relation"]="无昨日数据"; result["new_boards"]=", ".join(top_n[:3]) or "-"
    return result


def build_strong_boards(r):
    zd = {d["行业"]: d["涨停家数"] for d in r.get("zt_industry_dist",[])}
    bt = r.get("board_top",[]); boards=[]; seen=set()
    for b in bt[:10]:
        name=b.get("板块名称","")
        if not name or name in seen: continue
        seen.add(name)
        boards.append({"排名":len(boards)+1,"板块":name,"涨停家数":zd.get(name,0),"龙头个股":b.get("领涨股票",""),"涨跌幅":b.get("涨跌幅","")})
        if len(boards)>=5: break
    if not boards and zd:
        for ind,cnt in sorted(zd.items(),key=lambda x:x[1],reverse=True)[:5]:
            boards.append({"排名":len(boards)+1,"板块":ind,"涨停家数":cnt,"龙头个股":"","涨跌幅":""})
    return boards


# ========== DeepSeek AI ==========

def call_deepseek_analysis(report):
    try:
        from openai import OpenAI
    except ImportError:
        return "需要安装 openai 库: pip install openai"
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": """你是一位资深A股短线交易分析师。请基于数据用Markdown输出复盘分析：

## 一、今日市场总结
## 二、情绪周期研判
## 三、连板梯队点评
## 四、板块轮动观点
## 五、消息面影响分析
结合新闻分析对A股板块和个股的潜在影响
## 六、明日操作策略
- **今日主线**：最强主线板块
- **核心龙头**：最值得关注的龙头股
- **明日预期**：情绪和走势预判
- **退潮风险**：可能走弱的方向
- **可观察标的**：明日值得关注的具体个股（附理由）

800字以内。"""},
            {"role": "user", "content": _build_ai_prompt(report)},
        ],
        stream=False, max_tokens=2000,
    )
    return resp.choices[0].message.content


def _build_ai_prompt(r):
    pa = r.get("prev_zt_analysis") or {}; s = r.get("sentiment",{}); ta = r.get("tier_analysis",{})
    lines = [
        f"日期:{r['date']} 涨停{r['zt_count']} 跌停{r['dt_count']} 炸板{r['zb_count']} 炸板率{r['zb_rate']}%",
        f"上涨{r.get('up_count','-')} 下跌{r.get('down_count','-')} 首板{r.get('shouban_count','-')} 连板{r['lianban_count']}",
        f"最高{r['max_lianban']}板 晋级{r.get('promotion_count','-')} 溢价{pa.get('premium_rate','-')}% 晋级率{pa.get('promotion_rate','-')}%",
        f"情绪:{s.get('level','-')}({s.get('score',0)}分) 周期:{s.get('cycle','-')}",
        f"梯队:{ta.get('desc','-')} 龙头:{ta.get('core_leader','-')}",
    ]
    for t, stocks in r.get("lianban_tiers",{}).items():
        if int(t) >= 2: lines.append(f"  {t}板: " + ", ".join(item["名称"] for item in stocks))
    for b in r.get("strong_boards",[])[:5]:
        lines.append(f"  板块:{b['板块']} 涨停{b['涨停家数']} 龙头{b['龙头个股']}")
    br = r.get("board_rotation",{})
    if br.get("relation"): lines.append(f"板块关系:{br['relation']}")
    if br.get("retreat_warning"): lines.append(f"退潮预警:{br['retreat_warning']}")
    themes = r.get("zt_themes",[])
    if themes:
        top3 = ", ".join(t["theme"]+"("+str(t["count"])+"只)" for t in themes[:3])
        lines.append(f"涨停主题TOP3: {top3}")
    news = r.get("news",[])[:8]
    if news:
        lines.append("\n消息面:")
        for n in news:
            hint = f" [{n['impact_hint']}]" if n.get("impact_hint") else ""
            lines.append(f"  - {n.get('标题','')}{hint}")
    return "\n".join(lines)


# ========== Board Trend (Long-cycle) ==========

TREND_CACHE_DIR = os.path.join(BASE_DIR, "cache_trend")
os.makedirs(TREND_CACHE_DIR, exist_ok=True)


def _trend_cache_path(ds):
    return os.path.join(TREND_CACHE_DIR, f"{ds}.json")


def _read_trend_cache(ds):
    p = _trend_cache_path(ds)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _write_trend_cache(ds, data):
    with open(_trend_cache_path(ds), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)


def fetch_board_trend(date_str, force=False):
    cached = _read_trend_cache(date_str)
    if cached and not force:
        return cached

    end_d = datetime.strptime(date_str, "%Y%m%d")
    periods = {
        "1w": (end_d - timedelta(days=7)).strftime("%Y%m%d"),
        "1m": (end_d - timedelta(days=30)).strftime("%Y%m%d"),
        "3m": (end_d - timedelta(days=90)).strftime("%Y%m%d"),
        "6m": (end_d - timedelta(days=180)).strftime("%Y%m%d"),
        "1y": (end_d - timedelta(days=365)).strftime("%Y%m%d"),
    }

    board_names = []
    try:
        bdf = ak.stock_board_industry_name_em()
        if bdf is not None and not bdf.empty:
            bdf = bdf.sort_values("涨跌幅", ascending=False)
            board_names = bdf["板块名称"].tolist()[:30]
    except Exception:
        pass

    concept_names = []
    time.sleep(1)
    try:
        cdf = ak.stock_board_concept_name_em()
        if cdf is not None and not cdf.empty:
            cdf = cdf.sort_values("涨跌幅", ascending=False)
            concept_names = cdf["板块名称"].tolist()[:20]
    except Exception:
        pass

    def _fetch_hist(symbol, start, end, board_type="industry"):
        fn = ak.stock_board_industry_hist_em if board_type == "industry" else ak.stock_board_concept_hist_em
        try:
            time.sleep(0.5)
            df = fn(symbol=symbol, start_date=start, end_date=end, period="日k")
            if df is not None and not df.empty:
                first_c = _sf(df.iloc[0].get("开盘", df.iloc[0].get("收盘", 0)))
                last_c = _sf(df.iloc[-1].get("收盘", 0))
                chg = round((last_c - first_c) / first_c * 100, 2) if first_c > 0 else 0
                vol_avg = _sf(df["成交量"].mean()) if "成交量" in df.columns else 0
                vol_last = _sf(df.iloc[-1].get("成交量", 0)) if "成交量" in df.columns else 0
                vol_ratio = round(vol_last / vol_avg, 2) if vol_avg > 0 else 1
                return {"chg": chg, "days": len(df), "vol_ratio": vol_ratio}
        except Exception:
            pass
        return None

    industry_data = []
    for name in board_names[:15]:
        entry = {"name": name, "type": "industry"}
        for pk, start in periods.items():
            entry[pk] = _fetch_hist(name, start, date_str, "industry")
        if any(entry.get(pk) for pk in periods):
            industry_data.append(entry)
        if len(industry_data) >= 10:
            break

    concept_data = []
    for name in concept_names[:15]:
        entry = {"name": name, "type": "concept"}
        for pk, start in periods.items():
            entry[pk] = _fetch_hist(name, start, date_str, "concept")
        if any(entry.get(pk) for pk in periods):
            concept_data.append(entry)
        if len(concept_data) >= 10:
            break

    news_summary = []
    try:
        ndf = ak.stock_info_global_cls()
        if ndf is not None and not ndf.empty:
            for _, row in ndf.head(15).iterrows():
                news_summary.append(row.get("标题", ""))
    except Exception:
        pass

    result = {
        "date": date_str,
        "industry": industry_data,
        "concept": concept_data,
        "news_titles": news_summary,
    }

    _write_trend_cache(date_str, result)
    return result


def call_trend_ai(trend_data, report_data=None):
    try:
        from openai import OpenAI
    except ImportError:
        return "需要安装 openai 库"
    if not DEEPSEEK_API_KEY:
        return "未配置 DEEPSEEK_API_KEY"

    lines = [f"分析日期: {trend_data['date']}\n"]

    period_labels = {"1w": "近1周", "1m": "近1月", "3m": "近3月", "6m": "近半年", "1y": "近1年"}

    lines.append("=== 行业板块多周期涨幅 ===")
    for b in trend_data.get("industry", []):
        parts = [f"{b['name']}:"]
        for pk in ["1w", "1m", "3m", "6m", "1y"]:
            d = b.get(pk)
            if d:
                parts.append(f"{period_labels[pk]}{d['chg']:+.1f}%(量比{d['vol_ratio']})")
        lines.append(" ".join(parts))

    lines.append("\n=== 概念板块多周期涨幅 ===")
    for b in trend_data.get("concept", []):
        parts = [f"{b['name']}:"]
        for pk in ["1w", "1m", "3m", "6m", "1y"]:
            d = b.get(pk)
            if d:
                parts.append(f"{period_labels[pk]}{d['chg']:+.1f}%(量比{d['vol_ratio']})")
        lines.append(" ".join(parts))

    if report_data:
        lines.append("\n=== 今日盘面概况 ===")
        lines.append(f"涨停{report_data.get('zt_count',0)} 跌停{report_data.get('dt_count',0)} "
                     f"炸板率{report_data.get('zb_rate',0)}% 最高{report_data.get('max_lianban',0)}板")
        for b in report_data.get("strong_boards", [])[:5]:
            lines.append(f"  强势: {b['板块']} 涨停{b['涨停家数']}")

    news = trend_data.get("news_titles", [])
    if news:
        lines.append("\n=== 近期消息面 ===")
        for t in news[:10]:
            lines.append(f"  - {t}")

    prompt_text = "\n".join(lines)

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": """你是一位资深A股趋势交易分析师，擅长中长线板块轮动分析和趋势预判。

基于多周期（1周/1月/3月/半年/1年）板块数据和消息面，用Markdown输出板块趋势分析：

## 一、板块轮动全景
分析当前A股板块的整体轮动格局，哪些板块处于上升趋势、哪些在衰退、哪些在筑底

## 二、强势板块追踪
列出近期持续强势的板块（多个周期均表现好），分析其上涨逻辑和持续性

## 三、新兴方向挖掘
找出近1周/1月刚启动但更长周期处于低位的板块，这些可能是新主线的萌芽

## 四、衰退预警
哪些板块短期还在涨，但中长期已经走弱，可能面临回调

## 五、趋势预测
给出未来不同时间维度的板块轮动预测：
- **明日/本周**：最可能延续或启动的方向
- **未来1-2周**：哪些板块可能接力上位
- **未来1个月**：中线布局方向

## 六、趋势策略建议
- 趋势做多方向（中长线可关注的板块+逻辑）
- 趋势做空/回避方向
- 短线打板与趋势结合的思路（哪些趋势板块适合打首板/二板介入）

1200字以内，重点分析轮动规律和预测逻辑。"""},
            {"role": "user", "content": prompt_text},
        ],
        stream=False, max_tokens=3000,
    )
    return resp.choices[0].message.content


# ========== HTML Snapshot ==========

def save_html_snapshot(date_str, html_content):
    path = os.path.join(REPORTS_DIR, f"{date_str}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return path


# ========== Routes ==========

@app.route("/")
def index(): return send_from_directory("static", "index.html")


@app.route("/api/report")
def api_report():
    date_str = request.args.get("date", datetime.now().strftime("%Y%m%d"))
    force = request.args.get("force", "0") == "1"
    try:
        return jsonify({"success": True, "data": fetch_report(date_str, force=force)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/save_snapshot", methods=["POST"])
def api_save_snapshot():
    date_str = request.json.get("date", "")
    html = request.json.get("html", "")
    if not date_str or not html:
        return jsonify({"success": False, "error": "缺少参数"})
    try:
        path = save_html_snapshot(date_str, html)
        return jsonify({"success": True, "path": path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/reports/<path:filename>")
def serve_report(filename):
    return send_from_directory(REPORTS_DIR, filename)


@app.route("/api/dates")
def api_dates():
    dates = []; today = datetime.now()
    for i in range(45):
        d = today - timedelta(days=i)
        if d.weekday() < 5: dates.append(d.strftime("%Y%m%d"))
        if len(dates) >= 30: break
    result = []
    for ds in dates:
        c = _read_cache(ds)
        if c: result.append({"date": ds, "zt_count": c.get("zt_count","?"), "dt_count": c.get("dt_count","?"),
            "sentiment_level": c.get("sentiment",{}).get("level",""), "has_report": os.path.exists(os.path.join(REPORTS_DIR, f"{ds}.html"))})
        else: result.append({"date": ds, "zt_count": "?", "dt_count": "?", "sentiment_level": "", "has_report": False})
    return jsonify({"success": True, "data": result})


@app.route("/api/ai_analyze", methods=["POST"])
def api_ai_analyze():
    date_str = request.json.get("date", "")
    if not DEEPSEEK_API_KEY: return jsonify({"success": False, "error": "未配置 DEEPSEEK_API_KEY"})
    cached = _read_cache(date_str)
    if not cached: return jsonify({"success": False, "error": "请先加载该日期报表"})
    try:
        result = call_deepseek_analysis(cached)
        cached["ai_analysis"] = result
        _write_cache(date_str, cached)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    app.run(debug=True, port=5788)
