import logging
import csv
import os
from typing import Union, List, Dict
from datetime import datetime, timedelta
import io
import openpyxl
import dateparser  # +++ Import the new library +++

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
TOKEN = os.getenv("NEXUS_TOKEN")
DOCTORS_CSV = "doctors.csv"
APPOINTMENTS_CSV = "appointments.csv"

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONVERSATION STATES ---
AUTHENTICATING, VIEWING_OPTIONS, GETTING_DATE, POST_VIEWING_CHOICE = range(4)

# --- KEYBOARDS ---
start_over_keyboard = ReplyKeyboardMarkup(
    [["Start Over 🚀"]], resize_keyboard=True, one_time_keyboard=True
)


# --- DATA HELPER FUNCTIONS ---
def find_doctor_by_id(doctor_id: str) -> Union[dict, None]:
    """Finds a doctor's details by their ID from doctors.csv."""
    try:
        with open(DOCTORS_CSV, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row['DoctorID'].strip().lower() == doctor_id.strip().lower():
                    return row
        return None
    except FileNotFoundError:
        logger.error(f"Error: The file {DOCTORS_CSV} was not found.")
        return None


def get_appointments_for_doctor(doctor_id: str, day: datetime.date) -> List[Dict]:
    """Fetches appointment details for a specific doctor on a given day."""
    appointments_list = []
    try:
        with open(APPOINTMENTS_CSV, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row['DoctorID'].strip() == doctor_id.strip():
                    appointment_dt = datetime.fromisoformat(row['AppointmentDateTime'])
                    if appointment_dt.date() == day:
                        appointments_list.append({
                            "time": appointment_dt,
                            "patient_name": row['PatientName']
                        })
        appointments_list.sort(key=lambda x: x['time'])
        return appointments_list
    except FileNotFoundError:
        logger.error(f"Error: The file {APPOINTMENTS_CSV} was not found.")
        return []


def create_appointments_excel(appointments: List[Dict], doctor_name: str, day: datetime.date) -> io.BytesIO:
    """Creates an XLSX file in memory and returns it as a BytesIO object."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = day.strftime('%Y-%m-%d')
    sheet['A1'] = f"Appointments for Dr. {doctor_name}"
    sheet['A2'] = f"Date: {day.strftime('%A, %B %d, %Y')}"
    sheet.merge_cells('A1:B1')
    sheet['A4'] = "Appointment Time"
    sheet['B4'] = "Patient Name"
    for index, record in enumerate(appointments, start=5):
        sheet[f'A{index}'] = record['time'].strftime('%I:%M %p')
        sheet[f'B{index}'] = record['patient_name']
    for cell in ['A1', 'A4', 'B4']:
        sheet[cell].font = openpyxl.styles.Font(bold=True)
    sheet.column_dimensions['A'].width = 20
    sheet.column_dimensions['B'].width = 30
    file_stream = io.BytesIO()
    workbook.save(file_stream)
    file_stream.seek(0)
    return file_stream


# --- CONVERSATION HANDLER FUNCTIONS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Welcome to the Nexus Bot. Please enter your Doctor ID to authenticate.",
        reply_markup=ReplyKeyboardRemove()
    )
    return AUTHENTICATING


async def authenticate_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    doctor_id = update.message.text
    doctor_profile = find_doctor_by_id(doctor_id)
    if doctor_profile:
        doctor_name = doctor_profile.get('DoctorName', 'Doctor')
        context.user_data['doctor_id'] = doctor_id
        context.user_data['doctor_name'] = doctor_name
        await update.message.reply_text(f"Hello Dr. {doctor_name}, hope you are doing well!")
        return await show_viewing_options(update, context)
    else:
        await update.message.reply_text("Authentication failed. Invalid Doctor ID. Please try again.")
        return AUTHENTICATING


async def show_viewing_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("Today's Appointments", callback_data="view_today")],
        [InlineKeyboardButton("Tomorrow's Appointments", callback_data="view_tomorrow")],
        [InlineKeyboardButton("View by Specific Date", callback_data="view_specific_date")],
        [InlineKeyboardButton("End Session", callback_data="end_session")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Please choose an option:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Please choose an option:", reply_markup=reply_markup)
    return VIEWING_OPTIONS


async def view_records_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data
    today = datetime.now().date()
    date_to_view = today if choice == 'view_today' else today + timedelta(days=1)
    return await display_records(update, context, date_to_view)


# +++ MODIFIED: The prompt is now more user-friendly +++
async def ask_for_specific_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks the user to enter a date in any format."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Please enter a date. You can type 'today', 'tomorrow', 'next Tuesday', or a date like 'Sep 15' or '2025-09-15'."
    )
    return GETTING_DATE


# +++ MODIFIED: Uses dateparser for flexible date handling +++
async def get_specific_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parses the user-provided date using dateparser and displays records."""
    user_input = update.message.text
    # Use dateparser to understand human-like dates
    date_obj = dateparser.parse(user_input)

    if date_obj:
        date_to_view = date_obj.date()
        return await display_records(update, context, date_to_view)
    else:
        # If dateparser can't understand the date
        await update.message.reply_text(
            "Sorry, I couldn't understand that date. Please try again (e.g., 'tomorrow', 'Oct 5', '2025-10-05').")
        return await show_viewing_options(update, context)  # Go back to main menu


# +++ MODIFIED: Reordered the text to show details first, then the final count +++
async def display_records(update: Update, context: ContextTypes.DEFAULT_TYPE, date_to_view: datetime.date) -> int:
    doctor_id = context.user_data['doctor_id']
    doctor_name = context.user_data['doctor_name']
    appointments = get_appointments_for_doctor(doctor_id, date_to_view)
    total_appointments = len(appointments)

    date_str = date_to_view.strftime('%A, %B %d, %Y')

    if appointments:
        # Build the list of appointments first
        appointment_details = "\n".join(
            f"• {record['time'].strftime('%I:%M %p')} - {record['patient_name']}" for record in appointments
        )
        # Create the final message with the list first and count at the end
        message_text = f"Appointments for {date_str}:\n\n{appointment_details}\n\n*Total Appointments: {total_appointments}*"
    else:
        message_text = f"No appointments found for {date_str}."

    # Send the textual summary
    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(message_text, parse_mode='Markdown')

    # Send the Excel file if there are appointments
    if appointments:
        excel_file = create_appointments_excel(appointments, doctor_name, date_to_view)
        file_name = f"Appointments_{doctor_name.replace(' ', '_')}_{date_to_view}.xlsx"
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=excel_file,
            filename=file_name
        )

    # Show the follow-up menu
    keyboard = [
        [InlineKeyboardButton("See Other Records?", callback_data="view_again")],
        [InlineKeyboardButton("End Session", callback_data="end_session")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text("What would you like to do next?", reply_markup=reply_markup)

    return POST_VIEWING_CHOICE


async def end_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    end_message = "Your session has ended. Thank you!"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=end_message)
    else:
        await update.message.reply_text(end_message)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Click the button below to start a new session anytime.",
        reply_markup=start_over_keyboard
    )
    context.user_data.clear()
    return ConversationHandler.END


def main() -> None:
    application = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.Regex("^Start Over 🚀$"), start)],
        states={
            AUTHENTICATING: [MessageHandler(filters.TEXT & ~filters.COMMAND, authenticate_doctor)],
            VIEWING_OPTIONS: [
                CallbackQueryHandler(view_records_router, pattern="^view_(today|tomorrow)$"),
                CallbackQueryHandler(ask_for_specific_date, pattern="^view_specific_date$"),
                CallbackQueryHandler(end_session, pattern="^end_session$")
            ],
            GETTING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_specific_date)],
            POST_VIEWING_CHOICE: [
                CallbackQueryHandler(show_viewing_options, pattern="^view_again$"),
                CallbackQueryHandler(end_session, pattern="^end_session$"),
            ]
        },
        fallbacks=[CommandHandler("start", start)],
    )
    application.add_handler(conv_handler)
    print("Nexus Bot (Doctor Bot) is polling...")
    application.run_polling()


if __name__ == "__main__":
    main()