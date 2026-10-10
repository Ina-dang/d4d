"""문서 간 유사도·국가·출처 가중치로 대상 문서 주장의 신뢰도를 계산한다.

신뢰도 = 다른 문서들이 같은 입장일 확률 P_same(유사도)를
        (출처 가중치 × 국가 보정 u)로 가중 평균한 값 (0~1)

국가 보정 u: 같은 나라 문서끼리 서로 비슷할수록(받아쓰기) 문서 1건의 가치를 낮춘다.
  ρ̂   = (p·ρ̄ + m·ρ̄_전체) / (p + m)      경험적 베이즈 축소 (쌍이 적은 나라는 전체 평균 쪽으로)
  n_eff = n / (1 + (n-1)·ρ̂)              Kish 유효표본수
  u     = n_eff / n

입력: {"docs": [...], "claims": [...]}
출력: {"claims": [... 입력 claim 그대로 + "reliability"]}
  claim의 신뢰도 = 그 claim이 나온 문서(document_id)의 신뢰도

모듈로 쓰기:
    from reliability import run
    output = run(data)               # 다음 단계로 넘길 {"claims": [...]}
    output = run(data, full=True)    # 국가 보정·근거 내역까지 포함

CLI로 쓰기:
    python reliability.py input.json                 # 결과 JSON을 stdout으로
    python reliability.py input.json -o output.json  # 파일로 저장
    cat input.json | python reliability.py -         # stdin 입력
    python reliability.py input.json --full          # 근거 내역 포함
    python reliability.py input.json --pretty        # 사람이 읽는 표로 출력
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

DEFAULT_M = 3  # 축소 강도. 1~2로 낮추면 각 나라 실제 값을 더 믿음

# stance_sim.py 실험(주제 3개: 최저임금·원자력·학교 휴대폰, 주제당 200문장, 쌍 59,700개)의
# 유사도 구간 → P(같은 입장). 쌍 200개 미만 구간은 병합. 주제 추가 후 stance_sim.py 출력값으로 교체
DEFAULT_P_SAME = [
    (0.50, 0.17), (0.55, 0.22), (0.60, 0.27), (0.65, 0.38), (0.70, 0.40),
    (0.75, 0.42), (0.80, 0.61), (0.85, 0.85), (0.90, 0.95), (1.01, 0.99),
]  # (구간 상한, 확률)


def p_same(s: float, table=DEFAULT_P_SAME) -> float:
    """유사도 s → 같은 입장일 확률."""
    for hi, p in table:
        if s < hi:
            return p
    return table[-1][1]


def validate(data: dict) -> list[dict]:
    """입력 형식 검사. 문제가 있으면 무엇이 틀렸는지 담아 ValueError."""
    if not isinstance(data, dict) or not isinstance(data.get("docs"), list):
        raise ValueError('입력은 {"docs": [...]} 형식이어야 합니다')
    docs = data["docs"]
    ids = [d.get("id") for d in docs]
    if len(set(ids)) != len(ids):
        raise ValueError("문서 id가 중복됩니다")
    for d in docs:
        for key in ("id", "country", "weight", "sim"):
            if key not in d:
                raise ValueError(f"문서 {d.get('id', '?')}에 '{key}' 필드가 없습니다")
        missing = [o for o in ids if o != d["id"] and o not in d["sim"]]
        if missing:
            raise ValueError(f"문서 {d['id']}의 sim에 {missing} 유사도가 없습니다")
    return docs


def country_u(docs: list[dict], m: float = DEFAULT_M) -> dict:
    """나라별 내부 유사도 → 축소(ρ̂) → n_eff → 문서 1건 가중치 u."""
    by_c = defaultdict(list)
    for d in docs:
        by_c[d["country"]].append(d)
    pair_sims = {
        c: [a["sim"][b["id"]] for i, a in enumerate(ds) for b in ds[i + 1:]]
        for c, ds in by_c.items()
    }
    all_pairs = [s for ss in pair_sims.values() for s in ss]
    rho_all = sum(all_pairs) / len(all_pairs) if all_pairs else 0.0
    out = {}
    for c, ds in by_c.items():
        n, ss = len(ds), pair_sims[c]
        if not ss:  # 문서 1건: 쌍 없음 → 보정 없이 u = 1
            out[c] = {"n": 1, "rho_hat": None, "n_eff": 1.0, "u": 1.0}
            continue
        rho_hat = (sum(ss) + m * rho_all) / (len(ss) + m)
        n_eff = n / (1 + (n - 1) * rho_hat)
        out[c] = {"n": n, "rho_hat": rho_hat, "n_eff": n_eff, "u": n_eff / n}
    return out


def reliability(docs: list[dict], target_id: str, cu: dict, table=DEFAULT_P_SAME) -> dict:
    """대상 문서 하나의 신뢰도와 근거 내역."""
    target = next((d for d in docs if d["id"] == target_id), None)
    if target is None:
        raise ValueError(f"대상 문서 {target_id}가 입력에 없습니다")
    evidence, num, den = [], 0.0, 0.0
    for d in docs:
        if d["id"] == target_id:
            continue
        s = target["sim"][d["id"]]
        w = d["weight"] * cu[d["country"]]["u"]  # 출처 가중치 × 국가 보정
        p = p_same(s, table)
        num, den = num + w * p, den + w
        evidence.append({"id": d["id"], "country": d["country"], "sim": s,
                         "weight": round(w, 4), "p_same": p})
    return {
        "id": target_id,
        "country": target["country"],
        "reliability": round(num / den, 4) if den > 0 else None,  # 비교할 문서가 없으면 None
        "evidence": evidence,
    }


def score(data: dict, targets: list[str] | None = None,
          m: float = DEFAULT_M, table=DEFAULT_P_SAME) -> dict:
    """입력 전체를 받아 결과 dict를 돌려준다 (JSON 직렬화 가능)."""
    docs = validate(data)
    cu = country_u(docs, m)
    targets = targets or [d["id"] for d in docs]
    return {
        "countries": {c: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in info.items()}
                      for c, info in cu.items()},
        "results": [reliability(docs, t, cu, table) for t in targets],
    }


def run(data: dict, m: float = DEFAULT_M, table=DEFAULT_P_SAME, full: bool = False) -> dict:
    """docs로 문서별 신뢰도를 계산해 claims 각각에 붙여 돌려준다.

    - claim 필드는 그대로 두고 "reliability"만 추가한다.
    - document_id가 docs에 없는 claim은 reliability = None, 경고는 stderr로.
    - full=True면 countries(국가 보정)와 documents(문서별 근거 내역)도 함께 돌려준다.
    """
    claims = data.get("claims")
    if not isinstance(claims, list):
        raise ValueError('입력에 "claims" 리스트가 없습니다')
    doc_ids = {d.get("id") for d in data.get("docs", [])}
    targets = sorted({c.get("document_id") for c in claims} & doc_ids)

    scored = score(data, targets, m, table) if targets else {"countries": {}, "results": []}
    rel_by_doc = {r["id"]: r["reliability"] for r in scored["results"]}

    out_claims = []
    for c in claims:
        doc_id = c.get("document_id")
        if doc_id not in doc_ids:
            print(f"경고: claim {c.get('claim_id')}의 document_id {doc_id}가 docs에 없습니다",
                  file=sys.stderr)
        out_claims.append({**c, "reliability": rel_by_doc.get(doc_id)})

    output = {"claims": out_claims}
    if full:
        output["countries"] = scored["countries"]
        output["documents"] = scored["results"]
    return output


def print_pretty(result: dict) -> None:
    """run(..., full=True) 결과를 표로 출력."""
    for c in result["claims"]:
        rel = "-" if c["reliability"] is None else f"{c['reliability']:.3f}"
        print(f"claim {c.get('claim_id')} (문서 {c.get('document_id')})  신뢰도 {rel}")
    print()
    print("나라  문서수  ρ̂      n_eff  u")
    for c, v in result["countries"].items():
        rho = "  -  " if v["rho_hat"] is None else f"{v['rho_hat']:.3f}"
        print(f"{c:4}  {v['n']:5d}  {rho}  {v['n_eff']:.3f}  {v['u']:.3f}")
    for r in result["documents"]:
        rel = "-" if r["reliability"] is None else f"{r['reliability']:.3f}"
        print(f"\n[{r['id']}({r['country']})] 신뢰도 {rel}")
        for e in r["evidence"]:
            print(f"  {e['id']}({e['country']})  유사도 {e['sim']:.2f}  "
                  f"가중치 {e['weight']:.3f}  P(같은 입장) {e['p_same']:.2f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="문서 신뢰도 계산")
    ap.add_argument("input", help="입력 JSON 파일 경로, '-'면 stdin")
    ap.add_argument("-o", "--output", help="결과 JSON 저장 경로 (기본: stdout)")
    ap.add_argument("-m", type=float, default=DEFAULT_M, help=f"축소 강도 (기본 {DEFAULT_M})")
    ap.add_argument("--full", action="store_true", help="국가 보정·문서별 근거 내역도 출력")
    ap.add_argument("--pretty", action="store_true", help="JSON 대신 사람이 읽는 표로 출력")
    args = ap.parse_args(argv)

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)

    try:
        result = run(data, args.m, full=args.full or args.pretty)
    except ValueError as e:
        print(f"입력 오류: {e}", file=sys.stderr)
        return 1

    if args.pretty:
        print_pretty(result)
    elif args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
