import sqlite3
connection = sqlite3.connect("data/jobs.db")
row = connection.execute(
    "SELECT job_id, status, stage, error_message FROM jobs WHERE job_id=?",
    ("37accbc705c24d12b66cb4a4bff2f9b9",),
).fetchone()
print(row)
