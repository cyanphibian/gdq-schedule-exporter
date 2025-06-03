import requests

events = requests.get('https://tracker.gamesdonequick.com/tracker/api/v2/events').json()

for ev in events.get('results'):
    print(f"Event ID {ev['id']}: {ev['name']}")
