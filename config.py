import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OWNER_CHAT_ID = TELEGRAM_CHAT_ID  # admin-only commands (scan, pause, broadcast)

SEARCH_CRITERIA = {
    "rooms": None,  # no default rooms filter — each user sets their own
    "min_price": 4500,         # סנן מודעות זולות מדי (חדרים בשיתוף)
    "max_price": 7200,
    "neighborhoods": [
        "צפון פלורנטין",
        "פלורנטין",
        "לב העיר",
        "מרכז העיר",
        "נווה צדק",
    ],
    "city": "תל אביב",
    "require_price": False,   # מודעות ללא מחיר עוברות — המשתמש יראה בעצמו
    "no_broker": True,        # סנן מודעות של מתווכים
}

# קבוצות פייסבוק לסריקה - הוסף/ערוך לפי הצורך
FACEBOOK_GROUPS = [
    "https://www.facebook.com/groups/101875683484689",
    "https://www.facebook.com/groups/458499457501175",
    "https://www.facebook.com/groups/252996637878752",
    "https://www.facebook.com/groups/333022240594651",
    "https://www.facebook.com/groups/457465901082882",
    "https://www.facebook.com/groups/287564448778602",
    "https://www.facebook.com/groups/1529488140613580",
    "https://www.facebook.com/groups/305724686290054",
    "https://www.facebook.com/groups/tlvapartment",
    "https://www.facebook.com/groups/2541381749432833",
    "https://www.facebook.com/groups/2065942027026008",
    "https://www.facebook.com/groups/743669175688649",
    "https://www.facebook.com/groups/676960712363338",
    "https://www.facebook.com/groups/jaffarent",
    "https://www.facebook.com/groups/ApartmentsTelAviv",
]

FACEBOOK_COOKIES_FILE = "facebook_cookies.json"
DB_PATH = "data/listings.db"

# כמה זמן לחכות בין סריקות (בשניות)
YAD2_POLL_INTERVAL = 15 * 60       # כל 15 דקות
FACEBOOK_POLL_INTERVAL = 30 * 60   # כל 30 דקות
