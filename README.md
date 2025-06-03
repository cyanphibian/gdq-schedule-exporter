# GDQ Schedule ICS Exporter
This Python script does the following high-level action:
- Takes a GDQ event schedule (e.g., https://gamesdonequick.com/api/schedule/56)<sup>1</sup> and creates ICS file(s)<sup>2</sup>.

<sup>1</sup><i>Any schedule following GDQ's schedule API will work (e.g., AGDQ/SGDQ, Frost/Flame Fatales, Back to Black).</i>

<sup>2</sup><i>If a list of Fatales names are provided, then a second ICS file with only Fatales runs is created. (This is presently hard-coded for Fatales usage, but could be modified to generically apply to any subgroup within an event.)</i>

## Usage
1. Install dependencies.
2. <i>(Optional)</i> Populate `fatales_names.txt` (in same directory as `gdq_cal_ecs_exporter.py`) with list of Fatales names for event.
3. Find the event ID you want by running `python list_events.py` and copying the ID of the event you want.
4. Run script.
  1. If you want to change the log level, use the optional `--loglevel` flag.
  2. If you want to output a fatales-specific calendar as well, use the `--fatales` flag with no additional arguments.
  3. To enable Google Calendar support, follow the steps below, and add the `--gcal` flag with no additional arguments.

```python gdq_cal_ecs_exporter.py --id {EVENT_ID_HERE}```

The ICS file(s) will be saved to the script's home directory.

### Manual Google Calendar Actions
The goal with the ICS file(s) is to create a publicly consumable calendar for the GDQ schedule.

Before this is automated (see below), these manual actions must occur:
- (one-time) Create public calendar
- (for each updated ICS file generation) Import ICS file via Google Calendar UI into the appropriate public calendar


### Automatic Google Calendar Creation
This script supports automatically adding these calendars to your google calendar. To enable this,
follow the steps from [Google's Documentation](https://developers.google.com/workspace/calendar/api/quickstart/python)
up to the end of the "Authorize credentials for a desktop application" step, and make sure the `credentials.json` file is in the directory
that the script is in.
