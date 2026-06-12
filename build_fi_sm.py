# -*- coding: utf-8 -*-
"""직접비/간접비 월별 파일 통합 → BigQuery Sales_Integration.FI_SM / FI_Matching1 / FI_Matching2

- 직접비 N월.xlsx : [코스트센터분류, 코스트센터, 원가계정과목, 공통여부, 금액] (헤더 2행째, TOTAL 행 제외)
- 간접비 N월.xlsx : [원가계정과목, 보내는 코스트센터, 보내는금액, 비율, 받는 코스트센터, 배부받은금액, 비율]
                    (헤더 3행째, TOTAL 행 제외) → 코스트센터분류='판매간접', Department=받는 코스트센터, 금액=배부받은금액
- FI_Matching 1번탭: 코스트센터 → 간접비분류/본부구분/팀구분 (Department 기준 조인)
- FI_Matching 2번탭: 원가계정과목 → 계정명(CNVN)/대분류/중분류/상세분류

실행: python build_fi_sm.py            # 빌드+검증+업로드
      python build_fi_sm.py --dry-run  # 업로드 없이 빌드+검증만
"""
import sys
import warnings
import pandas as pd

warnings.filterwarnings('ignore')

MONTHS = [1, 2, 3, 4]
YEAR = 2026
DATASET = 'skin1004-319714.Sales_Integration'
FINAL_COLS = ['코스트센터분류', 'Department', '원가계정과목', '금액', 'Year_Month',
              '계정명', '대분류', '중분류', '상세분류', '본부구분', '팀구분', '간접비분류']

# BQ 업로드용 영문 컬럼명 (값은 한글 유지, 컬럼명만 변환)
ENG_FI_SM = {
    '코스트센터분류': 'Cost_Center_Class', '원가계정과목': 'Cost_Account', '금액': 'Amount',
    '계정명': 'Account_Name', '대분류': 'Main_Category', '중분류': 'Sub_Category',
    '상세분류': 'Detail_Category', '본부구분': 'Division', '팀구분': 'Team',
    '간접비분류': 'Indirect_Cost_Class',
}
ENG_M1 = {'코스트센터': 'Cost_Center', 'CC분류': 'CC_Class', '간접비분류': 'Indirect_Cost_Class',
          '본부구분': 'Division', '팀구분': 'Team'}
ENG_M2 = {'원가계정과목': 'Cost_Account', '계정명': 'Account_Name', '대분류': 'Main_Category',
          '중분류': 'Sub_Category', '상세분류': 'Detail_Category'}

log_lines = []
def log(*a):
    s = ' '.join(str(x) for x in a)
    log_lines.append(s)
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('cp949', 'replace').decode('cp949'))


def load_matching():
    m1 = pd.read_excel('FI_Matching.xlsx', sheet_name='1', header=0)
    m1.columns = ['코스트센터', 'CC분류', '간접비분류', '본부구분', '팀구분']
    m1 = m1.dropna(subset=['코스트센터'])
    m1['코스트센터'] = m1['코스트센터'].astype(str).str.strip()

    m2 = pd.read_excel('FI_Matching.xlsx', sheet_name='2', header=0)
    m2.columns = ['원가계정과목', '계정명', '대분류', '중분류', '상세분류']
    m2 = m2.dropna(subset=['원가계정과목'])
    m2['원가계정과목'] = m2['원가계정과목'].astype(str).str.strip()
    # 계정명(CNVN)이 비면 원가계정과목 그대로
    m2['계정명'] = m2['계정명'].fillna(m2['원가계정과목'])
    return m1, m2


def load_direct(n):
    f = f'직접비 {n}월.xlsx'
    df = pd.read_excel(f, sheet_name=0, header=1)
    df.columns = [str(c).strip() for c in df.columns]
    total = pd.to_numeric(df.loc[df['코스트센터분류'] == 'TOTAL', '금액'], errors='coerce').sum()
    df = df[(df['코스트센터분류'] != 'TOTAL') & df['코스트센터'].notna()].copy()
    out = pd.DataFrame({
        '코스트센터분류': df['코스트센터분류'].astype(str).str.strip(),
        'Department': df['코스트센터'].astype(str).str.strip(),
        '원가계정과목': df['원가계정과목'].astype(str).str.strip(),
        '금액': pd.to_numeric(df['금액'], errors='coerce').fillna(0),
        'Year_Month': f'{YEAR}-{n:02d}',
    })
    diff = out['금액'].sum() - total
    log(f'[직접비 {n}월] rows={len(out)} sum={out["금액"].sum():,.0f} TOTAL={total:,.0f} diff={diff:,.0f}')
    assert abs(diff) < 1, f'{f} 합계 불일치'
    return out


def load_indirect(n):
    f = f'간접비 {n}월.xlsx'
    df = pd.read_excel(f, sheet_name=0, header=2)
    df.columns = [str(c).strip() for c in df.columns]
    total = pd.to_numeric(df.loc[df['원가계정과목'] == 'TOTAL', '배부받은금액'], errors='coerce').sum()
    df = df[(df['원가계정과목'] != 'TOTAL') & df['받는 코스트센터'].notna()].copy()
    out = pd.DataFrame({
        '코스트센터분류': '판매간접',
        'Department': df['받는 코스트센터'].astype(str).str.strip(),
        '원가계정과목': df['원가계정과목'].astype(str).str.strip(),
        '금액': pd.to_numeric(df['배부받은금액'], errors='coerce').fillna(0),
        'Year_Month': f'{YEAR}-{n:02d}',
    })
    diff = out['금액'].sum() - total
    log(f'[간접비 {n}월] rows={len(out)} sum={out["금액"].sum():,.0f} TOTAL={total:,.0f} diff={diff:,.0f}')
    assert abs(diff) < 1, f'{f} 합계 불일치'
    return out


def build():
    m1, m2 = load_matching()
    direct = pd.concat([load_direct(n) for n in MONTHS], ignore_index=True)
    indirect = pd.concat([load_indirect(n) for n in MONTHS], ignore_index=True)
    fi = pd.concat([direct, indirect], ignore_index=True)

    # 계정 매핑 (원가계정과목 → 계정명/대분류/중분류/상세분류)
    fi = fi.merge(m2[['원가계정과목', '계정명', '대분류', '중분류', '상세분류']],
                  on='원가계정과목', how='left')
    # 코스트센터 매핑 (Department=받는/보유 코스트센터 → 간접비분류/본부구분/팀구분)
    fi = fi.merge(m1[['코스트센터', '간접비분류', '본부구분', '팀구분']],
                  left_on='Department', right_on='코스트센터', how='left').drop(columns=['코스트센터'])

    fi['금액'] = fi['금액'].round(0).astype('int64')
    fi = fi[FINAL_COLS]

    # ── 데이터 품질 리포트 ──
    un_acct = sorted(fi.loc[fi['대분류'].isna(), '원가계정과목'].unique())
    un_dept = sorted(fi.loc[fi['간접비분류'].isna(), 'Department'].unique())
    if un_acct:
        log(f'[경고] 매칭 안 된 원가계정과목 {len(un_acct)}건:', '; '.join(un_acct))
    if un_dept:
        log(f'[경고] 매칭 안 된 Department {len(un_dept)}건:', '; '.join(un_dept))
    log(f'[FI_SM] 총 {len(fi)}행, 금액 합계 {fi["금액"].sum():,}')
    log(fi.groupby(['Year_Month', '코스트센터분류'])['금액'].sum().to_string())
    return fi, m1, m2


def upload(fi, m1, m2):
    """컬럼명을 영문으로 변환 후 CSV + 명시적 스키마 로드.
    (참고: Parquet 로드는 한글 컬럼명 값을 매칭하지 못해 전부 NULL이 됐었음)"""
    import io
    from google.cloud import bigquery
    from google.oauth2 import service_account
    import config
    creds = service_account.Credentials.from_service_account_file(config.BQ_KEY_PATH)
    client = bigquery.Client(project=config.BQ_PROJECT, credentials=creds)

    fi = fi.rename(columns=ENG_FI_SM)
    m1 = m1.rename(columns=ENG_M1)
    m2 = m2.rename(columns=ENG_M2)

    def schema_for(df):
        return [bigquery.SchemaField(c, 'INTEGER' if str(df[c].dtype).startswith('int') else 'STRING')
                for c in df.columns]

    for name, df in [('FI_SM', fi), ('FI_Matching1', m1), ('FI_Matching2', m2)]:
        table_id = f'{DATASET}.{name}'
        client.delete_table(table_id, not_found_ok=True)  # 잘못된 스키마 잔재 제거 후 재생성
        jc = bigquery.LoadJobConfig(
            schema=schema_for(df),
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            write_disposition='WRITE_TRUNCATE',
        )
        buf = io.BytesIO(df.to_csv(index=False).encode('utf-8'))
        job = client.load_table_from_file(buf, table_id, job_config=jc)
        job.result()
        t = client.get_table(table_id)
        log(f'[업로드] {table_id}: {t.num_rows}행, {len(t.schema)}컬럼')


if __name__ == '__main__':
    fi, m1, m2 = build()
    if '--dry-run' in sys.argv:
        log('[dry-run] 업로드 생략')
    else:
        upload(fi, m1, m2)
    with open('_build_fi_sm_log.txt', 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(log_lines))
