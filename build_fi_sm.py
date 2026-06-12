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
  -- 직접비: 원본 컬럼 그대로 (보내는 코스트센터 없음 → NULL)
  SELECT
    Cost_Center_Class,
    Cost_Center AS Department,
    CAST(NULL AS STRING) AS Sending_Cost_Center,
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
-- 간접비분류: 보내는 코스트센터 기준 (직접비는 보내는 쪽이 없으므로 자기 코스트센터 → '직접')
LEFT JOIN `{DATASET}.FI_Matching1` mc ON COALESCE(t.Sending_Cost_Center, t.Department) = mc.Cost_Center
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


if __name__ == '__main__':
    with open('fi_sm_query.sql', 'w', encoding='utf-8') as fh:
        fh.write(FI_SM_SQL.strip() + '\n')
    direct, indirect, m1, m2 = build()
    if '--dry-run' in sys.argv:
        log('[dry-run] BQ 업로드/쿼리 생략')
    else:
        run(direct, indirect, m1, m2)
    with open('_build_fi_sm_log.txt', 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(log_lines))
