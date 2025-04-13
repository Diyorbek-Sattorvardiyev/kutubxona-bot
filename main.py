import os
from flask import Flask, request, jsonify, send_file
import sqlite3
import telebot
from telebot import types
import logging
from werkzeug.utils import secure_filename
import hashlib
import datetime

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
#malumotlarni korish sqlite3 C:\Users\Pc\Desktop\Kutubxona\library.db

# Configuration     
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'books'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'images'), exist_ok=True)

# Initialize Telegram bot
BOT_TOKEN = "bot_token"  # Replace with your actual token
bot = telebot.TeleBot(BOT_TOKEN)

# Database initialization
def init_db():
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        role TEXT DEFAULT 'user',
        registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create books table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        description TEXT,
        category TEXT,
        image_path TEXT,
        pdf_path TEXT,
        added_by INTEGER,
        add_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (added_by) REFERENCES users (user_id)
    )
    ''')
    
    # Create ratings table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_id INTEGER,
        user_id INTEGER,
        rating INTEGER,
        comment TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (book_id) REFERENCES books (id),
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # Create favorites table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        book_id INTEGER,
        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (book_id) REFERENCES books (id)
    )
    ''')
    
    # Create the first superadmin if not exists
    cursor.execute("SELECT * FROM users WHERE role = 'superadmin'")
    if not cursor.fetchone():
        # Set your superadmin chat ID here
        superadmin_id = 70703567  # Replace with your actual Telegram ID
        cursor.execute('''
        INSERT INTO users (user_id, username, first_name, last_name, role) 
        VALUES (?, ?, ?, ?, ?)
        ''', (superadmin_id, 'superadmin', 'Super', 'Admin', 'superadmin'))
    
    conn.commit()
    conn.close()

# Helper function to check allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Helper function to get user role
def get_user_role(user_id):
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    conn.close()
    return result[0] if result else 'user'

# Database data access functions
def get_book_by_id(book_id):
    conn = sqlite3.connect('library.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT * FROM books WHERE id = ?
    ''', (book_id,))
    
    book = cursor.fetchone()
    conn.close()
    
    return dict(book) if book else None

def search_books(query):
    conn = sqlite3.connect('library.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT * FROM books 
    WHERE title LIKE ? OR author LIKE ?
    ''', (f'%{query}%', f'%{query}%'))
    
    books = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return books

def get_books_by_category(category):
    conn = sqlite3.connect('library.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT * FROM books WHERE category = ?
    ''', (category,))
    
    books = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return books

def get_user_favorites(user_id):
    conn = sqlite3.connect('library.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT b.* FROM books b
    JOIN favorites f ON b.id = f.book_id
    WHERE f.user_id = ?
    ''', (user_id,))
    
    books = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return books

def add_to_favorites(user_id, book_id):
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        INSERT INTO favorites (user_id, book_id) VALUES (?, ?)
        ''', (user_id, book_id))
        conn.commit()
        success = True
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
        success = False
    
    conn.close()
    return success

def remove_from_favorites(user_id, book_id):
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        DELETE FROM favorites WHERE user_id = ? AND book_id = ?
        ''', (user_id, book_id))
        conn.commit()
        success = True
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
        success = False
    
    conn.close()
    return success

def add_rating(user_id, book_id, rating, comment):
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    try:
        # Check if the user has already rated this book
        cursor.execute('''
        SELECT id FROM ratings WHERE user_id = ? AND book_id = ?
        ''', (user_id, book_id))
        existing_rating = cursor.fetchone()
        
        if existing_rating:
            # Update existing rating
            cursor.execute('''
            UPDATE ratings SET rating = ?, comment = ?, date = CURRENT_TIMESTAMP
            WHERE user_id = ? AND book_id = ?
            ''', (rating, comment, user_id, book_id))
        else:
            # Add new rating
            cursor.execute('''
            INSERT INTO ratings (user_id, book_id, rating, comment)
            VALUES (?, ?, ?, ?)
            ''', (user_id, book_id, rating, comment))
        
        conn.commit()
        success = True
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
        success = False
    
    conn.close()
    return success

def get_book_ratings(book_id):
    conn = sqlite3.connect('library.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT r.*, u.username, u.first_name, u.last_name
    FROM ratings r
    JOIN users u ON r.user_id = u.user_id
    WHERE r.book_id = ?
    ORDER BY r.date DESC
    ''', (book_id,))
    
    ratings = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return ratings

def add_book(title, author, description, category, image_path, pdf_path, added_by):
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        INSERT INTO books (title, author, description, category, image_path, pdf_path, added_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (title, author, description, category, image_path, pdf_path, added_by))
        
        book_id = cursor.lastrowid
        conn.commit()
        success = True
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
        book_id = None
        success = False
    
    conn.close()
    return success, book_id

def update_book(book_id, title, author, description, category, image_path, pdf_path):
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    try:
        # Get existing book data
        cursor.execute("SELECT image_path, pdf_path FROM books WHERE id = ?", (book_id,))
        book = cursor.fetchone()
        
        if not book:
            conn.close()
            return False
        
        # Only update paths if new ones are provided
        if not image_path:
            image_path = book[0]
        if not pdf_path:
            pdf_path = book[1]
        
        cursor.execute('''
        UPDATE books 
        SET title = ?, author = ?, description = ?, category = ?, image_path = ?, pdf_path = ?
        WHERE id = ?
        ''', (title, author, description, category, image_path, pdf_path, book_id))
        
        conn.commit()
        success = True
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
        success = False
    
    conn.close()
    return success

def delete_book(book_id):
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    try:
        # Get the book to delete its files
        cursor.execute("SELECT image_path, pdf_path FROM books WHERE id = ?", (book_id,))
        book = cursor.fetchone()
        
        if not book:
            conn.close()
            return False
        
        # Delete related records first
        cursor.execute("DELETE FROM ratings WHERE book_id = ?", (book_id,))
        cursor.execute("DELETE FROM favorites WHERE book_id = ?", (book_id,))
        
        # Delete the book
        cursor.execute("DELETE FROM books WHERE id = ?", (book_id,))
        
        conn.commit()
        
        # Delete files if they exist
        for path in book:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    logger.error(f"Error deleting file {path}: {e}")
        
        success = True
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
        success = False
    
    conn.close()
    return success

def add_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
        VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name))
        
        conn.commit()
        success = True
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
        success = False
    
    conn.close()
    return success

def set_user_role(user_id, role):
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        UPDATE users SET role = ? WHERE user_id = ?
        ''', (role, user_id))
        
        conn.commit()
        success = True
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
        success = False
    
    conn.close()
    return success

def get_all_users():
    conn = sqlite3.connect('library.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users ORDER BY registration_date DESC")
    
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return users

def get_statistics():
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    # Get total number of books
    cursor.execute("SELECT COUNT(*) FROM books")
    total_books = cursor.fetchone()[0]
    
    # Get total number of users
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    # Get total number of ratings
    cursor.execute("SELECT COUNT(*) FROM ratings")
    total_ratings = cursor.fetchone()[0]
    
    # Get top 5 books by rating
    cursor.execute('''
    SELECT b.id, b.title, AVG(r.rating) as avg_rating, COUNT(r.id) as num_ratings
    FROM books b
    LEFT JOIN ratings r ON b.id = r.book_id
    GROUP BY b.id
    ORDER BY avg_rating DESC, num_ratings DESC
    LIMIT 5
    ''')
    top_books = cursor.fetchall()
    
    # Get books by category
    cursor.execute('''
    SELECT category, COUNT(*) as count
    FROM books
    GROUP BY category
    ORDER BY count DESC
    ''')
    books_by_category = cursor.fetchall()
    
    conn.close()
    
    return {
        'total_books': total_books,
        'total_users': total_users,
        'total_ratings': total_ratings,
        'top_books': top_books,
        'books_by_category': books_by_category
    }

# Telegram bot handlers
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # Add user to database
    add_user(user_id, username, first_name, last_name)
    
    # Check user role
    role = get_user_role(user_id)
    
    # Create keyboard based on role
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    if role == 'superadmin':
        markup.row('🔍 Qidirish', '📚 Kategoriyalar')
        markup.row('⭐ Sevimlilar', '📊 Statistika')
        markup.row('👥 Foydalanuvchilar', '👤 Admin boshqarish')
    elif role == 'admin':
        markup.row('🔍 Qidirish', '📚 Kategoriyalar')
        markup.row('⭐ Sevimlilar', '📕 Kitob qo\'shish')
        markup.row('📊 Statistika')
    else:
        markup.row('🔍 Qidirish', '📚 Kategoriyalar')
        markup.row('⭐ Sevimlilar')
    
    bot.send_message(
        message.chat.id,
        f"Assalomu alaykum, {first_name}! Kutubxona botiga xush kelibsiz. "
        "Kitob qidirish uchun kitob nomi yoki muallif ismini yozing yoki tugmalardan foydalaning.",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: message.text == '🔍 Qidirish')
def search_command(message):
    bot.send_message(message.chat.id, "Kitob nomi yoki muallif ismini kiriting:")
    bot.register_next_step_handler(message, process_search)

def process_search(message):
    query = message.text
    books = search_books(query)
    
    if not books:
        bot.send_message(message.chat.id, "Hech qanday kitob topilmadi. Iltimos, boshqa so'rovni kiriting.")
        return
    
    for book in books[:10]:  # Limit to 10 results
        # Create inline keyboard for each book
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Batafsil", callback_data=f"book_{book['id']}"))
        
        # Send book info
        caption = f"📚 *{book['title']}*\n👤 *Muallif:* {book['author']}\n🔖 *Kategoriya:* {book['category']}"
        
        if book['image_path'] and os.path.exists(book['image_path']):
            with open(book['image_path'], 'rb') as photo:
                bot.send_photo(message.chat.id, photo, caption=caption, reply_markup=markup, parse_mode='Markdown')
        else:
            bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '📚 Kategoriyalar')
def categories_command(message):
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT DISTINCT category FROM books")
    categories = cursor.fetchall()
    
    conn.close()
    
    if not categories:
        bot.send_message(message.chat.id, "Hech qanday kategoriya topilmadi.")
        return
    
    markup = types.InlineKeyboardMarkup()
    for category in categories:
        if category[0]:  # Skip None categories
            markup.add(types.InlineKeyboardButton(category[0], callback_data=f"category_{category[0]}"))
    
    bot.send_message(message.chat.id, "Kategoriyani tanlang:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '⭐ Sevimlilar')
def favorites_command(message):
    user_id = message.from_user.id
    books = get_user_favorites(user_id)
    
    if not books:
        bot.send_message(message.chat.id, "Sizda hali sevimli kitoblar yo'q.")
        return
    
    for book in books:
        # Create inline keyboard for each book
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Batafsil", callback_data=f"book_{book['id']}"))
        markup.add(types.InlineKeyboardButton("❌ Sevimlilardan olib tashlash", callback_data=f"remove_favorite_{book['id']}"))
        
        # Send book info
        caption = f"📚 *{book['title']}*\n👤 *Muallif:* {book['author']}\n🔖 *Kategoriya:* {book['category']}"
        
        if book['image_path'] and os.path.exists(book['image_path']):
            with open(book['image_path'], 'rb') as photo:
                bot.send_photo(message.chat.id, photo, caption=caption, reply_markup=markup, parse_mode='Markdown')
        else:
            bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '📊 Statistika')
def statistics_command(message):
    user_id = message.from_user.id
    role = get_user_role(user_id)
    
    if role not in ['admin', 'superadmin']:
        bot.send_message(message.chat.id, "Statistika faqat adminlar uchun mavjud.")
        return
    
    stats = get_statistics()
    
    text = f"📊 *Statistika*\n\n" \
          f"📚 Kitoblar soni: {stats['total_books']}\n" \
          f"👥 Foydalanuvchilar soni: {stats['total_users']}\n" \
          f"⭐ Reytinglar soni: {stats['total_ratings']}\n\n" \
          f"🏆 *TOP 5 kitoblar:*\n"
    
    for i, (book_id, title, rating, count) in enumerate(stats['top_books'], 1):
        # Reytingni tekshirib olamiz - agar None bo'lsa 0 ga o'zgartiramiz
        formatted_rating = f"{rating:.1f}" if rating is not None else "0.0"
        text += f"{i}. {title} - {formatted_rating}⭐ ({count} baholash)\n"
    
    text += "\n📚 *Kategoriyalar bo'yicha kitoblar:*\n"
    for category, count in stats['books_by_category']:
        category_name = category if category else "Kategoriyasiz"
        text += f"{category_name}: {count} ta\n"
    
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '👥 Foydalanuvchilar')
def users_command(message):
    user_id = message.from_user.id
    role = get_user_role(user_id)
    
    if role != 'superadmin':
        bot.send_message(message.chat.id, "Bu funksiya faqat superadmin uchun mavjud.")
        return
    
    users = get_all_users()
    
    text = "👥 *Foydalanuvchilar ro'yxati:*\n\n"
    for user in users:
        text += f"ID: {user['user_id']}\n" \
               f"Username: @{user['username'] if user['username'] else 'mavjud emas'}\n" \
               f"Ism: {user['first_name']} {user['last_name'] if user['last_name'] else ''}\n" \
               f"Roli: {user['role']}\n" \
               f"Ro'yxatdan o'tgan: {user['registration_date']}\n\n"
    
    # Send in chunks if text is too long
    if len(text) > 4096:
        for x in range(0, len(text), 4096):
            bot.send_message(message.chat.id, text[x:x+4096], parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '👤 Admin boshqarish')
def manage_admins_command(message):
    user_id = message.from_user.id
    role = get_user_role(user_id)
    
    if role != 'superadmin':
        bot.send_message(message.chat.id, "Bu funksiya faqat superadmin uchun mavjud.")
        return
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Admin qo'shish", callback_data="add_admin"))
    markup.add(types.InlineKeyboardButton("➖ Adminni olib tashlash", callback_data="remove_admin"))
    
    bot.send_message(message.chat.id, "Admin boshqarish:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '📕 Kitob qo\'shish')
def add_book_command(message):
    user_id = message.from_user.id
    role = get_user_role(user_id)
    
    if role not in ['admin', 'superadmin']:
        bot.send_message(message.chat.id, "Bu funksiya faqat adminlar uchun mavjud.")
        return
    
    bot.send_message(message.chat.id, "Kitob nomini kiriting:")
    bot.register_next_step_handler(message, process_book_title)

def process_book_title(message):
    user_data = {}
    user_data['title'] = message.text
    
    bot.send_message(message.chat.id, "Muallif ismini kiriting:")
    bot.register_next_step_handler(message, process_book_author, user_data)

def process_book_author(message, user_data):
    user_data['author'] = message.text
    
    bot.send_message(message.chat.id, "Kitob tavsifini kiriting:")
    bot.register_next_step_handler(message, process_book_description, user_data)

def process_book_description(message, user_data):
    user_data['description'] = message.text
    
    bot.send_message(message.chat.id, "Kitob kategoriyasini kiriting:")
    bot.register_next_step_handler(message, process_book_category, user_data)

def process_book_category(message, user_data):
    user_data['category'] = message.text
    
    bot.send_message(message.chat.id, "Kitob rasmini yuklang yoki o'tkazib yuborish uchun 'o'tkazib yuborish' so'zini yozing:")
    bot.register_next_step_handler(message, process_book_image, user_data)

def process_book_image(message, user_data):
    if message.content_type == 'photo':
        # Get the largest photo
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save the file
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{timestamp}_{message.chat.id}.jpg"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'images', filename)
        
        with open(image_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        
        user_data['image_path'] = image_path
    else:
        user_data['image_path'] = None
    
    bot.send_message(message.chat.id, "Kitob PDF faylini yuklang:")
    bot.register_next_step_handler(message, process_book_pdf, user_data)

def process_book_pdf(message, user_data):
    if message.content_type == 'document' and message.document.mime_type == 'application/pdf':
        file_id = message.document.file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save the file
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{timestamp}_{message.chat.id}.pdf"
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'books', filename)
        
        with open(pdf_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        
        user_data['pdf_path'] = pdf_path
        
        # Add book to database
        success, book_id = add_book(
            user_data['title'], 
            user_data['author'], 
            user_data['description'], 
            user_data['category'], 
            user_data['image_path'], 
            pdf_path, 
            message.chat.id
        )
        
        if success:
            bot.send_message(message.chat.id, f"Kitob muvaffaqiyatli qo'shildi! Kitob ID: {book_id}")
        else:
            bot.send_message(message.chat.id, "Kitobni qo'shishda xatolik yuz berdi.")
    else:
        bot.send_message(message.chat.id, "PDF fayl yuklash kerak. Iltimos, qaytadan urinib ko'ring.")
        bot.register_next_step_handler(message, process_book_pdf, user_data)

# Callback query handlers
@bot.callback_query_handler(func=lambda call: call.data.startswith('book_'))
def book_callback(call):
    book_id = int(call.data.split('_')[1])
    book = get_book_by_id(book_id)
    
    if not book:
        bot.answer_callback_query(call.id, "Kitob topilmadi.")
        return
    
    # Get ratings
    ratings = get_book_ratings(book_id)
    avg_rating = sum(r['rating'] for r in ratings) / len(ratings) if ratings else 0
    
    # Create detailed book info text
    text = f"📚 *{book['title']}*\n\n" \
           f"👤 *Muallif:* {book['author']}\n" \
           f"🔖 *Kategoriya:* {book['category']}\n" \
           f"⭐ *Reyting:* {avg_rating:.1f} ({len(ratings)} baholash)\n\n" \
           f"📝 *Tavsif:*\n{book['description']}\n\n"
    
    # Create inline keyboard
    markup = types.InlineKeyboardMarkup()
    if book['pdf_path'] and os.path.exists(book['pdf_path']):
        markup.add(types.InlineKeyboardButton("📥 Yuklab olish", callback_data=f"download_{book_id}"))
    
    markup.add(types.InlineKeyboardButton("⭐ Baholash", callback_data=f"rate_{book_id}"))
    markup.add(types.InlineKeyboardButton("❤️ Sevimlilar qo'shish", callback_data=f"favorite_{book_id}"))
    
    # Add admin buttons if the user is admin or superadmin
    # Add admin buttons if the user is admin or superadmin
    user_role = get_user_role(call.from_user.id)
    if user_role in ['admin', 'superadmin']:
        markup.add(types.InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_{book_id}"))
        markup.add(types.InlineKeyboardButton("🗑️ O'chirish", callback_data=f"delete_{book_id}"))
    
    # Edit message if it has an image, otherwise send new message
    if book['image_path'] and os.path.exists(book['image_path']):
        try:
            with open(book['image_path'], 'rb') as photo:
                bot.edit_message_media(
                    types.InputMediaPhoto(photo, caption=text, parse_mode='Markdown'),
                    call.message.chat.id,
                    call.message.message_id
                )
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            with open(book['image_path'], 'rb') as photo:
                bot.send_photo(call.message.chat.id, photo, caption=text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('download_'))
def download_callback(call):
    book_id = int(call.data.split('_')[1])
    book = get_book_by_id(book_id)
    
    if not book or not book['pdf_path'] or not os.path.exists(book['pdf_path']):
        bot.answer_callback_query(call.id, "PDF fayl topilmadi.")
        return
    
    # Send the file
    with open(book['pdf_path'], 'rb') as file:
        bot.send_document(call.message.chat.id, file, caption=f"📚 {book['title']} - {book['author']}")
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('favorite_'))
def favorite_callback(call):
    book_id = int(call.data.split('_')[1])
    user_id = call.from_user.id
    
    success = add_to_favorites(user_id, book_id)
    
    if success:
        bot.answer_callback_query(call.id, "Kitob sevimlilar ro'yxatiga qo'shildi!")
    else:
        bot.answer_callback_query(call.id, "Xatolik yuz berdi yoki kitob allaqachon sevimlilar ro'yxatida.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_favorite_'))
def remove_favorite_callback(call):
    book_id = int(call.data.split('_')[2])
    user_id = call.from_user.id
    
    success = remove_from_favorites(user_id, book_id)
    
    if success:
        bot.answer_callback_query(call.id, "Kitob sevimlilar ro'yxatidan olib tashlandi!")
        # Update the message to remove the book from favorites list
        bot.delete_message(call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "Xatolik yuz berdi.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('rate_'))
def rate_callback(call):
    book_id = int(call.data.split('_')[1])
    
    # Create a rating keyboard from 1 to 5
    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = [types.InlineKeyboardButton(f"{i}⭐", callback_data=f"rating_{book_id}_{i}") for i in range(1, 6)]
    markup.add(*buttons)
    
    bot.send_message(call.message.chat.id, "Kitobni baholang (1-5):", reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('rating_'))
def rating_value_callback(call):
    parts = call.data.split('_')
    book_id = int(parts[1])
    rating = int(parts[2])
    
    # Ask for a comment
    bot.send_message(call.message.chat.id, f"Siz {rating}⭐ bahoni tanladingiz. Izoh qoldiring (yoki 'yo\'q' deb yozing):")
    bot.register_next_step_handler(call.message, process_rating_comment, book_id, rating)
    bot.answer_callback_query(call.id)

def process_rating_comment(message, book_id, rating):
    user_id = message.from_user.id
    comment = message.text if message.text.lower() != "yo'q" else ""
    
    success = add_rating(user_id, book_id, rating, comment)
    
    if success:
        bot.send_message(message.chat.id, "Rahmat! Sizning bahoyingiz qabul qilindi.")
    else:
        bot.send_message(message.chat.id, "Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('category_'))
def category_callback(call):
    category = call.data.split('_', 1)[1]
    books = get_books_by_category(category)
    
    if not books:
        bot.answer_callback_query(call.id, f"{category} kategoriyasida kitoblar topilmadi.")
        return
    
    bot.answer_callback_query(call.id)
    
    # Send message with category name
    bot.send_message(call.message.chat.id, f"📚 *{category}* kategoriyasidagi kitoblar:", parse_mode='Markdown')
    
    for book in books[:10]:  # Limit to 10 results
        # Create inline keyboard for each book
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Batafsil", callback_data=f"book_{book['id']}"))
        
        # Send book info
        caption = f"📚 *{book['title']}*\n👤 *Muallif:* {book['author']}"
        
        if book['image_path'] and os.path.exists(book['image_path']):
            with open(book['image_path'], 'rb') as photo:
                bot.send_photo(call.message.chat.id, photo, caption=caption, reply_markup=markup, parse_mode='Markdown')
        else:
            bot.send_message(call.message.chat.id, caption, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_'))
def edit_book_callback(call):
    parts = call.data.split('_')
    user_id = call.from_user.id
    role = get_user_role(user_id)
    
    if role not in ['admin', 'superadmin']:
        bot.answer_callback_query(call.id, "Bu funksiya faqat adminlar uchun mavjud.")
        return
    
    # Handle both formats: 'edit_[book_id]' and 'edit_[field]_[book_id]'
    if len(parts) == 2:  # Format is 'edit_[book_id]'
        book_id = int(parts[1])
        book = get_book_by_id(book_id)
        
        if not book:
            bot.answer_callback_query(call.id, "Kitob topilmadi.")
            return
        
        # Create a keyboard with edit options
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📝 Nom", callback_data=f"edit_title_{book_id}"))
        markup.add(types.InlineKeyboardButton("👤 Muallif", callback_data=f"edit_author_{book_id}"))
        markup.add(types.InlineKeyboardButton("📖 Tavsif", callback_data=f"edit_description_{book_id}"))
        markup.add(types.InlineKeyboardButton("🔖 Kategoriya", callback_data=f"edit_category_{book_id}"))
        markup.add(types.InlineKeyboardButton("🖼️ Rasm", callback_data=f"edit_image_{book_id}"))
        markup.add(types.InlineKeyboardButton("📄 PDF", callback_data=f"edit_pdf_{book_id}"))
        markup.add(types.InlineKeyboardButton("🔙 Orqaga", callback_data=f"book_details_{book_id}"))
        
        bot.send_message(call.message.chat.id, f"*{book['title']}* kitobini tahrirlash:", 
                        reply_markup=markup, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        
    elif len(parts) == 3:  # Format is 'edit_[field]_[book_id]'
        field = parts[1]
        book_id = int(parts[2])
        book = get_book_by_id(book_id)
        
        if not book:
            bot.answer_callback_query(call.id, "Kitob topilmadi.")
            return
            
        # Set up state for handling the edit
        if field == 'title':
            bot.send_message(call.message.chat.id, f"Joriy nom: *{book['title']}*\n\nYangi nomni kiriting:", 
                            parse_mode='Markdown')
            bot.register_next_step_handler(call.message, process_edit_title, book_id)
            
        elif field == 'author':
            bot.send_message(call.message.chat.id, f"Joriy muallif: *{book['author']}*\n\nYangi muallif nomini kiriting:", 
                            parse_mode='Markdown')
            bot.register_next_step_handler(call.message, process_edit_author, book_id)
            
        elif field == 'description':
            bot.send_message(call.message.chat.id, f"Joriy tavsif:\n*{book['description']}*\n\nYangi tavsifni kiriting:", 
                            parse_mode='Markdown')
            bot.register_next_step_handler(call.message, process_edit_description, book_id)
            
        elif field == 'category':
            # Get available categories
            categories = get_all_categories()
            markup = types.InlineKeyboardMarkup()
            
            # Add category buttons
            for category in categories:
                markup.add(types.InlineKeyboardButton(
                    f"{category['name']} {'✓' if category['id'] == book['category_id'] else ''}", 
                    callback_data=f"setcat_{book_id}_{category['id']}"
                ))
                
            markup.add(types.InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_{book_id}"))
            
            bot.send_message(call.message.chat.id, "Kategoriyani tanlang:", reply_markup=markup)
            
        elif field == 'image':
            bot.send_message(call.message.chat.id, "Yangi rasmni yuboring:")
            bot.register_next_step_handler(call.message, process_edit_image, book_id)
            
        elif field == 'pdf':
            bot.send_message(call.message.chat.id, "Yangi PDF faylni yuboring:")
            bot.register_next_step_handler(call.message, process_edit_pdf, book_id)
            
        bot.answer_callback_query(call.id)
        
    else:
        bot.answer_callback_query(call.id, "Noto'g'ri format.")
        return

# Handler functions for processing the edits

def process_edit_title(message, book_id):
    new_title = message.text
    if new_title:
        update_book_field(book_id, 'title', new_title)
        bot.send_message(message.chat.id, "Kitob nomi muvaffaqiyatli o'zgartirildi!")
        # Show book details or edit menu again
        show_book_after_edit(message.chat.id, book_id)
    else:
        bot.send_message(message.chat.id, "Noto'g'ri nom. Qayta urinib ko'ring.")

def process_edit_author(message, book_id):
    new_author = message.text
    if new_author:
        update_book_field(book_id, 'author', new_author)
        bot.send_message(message.chat.id, "Kitob muallifi muvaffaqiyatli o'zgartirildi!")
        show_book_after_edit(message.chat.id, book_id)
    else:
        bot.send_message(message.chat.id, "Noto'g'ri muallif nomi. Qayta urinib ko'ring.")

def process_edit_description(message, book_id):
    new_description = message.text
    if new_description:
        update_book_field(book_id, 'description', new_description)
        bot.send_message(message.chat.id, "Kitob tavsifi muvaffaqiyatli o'zgartirildi!")
        show_book_after_edit(message.chat.id, book_id)
    else:
        bot.send_message(message.chat.id, "Noto'g'ri tavsif. Qayta urinib ko'ring.")

def process_edit_image(message, book_id):
    if message.photo:
        # Get the largest photo (best quality)
        photo = message.photo[-1]
        file_id = photo.file_id
        
        # Download the file
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save the file and update the book record
        file_path = os.path.join(UPLOAD_FOLDER, 'images', f"{book_id}.jpg")
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        update_book_field(book_id, 'image_path', file_path)
        bot.send_message(message.chat.id, "Kitob rasmi muvaffaqiyatli o'zgartirildi!")
        show_book_after_edit(message.chat.id, book_id)
    else:
        bot.send_message(message.chat.id, "Iltimos, rasm yuboring.")

def process_edit_pdf(message, book_id):
    if message.document and message.document.mime_type == 'application/pdf':
        file_id = message.document.file_id
        
        # Download the file
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save the file and update the book record
        file_path = os.path.join(UPLOAD_FOLDER, 'books', f"{book_id}.pdf")
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        update_book_field(book_id, 'pdf_path', file_path)
        bot.send_message(message.chat.id, "Kitob PDF fayli muvaffaqiyatli o'zgartirildi!")
        show_book_after_edit(message.chat.id, book_id)
    else:
        bot.send_message(message.chat.id, "Iltimos, PDF fayl yuboring.")

# Helper function to show book details after edit
def show_book_after_edit(chat_id, book_id):
    book = get_book_by_id(book_id)
    
    if not book:
        bot.send_message(chat_id, "Kitob topilmadi.")
        return
        
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✏️ Tahrirlashni davom ettirish", callback_data=f"edit_{book_id}"))
    markup.add(types.InlineKeyboardButton("🔙 Kitob tafsilotlariga qaytish", callback_data=f"book_details_{book_id}"))
    
    bot.send_message(chat_id, f"*{book['title']}* kitobining ma'lumotlari o'zgartirildi.", 
                    reply_markup=markup, parse_mode='Markdown')

# Callback handler for category selection
@bot.callback_query_handler(func=lambda call: call.data.startswith('setcat_'))
def set_category_callback(call):
    parts = call.data.split('_')
    if len(parts) == 3:
        book_id = int(parts[1])
        category_id = int(parts[2])
        
        update_book_field(book_id, 'category_id', category_id)
        bot.answer_callback_query(call.id, "Kategoriya muvaffaqiyatli o'zgartirildi!")
        
        # Show book edit menu again
        edit_callback_data = f"edit_{book_id}"
        edit_book_callback(types.CallbackQuery(
            id=call.id,
            from_user=call.from_user,
            data=edit_callback_data,
            message=call.message
        ))
    else:
        bot.answer_callback_query(call.id, "Noto'g'ri format.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_title_'))
def edit_title_callback(call):
    book_id = int(call.data.split('_')[2])
    bot.send_message(call.message.chat.id, "Yangi kitob nomini kiriting:")
    bot.register_next_step_handler(call.message, process_edit_title, book_id)
    bot.answer_callback_query(call.id)

def process_edit_title(message, book_id):
    book = get_book_by_id(book_id)
    if not book:
        bot.send_message(message.chat.id, "Kitob topilmadi.")
        return
    
    success = update_book(
        book_id,
        message.text,  # New title
        book['author'],
        book['description'],
        book['category'],
        book['image_path'],
        book['pdf_path']
    )
    
    if success:
        bot.send_message(message.chat.id, f"Kitob nomi yangilandi: {message.text}")
    else:
        bot.send_message(message.chat.id, "Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_author_'))
def edit_author_callback(call):
    book_id = int(call.data.split('_')[2])
    bot.send_message(call.message.chat.id, "Yangi muallif ismini kiriting:")
    bot.register_next_step_handler(call.message, process_edit_author, book_id)
    bot.answer_callback_query(call.id)

def process_edit_author(message, book_id):
    book = get_book_by_id(book_id)
    if not book:
        bot.send_message(message.chat.id, "Kitob topilmadi.")
        return
    
    success = update_book(
        book_id,
        book['title'],
        message.text,  # New author
        book['description'],
        book['category'],
        book['image_path'],
        book['pdf_path']
    )
    
    if success:
        bot.send_message(message.chat.id, f"Muallif ismi yangilandi: {message.text}")
    else:
        bot.send_message(message.chat.id, "Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_description_'))
def edit_description_callback(call):
    book_id = int(call.data.split('_')[2])
    bot.send_message(call.message.chat.id, "Yangi tavsifni kiriting:")
    bot.register_next_step_handler(call.message, process_edit_description, book_id)
    bot.answer_callback_query(call.id)

def process_edit_description(message, book_id):
    book = get_book_by_id(book_id)
    if not book:
        bot.send_message(message.chat.id, "Kitob topilmadi.")
        return
    
    success = update_book(
        book_id,
        book['title'],
        book['author'],
        message.text,  # New description
        book['category'],
        book['image_path'],
        book['pdf_path']
    )
    
    if success:
        bot.send_message(message.chat.id, "Kitob tavsifi yangilandi.")
    else:
        bot.send_message(message.chat.id, "Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_category_'))
def edit_category_callback(call):
    book_id = int(call.data.split('_')[2])
    bot.send_message(call.message.chat.id, "Yangi kategoriyani kiriting:")
    bot.register_next_step_handler(call.message, process_edit_category, book_id)
    bot.answer_callback_query(call.id)

def process_edit_category(message, book_id):
    book = get_book_by_id(book_id)
    if not book:
        bot.send_message(message.chat.id, "Kitob topilmadi.")
        return
    
    success = update_book(
        book_id,
        book['title'],
        book['author'],
        book['description'],
        message.text,  # New category
        book['image_path'],
        book['pdf_path']
    )
    
    if success:
        bot.send_message(message.chat.id, f"Kitob kategoriyasi yangilandi: {message.text}")
    else:
        bot.send_message(message.chat.id, "Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_image_'))
def edit_image_callback(call):
    book_id = int(call.data.split('_')[2])
    bot.send_message(call.message.chat.id, "Yangi rasmni yuklang:")
    bot.register_next_step_handler(call.message, process_edit_image, book_id)
    bot.answer_callback_query(call.id)

def process_edit_image(message, book_id):
    book = get_book_by_id(book_id)
    if not book:
        bot.send_message(message.chat.id, "Kitob topilmadi.")
        return
    
    if message.content_type != 'photo':
        bot.send_message(message.chat.id, "Rasm yuklanmadi. Iltimos, rasmni yuklang.")
        bot.register_next_step_handler(message, process_edit_image, book_id)
        return
    
    # Get the largest photo
    file_id = message.photo[-1].file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # Save the file
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{timestamp}_{message.chat.id}.jpg"
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'images', filename)
    
    with open(image_path, 'wb') as new_file:
        new_file.write(downloaded_file)
    
    # Delete old image if exists
    if book['image_path'] and os.path.exists(book['image_path']):
        try:
            os.remove(book['image_path'])
        except Exception as e:
            logger.error(f"Error deleting old image: {e}")
    
    success = update_book(
        book_id,
        book['title'],
        book['author'],
        book['description'],
        book['category'],
        image_path,  # New image path
        book['pdf_path']
    )
    
    if success:
        bot.send_message(message.chat.id, "Kitob rasmi yangilandi.")
    else:
        bot.send_message(message.chat.id, "Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_pdf_'))
def edit_pdf_callback(call):
    book_id = int(call.data.split('_')[2])
    bot.send_message(call.message.chat.id, "Yangi PDF faylini yuklang:")
    bot.register_next_step_handler(call.message, process_edit_pdf, book_id)
    bot.answer_callback_query(call.id)

def process_edit_pdf(message, book_id):
    book = get_book_by_id(book_id)
    if not book:
        bot.send_message(message.chat.id, "Kitob topilmadi.")
        return
    
    if message.content_type != 'document' or message.document.mime_type != 'application/pdf':
        bot.send_message(message.chat.id, "PDF fayl yuklanmadi. Iltimos, PDF faylini yuklang.")
        bot.register_next_step_handler(message, process_edit_pdf, book_id)
        return
    
    file_id = message.document.file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # Save the file
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{timestamp}_{message.chat.id}.pdf"
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'books', filename)
    
    with open(pdf_path, 'wb') as new_file:
        new_file.write(downloaded_file)
    
    # Delete old PDF if exists
    if book['pdf_path'] and os.path.exists(book['pdf_path']):
        try:
            os.remove(book['pdf_path'])
        except Exception as e:
            logger.error(f"Error deleting old PDF: {e}")
    
    success = update_book(
        book_id,
        book['title'],
        book['author'],
        book['description'],
        book['category'],
        book['image_path'],
        pdf_path  # New PDF path
    )
    
    if success:
        bot.send_message(message.chat.id, "Kitob PDF fayli yangilandi.")
    else:
        bot.send_message(message.chat.id, "Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_'))
def delete_book_callback(call):
    book_id = int(call.data.split('_')[1])
    user_id = call.from_user.id
    role = get_user_role(user_id)
    
    if role not in ['admin', 'superadmin']:
        bot.answer_callback_query(call.id, "Bu funksiya faqat adminlar uchun mavjud.")
        return
    
    book = get_book_by_id(book_id)
    
    if not book:
        bot.answer_callback_query(call.id, "Kitob topilmadi.")
        return
    
    # Confirm deletion
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Ha", callback_data=f"confirm_delete_{book_id}"))
    markup.add(types.InlineKeyboardButton("❌ Yo'q", callback_data=f"cancel_delete_{book_id}"))
    
    bot.send_message(call.message.chat.id, f"*{book['title']}* kitobini o'chirishni tasdiqlaysizmi?", reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_delete_'))
def confirm_delete_callback(call):
    book_id = int(call.data.split('_')[2])
    
    success = delete_book(book_id)
    
    if success:
        bot.send_message(call.message.chat.id, "Kitob muvaffaqiyatli o'chirildi.")
        # Try to delete the original message if it exists
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
    else:
        bot.send_message(call.message.chat.id, "Kitobni o'chirishda xatolik yuz berdi.")
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_delete_'))
def cancel_delete_callback(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id, "O'chirish bekor qilindi.")

@bot.callback_query_handler(func=lambda call: call.data == 'add_admin')
def add_admin_callback(call):
    user_id = call.from_user.id
    role = get_user_role(user_id)
    
    if role != 'superadmin':
        bot.answer_callback_query(call.id, "Bu funksiya faqat superadmin uchun mavjud.")
        return
    
    bot.send_message(call.message.chat.id, "Admin qilmoqchi bo'lgan foydalanuvchi ID raqamini kiriting:")
    bot.register_next_step_handler(call.message, process_add_admin)
    bot.answer_callback_query(call.id)

def process_add_admin(message):
    try:
        user_id = int(message.text.strip())
        
        # Check if user exists
        conn = sqlite3.connect('library.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            bot.send_message(message.chat.id, "Foydalanuvchi topilmadi. Iltimos, foydalanuvchi botda ro'yxatdan o'tganligini tekshiring.")
            return
        
        success = set_user_role(user_id, 'admin')
        
        if success:
            bot.send_message(message.chat.id, f"Foydalanuvchi (ID: {user_id}) admin qilindi.")
        else:
            bot.send_message(message.chat.id, "Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")
    except ValueError:
        bot.send_message(message.chat.id, "Noto'g'ri ID. ID raqam bo'lishi kerak.")

@bot.callback_query_handler(func=lambda call: call.data == 'remove_admin')
def remove_admin_callback(call):
    user_id = call.from_user.id
    role = get_user_role(user_id)
    
    if role != 'superadmin':
        bot.answer_callback_query(call.id, "Bu funksiya faqat superadmin uchun mavjud.")
        return
    
    # Get all admins
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, last_name FROM users WHERE role = 'admin'")
    admins = cursor.fetchall()
    conn.close()
    
    if not admins:
        bot.send_message(call.message.chat.id, "Adminlar topilmadi.")
        bot.answer_callback_query(call.id)
        return
    
    # Create inline keyboard with admin list
    markup = types.InlineKeyboardMarkup()
    for admin_id, username, first_name, last_name in admins:
        display_name = f"@{username}" if username else f"{first_name} {last_name if last_name else ''}"
        markup.add(types.InlineKeyboardButton(f"{display_name} (ID: {admin_id})", callback_data=f"remove_admin_{admin_id}"))
    
    bot.send_message(call.message.chat.id, "Olib tashlamoqchi bo'lgan adminni tanlang:", reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_admin_'))
def remove_admin_user_callback(call):
    admin_id = int(call.data.split('_')[2])
    
    success = set_user_role(admin_id, 'user')
    
    if success:
        bot.send_message(call.message.chat.id, f"Foydalanuvchi (ID: {admin_id}) admin huquqlaridan mahrum qilindi.")
    else:
        bot.send_message(call.message.chat.id, "Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")
    
    bot.answer_callback_query(call.id)

# Flask routes for webhook
@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK'

@app.route('/uploads/books/<filename>')
def serve_book(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], 'books', filename))

@app.route('/uploads/images/<filename>') 
def serve_image(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], 'images', filename))

# Initialize database and set webhook
@app.before_request
def setup():
    init_db()
    # Set webhook
    try:
        bot.remove_webhook()
        bot.set_webhook(url=f"https://your-server-domain.com/{BOT_TOKEN}")
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    
    bot.remove_webhook()
    bot.polling(none_stop=True)
    
    
    # app.run(host='0.0.0.0', port=8443, debug=True)