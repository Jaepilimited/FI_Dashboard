# AD (Active Directory)
AD_HOST = '172.16.1.x'
AD_PORT = 636
AD_DOMAIN = 'yourdomain'
AD_BIND_USER = r'yourdomain\binduser'
AD_BIND_PASS = 'your_ad_password'
AD_SEARCH_BASE = 'OU=Users,OU=Accounts,DC=ad,DC=yourdomain,DC=com'

# MariaDB
DB_HOST = '127.0.0.1'
DB_PORT = 3306
DB_NAME = 'your_db'
DB_USER = 'your_user'
DB_PASS = 'your_password'

# BigQuery
BQ_KEY_PATH = r'C:/path/to/your-service-account.json'
BQ_PROJECT = 'your-gcp-project-id'
BQ_TABLE = 'your-gcp-project.dataset.table'

# Flask
SECRET_KEY = 'change-this-to-a-random-secret-key'
