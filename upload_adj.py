# -*- coding: utf-8 -*-
"""부서별 차이내역 → BQ FI_Adjustment 업로드
조인 키: Year_Month + Department (FI_Final과 동일)
"""
import io, sys, warnings
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

YEAR  = 2026
FNAME = '대시보드-손익계산서-수익성분석(0623).xlsx'
SHEET = '1-1. 부서별 차이내역'
TABLE = 'skin1004-319714.Sales_Integration.FI_Adjustment'

MONTH_MAP = {
    '1월': f'{YEAR}-01', '2월': f'{YEAR}-02', '3월': f'{YEAR}-03',
    '4월': f'{YEAR}-04', '5월': f'{YEAR}-05',
}
# 헤더/스킵 키워드
SKIP_C1 = {'구분', '부문', '재무팀', 'ERP', '[프로젝트]수익성분석지수조회', '요소별수익성분석', '매출', '원가'}
SKIP_C3 = {'팀', '[프로젝트]수익성분석지수조회', ''}


def parse():
    raw = pd.read_excel(FNAME, sheet_name=SHEET, header=None)
    print(f'원본 shape: {raw.shape}')

    rows = []
    ym = None

    for _, r in raw.iterrows():
        c = [str(r[j]).strip() if str(r[j]) not in ('nan', 'None') else '' for j in range(10)]

        # 월 헤더
        if c[1] in MONTH_MAP:
            ym = MONTH_MAP[c[1]]
            continue

        if ym is None:
            continue

        # 특수 행 우선 처리 (스킵 전에)
        if c[1] == '전체':
            team = '전체'
        elif c[1] == '매출원가가감계정':
            team = '매출원가가감계정'
        else:
            # 헤더 행 스킵
            if c[1] in SKIP_C1 or c[3] in SKIP_C3:
                continue
            team = c[3] if c[3] else None
            if not team:
                continue

        def vi(idx):
            try:
                v = c[idx]
                return int(float(v)) if v else 0
            except Exception:
                return 0

        rows.append({
            'Year_Month':    ym,
            'Department':    team,
            'Sales_Project': vi(4),   # [프로젝트]수익성분석지수조회 매출
            'Sales_ERP':     vi(5),   # 요소별수익성분석 매출
            'Sales_Diff':    vi(6),   # 차이 (Project − ERP)
            'COGS_Project':  vi(7),   # [프로젝트]수익성분석지수조회 원가
            'COGS_ERP':      vi(8),   # 요소별수익성분석 원가
            'COGS_Diff':     vi(9),   # 차이 (Project − ERP)
        })

    df = pd.DataFrame(rows)
    print(f'\n파싱 결과: {len(df)}행')
    # 월별 요약
    for m, g in df.groupby('Year_Month'):
        teams = [t for t in g['Department'].tolist() if t not in ('전체', '매출원가가감계정')]
        total = g[g['Department'] == '전체'].iloc[0] if len(g[g['Department'] == '전체']) else None
        adj   = g[g['Department'] == '매출원가가감계정'].iloc[0] if len(g[g['Department'] == '매출원가가감계정']) else None
        parts = [f'팀 {len(teams)}개']
        if total is not None:
            parts.append(f'전체매출_차이={total["Sales_Diff"]:,}')
        if adj is not None:
            parts.append(f'매출원가가감계정={adj["COGS_ERP"]:,}')
        print(f'  {m}: ' + ', '.join(parts))
    return df


def upload(df):
    from google.cloud import bigquery
    from google.oauth2 import service_account
    import config

    creds  = service_account.Credentials.from_service_account_file(config.BQ_KEY_PATH)
    client = bigquery.Client(project=config.BQ_PROJECT, credentials=creds)

    def bq_type(dtype):
        s = str(dtype)
        if s.startswith('int'):   return 'INTEGER'
        if s.startswith('float'): return 'FLOAT'
        return 'STRING'

    client.delete_table(TABLE, not_found_ok=True)
    jc = bigquery.LoadJobConfig(
        schema=[bigquery.SchemaField(col, bq_type(df[col].dtype)) for col in df.columns],
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        write_disposition='WRITE_TRUNCATE',
    )
    buf = io.BytesIO(df.to_csv(index=False).encode('utf-8'))
    client.load_table_from_file(buf, TABLE, job_config=jc).result()
    t = client.get_table(TABLE)
    print(f'\n[업로드 완료] {TABLE}')
    print(f'  {t.num_rows}행, {len(t.schema)}컬럼')

    # 검증 쿼리
    q = client.query(f'''
        SELECT Year_Month,
               COUNT(DISTINCT Department) AS dept_cnt,
               SUM(IF(Department="전체", Sales_Diff, 0))      AS total_sales_diff,
               SUM(IF(Department="전체", COGS_Diff,  0))      AS total_cogs_diff,
               SUM(IF(Department="매출원가가감계정", COGS_ERP, 0)) AS cogs_adj
        FROM `{TABLE}`
        GROUP BY Year_Month ORDER BY Year_Month
    ''').result()
    print('\n[월별 검증]')
    print(f'  {"월":<10} {"부서수":>6} {"매출차이":>16} {"원가차이":>16} {"원가가감계정":>16}')
    for row in q:
        print(f'  {row[0]:<10} {row[1]:>6} {row[2]:>16,} {row[3]:>16,} {row[4]:>16,}')


if __name__ == '__main__':
    df = parse()
    if '--dry-run' in sys.argv:
        print('\n[dry-run] BQ 업로드 생략')
        print(df.to_string(max_rows=10))
    else:
        upload(df)
