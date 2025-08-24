import logging
import csv
import os
from typing import Union
from datetime import datetime, time, timedelta


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
TOKEN = os.getenv("ECHO_TOKEN")
SPECIALTIES_CSV = "specialties.csv"
DOCTORS_CSV = "doctors.csv"
APPOINTMENTS_CSV = "appointments.csv"
PROFILES_CSV = "profiles.csv"

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONVERSATION STATES ---
# +++ NEW STATE ADDED for post-booking choice +++
ENTRY_POINT, GETTING_NAME, GETTING_AGE, GETTING_PHONE_NEW, GETTING_PHONE_REGULAR, CHOOSING_SPECIALTY, CHOOSING_DOCTOR, CHOOSING_SLOT, POST_BOOKING = range(
    9)

# --- KEYBOARDS ---
start_over_keyboard = ReplyKeyboardMarkup(
    [["Start Over 🚀"]], resize_keyboard=True
)


# --- DATA HELPER FUNCTIONS (No changes in this section) ---
def get_specialties_from_csv():
    specialties = []
    try:
        with open(SPECIALTIES_CSV, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            next(reader, None)  # Skip header
            for row in reader:
                if row: specialties.append(row[0].strip())
        return specialties
    except FileNotFoundError:
        return []


# ... (all other data helper functions remain the same) ...
def get_doctors_by_specialty(selected_specialty):
    doctors_list = []
    try:
        with open(DOCTORS_CSV, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row['Specialty'].strip() == selected_specialty:
                    doctors_list.append(row)
        return doctors_list
    except FileNotFoundError:
        return []


def get_doctor_by_id(doctor_id_to_find: str) -> Union[dict, None]:
    try:
        with open(DOCTORS_CSV, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row['DoctorID'].strip() == doctor_id_to_find.strip():
                    return row
        return None
    except FileNotFoundError:
        return None


def generate_time_slots(day, start_hour=9, end_hour=18, interval_minutes=15):
    start_time = datetime.combine(day, time(start_hour, 0))
    end_time = datetime.combine(day, time(end_hour, 0))
    slots = []
    current_time = start_time
    while current_time < end_time:
        slots.append(current_time)
        current_time += timedelta(minutes=interval_minutes)
    return slots


def get_booked_slots(doctor_id, day):
    booked_slots = []
    try:
        with open(APPOINTMENTS_CSV, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row['DoctorID'] == doctor_id:
                    appointment_time = datetime.fromisoformat(row['AppointmentDateTime'])
                    if appointment_time.date() == day.date():
                        booked_slots.append(appointment_time)
        return booked_slots
    except FileNotFoundError:
        return []


def book_appointment(doctor_id, patient_name, slot_time):
    try:
        appointment_id = int(datetime.now().timestamp())
        new_row = {'AppointmentID': appointment_id, 'DoctorID': doctor_id, 'PatientName': patient_name,
                   'AppointmentDateTime': slot_time.isoformat()}
        fieldnames = ['AppointmentID', 'DoctorID', 'PatientName', 'AppointmentDateTime']
        try:
            with open(APPOINTMENTS_CSV, 'r') as f:
                is_empty = (f.read(1) == '')
        except FileNotFoundError:
            is_empty = True
        with open(APPOINTMENTS_CSV, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if is_empty: writer.writeheader()
            writer.writerow(new_row)
        return True
    except Exception as e:
        logger.error(f"Failed to book appointment: {e}")
        return False


def find_profile_by_phone(phone_number: str) -> Union[dict, None]:
    try:
        with open(PROFILES_CSV, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row['PhoneNumber'].strip() == phone_number.strip():
                    return row
        return None
    except FileNotFoundError:
        return None


def save_new_profile(phone_number: str, name: str, age: str) -> None:
    fieldnames = ['PhoneNumber', 'PatientName', 'Age']
    try:
        with open(PROFILES_CSV, 'r') as f:
            is_empty = (f.read(1) == '')
    except FileNotFoundError:
        is_empty = True

    with open(PROFILES_CSV, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if is_empty:
            writer.writeheader()
        writer.writerow({'PhoneNumber': phone_number, 'PatientName': name, 'Age': age})


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


# ... (Registration and login flows are unchanged) ...
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
        "Perfect. Lastly, please provide your phone number. This will be used to log you in next time.")
    return GETTING_PHONE_NEW


async def get_phone_and_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone_number = update.message.text
    name = context.user_data['name_for_reg']
    age = context.user_data['age_for_reg']
    save_new_profile(phone_number, name, age)
    context.user_data['patient_name'] = name
    await update.message.reply_text(f"Thank you, {name}! Your profile has been created.")
    return await show_specialties(update, context)


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
        await update.message.reply_text(f"Welcome back, {patient_name}!")
        return await show_specialties(update, context)
    else:
        await update.message.reply_text(
            "Sorry, we couldn't find a profile with that phone number. Please /start again and register as a first-time user.")
        return ConversationHandler.END


# --- Booking Flow Functions ---
async def show_specialties(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    specialties = get_specialties_from_csv()
    if not specialties:
        # Determine how to send the message based on whether it's a new message or a button edit
        reply_func = update.message.reply_text if update.message else update.callback_query.edit_message_text
        await reply_func("Sorry, specialties list is unavailable. Please try again later.")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(s, callback_data=f"specialty:{s}")] for s in specialties]
    keyboard.append([InlineKeyboardButton("Stop ⛔", callback_data="cancel_flow")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text("Please select a specialty for your appointment:",
                                                      reply_markup=reply_markup)
    else:
        await update.message.reply_text("Please select a specialty for your appointment:", reply_markup=reply_markup)
    return CHOOSING_DOCTOR


# ... (choose_doctor, display_slots, etc., are unchanged)
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


async def show_today_slots_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, doctor_id = query.data.split(":")
    context.user_data['selected_doctor_id'] = doctor_id
    day_to_show = datetime.now()
    await display_slots(query, context, day_to_show)
    return CHOOSING_SLOT


async def display_slots(query, context: ContextTypes.DEFAULT_TYPE, day_to_show: datetime):
    doctor_id = context.user_data['selected_doctor_id']
    selected_specialty = context.user_data['selected_specialty']
    is_today = (day_to_show.date() == datetime.now().date())
    all_slots = generate_time_slots(day_to_show)
    booked_slots = get_booked_slots(doctor_id, day_to_show)
    available_slots = [slot for slot in all_slots if
                       slot not in booked_slots and slot > datetime.now()] if is_today else [slot for slot in all_slots
                                                                                             if
                                                                                             slot not in booked_slots]
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
    day_to_show = datetime.now() if action == "doctor" else datetime.now() + timedelta(days=1)
    await display_slots(query, context, day_to_show)
    return CHOOSING_SLOT


# +++ MODIFIED: This function now presents a choice instead of ending the conversation +++
async def make_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    patient_name = context.user_data.get('patient_name')
    _, doctor_id, slot_iso_time = query.data.split(":", 2)
    slot_time = datetime.fromisoformat(slot_iso_time)
    doctor_details = get_doctor_by_id(doctor_id)
    doctor_name = doctor_details['DoctorName'] if doctor_details else "the doctor"

    if book_appointment(doctor_id, patient_name, slot_time):
        confirmation_message = (
            f"✅ Appointment Confirmed!\n\n"
            f"Patient: {patient_name}\n"
            f"Doctor: {doctor_name}\n"
            f"Time: {slot_time.strftime('%I:%M %p on %A, %b %d')}"
        )
        # Define the new choice keyboard
        keyboard = [
            [InlineKeyboardButton("Book Another Appointment", callback_data="start_over_inline")],
            [InlineKeyboardButton("Finish Session ✅", callback_data="end_session")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=confirmation_message)
        await query.message.reply_text("What would you like to do next?", reply_markup=reply_markup)
        return POST_BOOKING  # Go to the new state to wait for the user's choice
    else:
        await query.edit_message_text("Booking failed. Please try again.")
        context.user_data.clear()
        return ConversationHandler.END


# +++ NEW FUNCTION: Handles the choice after booking is complete +++
async def finish_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ends the session and shows the 'Start Over' keyboard."""
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


# --- CANCEL/END FUNCTIONS ---
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
    """Run the bot."""
    application = Application.builder().token(TOKEN).build()

    # +++ MODIFIED: Added the new POST_BOOKING state to the handler +++
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^Start Over 🚀$"), start)
        ],
        states={
            ENTRY_POINT: [
                CallbackQueryHandler(ask_for_name, pattern="^new_user$"),
                CallbackQueryHandler(ask_for_phone_regular, pattern="^regular_user$"),
            ],
            GETTING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name_and_ask_age)],
            GETTING_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age_and_ask_phone)],
            GETTING_PHONE_NEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone_and_register)],
            GETTING_PHONE_REGULAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_phone_and_proceed)],
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
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel_flow, pattern="^cancel_flow$")
        ],
    )

    application.add_handler(conv_handler)
    print("Echo Bot (Patient Bot) is polling...")
    application.run_polling()


if __name__ == "__main__":
    main()