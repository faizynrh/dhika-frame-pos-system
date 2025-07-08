from config import *
from werkzeug.utils import redirect
from flask_mysqldb import MySQL
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_file,
    jsonify,
    Response,
    make_response,
)
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.units import inch
from datetime import datetime, timedelta
import pandas as pd
from io import BytesIO
import os
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
import barcode
from barcode.writer import ImageWriter
import io
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import inch
import textwrap
from datetime import datetime, date


app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = "many random bytes"

UPLOAD_FOLDER = "static/images"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

app.config["MYSQL_HOST"] = "localhost"
app.config["MYSQL_USER"] = "root"
app.config["MYSQL_PASSWORD"] = ""
app.config["MYSQL_DB"] = "dhika_frame"

mysql = MySQL(app)


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()

        if user and user[1] == password:
            session["id"] = user[0]
            session["username"] = user[1]
            session["role"] = user[4]
            if session["role"] == "superadmin":
                return redirect(url_for("dashboard"))
            elif session["role"] == "petugas":
                return redirect(url_for("kategori_barang"))
            elif session["role"] == "kasir":
                return redirect(url_for("transaksibc"))
        else:
            flash("Username atau Password Salah", "danger")
    return render_template("login.html")


# menyediakan variabel untuk semua template
@app.context_processor
def inject_user_and_greeting():
    if "username" in session:
        username = session["username"]
        hak_akses = session["role"]

        current_time = datetime.now()
        current_hour = current_time.hour

        if 4 <= current_hour < 10:
            greeting = "Selamat Pagi"
        elif 10 <= current_hour < 15:
            greeting = "Selamat Siang"
        elif 15 <= current_hour < 18:
            greeting = "Selamat Sore"
        else:
            greeting = "Selamat Malam"

        return {"username": username, "hak_akses": hak_akses, "greeting": greeting}
    return {}


@app.route("/dashboard")
def dashboard():
    username = session["username"]
    filter_type = request.args.get("filter_type", "day")
    cur = mysql.connection.cursor()

    cur.execute("SELECT SUM(total_harga) FROM transaksi")
    total_sales = cur.fetchone()[0] or 0

    cur.execute("SELECT SUM(stok) FROM produk")
    total_stok = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM users")
    total_akun = cur.fetchone()[0] or 0
    labels = []
    data = []
    if filter_type == "day":
        current_hour = datetime.now().hour
        labels = [str(i) for i in range(current_hour + 1)]
        data = [0] * (current_hour + 1)

        cur.execute(
            """
                SELECT HOUR(tanggal_transaksi) AS jam, SUM(total_harga) AS total_penjualan
                FROM transaksi
                WHERE DATE(tanggal_transaksi) = CURDATE()
                GROUP BY jam
                ORDER BY jam ASC
            """
        )
        penjualan_data = cur.fetchall()

        # Fill the data for each hour, set sales if exists, otherwise leave as 0
        for row in penjualan_data:
            jam = row[0]
            total_penjualan = row[1]
            if jam <= current_hour:
                data[jam] = total_penjualan

    elif filter_type == "week":
        # Dapatkan tanggal untuk 7 hari terakhir
        labels = []
        data = [0] * 7

        # Generate labels untuk 7 hari terakhir
        for i in range(6, -1, -1):
            date = datetime.now() - timedelta(days=i)
            labels.append(date.strftime("%A"))  # Nama hari

        # Query untuk mendapatkan data 7 hari terakhir
        cur.execute(
            """
                SELECT 
                    DATE(tanggal_transaksi) as tanggal,
                    DAYNAME(tanggal_transaksi) as hari,
                    SUM(total_harga) as total_penjualan
                FROM transaksi
                WHERE tanggal_transaksi >= DATE(NOW()) - INTERVAL 6 DAY
                AND tanggal_transaksi <= DATE(NOW())
                GROUP BY tanggal, hari
                ORDER BY tanggal ASC
                """
        )
        penjualan_data = cur.fetchall()

        # Buat dictionary untuk memetakan nama hari ke total penjualan
        hari_map = {}
        for row in penjualan_data:
            hari_map[row[1]] = row[
                2
            ]  # row[1] adalah nama hari, row[2] adalah total_penjualan

        # Isi data sesuai dengan urutan hari
        for i, hari in enumerate(labels):
            if hari in hari_map:
                data[i] = hari_map[hari]
            else:
                data[i] = 0

    elif filter_type == "month":
        today = datetime.today()
        total_days_in_month = (today.replace(day=28) + timedelta(days=4)).day
        labels = [str(i) for i in range(1, total_days_in_month + 1)]
        data = [0] * total_days_in_month

        cur.execute(
            """
                SELECT DAY(tanggal_transaksi) AS tanggal, SUM(total_harga) AS total_penjualan
                FROM transaksi
                WHERE MONTH(tanggal_transaksi) = MONTH(CURDATE())
                AND YEAR(tanggal_transaksi) = YEAR(CURDATE())
                GROUP BY tanggal
                ORDER BY tanggal ASC
            """
        )
        penjualan_data = cur.fetchall()

        # Fill the data for each day, set sales if exists, otherwise leave as 0
        for row in penjualan_data:
            tanggal = row[0]
            total_penjualan = row[1]
            data[tanggal - 1] = total_penjualan

    # Query recent history
    cur.execute(
        """
                SELECT 
                    history.user_id,
                    CASE 
                        WHEN history.table_name = 'produk' THEN 'barang'
                        ELSE history.table_name 
                    END as table_name,
                    history.aksi,
                    history.timestamp,
                    users.username
                FROM history
                JOIN users ON history.user_id = users.id
                ORDER BY history.timestamp DESC
                LIMIT 3
                """
    )
    history = cur.fetchall()

    cur.close()

    return render_template(
        "dashboard.html",
        username=username,
        active_page="dashboard",
        omset=total_sales,
        stok=total_stok,
        akun=total_akun,
        bulan=labels,
        penjualan=data,
        history=history,
        filter_type=filter_type,
    )


@app.route("/dashboard_data")
def dashboard_data():
    filter_type = request.args.get("filter_type", "day")
    labels = []
    data = []

    # Koneksi ke database
    cur = mysql.connection.cursor()

    if filter_type == "day":
        # 12 jam terakhir dari sekarang
        end_hour = datetime.now().hour
        start_hour = end_hour - 11

        labels = [f"{(start_hour + i) % 24:02d}:00" for i in range(12)]
        data = [0] * 12

        cur.execute(
            """
            SELECT HOUR(tanggal_transaksi) AS jam, SUM(total_harga) AS total_penjualan
            FROM transaksi
            WHERE tanggal_transaksi >= NOW() - INTERVAL 12 HOUR
            GROUP BY jam
            ORDER BY jam ASC
            """
        )
        penjualan_data = cur.fetchall()
        for row in penjualan_data:
            jam = row[0]
            total_penjualan = row[1]
            index = (jam - start_hour) % 12
            data[index] = total_penjualan

    elif filter_type == "week":
        # 7 hari terakhir dari hari ini
        labels = []
        data = [0] * 7

        hari = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
        for i in range(6, -1, -1):
            date = datetime.now() - timedelta(days=i)
            labels.append(hari[date.weekday()])

        cur.execute(
            """
            SELECT DATE(tanggal_transaksi) as tanggal, SUM(total_harga) as total_penjualan
            FROM transaksi
            WHERE tanggal_transaksi >= DATE(NOW()) - INTERVAL 6 DAY
            GROUP BY tanggal
            ORDER BY tanggal ASC
            """
        )
        penjualan_data = cur.fetchall()

        date_sales = {row[0]: row[1] for row in penjualan_data}

        for i, date in enumerate(reversed(range(7))):
            current_date = datetime.now().date() - timedelta(days=date)
            if current_date in date_sales:
                data[i] = date_sales[current_date]

    elif filter_type == "month":
        # Dari tanggal 1 hingga hari ini
        today = datetime.today()
        labels = [str(i) for i in range(1, today.day + 1)]
        data = [0] * today.day

        cur.execute(
            """
            SELECT DAY(tanggal_transaksi) AS tanggal, SUM(total_harga) AS total_penjualan
            FROM transaksi
            WHERE MONTH(tanggal_transaksi) = MONTH(CURDATE()) AND YEAR(tanggal_transaksi) = YEAR(CURDATE())
            GROUP BY tanggal
            ORDER BY tanggal ASC
            """
        )
        penjualan_data = cur.fetchall()
        for row in penjualan_data:
            tanggal = row[0]
            total_penjualan = row[1]
            data[tanggal - 1] = total_penjualan

    elif filter_type == "year":
        # Dari Januari hingga bulan ini
        labels = [
            "Januari",
            "Februari",
            "Maret",
            "April",
            "Mei",
            "Juni",
            "Juli",
            "Agustus",
            "September",
            "Oktober",
            "November",
            "Desember",
        ][: datetime.now().month]
        data = [0] * len(labels)

        cur.execute(
            """
            SELECT MONTH(tanggal_transaksi) AS bulan, SUM(total_harga) AS total_penjualan
            FROM transaksi
            WHERE YEAR(tanggal_transaksi) = YEAR(CURDATE())
            GROUP BY bulan
            ORDER BY bulan ASC
            """
        )
        penjualan_data = cur.fetchall()
        for row in penjualan_data:
            bulan = row[0]
            total_penjualan = row[1]
            data[bulan - 1] = total_penjualan

    cur.close()

    return jsonify({"labels": labels, "data": data})


@app.route("/kategori_barang", methods=["GET", "POST"])
def kategori_barang():
    # Buat koneksi ke database
    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM kategori")

    kategori_data = cur.fetchall()

    # Tutup koneksi
    cur.close()

    # Kirim data ke template
    return render_template(
        "kategori_barang.html", kategori=kategori_data, active_page="kategori_barang"
    )


@app.route("/tambah_kategori", methods=["POST"])
def tambah_kategori():
    nama_kategori = request.form["nama_kategori"]
    user_id = session.get("id")

    cur = mysql.connection.cursor()

    cur.execute(
        """
        INSERT INTO kategori (nama_kategori)
        VALUES (%s)
        """,
        (nama_kategori,),
    )

    kategori_id = cur.lastrowid

    aksi = f"Menambah kategori '{nama_kategori}'"
    cur.execute(
        """
        INSERT INTO history (user_id, table_name, aksi)
        VALUES (%s, 'kategori', %s)
        """,
        (user_id, aksi),
    )

    mysql.connection.commit()

    cur.close()

    flash("Data berhasil disubmit!", "success")
    return redirect(url_for("kategori_barang"))


@app.route("/hapus_kategori/<int:kategori_id>", methods=["POST"])
def hapus_kategori(kategori_id):
    user_id = session.get("id")
    cur = mysql.connection.cursor()

    # Ambil nama kategori sebelum dihapus untuk log history
    cur.execute("SELECT nama_kategori FROM kategori WHERE id = %s", (kategori_id,))
    result = cur.fetchone()

    nama_kategori = result[0]

    # Cek apakah kategori digunakan di tabel lain
    cur.execute(
        "SELECT COUNT(*) as count FROM produk WHERE kategori_id = %s", (kategori_id,)
    )
    product_count = cur.fetchone()[0]

    if product_count > 0:
        flash(
            f"Kategori '{nama_kategori}' tidak dapat dihapus karena masih digunakan oleh {product_count} produk. Harap ubah atau hapus produk terkait terlebih dahulu.",
            "error",
        )
        cur.close()
        return redirect(url_for("kategori_barang"))

    cur.execute("DELETE FROM kategori WHERE id = %s", (kategori_id,))

    aksi = f"Menghapus kategori '{nama_kategori}'"
    cur.execute(
        "INSERT INTO history (user_id, table_name, aksi) VALUES (%s, 'kategori', %s)",
        (user_id, aksi),
    )

    mysql.connection.commit()
    cur.close()

    flash(f"Kategori '{nama_kategori}' berhasil dihapus!", "success")
    return redirect(url_for("kategori_barang"))

    @app.route("/edit_kategori/<int:kategori_id>", methods=["POST"])
    def edit_kategori(kategori_id):
        user_id = session.get("id")
        nama_kategori = request.form["nama_kategori"]

        cur = mysql.connection.cursor()

        # Ambil nama kategori lama
        cur.execute("SELECT nama_kategori FROM kategori WHERE id = %s", (kategori_id,))
        nama_kategori_lama = cur.fetchone()[0]

        # Update kategori di database
        cur.execute(
            "UPDATE kategori SET nama_kategori = %s WHERE id = %s",
            (nama_kategori, kategori_id),
        )

        # Tambahkan ke tabel history
        aksi = (
            f"Mengubah kategori dari '{nama_kategori_lama}' menjadi '{nama_kategori}'"
        )
        cur.execute(
            "INSERT INTO history (user_id, table_name, aksi) VALUES (%s, 'kategori', %s)",
            (user_id, aksi),
        )

        mysql.connection.commit()
        cur.close()

        flash("Kategori berhasil diubah!", "success")
        return redirect(url_for("kategori_barang"))


@app.route("/search_kategori", methods=["GET"])
def search_kategori():
    query = request.args.get("query", "")
    cur = mysql.connection.cursor()

    cur.execute(
        "SELECT id, nama_kategori FROM kategori WHERE nama_kategori LIKE %s",
        (f"%{query}%",),
    )
    kategori = cur.fetchall()

    cur.close()

    # Return data sebagai JSON
    return jsonify([{"id": k[0], "nama_kategori": k[1]} for k in kategori])


@app.route("/daftar_barang", methods=["GET"])
def daftar_barang():
    query = request.args.get("query", "")

    cur = mysql.connection.cursor()
    cur.execute("SELECT id, nama_kategori FROM kategori")
    kategori_data = cur.fetchall()

    if query:
        search_query = f"%{query}%"
        cur.execute(
            """
            SELECT p.id, p.kode_barang, p.nama_produk, p.kategori_id, p.deskripsi, p.harga, p.stok, k.nama_kategori
            FROM produk p
            JOIN kategori k ON p.kategori_id = k.id
            WHERE p.nama_produk LIKE %s OR p.deskripsi LIKE %s OR CAST(p.stok AS CHAR) LIKE %s
        """,
            (search_query, search_query, search_query),
        )
    else:
        cur.execute(
            """
            SELECT p.id, p.kode_barang, p.nama_produk, p.kategori_id, p.deskripsi, p.harga, p.stok, k.nama_kategori
            FROM produk p
            JOIN kategori k ON p.kategori_id = k.id
        """
        )

    produk_data = cur.fetchall()
    cur.close()

    return render_template(
        "daftar_barang.html",
        produk=produk_data,
        kategori=kategori_data,
        active_page="daftar_barang",
        search_query=query,
    )


@app.route("/laporan_barang", methods=["GET"])
def laporan_barang():
    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT p.id, p.kode_barang, p.nama_produk, p.kategori_id, p.deskripsi, p.harga, p.stok, k.nama_kategori
        FROM produk p
        JOIN kategori k ON p.kategori_id = k.id
        ORDER BY p.nama_produk
    """
    )
    barang = cur.fetchall()
    cur.close()

    return render_template("laporan_barang.html", barang=barang, now=datetime.now)


@app.route("/tambah_stok", methods=["POST"])
def tambah_stok():
    produk_id = request.form.get("id")
    jumlah_stok = request.form["tambah_stok"]
    user_id = session.get("id")

    cur = mysql.connection.cursor()

    cur.execute(
        """
        UPDATE produk SET stok = stok + %s WHERE id = %s
        """,
        (jumlah_stok, produk_id),
    )

    # Ambil nama produk untuk log
    cur.execute("SELECT nama_produk FROM produk WHERE id = %s", (produk_id,))
    nama_produk = cur.fetchone()[0]

    # Tambahkan ke tabel history
    aksi = f"Menambah stok '{nama_produk}' sebanyak {jumlah_stok}"
    cur.execute(
        """
        INSERT INTO history (user_id, table_name, aksi)
        VALUES (%s, 'produk', %s)
        """,
        (user_id, aksi),
    )

    # Commit perubahan
    mysql.connection.commit()
    cur.close()

    flash("Stok berhasil ditambahkan!", "success")
    return redirect(url_for("daftar_barang"))


@app.route("/tambah_barang", methods=["POST"])
def tambah_barang():
    user_id = session.get("id")
    kode_barang = request.form["kode_barang"]
    nama_produk = request.form["nama_produk"]
    kategori_id = request.form["kategori_id"]
    deskripsi = request.form["deskripsi"]
    harga = request.form["harga"]
    stok = 0

    cur = mysql.connection.cursor()

    # Cek apakah kode_barang sudah ada
    cur.execute("SELECT COUNT(*) FROM produk WHERE kode_barang = %s", (kode_barang,))
    if cur.fetchone()[0] > 0:
        flash("Kode barang sudah ada!", "danger")
        cur.close()
        return redirect(url_for("daftar_barang"))

    cur.execute(
        """
        INSERT INTO produk (kode_barang, nama_produk, kategori_id, deskripsi, harga, stok)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (kode_barang, nama_produk, kategori_id, deskripsi, harga, stok),
    )

    aksi = f"Menambah barang '{nama_produk}'"
    cur.execute(
        "INSERT INTO history (user_id, table_name, aksi) VALUES (%s, 'produk', %s)",
        (user_id, aksi),
    )

    mysql.connection.commit()
    cur.close()

    flash("Data berhasil disubmit!", "success")
    return redirect(url_for("daftar_barang"))


@app.route("/cek_kode_barang", methods=["POST"])
def cek_kode_barang():
    kode_barang = request.form.get("kode_barang")

    cur = mysql.connection.cursor()

    cur.execute("SELECT COUNT(*) FROM produk WHERE id = %s", (kode_barang,))
    result = cur.fetchone()

    if result[0] > 0:
        return jsonify({"exists": True})
    else:
        return jsonify({"exists": False})


@app.route("/hapus_produk/<int:produk_id>", methods=["POST"])
def hapus_produk(produk_id):
    user_id = session.get("id")
    cur = mysql.connection.cursor()

    # Ambil nama produk sebelum dihapus untuk log history
    cur.execute("SELECT nama_produk FROM produk WHERE id = %s", (produk_id,))
    nama_produk = cur.fetchone()[0]

    # Hapus produk
    cur.execute("DELETE FROM produk WHERE id = %s", (produk_id,))

    # Tambahkan ke tabel history
    aksi = f"Menghapus barang '{nama_produk}'"
    cur.execute(
        "INSERT INTO history (user_id, table_name, aksi) VALUES (%s, 'produk', %s)",
        (user_id, aksi),
    )

    mysql.connection.commit()
    cur.close()

    flash("Data berhasil dihapus!", "success")
    return redirect(url_for("daftar_barang"))


@app.route("/edit_produk/<int:produk_id>", methods=["POST"])
def edit_produk(produk_id):
    user_id = session.get("id")
    nama_produk = request.form["nama_produk"]
    kategori_id = request.form["kategori_id"]
    deskripsi = request.form["deskripsi"]
    harga = request.form["harga"]
    stok = request.form["stok"]

    try:
        cur = mysql.connection.cursor()

        # Ambil data produk lama sebelum diupdate
        cur.execute("SELECT * FROM produk WHERE id = %s", (produk_id,))
        old_produk = cur.fetchone()

        # Update produk di database
        cur.execute(
            """UPDATE produk SET nama_produk=%s, kategori_id=%s, deskripsi=%s, harga=%s, stok=%s
               WHERE id=%s""",
            (nama_produk, kategori_id, deskripsi, harga, stok, produk_id),
        )

        # Tambahkan ke tabel history
        aksi = f"Mengubah barang '{old_produk[2]}'"
        cur.execute(
            "INSERT INTO history (user_id, table_name, aksi) VALUES (%s, 'produk', %s)",
            (user_id, aksi),
        )

        mysql.connection.commit()
        flash("Produk berhasil diubah!", "success")

    except Exception as e:
        print(f"Error updating product: {e}")
        mysql.connection.rollback()
        flash("Terjadi kesalahan saat mengubah produk!", "danger")

    finally:
        cur.close()

    return redirect(url_for("daftar_barang"))


@app.route("/search_produk", methods=["GET"])
def search_produk():
    query = request.args.get("query", "")

    cur = mysql.connection.cursor()
    search_query = f"%{query}%"

    # Query untuk mencari berdasarkan nama, deskripsi, dan stok
    cur.execute(
        """
        SELECT * FROM produk
        WHERE nama_produk LIKE %s OR deskripsi LIKE %s OR stok LIKE %s
    """,
        (search_query, search_query, search_query),
    )

    results = cur.fetchall()
    cur.close()

    # Format hasil sebagai JSON
    produk_list = [
        {
            "id": produk[0],
            "kode_barang": produk[1],
            "nama_produk": produk[2],
            "kategori_id": produk[3],
            "deskripsi": produk[4],
            "harga": produk[5],
            "stok": produk[6],
            "gambar": produk[7],
        }
        for produk in results
    ]

    return jsonify(produk_list)


@app.route("/generate-barcode", methods=["GET"])
def generate_barcode():
    produk_id = request.args.get("id")  # Ambil id dari query string

    if not produk_id:
        return "ID produk tidak ditemukan", 400

    cur = mysql.connection.cursor()
    cur.execute("SELECT kode_barang FROM produk WHERE id = %s", (produk_id,))
    result = cur.fetchone()

    if result:
        kode = str(result[0])  # Akses kode_barang menggunakan indeks
    else:
        kode = "123456"  # ID default jika tidak ada hasil dari query

    barcode_format = barcode.get_barcode_class("code128")
    my_barcode = barcode_format(kode, writer=ImageWriter())

    buffer = io.BytesIO()
    my_barcode.write(buffer)
    buffer.seek(0)

    return send_file(buffer, mimetype="image/png")


@app.route("/generate-barcode-image", methods=["GET"])
def generate_barcode_image():
    try:
        kode_barang = request.args.get("kode_barang")

        if not kode_barang:
            return "Missing 'kode_barang' parameter", 400

        barcode_dir = "barcode"
        os.makedirs(barcode_dir, exist_ok=True)

        barcode_image_path = os.path.join(barcode_dir, f"{kode_barang}.png")

        if not os.path.exists(barcode_image_path):
            code128 = barcode.get("code128", kode_barang, writer=ImageWriter())
            code128.save(barcode_image_path[:-4])

        if os.path.exists(barcode_image_path):
            with open(barcode_image_path, "rb") as f:
                image_data = f.read()
            return Response(image_data, mimetype="image/png")
        else:
            return "File not found", 404

    except Exception as e:
        return f"Internal Server Error: {e}", 500


@app.route("/print-barcode")
def print_barcode():
    return render_template("print-barcode.html")


# @app.route("/get_products/<int:kategori_id>", methods=["GET"])
# def get_products(kategori_id):
#     # Buat koneksi ke database
#     cur = mysql.connection.cursor()
#     cur.execute(
#         "SELECT id, nama_produk FROM produk WHERE kategori_id = %s", (kategori_id,)
#     )
#     produk_data = cur.fetchall()
#     cur.close()

#     # Mengembalikan data produk dalam bentuk JSON
#     return jsonify(produk_data)


@app.route("/kelola_akun", methods=["GET"])
def kelola_akun():
    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM users")

    users_data = cur.fetchall()

    cur.close()

    return render_template(
        "kelola_akun.html", users=users_data, active_page="kelola_akun"
    )


@app.route("/tambah_akun", methods=["POST"])
def tambah_akun():
    username = request.form["username"]
    email = request.form["email"]
    password = request.form["password"]
    role = request.form["role"]

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    existing_user = cur.fetchone()

    if existing_user:
        cur.close()
        flash("Email sudah terdaftar. Silakan gunakan email lain.", "danger")
        return redirect(url_for("kelola_akun"))

    cur.execute(
        """INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)""",
        (username, email, password, role),
    )

    mysql.connection.commit()

    cur.close()

    flash("Data berhasil disubmit!", "success")

    return redirect(url_for("kelola_akun"))


@app.route("/edit_akun/<int:akun_id>", methods=["POST"])
def edit_akun(akun_id):
    username = request.form["username"]
    email = request.form["email"]
    password = request.form["password"]
    role = request.form["role"]

    cur = mysql.connection.cursor()

    cur.execute(
        """
        UPDATE users SET username=%s, email=%s, password=%s, role=%s
                    WHERE id=%s""",
        (username, email, password, role, akun_id),
    )

    mysql.connection.commit()

    cur.close()
    flash("Data berhasil diubah!", "success")

    return redirect(url_for("kelola_akun"))


@app.route("/hapus_akun/<int:akun_id>", methods=["POST"])
def hapus_akun(akun_id):
    cur = mysql.connection.cursor()

    cur.execute("DELETE FROM users WHERE id = %s", (akun_id,))

    mysql.connection.commit()

    cur.close()

    return redirect(url_for("kelola_akun"))


@app.route("/search_users", methods=["GET"])
def search_users():
    query = request.args.get("query", "")

    cur = mysql.connection.cursor()
    search_query = f"%{query}%"
    cur.execute(
        "SELECT * FROM users WHERE username LIKE %s OR email LIKE %s OR role LIKE %s",
        (search_query, search_query, search_query),
    )
    results = cur.fetchall()
    cur.close()

    # Format hasil sebagai JSON
    users_list = [
        {
            "id": user[0],
            "username": user[1],
            "password": user[2],
            "email": user[3],
            "role": user[4],
        }
        for user in results
    ]
    return jsonify(users_list)


# @app.route("/transaksi")
# def transaksi():
#     if "username" in session:  # Check if the user is logged in
#         # Assuming 'username' is the user's ID
#         user_id = session.get("username")
#         cur = mysql.connection.cursor()

#         # Query to get all the product data
#         cur.execute("SELECT * FROM produk WHERE stok > 0")
#         produk_data = cur.fetchall()

#         # Get the keranjang data along with product names
#         query_keranjang = """
#             SELECT k.*, p.nama_produk
#             FROM keranjang k
#             JOIN produk p ON k.produk_id = p.id
#             WHERE k.user_id = %s
#         """
#         cur.execute(query_keranjang, (user_id,))
#         keranjang_data = cur.fetchall()

#         # Calculate the total amount from subtotal
#         # Adjust index based on the structure
#         total = sum(item[5] for item in keranjang_data)

#         # Close the cursor
#         cur.close()

#         # Pass the user_id, product data, keranjang data, and total to the template
#         return render_template(
#             "transaksi1.html",
#             active_page="transaksi",
#             produk=produk_data,
#             user_id=user_id,
#             keranjang=keranjang_data,
#             total=total,
#         )
#     else:
#         # Redirect to login if the user is not logged in
#         return redirect(url_for("login"))


# @app.route("/keranjang", methods=["POST"])
# def keranjang():
#     username = request.form.get("username")
#     # This corresponds to the 'id' in produk table
#     produk_id = request.form.get("produk_id")
#     harga = request.form.get("harga")  # Price from form data
#     jumlah = 1  # Default quantity to add
#     subtotal = int(harga) * jumlah

#     # Create a connection to the database
#     cur = mysql.connection.cursor()

#     # Check if the product already exists in the user's cart
#     query_check = "SELECT jumlah FROM keranjang WHERE user_id = %s AND produk_id = %s"
#     cur.execute(query_check, (username, produk_id))
#     result = cur.fetchone()

#     # Check available stock in the produk table
#     # Adjusted to match your column name
#     query_stock_check = "SELECT stok FROM produk WHERE id = %s"
#     cur.execute(query_stock_check, (produk_id,))
#     stock_result = cur.fetchone()
#     available_stock = stock_result[0] if stock_result else 0

#     # Return an error response if stock is insufficient

#     if result:
#         # If the product exists, update the quantity and subtotal
#         existing_jumlah = result[0]
#         new_jumlah = existing_jumlah + 1
#         new_subtotal = int(harga) * new_jumlah

#         # Update the keranjang table
#         query_update = "UPDATE keranjang SET jumlah = %s, subtotal = %s WHERE user_id = %s AND produk_id = %s"
#         cur.execute(query_update, (new_jumlah, new_subtotal, username, produk_id))
#     else:
#         # If the product does not exist, insert a new record
#         query_insert = "INSERT INTO keranjang (user_id, produk_id, harga, jumlah, subtotal) VALUES (%s, %s, %s, %s, %s)"
#         cur.execute(query_insert, (username, produk_id, harga, jumlah, subtotal))

#     # Reduce the stock in the produk table
#     new_stock = available_stock - 1  # Decrease stock by 1 for each addition to the cart
#     # Adjusted to match your column name
#     query_update_stock = "UPDATE produk SET stok = %s WHERE id = %s"
#     cur.execute(query_update_stock, (new_stock, produk_id))

#     # Commit changes and close the connection
#     mysql.connection.commit()
#     cur.close()

#     # Redirect back to the transaction page after adding to the cart
#     return redirect(url_for("transaksi"))


@app.route("/transaksibc")
def transaksibc():
    user_id = session.get("id")
    cur = mysql.connection.cursor()

    query_keranjang = """
            SELECT k.*, p.nama_produk
            FROM keranjang k
            JOIN produk p ON k.produk_id = p.id
            WHERE k.user_id = %s
        """
    cur.execute(query_keranjang, (user_id,))
    keranjang_data = cur.fetchall()

    total = sum(item[5] for item in keranjang_data)

    cur = mysql.connection.cursor()
    cur.execute("SELECT id_transaksi FROM transaksi ORDER BY id_transaksi DESC LIMIT 1")
    last_transaction = cur.fetchone()

    if last_transaction:
        last_id = last_transaction[0]
        last_number = int(last_id[3:])  # Ambil angka setelah 'TRS'
        new_number = last_number + 1  # Tambah 1
    else:
        new_number = 1  # Mulai dari 1 jika tidak ada transaksi sebelumnya

    new_id = f"TRS{new_number:04}"  # Format ID baru

    cur.close()

    return render_template(
        "transaksi_barcode.html",
        active_page="transaksibc",
        user_id=user_id,
        keranjang=keranjang_data,
        total=total,
        id_transaksi=new_id,
    )


@app.route("/tambah_keranjangbc", methods=["POST"])
def tambah_keranjangbc():
    if request.method == "POST":
        kode_input = request.form.get("kode_barang")

        if kode_input:
            if "x" in kode_input:
                jumlah_str, kode_barang = kode_input.split("x")
                jumlah = int(jumlah_str.strip())  # Ambil jumlah
            else:
                kode_barang = kode_input.strip()
                jumlah = 1  # Default jumlah 1 jika tidak ada 'x'

            cur = mysql.connection.cursor()
            cur.execute(
                "SELECT id, harga, stok FROM produk WHERE kode_barang = %s",
                (kode_barang,),
            )
            produk = cur.fetchone()

            if produk:
                produk_id = produk[0]
                harga_produk = produk[1]
                stok_produk = produk[2]

                if stok_produk >= jumlah:
                    user_id = session.get("id")
                    cur.execute(
                        "SELECT jumlah FROM keranjang WHERE user_id = %s AND produk_id = %s",
                        (user_id, produk_id),
                    )
                    existing_item = cur.fetchone()

                    if existing_item:
                        jumlah_sekarang = existing_item[0]
                        jumlah_baru = jumlah_sekarang + jumlah
                        subtotal_baru = harga_produk * jumlah_baru

                        cur.execute(
                            "UPDATE keranjang SET jumlah = %s, subtotal = %s WHERE user_id = %s AND produk_id = %s",
                            (jumlah_baru, subtotal_baru, user_id, produk_id),
                        )
                    else:
                        subtotal = harga_produk * jumlah  # Hitung subtotal

                        cur.execute(
                            "INSERT INTO keranjang (user_id, produk_id, harga, jumlah, subtotal) VALUES (%s, %s, %s, %s, %s)",
                            (user_id, produk_id, harga_produk, jumlah, subtotal),
                        )

                    cur.execute(
                        "UPDATE produk SET stok = stok - %s WHERE id = %s",
                        (jumlah, produk_id),
                    )

                    mysql.connection.commit()
                    cur.close()
                else:
                    flash(
                        "Stok tidak cukup untuk menambahkan barang tersebut!", "danger"
                    )
            else:
                flash("Kode barang tidak ditemukan.", "danger")
        else:
            flash("Kode barang tidak boleh kosong.", "warning")

    return redirect(url_for("transaksibc"))


@app.route("/hapuskeranjang/<int:id>", methods=["POST"])
def hapuskeranjang(id):
    cur = mysql.connection.cursor()

    cur.execute("SELECT jumlah, produk_id FROM keranjang WHERE id = %s", (id,))
    result = cur.fetchone()

    if result:
        qty = result[0]
        produk_id = result[1]

        cur.execute("SELECT harga FROM produk WHERE id = %s", (produk_id,))
        harga_result = cur.fetchone()
        harga = harga_result[0] if harga_result else 0

        if qty > 1:
            cur.execute("UPDATE keranjang SET jumlah = jumlah - 1 WHERE id = %s", (id,))
            cur.execute("UPDATE produk SET stok = stok + 1 WHERE id = %s", (produk_id,))

            new_qty = qty - 1
            subtotal = harga * new_qty

            cur.execute(
                "UPDATE keranjang SET subtotal = %s WHERE id = %s", (subtotal, id)
            )
        else:
            cur.execute("DELETE FROM keranjang WHERE id = %s", (id,))
            cur.execute("UPDATE produk SET stok = stok + 1 WHERE id = %s", (produk_id,))

    mysql.connection.commit()
    cur.close()
    return redirect(url_for("transaksibc"))


@app.route("/tambah_transaksi", methods=["POST"])
def tambah_transaksi():
    user_id = session.get("id")
    id_transaksi = request.form["id_transaksi"]
    total_harga = request.form["total"]
    bayar = request.form["bayar"]
    kembali = request.form["kembali"]
    cur = mysql.connection.cursor()
    # Insert Transaksi
    insert_transaksi_query = """
        INSERT INTO transaksi (id_transaksi, user_id, total_harga, bayar, kembali)
        VALUES (%s, %s, %s, %s, %s)
    """
    cur.execute(
        insert_transaksi_query, (id_transaksi, user_id, total_harga, bayar, kembali)
    )
    transaksi_id = cur.lastrowid
    # Insert detail transaksi
    query_keranjang = "SELECT * FROM keranjang WHERE user_id = %s"
    cur.execute(query_keranjang, (user_id,))
    keranjang_data = cur.fetchall()
    for item in keranjang_data:
        produk_id = item[2]
        jumlah = item[4]
        harga = item[5]
        insert_detail_query = """
            INSERT INTO detailtransaksi (transaksi_id, produk_id, jumlah, harga)
            VALUES (%s, %s, %s, %s)
        """
        cur.execute(insert_detail_query, (transaksi_id, produk_id, jumlah, harga))
    cur.execute("DELETE FROM keranjang WHERE user_id = %s", (user_id,))
    mysql.connection.commit()
    cur.close()
    # Get the PDF receipt as a BytesIO stream
    pdf_stream = generate_receipt(id_transaksi, transaksi_id, user_id)
    # Kirim PDF sebagai respons dengan header yang sesuai
    response = make_response(pdf_stream.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f"inline; filename=receipt_{id_transaksi}.pdf"
    )
    # Send the PDF file directly
    return send_file(
        pdf_stream,
        as_attachment=True,
        download_name=f"receipt_{id_transaksi}.pdf",
        mimetype="application/pdf",
    )


def generate_receipt(id_transaksi, transaksi_id, user_id):
    # Set the width to 4.5 cm (45 mm) and initialize the height with a default value
    width = 45 * 2.83  # Converting cm to points (1 cm = 28.3 points)
    base_height = 300  # Adjusted base height to fit within narrower width

    cur = mysql.connection.cursor()

    # Fetch the number of items to calculate the dynamic height
    cur.execute(
        "SELECT COUNT(*) FROM detailtransaksi WHERE transaksi_id = %s", (transaksi_id,)
    )
    total_items = cur.fetchone()[0]

    # Calculate the dynamic height based on the number of items
    item_height = 10 * total_items  # Adjusted item height to fit more on narrower page
    total_height = base_height + item_height

    # Create a BytesIO stream to hold the PDF
    pdf_stream = BytesIO()
    c = canvas.Canvas(pdf_stream, pagesize=(width, total_height))

    # Fetch transaction details
    cur.execute(
        "SELECT total_harga, bayar, kembali, tanggal_transaksi FROM transaksi WHERE id = %s",
        (transaksi_id,),
    )
    transaction = cur.fetchone()
    total_harga, bayar, kembali, created_at = transaction

    # Fetch username of the cashier from user table
    cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
    cashier = cur.fetchone()[0]

    # Centered Header
    y = total_height - 20  # Starting point from the top
    c.setFont("Helvetica-Bold", 7)  # Adjusted font size
    header_text = "DHIKA FRAME STORE"
    c.drawCentredString(width / 2, y, header_text)
    c.setFont("Helvetica", 6)
    c.drawCentredString(width / 2, y - 10, "Kp Citaman, RT.04/RW.18, Cigugur Tengah,")
    c.drawCentredString(width / 2, y - 18, "Cimahi Tengah, Kota Cimahi")
    c.drawCentredString(width / 2, y - 26, "081322205321")

    # Add a line above the transaction info
    y -= 35
    line_width = width - 10  # Full width minus padding
    c.line(5, y, line_width, y)

    # Transaction Info Section
    y -= 10  # Move down a bit after the line
    c.drawString(5, y, f"No. Bon      : {id_transaksi}")
    c.drawString(5, y - 8, f"Tanggal      : {created_at.strftime('%d-%m-%Y %H:%M:%S')}")
    c.drawString(5, y - 16, f"Kasir        : {cashier}")
    c.line(5, y - 24, line_width, y - 24)  # Full-width line

    # Table Header for Items
    y -= 30
    c.setFont("Helvetica-Bold", 5)  # Ukuran font header diubah menjadi 5
    c.drawString(5, y, "Nama Barang")
    c.drawString(55, y, "Qty")
    c.drawString(70, y, "Harga")
    c.drawString(97, y, "Subtotal")
    c.line(5, y - 8, line_width, y - 8)

    # Item Details Section
    y -= 8
    c.setFont("Helvetica", 5)  # Ukuran font item detail diubah menjadi 5
    cur.execute(
        "SELECT produk_id, jumlah, harga FROM detailtransaksi WHERE transaksi_id = %s",
        (transaksi_id,),
    )
    products = cur.fetchall()

    for product in products:
        produk_id, jumlah, harga = product
        cur.execute("SELECT nama_produk, harga FROM produk WHERE id = %s", (produk_id,))
        nama_produk, harga_satuan = cur.fetchone()

        total_harga_produk = jumlah * harga_satuan
        y -= 8  # Mengurangi jarak antar item untuk menghindari tumpang tindih

        # Wrap product name if too long
        max_chars_per_line = 15
        wrapped_nama_produk = textwrap.wrap(nama_produk, max_chars_per_line)

        # Render the product name over multiple lines if necessary
        for line in wrapped_nama_produk:
            c.drawString(5, y, line)
            y -= 6  # Mengurangi jarak antar baris untuk menghemat ruang

        # Pastikan offset untuk qty, harga, dan subtotal sesuai dengan header
        c.drawRightString(60, y + 6, str(jumlah))  # Offset untuk qty
        c.drawRightString(86, y + 6, f"{harga_satuan:,}")  # Offset untuk harga
        c.drawRightString(
            115, y + 6, f"{total_harga_produk:,}"
        )  # Offset untuk subtotal

    # Summary Section
    y -= 10
    c.line(5, y, line_width, y)
    y -= 10
    c.drawString(5, y, f"Total Item : {total_items}")
    c.drawString(5, y - 8, "Total Disc : 0")
    c.drawString(5, y - 16, f"Total Belanja: {total_harga:,}")
    c.drawString(5, y - 24, f"Tunai       : {bayar:,}")
    c.drawString(5, y - 32, f"Kembalian   : {kembali:,}")
    y -= 50
    c.line(5, y, line_width, y)

    # Centered Footer Message
    c.setFont("Helvetica-Bold", 6)
    c.drawCentredString(width / 2, y - 15, "Terima kasih atas kepercayaan Anda!")
    c.drawCentredString(width / 2, y - 25, "Senang bisa melayani kebutuhan Anda!")
    c.drawCentredString(width / 2, y - 35, "Sampai jumpa di kunjungan berikutnya!")
    c.drawCentredString(width / 2, y - 45, "Kritik & Saran: 081322205321")
    c.line(5, y - 55, line_width, y - 55)

    # Save the PDF to the BytesIO stream
    c.save()
    pdf_stream.seek(0)

    cur.close()

    return pdf_stream


# def generate_receipt(transaksi_id, user_id):
#     # Set the width to 8 cm (80 mm) and initialize the height with a default value
#     width = 90 * 2.83  # Converting cm to points (1 cm = 28.3 points)
#     base_height = 400  # Base height for the receipt header, summary, and footer

#     cur = mysql.connection.cursor()

#     # Fetch the number of items to calculate the dynamic height
#     cur.execute(
#         "SELECT COUNT(*) FROM detailtransaksi WHERE transaksi_id = %s", (transaksi_id,)
#     )
#     total_items = cur.fetchone()[0]

#     # Calculate the dynamic height based on the number of items
#     # Each item will take approximately 20 points in height
#     item_height = 20 * total_items
#     total_height = base_height + item_height

#     # Create a BytesIO stream to hold the PDF
#     pdf_stream = BytesIO()
#     c = canvas.Canvas(pdf_stream, pagesize=(width, total_height))

#     # Fetch transaction details
#     cur.execute(
#         "SELECT total_harga, bayar, kembali, tanggal_transaksi FROM transaksi WHERE id = %s",
#         (transaksi_id,),
#     )
#     transaction = cur.fetchone()
#     total_harga, bayar, kembali, created_at = transaction

#     # Fetch username of the cashier from user table
#     cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
#     cashier = cur.fetchone()[0]

#     # Centered Header
#     y = total_height - 30  # Starting point from the top
#     c.setFont("Helvetica-Bold", 10)
#     header_text = "DHIKA FRAME STORE"
#     c.drawCentredString(width / 2, y, header_text)
#     c.drawCentredString(width / 2, y - 15, "Kp Citaman, RT.04/RW.18, Cigugur Tengah,")
#     c.drawCentredString(width / 2, y - 30, "Cimahi Tengah, Kota Cimahi")
#     c.drawCentredString(width / 2, y - 45, "081322205321")

#     # Transaction Info Section
#     y -= 70
#     line_width = width - 20  # Full width minus some padding
#     c.drawString(10, y, f"No. Bon      : {transaksi_id}")
#     c.drawString(
#         10, y - 15, f"Tanggal      : {created_at.strftime('%d-%m-%Y %H:%M:%S')}"
#     )
#     c.drawString(10, y - 30, f"Kasir        : {cashier}")
#     c.line(10, y - 45, line_width, y - 45)  # Full-width line

#     # Table Header for Items
#     y -= 60
#     c.setFont("Helvetica-Bold", 9)
#     c.drawString(10, y, "Nama Barang")  # Left-aligned
#     c.drawString(120, y, "Qty")  # Right-aligned under Quantity
#     c.drawString(160, y, "Harga")  # Right-aligned under Unit Price
#     c.drawString(200, y, "Subtotal")  # Right-aligned under Subtotal
#     c.line(10, y - 15, line_width, y - 15)  # Full-width line

#     # Adjust the initial position of `y` to give enough space from the header
#     y -= 10  # Provide enough space for the first item

#     # Item Details Section
#     c.setFont("Helvetica", 9)
#     cur.execute(
#         "SELECT produk_id, jumlah, harga FROM detailtransaksi WHERE transaksi_id = %s",
#         (transaksi_id,),
#     )
#     products = cur.fetchall()

#     for product in products:
#         produk_id, jumlah, harga = product
#         cur.execute("SELECT nama_produk, harga FROM produk WHERE id = %s", (produk_id,))
#         nama_produk, harga_satuan = cur.fetchone()

#         total_harga_produk = jumlah * harga_satuan
#         y -= 20  # Adjust y for each item to avoid overlap

#         # Wrap product name if too long
#         max_chars_per_line = 20
#         wrapped_nama_produk = textwrap.wrap(nama_produk, max_chars_per_line)

#         # Render the product name over multiple lines if necessary
#         for line in wrapped_nama_produk:
#             c.drawString(10, y, line)  # Product name
#             y -= 10  # Move y position for the next line of the name (if needed)

#         c.drawRightString(140, y + 10, str(jumlah))  # Right-aligned Quantity
#         c.drawRightString(190, y + 10, f"{harga_satuan:,}")  # Right-aligned Unit price
#         # Right-aligned Total price
#         c.drawRightString(line_width, y + 10, f"{total_harga_produk:,}")

#     # Summary Section
#     y -= 10  # Adjust `y` before the summary section
#     c.line(10, y, line_width, y)  # Full-width line
#     y -= 15
#     c.drawString(10, y, f"Total Item : {total_items}")
#     c.drawString(10, y - 15, "Total Disc : 0")
#     c.drawString(10, y - 30, f"Total Belanja:            {total_harga:,}")
#     c.drawString(10, y - 45, f"Tunai   :                 {bayar:,}")
#     c.drawString(10, y - 60, f"Kembalian:                {kembali:,}")
#     y -= 75
#     c.line(10, y, line_width, y)  # Full-width line

#     # Centered Footer Message
#     c.setFont("Helvetica-Bold", 10)
#     c.drawCentredString(width / 2, y - 20, "Terima kasih atas kepercayaan Anda!")
#     c.drawCentredString(width / 2, y - 35, "Senang bisa melayani kebutuhan Anda!")
#     c.drawCentredString(width / 2, y - 50, "Sampai jumpa di kunjungan berikutnya!")
#     c.drawCentredString(width / 2, y - 70, "Kritik & Saran: 081322205321")
#     c.line(10, y - 90, line_width, y - 90)  # Full-width line

#     # Save the PDF to the BytesIO stream
#     c.save()
#     pdf_stream.seek(0)  # Go to the start of the stream

#     cur.close()

#     return pdf_stream  # Return the stream instead of a file path


# @app.route("/detailtransaksi", methods=["GET"])
# def detailtransaksi():
#     if "username" in session:  # Check if the user is logged in
#         # Assuming 'username' is the user's ID
#         user_id = session.get("username")
#         cur = mysql.connection.cursor()

#         # Get current date info
#         now = datetime.now()
#         current_year = now.year
#         current_month = now.month
#         current_day = now.day

#         # Get filter values from form (if any)
#         tahun = request.args.get("tahun")
#         bulan = request.args.get("bulan")
#         tanggal = request.args.get("tanggal")

#         # Build base query
#         query = """
#         SELECT t.*, u.username
#         FROM transaksi t
#         JOIN users u ON t.user_id = u.id
#         WHERE 1 = 1
#         """

#         # Add filters to query based on input
#         if tahun:
#             query += f" AND YEAR(t.tanggal_transaksi) = {tahun}"
#         if bulan:
#             query += f" AND MONTH(t.tanggal_transaksi) = {bulan}"
#         if tanggal:
#             query += f" AND DAY(t.tanggal_transaksi) = {tanggal}"

#         # Order by tanggal_transaksi
#         query += " ORDER BY t.tanggal_transaksi DESC"

#         # Execute the query
#         cur.execute(query)
#         transaksi_data = cur.fetchall()

#         # Pass the current date info to the template
#         return render_template(
#             "detailtransaksi.html",
#             active_page="detailtransaksi",
#             transaksi=transaksi_data,
#             user_id=user_id,
#             current_year=current_year,
#             current_month=current_month,
#             current_day=current_day,
#         )


# @app.route("/download/<path:filename>")
# def download_file(filename):
#     return send_file(filename, as_attachment=True)


@app.route("/laporan_penjualan", methods=["GET"])
def laporan_penjualan():
    cur = mysql.connection.cursor()

    tahun = request.args.get("tahun")
    bulan = request.args.get("bulan")
    tanggal = request.args.get("tanggal")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    current_year = datetime.now().year

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if tahun and not bulan and not tanggal:
            # Menampilkan penjualan per bulan
            query = """
                SELECT 
                    m.month AS bulan,
                    COALESCE(SUM(t.total_harga), 0) AS total_penjualan
                FROM 
                    (SELECT 1 AS month UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
                     UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8
                     UNION SELECT 9 UNION SELECT 10 UNION SELECT 11 UNION SELECT 12) m
                LEFT JOIN 
                    transaksi t ON MONTH(t.tanggal_transaksi) = m.month 
                                AND YEAR(t.tanggal_transaksi) = %s
                GROUP BY 
                    m.month
                ORDER BY 
                    m.month
            """
            cur.execute(query, (tahun,))
            penjualan_bulanan = cur.fetchall()
            return render_template(
                "partials/laporan_bulanan.html",
                penjualan_bulanan=penjualan_bulanan,
                tahun=tahun,
            )

        elif tahun and bulan and not tanggal:
            # Menampilkan penjualan per tanggal
            query = """
                SELECT 
                    d.day AS hari,
                    COALESCE(SUM(t.total_harga), 0) AS total_penjualan
                FROM 
                    (SELECT 1 AS day UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
                     UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8
                     UNION SELECT 9 UNION SELECT 10 UNION SELECT 11 UNION SELECT 12
                     UNION SELECT 13 UNION SELECT 14 UNION SELECT 15 UNION SELECT 16
                     UNION SELECT 17 UNION SELECT 18 UNION SELECT 19 UNION SELECT 20
                     UNION SELECT 21 UNION SELECT 22 UNION SELECT 23 UNION SELECT 24
                     UNION SELECT 25 UNION SELECT 26 UNION SELECT 27 UNION SELECT 28
                     UNION SELECT 29 UNION SELECT 30 UNION SELECT 31) d
                LEFT JOIN 
                    transaksi t ON DAY(t.tanggal_transaksi) = d.day 
                                AND MONTH(t.tanggal_transaksi) = %s
                                AND YEAR(t.tanggal_transaksi) = %s
                WHERE 
                    d.day <= DAY(LAST_DAY(%s))
                GROUP BY 
                    d.day
                ORDER BY 
                    d.day
            """
            cur.execute(query, (bulan, tahun, f"{tahun}-{bulan}-01"))
            penjualan_harian = cur.fetchall()
            bulan_nama = [
                "Januari",
                "Februari",
                "Maret",
                "April",
                "Mei",
                "Juni",
                "Juli",
                "Agustus",
                "September",
                "Oktober",
                "November",
                "Desember",
            ]
            periode = f"Bulan {bulan_nama[int(bulan)-1]} Tahun {tahun}"

            # Cek apakah semua transaksi bernilai 0
            if all(penjualan[1] == 0 for penjualan in penjualan_harian):
                return render_template("partials/data_kosong.html")

            return render_template(
                "partials/laporan_harian.html",
                penjualan_harian=penjualan_harian,
                bulan=bulan,
                tahun=tahun,
                periode=periode,
            )

        elif tahun and bulan and tanggal:
            query = """
            SELECT transaksi.id_transaksi, users.username, transaksi.total_harga, transaksi.bayar, transaksi.kembali,
                   TIME(transaksi.tanggal_transaksi) AS jam_transaksi
            FROM transaksi JOIN users ON transaksi.user_id = users.id
            WHERE YEAR(transaksi.tanggal_transaksi) = %s
                AND MONTH(transaksi.tanggal_transaksi) = %s
                AND DAY(transaksi.tanggal_transaksi) = %s
            ORDER BY transaksi.tanggal_transaksi
            """
            cur.execute(query, (tahun, bulan, tanggal))
            transaksi_detail = cur.fetchall()
            if not transaksi_detail:
                return render_template("partials/data_kosong.html")
            return render_template(
                "partials/laporan_tanggal.html", transaksi_detail=transaksi_detail
            )

        elif start_date and end_date:
            # Tambahkan 1 hari ke end_date untuk memasukkan seluruh waktu di tanggal tersebut
            query = """
            SELECT transaksi.id_transaksi, users.username, transaksi.total_harga, transaksi.bayar, transaksi.kembali,
                   transaksi.tanggal_transaksi
            FROM transaksi JOIN users ON transaksi.user_id = users.id
            WHERE transaksi.tanggal_transaksi >= %s 
            AND transaksi.tanggal_transaksi < DATE_ADD(%s, INTERVAL 1 DAY)
            ORDER BY transaksi.tanggal_transaksi
            """
            cur.execute(query, (start_date, end_date))
            transaksi_detail = cur.fetchall()
            if not transaksi_detail:
                return render_template("partials/data_kosong.html")
            return render_template(
                "partials/laporan_tanggal.html", transaksi_detail=transaksi_detail
            )

    else:
        # Untuk tampilan awal
        query = """
                    SELECT 
                transaksi.*,
                users.username 
            FROM transaksi 
            JOIN users ON transaksi.user_id = users.id 
            ORDER BY transaksi.tanggal_transaksi DESC 
            LIMIT 10
        """
        cur.execute(query)
        transaksi = cur.fetchall()
        cur.close()
        return render_template(
            "laporan_penjualan.html",
            transaksi=transaksi,
            current_year=current_year,
            active_page="laporan_penjualan",
        )


@app.route("/pdf_laporan_penjualan")
def pdf_laporan_penjualan():
    cur = mysql.connection.cursor()

    tahun = request.args.get("tahun")
    bulan = request.args.get("bulan")
    tanggal = request.args.get("tanggal")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    current_year = datetime.now().year

    penjualan_bulanan = None
    penjualan_harian = None
    transaksi_detail = None
    periode = "Tidak Ada Data"  # Default value
    total_transaksi = None

    if tahun and not bulan and not tanggal:
        # Menampilkan penjualan per bulan
        query = """
            SELECT 
                m.month AS bulan,
                COALESCE(SUM(t.total_harga), 0) AS total_penjualan
            FROM 
                (SELECT 1 AS month UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
                 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8
                 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11 UNION SELECT 12) m
            LEFT JOIN 
                transaksi t ON MONTH(t.tanggal_transaksi) = m.month 
                            AND YEAR(t.tanggal_transaksi) = %s
            GROUP BY 
                m.month
            ORDER BY 
                m.month
        """
        cur.execute(query, (tahun,))
        penjualan_bulanan = cur.fetchall()
        periode = f"Tahun {tahun}"

        # Hitung total transaksi untuk tahun ini
        total_transaksi = sum(row[1] for row in penjualan_bulanan)

    elif tahun and bulan and not tanggal:
        # Menampilkan penjualan per tanggal
        query = """
            SELECT 
                d.day AS hari,
                COALESCE(SUM(t.total_harga), 0) AS total_penjualan
            FROM 
                (SELECT 1 AS day UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
                 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8
                 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11 UNION SELECT 12
                 UNION SELECT 13 UNION SELECT 14 UNION SELECT 15 UNION SELECT 16
                 UNION SELECT 17 UNION SELECT 18 UNION SELECT 19 UNION SELECT 20
                 UNION SELECT 21 UNION SELECT 22 UNION SELECT 23 UNION SELECT 24
                 UNION SELECT 25 UNION SELECT 26 UNION SELECT 27 UNION SELECT 28
                 UNION SELECT 29 UNION SELECT 30 UNION SELECT 31) d
            LEFT JOIN 
                transaksi t ON DAY(t.tanggal_transaksi) = d.day 
                            AND MONTH(t.tanggal_transaksi) = %s
                            AND YEAR(t.tanggal_transaksi) = %s
            WHERE 
                d.day <= DAY(LAST_DAY(%s))
            GROUP BY 
                d.day
            ORDER BY 
                d.day
        """
        cur.execute(query, (bulan, tahun, f"{tahun}-{bulan}-01"))
        penjualan_harian = cur.fetchall()
        periode = f"Bulan {bulan} Tahun {tahun}"

        # Hitung total transaksi untuk bulan ini
        total_transaksi = sum(row[1] for row in penjualan_harian)

    elif tahun and bulan and tanggal:
        query = """
        SELECT transaksi.id_transaksi, users.username, transaksi.total_harga, transaksi.bayar, transaksi.kembali,
               TIME(transaksi.tanggal_transaksi) AS jam_transaksi
        FROM transaksi JOIN users ON transaksi.user_id = users.id
        WHERE YEAR(transaksi.tanggal_transaksi) = %s
            AND MONTH(transaksi.tanggal_transaksi) = %s
            AND DAY(transaksi.tanggal_transaksi) = %s
        ORDER BY transaksi.tanggal_transaksi
        """
        cur.execute(query, (tahun, bulan, tanggal))
        transaksi_detail = cur.fetchall()
        periode = f"Tanggal {tanggal}-{bulan}-{tahun}"

        # Hitung total transaksi untuk tanggal ini
        total_transaksi = sum(row[2] for row in transaksi_detail)

    elif start_date and end_date:
        query = """
        SELECT transaksi.id_transaksi, users.username, transaksi.total_harga, transaksi.bayar, transaksi.kembali, 
               transaksi.tanggal_transaksi
        FROM transaksi JOIN users ON transaksi.user_id = users.id
        WHERE transaksi.tanggal_transaksi >= %s 
        AND transaksi.tanggal_transaksi < DATE_ADD(%s, INTERVAL 1 DAY)
        ORDER BY transaksi.tanggal_transaksi
        """
        cur.execute(query, (start_date, end_date))
        transaksi_detail = cur.fetchall()
        periode = f"Dari {start_date} Ke {end_date}"

        # Hitung total transaksi untuk rentang tanggal ini
        total_transaksi = sum(row[2] for row in transaksi_detail)

    else:
        # Untuk tampilan awal atau jika tidak ada filter yang cocok
        query = """
        SELECT transaksi.id_transaksi, users.username, transaksi.total_harga, transaksi.bayar, transaksi.kembali,
               TIME(transaksi.tanggal_transaksi) AS jam_transaksi
        FROM transaksi JOIN users ON transaksi.user_id = users.id
        ORDER BY transaksi.tanggal_transaksi DESC LIMIT 10
        """
        cur.execute(query)
        transaksi_detail = cur.fetchall()
        periode = "10 Transaksi Terakhir"

        # Hitung total transaksi untuk 10 transaksi terakhir
        total_transaksi = sum(row[2] for row in transaksi_detail)

    cur.close()

    return render_template(
        "pdf_laporan_penjualan.html",
        penjualan_bulanan=penjualan_bulanan,
        penjualan_harian=penjualan_harian,
        transaksi_detail=transaksi_detail,
        periode=periode,
        current_year=current_year,
        total_transaksi=total_transaksi,
        tahun=tahun,
        bulan=bulan,
        tanggal=tanggal,
    )


@app.route("/riwayat")
def riwayat():
    cur = mysql.connection.cursor()

    filter_date = request.args.get("filter_date")

    today_date = date.today().strftime("%Y-%m-%d")

    query = """
        SELECT 
            history.user_id,
            CASE 
                WHEN history.table_name = 'produk' THEN 'barang'
                ELSE history.table_name 
            END as table_name,
            history.aksi,
            history.timestamp,
            users.username
        FROM history
        JOIN users ON history.user_id = users.id
    """

    if filter_date:
        # Validasi tanggal
        filter_date_obj = datetime.strptime(filter_date, "%Y-%m-%d").date()
        if filter_date_obj > date.today():
            flash("Tidak dapat memilih tanggal yang belum datang!", "error")
            return redirect(url_for("riwayat"))

        query += " WHERE DATE(history.timestamp) = %s"
        cur.execute(query + " ORDER BY history.timestamp DESC", (filter_date,))
    else:
        cur.execute(query + " ORDER BY history.timestamp DESC")

    histories = cur.fetchall()
    cur.close()

    return render_template(
        "riwayat.html",
        active_page="riwayat",
        histories=histories,
        today_date=today_date,  # Kirim tanggal hari ini ke template
    )


@app.route("/logout")
def logout():
    session.clear()

    flash("Anda Telah Berhasil Keluar.", "success")

    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
