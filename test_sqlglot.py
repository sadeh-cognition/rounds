import sqlglot
from sqlglot import exp

sql = "SELECT pg_sleep(5);"
parsed = sqlglot.parse(sql)[0]
print(repr(parsed))
for func in parsed.find_all(exp.Func):
    print("Found Func:", func.name.upper())
