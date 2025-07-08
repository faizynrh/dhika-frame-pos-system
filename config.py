# import mysql.connector
# from mysql.connector import Error


# def connect_to_database():
#     try:
#         # Koneksi ke database MySQL
#         connection = mysql.connector.connect(
#             host="localhost",
#             user="root",
#             password="",
#             database="dhika_frame"
#         )

#         if connection.is_connected():
#             print("Koneksi ke database berhasil")
#             return connection
#     except Error as e:
#         print("Gagal terhubung ke database")
#         return None


# def check_connection():
#     connection = connect_to_database()
#     if connection:
#         try:
#             # cek apakah bisa menjalankan query sederhana
#             cursor = connection.cursor()
#             cursor.execute("select database();")
#             record = cursor.fetchone()
#             print(f"Anda tersambung ke database: {record[0]}")
#         finally:
#             cursor.close()
#             connection.close()
#             print("koneksi ke database ditutup")
#     else:
#         print("koneksi gagal,tidak ada database yang terhubung.")


# # panggil fungsi untuk mengecek koneksi
# check_connection()
