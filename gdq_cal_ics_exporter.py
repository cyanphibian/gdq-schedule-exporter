import argparse
import logging
import os
import pytz
import requests

from collections import namedtuple
from datetime import datetime
from icalendar import Event, Calendar

# enable logging configuration
def parse_args():
    parser = argparse.ArgumentParser(description="GDQ Schedule ICS Exporter")
    parser.add_argument(
        '--loglevel', 
        default='INFO', 
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help="Set the logging level (default: INFO)"
    )
    return parser.parse_args()

def configure_logging(loglevel):
    logging.basicConfig(level=loglevel, format='%(asctime)s - %(levelname)s - %(message)s')

# event globals — update with each event
GDQ_EVENT_URL = 'https://gamesdonequick.com/api/schedule/56'
GDQ_EVENT_NAME = 'TEST_sgdq'
GDQ_EVENT_YEAR = '2025'
INCLUDE_FATALES_ONLY_CAL = True
FATALES_NAMES_FILE = 'fatales_names.txt' # no public list — this needs to be ~manually updated~ to include folks in the event

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
        schedule_data = response.json()['schedule']
        logging.debug(f"Sample run from schedule: {schedule_data[1]}")
        return schedule_data
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching schedule from GDQ API: {e}")
        raise

def create_cal(schedule_data: list, fatales_names: set = set()) -> Calendar:
    logging.debug("Starting to process events...")
    last_updated = datetime.now(pytz.timezone('US/Eastern'))

    # if any fatales_names are provided, then filter schedule for Fatales
    filter_for_fatales = True if fatales_names else False
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
    calendar = Calendar()
    
    for run in all_runs:
        event = Event()
        
        uid = '{}||{}||{}'.format(GDQ_EVENT_YEAR, GDQ_EVENT_NAME, run.id) # consistent uid required for updates
        
        all_runners = [runner.Name for runner in run.Runners]

        if filter_for_fatales:
            fatales = [runner.Name for runner in run.Runners if runner.isFatale]
            hasNonFataleRunners = len(all_runners) > len(fatales)
            runner_str = """{}{}""".format(' & '.join(fatales), ' & more' if hasNonFataleRunners else '')
        else:
            runner_str = """{}""".format(', '.join(all_runners))
        description = """Runner{}: {}\nGame: {}\nCategory: {}\nConsole: {}\n\nFull schedule: {}""".format('s' if len(all_runners) > 1 else '', ', '.join(all_runners), run.Game, run.category, run.console, GDQ_EVENT_URL)
        description += f"\n\nLast updated (in ET): {last_updated.strftime('%Y-%m-%d %H:%M:%S')}"
        
        start_dt = datetime.fromisoformat(run.startTime)
        start_dt = start_dt.astimezone(pytz.utc)
        end_dt = datetime.fromisoformat(run.endTime)
        end_dt = end_dt.astimezone(pytz.utc)
        
        event.add('summary', '{} with {}'.format(run.Game, runner_str))
        event.add('description', description)
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)
    
        event.add('dtstamp', datetime.now(pytz.utc))
        
        event.add('uid', uid)
    
        calendar.add_component(event)

    return calendar

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


def main():
    args = parse_args()
    configure_logging(args.loglevel)

    try:
        schedule_data = get_schedule()
        
        logging.info(f"Starting ICS creation...")
        event_cal = create_cal(schedule_data) # schedule without Fatales filter
        create_ics(event_cal)
        
        if INCLUDE_FATALES_ONLY_CAL:
            logging.info(f"Starting Fatales-only ICS creation...")
            fatales_names = get_fatales_names_lowered()
            fatales_event_cal = create_cal(schedule_data, fatales_names)
            create_ics(fatales_event_cal, True)

    except Exception as e:
        logging.error(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
