# -*- coding: utf-8 -*-
"""직접비/간접비 원본 → BigQuery raw 테이블 업로드 → BQ 쿼리로 FI_SM 생성

흐름:
  1) 직접비 N월.xlsx → Sales_Integration.FI_Direct_Cost   (원본 컬럼 그대로 + Year_Month)
  2) 간접비 N월.xlsx → Sales_Integration.FI_Indirect_Cost (원본 컬럼 그대로 + Year_Month)
  3) FI_Matching.xlsx 1/2번탭 → FI_Matching1 / FI_Matching2
  4) fi_sm_query.sql (CREATE OR REPLACE TABLE) 실행 → FI_SM
     → 이후에는 BQ 콘솔에서 fi_sm_query.sql만 다시 실행해도 FI_SM 재생성 가능

실행: python build_fi_sm.py            # 업로드 + 쿼리 실행 + 검증
      python build_fi_sm.py --dry-run  # 로컬 빌드/검증만 (BQ 접근 없음)

새 달 추가: MONTHS에 월 추가 후 재실행 (TOTAL 행과 합계 대조 검증 자동 수행)
"""
import sys
import warnings
import pandas as pd

warnings.filterwarnings('ignore')

MONTHS = [1, 2, 3, 4]
YEAR = 2026
DATASET = 'skin1004-319714.Sales_Integration'

FI_SM_SQL = f"""
CREATE OR REPLACE TABLE `{DATASET}.FI_SM` AS
WITH unified AS (
  -- 직접비: 보내는 쪽이 따로 없으므로 자기 코스트센터를 Sending_Cost_Center로
  SELECT
    Cost_Center_Class,
    Cost_Center AS Department,
    Cost_Center AS Sending_Cost_Center,
    Cost_Account,
    Amount,
    Year_Month
  FROM `{DATASET}.FI_Direct_Cost`

  UNION ALL

  -- 간접비: 분류='판매간접', 받는 코스트센터→Department, 배부받은금액→Amount
  SELECT
    '판매간접' AS Cost_Center_Class,
    Receiving_Cost_Center AS Department,
    Sending_Cost_Center,
    Cost_Account,
    Allocated_Amount AS Amount,
    Year_Month
  FROM `{DATASET}.FI_Indirect_Cost`
)
SELECT
  t.Cost_Center_Class,
  t.Department,
  t.Sending_Cost_Center,
  t.Cost_Account,
  t.Amount,
  t.Year_Month,
  IFNULL(m2.Account_Name, t.Cost_Account) AS Account_Name,
  m2.Main_Category,
  m2.Sub_Category,
  m2.Detail_Category,
  m1.Division,
  m1.Team,
  mc.Indirect_Cost_Class
FROM unified t
LEFT JOIN `{DATASET}.FI_Matching2` m2 ON t.Cost_Account = m2.Cost_Account
-- 본부/팀: 귀속(받는/보유) 코스트센터 기준
LEFT JOIN `{DATASET}.FI_Matching1` m1 ON t.Department = m1.Cost_Center
-- 간접비분류: 보내는 코스트센터 기준 (직접비는 자기 코스트센터 → '직접')
LEFT JOIN `{DATASET}.FI_Matching1` mc ON t.Sending_Cost_Center = mc.Cost_Center
"""

FI_FINAL_SM_SQL = f"""
CREATE OR REPLACE TABLE `{DATASET}.FI_Final_SM` AS

-- ① FI_Final 손익을 Department×월로 집계 → 롱 포맷 전개
WITH pnl AS (
  SELECT Department, Year_Month,
         SUM(Sales_Amount)     AS Sales_Amount,
         SUM(Cost_of_Sales)    AS Cost_of_Sales,
         SUM(Gross_Profit)     AS Gross_Profit,
         SUM(Operating_Income) AS Operating_Income
  FROM `{DATASET}.FI_Final`
  GROUP BY Department, Year_Month
),
-- FI_SM 간접비분류별 판관비 합계 (직접이익·공헌이익 파생에 사용)
sga_class AS (
  SELECT Department, Year_Month,
    SUM(CASE WHEN Indirect_Cost_Class = '직접'    THEN Amount ELSE 0 END) AS sga_direct,
    SUM(CASE WHEN Indirect_Cost_Class = '조직간접' THEN Amount ELSE 0 END) AS sga_org_indirect
  FROM `{DATASET}.FI_SM`
  GROUP BY Department, Year_Month
),
pnl_long AS (
  SELECT p.Department, p.Year_Month, item.name AS Item, item.amt AS Amount
  FROM pnl p
  LEFT JOIN sga_class sc ON p.Department = sc.Department AND p.Year_Month = sc.Year_Month,
  UNNEST([
    STRUCT('매출액'    AS name, p.Sales_Amount     AS amt),
    STRUCT('매출원가',          p.Cost_of_Sales),
    STRUCT('매출총이익',        p.Gross_Profit),
    STRUCT('직접이익',          p.Gross_Profit - COALESCE(sc.sga_direct, 0)),
    STRUCT('공헌이익',          p.Gross_Profit - COALESCE(sc.sga_direct, 0) - COALESCE(sc.sga_org_indirect, 0)),
    STRUCT('영업이익',          p.Operating_Income)
  ]) AS item
)

-- ② 판관비: FI_SM 계정 디테일 그대로
SELECT
  '판관비' AS Item_Class,
  s.Cost_Center_Class,
  s.Department,
  s.Sending_Cost_Center,
  s.Cost_Account,
  s.Amount,
  s.Year_Month,
  s.Account_Name,
  s.Main_Category,
  s.Sub_Category,
  s.Detail_Category,
  s.Division,
  s.Team,
  s.Indirect_Cost_Class
FROM `{DATASET}.FI_SM` s

UNION ALL

-- ③ 손익 항목: 매출액/매출원가/매출총이익/영업이익 (판관비는 FI_SM 행이 담당 — 중복 없음)
SELECT
  pl.Item AS Item_Class,
  CAST(NULL AS STRING) AS Cost_Center_Class,
  pl.Department,
  CAST(NULL AS STRING) AS Sending_Cost_Center,
  pl.Item AS Cost_Account,
  pl.Amount,
  pl.Year_Month,
  pl.Item AS Account_Name,
  pl.Item AS Main_Category,
  pl.Item AS Sub_Category,
  pl.Item AS Detail_Category,
  m1.Division,
  m1.Team,
  CAST(NULL AS STRING) AS Indirect_Cost_Class
FROM pnl_long pl
LEFT JOIN `{DATASET}.FI_Matching1` m1 ON pl.Department = m1.Cost_Center
"""

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
    m1.columns = ['Cost_Center', 'CC_Class', 'Indirect_Cost_Class', 'Division', 'Team']
    m1 = m1.dropna(subset=['Cost_Center'])
    m1['Cost_Center'] = m1['Cost_Center'].astype(str).str.strip()

    m2 = pd.read_excel('FI_Matching.xlsx', sheet_name='2', header=0)
    m2.columns = ['Cost_Account', 'Account_Name', 'Main_Category', 'Sub_Category', 'Detail_Category']
    m2 = m2.dropna(subset=['Cost_Account'])
    m2['Cost_Account'] = m2['Cost_Account'].astype(str).str.strip()
    m2['Account_Name'] = m2['Account_Name'].fillna(m2['Cost_Account'])
    return m1, m2


def load_direct(n):
    """직접비 N월: [코스트센터분류, 코스트센터, 원가계정과목, 공통여부, 금액] (헤더 2행째)"""
    f = f'직접비 {n}월.xlsx'
    df = pd.read_excel(f, sheet_name=0, header=1)
    df.columns = ['Cost_Center_Class', 'Cost_Center', 'Cost_Account', 'Common_YN', 'Amount']
    total = pd.to_numeric(df.loc[df['Cost_Center_Class'] == 'TOTAL', 'Amount'], errors='coerce').sum()
    df = df[(df['Cost_Center_Class'] != 'TOTAL') & df['Cost_Center'].notna()].copy()
    for c in ['Cost_Center_Class', 'Cost_Center', 'Cost_Account']:
        df[c] = df[c].astype(str).str.strip()
    df['Common_YN'] = pd.to_numeric(df['Common_YN'], errors='coerce').fillna(0).astype('int64')
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0).round(0).astype('int64')
    df['Year_Month'] = f'{YEAR}-{n:02d}'
    diff = df['Amount'].sum() - total
    log(f'[직접비 {n}월] rows={len(df)} sum={df["Amount"].sum():,.0f} TOTAL={total:,.0f} diff={diff:,.0f}')
    assert abs(diff) < 1, f'{f} 합계 불일치'
    return df


def load_indirect(n):
    """간접비 N월: [원가계정과목, 보내는 코스트센터, 보내는금액, 비율, 받는 코스트센터, 배부받은금액, 비율] (헤더 3행째)"""
    f = f'간접비 {n}월.xlsx'
    df = pd.read_excel(f, sheet_name=0, header=2)
    df.columns = ['Cost_Account', 'Sending_Cost_Center', 'Sent_Amount', 'Sent_Ratio',
                  'Receiving_Cost_Center', 'Allocated_Amount', 'Allocated_Ratio']
    total = pd.to_numeric(df.loc[df['Cost_Account'] == 'TOTAL', 'Allocated_Amount'], errors='coerce').sum()
    df = df[(df['Cost_Account'] != 'TOTAL') & df['Receiving_Cost_Center'].notna()].copy()
    for c in ['Cost_Account', 'Sending_Cost_Center', 'Receiving_Cost_Center']:
        df[c] = df[c].astype(str).str.strip()
    df['Sent_Amount'] = pd.to_numeric(df['Sent_Amount'], errors='coerce').fillna(0).round(0).astype('int64')
    df['Allocated_Amount'] = pd.to_numeric(df['Allocated_Amount'], errors='coerce').fillna(0).round(0).astype('int64')
    for c in ['Sent_Ratio', 'Allocated_Ratio']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0).astype('float64')
    df['Year_Month'] = f'{YEAR}-{n:02d}'
    diff = df['Allocated_Amount'].sum() - total
    log(f'[간접비 {n}월] rows={len(df)} sum={df["Allocated_Amount"].sum():,.0f} TOTAL={total:,.0f} diff={diff:,.0f}')
    assert abs(diff) < 1, f'{f} 합계 불일치'
    return df


def build():
    m1, m2 = load_matching()
    direct = pd.concat([load_direct(n) for n in MONTHS], ignore_index=True)
    indirect = pd.concat([load_indirect(n) for n in MONTHS], ignore_index=True)
    log(f'[로컬 검증] 직접비 {len(direct)}행 + 간접비 {len(indirect)}행, '
        f'예상 FI_SM 합계 {direct["Amount"].sum() + indirect["Allocated_Amount"].sum():,}')
    return direct, indirect, m1, m2


def bq_client():
    from google.cloud import bigquery
    from google.oauth2 import service_account
    import config
    creds = service_account.Credentials.from_service_account_file(config.BQ_KEY_PATH)
    return bigquery, bigquery.Client(project=config.BQ_PROJECT, credentials=creds)


def upload_table(bigquery, client, name, df):
    """CSV + 명시적 스키마 로드 (Parquet은 비ASCII 이슈 전력이 있어 CSV 위치 매핑 사용)"""
    import io
    def bq_type(dtype):
        s = str(dtype)
        if s.startswith('int'):
            return 'INTEGER'
        if s.startswith('float'):
            return 'FLOAT'
        return 'STRING'
    table_id = f'{DATASET}.{name}'
    client.delete_table(table_id, not_found_ok=True)
    jc = bigquery.LoadJobConfig(
        schema=[bigquery.SchemaField(c, bq_type(df[c].dtype)) for c in df.columns],
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        write_disposition='WRITE_TRUNCATE',
    )
    buf = io.BytesIO(df.to_csv(index=False).encode('utf-8'))
    client.load_table_from_file(buf, table_id, job_config=jc).result()
    t = client.get_table(table_id)
    log(f'[업로드] {table_id}: {t.num_rows}행, {len(t.schema)}컬럼')


def run(direct, indirect, m1, m2):
    bigquery, client = bq_client()
    upload_table(bigquery, client, 'FI_Direct_Cost', direct)
    upload_table(bigquery, client, 'FI_Indirect_Cost', indirect)
    upload_table(bigquery, client, 'FI_Matching1', m1)
    upload_table(bigquery, client, 'FI_Matching2', m2)

    log('[쿼리] CREATE OR REPLACE TABLE FI_SM 실행…')
    client.query(FI_SM_SQL).result()

    # 검증: 행수/합계 + 매칭 누락
    q = client.query(f'''
        SELECT COUNT(*) n, SUM(Amount) amt,
               COUNTIF(Main_Category IS NULL) no_acct,
               COUNTIF(Indirect_Cost_Class IS NULL) no_cc
        FROM `{DATASET}.FI_SM`''').result()
    r = list(q)[0]
    expected = direct['Amount'].sum() + indirect['Allocated_Amount'].sum()
    log(f'[FI_SM] {r[0]}행, 합계 {r[1]:,} (예상 {expected:,}, 일치={r[1]==expected}), '
        f'계정 미매칭 {r[2]}건, 코스트센터 미매칭 {r[3]}건')

    log('[쿼리] CREATE OR REPLACE TABLE FI_Final_SM 실행…')
    client.query(FI_FINAL_SM_SQL).result()

    # 정합 검증: 원시데이터 탭(FI_Final RAW)과 합계 대조
    q = client.query(f'''
        WITH f AS (SELECT SUM(Sales_Amount) sales, SUM(Cost_of_Sales) cogs,
                          SUM(Gross_Profit) gp, SUM(SG_and_A_Expenses) sga,
                          SUM(Operating_Income) oi
                   FROM `{DATASET}.FI_Final`),
             c AS (SELECT SUM(IF(Item_Class='매출액',   Amount, 0)) sales,
                          SUM(IF(Item_Class='매출원가',  Amount, 0)) cogs,
                          SUM(IF(Item_Class='매출총이익', Amount, 0)) gp,
                          SUM(IF(Item_Class='판관비',    Amount, 0)) sga,
                          SUM(IF(Item_Class='영업이익',  Amount, 0)) oi
                   FROM `{DATASET}.FI_Final_SM`)
        SELECT f.sales, c.sales, f.cogs, c.cogs, f.gp, c.gp, f.sga, c.sga, f.oi, c.oi FROM f, c''').result()
    r = list(q)[0]
    for i, name in enumerate(['매출액', '매출원가', '매출총이익', '판관비', '영업이익']):
        a, b = r[i*2], r[i*2+1]
        log(f'[정합] {name}: FI_Final={a:,} / FI_Final_SM={b:,} 일치={a==b}')


if __name__ == '__main__':
    with open('fi_sm_query.sql', 'w', encoding='utf-8') as fh:
        fh.write(FI_SM_SQL.strip() + '\n')
    with open('fi_final_sm_query.sql', 'w', encoding='utf-8') as fh:
        fh.write(FI_FINAL_SM_SQL.strip() + '\n')
    direct, indirect, m1, m2 = build()
    if '--dry-run' in sys.argv:
        log('[dry-run] BQ 업로드/쿼리 생략')
    else:
        run(direct, indirect, m1, m2)
    with open('_build_fi_sm_log.txt', 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(log_lines))
