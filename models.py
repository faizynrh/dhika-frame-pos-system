import mysql.connector

mydb = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    # database="dhika_frame"
)

my_cursor = mydb.cursor()

# my_cursor.execute("CREATE DATABASE dhika_frame")

my_cursor.execute("SHOW DATABASES")

my_cursor.execute("USE dhika_frame")

my_cursor.execute("SHOW TABLES")
for db in my_cursor:
    print(db)
