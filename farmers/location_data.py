import csv
import os
import json
from django.conf import settings

def _read_csv():
    """Helper to safely read the CSV and clean up column names."""
    path = os.path.join(settings.BASE_DIR, 'states_districts.csv')
    location_map = {}

    try:
        # Use utf-8-sig to automatically handle Windows BOM characters
        with open(path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Clean up keys in case the CSV has spaces
                cleaned_row = { (k.strip() if k else ''): (v.strip() if v else '') for k, v in row.items() }

                state = cleaned_row.get('State') or cleaned_row.get('state') or cleaned_row.get('STATE')
                district = cleaned_row.get('District') or cleaned_row.get('district') or cleaned_row.get('DISTRICT')

                if state and district:
                    if state not in location_map:
                        location_map[state] = []
                    location_map[state].append(district)

        return location_map
    except FileNotFoundError:
        print("⚠️ WARNING: states_districts.csv not found in BASE_DIR.")
        return {}
    except Exception as e:
        print(f"⚠️ ERROR reading states_districts.csv: {e}")
        return {}

def get_location_json():
    """Reads the CSV and returns a JSON string mapping States to a list of Districts."""
    location_map = _read_csv()
    return json.dumps(location_map)

def get_state_choices():
    """Returns a simple list of tuples for a standard dropdown."""
    location_map = _read_csv()
    states = sorted(location_map.keys())

    if not states:
        return [('', 'CSV File Missing or Invalid')]

    return [('', 'Select State...')] + [(s, s) for s in states]