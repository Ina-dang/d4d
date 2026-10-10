"""
OSINT 수집기 설정 및 도메인 티어(Tier) 정의
"""

# 🎯 도메인별 티어, 기본 언어, 국가, 기관명, 기본 신뢰도 가중치
OSINT_WHITELIST = {

    # 📱 OSINT 공식 SNS 도메인 (속보·1차 팩트 가치, 가중치 0.50~0.60 적용)
    "x.com": {
        "tier": 3,
        "name": "X (구 트위터 - 공식 안보 계정)",
        "country": "GLOBAL",
        "category": "official_sns",
        "weight": 0.60,
        "language": "unknown",
    },
    "twitter.com": {
        "tier": 3,
        "name": "Twitter (공식 안보 계정)",
        "country": "GLOBAL",
        "category": "official_sns",
        "weight": 0.60,
        "language": "unknown",
    },
    "weibo.com": {
        "tier": 3,
        "name": "Weibo (중국 웨이보 - 전구/국방부 공식 계정)",
        "country": "CN",
        "category": "official_sns",
        "weight": 0.60,
        "language": "zh",
    },
    "facebook.com": {
        "tier": 3,
        "name": "Facebook (공식 기관 SNS)",
        "country": "GLOBAL",
        "category": "official_sns",
        "weight": 0.55,
        "language": "unknown",
    },
    "youtube.com": {
        "tier": 3,
        "name": "YouTube (국방부/군 공식 브리핑 영상)",
        "country": "GLOBAL",
        "category": "social_media",
        "weight": 0.55,
        "language": "unknown",
    },
    # 🇭🇰 홍콩 (중국 본토 선전·검열 완충 및 중화권 심층 분석 2차 보고 출처)
    "scmp.com": {
        "tier": 2,
        "name": "South China Morning Post (홍콩 SCMP)",
        "country": "HK",
        "category": "reputable_media",
        "weight": 0.85,
        "language": "en",
    },
    "mingpao.com": {
        "tier": 2,
        "name": "Ming Pao (홍콩 명보)",
        "country": "HK",
        "category": "reputable_media",
        "weight": 0.85,
        "language": "zh",
    },
    "singtao.com": {
        "tier": 3,
        "name": "Sing Tao (홍콩 성도일보)",
        "country": "HK",
        "category": "commercial_media",
        "weight": 0.75,
        "language": "zh",
    },
    "hk01.com": {
        "tier": 3,
        "name": "HK01 (홍콩01)",
        "country": "HK",
        "category": "commercial_media",
        "weight": 0.75,
        "language": "zh",
    },
    # [Tier 1] 역내 제3국 및 공식 감시·국방 기관 (가장 객관적인 레이더/공식 감시 팩트 -> 가중치 0.95 최고점)
    "mod.go.jp": {
        "tier": 1, "country": "JP", "language": "ja", "category": "neutral_observer",
        "name": "Japan MoD / Joint Staff", "weight": 0.95
    },
    "mnd.go.kr": {
        "tier": 1, "country": "KR", "language": "ko", "category": "neutral_observer",
        "name": "Korea MND", "weight": 0.95
    },
    "jcs.mil.kr": {
        "tier": 1, "country": "KR", "language": "ko", "category": "neutral_observer",
        "name": "Korea JCS (합동참모본부)", "weight": 0.95
    },
    "coastguard.gov.ph": {
        "tier": 1, "country": "PH", "language": "en", "category": "neutral_observer",
        "name": "Philippine Coast Guard", "weight": 0.95
    },
    "defense.gov": {
        "tier": 1, "country": "US", "language": "en", "category": "neutral_observer",
        "name": "US DoD (미 국방부)", "weight": 0.95
    },

    # [Tier 2] 당사국 공식 발표 (공식성은 높으나 자국 유리 왜곡·일방 주장 가능성 감안 -> 가중치 0.85)
    "mnd.gov.tw": {
        "tier": 2, "country": "TW", "language": "zh", "category": "party_official",
        "name": "Taiwan MND (대만 국방부)", "weight": 0.85
    },
    "mod.gov.cn": {
        "tier": 2, "country": "CN", "language": "zh", "category": "party_official",
        "name": "China MoD (중국 국방부)", "weight": 0.85
    },
    "ccg.gov.cn": {
        "tier": 2, "country": "CN", "language": "zh", "category": "party_official",
        "name": "China Coast Guard (중국 해경)", "weight": 0.85
    },
    "news.cn": {
        "tier": 2, "country": "CN", "language": "zh", "category": "party_official",
        "name": "Xinhua News (신화통신 - 중국 관영)", "weight": 0.85
    },
    "mod.gov.in": {
        "tier": 2, "country": "IN", "language": "en", "category": "party_official",
        "name": "Ministry of Defence, India (인도 국방부)", "weight": 0.85
    },
    "pib.gov.in": {
        "tier": 2, "country": "IN", "language": "en", "category": "party_official",
        "name": "Press Information Bureau, India (인도 정부 공보국)", "weight": 0.85
    },
    "ispr.gov.pk": {
        "tier": 2, "country": "PK", "language": "en", "category": "party_official",
        "name": "ISPR Pakistan (파키스탄 군 홍보원)", "weight": 0.85
    },

    # [Tier 3] 공신력 있는 역내/글로벌 팩트 언론 (취재 기반 2차 보도 -> 가중치 0.75)
    "yna.co.kr": {
        "tier": 3, "country": "KR", "language": "ko", "category": "reputable_media",
        "name": "Yonhap News (연합뉴스)", "weight": 0.75
    },
    "cna.com.tw": {
        "tier": 3, "country": "TW", "language": "zh", "category": "reputable_media",
        "name": "CNA Taiwan (대만 중앙통신사)", "weight": 0.75
    },
    "kyodonews.net": {
        "tier": 3, "country": "JP", "language": "ja", "category": "reputable_media",
        "name": "Kyodo News (교도통신)", "weight": 0.75
    },
    "nhk.or.jp": {
        "tier": 3, "country": "JP", "language": "ja", "category": "reputable_media",
        "name": "NHK World", "weight": 0.75
    },
    "thehindu.com": {
        "tier": 3, "country": "IN", "language": "en", "category": "reputable_media",
        "name": "The Hindu (인도 일간지)", "weight": 0.75
    },
    "dawn.com": {
        "tier": 3, "country": "PK", "language": "en", "category": "reputable_media",
        "name": "Dawn (파키스탄 일간지)", "weight": 0.75
    },
    "dawnnews.tv": {
        "tier": 3, "country": "PK", "language": "ur", "category": "reputable_media",
        "name": "Dawn News Urdu", "weight": 0.75
    },
    "jang.com.pk": {
        "tier": 3, "country": "PK", "language": "ur", "category": "commercial_media",
        "name": "Daily Jang", "weight": 0.75
    },
    "urdu.geo.tv": {
        "tier": 3, "country": "PK", "language": "ur", "category": "commercial_media",
        "name": "Geo News Urdu", "weight": 0.75
    },
    "bbc.com": {
        "tier": 3, "country": "GLOBAL", "language": "unknown", "category": "reputable_media",
        "name": "BBC News", "weight": 0.75
    },
    "channelnewsasia.com": {
        "tier": 3, "country": "SG", "language": "en", "category": "reputable_media",
        "name": "CNA Singapore", "weight": 0.75
    },
    "reuters.com": {
        "tier": 3, "country": "GLOBAL", "language": "en", "category": "reputable_media",
        "name": "Reuters", "weight": 0.75
    },
    "apnews.com": {
        "tier": 3, "country": "US", "language": "en", "category": "reputable_media",
        "name": "AP News", "weight": 0.75
    }
}

# 🎯 7개 주요 안보 행위자별 화이트리스트 도메인 매핑
COUNTRY_DOMAINS = {
    "HK": ["scmp.com", "mingpao.com", "singtao.com", "hk01.com"],  # 🇭🇰 홍콩 (비검열 완충 분석)
    "KR": ["mnd.go.kr", "x.com", "youtube.com", "jcs.mil.kr", "yna.co.kr"],
    "CN": ["mod.gov.cn", "weibo.com", "ccg.gov.cn", "news.cn"],
    "TW": ["mnd.gov.tw", "x.com", "twitter.com", "facebook.com", "cna.com.tw"],
    "JP": ["mod.go.jp", "x.com", "twitter.com", "kyodonews.net", "nhk.or.jp"],
    "IN": ["mod.gov.in", "thehindu.com"],  # pib.gov.in 대용량 PDF 크롤링 지연 배제
    "PK": ["dawn.com"],
    "US": ["defense.gov", "x.com", "twitter.com", "youtube.com", "apnews.com", "reuters.com", "channelnewsasia.com"],
}

# Search source hints only. Article language is always detected from the fetched body.
LANGUAGE_SEARCH_DOMAINS = {
    'ur': ['dawnnews.tv', 'jang.com.pk', 'urdu.geo.tv', 'bbc.com',
           'pib.gov.in', 'ispr.gov.pk', 'nhk.or.jp'],
}


# 텍스트 및 파싱 제한 상수
MAX_RAW_CHARS = 4000          # 1개 문서당 최대 본문 길이 (토큰 및 비용 절약)
MAX_PARAGRAPH_CHARS = 400     # 1개 문단 최대 글자 수 (LLM 문맥 크기 최적화)
MIN_PARAGRAPH_CHARS = 15      # 너무 짧은 무의미한 줄 제거 기준
DEFAULT_MIN_SCORE = 0.7
MIN_SCORE_FLOOR = 0.35                     # 🎯 적응형 보충 선별 시 허용되는 절대 최소 하한선 (0.35 미만 무관한 노이즈는 폐기)
DEFAULT_MAX_DOCS_PER_COUNTRY = 20        # 국가별 기본 최대 수집 건수 (확대 20건)
MAX_GREATER_CHINA_TOTAL = 20          # 중화권(CN + HK + TW) 3대 진영 합산 최대 건수 제한 (20건)

# 🌐 다국어 안보/국방 전문 번역 사전 (질문 문장 -> 중국어(간체/번체), 일본어, 영어 1:1 자연 번역용)
DEFENSE_LEXICON = [
    # [신규 추가: 양안 충돌 / 공식 발표 / 주요 쟁점 및 논쟁 어휘]
    ("중국과 대만", {"CN": "两岸 中台", "TW": "兩岸 中台", "JP": "中台 両岸", "EN": "China Taiwan cross-strait"}),
    ("중국 대만", {"CN": "两岸 中台", "TW": "兩岸 中台", "JP": "中台 両岸", "EN": "China Taiwan cross-strait"}),
    ("대만해협 충돌", {"CN": "台湾海峡 冲突", "TW": "台灣海峽 衝突", "JP": "台湾海峡 衝突", "EN": "Taiwan Strait clash conflict"}),
    ("대만 해협 충돌", {"CN": "台湾海峡 冲突", "TW": "台灣海峽 衝突", "JP": "台湾海峡 衝突", "EN": "Taiwan Strait clash conflict"}),
    ("양측 발표", {"CN": "双方 表态 声明", "TW": "雙方 表態 聲明", "JP": "双方 発表 声明", "EN": "both sides statements official response"}),
    ("양측", {"CN": "双方", "TW": "雙方", "JP": "双方", "EN": "both sides"}),
    ("공식 발표", {"CN": "官方 声明 表态", "TW": "官方 聲明 表態", "JP": "公式 発表 声明", "EN": "official statement"}),
    ("발표", {"CN": "声明 表态", "TW": "聲明 表態", "JP": "発表 声明", "EN": "statement announcement"}),
    ("주요 논쟁사항", {"CN": "主要 争议 争端", "TW": "主要 爭議 爭端", "JP": "主な 争点 議論", "EN": "key disputes controversy"}),
    ("주요 논쟁", {"CN": "主要 争议", "TW": "主要 爭議", "JP": "主な 争点", "EN": "key disputes"}),
    ("논쟁사항", {"CN": "争议 争端", "TW": "爭議 爭端", "JP": "争点 議論", "EN": "disputes controversy"}),
    ("논쟁", {"CN": "争议", "TW": "爭議", "JP": "争点", "EN": "dispute controversy"}),
    ("쟁점", {"CN": "焦点 争议", "TW": "焦點 爭議", "JP": "争点 焦点", "EN": "key issue dispute"}),

    # [전구 / 공역·항행 통제 / 대응 데이터 / 전문 군사 분석 어휘]
    ("대만 해협 일대", {"CN": "台湾海峡", "TW": "台灣海峽", "JP": "台湾海峡", "EN": "Taiwan Strait"}),
    ("대만 해협", {"CN": "台湾海峡", "TW": "台灣海峽", "JP": "台湾海峡", "EN": "Taiwan Strait"}),
    ("중국 동부전구", {"CN": "解放军 东部战区", "TW": "共軍 東部戰區", "JP": "中国軍 東部戦区", "EN": "PLA Eastern Theater Command"}),
    ("동부전구", {"CN": "东部战区", "TW": "東部戰區", "JP": "東部戦区", "EN": "Eastern Theater Command"}),
    ("동부 전구", {"CN": "东部战区", "TW": "東部戰區", "JP": "東部戦区", "EN": "Eastern Theater Command"}),
    ("남부전구", {"CN": "南部战区", "TW": "南部戰區", "JP": "南部戦区", "EN": "Southern Theater Command"}),
    ("군사 훈련", {"CN": "军事演习", "TW": "軍事演習", "JP": "軍事演習", "EN": "military exercises"}),
    ("군사훈련", {"CN": "军事演习", "TW": "軍事演習", "JP": "軍事演習", "EN": "military exercises"}),
    ("비행/항행 통제", {"CN": "航行警告 禁航 禁飞", "TW": "航行警告 禁航 禁飛", "JP": "航行警報 飛行制限", "EN": "airspace navigation restrictions"}),
    ("항행 통제", {"CN": "航行警告", "TW": "航行警告 禁航", "JP": "航行警報", "EN": "navigation restrictions"}),
    ("항행통제", {"CN": "航行警告", "TW": "航行警告 禁航", "JP": "航行警報", "EN": "navigation restrictions"}),
    ("비행 통제", {"CN": "禁飞区", "TW": "禁飛區", "JP": "飛行制限", "EN": "airspace restrictions"}),
    ("비행통제", {"CN": "禁飞区", "TW": "禁飛區", "JP": "飛行制限", "EN": "airspace restrictions"}),
    ("통제 시간 구역", {"CN": "管制时间 区域", "TW": "管制時間 區域", "JP": "制限期間 区域", "EN": "restriction time and area"}),
    ("시간·구역", {"CN": "时间 区域", "TW": "時間 區域", "JP": "時間 区域", "EN": "time and area"}),
    ("시간 구역", {"CN": "时间 区域", "TW": "時間 區域", "JP": "時間 区域", "EN": "time and area"}),
    ("통제 구역", {"CN": "管制区域", "TW": "管制區域", "JP": "管制区域", "EN": "restricted area"}),
    ("훈련 구역", {"CN": "演习区域", "TW": "演習區域", "JP": "演習区域", "EN": "exercise zone"}),
    ("대만 국방부", {"CN": "台湾 国防部", "TW": "台灣 國防部", "JP": "台湾 国防部", "EN": "Taiwan MND"}),
    ("일본 방위성", {"CN": "日本 防卫省", "TW": "日本 防衛省", "JP": "日本 防衛省", "EN": "Japan MOD"}),
    ("방위성", {"CN": "防卫省", "TW": "防衛省", "JP": "防衛省", "EN": "Ministry of Defense"}),
    ("실측 대응 데이터", {"CN": "监测 应对 数据", "TW": "實測 應對 數據", "JP": "監視 対応 データ", "EN": "monitoring response data"}),
    ("실측 대응", {"CN": "监测 应对", "TW": "實測 應對", "JP": "監視 対応", "EN": "monitoring response"}),
    ("대응 데이터", {"CN": "应对 数据", "TW": "應對 數據", "JP": "対応 データ", "EN": "response data"}),
    ("일치·상충", {"CN": "差异 一致", "TW": "差異 一致", "JP": "相違 一致", "EN": "discrepancies"}),
    ("일치 상충", {"CN": "差异 一致", "TW": "差異 一致", "JP": "相違 一致", "EN": "discrepancies"}),
    ("대만해협 군사활동", {"CN": "台湾海峡 军事活动", "TW": "台灣海峽 軍事活動", "JP": "台湾海峡 軍事活動", "EN": "Taiwan Strait military activity"}),
    ("대만해협 군사훈련", {"CN": "台湾海峡 军事演习", "TW": "台灣海峽 軍事演習", "JP": "台湾海峡 軍事演習", "EN": "Taiwan Strait military exercise"}),
    ("대만해협", {"CN": "台湾海峡", "TW": "台灣海峽", "JP": "台湾海峡", "EN": "Taiwan Strait"}),
    ("남중국해", {"CN": "南海", "TW": "南海", "JP": "南シナ海", "EN": "South China Sea"}),
    ("동중국해", {"CN": "东海", "TW": "東海", "JP": "東シナ海", "EN": "East China Sea"}),
    ("한반도", {"CN": "朝鲜半岛", "TW": "朝鮮半島", "JP": "朝鮮半島", "EN": "Korean Peninsula"}),
    ("카슈미르", {"CN": "克什米尔", "TW": "喀什米爾", "JP": "カシミール", "EN": "Kashmir"}),
    ("대만", {"CN": "台湾", "TW": "台灣", "JP": "台湾", "EN": "Taiwan"}),
    ("중국", {"CN": "中国", "TW": "中國", "JP": "中国", "EN": "China"}),
    ("일본", {"CN": "日本", "TW": "日本", "JP": "日本", "EN": "Japan"}),
    ("한국", {"CN": "韩国", "TW": "韓國", "JP": "韓国", "EN": "South Korea"}),
    ("대한민국", {"CN": "韩国", "TW": "韓國", "JP": "韓国", "EN": "South Korea"}),
    ("북한", {"CN": "朝鲜", "TW": "北韓", "JP": "北朝鮮", "EN": "North Korea"}),
    ("미국", {"CN": "美国", "TW": "美國", "JP": "米国", "EN": "United States"}),
    ("인도", {"CN": "印度", "TW": "印度", "JP": "インド", "EN": "India"}),
    ("파키스탄", {"CN": "巴基斯坦", "TW": "巴基斯坦", "JP": "パキスタン", "EN": "Pakistan"}),
    ("러시아", {"CN": "俄罗斯", "TW": "俄羅斯", "JP": "ロシア", "EN": "Russia"}),
    ("필리핀", {"CN": "菲律宾", "TW": "菲律賓", "JP": "フィリピン", "EN": "Philippines"}),

    # 복합 군사 용어 / 사건
    ("방공식별구역", {"CN": "防空识别区", "TW": "防空識別區", "JP": "防空識別圏", "EN": "air defense identification zone ADIZ"}),
    ("군사활동", {"CN": "军事活动", "TW": "軍事活動", "JP": "軍事活動", "EN": "military activity"}),
    ("군사훈련", {"CN": "军事演习", "TW": "軍事演習", "JP": "軍事演習", "EN": "military exercise"}),
    ("군사작전", {"CN": "军事行动", "TW": "軍事行動", "JP": "軍事作戦", "EN": "military operation"}),
    ("군사동향", {"CN": "军事动向", "TW": "軍事動向", "JP": "軍事動向", "EN": "military movements"}),
    ("국경 충돌", {"CN": "边境冲突", "TW": "邊界衝突", "JP": "国境衝突", "EN": "border clash"}),
    ("국경 분쟁", {"CN": "边境争端", "TW": "邊界爭端", "JP": "国境紛争", "EN": "border dispute"}),
    ("영공 침범", {"CN": "侵犯领空", "TW": "侵犯領空", "JP": "領空侵犯", "EN": "airspace violation"}),
    ("영해 침범", {"CN": "侵入领海", "TW": "侵入領海", "JP": "領海侵犯", "EN": "territorial waters violation"}),
    ("미사일 발사", {"CN": "导弹发射", "TW": "飛彈發射", "JP": "ミサイル発射", "EN": "missile launch"}),
    ("탄도미사일", {"CN": "弹道导弹", "TW": "彈道飛彈", "JP": "弾道ミサイル", "EN": "ballistic missile"}),
    ("순항미사일", {"CN": "巡航导弹", "TW": "巡弋飛彈", "JP": "巡航ミサイル", "EN": "cruise missile"}),
    ("극초음속 미사일", {"CN": "高超音速导弹", "TW": "極音速飛彈", "JP": "極超音速ミサイル", "EN": "hypersonic missile"}),
    ("핵실험", {"CN": "核试验", "TW": "核試驗", "JP": "核実験", "EN": "nuclear test"}),
    ("항공모함", {"CN": "航空母舰", "TW": "航空母艦", "JP": "空母", "EN": "aircraft carrier"}),
    ("군용기", {"CN": "军机", "TW": "軍機", "JP": "軍用機", "EN": "military aircraft"}),
    ("전투기", {"CN": "战斗机", "TW": "戰鬥機", "JP": "戦闘機", "EN": "fighter jet"}),
    ("폭격기", {"CN": "轰炸机", "TW": "轟炸機", "JP": "爆撃機", "EN": "bomber"}),
    ("초계기", {"CN": "巡逻机", "TW": "巡邏機", "JP": "哨戒機", "EN": "patrol aircraft"}),
    ("무인기", {"CN": "无人机", "TW": "無人機", "JP": "無人機", "EN": "drone UAV"}),
    ("드론", {"CN": "无人机", "TW": "無人機", "JP": "ドローン", "EN": "drone"}),
    ("군함", {"CN": "军舰", "TW": "軍艦", "JP": "軍艦", "EN": "warship"}),
    ("함정", {"CN": "舰艇", "TW": "艦艇", "JP": "艦艇", "EN": "naval vessel"}),
    ("잠수함", {"CN": "潜艇", "TW": "潛艦", "JP": "潜水艦", "EN": "submarine"}),
    ("실사격", {"CN": "实弹", "TW": "實彈", "JP": "実弾", "EN": "live-fire"}),
    ("동향", {"CN": "动向", "TW": "動向", "JP": "동향", "EN": "movements"}),
    ("충돌", {"CN": "冲突", "TW": "衝突", "JP": "衝突", "EN": "clash"}),
    ("훈련", {"CN": "演习", "TW": "演習", "JP": "演習", "EN": "exercise"}),
    ("활동", {"CN": "活动", "TW": "活動", "JP": "活動", "EN": "activity"}),
    ("작전", {"CN": "行动", "TW": "行動", "JP": "作戦", "EN": "operation"}),
    ("발사", {"CN": "发射", "TW": "發射", "JP": "発射", "EN": "launch"}),
    ("배치", {"CN": "部署", "TW": "部署", "JP": "配備", "EN": "deployment"}),
    ("도발", {"CN": "挑衅", "TW": "挑釁", "JP": "挑発", "EN": "provocation"}),
    ("위협", {"CN": "威胁", "TW": "威脅", "JP": "脅威", "EN": "threat"}),
    ("안보", {"CN": "安全", "TW": "安全", "JP": "安全保障", "EN": "security"}),
    ("국방", {"CN": "国防", "TW": "國防", "JP": "防衛", "EN": "defense"}),
    ("해상", {"CN": "海上", "TW": "海上", "JP": "海上", "EN": "maritime"}),
    ("공중", {"CN": "空中", "TW": "空中", "JP": "空中", "EN": "aerial"}),
    ("주변", {"CN": "周边", "TW": "周邊", "JP": "周辺", "EN": "surrounding"}),
    ("최근", {"CN": "近期", "TW": "近期", "JP": "最近", "EN": "recent"}),
]
