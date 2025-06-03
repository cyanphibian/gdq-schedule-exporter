from __future__ import annotations
import argparse
import base64
import logging
import os
import pytz
import requests
import typing

from collections import namedtuple
from datetime import datetime
from icalendar import Event, Calendar
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.http import BatchHttpRequest
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

if typing.TYPE_CHECKING:
    from googleapiclient._apis.calendar.v3 import EventResource

# enable logging configuration
def parse_args():
    parser = argparse.ArgumentParser(description="GDQ Schedule ICS Exporter")
    parser.add_argument(
        '--loglevel',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help="Set the logging level (default: INFO)"
    )
    parser.add_argument(
        '--id',
        required=True,
        type=int,
        help="The event ID to run for"
    )
    parser.add_argument(
        '--fatales',
        action='store_true',
        help="Create a Fatales-only calendar(default: False)"
    )
    return parser.parse_args()

def configure_logging(loglevel):
    logging.basicConfig(level=loglevel, format='%(asctime)s - %(levelname)s - %(message)s')

# Static Globals - do not change
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events.owned",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist",
    "https://www.googleapis.com/auth/calendar.calendars",
    "https://www.googleapis.com/auth/calendar.acls",
]

# event globals — update with each event
FATALES_NAMES_FILE = 'fatales_names.txt' # no public list — this needs to be ~manually updated~ to include folks in the event

# Templates, do not touch
global GDQ_EVENT_ID
GDQ_EVENT_ID: int
global GENERAL_CAL_NAME
GENERAL_CAL_NAME: str = ""
global GDQ_EVENT_YEAR
GDQ_EVENT_YEAR: str = ""
global GDQ_EVENT_NAME
GDQ_EVENT_NAME: str = ""
global GENERAL_CAL_ID
GENERAL_CAL_ID: str = ""
global FATALES_CAL_ID
FATALES_CAL_ID: str = ""
global EVENT_DATA
EVENT_DATA: dict = {}
global EVENT_TIMEZONE
EVENT_TIMEZONE: str = ""
global INCLUDE_FATALES_ONLY_CAL
INCLUDE_FATALES_ONLY_CAL: bool = False
global GENERAL_GCAL_EVENTS
GENERAL_GCAL_EVENTS: list[EventResource] = []
global FATALES_GCAL_EVENTS
FATALES_GCAL_EVENTS: list[EventResource] = []

# functions
def read_file_as_list(file_name):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, file_name) # assumes file is in same dir as script
    try:
        with open(file_path, 'r') as file:
            return [line.strip() for line in file.readlines()]
    except FileNotFoundError:
        logging.error(f"The file {file_name} was not found.")
        raise
    except Exception as e:
        logging.error(f"Error reading the file {file_name}: {e}")
        raise

def get_fatales_names_lowered() -> set:
    fatales_names = read_file_as_list(FATALES_NAMES_FILE)
    return {name.lower() for name in fatales_names}

def get_schedule() -> list:
    logging.debug("Fetching GDQ event data from API...")
    try:
        response = requests.get(GDQ_EVENT_URL)
        response.raise_for_status()
        logging.debug(f"Successfully fetched schedule. Status Code: {response.status_code}")
        global EVENT_DATA
        EVENT_DATA = response.json()
        schedule_data = EVENT_DATA['schedule']
        logging.debug(f"Sample run from schedule: {schedule_data[1]}")
        return schedule_data
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching schedule from GDQ API: {e}")
        raise

def find_or_create_google_calendars(service: Resource, timezone: str):
    global FATALES_CAL_ID
    global GENERAL_CAL_ID
    global GENERAL_GCAL_EVENTS
    global FATALES_GCAL_EVENTS
    page_token = None
    cal_list = service.calendarList().list(pageToken=page_token).execute()
    for entry in cal_list['items']:
        if not GENERAL_CAL_ID and entry['summary'] == GENERAL_CAL_NAME:
            print(f"Found General calendar: {entry['id']}")

            GENERAL_CAL_ID = entry['id']
            continue
        elif not FATALES_CAL_ID and entry['summary'] == FATALES_CAL_NAME:
            print(f"Found Fatales Calendar: {entry['id']}")
            FATALES_CAL_ID = entry['id']
            continue

    acl = {
        'scope': {
            'type': 'default'
        },
        'role': 'reader',
    }
    if not GENERAL_CAL_ID:
        cal = {
            'summary': GENERAL_CAL_NAME,
            'timeZone': timezone
        }
        new_cal = service.calendars().insert(body=cal).execute()
        service.acl().insert(calendarId=new_cal['id'], body=acl).execute()
        logging.info(f"Did not find a calendar for {GDQ_EVENT_NAME} {GDQ_EVENT_YEAR}, created one!")
        GENERAL_CAL_ID = new_cal['id']
    else:
        # If we have an existing calendar, fetch all events from it for updates later.
        req = service.events().list(calendarId=GENERAL_CAL_ID)
        res = req.execute()
        GENERAL_GCAL_EVENTS.extend(res['items'])
        if res.get('nextPageToken'):
            req = service.events().list_next(previous_request=req, previous_response=res)
            res = req.execute()
            GENERAL_GCAL_EVENTS.extend(res['items'])

    if not FATALES_CAL_ID and INCLUDE_FATALES_ONLY_CAL:
        cal = {
            'summary': FATALES_CAL_NAME,
            'timeZone': timezone
        }
        new_cal = service.calendars().insert(body=cal).execute()
        service.acl().insert(calendarId=new_cal['id'], body=acl).execute()
        logging.info(f"Did not find a fatales calendar for {GDQ_EVENT_NAME} {GDQ_EVENT_YEAR}, created one!")
        FATALES_CAL_ID = new_cal['id']
    elif FATALES_CAL_ID and INCLUDE_FATALES_ONLY_CAL:
        req = service.events().list(calendarId=FATALES_CAL_ID)
        res = req.execute()
        FATALES_GCAL_EVENTS.extend(res['items'])
        if res.get('nextPageToken'):
            req = service.events().list_next(previous_request=req, previous_response=res)
            res = req.execute()
            FATALES_GCAL_EVENTS.extend(res['items'])


    page_token = cal_list.get('nextPageToken')

def create_cal(schedule_data: list, cal_service: Resource, fatales_names: set = set()) -> tuple[Calendar, BatchHttpRequest]:
    global GENERAL_CAL_ID
    global FATALES_CAL_ID

    logging.debug("Starting to process events...")
    last_updated = datetime.now(pytz.timezone('US/Eastern'))

    # if any fatales_names are provided, then filter schedule for Fatales
    filter_for_fatales = True if fatales_names else False
    cal_id = FATALES_CAL_ID if fatales_names else GENERAL_CAL_ID
    # Pre-existing event IDs that are already on the calendar
    events = FATALES_GCAL_EVENTS if fatales_names else GENERAL_GCAL_EVENTS
    event_ids = [e['id'] for e in events]
    logging.debug(f"Filtering for Fatales: {filter_for_fatales}")

    Speedrun = namedtuple('Speedrun', ['Game', 'hasFatale', 'Runners', 'startTime', 'endTime', 'id', 'category', 'console'])
    Runner = namedtuple('Runner', ['Name', 'isFatale'])

    all_runs = []
    for event in schedule_data:
        logging.debug(f"Begin processing event: {event}")

        if event['type'] == 'interview':
            continue # skip
        runners = [Runner(runner['name'], runner['name'].lower() in fatales_names) for runner in event['runners']]
        hasFatale = any([runner.isFatale for runner in runners])
        run = Speedrun(event['name'], hasFatale, runners, event['starttime'], event['endtime'], event['id'], event['category'], event['console'])
        if run.Game == 'Sleep' and ('Tech Crew' in (runner.Name for runner in run.Runners) or 'Faith' in (runner.Name for runner in run.Runners)):
            continue # skip
        all_runs.append(run)

    logging.debug(f"All runs processed: {all_runs}")

    if filter_for_fatales:
        non_run_names = set(['pre-show', 'finale', 'the checkpoint']) # filter out non-runs too
        all_runs = [run for run in all_runs if run.hasFatale and run.Game.lower() not in non_run_names]
        logging.debug(f"Runs after Fatales filter: {all_runs}")

    logging.debug("Starting to create calendar object...")
    logging.debug("Fetching")
    calendar = Calendar()
    gcal_batch = cal_service.new_batch_http_request()

    for run in all_runs:
        gcal_event = {
            'status': 'confirmed',
            'transparency': 'transparent',
            'visibility': 'public',
            'start': {},
            'end': {},
        }
        event = Event()

        icalUid = '{}||{}||{}'.format(GDQ_EVENT_YEAR, GDQ_EVENT_NAME, run.id) # consistent uid required for updates
        # Google Calendar API only allows event IDs in this character set.
        # Therefore, encode the above ID with b32Hex to ensure they are identical
        eventId = base64.b32hexencode(bytes(icalUid, 'UTF-8')).decode('UTF-8').replace('=', '').lower()

        all_runners = [runner.Name for runner in run.Runners]

        if filter_for_fatales:
            fatales = [runner.Name for runner in run.Runners if runner.isFatale]
            hasNonFataleRunners = len(all_runners) > len(fatales)
            runner_str = """{}{}""".format(' & '.join(fatales), ' & more' if hasNonFataleRunners else '')
        else:
            runner_str = """{}""".format(', '.join(all_runners))
        description = """Runner{}: {}\nGame: {}\nCategory: {}\nConsole: {}\n\nFull schedule: {}""".format('s' if len(all_runners) > 1 else '', ', '.join(all_runners), run.Game, run.category, run.console, GDQ_EVENT_URL)
        description += f"\n\nLast updated (in ET): {last_updated.strftime('%Y-%m-%d %H:%M:%S')}"
        summary = '{} with {}'.format(run.Game, runner_str)

        start_dt = datetime.fromisoformat(run.startTime)
        start_dt = start_dt.astimezone(pytz.utc)
        end_dt = datetime.fromisoformat(run.endTime)
        end_dt = end_dt.astimezone(pytz.utc)

        event.add('summary', summary)
        gcal_event['summary'] = summary

        event.add('description', description)
        gcal_event['description'] = description

        event.add('dtstart', start_dt)
        gcal_event['start']['dateTime'] = run.startTime

        event.add('dtend', end_dt)
        gcal_event['end']['dateTime'] = run.endTime

        event.add('dtstamp', datetime.now(pytz.utc))

        event.add('uid', icalUid)
        gcal_event['id'] = eventId

        calendar.add_component(event)
        if eventId in event_ids:
            # If pre-existing event, use `update()` instead of `insert()` to update the event.
            # Note that we don't check if the event is the exact same content-wise, so we always update
            # even if nothing has changed.
            # While we could also use `patch()`, the google API documentation recommends using `get()` + `update()` instead,
            # as `patch()` consumes 3 quota units, vs just 2 for the get+update.
            # `patch()` would allow us to only send partial updates of changed events, though.
            gcal_batch.add(cal_service.events().update(calendarId=cal_id, eventId=eventId, body=gcal_event))
        else:
            gcal_batch.add(cal_service.events().insert(calendarId=cal_id, body=gcal_event))

    return calendar, gcal_batch

def create_ics(calendar: Calendar, filter_for_fatales: bool = False) -> None:
    file_name = "{}-{}{}.ics".format(GDQ_EVENT_YEAR, GDQ_EVENT_NAME, "-fatales" if filter_for_fatales else "")
    try:
        with open(file_name, 'w', encoding='utf-8-sig') as f:
            f.write(calendar.to_ical().decode('utf-8-sig'))
        logging.info(f"ICS file has been created successfully: {file_name}")

        # used in some debugging around Google Calendar seemingly requiring a BOM to handle encoding correctly (e.g. avoiding "Pokémon" -> "PokÃ©mon")
        with open(file_name, "rb") as file:
            beginning = file.read(4)
            bom = ""
            # The order of these if-statements is important
            # otherwise UTF32 LE may be detected as UTF16 LE as well
            if beginning == b'\x00\x00\xfe\xff':
                bom = "UTF-32 BE"
            elif beginning == b'\xff\xfe\x00\x00':
                bom = "UTF-32 LE"
            elif beginning[0:3] == b'\xef\xbb\xbf':
                bom = "UTF-8"
            elif beginning[0:2] == b'\xff\xfe':
                bom = "UTF-16 LE"
            elif beginning[0:2] == b'\xfe\xff':
                bom = "UTF-16 BE"
            else:
                bom = "Unknown or no BOM"
            logging.debug(f"BOM check result: {bom}")
    except Exception as e:
        logging.error(f"Error writing to ICS file: {e}")
        raise

def google_login():
    """
        Implements the authentication logic from the following quickstart example:
        https://github.com/googleworkspace/python-samples/blob/main/calendar/quickstart/quickstart.py
    """
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", GOOGLE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", GOOGLE_SCOPES)
            creds = flow.run_local_server(port=8081, open_browser=False)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return creds


def main():
    global EVENT_DATA
    global GDQ_EVENT_ID
    global GDQ_EVENT_NAME
    global GDQ_EVENT_YEAR
    global GDQ_EVENT_URL
    global GENERAL_CAL_NAME
    global FATALES_CAL_NAME
    global EVENT_TIMEZONE
    global INCLUDE_FATALES_ONLY_CAL
    args = parse_args()
    configure_logging(args.loglevel)
    INCLUDE_FATALES_ONLY_CAL = args.fatales
    GDQ_EVENT_ID = args.id
    GDQ_EVENT_URL = f'https://gamesdonequick.com/api/schedule/{GDQ_EVENT_ID}'


    try:
        schedule_data = get_schedule()
        # Set timezone, which we will need for events and creating calendars.
        EVENT_TIMEZONE = EVENT_DATA['event']['timezone']
        # Set all the global variables we'll need throughout this script
        event_name_words = [ word for word in EVENT_DATA['event']['name'].split()]
        # Set event name to full event name if it's a fatales event
        # and force-skip the fatales-specific calendar(since it's a fatales event)
        if event_name_words[1] == "Fatales":
            GDQ_EVENT_NAME = " ".join(event_name_words[:1])
            INCLUDE_FATALES_ONLY_CAL = False
        else:
            # if a non-fatales event, use the shortened form of the name.
            # Don't take the last word since that's the year.
            # Also don't force-disable the
            GDQ_EVENT_NAME = "".join([c[0].upper() for c in event_name_words[:-1]])


        # Pad the event year to 4 digits if it's only a 2-digit year
        # Such as the Speedrun Stage @ PAX events, which use 2-digit years
        if len(event_name_words[-1]) == 2:
            GDQ_EVENT_YEAR = str(2000 + int(event_name_words[-1]))
        else:
            GDQ_EVENT_YEAR = event_name_words[-1]

        # Set calendar names based on above
        GENERAL_CAL_NAME = f'{GDQ_EVENT_NAME} {GDQ_EVENT_YEAR} Schedule'
        FATALES_CAL_NAME = f'{GENERAL_CAL_NAME} — Fatales Runs!'

        creds = google_login()
        cal_service = build("calendar", "v3", credentials=creds)
        find_or_create_google_calendars(cal_service, EVENT_TIMEZONE)

        logging.info("Starting ICS creation...")
        event_cal, event_batch = create_cal(schedule_data, cal_service=cal_service) # schedule without Fatales filter
        create_ics(event_cal)
        logging.info("Creating general schedule with Google Calendar...")
        event_batch.execute()

        if INCLUDE_FATALES_ONLY_CAL:
            logging.info("Starting Fatales-only ICS creation...")
            fatales_names = get_fatales_names_lowered()
            fatales_event_cal, fatales_event_batch = create_cal(schedule_data, cal_service, fatales_names)
            create_ics(fatales_event_cal, True)
            logging.info("Creating Fatales-only schedule with Google Calendar...")
            fatales_event_batch.execute()

    except Exception as e:
        logging.error(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
