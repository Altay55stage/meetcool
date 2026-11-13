"""Provision only meetcool's private tables, using server environment credentials."""
import os
import time
import httpx


def setup():
    endpoint = os.environ['APPWRITE_ENDPOINT'].rstrip('/')
    database = os.environ.get('APPWRITE_DATABASE_ID', 'meetcool')
    headers = {'X-Appwrite-Project': os.environ['APPWRITE_PROJECT_ID'],
               'X-Appwrite-Key': os.environ['APPWRITE_API_KEY']}
    with httpx.Client(base_url=endpoint, headers=headers, timeout=20) as client:
        def ensure(path, body, get_path):
            existing = client.get(get_path)
            if existing.status_code == 200:
                print('Exists:', get_path)
                return
            if existing.status_code != 404:
                raise RuntimeError(f'Appwrite read failed: {existing.status_code}')
            response = client.post(path, json=body)
            if response.status_code not in (200, 201, 202):
                raise RuntimeError(f'Appwrite setup failed ({response.status_code}): {response.json().get("type", "unknown")}')
            print('Created:', get_path)
        ensure('/tablesdb', {'databaseId': database, 'name': 'meet’cool'}, f'/tablesdb/{database}')
        for table, fields in [('meetings', [('admin_token', 128), ('payload', 65535)]),
                              ('participants', [('meeting_id', 36), ('payload', 65535)])]:
            root = f'/tablesdb/{database}/tables/{table}'
            ensure(f'/tablesdb/{database}/tables', {'tableId': table, 'name': table,
                   'permissions': [], 'rowSecurity': True, 'enabled': False}, root)
            for key, size in fields:
                ensure(root+'/columns/string', {'key': key, 'size': size, 'required': True}, root+'/columns/'+key)
            for _ in range(20):
                columns = client.get(root+'/columns').json().get('columns', [])
                if len(columns) == len(fields) and all(c.get('status') == 'available' for c in columns):
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Appwrite columns are still provisioning; rerun setup shortly.')
            if table == 'participants':
                ensure(root+'/indexes', {'key': 'by_meeting', 'type': 'key', 'columns': ['meeting_id']}, root+'/indexes/by_meeting')


if __name__ == '__main__':
    setup()
