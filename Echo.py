# Echo.py

import logging
import os
from typing import Union, List, Dict
from datetime import datetime, time, timedelta

# New Imports for Time Zone Handling
from zoneinfo import ZoneInfo

# Imports for PostgreSQL Database
import psycopg2
from dotenv import load_dotenv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# --- CONFIGURATION ---
load_dotenv()  # Load .env file for local development
TOKEN = os.getenv("ECHO_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# +++ Time Zone Configuration +++
# --- IMPORTANT: SET THIS TO YOUR LOCAL TIME ZONE ---
# Find your timezone name from: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
LOCAL_TZ_STR = "Asia/Kolkata"
# ------------------------------------------------
LOCAL_TZ = ZoneInfo(LOCAL_TZ_STR)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONVERSATION STATES ---
ENTRY_POINT, GETTING_NAME, GETTING_AGE, GETTING_PHONE_NEW, GETTING_PHONE_REGULAR, CHOOSING_SPECIALTY, CHOOSING_DOCTOR, CHOOSING_SLOT, POST_BOOKING, CONFIRM_EXISTING_PROFILE = range(
    10)

# --- KEYBOARDS ---
start_over_keyboard = ReplyKeyboardMarkup([["Start Over 🚀"]], resize_keyboard=True)


# --- DATABASE HELPER FUNCTIONS ---

def get_db_connection():
    """Establishes and returns a database connection."""
    try:
        return psycopg2.connect(DATABASE_URL)
    except psycopg2.OperationalError as e:
        logger.error(f"CRITICAL: Could not connect to the database: {e}")
        return None


def get_specialties_from_db() -> List[str]:
    conn = get_db_connection()
    if not conn: return []
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM specialties ORDER BY name;")
        specialties = [row[0] for row in cur.fetchall()]
    conn.close()
    return specialties


def get_doctors_by_specialty(selected_specialty: str) -> List[Dict]:
    conn = get_db_connection()
    if not conn: return []
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.DoctorID, d.DoctorName, d.Experience FROM doctors d
            JOIN specialties s ON d.SpecialtyID = s.id
            WHERE s.name = %s ORDER BY d.Experience DESC;
        """, (selected_specialty,))
        doctors = [{'DoctorID': r[0], 'DoctorName': r[1], 'Experience': r[2]} for r in cur.fetchall()]
    conn.close()
    return doctors


def get_doctor_by_id(doctor_id_to_find: str) -> Union[Dict, None]:
    conn = get_db_connection()
    if not conn: return None
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.DoctorName, s.name as Specialty FROM doctors d
            JOIN specialties s ON d.SpecialtyID = s.id
            WHERE d.DoctorID = %s;
        """, (int(doctor_id_to_find),))
        result = cur.fetchone()
    conn.close()
    return {'DoctorName': result[0], 'Specialty': result[1]} if result else None


def generate_time_slots(day: datetime, start_hour=9, end_hour=18, interval_minutes=15) -> List[datetime]:
    start_time = datetime.combine(day.date(), time(start_hour, 0), tzinfo=LOCAL_TZ)
    end_time = datetime.combine(day.date(), time(end_hour, 0), tzinfo=LOCAL_TZ)
    slots = []
    current_time = start_time
    while current_time < end_time:
        slots.append(current_time)
        current_time += timedelta(minutes=interval_minutes)
    return slots


def get_booked_slots(doctor_id: str, day: datetime) -> List[datetime]:
    conn = get_db_connection()
    if not conn: return []
    start_of_day_local = datetime.combine(day.date(), time.min, tzinfo=LOCAL_TZ)
    end_of_day_local = datetime.combine(day.date(), time.max, tzinfo=LOCAL_TZ)
    booked_slots = []
    with conn.cursor() as cur:
        cur.execute("""
            SELECT AppointmentDateTime FROM appointments
            WHERE DoctorID = %s AND AppointmentDateTime >= %s AND AppointmentDateTime <= %s;
        """, (int(doctor_id), start_of_day_local, end_of_day_local))
        booked_slots = [row[0].astimezone(LOCAL_TZ) for row in cur.fetchall()]
    conn.close()
    return booked_slots


def book_appointment(doctor_id: str, patient_phone: str, slot_time: datetime) -> bool:
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO appointments (DoctorID, PatientPhoneNumber, AppointmentDateTime)
                VALUES (%s, %s, %s);
            """, (int(doctor_id), patient_phone, slot_time))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to book appointment in DB: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def find_profile_by_phone(phone_number: str) -> Union[Dict, None]:
    conn = get_db_connection()
    if not conn: return None
    with conn.cursor() as cur:
        cur.execute("SELECT PatientName, Age FROM profiles WHERE PhoneNumber = %s;", (phone_number.strip(),))
        result = cur.fetchone()
    conn.close()
    return {'PatientName': result[0], 'Age': result[1]} if result else None


def save_new_profile(phone_number: str, name: str, age: str) -> None:
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO profiles (PhoneNumber, PatientName, Age)
                VALUES (%s, %s, %s) ON CONFLICT (PhoneNumber) DO UPDATE
                SET PatientName = EXCLUDED.PatientName, Age = EXCLUDED.Age;
            """, (phone_number, name, int(age)))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to save new profile to DB: {e}")
        conn.rollback()
    finally:
        conn.close()


def check_existing_appointment(patient_phone: str, doctor_id: str, day: datetime) -> Union[Dict, None]:
    conn = get_db_connection()
    if not conn: return None
    start_of_day_local = datetime.combine(day.date(), time.min, tzinfo=LOCAL_TZ)
    end_of_day_local = datetime.combine(day.date(), time.max, tzinfo=LOCAL_TZ)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT AppointmentDateTime FROM appointments
            WHERE PatientPhoneNumber = %s AND DoctorID = %s AND
                  AppointmentDateTime >= %s AND AppointmentDateTime <= %s;
        """, (patient_phone, int(doctor_id), start_of_day_local, end_of_day_local))
        result = cur.fetchone()
    conn.close()
    return {'time': result[0].astimezone(LOCAL_TZ)} if result else None


# --- CONVERSATION HANDLER FUNCTIONS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [
            InlineKeyboardButton("I'm a First-time User", callback_data="new_user"),
            InlineKeyboardButton("I'm a Regular User", callback_data="regular_user"),
        ],
        [InlineKeyboardButton("Stop ⛔", callback_data="cancel_flow")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome to the Echo Appointment Bot! Please let us know if you are a new or regular user.",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text("Please choose an option:", reply_markup=reply_markup)
    return ENTRY_POINT


async def ask_for_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Great! To register your profile, please tell me your full name.")
    return GETTING_NAME


async def get_name_and_ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['name_for_reg'] = update.message.text
    await update.message.reply_text("Thank you. Now, please enter your age.")
    return GETTING_AGE


async def get_age_and_ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['age_for_reg'] = update.message.text
    await update.message.reply_text(
        "Perfect. Lastly, please provide your phone number. This will be used to create your account.")
    return GETTING_PHONE_NEW


async def get_phone_and_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone_number = update.message.text
    profile = find_profile_by_phone(phone_number)

    if profile:
        context.user_data['existing_profile'] = profile
        context.user_data['existing_phone'] = phone_number
        patient_name = profile['PatientName']
        keyboard = [
            [
                InlineKeyboardButton("Yes, continue with this account", callback_data="continue_yes"),
                InlineKeyboardButton("No, use a different number", callback_data="continue_no"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"This phone number is already registered to '{patient_name}'.\n\nDo you want to continue with this account?",
            reply_markup=reply_markup
        )
        return CONFIRM_EXISTING_PROFILE
    else:
        name = context.user_data['name_for_reg']
        age = context.user_data['age_for_reg']
        save_new_profile(phone_number, name, age)
        context.user_data['patient_name'] = name
        context.user_data['patient_phone'] = phone_number
        await update.message.reply_text(f"Thank you, {name}! Your profile has been created.")
        return await show_specialties(update, context)


async def handle_existing_profile_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == 'continue_yes':
        profile = context.user_data['existing_profile']
        phone = context.user_data['existing_phone']
        patient_name = profile['PatientName']
        context.user_data['patient_name'] = patient_name
        context.user_data['patient_phone'] = phone
        await query.edit_message_text(f"Welcome back, {patient_name}!")
        return await show_specialties(update, context)
    else:  # continue_no
        await query.edit_message_text("Understood. Please enter a new, unregistered phone number.")
        return GETTING_PHONE_NEW


async def ask_for_phone_regular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Welcome back! Please enter your registered phone number to log in.")
    return GETTING_PHONE_REGULAR


async def check_phone_and_proceed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone_number = update.message.text
    profile = find_profile_by_phone(phone_number)
    if profile:
        patient_name = profile['PatientName']
        context.user_data['patient_name'] = patient_name
        context.user_data['patient_phone'] = phone_number
        await update.message.reply_text(f"Welcome back, {patient_name}!")
        return await show_specialties(update, context)
    else:
        await update.message.reply_text(
            "This phone number is not registered. Please try again, or /start to register as a new user.")
        return GETTING_PHONE_REGULAR


async def show_specialties(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    specialties = get_specialties_from_db()
    if not specialties:
        reply_func = update.message.reply_text if update.message else update.callback_query.edit_message_text
        await reply_func("Sorry, specialties list is unavailable. Please try again later.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(s, callback_data=f"specialty:{s}")] for s in specialties]
    keyboard.append([InlineKeyboardButton("Stop ⛔", callback_data="cancel_flow")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text("Please select a specialty:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Please select a specialty:", reply_markup=reply_markup)
    return CHOOSING_DOCTOR


async def choose_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    selected_specialty = query.data.split(":")[1]
    context.user_data['selected_specialty'] = selected_specialty
    doctors = get_doctors_by_specialty(selected_specialty)
    if not doctors:
        await query.edit_message_text(text=f"Sorry, no doctors found for {selected_specialty}.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"{d['DoctorName']} ({d['Experience']} years exp.)",
                                      callback_data=f"doctor:{d['DoctorID']}")] for d in doctors]
    keyboard.append([InlineKeyboardButton("Stop ⛔", callback_data="cancel_flow")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="Please choose a doctor:", reply_markup=reply_markup)
    return CHOOSING_SLOT


async def display_slots(query, context: ContextTypes.DEFAULT_TYPE, day_to_show: datetime):
    """MODIFIED: The double-booking check has been REMOVED from this function."""
    doctor_id = context.user_data['selected_doctor_id']
    selected_specialty = context.user_data['selected_specialty']
    now_aware = datetime.now(LOCAL_TZ)
    is_today = (day_to_show.date() == now_aware.date())

    all_slots = generate_time_slots(day_to_show)
    booked_slots = get_booked_slots(doctor_id, day_to_show)

    available_slots = [
        slot for slot in all_slots
        if slot not in booked_slots and (slot > now_aware if is_today else True)
    ]
    keyboard = []
    day_string = "for today" if is_today else "for tomorrow"
    if available_slots:
        message_text = f"Please select an available time slot {day_string}:"
        row = []
        for slot in available_slots:
            row.append(
                InlineKeyboardButton(slot.strftime("%I:%M %p"), callback_data=f"book:{doctor_id}:{slot.isoformat()}"))
            if len(row) == 2: keyboard.append(row); row = []
        if row: keyboard.append(row)
    else:
        message_text = f"No available slots for this doctor {day_string}."
    if is_today:
        keyboard.append([InlineKeyboardButton("Book for Tomorrow ➡️", callback_data=f"next_day:{doctor_id}")])
    else:
        keyboard.append([
            InlineKeyboardButton("⬅️ Show Today's Slots", callback_data=f"show_today:{doctor_id}"),
            InlineKeyboardButton("Show Other Doctors", callback_data=f"specialty:{selected_specialty}")
        ])
    keyboard.append([InlineKeyboardButton("Stop ⛔", callback_data="cancel_flow")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=message_text, reply_markup=reply_markup)


async def choose_slot_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action, doctor_id = query.data.split(":")
    context.user_data['selected_doctor_id'] = doctor_id
    now_aware = datetime.now(LOCAL_TZ)
    day_to_show = now_aware if action == "doctor" else now_aware + timedelta(days=1)
    await display_slots(query, context, day_to_show)
    return CHOOSING_SLOT


async def show_today_slots_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, doctor_id = query.data.split(":")
    context.user_data['selected_doctor_id'] = doctor_id
    day_to_show = datetime.now(LOCAL_TZ)
    await display_slots(query, context, day_to_show)
    return CHOOSING_SLOT


async def make_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """MODIFIED: Double-booking check is now performed here, right before booking."""
    query = update.callback_query
    await query.answer()
    patient_name = context.user_data.get('patient_name')
    patient_phone = context.user_data.get('patient_phone')
    _, doctor_id, slot_iso_time = query.data.split(":", 2)
    slot_time = datetime.fromisoformat(slot_iso_time)

    # --- NEW: Double Booking Check ---
    existing_appointment = check_existing_appointment(patient_phone, doctor_id, slot_time)
    if existing_appointment:
        doctor_details = get_doctor_by_id(doctor_id)
        doctor_name = doctor_details['DoctorName']
        booked_time = existing_appointment['time'].strftime('%I:%M %p')
        day_str = slot_time.strftime('%A, %b %d')

        message = (
            f"⚠️ **Appointment Not Booked!**\n\n"
            f"You already have an appointment with **{doctor_name}** on this day.\n\n"
            f"**Existing Booking Details:**\n"
            f"**Time:** {booked_time}\n"
            f"**Date:** {day_str}"
        )
        keyboard = [[InlineKeyboardButton("Finish Session ✅", callback_data="end_session")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=message, reply_markup=reply_markup, parse_mode='Markdown')
        return POST_BOOKING
    # --- End of Check ---

    doctor_details = get_doctor_by_id(doctor_id)
    doctor_name = doctor_details['DoctorName']
    doctor_specialty = doctor_details['Specialty']

    if book_appointment(doctor_id, patient_phone, slot_time):
        confirmation_message = (
            f"✅ **Appointment Confirmed!**\n\n"
            f"**Patient:** {patient_name}\n"
            f"**Doctor:** {doctor_name}\n"
            f"**Specialty:** {doctor_specialty}\n"
            f"**Time:** {slot_time.astimezone(LOCAL_TZ).strftime('%I:%M %p on %A, %b %d')}"
        )
        keyboard = [
            [InlineKeyboardButton("Book Another Appointment", callback_data="start_over_inline")],
            [InlineKeyboardButton("Finish Session ✅", callback_data="end_session")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=confirmation_message, parse_mode='Markdown')
        await query.message.reply_text("What would you like to do next?", reply_markup=reply_markup)
        return POST_BOOKING
    else:
        await query.edit_message_text("Booking failed. Please try again.")
        context.user_data.clear()
        return ConversationHandler.END


async def finish_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Thank you for using the Appointment Bot!")
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="You can start over anytime by clicking the button below.",
        reply_markup=start_over_keyboard
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Process cancelled.")
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="You can start over anytime by clicking the button below.",
        reply_markup=start_over_keyboard
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Operation cancelled. You can start over anytime by clicking the button below.",
        reply_markup=start_over_keyboard
    )
    context.user_data.clear()
    return ConversationHandler.END


def main() -> None:
    application = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.Regex("^Start Over 🚀$"), start)],
        states={
            ENTRY_POINT: [
                CallbackQueryHandler(ask_for_name, pattern="^new_user$"),
                CallbackQueryHandler(ask_for_phone_regular, pattern="^regular_user$"),
            ],
            GETTING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name_and_ask_age)],
            GETTING_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age_and_ask_phone)],
            GETTING_PHONE_NEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone_and_register)],
            GETTING_PHONE_REGULAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_phone_and_proceed)],
            CONFIRM_EXISTING_PROFILE: [
                CallbackQueryHandler(handle_existing_profile_confirmation, pattern="^continue_.*$")],
            CHOOSING_DOCTOR: [CallbackQueryHandler(choose_doctor, pattern="^specialty:.*$")],
            CHOOSING_SLOT: [
                CallbackQueryHandler(choose_slot_router, pattern="^(doctor|next_day):.*$"),
                CallbackQueryHandler(make_booking, pattern="^book:.*$"),
                CallbackQueryHandler(show_today_slots_again, pattern="^show_today:.*$"),
                CallbackQueryHandler(choose_doctor, pattern="^specialty:.*$"),
            ],
            POST_BOOKING: [
                CallbackQueryHandler(show_specialties, pattern="^start_over_inline$"),
                CallbackQueryHandler(finish_session, pattern="^end_session$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel_flow, pattern="^cancel_flow$")],
    )
    application.add_handler(conv_handler)
    print("Echo Bot (Patient Bot) is polling...")
    application.run_polling()


if __name__ == "__main__":
    main()